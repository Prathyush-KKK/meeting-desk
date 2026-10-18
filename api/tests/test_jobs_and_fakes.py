"""The background jobs, and the fake Google's conformance to the interfaces."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app import seed_data
from app.extract.vertex import VertexExtractionProvider
from app.google.fake import FakeGoogle
from app.google.interface import (
    AuthExpired,
    CalendarClient,
    DocsClient,
    DriveClient,
    GmailClient,
    PeopleClient,
    PermissionDenied,
    SheetsClient,
)
from app.google.real import RealGoogle
from app.jobs.fetch_doc import fetch_notes_doc
from app.jobs.token_health import check_connection_health
from app.models import Meeting

IST = ZoneInfo("Asia/Kolkata")


def test_the_fake_satisfies_every_client_protocol() -> None:
    google = FakeGoogle()
    assert isinstance(google.calendar, CalendarClient)
    assert isinstance(google.drive, DriveClient)
    assert isinstance(google.docs, DocsClient)
    assert isinstance(google.gmail, GmailClient)
    assert isinstance(google.sheets, SheetsClient)
    assert isinstance(google.people, PeopleClient)


def test_the_real_suite_satisfies_every_client_protocol() -> None:
    from app.google.http import GoogleHttp
    from app.google.tokens import StaticTokens

    google = RealGoogle(GoogleHttp(StaticTokens(), httpx.MockTransport(lambda r: httpx.Response(404))))
    assert isinstance(google.calendar, CalendarClient)
    assert isinstance(google.drive, DriveClient)
    assert isinstance(google.docs, DocsClient)
    assert isinstance(google.gmail, GmailClient)
    assert isinstance(google.sheets, SheetsClient)
    assert isinstance(google.people, PeopleClient)


def test_real_mode_without_a_token_key_fails_loudly(tmp_path) -> None:
    from app.config import Settings
    from app.db import Database

    settings = Settings(fake_google=False, google_client_id="x", google_client_secret="y")
    with pytest.raises(RuntimeError) as err:
        RealGoogle.from_settings(settings, Database(f"sqlite:///{tmp_path / 'x.db'}"))
    assert "MEETING_DESK_TOKEN_KEY" in str(err.value)


def test_the_vertex_provider_refuses_to_run_unconfigured() -> None:
    from app.config import Settings
    from app.extract.provider import ExtractionError

    provider = VertexExtractionProvider(Settings())
    assert provider.region == "us-central1"
    assert provider.model == "gemini-2.5-flash"
    with pytest.raises(ExtractionError) as err:
        provider.extract("text", None)
    assert "VERTEX_PROJECT" in str(err.value)


def test_the_fake_calendar_window_and_dedup() -> None:
    google = FakeGoogle()
    start, end = seed_data.default_window()
    mine = google.calendar.list_events("daniel.okafor@example.com", start, end)
    theirs = google.calendar.list_events("alex.s@example.com", start, end)
    shared = {e.ical_uid for e in mine} & {e.ical_uid for e in theirs}
    assert shared  # the same event really is on both calendars
    assert all(start <= e.start_at <= end for e in mine)


def test_the_fake_refuses_a_doc_that_is_not_shared() -> None:
    google = FakeGoogle()
    with pytest.raises(PermissionDenied):
        google.docs.get_document("daniel.okafor@example.com", "doc-m4")
    doc = google.docs.get_document("alex.s@example.com", "doc-m4")
    assert [t.title for t in doc.tabs] == ["Quick notes", "Full notes"]


def test_the_fake_docs_carry_the_three_gemini_tabs() -> None:
    google = FakeGoogle()
    doc = google.docs.get_document("daniel.okafor@example.com", "doc-m1")
    assert [t.title for t in doc.tabs] == ["Quick notes", "Full notes", "Transcript"]
    assert doc.tab("Full notes").text.startswith("Platform squad sync - full notes")


def test_the_fake_people_directory_search() -> None:
    google = FakeGoogle()
    hits = google.people.search_directory("daniel.okafor@example.com", "sofia")
    assert [p.email for p in hits] == ["sofia.silva@example.com"]
    assert google.people.search_directory("daniel.okafor@example.com", "") == []


def test_the_fake_cannot_write_where_it_cannot_edit() -> None:
    google = FakeGoogle()
    assert google.sheets.can_edit("alex.s@example.com", "rewards") is True
    assert google.sheets.can_edit("daniel.okafor@example.com", "rewards") is False
    from app.google.interface import SetCell

    with pytest.raises(PermissionDenied):
        google.sheets.batch_update("daniel.okafor@example.com", "rewards", [SetCell("t6", 5, 0, "x")])


def test_the_fixture_tabs_are_available_as_a_workbook() -> None:
    google = FakeGoogle()
    meta = google.sheets.get_spreadsheet("daniel.okafor@example.com", "plannerfixtures")
    titles = {t.sheet_id for t in meta.tabs}
    assert {"headers_row_1", "headers_row_9_banner", "no_header", "two_header_rows"} <= titles


def test_token_health_marks_a_broken_connection(client: TestClient) -> None:
    from app.models import Connection

    class Broken(FakeGoogle):
        def list_events(self, connection_email, time_min, time_max):
            if connection_email == "alex.s@example.com":
                # The refresh token itself refused: this, and only this, means "reconnect me".
                raise AuthExpired("invalid_grant")
            return super().list_events(connection_email, time_min, time_max)

    with client.app.state.db.session() as session:
        unhealthy = check_connection_health(session, Broken(), datetime.now(IST))
        session.commit()
        assert [c.email for c in unhealthy] == ["alex.s@example.com"]
        refreshed = session.query(Connection).filter_by(email="alex.s@example.com").one()
        assert refreshed.status == "expired"
        assert refreshed.last_error == "invalid_grant"


def test_fetch_doc_finds_the_attached_notes_doc(client: TestClient) -> None:
    google = client.app.state.google
    with client.app.state.db.session() as session:
        meeting = session.query(Meeting).filter_by(title="Ethan Interview Task Handover").one()
        found = fetch_notes_doc(google, meeting, ["daniel.okafor@example.com", "alex.s@example.com"])
        assert found is not None
        assert found.id == "doc-m4"


def test_fetch_doc_returns_nothing_when_there_is_no_doc(client: TestClient) -> None:
    with client.app.state.db.session() as session:
        meeting = session.query(Meeting).filter_by(title="Northwind call prep").one()
        assert fetch_notes_doc(client.app.state.google, meeting, ["daniel.okafor@example.com"]) is None


def test_the_calendar_window_reaches_ahead_as_well_as_back() -> None:
    """The list used to end at midnight tonight: a meeting later this week could not be prepared,
    and one older than seven days could not be captured. Both windows are settings now."""
    from datetime import datetime

    from app.routes.meetings import _window

    now = datetime(2026, 9, 29, 10, 30)
    start, end = _window(now, 30, 14)
    assert (start.year, start.month, start.day, start.hour) == (2026, 8, 30, 0)
    assert (end.year, end.month, end.day, end.hour, end.minute) == (2026, 10, 13, 23, 59)
    _, today = _window(now, 7)
    assert (today.month, today.day, today.hour) == (9, 29, 23)
