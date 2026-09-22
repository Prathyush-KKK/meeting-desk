"""The HTTP door: bearer tokens, 401 refresh, 429 backoff, per-connection cooldown, error mapping."""

from __future__ import annotations

import httpx
import pytest

from app.google.http import GoogleApiError, GoogleHttp, parse_error
from app.google.interface import AuthExpired, NotFoundError, PermissionDenied, RateLimited
from app.google.tokens import StaticTokens
from tests.google_mock import MockGoogleApi, json_response

URL = "https://sheets.googleapis.com/v4/spreadsheets/abc"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_every_request_carries_the_connections_bearer_token() -> None:
    api = MockGoogleApi().on("GET", "/spreadsheets/abc", {"ok": True})
    http = api.http(tokens=StaticTokens({"a@simpleo.ai": "token-for-a"}))
    assert http.get("a@simpleo.ai", URL) == {"ok": True}
    assert api.requests[0].headers["Authorization"] == "Bearer token-for-a"
    assert api.requests[0].headers["Accept"] == "application/json"


def test_a_401_refreshes_the_token_once_and_retries() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/spreadsheets/abc",
        [lambda r: json_response("error_401.json", 401), lambda r: json_response({"ok": True})],
    )
    tokens = StaticTokens()
    http = api.http(tokens=tokens)
    assert http.get("a@simpleo.ai", URL) == {"ok": True}
    assert tokens.refreshes == ["a@simpleo.ai"]
    assert len(api.requests) == 2


def test_a_second_401_after_the_refresh_is_auth_expired() -> None:
    api = MockGoogleApi().on("GET", "/spreadsheets/abc", lambda r: json_response("error_401.json", 401))
    http = api.http()
    with pytest.raises(AuthExpired):
        http.get("a@simpleo.ai", URL)
    assert len(api.requests) == 2


def test_429_is_retried_with_exponential_backoff_up_to_five_times() -> None:
    api = MockGoogleApi().on("GET", "/spreadsheets/abc", lambda r: json_response("error_429_quota.json", 429))
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now, max_retries=5, backoff_base=0.5)
    with pytest.raises(RateLimited) as err:
        http.get("a@simpleo.ai", URL)
    assert len(api.requests) == 6  # the call and five retries
    assert clock.slept == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert err.value.retry_after_seconds > 0


def test_403_rate_limit_exceeded_counts_as_a_rate_limit() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/spreadsheets/abc",
        [lambda r: json_response("error_403_rate_limit.json", 403), lambda r: json_response({"ok": True})],
    )
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now)
    assert http.get("a@simpleo.ai", URL) == {"ok": True}
    assert clock.slept == [0.5]


def test_retry_after_header_wins_over_the_backoff_schedule() -> None:
    api = MockGoogleApi().on(
        "GET",
        "/spreadsheets/abc",
        [
            lambda r: json_response("error_429_quota.json", 429, headers={"Retry-After": "3"}),
            lambda r: json_response({"ok": True}),
        ],
    )
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now)
    http.get("a@simpleo.ai", URL)
    assert clock.slept == [3.0]


def test_a_rate_limited_connection_is_backed_off_and_the_next_call_fails_fast() -> None:
    api = MockGoogleApi().on("GET", "/spreadsheets/abc", lambda r: json_response("error_429_quota.json", 429))
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now, max_retries=0, connection_backoff_seconds=60)
    with pytest.raises(RateLimited):
        http.get("a@simpleo.ai", URL)
    assert len(api.requests) == 1
    with pytest.raises(RateLimited) as err:
        http.get("a@simpleo.ai", URL)
    assert len(api.requests) == 1  # no network call while backed off
    assert 0 < err.value.retry_after_seconds <= 60
    # Another connection is not affected.
    api.on("GET", "/spreadsheets/xyz", {"ok": True})
    assert http.get("b@simpleo.ai", "https://sheets.googleapis.com/v4/spreadsheets/xyz") == {"ok": True}
    # The cooldown doubles on a repeat and clears after it elapses.
    clock.t += 61
    with pytest.raises(RateLimited):
        http.get("a@simpleo.ai", URL)
    assert http.backoff_remaining("a@simpleo.ai") > 60


def test_5xx_is_retried_then_surfaced_as_an_api_error() -> None:
    api = MockGoogleApi().on(
        "GET", "/spreadsheets/abc", lambda r: httpx.Response(503, text="Service Unavailable")
    )
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now, max_retries=2)
    with pytest.raises(GoogleApiError) as err:
        http.get("a@simpleo.ai", URL)
    assert err.value.status == 503
    assert len(api.requests) == 3


def test_404_and_403_map_to_the_interface_errors() -> None:
    api = (
        MockGoogleApi()
        .on("GET", "/missing", lambda r: json_response("error_404.json", 404))
        .on("GET", "/forbidden", lambda r: json_response("error_403_forbidden.json", 403))
    )
    http = api.http()
    with pytest.raises(NotFoundError, match="not found"):
        http.get("a@simpleo.ai", "https://www.googleapis.com/drive/v3/files/missing")
    with pytest.raises(PermissionDenied) as err:
        http.get("a@simpleo.ai", "https://www.googleapis.com/drive/v3/files/forbidden")
    assert err.value.detail == "PERMISSION_DENIED"


def test_transport_failures_are_retried_then_reported() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    api = MockGoogleApi().on("GET", "/spreadsheets/abc", boom)
    clock = FakeClock()
    http = api.http(sleep=clock.sleep, now=clock.now, max_retries=1)
    with pytest.raises(Exception, match="connection reset"):
        http.get("a@simpleo.ai", URL)
    assert len(api.requests) == 2


def test_boolean_params_are_lowercase_strings_and_none_is_dropped() -> None:
    api = MockGoogleApi().on("GET", "/spreadsheets/abc", {"ok": True})
    http = api.http()
    http.get("a@simpleo.ai", URL, params={"singleEvents": True, "pageToken": None, "maxResults": 5})
    params = MockGoogleApi.params(api.requests[0])
    assert params == {"singleEvents": ["true"], "maxResults": ["5"]}


def test_parse_error_handles_every_shape() -> None:
    assert parse_error(httpx.Response(500, text="<html>oops</html>"))[0] == "<html>oops</html>"
    assert parse_error(
        httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"})
    ) == (
        "expired",
        "invalid_grant",
        "",
    )
    message, reason, status = parse_error(json_response("error_429_quota.json", 429))
    assert "Quota exceeded" in message
    assert reason == "RATE_LIMIT_EXCEEDED"
    assert status == "RESOURCE_EXHAUSTED"


def test_the_real_http_layer_never_touches_the_network_in_tests() -> None:
    """The conftest socket guard: a real client with no transport fails before any packet leaves."""
    from tests.conftest import NetworkAccessBlocked

    http = GoogleHttp(StaticTokens(), None)
    with pytest.raises(NetworkAccessBlocked):
        http.get("a@simpleo.ai", "http://127.0.0.1:9/never")
