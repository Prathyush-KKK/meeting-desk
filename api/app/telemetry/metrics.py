"""The six required metrics, plus ``app_build_info``.

Names, types, labels and buckets are `docs/TELEMETRY.md` verbatim. They live
on their own ``CollectorRegistry`` rather than the process-global one so that

* ``GET /metrics`` on the metrics port answers exactly these and nothing else (no ``python_gc_*``,
  no ``process_*`` - nothing that would blur the cardinality statement), and
* a test can build an isolated ``Metrics`` and assert on it without the module-level one leaking in.

Cardinality is kept by construction: the label values are closed enums (``app/telemetry/providers.py``)
and route labels are the templated paths from the route table, never a request path.
"""

from __future__ import annotations

import os

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, disable_created_metrics

# The `_created` gauge prometheus_client adds next to every counter is noise docs/TELEMETRY.md does
# not ask for; switching it off keeps /metrics to the names below.
disable_created_metrics()

DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

REQUIRED_METRIC_NAMES = (
    "http_requests_total",
    "http_request_duration_seconds",
    "external_provider_requests_total",
    "external_provider_last_success_timestamp_seconds",
    "external_provider_breaker_state",
    "background_job_total",
)
BUILD_INFO_METRIC = "app_build_info"

STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx")
JOB_OUTCOMES = ("success", "failure")


def status_class(code: int) -> str:
    """``status_class`` is the bucket, never the raw code - that is the cardinality rule."""
    if code < 200:
        return "2xx"
    bucket = f"{code // 100}xx"
    return bucket if bucket in STATUS_CLASSES else "5xx"


class Metrics:
    """One registry, one set of collectors."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()

        self.http_requests = Counter(
            "http_requests_total",
            "HTTP requests served, by templated route, method and status class.",
            ["route", "method", "status_class"],
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "http_request_duration_seconds",
            "Wall time spent serving a request, by templated route and method.",
            ["route", "method"],
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        self.provider_requests = Counter(
            "external_provider_requests_total",
            "Outbound calls to a dependency, by provider, operation and outcome.",
            ["provider", "op", "outcome"],
            registry=self.registry,
        )
        self.provider_last_success = Gauge(
            "external_provider_last_success_timestamp_seconds",
            "Unix time of the last successful call to a provider. Only ever written on success.",
            ["provider"],
            registry=self.registry,
        )
        self.breaker_state = Gauge(
            "external_provider_breaker_state",
            "Circuit breaker: 0 closed, 1 half-open, 2 open.",
            ["provider"],
            registry=self.registry,
        )
        self.job_total = Counter(
            "background_job_total",
            "Background job runs, by job name and outcome.",
            ["job_name", "outcome"],
            registry=self.registry,
        )
        self.job_last_success = Gauge(
            "background_job_last_success_timestamp_seconds",
            "Unix time of the last successful run of a background job.",
            ["job_name"],
            registry=self.registry,
        )
        self.build_info = Gauge(
            "app_build_info",
            "Always 1; the build is in the labels.",
            ["version", "commit"],
            registry=self.registry,
        )

    def set_build_info(self, version: str = "", commit: str = "") -> None:
        self.build_info.labels(
            version=version or os.getenv("APP_VERSION", "0.1.0"),
            commit=commit or os.getenv("GIT_COMMIT", "unknown"),
        ).set(1)

    def names(self) -> set[str]:
        """The exposed metric names. prometheus_client keeps a counter's family name without the
        ``_total`` suffix, so it is put back here: what this returns is what ``/metrics`` prints."""
        out: set[str] = set()
        for metric in self.registry.collect():
            out.add(f"{metric.name}_total" if metric.type == "counter" else metric.name)
        return out


_METRICS: Metrics | None = None


def metrics() -> Metrics:
    """The process-wide set. Built on first use; there is one per process by design."""
    global _METRICS
    if _METRICS is None:
        _METRICS = Metrics()
        _METRICS.set_build_info()
    return _METRICS


def reset_metrics() -> Metrics:
    """Tests only: throw the collectors away and build a fresh set."""
    global _METRICS
    _METRICS = None
    return metrics()
