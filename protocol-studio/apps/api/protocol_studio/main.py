"""FastAPI application factory.

    uvicorn protocol_studio.main:app --reload --port 8080

Serves the JSON API under /api and /auth, and (when ``PS_WEB_DIST`` points at a
built frontend) the single-page app at "/". SessionMiddleware is only used by
the Google OAuth dance (state/nonce); our own login cookie is the signed
``ps_session`` cookie in auth/session.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from protocol_studio.api import admin, ai, collab, evidence, library, providers, trial_lab, versions, works
from protocol_studio.auth import routes as auth_routes
from protocol_studio.db import init_db
from protocol_studio.settings import settings


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Protocol Studio", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.public_base_url.startswith("https"),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_routes.router)
    app.include_router(works.router)
    app.include_router(versions.router)
    app.include_router(admin.router)
    app.include_router(library.router)
    app.include_router(trial_lab.router)
    app.include_router(collab.router)
    app.include_router(ai.router)
    app.include_router(providers.router)
    app.include_router(evidence.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    dist = Path(settings.web_dist)
    if not dist.is_absolute():
        dist = (Path(__file__).resolve().parents[1] / dist).resolve()
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = dist / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
