"""Step 1 - the meeting list, calendar upserts and manual meetings."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.google import get_google
from app.google.interface import AuthExpired, CalendarEvent, GoogleError, GoogleSuite
from app.models import Connection, Meeting, Note, Point, User
from app.routes.common import (
    admin_emails,
    get_clock,
    get_config,
    get_meeting,
    healthy_connections,
    next_key,
)
from app.schemas import FromCalendarIn, MeetingManualIn, MeetingPatchIn, meeting_out

router = APIRouter(prefix="/meetings", tags=["meetings"])


# --- calendar merge -------------------------------------------------------------------------------


def _window(now: datetime, lookback_days: int) -> tuple[datetime, datetime]:
    start = (now - timedelta(days=lookback_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start, end


def connection_fingerprint(db: Session) -> str:
    """The healthy connections the cache was filled from.

    Connecting or reconnecting an account changes which calendars the merge can see, so the entry
    filled before it must not be served afterwards - the person who just connected would be told
    their meetings are not there.
    """
    return "|".join(sorted(admin_emails(db)))


def clear_calendar_cache(request: Request) -> None:
    """Called wherever the connection set changes (connect, disconnect, health)."""
    cache = getattr(request.app.state, "calendar_cache", None)
    if isinstance(cache, dict):
        cache.clear()


def calendar_events(
    request: Request,
    db: Session,
    google: GoogleSuite,
    clock: Clock,
    settings: Settings,
    force: bool = False,
) -> tuple[list[CalendarEvent], datetime]:
    """Every healthy admin calendar, merged and de-duplicated on ``ical_uid``. Cached 60 s.

    ``force`` is the Refresh button. It skips the cache, but not more often than
    ``calendar_refresh_min_seconds``: holding Refresh down must not turn into one Calendar call per
    click per connection and earn the workspace a 429.
    """
    cache: dict[str, Any] = request.app.state.calendar_cache
    now = clock.now()
    cached_at: datetime | None = cache.get("at")
    fingerprint = connection_fingerprint(db)
    if cached_at and cache.get("connections") != fingerprint:
        cached_at = None
    if cached_at is not None:
        if force:
            # Refresh goes through, but not again within calendar_refresh_min_seconds: a held-down
            # button would otherwise be one Calendar call per click per connection.
            forced_at: datetime | None = cache.get("forced_at")
            if forced_at and (now - forced_at).total_seconds() < settings.calendar_refresh_min_seconds:
                return cache["events"], cached_at
        elif (now - cached_at).total_seconds() < settings.calendar_cache_seconds:
            return cache["events"], cached_at
    if force:
        cache["forced_at"] = now

    time_min, time_max = _window(now, settings.calendar_lookback_days)
    merged: dict[str, CalendarEvent] = {}
    for connection in healthy_connections(db):
        try:
            events = google.calendar.list_events(connection.email, time_min, time_max)
        except AuthExpired as exc:
            connection.status = "expired"
            connection.last_error = str(exc)
            continue
        except GoogleError as exc:  # rate-limited or down: keep the status, remember why
            connection.last_error = str(exc)
            continue
        connection.last_ok_at = now
        connection.last_error = None
        for event in events:
            merged.setdefault(event.ical_uid or event.id, event)

    ordered = sorted(merged.values(), key=lambda e: e.start_at, reverse=True)
    cache["at"] = now
    cache["events"] = ordered
    cache["connections"] = connection_fingerprint(db)
    return ordered, now


def _event_out(event: CalendarEvent, in_progress: str | None = None) -> dict[str, Any]:
    return {
        "id": None,
        "key": None,
        "source": "calendar",
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "date": event.start_at.date().isoformat(),
        "start": event.start_at.strftime("%H:%M"),
        "end": event.end_at.strftime("%H:%M"),
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "timezone": event.timezone,
        "organizer_email": event.organizer_email,
        "organizer_name": event.organizer_name,
        "attendees": [a.to_dict() for a in event.attendees],
        "conference": event.conference,
        "attachments": [a.to_dict() for a in event.attachments],
        "calendar_event_id": event.id,
        "ical_uid": event.ical_uid,
        "recurring_event_id": event.recurring_event_id,
        "html_link": event.html_link,
        "workstream": "",
        "step": "meeting",
        "in_progress_by": in_progress,
        "editable": False,
        "saved": False,
        "notes_count": 0,
        "points_count": 0,
    }


def _counts(db: Session) -> dict[Any, dict[str, int]]:
    out: dict[Any, dict[str, int]] = {}
    for meeting_id, n in db.execute(
        select(Note.meeting_id, func.count()).where(Note.deleted_at.is_(None)).group_by(Note.meeting_id)
    ):
        out.setdefault(meeting_id, {})["notes"] = n
    for meeting_id, n in db.execute(
        select(Point.meeting_id, func.count())
        .where(Point.deleted_at.is_(None), Point.lifecycle == "active")
        .group_by(Point.meeting_id)
    ):
        out.setdefault(meeting_id, {})["points"] = n
    return out


@router.get("/list")
def list_meetings(
    request: Request,
    refresh: bool = False,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    events, fetched_at = calendar_events(request, db, google, clock, settings, force=refresh)
    saved = list(db.scalars(select(Meeting).where(Meeting.deleted_at.is_(None))).all())
    counts = _counts(db)

    by_event = {m.calendar_event_id: m for m in saved if m.calendar_event_id}
    by_uid = {m.ical_uid: m for m in saved if m.ical_uid}

    items: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for event in events:
        existing = by_event.get(event.id) or by_uid.get(event.ical_uid)
        if existing is not None:
            items.append({**meeting_out(existing, counts.get(existing.id)), "saved": True})
            seen.add(existing.id)
        else:
            items.append(_event_out(event))
    for meeting in saved:
        if meeting.id in seen:
            continue
        items.append({**meeting_out(meeting, counts.get(meeting.id)), "saved": True})

    items.sort(key=lambda i: i["start_at"] or "", reverse=True)
    now = clock.now()
    return {
        "items": items,
        "fetched_at": fetched_at.isoformat(),
        "age_minutes": int((now - fetched_at).total_seconds() // 60),
        "connections": admin_emails(db),
        "empty_hint": (
            "No meeting here? Add one, or paste the notes straight into the box above." if not items else ""
        ),
    }


@router.post("/from-calendar", status_code=status.HTTP_201_CREATED)
def upsert_from_calendar(
    body: FromCalendarIn,
    request: Request,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Selecting a calendar card upserts the record on ``calendar_event_id``."""
    events, _ = calendar_events(request, db, google, clock, settings)
    event = next((e for e in events if e.id == body.calendar_event_id), None)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That event is not on any connected calendar.")

    meeting = db.scalar(select(Meeting).where(Meeting.calendar_event_id == event.id))
    if meeting is None and event.ical_uid:
        meeting = db.scalar(select(Meeting).where(Meeting.ical_uid == event.ical_uid))
    created = meeting is None
    if meeting is None:
        meeting = Meeting(key=next_key(db, "M"), source="calendar", created_by=user.email)
        db.add(meeting)
    _apply_event(meeting, event, clock.now())
    if body.workstream:
        meeting.workstream = body.workstream
    meeting.deleted_at = None
    db.flush()
    if created:
        log(db, user.email, f"Captured {meeting.title} from the calendar")
    return {**meeting_out(meeting), "saved": True, "created": created}


def _apply_event(meeting: Meeting, event: CalendarEvent, now: datetime) -> None:
    """Only Calendar fields; notes and points stay attached."""
    meeting.calendar_event_id = event.id
    meeting.calendar_id = event.calendar_id
    meeting.ical_uid = event.ical_uid or None
    meeting.recurring_event_id = event.recurring_event_id or None
    meeting.html_link = event.html_link
    meeting.title = event.title
    meeting.description = event.description
    meeting.location = event.location
    meeting.start_at = event.start_at
    meeting.end_at = event.end_at
    meeting.timezone = event.timezone
    meeting.organizer_email = event.organizer_email
    meeting.organizer_name = event.organizer_name
    meeting.attendees = [a.to_dict() for a in event.attendees]
    meeting.conference = event.conference
    meeting.attachments = [a.to_dict() for a in event.attachments]
    meeting.event_updated_at = event.updated_at
    meeting.last_synced_at = now


@router.post("/manual", status_code=status.HTTP_201_CREATED)
def create_manual(
    body: MeetingManualIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = Meeting(
        key=next_key(db, "M"),
        source="manual",
        created_by=user.email,
        title=body.title,
        description=body.description,
        location=body.location,
        start_at=body.start_at(),
        end_at=body.end_at(),
        organizer_email=user.email,
        organizer_name=user.name,
        attendees=[a.model_dump() for a in body.attendees],
        workstream=body.workstream,
        step="meeting",
    )
    db.add(meeting)
    db.flush()
    log(db, user.email, f"Added meeting {meeting.title}")
    return {**meeting_out(meeting), "saved": True}


@router.get("/{meeting_id}")
def get_one(
    meeting_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    counts = _counts(db).get(meeting.id)
    return {**meeting_out(meeting, counts), "saved": True}


@router.patch("/{meeting_id}")
def patch_meeting(
    meeting_id: str,
    body: MeetingPatchIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    data = body.model_dump(exclude_unset=True)
    if meeting.source == "calendar" and set(data) - {"workstream", "step"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Calendar meetings are read-only here. Edit the event in Google Calendar and re-sync.",
        )
    for name in ("title", "description", "location", "workstream", "step"):
        if name in data and data[name] is not None:
            setattr(meeting, name, data[name])
    if "attendees" in data and data["attendees"] is not None:
        meeting.attendees = data["attendees"]
    if any(k in data for k in ("date", "start", "end")):
        current_start = meeting.start_at
        current_end = meeting.end_at
        day = data.get("date") or (current_start.date() if current_start else None)
        start = data.get("start") or (current_start.strftime("%H:%M") if current_start else "09:00")
        end = data.get("end") or (current_end.strftime("%H:%M") if current_end else "10:00")
        rebuilt = MeetingManualIn(title=meeting.title, date=day, start=start, end=end)
        meeting.start_at = rebuilt.start_at()
        meeting.end_at = rebuilt.end_at()
    meeting.in_progress_by = user.email
    log(db, user.email, f"Edited meeting {meeting.title}")
    return {**meeting_out(meeting), "saved": True}


@router.delete("/{meeting_id}")
def delete_meeting(
    meeting_id: str,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Manual meetings only; a soft delete recoverable for 30 days."""
    meeting = get_meeting(db, meeting_id)
    if meeting.source != "manual":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Calendar meetings cannot be deleted here; remove the event in Calendar.",
        )
    meeting.deleted_at = clock.now()
    log(db, user.email, f"Removed meeting {meeting.title}")
    return {
        "ok": True,
        "id": str(meeting.id),
        "recoverable_until": (
            meeting.deleted_at + timedelta(days=settings.soft_delete_retention_days)
        ).isoformat(),
    }


@router.post("/{meeting_id}/restore")
def restore_meeting(
    meeting_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id, include_deleted=True)
    meeting.deleted_at = None
    log(db, user.email, f"Restored meeting {meeting.title}")
    return {**meeting_out(meeting), "saved": True}


@router.post("/{meeting_id}/resync")
def resync(
    meeting_id: str,
    request: Request,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Re-read the event; only Calendar fields move. Notes and points stay attached."""
    meeting = get_meeting(db, meeting_id)
    if meeting.source != "calendar" or not meeting.calendar_event_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only calendar meetings can be re-synced.")
    events, _ = calendar_events(request, db, google, clock, settings, force=True)
    event = next(
        (
            e
            for e in events
            if e.id == meeting.calendar_event_id or (meeting.ical_uid and e.ical_uid == meeting.ical_uid)
        ),
        None,
    )
    if event is None:
        return {
            **meeting_out(meeting),
            "saved": True,
            "resynced": False,
            "note": "The event is no longer on any connected calendar.",
        }
    _apply_event(meeting, event, clock.now())
    return {**meeting_out(meeting), "saved": True, "resynced": True}


@router.get("/{meeting_id}/connections")
def meeting_connections(
    meeting_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, str]]:
    get_meeting(db, meeting_id)
    return [
        {"email": c.email, "status": c.status}
        for c in db.scalars(select(Connection).order_by(Connection.connected_at)).all()
    ]
