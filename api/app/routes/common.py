"""Helpers every route group needs: connections, tab reads, keys, lookups."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.google.interface import AuthExpired, GoogleSuite, TabRead
from app.google.picker import Pick, first_able
from app.models import Connection, Meeting, Point, SheetLayout, Workbook
from app.sheets.layout import Layout, detect_date_cols, detect_formula_cols, detect_layout, region_hash
from app.tz import display_zone

SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
# A bare id pasted without the URL around it. Google's file ids are long base64url strings, so
# anything with a query string, a fragment, a dot or a path segment in it is a mistyped link, not
# an id - it must not reach the Sheets API as one.
BARE_SPREADSHEET_ID_RE = re.compile(r"[A-Za-z0-9_-]{20,}")


def aware(value: datetime | None, tz: ZoneInfo | None = None) -> datetime | None:
    """SQLite drops the offset, so datetimes read back naive. Put it back before comparing."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=tz or display_zone())


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_config(request: Request) -> Settings:
    return request.app.state.settings


def as_uuid(value: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown {what}") from exc


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def next_key(db: Session, prefix: str) -> str:
    """Human-facing meeting keys: M-113, M-114, ..."""
    highest = 0
    for key in db.scalars(select(Meeting.key)).all():
        m = re.fullmatch(rf"{prefix}-(\d+)", key or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}-{highest + 1:03d}"


def healthy_connections(db: Session) -> list[Connection]:
    return list(
        db.scalars(
            select(Connection).where(Connection.status == "ok").order_by(Connection.connected_at)
        ).all()
    )


def admin_emails(db: Session) -> list[str]:
    return [c.email for c in healthy_connections(db)]


def mark_expired(db: Session, connection_email: str, error: str) -> None:
    """A refused refresh token: the connection is ``expired`` until an admin reconnects it."""
    connection = db.scalar(select(Connection).where(Connection.email == connection_email))
    if connection is not None:
        connection.status = "expired"
        connection.last_error = error


def note_refusal(db: Session, connection_email: str, exc: BaseException) -> None:
    if isinstance(exc, AuthExpired):
        mark_expired(db, connection_email, str(exc))
    else:
        connection = db.scalar(select(Connection).where(Connection.email == connection_email))
        if connection is not None:
            connection.last_error = str(exc)


def pick_for(db: Session, emails: Iterable[str], attempt: Callable[[str], Any], accept: Any = None) -> Pick:
    """``first_able`` plus the bookkeeping: an expired connection is marked in this session.

    One extra rule: if every connection that was tried came back rate-limited, that is re-raised
    rather than reported as "nobody can see this". ``create_app`` turns ``RateLimited`` into a 503
    with ``Retry-After``, which is the answer the person can act on.
    """
    pick = first_able(emails, attempt, accept)
    for email, error in pick.expired.items():
        mark_expired(db, email, error)
    throttled = pick.only_rate_limited
    if throttled is not None:
        raise throttled
    return pick


def get_meeting(db: Session, meeting_id: str, include_deleted: bool = False) -> Meeting:
    meeting = db.get(Meeting, as_uuid(meeting_id, "meeting"))
    if meeting is None or (meeting.deleted_at is not None and not include_deleted):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown meeting")
    return meeting


def get_point(db: Session, point_id: str, include_deleted: bool = False) -> Point:
    point = db.get(Point, as_uuid(point_id, "point"))
    if point is None or (point.deleted_at is not None and not include_deleted):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown point")
    return point


def get_workbook(db: Session, workbook_id: str) -> Workbook:
    workbook = db.get(Workbook, as_uuid(workbook_id, "workbook"))
    if workbook is None or workbook.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown workbook")
    return workbook


def spreadsheet_id_from_url(url: str) -> str:
    m = SPREADSHEET_URL_RE.search(url or "")
    if m:
        return m.group(1)
    bare = (url or "").strip()
    if BARE_SPREADSHEET_ID_RE.fullmatch(bare):
        return bare
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "That does not look like a Google Sheets link. Paste the URL from the browser's address bar.",
    )


def meeting_label(meeting: Meeting | None, tz_now: datetime | None = None) -> str:
    """What lands in the Notes column so the row keeps its link to the meeting."""
    if meeting is None:
        return ""
    when = meeting.start_at
    if when is None:
        return meeting.title
    return f"{meeting.title} · {when.strftime('%-d %b')}"


@dataclass(slots=True)
class TabState:
    workbook: Workbook
    connection_email: str
    read: TabRead
    layout: Layout
    region_hash: str
    read_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_id": str(self.workbook.id),
            "sheet_id": self.read.sheet_id,
            "title": self.read.title,
            "values": self.read.values,
            "dropdowns": {str(k): v for k, v in self.read.dropdowns.items()},
            "formula_cols": self.layout.formula_cols,
            "date_cols": self.layout.date_cols,
            "layout": self.layout.to_dict(),
            "region_hash": self.region_hash,
            "read_at": self.read_at.isoformat(),
            "can_edit": self.workbook.can_edit,
        }


def reader_connections(db: Session, workbook: Workbook) -> list[str]:
    """The workbook's own connection first, then every other healthy one as a read fallback."""
    emails = []
    if workbook.connection_id:
        owner = db.get(Connection, workbook.connection_id)
        if owner and owner.status == "ok":
            emails.append(owner.email)
    emails.extend(e for e in admin_emails(db) if e not in emails)
    return emails


def read_tab(
    db: Session,
    google: GoogleSuite,
    workbook: Workbook,
    sheet_id: str,
    clock: Clock,
) -> TabState:
    """Read a tab through the first connection that can, detect the layout, remember it."""
    pick = pick_for(
        db,
        reader_connections(db, workbook),
        lambda email: google.sheets.read_tab(email, workbook.spreadsheet_id, sheet_id),
    )
    if pick.ok:
        read: TabRead = pick.value
        now = clock.now()
        provisional = detect_layout(read.values)
        formula_cols = detect_formula_cols(read.formulas, header_row=provisional.header_row)
        date_cols = detect_date_cols(read.number_formats, header_row=provisional.header_row)
        layout = detect_layout(read.values, formula_cols=formula_cols, date_cols=date_cols)
        digest = region_hash(read.values, layout)
        _remember_layout(db, workbook, sheet_id, read, layout, digest, now)
        workbook.last_read_at = now
        workbook.last_error = None
        return TabState(workbook, pick.email, read, layout, digest, now)

    message = "This workbook is not shared with any admin connection."
    workbook.last_error = message
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        f"{message} Share it with {', '.join(admin_emails(db)) or 'an admin account'}."
        + (f" ({pick.detail})" if pick.detail else ""),
    )


def _remember_layout(
    db: Session,
    workbook: Workbook,
    sheet_id: str,
    read: TabRead,
    layout: Layout,
    digest: str,
    now: datetime,
) -> None:
    row = _layout_row(db, workbook, sheet_id)
    row.title = read.title
    row.header_row = layout.header_row
    row.first_col = layout.first_col
    row.last_col = layout.last_col
    row.columns = dict(layout.columns)
    row.key_col = layout.key_col
    row.key_prefix = layout.key_prefix
    row.last_table_row = layout.last_table_row
    row.dropdowns = {str(k): v for k, v in read.dropdowns.items()}
    row.formula_cols = list(layout.formula_cols)
    row.date_cols = list(layout.date_cols)
    row.region_hash = digest
    row.detected_at = now


def _layout_row(db: Session, workbook: Workbook, sheet_id: str) -> SheetLayout:
    """The tab's layout row, created if this is the tab's first read."""
    key = (workbook.id, sheet_id)
    row = db.get(SheetLayout, key)
    if row is None:
        # A tab's first read is usually two requests at once (the Transfer step loads the grid and
        # the preview together), so both get here. Insert-if-absent: the one that loses the race
        # takes the row the other wrote instead of failing on the primary key.
        insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
        db.execute(
            insert(SheetLayout).values(workbook_id=workbook.id, sheet_id=sheet_id).on_conflict_do_nothing()
        )
        row = db.get(SheetLayout, key)
        assert row is not None  # the insert or the request it raced with wrote it
    return row


def require_editable(db: Session, workbook: Workbook, google: GoogleSuite) -> str:
    """The connection that may write, re-checked before every write."""
    if not workbook.connection_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No admin connection can edit {workbook.name}. Share it with "
            f"{', '.join(admin_emails(db)) or 'an admin account'} and connect it again.",
        )
    connection = db.get(Connection, workbook.connection_id)
    if connection is None or connection.status != "ok":
        raise HTTPException(status.HTTP_409_CONFLICT, "The connection for this workbook needs reconnecting.")
    if not google.sheets.can_edit(connection.email, workbook.spreadsheet_id):
        workbook.can_edit = False
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{connection.email} can no longer edit {workbook.name}.",
        )
    return connection.email
