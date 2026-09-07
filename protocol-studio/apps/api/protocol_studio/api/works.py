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
    PATCH  /api/works/{id}                   study metadata (title, status, data_class, drugs…)
    GET    /api/works/{id}/adaptation        adaptation proposals + evidence requirements + summary
    GET    /api/works/{id}/key-inputs        grouped questionnaire with current values and coverage
    GET    /api/works/{id}/proposals         blocks with pending text proposals (tracked changes)

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
from protocol_studio.engine.adaptation import adaptation_summary
from protocol_studio.engine.commands import Command, CommandError, ConflictError, apply_command
from protocol_studio.engine.evaluation import evaluate
from protocol_studio.engine.key_inputs import questionnaire
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
        "study_code": w.study_code,
        "phase": w.phase,
        "drugs": w.drugs,
        "status": w.status,
        "sap_status": w.sap_status,
        "data_class": w.data_class,
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


class DrugIn(BaseModel):
    name: str
    mechanism: str = ""
    role: str = "investigational"


class CreateWork(BaseModel):
    title: str
    indication: str = "atopic dermatitis"
    kind: str = "protocol"
    starter: str = "blank"  # "blank" or a library starter id
    study_code: str = ""
    phase: str = ""
    drugs: list[DrugIn] = []
    data_class: str = "internal"


class PatchWork(BaseModel):
    title: str | None = None
    indication: str | None = None
    study_code: str | None = None
    phase: str | None = None
    drugs: list[DrugIn] | None = None
    status: str | None = None
    sap_status: str | None = None
    data_class: str | None = None


_STATUSES = {"draft", "review", "approved", "archived"}
_SAP_STATUSES = {"not_started", "draft", "review", "approved"}
_DATA_CLASSES = {"public", "internal", "confidential", "restricted"}


@router.get("")
def list_works(user: User = Depends(current_user), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    works = db.scalars(select(Work).order_by(Work.updated_at.desc())).all()
    out = []
    for w in works:
        if not work_level(db, user, w):
            continue
        row = _work_json(db, user, w)
        d = db.get(Draft, w.id)
        if d is not None:
            ev = evaluate(DraftState.model_validate({**d.state, "revision": d.revision}), adjudication_map(db, w.id))
            row["completion_pct"] = ev["completion"]["overall"]["pct"]
            row["open_findings"] = ev["counts"]["error"] + ev["counts"]["warning"]
        out.append(row)
    return out


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
    if body.data_class not in _DATA_CLASSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"data_class must be one of {sorted(_DATA_CLASSES)}")
    w = Work(
        id=wid,
        title=body.title,
        kind=body.kind,
        indication=body.indication,
        owner_id=user.id,
        starter=body.starter,
        study_code=body.study_code,
        phase=body.phase,
        drugs=[d.model_dump() for d in body.drugs],
        data_class=body.data_class,
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


@router.patch("/{work_id}")
def patch_work(
    body: PatchWork,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    if body.status is not None and body.status not in _STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"status must be one of {sorted(_STATUSES)}")
    if body.sap_status is not None and body.sap_status not in _SAP_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sap_status must be one of {sorted(_SAP_STATUSES)}")
    if body.data_class is not None and body.data_class not in _DATA_CLASSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"data_class must be one of {sorted(_DATA_CLASSES)}")
    if body.status == "approved":
        ev = evaluate(load_state(db, work.id), adjudication_map(db, work.id))
        if not ev["readiness"]["ready"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"error": "not_ready", "blockers": ev["readiness"]["blockers"]}
            )
    changed = body.model_dump(exclude_none=True)
    if body.title is not None:
        work.title = body.title
    if body.indication is not None:
        work.indication = body.indication
    if body.study_code is not None:
        work.study_code = body.study_code
    if body.phase is not None:
        work.phase = body.phase
    if body.status is not None:
        work.status = body.status
    if body.sap_status is not None:
        work.sap_status = body.sap_status
    if body.data_class is not None:
        work.data_class = body.data_class
    if body.drugs is not None:
        work.drugs = [d.model_dump() for d in body.drugs]
    work.updated_at = datetime.now(UTC)
    audit(db, actor=user, action="work.update", work_id=work.id, **changed)
    db.commit()
    return _work_json(db, user, work)


@router.get("/{work_id}/draft")
def get_draft(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    return load_state(db, work.id).model_dump()


@router.get("/{work_id}/adaptation")
def get_adaptation(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    st = load_state(db, work.id)
    return {
        "summary": adaptation_summary(st.adaptation),
        "adaptation": st.adaptation.model_dump() if st.adaptation else None,
        "revision": st.revision,
    }


@router.get("/{work_id}/key-inputs")
def get_key_inputs(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    st = load_state(db, work.id)
    return {**questionnaire(st), "revision": st.revision}


@router.get("/{work_id}/proposals")
def get_proposals(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> dict[str, Any]:
    st = load_state(db, work.id)
    rows = [
        {
            "block_id": b.id,
            "section_id": b.section_id,
            "subsection_id": b.subsection_id,
            "original": b.text,
            "proposal": b.proposal.model_dump(),
        }
        for b in st.blocks
        if b.proposal is not None
    ]
    return {"revision": st.revision, "proposals": rows}


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
    return persist_revision(db, work, user, new_state, command=cmd.model_dump(), summary=summary)


def persist_revision(
    db: Session, work: Work, user: User, new_state: DraftState, *, command: dict[str, Any], summary: str
) -> dict[str, Any]:
    """Write a new head + append-only Revision + audit row, then return the standard command response.

    Shared by the command route, version restore and applied comment suggestions so every
    head change goes through exactly one code path.
    """
    d = db.get(Draft, work.id)
    assert d is not None
    d.state = new_state.model_dump(exclude={"revision"})
    d.revision = new_state.revision
    d.updated_at = datetime.now(UTC)
    work.updated_at = d.updated_at
    db.add(Revision(work_id=work.id, revision=new_state.revision, actor_id=user.id, command=command, summary=summary))
    audit(
        db,
        actor=user,
        action=f"command.{command.get('type', 'unknown')}",
        work_id=work.id,
        revision=new_state.revision,
        summary=summary,
    )
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
