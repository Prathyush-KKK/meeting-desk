"""Re-check for a Notes by Gemini doc that appears minutes after the meeting.

Spec section 7: "the source shows 'not generated yet' with Retry, and a job re-checks every 5
minutes for an hour after the meeting ends". ``fetch_notes_doc`` is the one-shot lookup the Retry
button and the job share; ``fetch_missing_docs`` is what the periodic task runs: every captured
calendar meeting that ended inside the last hour and has no Gemini note yet gets one lookup, and a
found doc is imported (Full notes tab preferred) and pinned on the meeting's attachments so the
Sources line shows it without another Drive search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log
from app.clock import Clock
from app.google.docs import preferred_tab
from app.google.interface import DriveFile, GoogleError, GoogleSuite
from app.models import Connection, Meeting
from app.notes_store import has_note_from, save_note
from app.routes.common import pick_for
from app.telemetry.providers import track_job

IST = ZoneInfo("Asia/Kolkata")

SEARCH_WINDOW = timedelta(hours=2)
RETRY_FOR = timedelta(hours=1)
RETRY_EVERY = timedelta(minutes=5)
JOB_ACTOR = "meeting-desk (doc fetch)"


def fetch_notes_doc(google: GoogleSuite, meeting: Meeting, connection_emails: list[str]) -> DriveFile | None:
    """The attachment first, then a Drive search by title within +/-2 h of the start."""
    attached = next(
        (
            a.get("file_id")
            for a in (meeting.attachments or [])
            if a.get("kind") == "doc" and a.get("file_id")
        ),
        "",
    )
    for email in connection_emails:
        try:
            if attached:
                found = google.drive.get_file(email, attached)
                if found:
                    return found
            start_at = meeting.start_at
            if start_at is not None:
                if start_at.tzinfo is None:
                    start_at = start_at.replace(tzinfo=IST)
                hits = google.drive.search(
                    email, meeting.title, start_at - SEARCH_WINDOW, start_at + SEARCH_WINDOW
                )
                if hits:
                    return hits[0]
        except GoogleError:
            continue
    return None


@dataclass(slots=True)
class FetchReport:
    checked: list[str] = field(default_factory=list)  # meeting ids looked at
    imported: list[str] = field(default_factory=list)  # meeting ids that got a note
    still_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {"checked": self.checked, "imported": self.imported, "still_missing": self.still_missing}


def meetings_due_for_check(db: Session, now: datetime) -> list[Meeting]:
    """Calendar meetings that ended within the last hour and have no Gemini note yet."""
    since = now - RETRY_FOR
    rows = db.scalars(
        select(Meeting)
        .where(Meeting.deleted_at.is_(None), Meeting.source == "calendar", Meeting.end_at.is_not(None))
        .order_by(Meeting.end_at)
    ).all()
    due: list[Meeting] = []
    for meeting in rows:
        end_at = meeting.end_at
        if end_at is None:
            continue
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=IST)
        if since <= end_at <= now and not has_note_from(db, meeting, "gemini_doc"):
            due.append(meeting)
    return due


def fetch_missing_docs(
    db: Session,
    google: GoogleSuite,
    clock: Clock,
    connection_emails: list[str] | None = None,
    actor: str = JOB_ACTOR,
) -> FetchReport:
    """One pass of the periodic job. Safe to call as often as every 5 minutes."""
    with track_job("fetch_doc"):
        return _fetch_missing_docs(db, google, clock, connection_emails, actor)


def _fetch_missing_docs(
    db: Session,
    google: GoogleSuite,
    clock: Clock,
    connection_emails: list[str] | None = None,
    actor: str = JOB_ACTOR,
) -> FetchReport:
    now = clock.now()
    emails = connection_emails
    if emails is None:
        emails = list(
            db.scalars(
                select(Connection.email).where(Connection.status == "ok").order_by(Connection.connected_at)
            ).all()
        )
    report = FetchReport()
    for meeting in meetings_due_for_check(db, now):
        report.checked.append(str(meeting.id))
        found = fetch_notes_doc(google, meeting, emails)
        if found is None:
            report.still_missing.append(str(meeting.id))
            continue
        if import_doc(db, google, meeting, found, emails, actor):
            report.imported.append(str(meeting.id))
        else:
            report.still_missing.append(str(meeting.id))
    return report


def import_doc(
    db: Session,
    google: GoogleSuite,
    meeting: Meeting,
    found: DriveFile,
    connection_emails: list[str],
    actor: str = JOB_ACTOR,
) -> bool:
    """Read the doc through the first connection that can and save its preferred tab as a note."""
    pick = pick_for(db, connection_emails, lambda email: google.docs.get_document(email, found.id))
    if not pick.ok:
        return False
    document = pick.value
    tab = preferred_tab(document)
    if tab is None or not tab.text.strip():
        return False
    attachments = list(meeting.attachments or [])
    if not any(a.get("file_id") == found.id for a in attachments):
        attachments.append(
            {"title": found.name, "kind": "doc", "file_id": found.id, "url": found.web_view_link}
        )
        meeting.attachments = attachments
    _, created = save_note(
        db,
        meeting,
        source="gemini_doc",
        title=f"{document.title} - {tab.title}",
        raw=tab.text,
        origin_ref=f"{document.id}#{tab.id}",
        actor=actor,
    )
    if created:
        log(db, actor, f"Picked up the Notes by Gemini doc for {meeting.title} through {pick.email}")
    return created
