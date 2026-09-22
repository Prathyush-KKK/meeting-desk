"""The activity log: every change records who did it. Kept 90 days (spec section 5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Activity

RETENTION_DAYS = 90
IST = ZoneInfo("Asia/Kolkata")


def now() -> datetime:
    """The log is wall-clock, not the demo clock, so entries stay in the order they happened."""
    return datetime.now(IST)


def log(db: Session, actor: str, text: str) -> Activity:
    row = Activity(actor=actor, text=text, at=now())
    db.add(row)
    return row


def recent(db: Session, limit: int = 100) -> list[Activity]:
    return list(db.scalars(select(Activity).order_by(Activity.at.desc()).limit(limit)).all())


def purge(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    result = db.execute(delete(Activity).where(Activity.at < cutoff))
    return int(result.rowcount or 0)
