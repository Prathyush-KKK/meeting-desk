"""Admin - connections (connect, reconnect, health, key rotation), the allow-list, activity, jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log, recent
from app.auth.deps import authenticate, require_admin
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.google import get_google
from app.google import oauth as connect_flow
from app.google.interface import GoogleSuite
from app.google.tokens import TokenCipher, rotate_connections
from app.jobs.fetch_doc import fetch_missing_docs
from app.jobs.token_health import check_connection_health
from app.models import AllowListEntry, Connection, User
from app.routes.common import get_clock, get_config
from app.routes.meetings import clear_calendar_cache
from app.schemas import AllowListIn, AllowListPatchIn, activity_out, allow_entry_out, connection_out

router = APIRouter(prefix="/admin", tags=["admin"])

ONE_CONNECTION_WARNING = (
    "Only one Google account is connected. Connect a second so reads keep working if one expires."
)
CONNECT_STATE_KEY = "connect_state"
CONNECT_VERIFIER_KEY = "connect_code_verifier"
CONNECT_NEXT_KEY = "connect_next"
FIRST_RUN_NOTICE = (
    "No Google account is connected yet, so the calendar, Notes by Gemini and Sheets are off. "
    "Connect yours to switch them on."
)
FIRST_RUN_NOTICE_MEMBER = (
    "No Google account is connected yet, so the calendar, Notes by Gemini and Sheets are off. "
    "Paste, points and manual meetings work; ask an admin to connect one: {admins}."
)


def _banner(rows: list[Connection]) -> str:
    expired = [c.email for c in rows if c.status != "ok"]
    if not expired:
        return ""
    return (
        f"Google connection needs reconnecting: {', '.join(expired)}. "
        "Paste, points and manual meetings keep working."
    )


def safe_next(value: str) -> str:
    """Where to land after the connect flow: a path inside the app, never another host."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/admin"
    return value


@router.get("/connections")
def list_connections(
    db: Session = Depends(get_session),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    rows = list(db.scalars(select(Connection).order_by(Connection.connected_at)).all())
    return {
        "connections": [connection_out(c) for c in rows],
        # "Only one" is wrong with none; the first-run notice covers that case.
        "warning": ONE_CONNECTION_WARNING if len(rows) == 1 else "",
        "banner": _banner(rows),
        # First run: nothing is connected at all. The app shows this with a Connect button, and
        # sign-in sends a new admin straight to the consent screen (app.auth.oidc).
        "first_run": not rows,
        "first_run_notice": FIRST_RUN_NOTICE if not rows else "",
    }


@router.get("/connections/status")
def connection_status(
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """The banner, for everyone signed in - not only admins.

    When an admin connection expires, a banner on every page names the connection and the admin.
    ``GET /connections`` is admin-only, so a member would see no banner at all. This answers only
    what the banner says: which connection needs reconnecting, and whether nothing is connected yet
    - no scopes, no list.
    """
    rows = list(db.scalars(select(Connection).order_by(Connection.connected_at)).all())
    admins = db.scalars(select(AllowListEntry.email).where(AllowListEntry.role == "admin")).all()
    is_admin = user.role == "admin"
    first_run = not rows
    notice = ""
    if first_run:
        notice = FIRST_RUN_NOTICE if is_admin else FIRST_RUN_NOTICE_MEMBER.format(
            admins=", ".join(admins) or "the workspace owner"
        )
    return {
        "banner": _banner(rows),
        "first_run": first_run,
        "first_run_notice": notice,
        "can_connect": is_admin,
    }


@router.post("/connections/health")
def run_health_check(
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    unhealthy = check_connection_health(db, google, clock.now())
    return {"checked": True, "unhealthy": [c.email for c in unhealthy]}


# --- connect an account (OAuth authorization code, offline access) ----------------------------------


def _require_connect_config(settings: Settings) -> TokenCipher:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Connecting a Google account needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    cipher = TokenCipher.from_settings(settings)
    if cipher is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Connecting a Google account needs MEETING_DESK_TOKEN_KEY so the refresh token can be stored.",
        )
    return cipher


@router.get("/connections/connect")
def connect_account(
    request: Request,
    email: str = "",
    next: str = "/admin",
    settings: Settings = Depends(get_config),
    user: User = Depends(require_admin),
) -> Response:
    """Send the admin to Google.

    ``email`` pre-selects the account (a reconnect, or the person who just signed in); ``next`` is
    the app path to land on afterwards - ``/admin`` by default, ``/`` when sign-in started this so
    the person arrives at Step 1 with their calendar already there.
    """
    _require_connect_config(settings)
    client = connect_flow.oauth_client(settings, getattr(request.app.state, "transport", None))
    url, state, verifier = connect_flow.authorization_url(client, settings, login_hint=email)
    request.session[CONNECT_STATE_KEY] = state
    request.session[CONNECT_VERIFIER_KEY] = verifier
    request.session[CONNECT_NEXT_KEY] = safe_next(next)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/connections/callback")
def connect_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(require_admin),
) -> Response:
    cipher = _require_connect_config(settings)
    expected = request.session.pop(CONNECT_STATE_KEY, None)
    verifier = request.session.pop(CONNECT_VERIFIER_KEY, "") or ""
    back_to = safe_next(str(request.session.pop(CONNECT_NEXT_KEY, "") or ""))
    if error:
        log(db, user.email, f"Google connection refused: {error}")
        return _back_to_app(settings, back_to, error=error)
    if not code or not state or not expected or state != expected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The connect flow did not come back with a valid state."
        )

    client = connect_flow.oauth_client(settings, getattr(request.app.state, "transport", None))
    try:
        token = connect_flow.exchange_code(client, code, verifier)
        info = connect_flow.fetch_userinfo(client, token)
    except connect_flow.ConnectError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    account = str(info.get("email") or "").strip().lower()
    domain = str(info.get("hd") or "") or account.split("@")[-1]
    if not account:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google did not say whose account this is.")
    if settings.google_hosted_domain and domain != settings.google_hosted_domain:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Connect a {settings.google_hosted_domain} account, not {account}."
        )
    try:
        connection, created = connect_flow.store_connection(
            db, cipher, email=account, name=str(info.get("name") or ""), token=token, now=clock.now()
        )
    except connect_flow.ConnectError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    forget = getattr(google, "forget_connection", None)
    if callable(forget):
        forget(connection.email)
    # The merged meeting list is cached per healthy connection set; this account's calendar is new
    # to it, so the entry filled a moment ago must go.
    clear_calendar_cache(request)
    missing = connect_flow.missing_scopes(list(connection.scopes or []))
    log(db, user.email, f"{'Connected' if created else 'Reconnected'} Google account {connection.email}")
    # A scope left unticked is worth a look at the Admin page whatever ``next`` said.
    return _back_to_app(
        settings,
        "/admin" if missing else back_to,
        connected=connection.email,
        missing=",".join(missing) if missing else None,
    )


def _back_to_app(settings: Settings, path: str, **params: str | None) -> Response:
    """303 to the web app at ``path`` (``/`` is the capture flow, ``/admin`` the Admin page)."""
    query = urlencode({k: v for k, v in params.items() if v})
    base = settings.web_base_url.rstrip("/")
    path = safe_next(path)
    url = base + path + (f"?{query}" if query else "")
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/connections/rotate-keys")
def rotate_keys(
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_config),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """After a key rotation: re-encrypt every stored refresh token with the current key."""
    cipher = _require_connect_config(settings)
    rotated = rotate_connections(db, cipher)
    if rotated:
        log(
            db,
            user.email,
            f"Re-encrypted {len(rotated)} connection token(s) with key version {cipher.version}",
        )
    return {"key_version": cipher.version, "rotated": rotated}


@router.post("/jobs/fetch-docs")
def run_fetch_docs(
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """One pass of the Doc re-check, by hand (the queue runs it every 5 minutes)."""
    return fetch_missing_docs(db, google, clock).to_dict()


@router.post("/fake/reset")
def reset_fake_google(
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    settings: Settings = Depends(get_config),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Put the in-memory Google back to its seeded state. Only with ``FAKE_GOOGLE=1``.

    The fake keeps its spreadsheets in the API process's memory - one instance per process, on
    ``app.state.google`` - so the e2e walkthrough's rows accumulate across runs against one
    long-lived dev server. Restarting the API has always been the reset; this is the same thing
    without the restart. It does not touch the database.
    """
    reset = getattr(google, "reset", None)
    if not settings.fake_google or not callable(reset):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is no fake Google to reset: this process is running against the real clients.",
        )
    reset()
    log(db, user.email, "Reset the in-memory Google (fake mode)")
    return {"ok": True, "fake_google": True}


@router.get("/allow-list")
def list_allow_list(
    db: Session = Depends(get_session),
    user: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(AllowListEntry).order_by(AllowListEntry.added_at)).all()
    return [allow_entry_out(e) for e in rows]


@router.post("/allow-list", status_code=status.HTTP_201_CREATED)
def add_to_allow_list(
    body: AllowListIn,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    email = body.email.strip().lower()
    if db.get(AllowListEntry, email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} is already on the allow-list.")
    entry = AllowListEntry(email=email, role=body.role, added_by=user.email, added_at=clock.now())
    db.add(entry)
    log(db, user.email, f"Added {email} to the allow-list as {body.role}")
    return allow_entry_out(entry)


@router.patch("/allow-list/{email}")
def patch_allow_list(
    email: str,
    body: AllowListPatchIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """An admin can fix an email in place when the Google account turned out to differ."""
    entry = db.get(AllowListEntry, email.strip().lower())
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown allow-list entry")
    data = body.model_dump(exclude_unset=True)
    if data.get("role"):
        entry.role = data["role"]
        if entry.matched_user_id:
            matched = db.get(User, entry.matched_user_id)
            if matched:
                matched.role = entry.role
    if data.get("email") and data["email"].strip().lower() != entry.email:
        replacement = AllowListEntry(
            email=data["email"].strip().lower(),
            role=entry.role,
            added_by=entry.added_by,
            added_at=entry.added_at,
            matched_user_id=entry.matched_user_id,
        )
        db.delete(entry)
        db.add(replacement)
        db.flush()
        log(db, user.email, f"Changed an allow-list email to {replacement.email}")
        return allow_entry_out(replacement)
    log(db, user.email, f"Updated the allow-list entry for {entry.email}")
    return allow_entry_out(entry)


@router.delete("/allow-list/{email}")
def remove_from_allow_list(
    email: str,
    db: Session = Depends(get_session),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    entry = db.get(AllowListEntry, email.strip().lower())
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown allow-list entry")
    if entry.email == user.email:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove your own access.")
    db.delete(entry)
    log(db, user.email, f"Removed {entry.email} from the allow-list")
    return {"ok": True, "email": entry.email}


@router.get("/activity")
def list_activity(
    limit: int = 100,
    db: Session = Depends(get_session),
    user: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    return [activity_out(a) for a in recent(db, limit)]


@router.get("/health")
def workspace_health(
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    connections = list(db.scalars(select(Connection)).all())
    now: datetime = clock.now()
    return {
        "now": now.isoformat(),
        "connections_ok": sum(1 for c in connections if c.status == "ok"),
        "connections_total": len(connections),
        "allow_list": db.scalar(select(AllowListEntry.email).limit(1)) is not None,
    }
