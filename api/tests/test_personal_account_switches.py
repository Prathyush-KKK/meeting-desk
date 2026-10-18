"""GOOGLE_USE_GMAIL=0 and GOOGLE_USE_DIRECTORY=0: the setup for a personal Google account.

Gmail is a restricted scope (an External OAuth app needs Google's verification for it) and the
directory only exists in Google Workspace, so either can be left out: the scope is not requested,
a missing grant is not reported, and the client finds nothing instead of failing.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import Settings
from app.google.oauth import (
    CONNECTION_SCOPES,
    DIRECTORY_SCOPE,
    GMAIL_SCOPE,
    connection_scopes,
    missing_scopes,
)
from app.google.real import NoDirectory, NoGmail, RealGoogle
from app.google.tokens import generate_key
from app.main import create_app
from tests.conftest import make_settings
from tests.google_mock import MockGoogleApi


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_both_switches_default_on() -> None:
    assert connection_scopes(settings()) == CONNECTION_SCOPES
    assert connection_scopes(None) == CONNECTION_SCOPES


def test_a_switched_off_scope_is_not_requested_and_not_reported_missing() -> None:
    personal = settings(google_use_gmail=False, google_use_directory=False)
    scopes = connection_scopes(personal)
    assert GMAIL_SCOPE not in scopes and DIRECTORY_SCOPE not in scopes
    assert len(scopes) == len(CONNECTION_SCOPES) - 2

    granted = ["calendar.readonly", "drive.readonly", "documents.readonly", "spreadsheets"]
    assert missing_scopes(granted, personal) == []
    assert missing_scopes(granted, settings()) == ["gmail.readonly", "directory.readonly"]


def test_the_connect_redirect_asks_only_for_the_scopes_in_use(tmp_path: Path) -> None:
    app = create_app(
        make_settings(
            tmp_path,
            google_client_id="client-id.apps.googleusercontent.com",
            google_client_secret="client-secret",
            token_key=generate_key(),
            google_hosted_domain="",
            google_use_gmail=False,
            google_use_directory=False,
        ),
        transport=MockGoogleApi().transport(),
    )
    with TestClient(app) as client:
        response = client.get("/admin/connections/connect", follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    requested = query["scope"][0].split()
    assert GMAIL_SCOPE not in requested and DIRECTORY_SCOPE not in requested
    assert "hd" not in query  # no domain set: any Google account may be connected


def test_the_real_suite_swaps_in_clients_that_find_nothing() -> None:
    suite = RealGoogle(http=None, use_gmail=False, use_directory=False)  # type: ignore[arg-type]
    assert isinstance(suite.gmail, NoGmail) and isinstance(suite.people, NoDirectory)
    assert suite.gmail.search_messages("me@gmail.com", "from:gemini-notes@google.com") == []
    assert suite.people.search_directory("me@gmail.com", "Alex") == []
