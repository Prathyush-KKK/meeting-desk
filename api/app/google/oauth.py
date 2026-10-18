"""'Connect an account': the OAuth authorization-code flow for an admin connection.

Distinct from sign-in (``app/auth/oidc.py``, which only identifies a person). This one asks for the
scope list below with offline access so a refresh token comes back, ``prompt=consent`` so Google
issues that refresh token every time (a reconnect replaces a revoked one), and
``include_granted_scopes`` so a later, wider request keeps what was granted before (incremental
consent). Built on authlib's ``OAuth2Client``; the token exchange goes through the same transport
as the Google clients, so it is mocked the same way in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import OAuth2Client
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.google.tokens import TokenCipher
from app.models import Connection

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Read Calendar, Drive, Docs and Gmail; write Sheets; search the directory for owner resolution;
# identify the account.
CONNECTION_SCOPES: list[str] = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/directory.readonly",
]
# The short names the Admin page shows.
SCOPE_LABELS = {
    "https://www.googleapis.com/auth/calendar.readonly": "calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly": "drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly": "documents.readonly",
    "https://www.googleapis.com/auth/gmail.readonly": "gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets": "spreadsheets",
    "https://www.googleapis.com/auth/directory.readonly": "directory.readonly",
}


GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DIRECTORY_SCOPE = "https://www.googleapis.com/auth/directory.readonly"


def connection_scopes(settings: Settings | None = None) -> list[str]:
    """``CONNECTION_SCOPES`` without the ones ``GOOGLE_USE_GMAIL`` / ``GOOGLE_USE_DIRECTORY`` turn off."""
    off = set()
    if settings is not None and not settings.google_use_gmail:
        off.add(GMAIL_SCOPE)
    if settings is not None and not settings.google_use_directory:
        off.add(DIRECTORY_SCOPE)
    return [s for s in CONNECTION_SCOPES if s not in off]


class ConnectError(RuntimeError):
    pass


def is_configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.token_key)


def oauth_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> OAuth2Client:
    return OAuth2Client(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scope=" ".join(connection_scopes(settings)),
        redirect_uri=settings.google_connect_redirect_uri,
        # Google documents client_id / client_secret in the token request body.
        token_endpoint_auth_method="client_secret_post",
        # PKCE: the authorization request carries the S256 challenge, the token request the
        # verifier. An authorization code intercepted on the way back is then worth nothing on its
        # own, which is what stops a code injected into the callback from becoming a connection.
        code_challenge_method="S256",
        transport=transport,
        timeout=settings.google_api_timeout_seconds,
    )


def authorization_url(client: OAuth2Client, settings: Settings, login_hint: str = "") -> tuple[str, str, str]:
    """(url, state, code_verifier). Offline access, forced consent, incremental scopes, the domain.

    The verifier is the caller's to keep for the length of the round trip (the connect route puts
    it in the session beside the state) and to hand back to ``exchange_code``.
    """
    extra: dict[str, Any] = {
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if settings.google_hosted_domain:
        extra["hd"] = settings.google_hosted_domain
    if login_hint:
        extra["login_hint"] = login_hint
    code_verifier = generate_token(48)
    url, state = client.create_authorization_url(AUTH_URL, code_verifier=code_verifier, **extra)
    return url, state, code_verifier


def exchange_code(client: OAuth2Client, code: str, code_verifier: str = "") -> dict[str, Any]:
    try:
        token = client.fetch_token(
            TOKEN_URL,
            code=code,
            grant_type="authorization_code",
            **({"code_verifier": code_verifier} if code_verifier else {}),
        )
    except Exception as exc:  # authlib raises its own hierarchy; the message is what matters
        raise ConnectError(f"Google refused the authorization code: {exc}") from exc
    return dict(token)


def fetch_userinfo(client: OAuth2Client, token: dict[str, Any]) -> dict[str, Any]:
    response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {token.get('access_token', '')}"})
    if response.status_code >= 400:
        raise ConnectError(f"Google did not say whose account this is ({response.status_code}).")
    return dict(response.json())


def granted_scopes(token: dict[str, Any]) -> list[str]:
    raw = token.get("scope") or ""
    scopes = raw.split() if isinstance(raw, str) else list(raw)
    return [SCOPE_LABELS.get(s, s) for s in scopes if s in SCOPE_LABELS]


def missing_scopes(labels: list[str], settings: Settings | None = None) -> list[str]:
    wanted = [label for scope, label in SCOPE_LABELS.items() if scope in connection_scopes(settings)]
    return [s for s in wanted if s not in labels]


def store_connection(
    db: Session,
    cipher: TokenCipher,
    *,
    email: str,
    name: str,
    token: dict[str, Any],
    now: datetime,
) -> tuple[Connection, bool]:
    """Upsert the connection. A missing refresh token keeps the one already stored."""
    email = email.strip().lower()
    connection = db.scalar(select(Connection).where(Connection.email == email))
    created = connection is None
    if connection is None:
        connection = Connection(email=email, name=name, connected_at=now)
        db.add(connection)
    if name:
        connection.name = name
    scopes = granted_scopes(token)
    previous = [s for s in (connection.scopes or []) if isinstance(s, str)]
    order = list(SCOPE_LABELS.values())
    connection.scopes = sorted(
        set(previous) | set(scopes), key=lambda s: order.index(s) if s in order else len(order)
    )
    refresh_token = token.get("refresh_token")
    if refresh_token:
        connection.refresh_token_enc, connection.key_version = cipher.encrypt(str(refresh_token))
    elif not connection.refresh_token_enc:
        raise ConnectError(
            "Google returned no refresh token. Remove Meeting Desk from the account's connected apps "
            "and connect again."
        )
    connection.status = "ok"
    connection.connected_at = now
    connection.last_ok_at = now
    connection.last_error = None
    db.flush()
    return connection, created
