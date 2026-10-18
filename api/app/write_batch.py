"""Idempotency for the three routes that write to Google.

A transfer is one ``batchUpdate``, and the points leave the tool only once the write landed. Between
those two there is a network call, and a network call can be answered twice: the browser retries, a
phone wakes up and re-sends, someone taps Save again while the first request is still in flight.
Without a key on the request, the second attempt writes the same rows again and deletes points that
are already gone.

So every write carries a client ``batch_id`` and goes through ``begin`` / ``settle``:

1. ``begin`` looks the id up. ``done`` returns the stored answer, ``pending`` says a write with
   that id is in flight, ``failed`` lets the caller try again, and a different request body under
   the same id is a client bug and is refused.
2. ``begin`` then writes a ``pending`` row **and commits it**, before the Google call. The record
   exists even if the process dies mid-write.
3. The caller makes the Google call, does its database work, and calls ``settle`` with the response
   body: that marks the row ``done`` and stores the answer for the replay.
4. If Google refuses, ``fail`` rolls the request's work back, records the reason, and commits that
   alone - no point deleted, no edit logged, and a record saying what was attempted.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import WriteBatch


class Replay(Exception):
    """This ``batch_id`` was already carried out; ``result`` is what it answered."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("replayed")
        self.result = result


def request_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def check(db: Session, batch_id: uuid.UUID | None, payload: Any) -> WriteBatch | None:
    """What this ``batch_id`` has already done, before the route does anything else.

    Called first thing in the route, because a replay must answer with the stored result rather
    than fall over on work the first attempt already did - the points it transferred are gone, the
    cells it wrote no longer hold what the client said they held.

    Raises ``Replay`` when the id already ran to completion, and 409 when it is in flight or was
    used for a different request. Returns the failed record to retry on, or ``None`` for a new id.
    """
    if batch_id is None:
        return None
    existing = db.get(WriteBatch, batch_id)
    if existing is None:
        return None
    if existing.request_hash and existing.request_hash != request_hash(payload):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That batch_id was used for a different write. Use a new one.",
        )
    if existing.status == "done":
        raise Replay(dict(existing.result or {}))
    if existing.status == "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "A write with this batch_id is still in flight. Check the tab before "
                "sending it again.",
                "batch_id": str(batch_id),
            },
        )
    return existing  # "failed": the previous attempt did not write, so this one may try again


def begin(
    db: Session,
    *,
    batch_id: uuid.UUID,
    kind: str,
    actor: str,
    workbook_id: uuid.UUID | None,
    sheet_id: str,
    payload: Any,
    now: datetime,
) -> WriteBatch:
    """The pending record, committed before anything is sent to Google."""
    digest = request_hash(payload)
    existing = check(db, batch_id, payload)
    if existing is not None:
        existing.status = "pending"
        existing.error = None
        existing.started_at = now
        existing.settled_at = None
        db.commit()
        return existing

    record = WriteBatch(
        batch_id=batch_id,
        kind=kind,
        status="pending",
        actor=actor,
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        request_hash=digest,
        result={},
        started_at=now,
    )
    db.add(record)
    db.commit()  # before the Google call, on purpose: the intent outlives a crash
    return record


def settle(db: Session, record: WriteBatch, result: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The write landed and the database work is staged: mark it done and keep the answer."""
    record.status = "done"
    record.result = result
    record.settled_at = now
    db.add(record)
    db.commit()
    return result


def fail(db: Session, batch_id: uuid.UUID, error: str, now: datetime) -> None:
    """Google refused. Roll the request's work back, then record the failure on its own."""
    db.rollback()
    record = db.get(WriteBatch, batch_id)
    if record is not None:
        record.status = "failed"
        record.error = error[:2000]
        record.settled_at = now
        db.add(record)
        db.commit()
