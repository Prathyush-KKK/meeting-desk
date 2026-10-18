"""Calendar: ``events.list`` per admin connection.

``singleEvents=true`` and ``orderBy=startTime`` so a recurring series comes back as instances; a
fields mask limited to what ``models.py`` stores; every page followed. Results are cached in
process for 60 s per (connection, window) - the merge across connections and the de-duplication
on ``iCalUID`` happen in ``routes/meetings.py``. A 429 or ``rateLimitExceeded`` is not retried
inside the request path (the list is served from the route's cache); the HTTP layer backs the
connection off and the route skips it until then.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime
from datetime import time as time_of_day
from typing import Any
from zoneinfo import ZoneInfo

from app.google.http import GoogleHttp
from app.google.interface import GEMINI_NOTES_MARKER, Attachment, Attendee, CalendarEvent, NotFoundError
from app.tz import as_zone, display_zone

BASE = "https://www.googleapis.com/calendar/v3"
FIELDS = (
    "nextPageToken,items("
    "id,iCalUID,status,summary,description,location,start,end,updated,htmlLink,recurringEventId,"
    "organizer(email,displayName),attendees(email,displayName,responseStatus,self),"
    "conferenceData(conferenceSolution(name),entryPoints(entryPointType,uri)),"
    "attachments(fileId,title,mimeType,fileUrl)"
    ")"
)
PAGE_SIZE = 250
MAX_PAGES = 20  # 5000 events in a week is not a calendar, it is a bug


class RealCalendarClient:
    def __init__(
        self,
        http: GoogleHttp,
        display_tz: ZoneInfo | str | None = None,
        cache_seconds: float = 60.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.tz = as_zone(display_tz)
        self.cache_seconds = cache_seconds
        self._now = now
        self._cache: dict[tuple[str, str, str], tuple[float, list[CalendarEvent]]] = {}

    def list_events(
        self, connection_email: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        key = (connection_email, time_min.isoformat(), time_max.isoformat())
        hit = self._cache.get(key)
        if hit and self._now() - hit[0] < self.cache_seconds:
            return list(hit[1])

        events: list[CalendarEvent] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "timeMin": _rfc3339(time_min),
                "timeMax": _rfc3339(time_max),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": PAGE_SIZE,
                "fields": FIELDS,
                "pageToken": page_token,
            }
            body = self.http.get(
                connection_email, f"{BASE}/calendars/primary/events", params=params, retries=0
            )
            for item in body.get("items") or []:
                event = self.parse_event(item, connection_email)
                if event is not None:
                    events.append(event)
            page_token = body.get("nextPageToken")
            if not page_token or page_token in seen_tokens or len(seen_tokens) >= MAX_PAGES:
                break
            seen_tokens.add(page_token)

        events.sort(key=lambda e: e.start_at, reverse=True)
        self._cache[key] = (self._now(), events)
        return list(events)

    def get_event(self, connection_email: str, event_id: str) -> CalendarEvent | None:
        try:
            item = self.http.get(
                connection_email,
                f"{BASE}/calendars/primary/events/{event_id}",
                params={"fields": FIELDS.replace("nextPageToken,items(", "")[:-1]},
            )
        except NotFoundError:
            return None
        return self.parse_event(item, connection_email)

    def forget(self, connection_email: str) -> None:
        for key in [k for k in self._cache if k[0] == connection_email]:
            self._cache.pop(key, None)

    # --- parsing --------------------------------------------------------------------------------
    def parse_event(self, item: dict[str, Any], connection_email: str) -> CalendarEvent | None:
        if item.get("status") == "cancelled":
            return None
        start_raw = item.get("start") or {}
        end_raw = item.get("end") or {}
        start_at = self._when(start_raw)
        end_at = self._when(end_raw) or start_at
        if start_at is None:
            return None
        organizer = item.get("organizer") or {}
        return CalendarEvent(
            id=str(item.get("id", "")),
            ical_uid=str(item.get("iCalUID", "") or ""),
            calendar_id=connection_email,
            title=str(item.get("summary") or "(no title)"),
            start_at=start_at,
            end_at=end_at,
            timezone=str(start_raw.get("timeZone") or self.tz.key),
            description=str(item.get("description") or ""),
            location=str(item.get("location") or ""),
            organizer_email=str(organizer.get("email") or ""),
            organizer_name=str(organizer.get("displayName") or ""),
            recurring_event_id=str(item.get("recurringEventId") or ""),
            html_link=str(item.get("htmlLink") or ""),
            attendees=[
                Attendee(
                    email=str(a.get("email") or ""),
                    name=str(a.get("displayName") or ""),
                    response=str(a.get("responseStatus") or "needsAction"),
                )
                for a in item.get("attendees") or []
                if a.get("email")
            ],
            conference=_conference(item.get("conferenceData") or {}),
            attachments=[_attachment(a) for a in item.get("attachments") or []],
            updated_at=_parse_dt(item.get("updated"), self.tz),
        )

    def _when(self, raw: dict[str, Any]) -> datetime | None:
        """``dateTime`` with its offset, or an all-day ``date`` at midnight in the display zone."""
        if raw.get("dateTime"):
            return _parse_dt(raw["dateTime"], self.tz)
        if raw.get("date"):
            day = date.fromisoformat(str(raw["date"]))
            return datetime.combine(day, time_of_day(0, 0), tzinfo=self.tz)
        return None


def _parse_dt(raw: Any, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    # Stored UTC-equivalent, shown in DISPLAY_TIMEZONE everywhere; the event's own zone is kept apart.
    return parsed.astimezone(tz)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=display_zone())
    return value.isoformat(timespec="seconds")


def _conference(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in data.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            out["meet_link"] = entry["uri"]
        elif entry.get("entryPointType") == "phone" and entry.get("uri"):
            out.setdefault("phone", entry["uri"])
    solution = (data.get("conferenceSolution") or {}).get("name")
    if solution:
        out["solution"] = solution
    return out


def _attachment(raw: dict[str, Any]) -> Attachment:
    title = str(raw.get("title") or "")
    mime = str(raw.get("mimeType") or "")
    lower = title.lower()
    if "transcript" in lower:
        kind = "transcript"
    elif GEMINI_NOTES_MARKER.lower() in lower or mime == "application/vnd.google-apps.document":
        kind = "doc"
    else:
        kind = "other"
    return Attachment(
        title=title, kind=kind, file_id=str(raw.get("fileId") or ""), url=str(raw.get("fileUrl") or "")
    )
