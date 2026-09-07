"""Works, drafts, commands, evaluation, history.

    GET    /api/works                        list works the user can see
    POST   /api/works                        create (blank or from a starter)
    GET    /api/works/{id}                   metadata + permissions
    GET    /api/works/{id}/draft             head state (model, blocks, N/A, revision)
    POST   /api/works/{id}/commands          apply one command at base_revision (409 on conflict)
    GET    /api/works/{id}/evaluation        findings + completion + readiness for the head
    POST   /api/works/{id}/adjudications     accept/dismiss a candidate finding (rejects stale)
    GET    /api/works/{id}/history           revision log
    GET    /api/works/{id}/outline           outline with per-section completion (sidebar)
    PUT    /api/works/{id}/permissions       set a user's level on the work (work admin)

Autosave is simply "the client sends commands as the author types"; every
command is durable and revisioned, so there is no separate backup path.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, current_user, require_work, work_level
from protocol_studio.db import Adjudication, Draft, Permission, Revision, User, Work, get_session
from protocol_studio.engine.commands import Command, CommandError, ConflictError, apply_command
from protocol_studio.engine.evaluation import evaluate
from protocol_studio.engine.state import DraftState
from protocol_studio.library import starter_state
from ps_model.outline import OUTLINE

router = APIRouter(prefix="/api/works", tags=["works"])


# ----------------------------------------------------------------------------- helpers


def _work_json(db: Session, user: User, w: Work) -> dict[str, Any]:
    d = db.get(Draft, w.id)
    return {
        "id": w.id,
        "title": w.title,
        "kind": w.kind,
        "indication": w.indication,
        "owner_id": w.owner_id,
        "starter": w.starter,
        "revision": d.revision if d else 0,
        "created_at": w.created_at.isoformat(),
        "updated_at": w.updated_at.isoformat(),
        "my_level": work_level(db, user, w),
    }


def load_state(db: Session, work_id: str) -> DraftState:
    d = db.get(Draft, work_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft missing")
    return DraftState.model_validate({**d.state, "revision": d.revision})


def adjudication_map(db: Session, work_id: str) -> dict[str, str]:
    return {a.finding_key: a.decision for a in db.scalars(select(Adjudication).where(Adjudication.work_id == work_id))}


def _new_work_id(db: Session) -> str:
    while True:
        wid = f"W-{secrets.randbelow(900) + 100}"
        if db.get(Work, wid) is None:
            return wid


# ----------------------------------------------------------------------------- routes


class CreateWork(BaseModel):
    title: str
    indication: str = "atopic dermatitis"
    kind: str = "protocol"
    starter: str = "blank"  # "blank" or a library starter id


@router.get("")
def list_works(user: User = Depends(current_user), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    works = db.scalars(select(Work).order_by(Work.updated_at.desc())).all()
    return [_work_json(db, user, w) for w in works if work_level(db, user, w)]


@router.post("", status_code=201)
def create_work(
    body: CreateWork, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    if user.role not in {"admin", "author"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "authors only")
    wid = _new_work_id(db)
    try:
        state = starter_state(body.starter, protocol_id=wid, title=body.title, indication=body.indication)
    except KeyError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown starter {body.starter}") from e
    w = Work(
        id=wid, title=body.title, kind=body.kind, indication=body.indication, owner_id=user.id, starter=body.starter
    )
    db.add(w)
    db.flush()  # the draft's FK needs the work row first
    db.add(Draft(work_id=wid, revision=0, state=state.model_dump(exclude={"revision"})))
    audit(db, actor=user, action="work.create", work_id=wid, starter=body.starter)
    db.commit()
    return _work_json(db, user, w)


@router.get("/{work_id}")
def get_work(
    work: Work = Depends(require_work("view")), user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    perms = db.scalars(select(Permission).where(Permission.work_id == work.id)).all()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return {
        **_work_json(db, user, work),
        "owner_email": users[work.owner_id].email if work.owner_id in users else None,
        "permissions": [
            {"user_id": p.user_id, "email": users[p.user_id].email if p.user_id in users else None, "level": p.level}
            for p in perms
        ],
    }


@router.get("/{work_id}/draft")
def get_draft(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    return load_state(db, work.id).model_dump()


@router.post("/{work_id}/commands")
def post_command(
    cmd: Command,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    state = load_state(db, work.id)
    try:
        new_state, summary = apply_command(state, cmd, actor=user.email)
    except ConflictError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"error": "stale", "head": state.revision, "detail": str(e)}
        ) from e
    except CommandError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    d = db.get(Draft, work.id)
    assert d is not None
    d.state = new_state.model_dump(exclude={"revision"})
    d.revision = new_state.revision
    d.updated_at = datetime.now(UTC)
    work.updated_at = d.updated_at
    db.add(
        Revision(
            work_id=work.id, revision=new_state.revision, actor_id=user.id, command=cmd.model_dump(), summary=summary
        )
    )
    audit(db, actor=user, action=f"command.{cmd.type}", work_id=work.id, revision=new_state.revision, summary=summary)
    db.commit()
    return {
        "revision": new_state.revision,
        "summary": summary,
        "state": new_state.model_dump(),
        "evaluation": evaluate(new_state, adjudication_map(db, work.id)),
    }


@router.get("/{work_id}/evaluation")
def get_evaluation(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    return evaluate(load_state(db, work.id), adjudication_map(db, work.id))


class Adjudicate(BaseModel):
    finding_key: str
    decision: str  # accepted | dismissed
    note: str = ""
    revision: int  # revision the finding was computed at


@router.post("/{work_id}/adjudications")
def adjudicate(
    body: Adjudicate,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    state = load_state(db, work.id)
    if body.revision != state.revision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "error": "stale",
                "head": state.revision,
                "detail": "finding computed at an older revision; re-evaluate first",
            },
        )
    if body.decision not in {"accepted", "dismissed"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "decision must be accepted|dismissed")
    current = evaluate(state)
    if body.finding_key not in {f["key"] for f in current["findings"]}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such finding at head")
    existing = db.scalar(
        select(Adjudication).where(Adjudication.work_id == work.id, Adjudication.finding_key == body.finding_key)
    )
    if existing:
        existing.decision, existing.note, existing.actor_id, existing.revision = (
            body.decision,
            body.note,
            user.id,
            state.revision,
        )
    else:
        db.add(
            Adjudication(
                work_id=work.id,
                finding_key=body.finding_key,
                decision=body.decision,
                note=body.note,
                actor_id=user.id,
                revision=state.revision,
            )
        )
    audit(db, actor=user, action="finding.adjudicate", work_id=work.id, key=body.finding_key, decision=body.decision)
    db.commit()
    return evaluate(state, adjudication_map(db, work.id))


@router.get("/{work_id}/history")
def history(
    work: Work = Depends(require_work("view")), db: Session = Depends(get_session), limit: int = 200
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Revision).where(Revision.work_id == work.id).order_by(Revision.revision.desc()).limit(limit)
    ).all()
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return [
        {
            "revision": r.revision,
            "actor": users.get(r.actor_id),
            "summary": r.summary,
            "type": r.command.get("type"),
            "note": r.command.get("note", ""),
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{work_id}/outline")
def outline(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ev = evaluate(load_state(db, work.id), adjudication_map(db, work.id))
    comp = {s["section_id"]: s for s in ev["completion"]["sections"]}
    return [
        {
            "id": s.id,
            "number": s.number,
            "title": s.title,
            "generated": s.generated_view,
            "subsections": [{"id": x.id, "title": x.title} for x in s.subsections],
            "completion": comp.get(s.id),
        }
        for s in OUTLINE
    ]


class SetPermission(BaseModel):
    email: str
    level: str | None  # view | edit | admin | None (remove)


@router.put("/{work_id}/permissions")
def set_permission(
    body: SetPermission,
    work: Work = Depends(require_work("admin")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    target = db.scalar(select(User).where(User.email == body.email))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user; add them in Admin › Users first")
    perm = db.scalar(select(Permission).where(Permission.work_id == work.id, Permission.user_id == target.id))
    if body.level is None:
        if perm:
            db.delete(perm)
    elif body.level not in {"view", "edit", "admin"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "level must be view|edit|admin")
    elif perm:
        perm.level = body.level
    else:
        db.add(Permission(work_id=work.id, user_id=target.id, level=body.level))
    audit(db, actor=user, action="work.permission", work_id=work.id, email=body.email, level=body.level)
    db.commit()
    return {"ok": True}
