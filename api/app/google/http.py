"""One HTTP door for every Google client.

Plain ``httpx`` against the REST endpoints rather than ``googleapiclient``: no discovery document
to fetch, one dependency that is already here, and ``httpx.MockTransport`` lets the contract tests
assert the exact request (query, fields mask, JSON body) against hand-written responses.

What every request gets:

* a bearer token for the connection it runs as, refreshed once on a 401;
* retries on 429 and 403 ``rateLimitExceeded`` with exponential backoff (``max_retries``, five by
  default; a ``Retry-After`` is honoured but capped at ``MAX_RETRY_AFTER_SECONDS`` and jittered),
  after which that (connection, Google API) pair is backed off for ``connection_backoff_seconds``
  and every call on it fails fast with ``RateLimited`` - the same connection's other APIs, and the
  other connections, carry on, because Google's quotas are per API;
* Google's error JSON turned into ``NotFoundError`` / ``PermissionDenied`` / ``GoogleError``;
* telemetry: one ``external_provider_requests_total`` count per logical call (the retries inside it
  are not separate calls), the last-success gauge on success only, and a circuit breaker per Google
  API that opens after five consecutive dependency failures - see ``app/telemetry/providers.py``.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.google.interface import AuthExpired, GoogleError, NotFoundError, PermissionDenied, RateLimited
from app.telemetry.breaker import BreakerOpen
from app.telemetry.providers import classify_google, track_provider

RATE_LIMIT_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "quotaExceeded",
    "dailyLimitExceeded",
    "RESOURCE_EXHAUSTED",
}
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Google answers a quota refusal with a Retry-After that can be minutes. Honouring it inside the
# request would hold a worker (and the person's browser) open for that long, so the wait is capped
# and the rest of the cooldown is served by the per-(connection, provider) backoff below.
MAX_RETRY_AFTER_SECONDS = 8.0


class AccessTokens(Protocol):
    def access_token(self, connection_email: str, force_refresh: bool = False) -> str: ...

    def forget(self, connection_email: str) -> None: ...


class GoogleApiError(GoogleError):
    """A non-mapped 4xx/5xx with the status and Google's message."""

    def __init__(self, status: int, message: str, reason: str = "") -> None:
        super().__init__(f"{status} {message}".strip())
        self.status = status
        self.reason = reason


def parse_error(response: httpx.Response) -> tuple[str, str, str]:
    """(message, reason, status_text) from Google's error envelope; tolerant of anything else."""
    try:
        body = response.json()
    except ValueError:
        return (response.text[:200] or f"HTTP {response.status_code}", "", "")
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or f"HTTP {response.status_code}")
        reason = ""
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            reason = str(errors[0].get("reason") or "")
        for detail in error.get("details") or []:
            if isinstance(detail, dict) and detail.get("reason") and not reason:
                reason = str(detail["reason"])
        return message, reason, str(error.get("status") or "")
    if isinstance(error, str):
        return str(body.get("error_description") or error), error, ""
    return (f"HTTP {response.status_code}", "", "")


class GoogleHttp:
    def __init__(
        self,
        tokens: AccessTokens,
        transport: httpx.BaseTransport | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        connection_backoff_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.tokens = tokens
        self.client = httpx.Client(transport=transport, timeout=timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.connection_backoff_seconds = connection_backoff_seconds
        self._sleep = sleep
        self._now = now
        self._jitter = jitter or (lambda: random.uniform(0.0, 0.5))
        self._backoff_until: dict[tuple[str, str], float] = {}
        self._backoff_hits: dict[tuple[str, str], int] = {}
        self.requests: list[httpx.Request] = []  # the last few, for diagnostics and tests

    # --- backoff state -------------------------------------------------------------------------
    # Quota is per API, not per account: Calendar's 429 says nothing about Sheets' quota, and
    # blocking the whole connection on one would stop a transfer because the meeting list was
    # busy. The key is therefore (connection, provider).
    def backoff_remaining(self, connection_email: str, provider: str = "") -> float:
        keys = [
            k
            for k in self._backoff_until
            if k[0] == connection_email and (not provider or k[1] == provider)
        ]
        return max((max(0.0, self._backoff_until[k] - self._now()) for k in keys), default=0.0)

    def forget(self, connection_email: str) -> None:
        for store in (self._backoff_until, self._backoff_hits):
            for key in [k for k in store if k[0] == connection_email]:
                del store[key]
        self.tokens.forget(connection_email)

    def _back_off(self, connection_email: str, provider: str) -> float:
        key = (connection_email, provider)
        hits = self._backoff_hits.get(key, 0) + 1
        self._backoff_hits[key] = hits
        # Doubles per consecutive limit, capped at ten minutes.
        seconds = min(self.connection_backoff_seconds * (2 ** (hits - 1)), 600.0)
        self._backoff_until[key] = self._now() + seconds
        return seconds

    # --- requests ------------------------------------------------------------------------------
    def get(self, connection_email: str, url: str, params: dict[str, Any] | None = None, **kw: Any) -> Any:
        return self.request(connection_email, "GET", url, params=params, **kw)

    def post(
        self,
        connection_email: str,
        url: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
        **kw: Any,
    ) -> Any:
        return self.request(connection_email, "POST", url, json=json, params=params, **kw)

    def request(
        self,
        connection_email: str,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retries: int | None = None,
    ) -> Any:
        """One logical outbound call, whatever the retries inside it.

        The telemetry wrapper sits here rather than around each client so that every Google call is
        covered by construction, and so a 429 retried four times is one call, not five.
        """
        provider, op = classify_google(method, url)
        try:
            with track_provider(provider, op):
                return self._send(
                    connection_email,
                    method,
                    url,
                    params=params,
                    json=json,
                    retries=retries,
                    provider=provider,
                )
        except BreakerOpen as exc:
            raise GoogleError(str(exc)) from exc

    def _send(
        self,
        connection_email: str,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retries: int | None = None,
        provider: str = "",
    ) -> Any:
        remaining = self.backoff_remaining(connection_email, provider)
        if remaining > 0:
            raise RateLimited(
                f"{connection_email} is rate-limited by Google on {provider or 'this API'}; "
                f"retrying in {int(remaining) + 1} s",
                retry_after_seconds=remaining,
            )
        budget = self.max_retries if retries is None else retries
        refreshed = False
        attempt = 0
        while True:
            token = self.tokens.access_token(connection_email)
            request = self.client.build_request(
                method,
                url,
                params=_clean_params(params),
                json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            self._remember(request)
            try:
                response = self.client.send(request)
            except httpx.HTTPError as exc:
                if attempt < budget:
                    self._sleep(self.backoff_base * (2**attempt))
                    attempt += 1
                    continue
                raise GoogleError(f"{method} {url} failed: {exc}") from exc

            if response.status_code < 400:
                self._backoff_hits.pop((connection_email, provider), None)
                if not response.content:
                    return {}
                try:
                    return response.json()
                except ValueError:
                    return {}

            message, reason, status_text = parse_error(response)

            if response.status_code == 401:
                if not refreshed:
                    refreshed = True
                    self.tokens.access_token(connection_email, force_refresh=True)
                    continue
                raise AuthExpired(f"{connection_email}: {message}")

            rate_limited = response.status_code == 429 or (
                response.status_code == 403
                and (reason in RATE_LIMIT_REASONS or status_text == "RESOURCE_EXHAUSTED")
            )
            if rate_limited or response.status_code in RETRY_STATUSES:
                if attempt < budget:
                    wait = _retry_after(response)
                    wait = self.backoff_base * (2**attempt) if wait is None else wait
                    self._sleep(min(wait, MAX_RETRY_AFTER_SECONDS) + self._jitter())
                    attempt += 1
                    continue
                if rate_limited:
                    seconds = self._back_off(connection_email, provider)
                    raise RateLimited(
                        f"{connection_email}: {message} (backing off {int(seconds)} s)",
                        retry_after_seconds=seconds,
                    )
                raise GoogleApiError(response.status_code, message, reason)

            if response.status_code == 404:
                raise NotFoundError(message)
            if response.status_code == 403:
                raise PermissionDenied(message, detail=reason or status_text or message)
            raise GoogleApiError(response.status_code, message, reason)

    def _remember(self, request: httpx.Request) -> None:
        self.requests.append(request)
        if len(self.requests) > 50:
            del self.requests[:-50]

    def close(self) -> None:
        self.client.close()


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        out[key] = "true" if value is True else "false" if value is False else value
    return out


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None
