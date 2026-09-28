"""The extraction job.

Two halves so the route and the queue share one implementation:

* ``start_extraction`` writes the ``extractions`` row (the notes it will read, the input hash, a
  ``queued`` marker) - the route calls it, then either runs the job inline or enqueues it;
* ``perform_extraction`` calls the provider, post-processes, and creates the points that are new
  by ``text_norm``. Edited or transferred points are never touched.

``run_extraction`` is the inline composite the tests and a queue-less deployment use. Job status
lives in ``extractions.usage["job"]`` (queued, running) until the provider's usage replaces it,
so spec section 4 stays exact and the polling route reads one row.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import seed_data
from app.clock import Clock
from app.extract.postprocess import normalise_text, postprocess, resolve_owner
from app.extract.provider import ExtractionContext, ExtractionError, ExtractionProvider
from app.extract.schema import SCHEMA_VERSION, ExtractionOutput
from app.google.interface import GoogleError, GoogleSuite
from app.models import Extraction, Meeting, Note, Point, Transfer
from app.telemetry import events
from app.telemetry.events import FailureReason
from app.telemetry.logs import get_logger, log_event
from app.telemetry.providers import track_job

log = get_logger("jobs.extract")


def gather_notes(db: Session, meeting: Meeting) -> list[Note]:
    return list(
        db.scalars(
            select(Note)
            .where(Note.meeting_id == meeting.id, Note.deleted_at.is_(None), Note.include.is_(True))
            .order_by(Note.created_at)
        ).all()
    )


def _known_text_norms(db: Session, meeting: Meeting) -> set[str]:
    """Points already on the meeting, plus the ones that were transferred away."""
    known = set(db.scalars(select(Point.text_norm).where(Point.meeting_id == meeting.id)).all())
    for snapshot in db.scalars(select(Transfer.snapshot).where(Transfer.meeting_id == meeting.id)).all():
        if isinstance(snapshot, dict) and snapshot.get("text_norm"):
            known.add(snapshot["text_norm"])
    return {k for k in known if k}


def _notes_text(notes: list[Note]) -> str:
    return "\n\n".join(n.text for n in notes).strip()


def start_extraction(
    db: Session, meeting: Meeting, provider: ExtractionProvider, queued: bool = False
) -> Extraction:
    notes = gather_notes(db, meeting)
    text = _notes_text(notes)
    extraction = Extraction(
        meeting_id=meeting.id,
        note_ids=[str(n.id) for n in notes],
        provider=getattr(provider, "name", "fake"),
        schema_version=SCHEMA_VERSION,
        input_hash=hashlib.sha256(text.encode()).hexdigest(),
        usage={"job": {"status": "queued"}} if queued else {},
    )
    db.add(extraction)
    db.flush()
    return extraction


def context_for(meeting: Meeting, directory: list[dict[str, str]]) -> ExtractionContext:
    return ExtractionContext(
        meeting_title=meeting.title,
        meeting_start=meeting.start_at,
        timezone=meeting.timezone or "Asia/Kolkata",
        workstream=meeting.workstream,
        attendees=list(meeting.attendees or []),
        directory=list(directory),
    )


def directory_for(
    output: ExtractionOutput,
    context: ExtractionContext,
    google: GoogleSuite | None,
    connection_emails: list[str],
) -> list[dict[str, str]]:
    """The People directory, asked only for owners the attendee list did not settle."""
    if google is None or not connection_emails:
        return []
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in output.action_items:
        owner = (item.owner_text or "").strip()
        if not owner or resolve_owner(owner, context.attendees).owner_email:
            continue
        query = owner.split(" ")[0]
        if query.lower() in seen:
            continue
        seen.add(query.lower())
        for email in connection_emails:
            try:
                hits = google.people.search_directory(email, query)
            except GoogleError:
                continue
            people.extend({"name": p.name, "email": p.email} for p in hits)
            break
    return people


def perform_extraction(
    db: Session,
    extraction: Extraction,
    meeting: Meeting,
    provider: ExtractionProvider,
    clock: Clock,
    actor: str = "",
    directory: list[dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
    google: GoogleSuite | None = None,
    connection_emails: list[str] | None = None,
) -> list[Point]:
    """The provider call and the points it yields. Raises ExtractionError; the row records it.

    This is the single door both the inline route and the queued task come through, so the
    ``background_job_total{job_name="extract"}`` counter is right either way. A meeting with no
    included notes returns empty and counts as a run that succeeded: the job did its job, there was
    nothing to extract.
    """
    with track_job("extract"):
        return _perform_extraction(
            db,
            extraction,
            meeting,
            provider,
            clock,
            actor=actor,
            directory=directory,
            aliases=aliases,
            google=google,
            connection_emails=connection_emails,
        )


def _perform_extraction(
    db: Session,
    extraction: Extraction,
    meeting: Meeting,
    provider: ExtractionProvider,
    clock: Clock,
    actor: str = "",
    directory: list[dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
    google: GoogleSuite | None = None,
    connection_emails: list[str] | None = None,
) -> list[Point]:
    notes = [n for n in gather_notes(db, meeting) if str(n.id) in set(extraction.note_ids or [])]
    if not notes:
        notes = gather_notes(db, meeting)
    text = _notes_text(notes)
    if not text:
        extraction.error = "No notes are included for this meeting."
        extraction.usage = {}
        db.flush()
        return []

    extraction.usage = {"job": {"status": "running", "started_at": clock.now().isoformat()}}
    # Committed, not flushed: the row says "running" to ``GET /meetings/{id}/extractions`` while the
    # model is still answering, and it stays as the record of a failed run - the route's session
    # rolls back on the 502, and used to take the row and its error message with it.
    db.commit()

    # The fake provider recognises owner lines by name, so it sees the demo directory up front; the
    # real one asks the People API afterwards, only for owners the attendee list did not settle.
    fake_side = google is None or getattr(google, "is_fake", False)
    people = list(directory) if directory is not None else (list(seed_data.DIRECTORY) if fake_side else [])
    context = context_for(meeting, people)
    try:
        result = provider.extract(text, context)
    except ExtractionError as exc:
        extraction.error = str(exc)
        extraction.usage = {}
        db.commit()
        log_event(
            log,
            events.EXTRACTION_FAILED,
            level=logging.ERROR,
            provider=getattr(provider, "name", "unknown"),
            failure_reason=FailureReason.PROVIDER_UNAVAILABLE,
        )
        raise
    except NotImplementedError as exc:
        extraction.error = str(exc)
        extraction.usage = {}
        db.commit()
        raise ExtractionError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive; notes are never lost
        extraction.error = str(exc)
        extraction.usage = {}
        db.commit()
        raise ExtractionError(str(exc)) from exc

    extraction.provider = result.provider
    extraction.model = result.model
    extraction.region = result.region
    extraction.latency_ms = result.latency_ms
    extraction.usage = dict(result.usage or {})
    extraction.output = result.output.model_dump()
    extraction.error = None
    db.flush()

    if directory is None and not fake_side:
        people = directory_for(result.output, context, google, connection_emails or [])
        context.directory = list(people)
    known = _known_text_norms(db, meeting)
    created: list[Point] = []
    for resolved in postprocess(result.output, context, people, aliases or seed_data.ALIASES):
        norm = normalise_text(resolved.text)
        if not norm or norm in known:
            continue
        known.add(norm)
        point = Point(
            meeting_id=meeting.id,
            extraction_id=extraction.id,
            kind=resolved.kind,
            text=resolved.text,
            text_norm=norm,
            evidence=resolved.evidence,
            owner_text=resolved.owner_text,
            owner_email=resolved.owner_email,
            owner_ambiguous=resolved.owner_ambiguous,
            due_text=resolved.due_text,
            due_date=resolved.due_date,
            status=resolved.status,
            workstream=resolved.workstream or meeting.workstream,
            lifecycle="active",
            created_by=actor,
            updated_by=actor,
        )
        db.add(point)
        created.append(point)

    if created and meeting.step in ("meeting", "notes"):
        meeting.step = "points"
    # On the record: points are deleted when they transfer, so a count taken later would shrink.
    extraction.usage = {**(extraction.usage or {}), "created_points": len(created)}
    db.flush()
    return created


def run_extraction(
    db: Session,
    meeting: Meeting,
    provider: ExtractionProvider,
    clock: Clock,
    actor: str = "",
    directory: list[dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
    google: GoogleSuite | None = None,
    connection_emails: list[str] | None = None,
) -> tuple[Extraction, list[Point]]:
    """Inline: start and perform in one go. What the route does when no queue is configured."""
    extraction = start_extraction(db, meeting, provider)
    created = perform_extraction(
        db,
        extraction,
        meeting,
        provider,
        clock,
        actor=actor,
        directory=directory,
        aliases=aliases,
        google=google,
        connection_emails=connection_emails,
    )
    return extraction, created


def extraction_status(extraction: Extraction) -> str:
    if extraction.error:
        return "error"
    job = (extraction.usage or {}).get("job") if isinstance(extraction.usage, dict) else None
    if isinstance(job, dict) and job.get("status") in ("queued", "running"):
        return str(job["status"])
    return "done"


def extraction_out(extraction: Extraction, created: list[Point]) -> dict[str, Any]:
    usage = dict(extraction.usage or {})
    usage.pop("job", None)
    stored = int(usage.pop("created_points", 0) or 0)
    return {
        "id": str(extraction.id),
        "meeting_id": str(extraction.meeting_id),
        "provider": extraction.provider,
        "model": extraction.model,
        "region": extraction.region,
        "schema_version": extraction.schema_version,
        "latency_ms": extraction.latency_ms,
        "usage": usage,
        "fallback_from": usage.get("fallback_from"),
        "error": extraction.error,
        "note_ids": extraction.note_ids or [],
        "created_points": len(created) if created else stored,
        "status": extraction_status(extraction),
        "at": extraction.created_at.isoformat() if extraction.created_at else None,
    }
