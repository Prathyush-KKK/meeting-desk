"""Saving a note: one path for the routes and the background Doc fetch.

Text is normalised (markdown stripped, line breaks kept), capped, hashed; a duplicate on the same
meeting is reported, not stored twice; the meeting's step moves to ``notes`` on the first one.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import log
from app.extract.fake import MAX_INPUT_CHARS
from app.extract.postprocess import normalise_note
from app.models import Meeting, Note
from app.routes.common import text_hash, word_count


def save_note(
    db: Session,
    meeting: Meeting,
    *,
    source: str,
    title: str,
    raw: str,
    origin_ref: str,
    actor: str,
) -> tuple[Note, bool]:
    """Returns (note, created). A duplicate is reported, not stored twice.

    The check and the insert are two statements, so two saves of the same text can pass the check
    together and meet at the index. That is the same "already have this" answer, not a 500: the
    unique index is partial on ``deleted_at IS NULL``, so it fires only when a live note really is
    there - a re-paste after a delete inserts cleanly.
    """
    text = normalise_note(raw)[:MAX_INPUT_CHARS]
    digest = text_hash(text)
    existing = live_note(db, meeting, digest)
    if existing is not None:
        return existing, False
    note = Note(
        meeting_id=meeting.id,
        source=source,
        origin_ref=origin_ref or None,
        title=title,
        text=text,
        word_count=word_count(text),
        text_hash=digest,
        include=True,
        created_by=actor,
    )
    db.add(note)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{meeting.title} already has this note.") from exc
    if meeting.step == "meeting":
        meeting.step = "notes"
    log(db, actor, f"Saved a note on {meeting.title}")
    return note, True


def live_note(db: Session, meeting: Meeting, digest: str) -> Note | None:
    """The meeting's note with this text that has not been removed."""
    return db.scalar(
        select(Note).where(Note.meeting_id == meeting.id, Note.text_hash == digest, Note.deleted_at.is_(None))
    )


def has_note_from(db: Session, meeting: Meeting, source: str) -> bool:
    return (
        db.scalar(
            select(Note.id)
            .where(Note.meeting_id == meeting.id, Note.source == source, Note.deleted_at.is_(None))
            .limit(1)
        )
        is not None
    )
