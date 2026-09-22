"""Request and response models, plus the serialisers the routes return.

Responses are plain dicts built here so one shape is used everywhere and the web client has a single
contract to type against.
"""

from __future__ import annotations

from datetime import date as DateT
from datetime import datetime, time
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.models import (
    Activity,
    AllowListEntry,
    Connection,
    Meeting,
    Note,
    Point,
    SheetEdit,
    Transfer,
    User,
    Workbook,
)

IST = ZoneInfo("Asia/Kolkata")

Kind = Literal["action", "decision", "risk", "question"]
Status = Literal["open", "in_progress", "blocked", "done", "dropped", "decided"]
Lifecycle = Literal["active", "deferred"]
Conflict = Literal["skip", "overwrite", "insert"]
Mode = Literal["append", "fill"]


# --- requests -------------------------------------------------------------------------------------


class AttendeeIn(BaseModel):
    name: str = ""
    email: str = ""
    response: str = "accepted"


class MeetingManualIn(BaseModel):
    title: str
    date: DateT
    start: str = "09:00"
    end: str = "10:00"
    description: str = ""
    location: str = ""
    workstream: str = ""
    attendees: list[AttendeeIn] = Field(default_factory=list)

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        hours, _, minutes = v.partition(":")
        time(int(hours), int(minutes))
        return v

    def start_at(self) -> datetime:
        h, m = (int(x) for x in self.start.split(":"))
        return datetime.combine(self.date, time(h, m), tzinfo=IST)

    def end_at(self) -> datetime:
        h, m = (int(x) for x in self.end.split(":"))
        return datetime.combine(self.date, time(h, m), tzinfo=IST)


class MeetingPatchIn(BaseModel):
    title: str | None = None
    date: DateT | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None
    workstream: str | None = None
    step: Literal["meeting", "notes", "points", "done"] | None = None
    attendees: list[AttendeeIn] | None = None


class FromCalendarIn(BaseModel):
    calendar_event_id: str
    workstream: str = ""


class NoteImportIn(BaseModel):
    meeting_id: str
    source: Literal["gemini_doc", "transcript", "recap_email"]
    origin_ref: str = ""
    tab: str = ""


class NotePasteIn(BaseModel):
    meeting_id: str
    text: str
    title: str = "Pasted note"
    source: Literal["paste", "upload"] = "paste"


class QuickPasteIn(BaseModel):
    text: str
    meeting_id: str | None = None


class NotePatchIn(BaseModel):
    include: bool | None = None
    title: str | None = None


class NoteMoveIn(BaseModel):
    meeting_id: str


class PointIn(BaseModel):
    meeting_id: str
    kind: Kind = "action"
    text: str
    owner_text: str = ""
    due_text: str = ""
    status: Status = "open"
    workstream: str = ""


class PointPatchIn(BaseModel):
    kind: Kind | None = None
    text: str | None = None
    owner_text: str | None = None
    owner_email: str | None = None
    due_text: str | None = None
    status: Status | None = None
    workstream: str | None = None
    selected: bool | None = None
    lifecycle: Lifecycle | None = None


class PointBulkIn(BaseModel):
    ids: list[str]
    patch: PointPatchIn


class PointIdsIn(BaseModel):
    ids: list[str]


class WorkbookConnectIn(BaseModel):
    url: str


class AnchorIn(BaseModel):
    r: int
    c: int


class TransferPreviewIn(BaseModel):
    workbook_id: str
    sheet_id: str
    mode: Mode = "append"
    point_ids: list[str]
    anchor: AnchorIn | None = None
    conflict: Conflict = "skip"
    write_keys: bool = True


class TransferExecuteIn(TransferPreviewIn):
    region_hash: str
    allow_repeat: bool = False
    # The client's idempotency key. Left out, the server makes one up and the write simply cannot
    # be replayed; sent, the same id always answers with the same result. See app/write_batch.py.
    batch_id: UUID | None = None


class PositionIn(BaseModel):
    mode: Literal["after_table", "above"] = "after_table"
    row: int | None = None  # 0-indexed grid row, as clicked


class AddRowIn(BaseModel):
    workbook_id: str
    sheet_id: str
    # Never optional: an insert without the digest of what the person was looking at is a write
    # into a tab that may have moved. 64 hex characters, always compared.
    region_hash: str = Field(min_length=64, max_length=64)
    point_id: str | None = None
    values: dict[str, str] = Field(default_factory=dict)
    position: PositionIn = Field(default_factory=PositionIn)
    batch_id: UUID | None = None


class CellEditIn(BaseModel):
    cell: str
    before: str = ""
    after: str = ""


class SheetSaveIn(BaseModel):
    workbook_id: str
    sheet_id: str
    edits: list[CellEditIn]
    batch_id: UUID | None = None


class AllowListIn(BaseModel):
    email: str
    role: Literal["admin", "member"] = "member"


class AllowListPatchIn(BaseModel):
    email: str | None = None
    role: Literal["admin", "member"] | None = None


# --- serialisers ----------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _local(value: datetime | None, tz: ZoneInfo = IST) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(tz)


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_admin": user.role == "admin",
    }


def meeting_out(m: Meeting, counts: dict[str, int] | None = None) -> dict[str, Any]:
    start = _local(m.start_at)
    end = _local(m.end_at)
    return {
        "id": str(m.id),
        "key": m.key,
        "source": m.source,
        "title": m.title,
        "description": m.description,
        "location": m.location,
        "date": start.date().isoformat() if start else None,
        "start": start.strftime("%H:%M") if start else None,
        "end": end.strftime("%H:%M") if end else None,
        "start_at": _iso(start),
        "end_at": _iso(end),
        "timezone": m.timezone,
        "organizer_email": m.organizer_email,
        "organizer_name": m.organizer_name,
        "attendees": m.attendees or [],
        "conference": m.conference or {},
        "attachments": m.attachments or [],
        "calendar_event_id": m.calendar_event_id,
        "ical_uid": m.ical_uid,
        "recurring_event_id": m.recurring_event_id,
        "html_link": m.html_link,
        "workstream": m.workstream,
        "step": m.step,
        "in_progress_by": m.in_progress_by,
        "last_synced_at": _iso(_local(m.last_synced_at)),
        "updated_at": _iso(_local(m.updated_at)),
        "editable": m.source == "manual",
        "notes_count": (counts or {}).get("notes", 0),
        "points_count": (counts or {}).get("points", 0),
    }


def note_out(n: Note) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "meeting_id": str(n.meeting_id),
        "source": n.source,
        "origin_ref": n.origin_ref,
        "title": n.title,
        "text": n.text,
        "word_count": n.word_count,
        "text_hash": n.text_hash,
        "include": n.include,
        "created_by": n.created_by,
        "created_at": _iso(_local(n.created_at)),
    }


def point_out(p: Point) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "meeting_id": str(p.meeting_id),
        "extraction_id": str(p.extraction_id) if p.extraction_id else None,
        "kind": p.kind,
        "text": p.text,
        "text_norm": p.text_norm,
        "evidence": p.evidence,
        "owner_text": p.owner_text,
        "owner_email": p.owner_email,
        "owner_ambiguous": p.owner_ambiguous,
        "due_text": p.due_text,
        "due_date": _iso(_local(p.due_date)),
        "status": p.status,
        "workstream": p.workstream,
        "lifecycle": p.lifecycle,
        "selected": p.selected,
        "updated_by": p.updated_by,
        "updated_at": _iso(_local(p.updated_at)),
        "deleted_at": _iso(_local(p.deleted_at)),
    }


def workbook_out(w: Workbook, tabs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "spreadsheet_id": w.spreadsheet_id,
        "name": w.name,
        "url": w.url,
        "connection_id": str(w.connection_id) if w.connection_id else None,
        "connected_by": w.connected_by,
        "connected_at": _iso(_local(w.connected_at)),
        "last_read_at": _iso(_local(w.last_read_at)),
        "can_edit": w.can_edit,
        "last_error": w.last_error,
        "tabs": tabs or [],
    }


def transfer_out(t: Transfer) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "batch_id": str(t.batch_id),
        "at": _iso(_local(t.at)),
        "actor": t.actor,
        "meeting_id": str(t.meeting_id) if t.meeting_id else None,
        "meeting_title": t.meeting_title,
        "point_text": t.point_text,
        "workbook_id": str(t.workbook_id),
        "sheet_id": t.sheet_id,
        "mode": t.mode,
        "cells": t.cells or [],
        "snapshot": t.snapshot or {},
        "previous": t.previous or {},
        "undone_at": _iso(_local(t.undone_at)),
    }


def sheet_edit_out(e: SheetEdit) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "at": _iso(_local(e.at)),
        "actor": e.actor,
        "workbook_id": str(e.workbook_id),
        "sheet_id": e.sheet_id,
        "cell": e.cell,
        "before": e.before,
        "after": e.after,
        "batch_id": str(e.batch_id),
    }


def connection_out(c: Connection) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "email": c.email,
        "name": c.name,
        "scopes": c.scopes or [],
        "status": c.status,
        "connected_at": _iso(_local(c.connected_at)),
        "last_ok_at": _iso(_local(c.last_ok_at)),
        "last_error": c.last_error,
    }


def allow_entry_out(e: AllowListEntry) -> dict[str, Any]:
    return {
        "email": e.email,
        "role": e.role,
        "added_by": e.added_by,
        "added_at": _iso(_local(e.added_at)),
        "signed_in": e.matched_user_id is not None,
    }


def activity_out(a: Activity) -> dict[str, Any]:
    return {"id": str(a.id), "at": _iso(_local(a.at)), "actor": a.actor, "text": a.text}
