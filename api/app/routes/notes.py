"""Step 2 - sources, imports, paste, quick paste, include toggles and moves."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.extract.fake import MAX_INPUT_CHARS
from app.extract.postprocess import normalise_note
from app.google import get_google
from app.google.docs import preferred_tab
from app.google.interface import GoogleSuite, recap_query
from app.models import Meeting, Note, User
from app.notes_store import live_note, save_note
from app.routes.common import (
    as_uuid,
    aware,
    get_clock,
    get_config,
    get_meeting,
    healthy_connections,
    next_key,
    pick_for,
)
from app.schemas import (
    NoteImportIn,
    NoteMoveIn,
    NotePasteIn,
    NotePatchIn,
    QuickPasteIn,
    meeting_out,
    note_out,
)

router = APIRouter(prefix="/notes", tags=["notes"])

DOC_SEARCH_WINDOW = timedelta(hours=2)


def _get_note(db: Session, note_id: str) -> Note:
    note = db.get(Note, as_uuid(note_id, "note"))
    if note is None or note.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown note")
    return note


_save = save_note


# --- sources --------------------------------------------------------------------------------------


@router.get("/sources")
def sources(
    meeting_id: str,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """What can be imported for this meeting, and through which connection."""
    meeting = get_meeting(db, meeting_id)
    emails = [c.email for c in healthy_connections(db)]
    out: list[dict[str, Any]] = []

    doc_id = next(
        (
            a.get("file_id")
            for a in (meeting.attachments or [])
            if a.get("kind") == "doc" and a.get("file_id")
        ),
        "",
    )
    start_at = aware(meeting.start_at)
    if not doc_id and start_at:
        found = pick_for(
            db,
            emails,
            lambda email: google.drive.search(
                email, meeting.title, start_at - DOC_SEARCH_WINDOW, start_at + DOC_SEARCH_WINDOW
            ),
            accept=bool,
        )
        if found.ok:
            doc_id = found.value[0].id

    if doc_id:
        reader, detail, document = _first_reader(db, google, emails, doc_id)
        tabs = [t.title for t in document.tabs] if document else []
        out.append(
            {
                "key": "gemini_doc",
                "source": "gemini_doc",
                "title": "Notes by Gemini",
                "origin_ref": doc_id,
                "available": reader is not None,
                "connection": reader,
                "tabs": tabs,
                "message": "" if reader else f"not shared with an admin account ({detail})",
            }
        )
        if "Transcript" in tabs:
            out.append(
                {
                    "key": "transcript",
                    "source": "transcript",
                    "title": "Transcript",
                    "origin_ref": doc_id,
                    "available": True,
                    "connection": reader,
                    "tabs": ["Transcript"],
                    "message": "",
                }
            )
    else:
        out.append(
            {
                "key": "gemini_doc",
                "source": "gemini_doc",
                "title": "Notes by Gemini",
                "origin_ref": "",
                "available": False,
                "connection": None,
                "tabs": [],
                "message": "not generated yet",
            }
        )

    query = recap_query(meeting.title, start_at)
    no_recap = "no recap email found" if settings.google_use_gmail else "Gmail is off"
    recap = pick_for(db, emails, lambda email: google.gmail.search_messages(email, query), accept=bool)
    out.append(
        {
            "key": "recap_email",
            "source": "recap_email",
            "title": "Recap email",
            "origin_ref": recap.value[0].id if recap.ok else "",
            "available": recap.ok,
            "connection": recap.email,
            "tabs": [],
            "message": "" if recap.ok else no_recap,
        }
    )
    out.append(
        {
            "key": "paste",
            "source": "paste",
            "title": "Paste or upload",
            "origin_ref": "",
            "available": True,
            "connection": None,
            "tabs": [],
            "message": "",
        }
    )
    return {"meeting_id": str(meeting.id), "sources": out, "read_at": clock.now().isoformat()}


def _first_reader(
    db: Session, google: GoogleSuite, emails: list[str], doc_id: str
) -> tuple[str | None, str, Any]:
    """(connection, refusal detail, document): the first admin connection that can read the doc."""
    pick = pick_for(db, emails, lambda email: google.docs.get_document(email, doc_id))
    if pick.ok:
        return pick.email, "", pick.value
    return None, pick.detail, None


# --- imports and paste ----------------------------------------------------------------------------


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_note(
    body: NoteImportIn,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, body.meeting_id)
    emails = [c.email for c in healthy_connections(db)]

    if body.source == "recap_email":
        query = recap_query(meeting.title, aware(meeting.start_at))

        def find(email: str):
            messages = google.gmail.search_messages(email, query)
            return next((m for m in messages if not body.origin_ref or m.id == body.origin_ref), None)

        pick = pick_for(db, emails, find, accept=lambda m: m is not None)
        if not pick.ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No recap email reached a connected mailbox.")
        match = pick.value
        note, created = _save(
            db,
            meeting,
            source="recap_email",
            title=match.subject,
            raw=match.body,
            origin_ref=match.id,
            actor=user.email,
        )
        return {"note": note_out(note), "created": created, "connection": pick.email}

    reader, detail, document = _first_reader(db, google, emails, body.origin_ref)
    if reader is None or document is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That document is not shared with an admin account. {detail} Paste the notes instead.",
        )
    wanted = body.tab or ("Transcript" if body.source == "transcript" else "")
    tab = document.tab(wanted) if wanted else None
    if tab is None:
        tab = preferred_tab(document)
    if tab is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That document has no readable content yet.")

    note, created = _save(
        db,
        meeting,
        source=body.source,
        title=f"{document.title} - {tab.title}",
        raw=tab.text,
        origin_ref=f"{document.id}#{tab.id}",
        actor=user.email,
    )
    return {"note": note_out(note), "created": created, "connection": reader, "tab": tab.title}


@router.post("/paste", status_code=status.HTTP_201_CREATED)
def paste(
    body: NotePasteIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, body.meeting_id)
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to save.")
    note, created = _save(
        db, meeting, source=body.source, title=body.title, raw=body.text, origin_ref="", actor=user.email
    )
    return {
        "note": note_out(note),
        "created": created,
        "meeting": meeting_out(meeting),
        "truncated": len(body.text) > MAX_INPUT_CHARS,
    }


@router.post("/quick", status_code=status.HTTP_201_CREATED)
def quick_paste(
    body: QuickPasteIn,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """The paste field at the top of Capture.

    With a meeting selected it saves a note on it; with nothing selected it creates a manual meeting
    titled from the first line, then continues.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to save.")

    created_meeting = False
    if body.meeting_id:
        meeting = get_meeting(db, body.meeting_id)
    else:
        first_line = normalise_note(text).splitlines()[0].strip()[:120] or "Pasted notes"
        now = clock.now()
        meeting = Meeting(
            key=next_key(db, "M"),
            source="manual",
            created_by=user.email,
            title=first_line,
            start_at=now,
            end_at=now,
            organizer_email=user.email,
            organizer_name=user.name,
            attendees=[],
            step="notes",
        )
        db.add(meeting)
        db.flush()
        created_meeting = True
        log(db, user.email, f"Added meeting {meeting.title} from a paste")

    note, created = _save(
        db, meeting, source="paste", title="Pasted note", raw=text, origin_ref="", actor=user.email
    )
    return {
        "meeting": {**meeting_out(meeting), "saved": True},
        "note": note_out(note),
        "created": created,
        "created_meeting": created_meeting,
    }


# --- list, toggle, move, delete --------------------------------------------------------------------


@router.get("")
def list_notes(
    meeting_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    meeting = get_meeting(db, meeting_id)
    rows = db.scalars(
        select(Note).where(Note.meeting_id == meeting.id, Note.deleted_at.is_(None)).order_by(Note.created_at)
    ).all()
    return [note_out(n) for n in rows]


@router.patch("/{note_id}")
def patch_note(
    note_id: str,
    body: NotePatchIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    note = _get_note(db, note_id)
    data = body.model_dump(exclude_unset=True)
    if "include" in data and data["include"] is not None:
        note.include = data["include"]
        log(db, user.email, f"{'Included' if note.include else 'Excluded'} a note from extraction")
    if data.get("title"):
        note.title = data["title"]
    return note_out(note)


@router.post("/{note_id}/move")
def move_note(
    note_id: str,
    body: NoteMoveIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Pasted onto the wrong meeting - move it rather than retyping it."""
    note = _get_note(db, note_id)
    target = get_meeting(db, body.meeting_id)
    if target.id == note.meeting_id:
        return note_out(note)
    if live_note(db, target, note.text_hash) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{target.title} already has this note.")
    note.meeting_id = target.id
    try:
        db.flush()
    except IntegrityError as exc:  # the same move twice, or a race with a paste on the target
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{target.title} already has this note."
        ) from exc
    log(db, user.email, f"Moved a note to {target.title}")
    return note_out(note)


@router.delete("/{note_id}")
def delete_note(
    note_id: str,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    note = _get_note(db, note_id)
    note.deleted_at = clock.now()
    log(db, user.email, "Removed a note")
    return {"ok": True, "id": str(note.id)}
