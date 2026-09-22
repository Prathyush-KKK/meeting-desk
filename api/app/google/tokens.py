"""Refresh tokens at rest, access tokens in flight.

* ``TokenCipher`` - Fernet over the refresh token. ``MEETING_DESK_TOKEN_KEY`` is the current key,
  ``MEETING_DESK_TOKEN_KEY_VERSION`` its number (stored on ``connections.key_version``), and
  ``MEETING_DESK_TOKEN_KEY_PREVIOUS`` the key being rotated out. Decrypting tries the key that
  matches the row's version first and the other one second, so a rotation is: set PREVIOUS to the
  old key, KEY to the new one, bump VERSION, deploy, then ``rotate_connections`` re-encrypts every
  row and PREVIOUS can be dropped.
* ``TokenBroker`` - turns a connection's refresh token into a bearer token, caches it until it
  expires, refreshes it again on demand (the HTTP layer asks for that on a 401), and raises
  ``AuthExpired`` when Google answers ``invalid_grant``. The route or job that catches it marks the
  connection ``expired`` with ``last_error`` in its own session (``routes/common.py``), so no second
  writer competes with the request's transaction.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.config import Settings
from app.google.interface import AuthExpired, GoogleError
from app.models import Connection
from app.telemetry import events
from app.telemetry.breaker import BreakerOpen
from app.telemetry.events import FailureReason
from app.telemetry.logs import get_logger, log_event
from app.telemetry.providers import GOOGLE_OAUTH, track_provider

log = get_logger("tokens")

TOKEN_URL = "https://oauth2.googleapis.com/token"
# Refresh a little before Google says the token dies, so a slow request does not straddle it.
EXPIRY_MARGIN_SECONDS = 60


def _connection_ref(email: str) -> str:
    """A stable handle for one connection that is not the person's address.

    Logs never carry a user identifier (the standard); an admin matches this against the Admin page
    by running the same hash, or simply reads which connection the banner names.
    """
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


class TokenDecryptError(RuntimeError):
    """No configured key opens this ciphertext: the row predates the keys we have."""


def generate_key() -> str:
    """A fresh Fernet key, base64 text, for ``MEETING_DESK_TOKEN_KEY``."""
    return Fernet.generate_key().decode()


class TokenCipher:
    def __init__(self, key: str, version: int = 1, previous: str = "") -> None:
        if not key:
            raise ValueError(
                "MEETING_DESK_TOKEN_KEY is empty; generate one with app.google.tokens.generate_key()"
            )
        self.version = int(version)
        self._current = Fernet(key.encode() if isinstance(key, str) else key)
        self._previous = Fernet(previous.encode()) if previous else None

    @classmethod
    def from_settings(cls, settings: Settings) -> TokenCipher | None:
        if not settings.token_key:
            return None
        return cls(settings.token_key, settings.token_key_version, settings.token_key_previous)

    def encrypt(self, plain: str) -> tuple[str, int]:
        """Ciphertext and the key version that made it."""
        return self._current.encrypt(plain.encode()).decode(), self.version

    def decrypt(self, token_enc: str, key_version: int | None) -> str:
        """The key registered for the row's version first, then the other one (rotation window)."""
        order = [self._current, self._previous]
        if key_version is not None and int(key_version) < self.version:
            order.reverse()
        for fernet in order:
            if fernet is None:
                continue
            try:
                return fernet.decrypt(token_enc.encode()).decode()
            except InvalidToken:
                continue
        raise TokenDecryptError(f"no configured token key decrypts a version {key_version} token")

    def needs_rotation(self, key_version: int | None) -> bool:
        return key_version is None or int(key_version) != self.version


def rotate_connections(db: Any, cipher: TokenCipher) -> list[str]:
    """Re-encrypt every connection still on an older key. Returns the emails touched."""
    rotated: list[str] = []
    for connection in db.scalars(select(Connection)).all():
        if not connection.refresh_token_enc or not cipher.needs_rotation(connection.key_version):
            continue
        plain = cipher.decrypt(connection.refresh_token_enc, connection.key_version)
        connection.refresh_token_enc, connection.key_version = cipher.encrypt(plain)
        rotated.append(connection.email)
    return rotated


# --- where refresh tokens come from -----------------------------------------------------------------


class RefreshTokenStore(Protocol):
    def refresh_token_for(self, connection_email: str) -> str: ...


class DbRefreshTokens:
    """Reads ``connections`` through its own short read-only session, from any thread or job."""

    def __init__(self, database: Any, cipher: TokenCipher) -> None:
        self._db = database
        self._cipher = cipher

    def refresh_token_for(self, connection_email: str) -> str:
        with self._db.session() as session:
            connection = session.scalar(select(Connection).where(Connection.email == connection_email))
            if connection is None:
                raise AuthExpired(f"{connection_email} is not a connected account")
            if not connection.refresh_token_enc:
                raise AuthExpired(f"{connection_email} has no refresh token stored; connect it again")
            try:
                return self._cipher.decrypt(connection.refresh_token_enc, connection.key_version)
            except TokenDecryptError as exc:
                raise AuthExpired(f"{connection_email}: {exc}") from exc


class InMemoryRefreshTokens:
    """For tests: a dict of email -> refresh token."""

    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self.tokens = dict(tokens or {})

    def refresh_token_for(self, connection_email: str) -> str:
        try:
            return self.tokens[connection_email]
        except KeyError as exc:
            raise AuthExpired(f"{connection_email} is not a connected account") from exc


# --- access tokens ------------------------------------------------------------------------------


@dataclass(slots=True)
class _Cached:
    token: str
    expires_at: float


@dataclass(slots=True)
class TokenBroker:
    """Bearer tokens per connection, refreshed from the stored refresh token."""

    client_id: str
    client_secret: str
    store: RefreshTokenStore
    http: httpx.Client
    now: Callable[[], float] = time.time
    _cache: dict[str, _Cached] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings, store: RefreshTokenStore, http: httpx.Client) -> TokenBroker:
        return cls(settings.google_client_id, settings.google_client_secret, store, http)

    def access_token(self, connection_email: str, force_refresh: bool = False) -> str:
        cached = self._cache.get(connection_email)
        if cached and not force_refresh and cached.expires_at > self.now():
            return cached.token
        return self._refresh(connection_email)

    def forget(self, connection_email: str) -> None:
        self._cache.pop(connection_email, None)

    def _refresh(self, connection_email: str) -> str:
        """The OAuth token endpoint is an outbound dependency like any other.

        It gets its own provider (``google_oauth``) because "OAuth refresh failures" is one of the
        alerts the spec asks for, and because an ``invalid_grant`` on one connection says nothing
        about Google's health - it is counted as an error but never moves the breaker.
        """
        try:
            with track_provider(GOOGLE_OAUTH, "token_refresh"):
                return self._refresh_once(connection_email)
        except BreakerOpen as exc:
            raise GoogleError(str(exc)) from exc
        except AuthExpired as exc:
            log_event(
                log,
                events.OAUTH_REFRESH_FAILED,
                level=logging.ERROR,
                provider=GOOGLE_OAUTH,
                op="token_refresh",
                connection=_connection_ref(connection_email),
                failure_reason=FailureReason.AUTH_EXPIRED,
            )
            raise exc

    def _refresh_once(self, connection_email: str) -> str:
        refresh_token = self.store.refresh_token_for(connection_email)
        try:
            response = self.http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleError(f"token endpoint unreachable: {exc}") from exc

        body: dict[str, Any] = {}
        with contextlib.suppress(ValueError):
            body = response.json()
        if response.status_code >= 400:
            error = str(body.get("error", response.status_code))
            description = str(body.get("error_description", "")).strip()
            message = f"{error}: {description}" if description else error
            if error in ("invalid_grant", "unauthorized_client", "invalid_client"):
                # Revoked, password changed, testing-mode expiry: the admin has to reconnect.
                self.forget(connection_email)
                raise AuthExpired(f"{connection_email}: {message}")
            raise GoogleError(f"token refresh failed for {connection_email}: {message}")

        token = str(body.get("access_token", ""))
        if not token:
            raise GoogleError(f"token refresh for {connection_email} returned no access token")
        ttl = float(body.get("expires_in", 3600))
        self._cache[connection_email] = _Cached(token, self.now() + max(0.0, ttl - EXPIRY_MARGIN_SECONDS))
        return token


class StaticTokens:
    """For tests: fixed bearer tokens, no refresh endpoint."""

    def __init__(self, tokens: dict[str, str] | None = None, default: str = "test-token") -> None:
        self.tokens = dict(tokens or {})
        self.default = default
        self.refreshes: list[str] = []

    def access_token(self, connection_email: str, force_refresh: bool = False) -> str:
        if force_refresh:
            self.refreshes.append(connection_email)
        return self.tokens.get(connection_email, self.default)

    def forget(self, connection_email: str) -> None:
        pass
