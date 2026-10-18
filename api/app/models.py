"""SQLAlchemy 2 models - the tables of spec section 4.

Two deliberate storage choices so the same code runs on Postgres 16 and on the SQLite the tests use:

* ``jsonb`` columns are ``JSON`` with a ``JSONB`` variant on Postgres.
* the spec's ``text[]`` / ``uuid[]`` columns (``connections.scopes``, ``extractions.note_ids``,
  ``transfers.cells``, ``sheet_layouts.formula_cols`` / ``date_cols``) are stored as JSON arrays
  rather than native Postgres arrays. Nothing queries inside them; they are read whole.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.tz import display_zone_name

Json = JSON().with_variant(postgresql.JSONB(), "postgresql")

ROLES = ("admin", "member")
CONNECTION_STATUS = ("ok", "expired")
MEETING_SOURCES = ("calendar", "manual")
MEETING_STEPS = ("meeting", "notes", "points", "done")
NOTE_SOURCES = ("gemini_doc", "transcript", "recap_email", "paste", "upload")
POINT_KINDS = ("action", "decision", "risk", "question")
POINT_STATUSES = ("open", "in_progress", "blocked", "done", "dropped", "decided")
LIFECYCLES = ("active", "deferred")
TRANSFER_MODES = ("append", "fill", "add_row")
WRITE_KINDS = ("transfer", "sheet_save", "add_row")
WRITE_STATUSES = ("pending", "done", "failed")


def _enum(*values: str, name: str) -> Enum:
    # native_enum=False keeps this a VARCHAR + CHECK, which SQLite understands too.
    return Enum(*values, name=name, native_enum=False, validate_strings=True)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: Json, list[Any]: Json}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(_enum(*ROLES, name="user_role"), default="member")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AllowListEntry(Base):
    __tablename__ = "allow_list"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    role: Mapped[str] = mapped_column(_enum(*ROLES, name="allow_role"), default="member")
    added_by: Mapped[str] = mapped_column(String(320), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    matched_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    scopes: Mapped[list[Any]] = mapped_column(Json, default=list)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(_enum(*CONNECTION_STATUS, name="connection_status"), default="ok")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    source: Mapped[str] = mapped_column(_enum(*MEETING_SOURCES, name="meeting_source"))
    created_by: Mapped[str] = mapped_column(String(320), default="")

    calendar_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    calendar_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    ical_uid: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    recurring_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    html_link: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default=display_zone_name)
    organizer_email: Mapped[str] = mapped_column(String(320), default="")
    organizer_name: Mapped[str] = mapped_column(String(200), default="")
    attendees: Mapped[list[Any]] = mapped_column(Json, default=list)
    conference: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    attachments: Mapped[list[Any]] = mapped_column(Json, default=list)

    event_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workstream: Mapped[str] = mapped_column(String(64), default="")
    step: Mapped[str] = mapped_column(_enum(*MEETING_STEPS, name="meeting_step"), default="meeting")
    in_progress_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    in_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Note(Base):
    __tablename__ = "notes"
    # "The same text saved twice" is only a duplicate while both are live. A removed note keeps its
    # row for the 30-day recovery window, and the partial index is what lets the same text be
    # pasted again afterwards instead of tripping a unique constraint on a row nobody can see.
    # Postgres and SQLite both index on a predicate; the two dialect kwargs say the same thing.
    __table_args__ = (
        Index(
            "uq_notes_meeting_text_live",
            "meeting_id",
            "text_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(_enum(*NOTE_SOURCES, name="note_source"))
    origin_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    note_ids: Mapped[list[Any]] = mapped_column(Json, default=list)
    provider: Mapped[str] = mapped_column(String(32), default="fake")
    model: Mapped[str] = mapped_column(String(64), default="")
    region: Mapped[str] = mapped_column(String(32), default="")
    schema_version: Mapped[str] = mapped_column(String(16), default="v3")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    output: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Point(Base):
    """Transferred points are deleted here; the transfer row keeps the cells and a snapshot."""

    __tablename__ = "points"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("extractions.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(_enum(*POINT_KINDS, name="point_kind"), default="action")
    text: Mapped[str] = mapped_column(Text, default="")
    text_norm: Mapped[str] = mapped_column(Text, default="", index=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    owner_text: Mapped[str] = mapped_column(String(200), default="")
    owner_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    owner_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    due_text: Mapped[str] = mapped_column(String(80), default="")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(_enum(*POINT_STATUSES, name="point_status"), default="open")
    workstream: Mapped[str] = mapped_column(String(64), default="")
    lifecycle: Mapped[str] = mapped_column(_enum(*LIFECYCLES, name="point_lifecycle"), default="active")
    deferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deferred_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(320), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Workbook(Base):
    __tablename__ = "workbooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    spreadsheet_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    # The admin connection that can edit this workbook, chosen automatically at connect time.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    connected_by: Mapped[str] = mapped_column(String(320), default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SheetLayout(Base):
    __tablename__ = "sheet_layouts"

    workbook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workbooks.id", ondelete="CASCADE"), primary_key=True
    )
    sheet_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    header_row: Mapped[int] = mapped_column(Integer, default=-1)
    first_col: Mapped[int] = mapped_column(Integer, default=0)
    last_col: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    key_col: Mapped[int] = mapped_column(Integer, default=-1)
    key_prefix: Mapped[str] = mapped_column(String(8), default="")
    last_table_row: Mapped[int] = mapped_column(Integer, default=-1)
    dropdowns: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    formula_cols: Mapped[list[Any]] = mapped_column(Json, default=list)
    date_cols: Mapped[list[Any]] = mapped_column(Json, default=list)
    region_hash: Mapped[str] = mapped_column(String(64), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(320), default="")
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    meeting_title: Mapped[str] = mapped_column(Text, default="")
    point_text: Mapped[str] = mapped_column(Text, default="")
    # The same value as ``snapshot["text_norm"]``, out as a column so "has this gone across
    # before?" is an index lookup scoped to the workbook rather than a scan of every transfer ever
    # made, JSON-decoded one row at a time.
    text_norm: Mapped[str] = mapped_column(Text, default="", index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    workbook_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workbooks.id", ondelete="CASCADE"))
    sheet_id: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(_enum(*TRANSFER_MODES, name="transfer_mode"), default="append")
    cells: Mapped[list[Any]] = mapped_column(Json, default=list)
    previous: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SheetEdit(Base):
    __tablename__ = "sheet_edits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(320), default="")
    workbook_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workbooks.id", ondelete="CASCADE"))
    sheet_id: Mapped[str] = mapped_column(String(64), default="")
    cell: Mapped[str] = mapped_column(String(16), default="")
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class WriteBatch(Base):
    """One attempt to write to Google, recorded before the call and settled after it.

    Every route that writes to a spreadsheet takes a client ``batch_id`` and lands a ``pending``
    row here, committed *before* the Google call. That is what makes the write idempotent and
    auditable at once:

    * the same ``batch_id`` arriving twice (a retry, a double tap, a proxy replay) is answered with
      the stored result instead of writing a second time;
    * a crash between the Google call and the database leaves ``pending``, which says "a write may
      have landed" rather than leaving no trace at all;
    * a refusal from Google leaves ``failed`` with the reason, and nothing else in the request has
      happened yet - no point is deleted, no edit is logged.
    """

    __tablename__ = "write_batches"

    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(_enum(*WRITE_KINDS, name="write_batch_kind"))
    status: Mapped[str] = mapped_column(
        _enum(*WRITE_STATUSES, name="write_batch_status"), default="pending", index=True
    )
    actor: Mapped[str] = mapped_column(String(320), default="")
    workbook_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    sheet_id: Mapped[str] = mapped_column(String(64), default="")
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(320), default="")
    text: Mapped[str] = mapped_column(Text, default="")
