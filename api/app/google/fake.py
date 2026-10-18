"""In-memory Google, built from ``app/seed_data.py`` and ``tests/fixtures/sheets/*.json``.

It backs fake mode and the tests. It keeps state across requests within one app, so
a transfer written in one request is visible to the read in the next - which is what makes the
re-read guard, undo and the Sheets page testable without a network.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app import seed_data
from app.google.interface import (
    GEMINI_NOTES_MARKER,
    Attachment,
    Attendee,
    BatchOp,
    CalendarEvent,
    CopyFormula,
    DeleteRows,
    DirectoryPerson,
    DocDocument,
    DocTab,
    DriveFile,
    GmailMessage,
    InsertRows,
    NotFoundError,
    PermissionDenied,
    SetCell,
    SpreadsheetMeta,
    TabMeta,
    TabRead,
    quoted_phrase,
)
from app.sheets.layout import parse_a1

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sheets"
FIXTURE_SPREADSHEET_ID = "plannerfixtures"


def _grid(rows: list[list[str]]) -> list[list[str]]:
    return [list(r) for r in rows]


def _shift_formula(formula: str, delta: int) -> str:
    """Move every A1 row reference in a formula by ``delta`` rows. Enough for a fake."""

    def repl(m: re.Match[str]) -> str:
        return f"{m.group(1)}{int(m.group(2)) + delta}"

    return re.sub(r"\b([A-Z]{1,3})(\d+)\b", repl, formula)


class FakeTab:
    def __init__(
        self,
        sheet_id: str,
        title: str,
        rows: list[list[str]],
        dropdowns: dict[int, list[str]] | None = None,
        formulas: list[list[str]] | None = None,
        number_formats: list[list[str]] | None = None,
        protected_by: str | None = None,
    ) -> None:
        self.sheet_id = sheet_id
        self.title = title
        self.values = _grid(rows)
        self.formulas = _grid(formulas) if formulas else _grid(rows)
        width = max((len(r) for r in self.values), default=0)
        self.number_formats = (
            _grid(number_formats) if number_formats else [["TEXT"] * width for _ in self.values]
        )
        self.dropdowns = dict(dropdowns or {})
        self.protected_by = protected_by

    def _ensure(self, row: int, col: int) -> None:
        width = max(col + 1, *(len(r) for r in self.values), col + 1)
        while len(self.values) <= row:
            self.values.append([""] * width)
            self.formulas.append([""] * width)
            self.number_formats.append(["TEXT"] * width)
        for grid, filler in ((self.values, ""), (self.formulas, ""), (self.number_formats, "TEXT")):
            while len(grid) <= row:
                grid.append([filler] * width)
            if len(grid[row]) <= col:
                grid[row].extend([filler] * (col + 1 - len(grid[row])))

    def insert_rows(self, at: int, count: int) -> None:
        width = max((len(r) for r in self.values), default=0)
        for _ in range(count):
            self.values.insert(at, [""] * width)
            self.formulas.insert(at, [""] * width)
            self.number_formats.insert(at, ["TEXT"] * width)

    def delete_rows(self, at: int, count: int) -> None:
        for grid in (self.values, self.formulas, self.number_formats):
            del grid[at : at + count]

    def set_cell(self, row: int, col: int, value: str, as_date: bool = False) -> None:
        self._ensure(row, col)
        self.values[row][col] = value
        self.formulas[row][col] = value
        if as_date:
            self.number_formats[row][col] = "DATE"

    def copy_formula(self, col: int, source_row: int, target_rows: list[int]) -> None:
        for target in target_rows:
            self._ensure(target, col)
            source = self.formulas[source_row][col] if source_row < len(self.formulas) else ""
            self.formulas[target][col] = (
                _shift_formula(source, target - source_row) if source.startswith("=") else source
            )
            # A fake cannot evaluate; the displayed value copies the source's.
            self.values[target][col] = self.values[source_row][col] if source_row < len(self.values) else ""

    def read(self, read_at: datetime | None = None) -> TabRead:
        return TabRead(
            sheet_id=self.sheet_id,
            title=self.title,
            values=_grid(self.values),
            formulas=_grid(self.formulas),
            number_formats=_grid(self.number_formats),
            dropdowns={int(k): list(v) for k, v in self.dropdowns.items()},
            read_at=read_at,
        )


class FakeSpreadsheet:
    def __init__(
        self,
        spreadsheet_id: str,
        name: str,
        url: str,
        tabs: list[FakeTab],
        editors: list[str],
        readers: list[str],
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.name = name
        self.url = url
        self.tabs = tabs
        self.editors = set(editors)
        self.readers = set(readers) | set(editors)

    def tab(self, sheet_id: str) -> FakeTab:
        for t in self.tabs:
            if t.sheet_id == sheet_id:
                return t
        raise NotFoundError(f"no tab {sheet_id} in {self.name}")


class FakeGoogle:
    """Implements every client Protocol; hand it out as the whole suite."""

    is_fake = True

    def __init__(self, load_fixtures: bool = True) -> None:
        self.calendar = self
        self.drive = self
        self.docs = self
        self.gmail = self
        self.sheets = self
        self.people = self
        self.calls: list[str] = []
        self._load_fixtures = load_fixtures
        self._build(load_fixtures)

    def reset(self) -> None:
        """Back to the seeded world: the spreadsheets, files, events and directory as they start.

        The fake's state lives in this object, which lives on ``app.state.google``: one per API
        process. So it is already reset by restarting the API - and this is that, without the
        restart. The walkthrough (``web/e2e/walkthrough.mjs``) appends rows to the fixture tabs, so
        a second run against a long-lived dev server sees the first run's rows; calling this (or
        ``POST /admin/fake/reset``, which only exists with ``FAKE_GOOGLE=1``) gives it a pristine
        grid. It does not touch the database - that is ``rm api/meeting-desk.db``.
        """
        self.calls.clear()
        self._build(self._load_fixtures)

    # --- construction -----------------------------------------------------------------------
    def _build(self, load_fixtures: bool) -> None:
        self.events: list[tuple[CalendarEvent, set[str]]] = []
        for m in seed_data.MEETINGS:
            if m["source"] != "calendar":
                continue
            start = seed_data.meeting_start(m)
            event = CalendarEvent(
                id=m["calendar_event_id"],
                ical_uid=seed_data.ical_uid(m),
                calendar_id="primary",
                title=m["title"],
                start_at=start,
                end_at=seed_data.meeting_end(m),
                timezone=start.tzinfo.key if isinstance(start.tzinfo, ZoneInfo) else "",
                description=m["description"],
                location=m["location"],
                organizer_email=m["organizer"],
                organizer_name=seed_data.person(m["organizer"]).get("name", ""),
                recurring_event_id=m["calendar_event_id"] + "_series" if m["recurring"] else "",
                html_link=f"https://calendar.google.com/event?eid={m['calendar_event_id']}",
                attendees=[Attendee(**a) for a in m["attendees"]],
                conference={"meet_link": m["meet_link"]} if m["meet_link"] else {},
                attachments=[
                    Attachment(
                        title=a["title"],
                        kind=a["kind"],
                        file_id=f"doc-{m['ref']}" if a["kind"] == "doc" else "",
                    )
                    for a in m["attachments"]
                ],
                updated_at=start - timedelta(minutes=30),
            )
            # The event sits on the calendar of its organizer and of every attendee.
            mailboxes = {m["organizer"], *(a["email"] for a in m["attendees"])}
            self.events.append((event, mailboxes))

        self.docs_by_id: dict[str, tuple[DocDocument, set[str]]] = {}
        self.files: list[tuple[DriveFile, set[str]]] = []
        for d in seed_data.GEMINI_DOCS:
            meeting = next(m for m in seed_data.MEETINGS if m["ref"] == d["meeting_ref"])
            doc = DocDocument(
                id=d["file_id"],
                title=d["name"],
                tabs=[DocTab(id=t["id"], title=t["title"], text=t["text"]) for t in d["tabs"]],
            )
            self.docs_by_id[d["file_id"]] = (doc, set(d["readers"]))
            appeared = seed_data.meeting_end(meeting) + timedelta(minutes=4)
            self.files.append(
                (
                    DriveFile(
                        id=d["file_id"],
                        name=d["name"],
                        modified_at=appeared,
                        created_at=appeared,
                        web_view_link=f"https://docs.google.com/document/d/{d['file_id']}",
                    ),
                    set(d["readers"]),
                )
            )

        self.messages: list[tuple[GmailMessage, str]] = []
        for msg in seed_data.RECAP_EMAILS:
            meeting = next(m for m in seed_data.MEETINGS if m["ref"] == msg["meeting_ref"])
            self.messages.append(
                (
                    GmailMessage(
                        id=msg["id"],
                        thread_id=msg["id"],
                        subject=msg["subject"],
                        from_email=msg["from_email"],
                        received_at=seed_data.meeting_end(meeting) + timedelta(minutes=6),
                        body=msg["body"],
                    ),
                    msg["mailbox"],
                )
            )

        self.spreadsheets: dict[str, FakeSpreadsheet] = {}
        for wb in [*seed_data.WORKBOOKS, *seed_data.UNCONNECTED_WORKBOOKS]:
            tabs = [
                FakeTab(
                    sheet_id=t["sheet_id"],
                    title=t["title"],
                    rows=t["rows"],
                    dropdowns=t.get("dropdowns"),
                    protected_by="alex.s@example.com" if t["sheet_id"] == "t4" else None,
                )
                for t in wb["tabs"]
            ]
            self.spreadsheets[wb["spreadsheet_id"]] = FakeSpreadsheet(
                spreadsheet_id=wb["spreadsheet_id"],
                name=wb["name"],
                url=wb["url"],
                tabs=tabs,
                editors=wb["editors"],
                readers=wb["readers"],
            )

        if load_fixtures and FIXTURE_DIR.exists():
            self.spreadsheets[FIXTURE_SPREADSHEET_ID] = self._fixture_spreadsheet()

        self.directory = [DirectoryPerson(**p) for p in seed_data.DIRECTORY]

    def _fixture_spreadsheet(self) -> FakeSpreadsheet:
        tabs: list[FakeTab] = []
        for path in sorted(FIXTURE_DIR.glob("*.json")):
            fx = json.loads(path.read_text())
            width = max((len(r) for r in fx["rows"]), default=0)
            formats = fx.get("number_formats") or [["TEXT"] * width for _ in fx["rows"]]
            tabs.append(
                FakeTab(
                    sheet_id=fx["name"],
                    title=fx["title"],
                    rows=fx["rows"],
                    dropdowns={int(k): v for k, v in fx["dropdowns"].items()},
                    formulas=fx.get("formulas"),
                    number_formats=formats,
                )
            )
        return FakeSpreadsheet(
            spreadsheet_id=FIXTURE_SPREADSHEET_ID,
            name="Planner Fixtures",
            url=f"https://docs.google.com/spreadsheets/d/{FIXTURE_SPREADSHEET_ID}",
            tabs=tabs,
            editors=["daniel.okafor@example.com"],
            readers=["daniel.okafor@example.com", "alex.s@example.com"],
        )

    # --- calendar ---------------------------------------------------------------------------
    def list_events(
        self, connection_email: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        self.calls.append(f"calendar.list:{connection_email}")
        out = [
            e
            for e, mailboxes in self.events
            if connection_email in mailboxes and time_min <= e.start_at <= time_max
        ]
        return sorted(out, key=lambda e: e.start_at, reverse=True)

    def get_event(self, connection_email: str, event_id: str) -> CalendarEvent | None:
        for e, mailboxes in self.events:
            if e.id == event_id and connection_email in mailboxes:
                return e
        return None

    # --- drive ------------------------------------------------------------------------------
    def search(
        self,
        connection_email: str,
        name_contains: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[DriveFile]:
        self.calls.append(f"drive.search:{connection_email}")
        needle = name_contains.strip().lower()
        marker = GEMINI_NOTES_MARKER.lower()
        out = []
        for f, readers in self.files:
            if connection_email not in readers:
                continue
            if marker not in f.name.lower() or (needle and needle not in f.name.lower()):
                continue
            appeared = f.created_at or f.modified_at
            if created_after and appeared and appeared < created_after:
                continue
            if created_before and appeared and appeared > created_before:
                continue
            out.append(f)
        return out

    def get_file(self, connection_email: str, file_id: str) -> DriveFile | None:
        for f, readers in self.files:
            if f.id == file_id and connection_email in readers:
                return f
        return None

    # --- docs -------------------------------------------------------------------------------
    def get_document(
        self, connection_email: str, document_id: str, include_tabs_content: bool = True
    ) -> DocDocument:
        self.calls.append(f"docs.get:{connection_email}")
        entry = self.docs_by_id.get(document_id)
        if entry is None:
            raise NotFoundError(f"no document {document_id}")
        doc, readers = entry
        if connection_email not in readers:
            raise PermissionDenied(
                "not shared with an admin account",
                detail=f"{document_id} is not shared with {connection_email}",
            )
        if include_tabs_content:
            return doc
        return DocDocument(id=doc.id, title=doc.title, tabs=doc.tabs[:1])

    # --- gmail ------------------------------------------------------------------------------
    def search_messages(self, connection_email: str, query: str) -> list[GmailMessage]:
        self.calls.append(f"gmail.search:{connection_email}")
        needle = quoted_phrase(query).lower()
        return [
            m
            for m, mailbox in self.messages
            if mailbox == connection_email and (not needle or needle in m.subject.lower())
        ]

    # --- people -----------------------------------------------------------------------------
    def search_directory(self, connection_email: str, query: str) -> list[DirectoryPerson]:
        self.calls.append(f"people.search:{connection_email}")
        needle = query.strip().lower()
        if not needle:
            return []
        return [p for p in self.directory if needle in p.name.lower() or needle in p.email.lower()]

    # --- sheets -----------------------------------------------------------------------------
    def _spreadsheet(self, connection_email: str, spreadsheet_id: str) -> FakeSpreadsheet:
        book = self.spreadsheets.get(spreadsheet_id)
        if book is None:
            raise NotFoundError(f"no spreadsheet {spreadsheet_id}")
        if connection_email not in book.readers:
            raise PermissionDenied(
                "not shared with an admin account",
                detail=f"{book.name} is not shared with {connection_email}",
            )
        return book

    def get_spreadsheet(self, connection_email: str, spreadsheet_id: str) -> SpreadsheetMeta:
        book = self._spreadsheet(connection_email, spreadsheet_id)
        return SpreadsheetMeta(
            spreadsheet_id=book.spreadsheet_id,
            title=book.name,
            url=book.url,
            tabs=[TabMeta(sheet_id=t.sheet_id, title=t.title, index=i) for i, t in enumerate(book.tabs)],
        )

    def can_edit(self, connection_email: str, spreadsheet_id: str) -> bool:
        book = self.spreadsheets.get(spreadsheet_id)
        return bool(book and connection_email in book.editors)

    def read_tab(self, connection_email: str, spreadsheet_id: str, sheet_id: str) -> TabRead:
        self.calls.append(f"sheets.read:{spreadsheet_id}/{sheet_id}")
        return self._spreadsheet(connection_email, spreadsheet_id).tab(sheet_id).read()

    def read_cells(
        self, connection_email: str, spreadsheet_id: str, sheet_id: str, refs: list[str]
    ) -> dict[str, str]:
        tab = self._spreadsheet(connection_email, spreadsheet_id).tab(sheet_id)
        out: dict[str, str] = {}
        for ref in refs:
            r, c = parse_a1(ref)
            row = tab.values[r] if r < len(tab.values) else []
            out[ref] = row[c] if c < len(row) else ""
        return out

    def batch_update(self, connection_email: str, spreadsheet_id: str, ops: list[BatchOp]) -> None:
        book = self._spreadsheet(connection_email, spreadsheet_id)
        if connection_email not in book.editors:
            raise PermissionDenied(
                "the connection cannot edit this workbook",
                detail=f"{connection_email} has read-only access to {book.name}",
            )
        for op in ops:
            tab = book.tab(op.sheet_id)
            if tab.protected_by:
                raise PermissionDenied(
                    f"{tab.title} is a protected range",
                    detail=f"protected by {tab.protected_by}",
                )
        self.calls.append(f"sheets.batchUpdate:{spreadsheet_id}:{len(ops)}")
        for op in ops:
            tab = book.tab(op.sheet_id)
            if isinstance(op, InsertRows):
                tab.insert_rows(op.at, op.count)
            elif isinstance(op, DeleteRows):
                tab.delete_rows(op.at, op.count)
            elif isinstance(op, SetCell):
                tab.set_cell(op.row, op.col, op.value, op.as_date)
            elif isinstance(op, CopyFormula):
                tab.copy_formula(op.col, op.source_row, op.target_rows)

    # --- test helpers -----------------------------------------------------------------------
    def add_spreadsheet(self, **kwargs: Any) -> FakeSpreadsheet:
        tabs = [FakeTab(**t) for t in kwargs.pop("tabs")]
        book = FakeSpreadsheet(tabs=tabs, **kwargs)
        self.spreadsheets[book.spreadsheet_id] = book
        return book

    def grant_edit(self, spreadsheet_id: str, email: str) -> None:
        book = self.spreadsheets[spreadsheet_id]
        book.editors.add(email)
        book.readers.add(email)
