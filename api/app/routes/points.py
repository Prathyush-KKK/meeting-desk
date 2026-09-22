"""Step 3 - points: list, edit, bulk, defer, restore, soft delete with undo, manual add.

Lifecycle is ``active`` or ``deferred``; ``transferred`` is not a value here - a transferred point
is deleted and the transfer row keeps the snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.extract.postprocess import Person, normalise_text, parse_due, resolve_owner
from app.models import Meeting, Point, User
from app.routes.common import get_clock, get_config, get_meeting, get_point
from app.schemas import PointBulkIn, PointIdsIn, PointIn, PointPatchIn, point_out

router = APIRouter(prefix="/points", tags=["points"])

EDITABLE = ("kind", "text", "owner_text", "owner_email", "due_text", "status", "workstream", "selected")


def _due_date(db: Session, point: Point, due_text: str) -> datetime | None:
    """The date the phrase means, resolved once here rather than again at write time.

    Same rules as post-processing, same base: the meeting's start in Asia/Kolkata. A point typed by
    hand therefore carries a date exactly like an extracted one, and the Sheets writer never has to
    read "by EOW" against whatever day it happens to be run.
    """
    meeting = db.get(Meeting, point.meeting_id)
    return parse_due(due_text, meeting.start_at if meeting else None)


def _apply_patch(db: Session, point: Point, patch: PointPatchIn, actor: str) -> Point:
    data = patch.model_dump(exclude_unset=True)
    for name in EDITABLE:
        if name in data and data[name] is not None:
            setattr(point, name, data[name])
    if "text" in data and data["text"] is not None:
        point.text_norm = normalise_text(data["text"])
    if "due_text" in data and data["due_text"] is not None:
        point.due_date = _due_date(db, point, data["due_text"])
    if "owner_text" in data and data["owner_text"] is not None and "owner_email" not in data:
        meeting = db.get(Meeting, point.meeting_id)
        attendees = [Person(a.get("name", ""), a.get("email", "")) for a in (meeting.attendees or [])]
        resolution = resolve_owner(data["owner_text"], attendees)
        point.owner_email = resolution.owner_email
        point.owner_ambiguous = resolution.ambiguous
    if "lifecycle" in data and data["lifecycle"] is not None:
        point.lifecycle = data["lifecycle"]
    point.updated_by = actor
    return point


@router.get("")
def list_points(
    meeting_id: str | None = None,
    lifecycle: str = "active",
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    """``lifecycle=active`` by default; ``deferred`` backs the "See deferred" toggle."""
    query = select(Point).where(Point.deleted_at.is_(None))
    if meeting_id:
        query = query.where(Point.meeting_id == get_meeting(db, meeting_id).id)
    if lifecycle in ("active", "deferred"):
        query = query.where(Point.lifecycle == lifecycle)
    rows = db.scalars(query.order_by(Point.created_at)).all()
    return [point_out(p) for p in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_point(
    body: PointIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    meeting = get_meeting(db, body.meeting_id)
    attendees = [Person(a.get("name", ""), a.get("email", "")) for a in (meeting.attendees or [])]
    owner = resolve_owner(body.owner_text, attendees)
    point = Point(
        meeting_id=meeting.id,
        kind=body.kind,
        text=body.text,
        text_norm=normalise_text(body.text),
        owner_text=owner.owner_text,
        owner_email=owner.owner_email,
        owner_ambiguous=owner.ambiguous,
        due_text=body.due_text,
        due_date=parse_due(body.due_text, meeting.start_at),
        status=body.status,
        workstream=body.workstream or meeting.workstream,
        lifecycle="active",
        created_by=user.email,
        updated_by=user.email,
    )
    db.add(point)
    db.flush()
    log(db, user.email, f"Added a point on {meeting.title}")
    return point_out(point)


@router.patch("/{point_id}")
def patch_point(
    point_id: str,
    body: PointPatchIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Every field edit autosaves; last write wins per field, ``updated_by`` shows who."""
    point = get_point(db, point_id)
    _apply_patch(db, point, body, user.email)
    return point_out(point)


@router.post("/bulk")
def bulk_patch(
    body: PointBulkIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    out = []
    for point_id in body.ids:
        point = get_point(db, point_id)
        out.append(point_out(_apply_patch(db, point, body.patch, user.email)))
    if out:
        log(db, user.email, f"Updated {len(out)} points")
    return out


@router.post("/{point_id}/defer")
def defer(
    point_id: str,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Hides the point without losing it; "See deferred" brings it back."""
    point = get_point(db, point_id)
    point.lifecycle = "deferred"
    point.deferred_at = clock.now()
    point.deferred_by = user.email
    point.selected = False
    point.updated_by = user.email
    return point_out(point)


@router.post("/defer")
def defer_many(
    body: PointIdsIn,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    now = clock.now()
    out = []
    for point_id in body.ids:
        point = get_point(db, point_id)
        point.lifecycle = "deferred"
        point.deferred_at = now
        point.deferred_by = user.email
        point.selected = False
        point.updated_by = user.email
        out.append(point_out(point))
    return out


@router.post("/{point_id}/restore")
def restore(
    point_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Restore works for a deferred point and for one deleted by mistake."""
    point = get_point(db, point_id, include_deleted=True)
    point.lifecycle = "active"
    point.deferred_at = None
    point.deferred_by = None
    point.deleted_at = None
    point.updated_by = user.email
    return point_out(point)


@router.delete("/{point_id}")
def soft_delete(
    point_id: str,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Soft delete with a 10-second undo toast; recoverable for 30 days."""
    point = get_point(db, point_id)
    now = clock.now()
    point.deleted_at = now
    point.selected = False
    point.updated_by = user.email
    log(db, user.email, "Removed a point")
    return {
        "ok": True,
        "id": str(point.id),
        "undo_until": (now + timedelta(seconds=settings.point_undo_seconds)).isoformat(),
        "recoverable_until": (now + timedelta(days=settings.soft_delete_retention_days)).isoformat(),
        "undo_url": f"/points/{point.id}/restore",
    }


@router.get("/deleted")
def list_deleted(
    meeting_id: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    query = select(Point).where(Point.deleted_at.is_not(None))
    if meeting_id:
        query = query.where(Point.meeting_id == get_meeting(db, meeting_id).id)
    return [point_out(p) for p in db.scalars(query.order_by(Point.deleted_at.desc())).all()]


@router.get("/{point_id}")
def get_one(
    point_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    return point_out(get_point(db, point_id))


@router.post("/copy-text")
def copy_as_text(
    body: PointIdsIn,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, str]:
    """``- [Owner] point - due`` grouped by kind, for pasting elsewhere."""
    groups: dict[str, list[str]] = {}
    for point_id in body.ids:
        point = get_point(db, point_id)
        owner = f"[{point.owner_text}] " if point.owner_text else ""
        due = f" · {point.due_text}" if point.due_text else ""
        groups.setdefault(point.kind, []).append(f"- {owner}{point.text}{due}")
    labels = {"action": "Actions", "decision": "Decisions", "risk": "Risks", "question": "Questions"}
    blocks = [f"{labels.get(k, k)}\n" + "\n".join(v) for k, v in groups.items()]
    return {"text": "\n\n".join(blocks)}


@router.get("/{point_id}/history")
def history(
    point_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    point = get_point(db, point_id, include_deleted=True)
    if point.updated_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown point")
    return {"id": str(point.id), "updated_by": point.updated_by, "updated_at": point.updated_at.isoformat()}
