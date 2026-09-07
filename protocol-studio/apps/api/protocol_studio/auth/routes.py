"""Sign-in routes.

    GET  /auth/me                      current user or 401
    POST /auth/dev-login               (auth_mode=dev only) sign in as PS_DEV_USER_EMAIL
    GET  /auth/google/login            redirect to Google (auth_mode=google)
    GET  /auth/google/callback         OIDC callback; creates/looks up the user
    POST /auth/logout

Google: Authlib OAuth client against the OIDC discovery document. Only accounts
in ``allowed_domain`` (hd claim) are accepted; the GCP project is configured
as *Internal* so Google enforces this too. Unknown accounts are created
inactive and get a 403 with a clear message until an admin activates them.
"""

from __future__ import annotations

from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, clear_session, current_user, ensure_user, set_session, user_from_request
from protocol_studio.db import User, get_session
from protocol_studio.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
if settings.auth_mode == "google" and settings.google_client_id:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "hd": settings.allowed_domain},
    )


def _user_json(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_session)) -> dict[str, Any]:
    u = user_from_request(request, db)
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    return {"user": _user_json(u), "auth_mode": settings.auth_mode}


@router.get("/config")
def config() -> dict[str, Any]:
    return {"auth_mode": settings.auth_mode, "allowed_domain": settings.allowed_domain}


@router.post("/dev-login")
def dev_login(response: Response, db: Session = Depends(get_session), email: str | None = None) -> dict[str, Any]:
    if settings.auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    u = ensure_user(db, email=email or settings.dev_user_email)
    if not u.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account not yet authorised")
    set_session(response, u)
    audit(db, actor=u, action="auth.login", mode="dev")
    db.commit()
    return {"user": _user_json(u)}


@router.get("/google/login")
async def google_login(request: Request) -> Response:
    if settings.auth_mode != "google":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    redirect_uri = f"{settings.public_base_url}/auth/google/callback"
    result: Response = await oauth.google.authorize_redirect(request, redirect_uri)
    return result


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_session)) -> Response:
    if settings.auth_mode != "google":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    token = await oauth.google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = str(info.get("email", "")).lower()
    if not email or not info.get("email_verified") or not email.endswith("@" + settings.allowed_domain):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"only {settings.allowed_domain} accounts may sign in")
    u = ensure_user(db, email=email, name=str(info.get("name", "")))
    if not u.active:
        audit(db, actor=None, action="auth.denied", email=email)
        db.commit()
        return RedirectResponse("/login?denied=1")
    resp = RedirectResponse("/")
    set_session(resp, u)
    audit(db, actor=u, action="auth.login", mode="google")
    db.commit()
    return resp


@router.post("/logout")
def logout(
    response: Response, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, bool]:
    clear_session(response)
    audit(db, actor=user, action="auth.logout")
    db.commit()
    return {"ok": True}
