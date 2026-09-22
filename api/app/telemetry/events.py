"""The event tokens.

Every structured log line carries one of these as its ``event``: a stable snake_case token, never
interpolated prose, so a runbook can say ``grep '"event":"external_call_failed"'`` and keep saying
it after the message text is reworded.

``EVENTS`` is the closed set. ``deploy/helm/meeting-desk/templates/prometheusrule.yaml`` writes its
remediation annotations in these tokens and ``tests/test_telemetry_alerts.py`` asserts every token
a rule names is in this module *and* emitted somewhere under ``app/``.
"""

from __future__ import annotations

# --- requests -------------------------------------------------------------------------------------
REQUEST_COMPLETED = "request_completed"
REQUEST_FAILED = "request_failed"
UNHANDLED_EXCEPTION = "unhandled_exception"

# --- outbound calls -------------------------------------------------------------------------------
EXTERNAL_CALL_FAILED = "external_call_failed"
EXTERNAL_CALL_REJECTED = "external_call_rejected_by_breaker"
BREAKER_OPENED = "breaker_opened"
BREAKER_HALF_OPEN = "breaker_half_open"
BREAKER_CLOSED = "breaker_closed"

# --- the named dependencies a rule points at ------------------------------------------------------
OAUTH_REFRESH_FAILED = "oauth_refresh_failed"
SHEETS_WRITE_CONFLICT = "sheets_write_conflict"
TRANSFER_CONFLICT = "transfer_conflict"
EXTRACTION_FAILED = "extraction_failed"

# --- background jobs ------------------------------------------------------------------------------
BACKGROUND_JOB_STARTED = "background_job_started"
BACKGROUND_JOB_SUCCEEDED = "background_job_succeeded"
BACKGROUND_JOB_FAILED = "background_job_failed"

# --- process --------------------------------------------------------------------------------------
METRICS_SERVER_STARTED = "metrics_server_started"
METRICS_SERVER_FAILED = "metrics_server_failed"

EVENTS = frozenset(
    {
        REQUEST_COMPLETED,
        REQUEST_FAILED,
        UNHANDLED_EXCEPTION,
        EXTERNAL_CALL_FAILED,
        EXTERNAL_CALL_REJECTED,
        BREAKER_OPENED,
        BREAKER_HALF_OPEN,
        BREAKER_CLOSED,
        OAUTH_REFRESH_FAILED,
        SHEETS_WRITE_CONFLICT,
        TRANSFER_CONFLICT,
        EXTRACTION_FAILED,
        BACKGROUND_JOB_STARTED,
        BACKGROUND_JOB_SUCCEEDED,
        BACKGROUND_JOB_FAILED,
        METRICS_SERVER_STARTED,
        METRICS_SERVER_FAILED,
    }
)


class FailureReason:
    """The closed enum for ``failure_reason``; one value on every failure path.

    A label, not prose: it is safe to put in a metric or an alert and it never carries user content.
    """

    RATE_LIMITED = "rate_limited"
    AUTH_EXPIRED = "auth_expired"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    BREAKER_OPEN = "breaker_open"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DATABASE_ERROR = "database_error"
    CONFLICT = "conflict"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    JOB_FAILED = "job_failed"


FAILURE_REASONS = frozenset(
    value
    for name, value in vars(FailureReason).items()
    if not name.startswith("_") and isinstance(value, str)
)

__all__ = ["EVENTS", "FAILURE_REASONS", "FailureReason"]
