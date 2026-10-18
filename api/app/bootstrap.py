"""Writes the demo world into the database.

Runs at startup when ``SEED_DEMO`` is on (the default in fake mode) and from the tests. It is
idempotent: an already-populated database is left alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import seed_data
from app.activity import log
from app.activity import now as activity_now
from app.clock import Clock
from app.extract.postprocess import normalise_text
from app.google.interface import GoogleSuite
from app.models import Activity, AllowListEntry, Connection, Meeting, Note, Point, User, Workbook
from app.routes.common import text_hash, word_count
from app.tz import display_zone_name


def already_seeded(db: Session) -> bool:
    return db.scalar(select(Connection.id).limit(1)) is not None


def seed_demo(db: Session, google: GoogleSuite, clock: Clock) -> None:
    if already_seeded(db):
        return
    now = clock.now()

    for entry in seed_data.ALLOW_LIST:
        db.add(
            AllowListEntry(email=entry["email"], role=entry["role"], added_by=entry["added_by"], added_at=now)
        )

    connections: dict[str, Connection] = {}
    for c in seed_data.CONNECTIONS:
        row = Connection(
            email=c["email"],
            name=c["name"],
            scopes=c["scopes"],
            status=c["status"],
            connected_at=datetime.fromisoformat(c["connected_at"]),
            last_ok_at=now,
            refresh_token_enc=None,
            key_version=1,
        )
        db.add(row)
        connections[c["email"]] = row
    db.flush()

    meetings: dict[str, Meeting] = {}
    for m in seed_data.MEETINGS:
        if m["ref"] not in seed_data.SEEDED_MEETING_REFS:
            continue
        row = Meeting(
            key=m["key"],
            source=m["source"],
            created_by=m["organizer"],
            calendar_event_id=m["calendar_event_id"] or None,
            calendar_id="primary" if m["calendar_event_id"] else None,
            ical_uid=seed_data.ical_uid(m) or None,
            recurring_event_id=(m["calendar_event_id"] + "_series") if m["recurring"] else None,
            html_link=f"https://calendar.google.com/event?eid={m['calendar_event_id']}"
            if m["calendar_event_id"]
            else None,
            title=m["title"],
            description=m["description"],
            location=m["location"],
            start_at=seed_data.meeting_start(m),
            end_at=seed_data.meeting_end(m),
            timezone=display_zone_name(),
            organizer_email=m["organizer"],
            organizer_name=seed_data.person(m["organizer"])["name"],
            attendees=m["attendees"],
            conference={"meet_link": m["meet_link"]} if m["meet_link"] else {},
            attachments=seed_data.attachments_for(m),
            workstream=m["workstream"],
            step=m["step"],
            last_synced_at=now if m["calendar_event_id"] else None,
        )
        db.add(row)
        meetings[m["ref"]] = row
    db.flush()

    for n in seed_data.NOTES:
        meeting = meetings.get(n["meeting_ref"])
        if meeting is None:
            continue
        db.add(
            Note(
                meeting_id=meeting.id,
                source=n["source"],
                title=n["title"],
                text=n["text"],
                word_count=word_count(n["text"]),
                text_hash=text_hash(n["text"]),
                include=n["include"],
                created_by=n["created_by"],
                created_at=now - timedelta(days=3),
            )
        )

    for p in seed_data.POINTS:
        meeting = meetings.get(p["meeting_ref"])
        if meeting is None:
            continue
        db.add(
            Point(
                meeting_id=meeting.id,
                kind=p["kind"],
                text=p["text"],
                text_norm=normalise_text(p["text"]),
                evidence=p["evidence"],
                owner_text=p["owner_text"],
                owner_email=p["owner_email"],
                due_text=p["due_text"],
                status=p["status"],
                workstream=meeting.workstream,
                lifecycle="active",
                selected=p["selected"],
                created_by=seed_data.DEMO_USER,
                updated_by=seed_data.DEMO_USER,
            )
        )

    for wb in seed_data.WORKBOOKS:
        editor = next(
            (c for c in connections.values() if google.sheets.can_edit(c.email, wb["spreadsheet_id"])),
            None,
        )
        db.add(
            Workbook(
                spreadsheet_id=wb["spreadsheet_id"],
                name=wb["name"],
                url=wb["url"],
                connection_id=editor.id if editor else None,
                connected_by=wb["connected_by"],
                connected_at=now - timedelta(days=1),
                can_edit=editor is not None,
            )
        )

    log_now = activity_now()
    for i, a in enumerate(seed_data.ACTIVITY):
        db.add(Activity(actor=a["actor"], text=a["text"], at=log_now - timedelta(minutes=5 * (i + 1))))

    db.commit()


BOOTSTRAP_ACTOR = "bootstrap"


def bootstrap_admins(db: Session, emails: list[str]) -> list[str]:
    """Put ``BOOTSTRAP_ADMINS`` on the allow-list as admins. Returns the emails that changed.

    Runs at every startup, in every mode. A fresh real-mode database has an empty allow-list and
    no way to fill it (the Admin page is behind the allow-list), so the first admin has to come
    from configuration. A missing entry is added; a member is promoted; an admin is left alone.
    Nothing is ever removed here - that stays a deliberate act on the Admin page.
    """
    changed: list[str] = []
    now = activity_now()
    for email in emails:
        entry = db.get(AllowListEntry, email)
        if entry is None:
            db.add(AllowListEntry(email=email, role="admin", added_by=BOOTSTRAP_ACTOR, added_at=now))
            log(db, BOOTSTRAP_ACTOR, f"Added {email} to the allow-list as admin (BOOTSTRAP_ADMINS)")
            changed.append(email)
        elif entry.role != "admin":
            entry.role = "admin"
            log(db, BOOTSTRAP_ACTOR, f"Promoted {email} to admin (BOOTSTRAP_ADMINS)")
            changed.append(email)
        # A person who already signed in as a member carries the new role from the next request:
        # ``authenticate`` copies ``entry.role`` onto the user row every time.
        for user in db.scalars(select(User).where(User.email == email)).all():
            if user.role != "admin":
                user.role = "admin"
    db.commit()
    return changed
