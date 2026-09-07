"""Admin portal API (admins only).

    GET   /api/admin/users              all users with activity
    POST  /api/admin/users              add/authorise a user (email, role)
    PATCH /api/admin/users/{id}         change role / active flag
    GET   /api/admin/audit              audit log (filter by action / work)
    GET   /api/admin/usage              counts per user: commands, exports, logins (last 30 days)

Model providers/keys (Admin › Models) arrive with the LLM gateway in Pilot 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, require_admin
from protocol_studio.db import AuditEvent, User, get_session
from protocol_studio.settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _u(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "active": u.active,
        "created_at": u.created_at.isoformat(),
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
    }


@router.get("/users")
def users(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_u(u) for u in db.scalars(select(User).order_by(User.email)).all()]


class NewUser(BaseModel):
    email: str
    name: str = ""
    role: str = "author"


@router.post("/users", status_code=201)
def add_user(body: NewUser, admin: User = Depends(require_admin), db: Session = Depends(get_session)) -> dict[str, Any]:
    email = body.email.strip().lower()
    if not email.endswith("@" + settings.allowed_domain):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"only @{settings.allowed_domain} accounts")
    if body.role not in {"admin", "author", "reviewer", "viewer"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad role")
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=body.name or email.split("@")[0], role=body.role, active=True)
        db.add(u)
    else:
        u.role, u.active = body.role, True
    audit(db, actor=admin, action="admin.user.add", email=email, role=body.role)
    db.commit()
    return _u(u)


class PatchUser(BaseModel):
    role: str | None = None
    active: bool | None = None
    name: str | None = None


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int, body: PatchUser, admin: User = Depends(require_admin), db: Session = Depends(get_session)
) -> dict[str, Any]:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if u.email in settings.admin_emails and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "the primary administrator cannot be demoted")
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.name is not None:
        u.name = body.name
    audit(db, actor=admin, action="admin.user.patch", target=u.email, **body.model_dump(exclude_none=True))
    db.commit()
    return _u(u)


@router.get("/audit")
def audit_log(
    db: Session = Depends(get_session), action: str | None = None, work_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if work_id:
        q = q.where(AuditEvent.work_id == work_id)
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return [
        {
            "id": e.id,
            "at": e.created_at.isoformat(),
            "actor": users.get(e.actor_id) if e.actor_id else None,
            "work_id": e.work_id,
            "action": e.action,
            "detail": e.detail,
        }
        for e in db.scalars(q).all()
    ]


@router.get("/usage")
def usage(db: Session = Depends(get_session), days: int = 30) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(AuditEvent.actor_id, AuditEvent.action, func.count())
        .where(AuditEvent.created_at >= since)
        .group_by(AuditEvent.actor_id, AuditEvent.action)
    ).all()
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    per: dict[int, dict[str, Any]] = {}
    for actor_id, action, n in rows:
        if actor_id is None:
            continue
        rec = per.setdefault(
            actor_id, {"email": users.get(actor_id), "commands": 0, "exports": 0, "logins": 0, "freezes": 0, "other": 0}
        )
        if action.startswith("command."):
            rec["commands"] += n
        elif action.startswith("export."):
            rec["exports"] += n
        elif action == "auth.login":
            rec["logins"] += n
        elif action == "version.freeze":
            rec["freezes"] += n
        else:
            rec["other"] += n
    return sorted(per.values(), key=lambda r: -r["commands"])
