"""The real Google suite, assembled from the clients under ``app/google/``.

One ``GoogleHttp`` (bearer tokens, retries, backoff, error mapping) feeds every client. The
refresh tokens come from the ``connections`` table through ``DbRefreshTokens`` and the Fernet
cipher configured by ``MEETING_DESK_TOKEN_KEY``. A ``transport`` can be injected so a test app in
real mode runs against ``httpx.MockTransport`` instead of the network.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.google.calendar import RealCalendarClient
from app.google.docs import RealDocsClient
from app.google.drive import RealDriveClient
from app.google.gmail import RealGmailClient
from app.google.http import AccessTokens, GoogleHttp
from app.google.interface import DirectoryPerson, GmailMessage
from app.google.people import RealPeopleClient
from app.google.sheets import RealSheetsClient
from app.google.tokens import DbRefreshTokens, TokenBroker, TokenCipher


class NoGmail:
    """``GOOGLE_USE_GMAIL=0``: the scope is never asked for, so there is no mailbox to search."""

    def search_messages(self, connection_email: str, query: str) -> list[GmailMessage]:
        return []


class NoDirectory:
    """``GOOGLE_USE_DIRECTORY=0`` (a personal account has no directory): owners resolve against
    the attendees only."""

    def search_directory(self, connection_email: str, query: str) -> list[DirectoryPerson]:
        return []


class RealGoogle:
    """The suite the app asks for; every client Protocol, backed by the REST endpoints."""

    def __init__(
        self,
        http: GoogleHttp,
        *,
        display_tz: str = "",
        calendar_cache_seconds: float = 60.0,
        sheets_max_rows: int = 5000,
        wall_clock: Any = None,
        use_gmail: bool = True,
        use_directory: bool = True,
    ) -> None:
        self.http = http
        self.calendar = RealCalendarClient(http, display_tz, cache_seconds=calendar_cache_seconds)
        self.drive = RealDriveClient(http, display_tz)
        self.docs = RealDocsClient(http)
        self.gmail: Any = RealGmailClient(http, display_tz) if use_gmail else NoGmail()
        self.sheets = RealSheetsClient(
            http, self.drive, display_tz, max_rows=sheets_max_rows, wall_clock=wall_clock
        )
        self.people: Any = RealPeopleClient(http) if use_directory else NoDirectory()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        database: Any,
        transport: httpx.BaseTransport | None = None,
        tokens: AccessTokens | None = None,
        wall_clock: Any = None,
    ) -> RealGoogle:
        if tokens is None:
            cipher = TokenCipher.from_settings(settings)
            if cipher is None:
                raise RuntimeError(
                    "FAKE_GOOGLE is off but MEETING_DESK_TOKEN_KEY is empty. Generate one with "
                    "`python -c 'from app.google.tokens import generate_key; print(generate_key())'`."
                )
            if not settings.google_client_id or not settings.google_client_secret:
                raise RuntimeError(
                    "FAKE_GOOGLE is off but GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are empty."
                )
            tokens = TokenBroker.from_settings(
                settings,
                DbRefreshTokens(database, cipher),
                httpx.Client(transport=transport, timeout=settings.google_api_timeout_seconds),
            )
        http = GoogleHttp(
            tokens,
            transport,
            timeout=settings.google_api_timeout_seconds,
            max_retries=settings.google_max_retries,
            backoff_base=settings.google_backoff_base_seconds,
            connection_backoff_seconds=settings.google_connection_backoff_seconds,
        )
        return cls(
            http,
            display_tz=settings.display_timezone,
            calendar_cache_seconds=settings.calendar_cache_seconds,
            sheets_max_rows=settings.sheets_max_rows,
            wall_clock=wall_clock,
            use_gmail=settings.google_use_gmail,
            use_directory=settings.google_use_directory,
        )

    def forget_connection(self, connection_email: str) -> None:
        """After a reconnect: drop cached tokens, backoff state and cached calendar pages."""
        self.http.forget(connection_email)
        self.calendar.forget(connection_email)
        self.sheets.forget(connection_email)

    def close(self) -> None:
        self.http.close()
        broker_client = getattr(self.http.tokens, "http", None)
        if broker_client is not None and hasattr(broker_client, "close"):
            broker_client.close()
