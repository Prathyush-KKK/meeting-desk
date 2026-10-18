"""Extraction.

``POST /meetings/{id}/extract`` answers in the polling shape either way: with no queue
(``JOBS_ENABLED=0``, the tests, a SQLite run) the job runs inline and the answer carries the
points; with the queue the row is created, the task deferred, and the answer says ``queued`` -
``GET /extractions/{id}`` then reports queued / running / done / error, and the points once done.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.db import get_session
from app.extract import get_provider
from app.extract.provider import ExtractionError, ExtractionProvider
from app.google import get_google
from app.google.interface import GoogleSuite
from app.jobs.extract import extraction_out, gather_notes, perform_extraction, start_extraction
from app.models import Extraction, Point, User
from app.routes.common import admin_emails, as_uuid, get_clock, get_meeting
from app.schemas import point_out

router = APIRouter(tags=["extract"])


@router.post("/meetings/{meeting_id}/extract")
def extract(
    meeting_id: str,
    request: Request,
    db: Session = Depends(get_session),
    provider: ExtractionProvider = Depends(get_provider),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_id)
    if not gather_notes(db, meeting):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No notes are included for this meeting. Paste some, or switch a note's include toggle on.",
        )
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is not None:
        from app.jobs.queue import enqueue_extraction

        extraction = start_extraction(db, meeting, provider, queued=True)
        db.commit()  # the worker may pick the job up before this request's session would commit
        job_id = enqueue_extraction(jobs, str(extraction.id), user.email)
        log(db, user.email, f"Queued extraction for {meeting.title}")
        return {
            "extraction": extraction_out(extraction, []),
            "points": [],
            "queued": True,
            "job_id": job_id,
            "poll": f"/extractions/{extraction.id}",
        }

    extraction = start_extraction(db, meeting, provider)
    try:
        created = perform_extraction(
            db,
            extraction,
            meeting,
            provider,
            clock,
            actor=user.email,
            google=google,
            connection_emails=admin_emails(db),
        )
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Extraction failed: {exc}") from exc
    log(db, user.email, f"Extracted {len(created)} points from {meeting.title}")
    return {
        "extraction": extraction_out(extraction, created),
        "points": [point_out(p) for p in created],
        "queued": False,
    }


@router.get("/extractions/{extraction_id}")
def get_extraction(
    extraction_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    extraction = db.get(Extraction, as_uuid(extraction_id, "extraction"))
    if extraction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown extraction")
    points = list(
        db.scalars(
            select(Point)
            .where(Point.extraction_id == extraction.id, Point.deleted_at.is_(None))
            .order_by(Point.created_at)
        ).all()
    )
    out = extraction_out(extraction, points)
    return {**out, "output": extraction.output or {}, "points": [point_out(p) for p in points]}


@router.get("/meetings/{meeting_id}/extractions")
def list_extractions(
    meeting_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    meeting = get_meeting(db, meeting_id)
    rows = db.scalars(
        select(Extraction).where(Extraction.meeting_id == meeting.id).order_by(Extraction.created_at.desc())
    ).all()
    return [extraction_out(e, []) for e in rows]
