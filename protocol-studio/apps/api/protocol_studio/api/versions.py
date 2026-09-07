"""Frozen versions and exports.

    GET  /api/works/{id}/versions                  list
    POST /api/works/{id}/versions                  freeze head: snapshot + evaluation + artifacts
    GET  /api/works/{id}/versions/{label}          one version (evaluation + artifact hashes)
    GET  /api/works/{id}/versions/{label}/file/{kind}   download pdf|docx|tex of a frozen version
    GET  /api/works/{id}/versions/{label}/diff?against=head|<label>   model + tracked-change block diff
    POST /api/works/{id}/versions/{label}/restore  restore the snapshot as a NEW head revision
    GET  /api/works/{id}/export/{kind}             render the *working draft* head (pdf|docx|tex)

Freezing does not require readiness — a team may freeze "v0.3 for internal
review" with open findings — but the version records the readiness verdict so
nobody can later claim it was submission-ready.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.api.works import adjudication_map, load_state, persist_revision
from protocol_studio.auth.session import audit, current_user, require_work
from protocol_studio.db import User, Version, Work, get_session
from protocol_studio.engine.commands import ConflictError, apply_restore
from protocol_studio.engine.diff import diff_states
from protocol_studio.engine.evaluation import evaluate
from protocol_studio.engine.export import draft_export_dir, render_all, version_export_dir
from protocol_studio.engine.state import DraftState

router = APIRouter(prefix="/api/works", tags=["versions"])

_KINDS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "tex": "text/x-tex",
}
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


def _version_json(v: Version, users: dict[int, str]) -> dict[str, Any]:
    return {
        "label": v.label,
        "revision": v.revision,
        "note": v.note,
        "frozen_by": users.get(v.frozen_by),
        "created_at": v.created_at.isoformat(),
        "readiness": v.evaluation.get("readiness"),
        "completion": v.evaluation.get("completion", {}).get("overall"),
        "counts": v.evaluation.get("counts"),
        "artifacts": {k: {"sha256": a.get("sha256"), "available": bool(a.get("path"))} for k, a in v.artifacts.items()},
    }


@router.get("/{work_id}/versions")
def list_versions(
    work: Work = Depends(require_work("view")), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    rows = db.scalars(select(Version).where(Version.work_id == work.id).order_by(Version.created_at.desc())).all()
    return [_version_json(v, users) for v in rows]


class Freeze(BaseModel):
    label: str
    note: str = ""
    render_pdf: bool = True


@router.post("/{work_id}/versions", status_code=201)
def freeze(
    body: Freeze,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    if not _LABEL_RE.match(body.label):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "label: letters, digits, . _ - (max 41 chars)")
    if db.scalar(select(Version).where(Version.work_id == work.id, Version.label == body.label)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"version {body.label} already exists")
    state = load_state(db, work.id)
    ev = evaluate(state, adjudication_map(db, work.id))
    artifacts = render_all(
        state,
        out_dir=version_export_dir(work.id, body.label),
        version_label=f"{body.label} (frozen, revision {state.revision})",
        want_pdf=body.render_pdf,
    )
    v = Version(
        work_id=work.id,
        label=body.label,
        revision=state.revision,
        snapshot=state.model_dump(),
        evaluation=ev,
        artifacts=artifacts,
        note=body.note,
        frozen_by=user.id,
    )
    db.add(v)
    audit(
        db,
        actor=user,
        action="version.freeze",
        work_id=work.id,
        label=body.label,
        revision=state.revision,
        ready=ev["readiness"]["ready"],
    )
    db.commit()
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return _version_json(v, users)


@router.get("/{work_id}/versions/{label}")
def get_version(
    label: str, work: Work = Depends(require_work("view")), db: Session = Depends(get_session)
) -> dict[str, Any]:
    v = db.scalar(select(Version).where(Version.work_id == work.id, Version.label == label))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return {**_version_json(v, users), "evaluation": v.evaluation, "snapshot": v.snapshot}


@router.get("/{work_id}/versions/{label}/file/{kind}")
def version_file(
    label: str, kind: str, work: Work = Depends(require_work("view")), db: Session = Depends(get_session)
) -> FileResponse:
    if kind not in _KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    v = db.scalar(select(Version).where(Version.work_id == work.id, Version.label == label))
    if v is None or not v.artifacts.get(kind, {}).get("path"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {kind} for {label}")
    return FileResponse(v.artifacts[kind]["path"], media_type=_KINDS[kind], filename=f"{work.id}-{label}.{kind}")


def _load_version(db: Session, work: Work, label: str) -> Version:
    v = db.scalar(select(Version).where(Version.work_id == work.id, Version.label == label))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no version {label}")
    return v


@router.get("/{work_id}/versions/{label}/diff")
def version_diff(
    label: str,
    against: str = "head",
    work: Work = Depends(require_work("view")),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Diff ``label`` → ``against`` (the working head by default, or another frozen label)."""
    old = DraftState.model_validate(_load_version(db, work, label).snapshot)
    if against == "head":
        new = load_state(db, work.id)
    else:
        new = DraftState.model_validate(_load_version(db, work, against).snapshot)
    return {"from": label, "to": against, **diff_states(old, new)}


class Restore(BaseModel):
    base_revision: int
    note: str = ""


@router.post("/{work_id}/versions/{label}/restore")
def restore_version(
    label: str,
    body: Restore,
    work: Work = Depends(require_work("edit")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    v = _load_version(db, work, label)
    state = load_state(db, work.id)
    try:
        new_state, summary = apply_restore(
            state, DraftState.model_validate(v.snapshot), base_revision=body.base_revision, label=label
        )
    except ConflictError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"error": "stale", "head": state.revision, "detail": str(e)}
        ) from e
    command = {"type": "restore_version", "base_revision": body.base_revision, "label": label, "note": body.note}
    return persist_revision(db, work, user, new_state, command=command, summary=summary)


@router.get("/{work_id}/export/{kind}")
def export_draft(
    kind: str,
    work: Work = Depends(require_work("view")),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> FileResponse:
    if kind not in _KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    state = load_state(db, work.id)
    try:
        artifacts = render_all(
            state,
            out_dir=draft_export_dir(work.id, state.revision),
            version_label=f"DRAFT — working copy, revision {state.revision}",
            want_pdf=(kind == "pdf"),
        )
    except RuntimeError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"render failed: {e}") from e
    art = artifacts.get(kind) or {}
    if not art.get("path"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, art.get("error", f"no {kind} produced"))
    audit(db, actor=user, action=f"export.{kind}", work_id=work.id, revision=state.revision)
    db.commit()
    return FileResponse(art["path"], media_type=_KINDS[kind], filename=f"{work.id}-draft-r{state.revision}.{kind}")
