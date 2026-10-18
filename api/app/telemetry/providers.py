"""Every outbound call, wrapped.

One context manager - ``track_provider(provider, op)`` - does all four things that
docs/TELEMETRY.md asks for:

* counts the call on ``external_provider_requests_total{provider, op, outcome}``;
* sets ``external_provider_last_success_timestamp_seconds{provider}`` **only** on success;
* moves ``external_provider_breaker_state{provider}`` and refuses the call while it is open;
* logs ``external_call_failed`` with a ``failure_reason`` from the closed enum.

``provider`` and ``op`` are both closed enums (below), which is what keeps the series count in the
low hundreds - see ``tests/test_telemetry_cardinality.py``, which derives the bound from these
tables rather than asserting a number somebody typed in.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.telemetry import events
from app.telemetry.breaker import BreakerOpen, BreakerRegistry
from app.telemetry.events import FAILURE_REASONS, FailureReason
from app.telemetry.logs import get_logger, log_event
from app.telemetry.metrics import Metrics, metrics

log = get_logger("provider")

# --- the closed enums -------------------------------------------------------------------------------

GOOGLE_CALENDAR = "google_calendar"
GOOGLE_DRIVE = "google_drive"
GOOGLE_DOCS = "google_docs"
GOOGLE_GMAIL = "google_gmail"
GOOGLE_SHEETS = "google_sheets"
GOOGLE_PEOPLE = "google_people"
GOOGLE_OAUTH = "google_oauth"
GOOGLE_API = "google_api"  # the catch-all, so an unmapped URL can never invent a label
VERTEX = "vertex"
BEDROCK = "bedrock"
OPENAI = "openai"  # any OpenAI-compatible endpoint: OpenAI, Ollama, OpenRouter, ...
ANTHROPIC = "anthropic"
POSTGRES = "postgres"

#: Operations per provider. ``other`` is always allowed, so the table is total.
OPS: dict[str, tuple[str, ...]] = {
    GOOGLE_CALENDAR: ("events_list", "events_get"),
    GOOGLE_DRIVE: ("files_list", "files_get"),
    GOOGLE_DOCS: ("documents_get",),
    GOOGLE_GMAIL: ("messages_list", "messages_get"),
    GOOGLE_SHEETS: ("spreadsheets_get", "values_batch_get", "batch_update"),
    GOOGLE_PEOPLE: ("search_directory_people",),
    GOOGLE_OAUTH: ("token_refresh", "token_exchange", "userinfo"),
    GOOGLE_API: (),
    VERTEX: ("generate_content",),
    BEDROCK: ("converse", "chat_completions"),  # the Converse API; the OpenAI-compatible endpoint
    OPENAI: ("chat_completions",),
    ANTHROPIC: ("messages_create",),
    POSTGRES: ("query",),
}
OTHER_OP = "other"

PROVIDERS: tuple[str, ...] = tuple(OPS)

#: Postgres has no breaker (see app/telemetry/breaker.py); its gauge stays a constant 0.
BREAKER_PROVIDERS: frozenset[str] = frozenset(PROVIDERS) - {POSTGRES}

OUTCOMES = ("success", "error", "timeout", "rejected_by_breaker")


def ops_for(provider: str) -> tuple[str, ...]:
    return (*OPS.get(provider, ()), OTHER_OP)


# --- classifying a Google URL -------------------------------------------------------------------------


def classify_google(method: str, url: str) -> tuple[str, str]:
    """(provider, op) for one Google REST URL. Total: anything unknown lands on ``google_api``."""
    path = url.split("?", 1)[0]
    if "docs.googleapis.com" in path:
        return GOOGLE_DOCS, "documents_get"
    if "gmail.googleapis.com" in path:
        return GOOGLE_GMAIL, "messages_get" if "/messages/" in path else "messages_list"
    if "people.googleapis.com" in path:
        return GOOGLE_PEOPLE, "search_directory_people"
    if "sheets.googleapis.com" in path:
        if path.endswith(":batchUpdate"):
            return GOOGLE_SHEETS, "batch_update"
        if "values:batchGet" in path or "/values" in path:
            return GOOGLE_SHEETS, "values_batch_get"
        return GOOGLE_SHEETS, "spreadsheets_get"
    if "/calendar/v3" in path:
        return GOOGLE_CALENDAR, "events_get" if "/events/" in path else "events_list"
    if "/drive/v3" in path:
        return GOOGLE_DRIVE, "files_get" if "/files/" in path else "files_list"
    if "oauth2.googleapis.com/token" in path:
        return GOOGLE_OAUTH, "token_refresh"
    if "openidconnect.googleapis.com" in path:
        return GOOGLE_OAUTH, "userinfo"
    return GOOGLE_API, OTHER_OP


# --- failure classification ----------------------------------------------------------------------------

#: Exception names that are an *answer*, not an outage: counted as errors, never breaker failures.
_ANSWER_NOT_OUTAGE = {
    "NotFoundError": FailureReason.NOT_FOUND,
    "PermissionDenied": FailureReason.PERMISSION_DENIED,
    "AuthExpired": FailureReason.AUTH_EXPIRED,
    "InvalidModelOutput": FailureReason.INVALID_MODEL_OUTPUT,
}
_TIMEOUTS = {"TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}
#: SQLAlchemy's hierarchy. Postgres has no breaker, so none of these can move one.
_DATABASE_ERRORS = {
    "DBAPIError",
    "DatabaseError",
    "IntegrityError",
    "InterfaceError",
    "InternalError",
    "InvalidRequestError",
    "OperationalError",
    "ProgrammingError",
    "StatementError",
}


def classify_failure(exc: BaseException) -> tuple[str, str, bool]:
    """(outcome, failure_reason, counts_against_the_breaker)."""
    name = type(exc).__name__
    if isinstance(exc, BreakerOpen):
        return "rejected_by_breaker", FailureReason.BREAKER_OPEN, False
    # An exception may say what it is: ``failure_reason`` from the closed enum, and
    # ``counts_against_breaker`` - False for an answer (a 4xx from an LLM endpoint), not an outage.
    # See ``EndpointRefusal`` in app/extract/openai_compat.py.
    declared = getattr(exc, "failure_reason", None)
    if isinstance(declared, str) and declared in FAILURE_REASONS:
        return "error", declared, bool(getattr(exc, "counts_against_breaker", True))
    if name in _TIMEOUTS:
        return "timeout", FailureReason.TIMEOUT, True
    if name in _ANSWER_NOT_OUTAGE:
        return "error", _ANSWER_NOT_OUTAGE[name], False
    if name in _DATABASE_ERRORS:
        return "error", FailureReason.DATABASE_ERROR, False
    if name == "RateLimited":
        # Google is up and saying "slower". Visible as an error, but tripping the breaker on top of
        # the per-connection cooldown would only take the other connections down with it.
        return "error", FailureReason.RATE_LIMITED, False
    return "error", FailureReason.UPSTREAM_ERROR, True


# --- the registry the app shares ------------------------------------------------------------------------


class ProviderTelemetry:
    """The metrics and the breakers, wired to each other."""

    def __init__(self, metric_set: Metrics | None = None, now: Callable[[], float] = time.monotonic) -> None:
        self.metrics = metric_set if metric_set is not None else metrics()
        self.breakers = BreakerRegistry(
            tuple(sorted(BREAKER_PROVIDERS)), on_change=self._publish_state, now=now
        )
        self.initialise()

    def initialise(self) -> None:
        """Every breaker gauge starts at 0 - including Postgres, which never moves off it."""
        for provider in PROVIDERS:
            self.metrics.breaker_state.labels(provider=provider).set(0)

    def _publish_state(self, provider: str, state: str) -> None:
        from app.telemetry.breaker import STATE_VALUE

        self.metrics.breaker_state.labels(provider=provider).set(STATE_VALUE[state])

    # --- recording ---------------------------------------------------------------------------------
    def record_success(self, provider: str, op: str, wall_time: float | None = None) -> None:
        self.metrics.provider_requests.labels(provider=provider, op=op, outcome="success").inc()
        self.metrics.provider_last_success.labels(provider=provider).set(
            wall_time if wall_time is not None else time.time()
        )
        breaker = self.breakers.get(provider)
        if breaker is not None:
            breaker.record_success()

    def record_failure(self, provider: str, op: str, exc: BaseException) -> tuple[str, str]:
        outcome, reason, counts = classify_failure(exc)
        self.metrics.provider_requests.labels(provider=provider, op=op, outcome=outcome).inc()
        breaker = self.breakers.get(provider)
        if breaker is not None and counts:
            breaker.record_failure()
        return outcome, reason

    @contextmanager
    def track(self, provider: str, op: str) -> Iterator[None]:
        breaker = self.breakers.get(provider)
        if breaker is not None and not breaker.allow():
            rejected = BreakerOpen(provider, breaker.retry_after())
            self.metrics.provider_requests.labels(
                provider=provider, op=op, outcome="rejected_by_breaker"
            ).inc()
            log_event(
                log,
                events.EXTERNAL_CALL_REJECTED,
                level=logging.WARNING,
                provider=provider,
                op=op,
                outcome="rejected_by_breaker",
                failure_reason=FailureReason.BREAKER_OPEN,
            )
            raise rejected
        started = time.perf_counter()
        try:
            yield
        except BaseException as exc:
            outcome, reason = self.record_failure(provider, op, exc)
            log_event(
                log,
                events.EXTERNAL_CALL_FAILED,
                level=logging.WARNING,
                provider=provider,
                op=op,
                outcome=outcome,
                failure_reason=reason,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        else:
            self.record_success(provider, op)


_TELEMETRY: ProviderTelemetry | None = None


def provider_telemetry() -> ProviderTelemetry:
    global _TELEMETRY
    if _TELEMETRY is None:
        _TELEMETRY = ProviderTelemetry()
    return _TELEMETRY


def reset_provider_telemetry(metric_set: Metrics | None = None) -> ProviderTelemetry:
    """Tests only: fresh counters and fresh breakers."""
    global _TELEMETRY
    _TELEMETRY = ProviderTelemetry(metric_set)
    return _TELEMETRY


@contextmanager
def track_provider(provider: str, op: str) -> Iterator[None]:
    """The one wrapper every outbound call goes through."""
    with provider_telemetry().track(provider, op):
        yield


def record_job(job_name: str, outcome: str, duration_ms: float | None = None) -> None:
    """``background_job_total`` plus the last-success gauge. The label is ``job_name``, never ``job``."""
    telemetry = provider_telemetry()
    telemetry.metrics.job_total.labels(job_name=job_name, outcome=outcome).inc()
    if outcome == "success":
        telemetry.metrics.job_last_success.labels(job_name=job_name).set(time.time())


@contextmanager
def track_job(job_name: str) -> Iterator[None]:
    started = time.perf_counter()
    log_event(log, events.BACKGROUND_JOB_STARTED, job_name=job_name)
    try:
        yield
    except BaseException as exc:
        duration = (time.perf_counter() - started) * 1000
        record_job(job_name, "failure", duration)
        _, reason, _ = classify_failure(exc)
        log_event(
            log,
            events.BACKGROUND_JOB_FAILED,
            level=logging.ERROR,
            job_name=job_name,
            failure_reason=reason or FailureReason.JOB_FAILED,
            duration_ms=duration,
        )
        raise
    else:
        duration = (time.perf_counter() - started) * 1000
        record_job(job_name, "success", duration)
        log_event(log, events.BACKGROUND_JOB_SUCCEEDED, job_name=job_name, duration_ms=duration)


__all__ = [
    "ANTHROPIC",
    "BEDROCK",
    "BREAKER_PROVIDERS",
    "GOOGLE_API",
    "GOOGLE_CALENDAR",
    "GOOGLE_DOCS",
    "GOOGLE_DRIVE",
    "GOOGLE_GMAIL",
    "GOOGLE_OAUTH",
    "GOOGLE_PEOPLE",
    "GOOGLE_SHEETS",
    "OPENAI",
    "OPS",
    "OTHER_OP",
    "OUTCOMES",
    "POSTGRES",
    "PROVIDERS",
    "VERTEX",
    "ProviderTelemetry",
    "classify_failure",
    "classify_google",
    "ops_for",
    "provider_telemetry",
    "record_job",
    "reset_provider_telemetry",
    "track_job",
    "track_provider",
]
