"""Telemetry per ``docs/TELEMETRY.md``.

metrics.py     the six required metrics plus app_build_info, on their own registry
providers.py   track_provider(): the wrapper every outbound call goes through
breaker.py     the circuit breakers behind that wrapper
middleware.py  request id, http_requests_total, http_request_duration_seconds
server.py      GET /metrics on its own port, never on the app router
logs.py        the JSON log line
events.py      the event tokens the runbook and the alert rules quote
"""

from __future__ import annotations

from app.telemetry.breaker import Breaker, BreakerOpen, BreakerRegistry
from app.telemetry.events import EVENTS, FailureReason
from app.telemetry.logs import configure_logging, get_logger, log_event
from app.telemetry.metrics import (
    BUILD_INFO_METRIC,
    DURATION_BUCKETS,
    REQUIRED_METRIC_NAMES,
    Metrics,
    metrics,
    reset_metrics,
)
from app.telemetry.middleware import TelemetryMiddleware
from app.telemetry.providers import (
    PROVIDERS,
    classify_google,
    provider_telemetry,
    record_job,
    reset_provider_telemetry,
    track_job,
    track_provider,
)
from app.telemetry.server import MetricsServer, make_metrics_app

__all__ = [
    "BUILD_INFO_METRIC",
    "DURATION_BUCKETS",
    "EVENTS",
    "PROVIDERS",
    "REQUIRED_METRIC_NAMES",
    "Breaker",
    "BreakerOpen",
    "BreakerRegistry",
    "FailureReason",
    "Metrics",
    "MetricsServer",
    "TelemetryMiddleware",
    "classify_google",
    "configure_logging",
    "get_logger",
    "log_event",
    "make_metrics_app",
    "metrics",
    "provider_telemetry",
    "record_job",
    "reset_metrics",
    "reset_provider_telemetry",
    "track_job",
    "track_provider",
]
