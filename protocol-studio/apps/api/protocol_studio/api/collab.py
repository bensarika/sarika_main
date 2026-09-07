"""Collaboration on a draft: comment threads, suggestions, presence, access requests.

    GET    /api/works/{id}/comments?resolved=false     threads (top-level + nested replies)
    POST   /api/works/{id}/comments                    new comment / suggestion / reply   (view access)
    PATCH  /api/works/{id}/comments/{cid}              edit body (author) · resolve/reopen (edit access or author)
    POST   /api/works/{id}/comments/{cid}/apply        turn a suggestion into a pending text proposal (edit access)
    PUT    /api/works/{id}/presence                    heartbeat {section_id}
    GET    /api/works/{id}/presence                    who is in the document right now

    POST   /api/works/{id}/access-requests             ask for view|edit (any signed-in user, no ACL needed)
    GET    /api/works/{id}/access-requests             pending + decided (work admin)
    POST   /api/works/{id}/access-requests/{rid}       decide {approve, level?, note}  (work admin)
    GET    /api/access-requests/mine                   the caller's own requests

Comments are *not* part of DraftState: they are review metadata, not document
content, so they never appear in exports or versions and do not bump the
revision. A suggestion becomes document content only through ``/apply``, which
routes it through the normal ``propose_text`` command (so it shows up as a
pending proposal with factual-change checks, and still needs accept/reject).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.api.works import load_state, persist_revision
from protocol_studio.auth.session import audit, current_user, require_work, work_level
from protocol_studio.db import AccessRequest, Comment, Permission, Presence, User, Work, get_session
from protocol_studio.engine.commands import CommandError, ConflictError, ProposeText, apply_command

router = APIRouter(tags=["collab"])

PRESENCE_WINDOW = timedelta(seconds=90)


def _users(db: Session) -> dict[int, str]:
    return {u.id: u.email for u in db.scalars(select(User)).all()}


def _iso(dt: datetime) -> str:
    """SQLite hands back naive datetimes; everything we store is UTC."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


# ----------------------------------------------------------------------------- comments


def _comment_json(c: Comment, users: dict[int, str]) -> dict[str, Any]:
    return {
        "id": c.id,
        "parent_id": c.parent_id,
        "author": users.get(c.author_id),
        "kind": c.kind,
        "section_id": c.section_id,
        "block_id": c.block_id,
        "anchor_text": c.anchor_text,
        "body": c.body,
        "suggested_text": c.suggested_text,
        "resolved": c.resolved,
        "resolved_by": users.get(c.resolved_by) if c.resolved_by else None,
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
    }


@router.get("/api/works/{work_id}/comments")
def list_comments(
    work: Work = Depends(require_work("view")),
    db: Session = Depends(get_session),
    resolved: bool | None = None,
    section_id: str | None = None,
) -> list[dict[str, Any]]:
    """Top-level comments (oldest first) each carrying its ``replies``; filters apply to the thread root."""
    users = _users(db)
    rows = db.scalars(select(Comment).where(Comment.work_id == work.id).order_by(Comment.created_at)).all()
    threads: dict[int, dict[str, Any]] = {}
    for c in rows:
        if c.parent_id is None:
            if resolved is not None and c.resolved != resolved:
                continue
            if section_id and c.section_id != section_id:
                continue
            threads[c.id] = {**_comment_json(c, users), "replies": []}
    for c in rows:
        if c.parent_id is not None and c.parent_id in threads:
            threads[c.parent_id]["replies"].append(_comment_json(c, users))
    return list(threads.values())


class NewComment(BaseModel):
    body: str = ""
    kind: str = "comment"  # comment | suggestion
    section_id: str = ""
    block_id: str | None = None
    anchor_text: str = ""
    suggested_text: str = ""
    parent_id: int | None = None


@router.post("/api/works/{work_id}/comments", status_code=201)
def add_comment(
    body: NewComment,
    work: Work = Depends(require_work("view")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    if body.kind not in {"comment", "suggestion"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind must be comment|suggestion")
    if body.kind == "suggestion" and not (body.block_id and body.suggested_text.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a suggestion needs block_id and suggested_text")
    if body.kind == "comment" and not body.body.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty comment")
    section_id, block_id = body.section_id, body.block_id
    if body.parent_id is not None:
        parent = db.get(Comment, body.parent_id)
        if parent is None or parent.work_id != work.id or parent.parent_id is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "parent must be a top-level comment on this work")
        section_id, block_id = parent.section_id, parent.block_id
    if block_id is not None:
        st = load_state(db, work.id)
        blk = next((b for b in st.blocks if b.id == block_id), None)
        if blk is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no block {block_id}")
        section_id = section_id or blk.section_id
    c = Comment(
        work_id=work.id,
        parent_id=body.parent_id,
        author_id=user.id,
        kind=body.kind,
        section_id=section_id,
        block_id=block_id,
        anchor_text=body.anchor_text,
        body=body.body,
        suggested_text=body.suggested_text,
    )
    db.add(c)
    audit(db, actor=user, action=f"comment.{body.kind}", work_id=work.id, section_id=section_id, block_id=block_id)
    db.commit()
    return _comment_json(c, _users(db))


class PatchComment(BaseModel):
    body: str | None = None
    resolved: bool | None = None


@router.patch("/api/works/{work_id}/comments/{comment_id}")
def patch_comment(
    comment_id: int,
    body: PatchComment,
    work: Work = Depends(require_work("view")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    c = db.get(Comment, comment_id)
    if c is None or c.work_id != work.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    is_author = c.author_id == user.id
    can_edit_work = work_level(db, user, work) in {"edit", "admin"}
    if body.body is not None:
        if not is_author:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "only the author can edit a comment")
        c.body = body.body
    if body.resolved is not None:
        if not (is_author or can_edit_work):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "needs edit access to resolve")
        if c.parent_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "resolve the thread, not a reply")
        c.resolved = body.resolved
        c.resolved_by = user.id if body.resolved else None
    c.updated_at = datetime.now(UTC)
    audit(
        db, actor=user, action="comment.patch", work_id=work.id, comment_id=c.id, **body.model_dump(exclude_none=True)
    )
    db.commit()
    return _comment_json(c, _users(db))


class ApplySuggestion(BaseModel):
    base_revision: int


@router.post("/api/works/{work_id}/comments/{comment_id}/apply")
def apply_suggestion(
    comment_id: int,
    body: ApplySuggestion,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Promote a suggestion to a pending ``propose_text`` on its block and resolve the thread."""
    c = db.get(Comment, comment_id)
    if c is None or c.work_id != work.id or c.kind != "suggestion" or c.block_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such suggestion")
    users = _users(db)
    cmd = ProposeText(
        base_revision=body.base_revision,
        block_id=c.block_id,
        text=c.suggested_text,
        origin="suggestion",
        instruction=f"Suggestion by {users.get(c.author_id, '?')}: {c.body}".strip(": "),
    )
    state = load_state(db, work.id)
    try:
        new_state, summary = apply_command(state, cmd, actor=user.email)
    except ConflictError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"error": "stale", "head": state.revision, "detail": str(e)}
        ) from e
    except CommandError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    c.resolved, c.resolved_by, c.updated_at = True, user.id, datetime.now(UTC)
    out = persist_revision(db, work, user, new_state, command={**cmd.model_dump(), "comment_id": c.id}, summary=summary)
    return {**out, "comment": _comment_json(c, users)}


# ----------------------------------------------------------------------------- presence


class Heartbeat(BaseModel):
    section_id: str = ""


@router.put("/api/works/{work_id}/presence")
def heartbeat(
    body: Heartbeat,
    work: Work = Depends(require_work("view")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    p = db.scalar(select(Presence).where(Presence.work_id == work.id, Presence.user_id == user.id))
    if p is None:
        p = Presence(work_id=work.id, user_id=user.id)
        db.add(p)
    p.section_id, p.seen_at = body.section_id, datetime.now(UTC)
    db.commit()
    return presence(work, db)


@router.get("/api/works/{work_id}/presence")
def presence(work: Work = Depends(require_work("view")), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - PRESENCE_WINDOW
    users = _users(db)
    rows = db.scalars(select(Presence).where(Presence.work_id == work.id).order_by(Presence.seen_at.desc())).all()
    return [
        {"email": users.get(p.user_id), "section_id": p.section_id, "seen_at": _iso(p.seen_at)}
        for p in rows
        if p.seen_at.replace(tzinfo=UTC) >= since
    ]


# ----------------------------------------------------------------------------- access requests


def _req_json(r: AccessRequest, users: dict[int, str], works: dict[str, str]) -> dict[str, Any]:
    return {
        "id": r.id,
        "work_id": r.work_id,
        "work_title": works.get(r.work_id, ""),
        "email": users.get(r.user_id),
        "level": r.level,
        "message": r.message,
        "status": r.status,
        "decided_by": users.get(r.decided_by) if r.decided_by else None,
        "decision_note": r.decision_note,
        "created_at": _iso(r.created_at),
        "decided_at": _iso(r.decided_at) if r.decided_at else None,
    }


class NewAccessRequest(BaseModel):
    level: str = "view"
    message: str = ""


@router.post("/api/works/{work_id}/access-requests", status_code=201)
def request_access(
    work_id: str,
    body: NewAccessRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Deliberately does *not* use ``require_work``: the whole point is that the caller lacks access."""
    work = db.get(Work, work_id)
    if work is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such work")
    if body.level not in {"view", "edit"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "level must be view|edit")
    have = work_level(db, user, work)
    if have is not None and (have != "view" or body.level == "view"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"you already have {have} access")
    pending = db.scalar(
        select(AccessRequest).where(
            AccessRequest.work_id == work.id, AccessRequest.user_id == user.id, AccessRequest.status == "pending"
        )
    )
    if pending is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a request is already pending")
    r = AccessRequest(work_id=work.id, user_id=user.id, level=body.level, message=body.message)
    db.add(r)
    audit(db, actor=user, action="access.request", work_id=work.id, level=body.level)
    db.commit()
    return _req_json(r, _users(db), {work.id: work.title})


@router.get("/api/works/{work_id}/access-requests")
def list_access_requests(
    work: Work = Depends(require_work("admin")), db: Session = Depends(get_session), status_filter: str | None = None
) -> list[dict[str, Any]]:
    q = select(AccessRequest).where(AccessRequest.work_id == work.id).order_by(AccessRequest.created_at.desc())
    if status_filter:
        q = q.where(AccessRequest.status == status_filter)
    users = _users(db)
    return [_req_json(r, users, {work.id: work.title}) for r in db.scalars(q).all()]


class Decide(BaseModel):
    approve: bool
    level: str | None = None  # override the requested level when approving
    note: str = ""


@router.post("/api/works/{work_id}/access-requests/{request_id}")
def decide_access_request(
    request_id: int,
    body: Decide,
    work: Work = Depends(require_work("admin")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    r = db.get(AccessRequest, request_id)
    if r is None or r.work_id != work.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if r.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"already {r.status}")
    level = body.level or r.level
    if level not in {"view", "edit"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "level must be view|edit")
    if body.approve:
        perm = db.scalar(select(Permission).where(Permission.work_id == work.id, Permission.user_id == r.user_id))
        if perm is None:
            db.add(Permission(work_id=work.id, user_id=r.user_id, level=level))
        else:
            perm.level = level
        r.level = level
    r.status = "approved" if body.approve else "denied"
    r.decided_by, r.decision_note, r.decided_at = user.id, body.note, datetime.now(UTC)
    audit(db, actor=user, action=f"access.{r.status}", work_id=work.id, request_id=r.id, level=level)
    db.commit()
    return _req_json(r, _users(db), {work.id: work.title})


@router.get("/api/access-requests/mine")
def my_access_requests(user: User = Depends(current_user), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AccessRequest).where(AccessRequest.user_id == user.id).order_by(AccessRequest.created_at.desc())
    ).all()
    works = {w.id: w.title for w in db.scalars(select(Work).where(Work.id.in_({r.work_id for r in rows}))).all()}
    return [_req_json(r, _users(db), works) for r in rows]
