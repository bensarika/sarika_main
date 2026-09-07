"""Session cookie + current-user dependency + ACL helpers.

Sign-in flows (dev auto-login, Google OIDC) live in ``routes.py``; this module
only knows how to read/write the signed cookie and answer "who is this and
what may they do".

Roles (docs/01_architecture.md §8): admin > author > reviewer > viewer.
Per-work permissions (view / edit / admin) override the default. Admins see
everything. Authorisation is *allow-list*: an @sarika.com account that signs
in but is not in ``users`` is created inactive and denied until an admin
activates it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.db import AuditEvent, Permission, User, Work, get_session
from protocol_studio.settings import settings

COOKIE = "ps_session"
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ps-session")

_LEVEL_RANK = {"view": 1, "edit": 2, "admin": 3}


def set_session(resp: Response, user: User) -> None:
    token = _serializer.dumps({"uid": user.id})
    resp.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https"),
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(COOKIE)


def user_from_request(request: Request, db: Session) -> User | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer.loads(raw, max_age=settings.session_max_age)
    except BadSignature:
        return None
    user = db.get(User, int(data["uid"]))
    if user is None or not user.active:
        return None
    return user


def ensure_user(db: Session, *, email: str, name: str = "") -> User:
    """Find or create a user row. New accounts are active only if listed as admin."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        is_admin = email in settings.admin_emails
        user = User(
            email=email, name=name or email.split("@")[0], role="admin" if is_admin else "author", active=is_admin
        )
        db.add(user)
        db.commit()
    return user


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    user.last_seen_at = datetime.now(UTC)
    db.commit()
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def work_level(db: Session, user: User, work: Work) -> str | None:
    """Effective permission level on a work: admin | edit | view | None."""
    if user.role == "admin" or work.owner_id == user.id:
        return "admin"
    perm = db.scalar(select(Permission).where(Permission.work_id == work.id, Permission.user_id == user.id))
    return perm.level if perm else None


def require_work(level: str) -> Callable[..., Work]:
    """Dependency factory: ``Depends(require_work("edit"))`` loads the work and checks the ACL."""

    def dep(work_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)) -> Work:
        work = db.get(Work, work_id)
        if work is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such work")
        have = work_level(db, user, work)
        if have is None or _LEVEL_RANK[have] < _LEVEL_RANK[level]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"needs {level} access")
        return work

    return dep


def audit(db: Session, *, actor: User | None, action: str, work_id: str | None = None, **detail: object) -> None:
    db.add(AuditEvent(actor_id=actor.id if actor else None, work_id=work_id, action=action, detail=dict(detail)))
