"""The Google surface the rest of the app is allowed to see.

Everything below is a Protocol plus the plain data it exchanges. ``app/google/fake.py`` implements
it in memory for tests and local runs; the real clients under ``app/google/`` (calendar, drive,
docs, gmail, sheets, people) implement it against the REST endpoints. Every call takes the admin
``connection_email`` it runs as - the spec requires reads to fall back across connections and every
write to name the connection that made it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# --- errors ---------------------------------------------------------------------------------------


class GoogleError(RuntimeError):
    """Anything the Google side refused."""


class NotFoundError(GoogleError):
    pass


class PermissionDenied(GoogleError):
    """403: not shared, or a protected range. ``detail`` names what and whose."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class RateLimited(GoogleError):
    """429 or 403 ``rateLimitExceeded`` after the retries ran out; the connection is backed off."""

    def __init__(self, message: str, retry_after_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AuthExpired(GoogleError):
    """The refresh token was refused (``invalid_grant``): the connection needs reconnecting."""


# --- calendar -------------------------------------------------------------------------------------


@dataclass(slots=True)
class Attendee:
    email: str
    name: str = ""
    response: str = "needsAction"

    def to_dict(self) -> dict[str, Any]:
        return {"email": self.email, "name": self.name, "response": self.response}


@dataclass(slots=True)
class Attachment:
    title: str
    kind: str = "doc"  # doc | transcript | other
    file_id: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "kind": self.kind, "file_id": self.file_id, "url": self.url}


@dataclass(slots=True)
class CalendarEvent:
    id: str
    ical_uid: str
    calendar_id: str
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str = ""  # the event's own zone; empty: DISPLAY_TIMEZONE
    description: str = ""
    location: str = ""
    organizer_email: str = ""
    organizer_name: str = ""
    recurring_event_id: str = ""
    html_link: str = ""
    attendees: list[Attendee] = field(default_factory=list)
    conference: dict[str, Any] = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)
    updated_at: datetime | None = None


@runtime_checkable
class CalendarClient(Protocol):
    def list_events(
        self, connection_email: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        """``singleEvents=true`` over the window, newest first."""
        ...

    def get_event(self, connection_email: str, event_id: str) -> CalendarEvent | None: ...


# --- drive ----------------------------------------------------------------------------------------


GEMINI_NOTES_MARKER = "Notes by Gemini"


@dataclass(slots=True)
class DriveFile:
    id: str
    name: str
    mime_type: str = "application/vnd.google-apps.document"
    modified_at: datetime | None = None
    web_view_link: str = ""
    created_at: datetime | None = None


@runtime_checkable
class DriveClient(Protocol):
    def search(
        self,
        connection_email: str,
        name_contains: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[DriveFile]:
        """Google Docs whose name contains both ``name_contains`` and ``GEMINI_NOTES_MARKER``.

        The window is on *creation* time: a Notes by Gemini doc is named after the meeting (a
        recurring one gets the same name every week) and is edited long after it appeared, so the
        moment it was created is what ties it to one instance.
        """
        ...

    def get_file(self, connection_email: str, file_id: str) -> DriveFile | None: ...


# --- docs -----------------------------------------------------------------------------------------


@dataclass(slots=True)
class DocTab:
    id: str
    title: str
    text: str


@dataclass(slots=True)
class DocDocument:
    id: str
    title: str
    tabs: list[DocTab] = field(default_factory=list)

    def tab(self, title: str) -> DocTab | None:
        wanted = title.strip().lower()
        return next((t for t in self.tabs if t.title.strip().lower() == wanted), None)


@runtime_checkable
class DocsClient(Protocol):
    def get_document(
        self, connection_email: str, document_id: str, include_tabs_content: bool = True
    ) -> DocDocument: ...


# --- gmail ----------------------------------------------------------------------------------------


@dataclass(slots=True)
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    from_email: str
    received_at: datetime
    body: str


@runtime_checkable
class GmailClient(Protocol):
    def search_messages(self, connection_email: str, query: str) -> list[GmailMessage]:
        """A Gmail search query, as typed in the search box. See ``recap_query``."""
        ...


RECAP_SENDER = "gemini-notes@google.com"
_QUOTED_RE = re.compile(r'"([^"]+)"')


def recap_query(title: str, after: datetime | None = None) -> str:
    """``from:gemini-notes@google.com "<title>" after:<date>`` - the recap of one meeting."""
    clean = (title or "").replace('"', " ").strip()
    parts = [f"from:{RECAP_SENDER}", f'"{clean}"']
    if after is not None:
        parts.append(f"after:{after.strftime('%Y/%m/%d')}")
    return " ".join(parts)


def quoted_phrase(query: str) -> str:
    """The phrase a query searches for: the first quoted part, else the whole query."""
    m = _QUOTED_RE.search(query or "")
    return m.group(1).strip() if m else (query or "").strip()


# --- people ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class DirectoryPerson:
    name: str
    email: str


@runtime_checkable
class PeopleClient(Protocol):
    def search_directory(self, connection_email: str, query: str) -> list[DirectoryPerson]: ...


# --- sheets ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class TabMeta:
    sheet_id: str
    title: str
    index: int = 0


@dataclass(slots=True)
class SpreadsheetMeta:
    spreadsheet_id: str
    title: str
    url: str
    tabs: list[TabMeta] = field(default_factory=list)


@dataclass(slots=True)
class TabRead:
    sheet_id: str
    title: str
    values: list[list[str]]
    formulas: list[list[str]]
    number_formats: list[list[str]]
    dropdowns: dict[int, list[str]] = field(default_factory=dict)
    read_at: datetime | None = None


@dataclass(slots=True)
class InsertRows:
    sheet_id: str
    at: int
    count: int
    # ``insertDimension.inheritFromBefore``. False takes the formatting from the row *below*
    # instead, which is what an insert directly under the header needs: the header's formatting is
    # not a data row's.
    inherit_from_before: bool = True


@dataclass(slots=True)
class DeleteRows:
    """Only used by undo, to take back rows that were inserted and are still untouched."""

    sheet_id: str
    at: int
    count: int


@dataclass(slots=True)
class SetCell:
    sheet_id: str
    row: int
    col: int
    value: str
    as_date: bool = False
    # ISO yyyy-mm-dd when the caller already knows the date (``points.due_date``); the writer falls
    # back to reading the text only when this is empty.
    date_value: str = ""


@dataclass(slots=True)
class CopyFormula:
    """``copyPaste`` of one formula column from ``source_row`` into ``target_rows``."""

    sheet_id: str
    col: int
    source_row: int
    target_rows: list[int]


BatchOp = InsertRows | DeleteRows | SetCell | CopyFormula


@runtime_checkable
class SheetsClient(Protocol):
    def get_spreadsheet(self, connection_email: str, spreadsheet_id: str) -> SpreadsheetMeta: ...

    def can_edit(self, connection_email: str, spreadsheet_id: str) -> bool:
        """``capabilities.canEdit``, checked on connect and before every write."""
        ...

    def read_tab(self, connection_email: str, spreadsheet_id: str, sheet_id: str) -> TabRead: ...

    def read_cells(
        self, connection_email: str, spreadsheet_id: str, sheet_id: str, refs: list[str]
    ) -> dict[str, str]:
        """The pre-save re-read: A1 ref -> displayed value."""
        ...

    def batch_update(self, connection_email: str, spreadsheet_id: str, ops: list[BatchOp]) -> None:
        """One ``batchUpdate`` per transfer. Raises PermissionDenied on a protected range."""
        ...


# --- the suite ------------------------------------------------------------------------------------


@runtime_checkable
class GoogleSuite(Protocol):
    calendar: CalendarClient
    drive: DriveClient
    docs: DocsClient
    gmail: GmailClient
    sheets: SheetsClient
    people: PeopleClient
