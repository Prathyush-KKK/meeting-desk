"""Who is asking, and may they.

Order is always the same: identify (dev bypass or session cookie), then check the allow-list, then
bind the entry to the Google ``sub`` on first sign-in so a changed email keeps working.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import AllowListEntry, User

LAST_SEEN_INTERVAL_SECONDS = 60

NOT_ALLOWED = (
    "This Google account is not on the Meeting Desk allow-list. Ask an admin to add it: " "{admins}."
)


def get_config(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _admin_emails(db: Session) -> str:
    rows = db.scalars(select(AllowListEntry.email).where(AllowListEntry.role == "admin")).all()
    return ", ".join(rows) if rows else "the workspace owner"


def _ensure_user(db: Session, google_sub: str, email: str, name: str, role: str) -> User:
    user = _find_user(db, google_sub, email)
    if user is None:
        user = User(google_sub=google_sub, email=email, name=name or email.split("@")[0], role=role)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # A first sign-in is several requests at once (the app polls four lists on load), so two
            # of them can reach this insert together and one loses the unique index on google_sub.
            # That is not an error: the row the other request wrote is the row this one wanted.
            db.rollback()
            user = _find_user(db, google_sub, email)
            if user is None:  # pragma: no cover - the constraint says it is there
                raise
    if user.google_sub != google_sub:
        user.google_sub = google_sub
    user.email = email
    if name:
        user.name = name
    user.role = role
    now = datetime.now(timezone.utc)
    # Once a minute, not once a request: every request used to write this column, and that
    # UPDATE took a row lock the request's transaction held until it answered. An extraction
    # holds its transaction across the whole model call, so for that minute every other request
    # from the same person queued behind it on their own users row (the list, the notes, the
    # points), and the app looked dead. See also ``authenticate``, which commits before the route.
    seen = user.last_seen_at
    if seen is not None and seen.tzinfo is None:  # SQLite hands the column back naive
        seen = seen.replace(tzinfo=timezone.utc)
    if seen is None or (now - seen).total_seconds() >= LAST_SEEN_INTERVAL_SECONDS:
        user.last_seen_at = now
    return user


def _find_user(db: Session, google_sub: str, email: str) -> User | None:
    return db.scalar(select(User).where(User.google_sub == google_sub)) or db.scalar(
        select(User).where(User.email == email)
    )


def authenticate(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_config),
) -> User:
    """The one place a request turns into a user."""
    if settings.auth_dev_user:
        email = settings.auth_dev_user.strip().lower()
        google_sub = f"dev|{email}"
        name = email.split("@")[0].replace(".", " ").title()
    else:
        from app.auth import session as session_cookie

        payload = session_cookie.read(settings, request.cookies.get(settings.session_cookie))
        if not payload:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in with Google to continue.")
        google_sub = str(payload["sub"])
        email = str(payload["email"]).strip().lower()
        name = ""

    entry = db.get(AllowListEntry, email)
    if entry is None:
        # An allow-list email may differ from the Google account; the sub binding covers that once
        # the person has signed in at least once.
        entry = db.scalar(
            select(AllowListEntry)
            .where(AllowListEntry.matched_user_id.is_not(None))
            .where(AllowListEntry.matched_user_id.in_(select(User.id).where(User.google_sub == google_sub)))
        )
    if entry is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_ALLOWED.format(admins=_admin_emails(db)))

    user = _ensure_user(db, google_sub, email, name, entry.role)
    if entry.matched_user_id is None:
        entry.matched_user_id = user.id
    # What sign-in wrote is its own short transaction: the route's transaction starts after this,
    # so a route that holds its transaction for a long time (an inline extraction) holds no lock on
    # the users row that every other request of the same person has to touch.
    db.commit()
    return user


def require_admin(user: User = Depends(authenticate)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only.")
    return user


CurrentUser = Depends(authenticate)
AdminUser = Depends(require_admin)
