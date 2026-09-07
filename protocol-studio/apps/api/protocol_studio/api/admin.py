"""Admin portal API (admins only).

    GET   /api/admin/users              all users with activity
    POST  /api/admin/users              add/authorise a user (email, role)
    PATCH /api/admin/users/{id}         change role / active flag
    GET   /api/admin/audit              audit log (filter by action / work)
    GET   /api/admin/usage?period=7d|30d|90d|all   (and /usage.csv for download)
                                        per-user counts: commands, exports, freezes, AI calls, logins, comments
    GET   /api/admin/access-requests    pending access requests across all works

Model providers/keys (Admin › Models) live in api/providers.py.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, require_admin
from protocol_studio.db import AccessRequest, AuditEvent, User, Work, get_session
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


_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
_USAGE_COLUMNS = ("email", "role", "commands", "exports", "freezes", "ai_calls", "comments", "logins", "other")


def _bucket(action: str) -> str:
    if action.startswith("command."):
        return "commands"
    if action.startswith("export."):
        return "exports"
    if action == "version.freeze":
        return "freezes"
    if action.startswith("ai."):
        return "ai_calls"
    if action.startswith("comment."):
        return "comments"
    if action == "auth.login":
        return "logins"
    return "other"


def usage_rows(db: Session, period: str) -> list[dict[str, Any]]:
    """One row per user (including users with no activity) for the period, busiest first."""
    if period not in _PERIODS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"period must be one of {sorted(_PERIODS)}")
    q = select(AuditEvent.actor_id, AuditEvent.action, func.count()).group_by(AuditEvent.actor_id, AuditEvent.action)
    days = _PERIODS[period]
    if days is not None:
        q = q.where(AuditEvent.created_at >= datetime.now(UTC) - timedelta(days=days))
    per: dict[int, dict[str, Any]] = {
        u.id: {**dict.fromkeys(_USAGE_COLUMNS, 0), "email": u.email, "role": u.role}
        for u in db.scalars(select(User)).all()
    }
    for actor_id, action, n in db.execute(q).all():
        if actor_id in per:
            per[actor_id][_bucket(action)] += n
    return sorted(per.values(), key=lambda r: (-r["commands"], -r["logins"], r["email"]))


@router.get("/usage")
def usage(db: Session = Depends(get_session), period: str = "30d") -> list[dict[str, Any]]:
    return usage_rows(db, period)


@router.get("/usage.csv")
def usage_csv(db: Session = Depends(get_session), period: str = "30d") -> PlainTextResponse:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(_USAGE_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(usage_rows(db, period))
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="usage-{period}.csv"'},
    )


@router.get("/access-requests")
def all_access_requests(db: Session = Depends(get_session), status_filter: str = "pending") -> list[dict[str, Any]]:
    q = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if status_filter != "all":
        q = q.where(AccessRequest.status == status_filter)
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    works = {w.id: w.title for w in db.scalars(select(Work)).all()}
    return [
        {
            "id": r.id,
            "work_id": r.work_id,
            "work_title": works.get(r.work_id, ""),
            "email": users.get(r.user_id),
            "level": r.level,
            "message": r.message,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in db.scalars(q).all()
    ]
