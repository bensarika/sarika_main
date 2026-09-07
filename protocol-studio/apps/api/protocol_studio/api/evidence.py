"""Evidence: master sheet, sources (upload / link / connection), extraction → study record, comparisons.

    GET   /api/evidence/indications                       counts per indication
    GET   /api/evidence/studies?indication=               master-sheet rows
    GET   /api/evidence/studies/{id}                      full StudyRecord (+ tier)
    PATCH /api/evidence/studies/{id}                      user records only: approve / edit canonical
    GET   /api/evidence/matrix?indication=                instrument × transformation matrix

    GET   /api/evidence/sources                           sources visible to the caller
    POST  /api/evidence/sources            (multipart)    upload PDF/MD/XLSX → SourceRecord (sha256 de-dup)
    POST  /api/evidence/sources/link                      register a URL
    GET   /api/evidence/sources/{id}                      record + extraction
    POST  /api/evidence/sources/{id}/extract              deterministic extraction → status "review"
    GET   /api/evidence/sources/{id}/draft                StudyRecord draft from the extraction
    POST  /api/evidence/sources/{id}/study                reviewer confirms a StudyRecord → master sheet

    GET   /api/evidence/connections                       stored connections + default corpus status
    POST  /api/evidence/connections                       {kind, uri, scope, work_id?} → check + store
    POST  /api/evidence/connections/{id}/check
    POST  /api/evidence/connections/{id}/sync             register listed objects as SourceRecords

    GET   /api/evidence/compare/endpoints?studies=a,b&role=primary
    GET   /api/evidence/compare/eligibility?indication=&category=age&min_age=&max_age=&text=
    GET   /api/evidence/compare/results?indication=&instrument=EASI&transformation=responder&threshold=75%&week=16

Visibility: ``workspace`` sources are readable by any signed-in user; ``study``
sources need view access on the work; ``private`` only the uploader. Files are
parsed once (keyed by sha256) and reused.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from protocol_studio.auth.session import audit, current_user, work_level
from protocol_studio.db import SourceConnection, SourceRecord, StudyRecordRow, User, Work, get_session
from protocol_studio.evidence import compare, connections, extract, master
from protocol_studio.evidence.schema import Criterion, StudyRecord
from protocol_studio.settings import settings

router = APIRouter(prefix="/api/evidence", tags=["evidence"], dependencies=[Depends(current_user)])

_DOC_TYPES = ("protocol", "sap", "fda_review", "label", "publication", "dataset", "other")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def _can_see(db: Session, user: User, s: SourceRecord) -> bool:
    if user.role == "admin" or s.uploaded_by == user.id or s.visibility == "workspace":
        return True
    if s.visibility == "study" and s.work_id:
        w = db.get(Work, s.work_id)
        return w is not None and work_level(db, user, w) is not None
    return False


def _source_json(s: SourceRecord, users: dict[int, str], *, with_extraction: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id,
        "name": s.name,
        "document_type": s.document_type,
        "origin": s.origin,
        "uri": s.uri if s.origin != "upload" else "",
        "sha256": s.sha256,
        "size_bytes": s.size_bytes,
        "media_type": s.media_type,
        "status": s.status,
        "indication": s.indication,
        "study_identifier": s.study_identifier,
        "visibility": s.visibility,
        "work_id": s.work_id,
        "uploaded_by": users.get(s.uploaded_by),
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
        "has_extraction": bool(s.extraction),
    }
    if with_extraction:
        out["extraction"] = s.extraction
    return out


def _users(db: Session) -> dict[int, str]:
    return {u.id: u.email for u in db.scalars(select(User)).all()}


def _source(db: Session, user: User, source_id: str) -> SourceRecord:
    s = db.get(SourceRecord, source_id)
    if s is None or not _can_see(db, user, s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    return s


def _check_scope(db: Session, user: User, visibility: str, work_id: str | None) -> None:
    if visibility not in ("workspace", "study", "private"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "visibility must be workspace | study | private")
    if visibility == "study":
        w = db.get(Work, work_id or "")
        if w is None or work_level(db, user, w) not in ("edit", "admin"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "study-scoped sources need edit access on the work")


# ----------------------------------------------------------------------------- master sheet


@router.get("/indications")
def indications(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return master.indication_summary(db)


@router.get("/studies")
def studies(indication: str | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    recs = master.all_records(db, indication)
    return {
        "indication": indication,
        "rows": [master.row(db, r) for r in recs],
        "results_source_linked": any(r.results and not r.synthetic for r in recs),
    }


@router.get("/matrix")
def matrix(indication: str | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    recs = master.all_records(db, indication)
    return {"studies": [{"id": r.id, "title": r.title} for r in recs], **master.endpoint_matrix(recs)}


@router.get("/studies/{study_id}")
def study(study_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    rec = master.find(db, study_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "study not found")
    row = db.get(StudyRecordRow, study_id)
    return {**rec.model_dump(), "tier": master.tier(db, rec), "status": row.status if row else "approved"}


class PatchStudy(BaseModel):
    status: str | None = None
    record: dict[str, Any] | None = None


@router.patch("/studies/{study_id}")
def patch_study(
    study_id: str, body: PatchStudy, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    row = db.get(StudyRecordRow, study_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "only user-added study records can be changed")
    if row.created_by != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your record")
    if body.record is not None:
        try:
            rec = StudyRecord.model_validate({**body.record, "id": study_id})
        except ValidationError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
        row.canonical, row.indication = rec.model_dump(), rec.indication
    if body.status is not None:
        if body.status not in ("review", "approved"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "status must be review | approved")
        if body.status == "approved" and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "approving a study record is an admin action")
        row.status = body.status
    row.updated_at = datetime.now(UTC)
    audit(db, actor=user, action="evidence.study.patch", study_id=study_id, status=row.status)
    db.commit()
    return study(study_id, db)


# ----------------------------------------------------------------------------- sources


@router.get("/sources")
def list_sources(
    indication: str | None = None,
    work_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    q = select(SourceRecord).order_by(SourceRecord.created_at.desc())
    if indication:
        q = q.where(SourceRecord.indication == indication)
    if work_id:
        q = q.where(SourceRecord.work_id == work_id)
    users = _users(db)
    return [_source_json(s, users) for s in db.scalars(q).all() if _can_see(db, user, s)]


def _new_id() -> str:
    return "src-" + secrets.token_hex(6)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def upload_source(
    file: UploadFile = File(...),
    document_type: str = Form("protocol"),
    indication: str = Form(""),
    study_identifier: str = Form(""),
    visibility: str = Form("workspace"),
    work_id: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    name = file.filename or "upload"
    mt = extract.media_type_for(name)
    if mt == "application/octet-stream":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "PDF, Markdown, text or Excel (.xlsx) only")
    if document_type not in _DOC_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"document_type must be one of {_DOC_TYPES}")
    _check_scope(db, user, visibility, work_id)
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty file")
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"max {settings.upload_max_bytes // (1024 * 1024)} MB"
        )
    sha = extract.sha256_hex(data)
    existing = db.scalar(select(SourceRecord).where(SourceRecord.sha256 == sha))
    users = _users(db)
    if existing is not None and _can_see(db, user, existing):
        return {**_source_json(existing, users), "reused": True}
    ext = name.rsplit(".", 1)[-1].lower()
    folder = settings.data_dir / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    s = SourceRecord(
        id=_new_id(),
        name=name,
        document_type=document_type,
        origin="upload",
        uri=str(path),
        sha256=sha,
        size_bytes=len(data),
        media_type=mt,
        status="uploaded",
        indication=indication,
        study_identifier=study_identifier,
        visibility=visibility,
        work_id=work_id if visibility == "study" else None,
        uploaded_by=user.id,
    )
    db.add(s)
    audit(db, actor=user, action="evidence.source.upload", source_id=s.id, sha256=sha, bytes=len(data))
    db.commit()
    return {**_source_json(s, {**users, user.id: user.email}), "reused": False}


class Link(BaseModel):
    url: str
    name: str = ""
    document_type: str = "protocol"
    indication: str = ""
    study_identifier: str = ""
    visibility: str = "workspace"
    work_id: str | None = None


@router.post("/sources/link", status_code=status.HTTP_201_CREATED)
def link_source(body: Link, user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict[str, Any]:
    url = body.url.strip()
    if not url.startswith(("http://", "https://", "s3://")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "url must be http(s):// or s3://")
    if body.document_type not in _DOC_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"document_type must be one of {_DOC_TYPES}")
    _check_scope(db, user, body.visibility, body.work_id)
    existing = db.scalar(select(SourceRecord).where(SourceRecord.uri == url))
    users = _users(db)
    if existing is not None and _can_see(db, user, existing):
        return {**_source_json(existing, users), "reused": True}
    s = SourceRecord(
        id=_new_id(),
        name=body.name or url.rsplit("/", 1)[-1] or url,
        document_type=body.document_type,
        origin="s3" if url.startswith("s3://") else "link",
        uri=url,
        media_type=extract.media_type_for(url),
        status="registered",
        indication=body.indication,
        study_identifier=body.study_identifier,
        visibility=body.visibility,
        work_id=body.work_id if body.visibility == "study" else None,
        uploaded_by=user.id,
    )
    db.add(s)
    audit(db, actor=user, action="evidence.source.link", source_id=s.id, url=url)
    db.commit()
    return {**_source_json(s, {**users, user.id: user.email}), "reused": False}


@router.get("/sources/{source_id}")
def get_source(
    source_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    s = _source(db, user, source_id)
    return _source_json(s, _users(db), with_extraction=True)


def _bytes_for(s: SourceRecord) -> bytes:
    if s.origin == "upload":
        p = Path(s.uri)
        if not p.exists():
            raise HTTPException(status.HTTP_410_GONE, "stored file is missing")
        return p.read_bytes()
    if s.origin == "s3":
        bucket, key = connections.parse_s3(s.uri)
        try:
            body = boto3.client("s3", region_name=settings.aws_region).get_object(Bucket=bucket, Key=key)["Body"].read()
        except (ClientError, BotoCoreError) as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"cannot read {s.uri}: {e.__class__.__name__}") from e
        return bytes(body)
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "link sources are registered only; upload the file to extract"
    )


@router.post("/sources/{source_id}/extract")
def extract_source(
    source_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    s = _source(db, user, source_id)
    if s.extraction and s.status in ("review", "canonical"):
        return {**_source_json(s, _users(db), with_extraction=True), "reused": True}
    data = _bytes_for(s)
    try:
        ex = extract.extract(s.name, data)
    except Exception as e:
        s.status, s.extraction = "failed", {"error": e.__class__.__name__}
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"extraction failed: {e.__class__.__name__}") from e
    if not s.sha256:
        s.sha256, s.size_bytes = ex["sha256"], ex["bytes"]
    s.extraction, s.status, s.updated_at = ex, "review", datetime.now(UTC)
    if not s.study_identifier and ex["identifiers"]["nct"]:
        s.study_identifier = ex["identifiers"]["nct"][0]
    audit(db, actor=user, action="evidence.source.extract", source_id=s.id, pages=ex.get("pages"))
    db.commit()
    return {**_source_json(s, _users(db), with_extraction=True), "reused": False}


@router.get("/sources/{source_id}/draft")
def draft(source_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict[str, Any]:
    s = _source(db, user, source_id)
    if not s.extraction or "identifiers" not in s.extraction:
        raise HTTPException(status.HTTP_409_CONFLICT, "run extraction first")
    return extract.draft_record(s.id, s.name, s.extraction, s.indication or "atopic-dermatitis")


class ConfirmStudy(BaseModel):
    record: dict[str, Any]


@router.post("/sources/{source_id}/study", status_code=status.HTTP_201_CREATED)
def confirm_study(
    source_id: str, body: ConfirmStudy, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    s = _source(db, user, source_id)
    try:
        rec = StudyRecord.model_validate(body.record)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
    if not rec.intervention or not rec.title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "intervention and title are required")
    if not rec.id:
        tail = rec.protocol_identifier or (rec.registry_ids[0] if rec.registry_ids else s.id)
        rec.id = master.slug(f"{rec.intervention}-{tail}")
    if master.find(db, rec.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"a study record {rec.id!r} already exists")
    if not any(d.source_id == s.id for d in rec.documents):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "record.documents must reference this source")
    db.add(
        StudyRecordRow(
            id=rec.id,
            indication=rec.indication,
            canonical=rec.model_dump(),
            status="review",
            source_id=s.id,
            created_by=user.id,
        )
    )
    s.status, s.indication, s.updated_at = "canonical", rec.indication, datetime.now(UTC)
    audit(db, actor=user, action="evidence.study.create", source_id=s.id, study_id=rec.id)
    db.commit()
    return study(rec.id, db)


# ----------------------------------------------------------------------------- connections


def _conn_json(c: SourceConnection, users: dict[int, str]) -> dict[str, Any]:
    return {
        "id": c.id,
        "kind": c.kind,
        "uri": c.uri,
        "scope": c.scope,
        "work_id": c.work_id,
        "status": c.status,
        "detail": {k: v for k, v in c.detail.items() if k != "objects"},
        "objects": c.detail.get("objects", []),
        "created_by": users.get(c.created_by),
        "created_at": _iso(c.created_at),
        "checked_at": _iso(c.checked_at),
    }


def _run_check(c: SourceConnection) -> None:
    res = connections.check(c.kind, c.uri)
    c.status = res.status
    c.detail = {**res.detail, "message": res.message, "objects": res.objects}
    c.checked_at = datetime.now(UTC)


@router.get("/connections")
def list_connections(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict[str, Any]:
    rows = db.scalars(select(SourceConnection).order_by(SourceConnection.id)).all()
    users = _users(db)
    return {
        "default_corpus": {"kind": "s3", "uri": settings.corpus_s3_uri, "region": settings.aws_region},
        "connections": [_conn_json(c, users) for c in rows if c.scope == "workspace" or _conn_visible(db, user, c)],
        "dropbox_configured": False,
    }


def _conn_visible(db: Session, user: User, c: SourceConnection) -> bool:
    if user.role == "admin" or c.created_by == user.id:
        return True
    w = db.get(Work, c.work_id or "")
    return w is not None and work_level(db, user, w) is not None


class NewConnection(BaseModel):
    kind: str
    uri: str
    scope: str = "workspace"
    work_id: str | None = None


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def add_connection(
    body: NewConnection, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    if body.kind not in ("s3", "dropbox"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind must be s3 | dropbox")
    if body.scope not in ("workspace", "study"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "scope must be workspace | study")
    if body.scope == "study":
        _check_scope(db, user, "study", body.work_id)
    elif user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace-wide connections are added by an administrator")
    c = SourceConnection(
        kind=body.kind, uri=body.uri.strip(), scope=body.scope, work_id=body.work_id, created_by=user.id
    )
    _run_check(c)
    db.add(c)
    audit(db, actor=user, action="evidence.connection.add", kind=body.kind, uri=c.uri, status=c.status)
    db.commit()
    return _conn_json(c, _users(db))


def _connection(db: Session, user: User, conn_id: int) -> SourceConnection:
    c = db.get(SourceConnection, conn_id)
    if c is None or not (c.scope == "workspace" or _conn_visible(db, user, c)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found")
    return c


@router.post("/connections/{conn_id}/check")
def check_connection(
    conn_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    c = _connection(db, user, conn_id)
    _run_check(c)
    db.commit()
    return _conn_json(c, _users(db))


@router.post("/connections/{conn_id}/sync")
def sync_connection(
    conn_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)
) -> dict[str, Any]:
    c = _connection(db, user, conn_id)
    _run_check(c)
    if c.status != "ok":
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, c.detail.get("message", "connection is not usable"))
    known = {s.uri for s in db.scalars(select(SourceRecord).where(SourceRecord.origin == "s3")).all()}
    added = 0
    for o in c.detail.get("objects", []):
        if o["uri"] in known:
            continue
        db.add(
            SourceRecord(
                id=_new_id(),
                name=o["name"],
                document_type="other",
                origin="s3",
                uri=o["uri"],
                size_bytes=o["size"],
                media_type=extract.media_type_for(o["name"]),
                status="registered",
                visibility="workspace" if c.scope == "workspace" else "study",
                work_id=c.work_id if c.scope == "study" else None,
                uploaded_by=user.id,
            )
        )
        added += 1
    audit(db, actor=user, action="evidence.connection.sync", connection_id=c.id, added=added)
    db.commit()
    return {**_conn_json(c, _users(db)), "registered": added}


# ----------------------------------------------------------------------------- compare


@router.get("/compare/endpoints")
def compare_endpoints(studies: str, role: str = "primary", db: Session = Depends(get_session)) -> dict[str, Any]:
    ids = [s for s in studies.split(",") if s]
    recs = [r for r in (master.find(db, i) for i in ids) if r is not None]
    if len(recs) < 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such studies")
    return compare.compare_endpoints(recs, role)


@router.get("/compare/eligibility")
def compare_eligibility(
    indication: str = "atopic-dermatitis",
    category: str = "age",
    text: str = "",
    min_age: float | None = None,
    max_age: float | None = None,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    ours = (
        Criterion(
            id="ours",
            kind="inclusion",
            category=category,
            text=text or "New study criterion",
            min_age=min_age,
            max_age=max_age,
        )
        if text or min_age is not None or max_age is not None
        else None
    )
    recs = [r for r in master.all_records(db, indication) if not r.synthetic]
    return compare.compare_eligibility(recs, category, ours)


@router.get("/compare/results")
def compare_results(
    indication: str = "atopic-dermatitis",
    instrument: str = "EASI",
    transformation: str = "responder",
    threshold: str = "75%",
    week: float = 16,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return compare.compare_results(master.all_records(db, indication), instrument, transformation, threshold, week)
