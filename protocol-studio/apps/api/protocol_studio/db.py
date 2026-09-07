"""SQLAlchemy 2 engine, session factory and ORM tables.

Design (docs/01_architecture.md §9): *head state* of a draft is one JSON
document (model + blocks + claims + N/A map) keyed by work; every accepted
command is appended to ``revisions`` so the history is replayable; frozen
``versions`` snapshot everything including findings and artifact hashes.
JSON columns are portable between SQLite (dev) and Postgres JSONB (prod).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from protocol_studio.settings import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default="author")  # admin | author | reviewer | viewer
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Work(Base):
    __tablename__ = "works"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "W-102"
    title: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(16), default="protocol")  # protocol | sap (legacy; a work is a study)
    indication: Mapped[str] = mapped_column(String(120), default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starter: Mapped[str] = mapped_column(String(120), default="")  # provenance of the seed
    # Study-level metadata shown in the Workspace; the trial model carries the clinical detail.
    study_code: Mapped[str] = mapped_column(String(64), default="")
    phase: Mapped[str] = mapped_column(String(16), default="")
    drugs: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{"name", "mechanism", "role"}]
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | review | approved | archived
    sap_status: Mapped[str] = mapped_column(String(16), default="not_started")  # not_started | draft | review
    data_class: Mapped[str] = mapped_column(
        String(16), default="internal"
    )  # public | internal | confidential | restricted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("work_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    level: Mapped[str] = mapped_column(String(16))  # view | edit | admin


class Draft(Base):
    """Head state of a work; exactly one row per work."""

    __tablename__ = "drafts"
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Revision(Base):
    """Append-only command log. (work_id, revision) is unique; replaying yields the head."""

    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("work_id", "revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    command: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Version(Base):
    """Immutable frozen version (what reviewers and regulators see)."""

    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("work_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)  # full draft state
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSON)  # findings, completion, readiness
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"pdf": {"path", "sha256"}, ...}
    note: Mapped[str] = mapped_column(Text, default="")
    frozen_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Adjudication(Base):
    """Human decision on a candidate finding, keyed by the finding's stable key."""

    __tablename__ = "adjudications"
    __table_args__ = (UniqueConstraint("work_id", "finding_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    finding_key: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(16))  # accepted | dismissed
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    """Selection-linked discussion. ``anchor`` records block id + quoted text so the thread
    survives re-wording; ``kind`` separates a comment from a suggestion (proposed wording)."""

    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="comment")  # comment | suggestion
    section_id: Mapped[str] = mapped_column(String(32), default="")
    block_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    anchor_text: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    suggested_text: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Presence(Base):
    """Last-seen heartbeat per (work, user) so collaborators see who is in a document."""

    __tablename__ = "presence"
    __table_args__ = (UniqueConstraint("work_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    section_id: Mapped[str] = mapped_column(String(32), default="")
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessRequest(Base):
    """A user asking for view/edit access to a work they can see exists but cannot open.

    Decided by the work owner, a work admin, or a global admin; approval writes a Permission row.
    """

    __tablename__ = "access_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    level: Mapped[str] = mapped_column(String(16), default="view")  # view | edit
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | denied
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderPolicy(Base):
    """Which model provider may receive which data class. Absent row = not approved (fail closed)."""

    __tablename__ = "provider_policies"
    __table_args__ = (UniqueConstraint("provider", "data_class"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))  # openai | ...
    data_class: Mapped[str] = mapped_column(String(16))
    approved: Mapped[bool] = mapped_column(default=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceRecord(Base):
    """An ingested or connected source document (upload, S3 object, link). Parsed once, reused."""

    __tablename__ = "source_records"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # "src-<hex>"
    name: Mapped[str] = mapped_column(String(400))
    document_type: Mapped[str] = mapped_column(String(32), default="other")
    origin: Mapped[str] = mapped_column(String(16), default="upload")  # upload | s3 | dropbox | link
    uri: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(
        String(24), default="uploaded"
    )  # uploaded | extracted | review | canonical | failed
    indication: Mapped[str] = mapped_column(String(120), default="")
    study_identifier: Mapped[str] = mapped_column(String(120), default="")
    extraction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    visibility: Mapped[str] = mapped_column(String(16), default="workspace")  # workspace | study | private
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id"), nullable=True, index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    work_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ----------------------------------------------------------------------------- engine/session


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    if url.startswith("sqlite"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn: Any, _record: Any) -> None:
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return eng
    return create_engine(url, pool_pre_ping=True)


engine: Engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng: Engine | None = None) -> None:
    Base.metadata.create_all(eng or engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s
