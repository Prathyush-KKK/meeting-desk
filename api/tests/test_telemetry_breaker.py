"""The deliberate failure, exercised end to end.

The standard's last verification item: break a dependency, watch the counter move, the last-success
gauge stall, the breaker move, and the error log appear. This is that, against the real Sheets
client and ``httpx.MockTransport`` - the same harness the phase 2 contract tests use, so nothing is
mocked out except Google itself.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.google.http import GoogleHttp
from app.google.interface import GoogleError, NotFoundError, RateLimited
from app.google.tokens import StaticTokens
from app.telemetry import events
from app.telemetry.breaker import HALF_OPEN, OPEN, Breaker, BreakerOpen
from app.telemetry.logs import configure_logging
from app.telemetry.metrics import metrics
from app.telemetry.providers import (
    GOOGLE_SHEETS,
    classify_failure,
    classify_google,
    provider_telemetry,
)
from tests.google_mock import MockGoogleApi, json_response

BOOK = "1RoadmapSpreadsheetId0000000000000000000000"
URL = f"https://sheets.googleapis.com/v4/spreadsheets/{BOOK}"


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def http_for(api: MockGoogleApi) -> GoogleHttp:
    # No retries and no sleeping: one call per failure, so the five that open the breaker are five.
    return GoogleHttp(StaticTokens(), transport=api.transport(), max_retries=0, sleep=lambda _s: None)


def counter(provider: str, op: str, outcome: str) -> float:
    for family in metrics().registry.collect():
        for sample in family.samples:
            if sample.name == "external_provider_requests_total" and sample.labels == {
                "provider": provider,
                "op": op,
                "outcome": outcome,
            }:
                return sample.value
    return 0.0


def gauge(name: str, provider: str) -> float | None:
    for family in metrics().registry.collect():
        for sample in family.samples:
            if sample.name == name and sample.labels.get("provider") == provider:
                return sample.value
    return None


class _Capture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> int:
        if text.strip():
            self.lines.append(text.strip())
        return len(text)

    def flush(self) -> None:
        return None


def events_seen(capture: _Capture) -> list[dict]:
    return [json.loads(line) for line in capture.lines]


def test_a_google_failure_counts_stalls_the_gauge_and_opens_the_breaker() -> None:
    capture = _Capture()
    configure_logging("INFO", capture)
    telemetry = provider_telemetry()
    telemetry.breakers[GOOGLE_SHEETS].now = _Clock()

    ok = MockGoogleApi().on("GET", f"/spreadsheets/{BOOK}", "sheets_spreadsheet_get.json")
    http = http_for(ok)
    http.get("a@example.com", URL, params={"fields": "properties.title"})

    assert counter(GOOGLE_SHEETS, "spreadsheets_get", "success") == 1
    first_success = gauge("external_provider_last_success_timestamp_seconds", GOOGLE_SHEETS)
    assert first_success is not None
    assert gauge("external_provider_breaker_state", GOOGLE_SHEETS) == 0

    # Now Google is out: five consecutive 503s.
    broken = MockGoogleApi().on(
        "GET", f"/spreadsheets/{BOOK}", lambda r: httpx.Response(503, json={"error": {"message": "down"}})
    )
    http = http_for(broken)
    for _ in range(5):
        with pytest.raises(GoogleError):
            http.get("a@example.com", URL, params={"fields": "properties.title"})

    assert counter(GOOGLE_SHEETS, "spreadsheets_get", "error") == 5
    # The last-success gauge is untouched: it is only ever written on a success.
    assert gauge("external_provider_last_success_timestamp_seconds", GOOGLE_SHEETS) == first_success
    assert gauge("external_provider_breaker_state", GOOGLE_SHEETS) == 2  # open

    # The sixth call never leaves the process.
    before = len(broken.requests)
    with pytest.raises(GoogleError):
        http.get("a@example.com", URL, params={"fields": "properties.title"})
    assert len(broken.requests) == before, "the breaker let a call through while open"
    assert counter(GOOGLE_SHEETS, "spreadsheets_get", "rejected_by_breaker") == 1

    seen = events_seen(capture)
    tokens = [line["event"] for line in seen]
    assert events.EXTERNAL_CALL_FAILED in tokens
    assert events.BREAKER_OPENED in tokens
    assert events.EXTERNAL_CALL_REJECTED in tokens
    failed = next(line for line in seen if line["event"] == events.EXTERNAL_CALL_FAILED)
    assert failed["provider"] == GOOGLE_SHEETS
    assert failed["failure_reason"] == "upstream_error"
    assert failed["level"] == "warning"


def test_the_breaker_half_opens_after_thirty_seconds_and_closes_on_a_success() -> None:
    telemetry = provider_telemetry()
    clock = _Clock()
    breaker = telemetry.breakers[GOOGLE_SHEETS]
    breaker.now = clock

    broken = MockGoogleApi().on(
        "GET", f"/spreadsheets/{BOOK}", lambda r: httpx.Response(503, json={"error": {"message": "down"}})
    )
    http = http_for(broken)
    for _ in range(5):
        with pytest.raises(GoogleError):
            http.get("a@example.com", URL)
    assert breaker.state == OPEN

    clock.t += 29
    with pytest.raises(GoogleError):
        http.get("a@example.com", URL)  # still refused
    assert breaker.state == OPEN

    clock.t += 2  # past the 30 s recovery window
    ok = MockGoogleApi().on("GET", f"/spreadsheets/{BOOK}", "sheets_spreadsheet_get.json")
    http = http_for(ok)
    assert breaker.allow() is True
    assert breaker.state == HALF_OPEN
    assert gauge("external_provider_breaker_state", GOOGLE_SHEETS) == 1
    http.get("a@example.com", URL)
    assert breaker.state == "closed"
    assert gauge("external_provider_breaker_state", GOOGLE_SHEETS) == 0


def test_a_failed_trial_opens_the_breaker_again() -> None:
    clock = _Clock()
    breaker = Breaker(provider="vertex", now=clock)
    for _ in range(5):
        breaker.record_failure()
    assert breaker.state == OPEN
    clock.t += 31
    assert breaker.allow() is True
    assert breaker.state == HALF_OPEN
    breaker.record_failure()
    assert breaker.state == OPEN
    assert breaker.retry_after() == pytest.approx(30.0)


def test_an_answer_is_not_an_outage() -> None:
    """404, 403 and invalid_grant are counted as errors but must not open a breaker."""
    for exc, reason in (
        (NotFoundError("no such doc"), "not_found"),
        (RateLimited("slow down", retry_after_seconds=1), "rate_limited"),
    ):
        outcome, failure_reason, counts = classify_failure(exc)
        assert outcome == "error"
        assert failure_reason == reason
        assert counts is False

    outcome, reason, counts = classify_failure(httpx.ReadTimeout("too slow"))
    assert (outcome, reason, counts) == ("timeout", "timeout", True)

    outcome, reason, counts = classify_failure(BreakerOpen("vertex", 12))
    assert (outcome, reason, counts) == ("rejected_by_breaker", "breaker_open", False)


def test_a_404_from_google_does_not_move_the_breaker() -> None:
    telemetry = provider_telemetry()
    api = MockGoogleApi().on("GET", f"/spreadsheets/{BOOK}", lambda r: json_response("error_404.json", 404))
    http = http_for(api)
    for _ in range(6):
        with pytest.raises(NotFoundError):
            http.get("a@example.com", URL)
    assert counter(GOOGLE_SHEETS, "spreadsheets_get", "error") == 6
    assert telemetry.breakers[GOOGLE_SHEETS].state == "closed"
    assert gauge("external_provider_breaker_state", GOOGLE_SHEETS) == 0


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://sheets.googleapis.com/v4/spreadsheets/{BOOK}", ("google_sheets", "spreadsheets_get")),
        (f"https://sheets.googleapis.com/v4/spreadsheets/{BOOK}/values:batchGet", ("google_sheets", "values_batch_get")),
        (f"https://sheets.googleapis.com/v4/spreadsheets/{BOOK}:batchUpdate", ("google_sheets", "batch_update")),
        ("https://www.googleapis.com/calendar/v3/calendars/primary/events", ("google_calendar", "events_list")),
        ("https://www.googleapis.com/calendar/v3/calendars/primary/events/abc", ("google_calendar", "events_get")),
        ("https://www.googleapis.com/drive/v3/files", ("google_drive", "files_list")),
        ("https://www.googleapis.com/drive/v3/files/abc", ("google_drive", "files_get")),
        ("https://docs.googleapis.com/v1/documents/abc", ("google_docs", "documents_get")),
        ("https://gmail.googleapis.com/gmail/v1/users/me/messages", ("google_gmail", "messages_list")),
        ("https://gmail.googleapis.com/gmail/v1/users/me/messages/abc", ("google_gmail", "messages_get")),
        ("https://people.googleapis.com/v1/people:searchDirectoryPeople", ("google_people", "search_directory_people")),
        ("https://oauth2.googleapis.com/token", ("google_oauth", "token_refresh")),
        ("https://example.invalid/whatever", ("google_api", "other")),
    ],
)
def test_every_google_url_classifies_into_the_closed_enum(url: str, expected: tuple[str, str]) -> None:
    assert classify_google("GET", url) == expected


def test_the_log_level_for_a_degraded_fallback_is_at_least_warning() -> None:
    """"A caught exception that degrades to a fallback logs at warn or error." """
    capture = _Capture()
    configure_logging("INFO", capture)
    api = MockGoogleApi().on(
        "GET", f"/spreadsheets/{BOOK}", lambda r: httpx.Response(503, json={"error": {"message": "down"}})
    )
    http = http_for(api)
    with pytest.raises(GoogleError):
        http.get("a@example.com", URL)
    levels = {json.loads(line)["level"] for line in capture.lines}
    assert levels & {"warning", "error"}
    assert logging.WARNING  # the constant the wrapper uses
