"""The metrics endpoint, the six required names, and the structured log line.

The metrics app is exercised through an ASGI client rather than a real port: the socket guard in
conftest forbids listening sockets, and what matters here is the app, not uvicorn.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from app.telemetry import events
from app.telemetry.logs import JsonFormatter, configure_logging, log_event, set_request_id
from app.telemetry.metrics import BUILD_INFO_METRIC, DURATION_BUCKETS, REQUIRED_METRIC_NAMES, metrics
from app.telemetry.middleware import REQUEST_ID_HEADER
from app.telemetry.providers import provider_telemetry
from app.telemetry.server import make_metrics_app
from tests.conftest import make_settings


def metrics_client() -> TestClient:
    return TestClient(make_metrics_app())


def declared(body: str) -> set[str]:
    """The metric names /metrics declares, from its ``# TYPE`` lines.

    A counter with no label combination observed yet has no sample line, only the declaration -
    which is exactly the state a pod is in the moment it starts. So "the six exist" is a question
    about the declarations, and the sample lines are asserted separately once traffic has run.
    """
    names: set[str] = set()
    for line in body.splitlines():
        if line.startswith("# TYPE "):
            names.add(line.split(" ")[2])
    return names


def test_the_metrics_app_serves_the_six_required_names_and_app_build_info() -> None:
    body = metrics_client().get("/metrics").text
    exposed = declared(body)
    for name in (*REQUIRED_METRIC_NAMES, BUILD_INFO_METRIC):
        assert name in exposed, f"{name} is not on /metrics"
    assert f'{BUILD_INFO_METRIC}{{commit="' in body


def test_the_six_carry_samples_once_the_app_has_done_some_work(client: TestClient) -> None:
    from tests.conftest import saved_meeting_id

    meeting_id = saved_meeting_id(client, "Mobile roadmap review")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: send the deck by Friday"})
    client.post(f"/meetings/{meeting_id}/extract")
    body = metrics_client().get("/metrics").text
    lines = [line for line in body.splitlines() if not line.startswith("#")]
    for name in (
        "http_requests_total",
        "http_request_duration_seconds_bucket",
        "external_provider_requests_total",
        "external_provider_last_success_timestamp_seconds",
        "external_provider_breaker_state",
        "background_job_total",
        "background_job_last_success_timestamp_seconds",
        "app_build_info",
    ):
        assert any(line.startswith(name) for line in lines), f"{name} has no series"


def test_the_registry_holds_nothing_but_those_metrics() -> None:
    """No python_gc_*, no process_*: the cardinality statement covers the whole endpoint."""
    assert metrics().names() == {
        *REQUIRED_METRIC_NAMES,
        "background_job_last_success_timestamp_seconds",
        BUILD_INFO_METRIC,
    }


def test_the_histogram_buckets_are_the_ones_the_standard_names() -> None:
    assert DURATION_BUCKETS == (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    body = metrics_client().get("/metrics").text
    metrics().http_duration.labels(route="/health", method="GET").observe(0.3)
    body = metrics_client().get("/metrics").text
    seen = [
        line.split('le="')[1].split('"')[0]
        for line in body.splitlines()
        if line.startswith("http_request_duration_seconds_bucket")
    ]
    assert seen == ["0.05", "0.1", "0.25", "0.5", "1.0", "2.5", "5.0", "10.0", "+Inf"]


def test_the_metrics_app_answers_nothing_else() -> None:
    client = metrics_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 404
    assert client.get("/meetings/list").status_code == 404
    assert client.post("/metrics").status_code == 405


def test_metrics_is_not_a_route_on_the_api(client: TestClient) -> None:
    """docs/TELEMETRY.md: a separate container port, never mounted on the app router."""
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert "/metrics" not in paths
    answer = client.get("/metrics")
    assert answer.status_code == 404
    assert "http_requests_total" not in answer.text


def test_metrics_is_still_not_served_on_the_api_port_with_the_spa_mounted(tmp_path: Path) -> None:
    """With ``WEB_DIST`` set, "/" is the SPA and every unknown path falls back to index.html - so
    ``GET /metrics`` on the app port answers the app, not the exposition format. That is what the
    README's "verify /metrics is not public" curl greps for."""
    from app.main import create_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body><div id=root></div></body></html>")
    app = create_app(make_settings(tmp_path, web_dist=str(dist)))
    with TestClient(app) as spa:
        answer = spa.get("/metrics")
        assert "# TYPE http_requests_total" not in answer.text
        assert "<div id=root>" in answer.text


def test_a_request_is_counted_with_a_templated_route_and_a_status_class(client: TestClient) -> None:
    before = _counter("/health", "GET", "2xx")
    response = client.get("/health")
    assert response.status_code == 200
    assert _counter("/health", "GET", "2xx") == before + 1
    assert response.headers[REQUEST_ID_HEADER]


def test_an_unknown_path_lands_in_one_bucket(client: TestClient) -> None:
    for path in ("/nope/1", "/nope/2", "/nope/3"):
        client.get(path)
    assert _counter("__unmatched__", "GET", "4xx") == 3


def test_the_request_id_header_is_echoed_when_it_is_sane(client: TestClient) -> None:
    given = client.get("/health", headers={REQUEST_ID_HEADER: "abc-123"})
    assert given.headers[REQUEST_ID_HEADER] == "abc-123"
    # A hostile one is replaced rather than logged.
    hostile = client.get("/health", headers={REQUEST_ID_HEADER: 'x" injected "'})
    assert hostile.headers[REQUEST_ID_HEADER] != 'x" injected "'


def test_the_database_is_covered_like_any_other_provider(client: TestClient) -> None:
    client.get("/meetings/list")
    samples = _provider_samples()
    assert samples[("postgres", "query", "success")] > 0
    # The breaker for postgres is a constant 0 and is never written again.
    assert _gauge("external_provider_breaker_state", {"provider": "postgres"}) == 0


def test_every_breaker_gauge_starts_at_zero(client: TestClient) -> None:
    from app.telemetry.providers import PROVIDERS

    for provider in PROVIDERS:
        assert _gauge("external_provider_breaker_state", {"provider": provider}) == 0


def test_last_success_is_absent_until_something_succeeds() -> None:
    provider_telemetry()  # fresh per test through the conftest fixture
    assert _gauge("external_provider_last_success_timestamp_seconds", {"provider": "vertex"}) is None


def test_a_background_job_records_its_name_and_outcome(client: TestClient) -> None:
    from tests.conftest import saved_meeting_id

    meeting_id = saved_meeting_id(client, "Mobile roadmap review")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: send the deck by Friday"})
    client.post(f"/meetings/{meeting_id}/extract")
    assert _job_counter("extract", "success") >= 1
    assert _gauge("background_job_last_success_timestamp_seconds", {"job_name": "extract"}) > 0


def test_the_job_label_is_job_name_not_job() -> None:
    assert metrics().job_total._labelnames == ("job_name", "outcome")
    assert metrics().job_last_success._labelnames == ("job_name",)


# --- the log line ---------------------------------------------------------------------------------


def test_a_log_line_is_one_json_object_with_the_required_fields() -> None:
    record = logging.LogRecord(
        "meeting_desk.test", logging.WARNING, __file__, 1, "external_call_failed", (), None
    )
    record.request_id = "rid-1"
    record.route = "/meetings/{meeting_id}/extract"
    record.duration_ms = 12.5
    record.failure_reason = "upstream_error"
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "warning"
    assert line["service"] == "meeting_desk"
    assert line["event"] == "external_call_failed"
    assert line["request_id"] == "rid-1"
    assert line["route"] == "/meetings/{meeting_id}/extract"
    assert line["duration_ms"] == 12.5
    assert line["failure_reason"] == "upstream_error"


def test_secrets_tokens_and_user_content_never_reach_a_log_line(tmp_path: Path) -> None:
    stream = _Capture()
    logger = configure_logging("INFO", stream)
    token = set_request_id("rid-2")
    try:
        log_event(
            logger,
            events.EXTERNAL_CALL_FAILED,
            provider="google_sheets",
            failure_reason="upstream_error",
            authorization="Bearer ya29.secret",
            refresh_token="1//rt-secret",
            text="the whole meeting transcript",
            email="someone@example.com",
            body={"points": ["..."]},
        )
    finally:
        from app.telemetry.logs import reset_request_id

        reset_request_id(token)
    line = json.loads(stream.lines[-1])
    assert line["provider"] == "google_sheets"
    assert line["request_id"] == "rid-2"
    for leak in ("ya29.secret", "1//rt-secret", "transcript", "someone@example.com", "points"):
        assert leak not in json.dumps(line)


def test_the_event_token_is_never_interpolated_prose() -> None:
    """Every token in the registry is a snake_case word, safe to grep for."""
    for token in events.EVENTS:
        assert token == token.lower()
        assert " " not in token and token.replace("_", "").isalnum()


def test_settings_keep_the_metrics_port_off_the_api_port(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert settings.metrics_port == 9464
    assert settings.metrics_enabled is False  # tests only; the default is True


# --- reading the registry -------------------------------------------------------------------------


class _Capture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> int:
        stripped = text.strip()
        if stripped:
            self.lines.append(stripped)
        return len(text)

    def flush(self) -> None:
        return None


def _sample(name: str, labels: dict[str, str]) -> float | None:
    for family in metrics().registry.collect():
        for sample in family.samples:
            if sample.name == name and all(sample.labels.get(k) == v for k, v in labels.items()):
                return sample.value
    return None


def _gauge(name: str, labels: dict[str, str]) -> float | None:
    return _sample(name, labels)


def _counter(route: str, method: str, status_class: str) -> float:
    value = _sample("http_requests_total", {"route": route, "method": method, "status_class": status_class})
    return value or 0.0


def _job_counter(job_name: str, outcome: str) -> float:
    return _sample("background_job_total", {"job_name": job_name, "outcome": outcome}) or 0.0


def _provider_samples() -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for family in metrics().registry.collect():
        for sample in family.samples:
            if sample.name == "external_provider_requests_total":
                key = (sample.labels["provider"], sample.labels["op"], sample.labels["outcome"])
                out[key] = sample.value
    return out


def test_healthz_and_livez_are_what_the_probes_call(client: TestClient) -> None:
    """Readiness touches the database; liveness does not, so a slow RDS cannot get pods killed."""
    ready = client.get("/healthz")
    assert ready.status_code == 200
    assert ready.json() == {"ok": True, "service": "meeting-desk"}
    assert client.get("/livez").status_code == 200
    # The readiness check is a real query, so it is counted like any other Postgres call.
    assert _sample("external_provider_requests_total", {"provider": "postgres", "outcome": "success"})


def test_every_line_of_a_request_carries_its_route_not_only_the_last(client: TestClient) -> None:
    """docs/TELEMETRY.md wants ``route`` on every line of the request.

    The middleware works the route out from the route table *before* the handler runs, so a line
    the handler itself writes - here the extraction job's - already has the templated path.
    """
    from tests.conftest import saved_meeting_id

    meeting_id = saved_meeting_id(client, "Mobile roadmap review")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: send the deck by Friday"})

    stream = _Capture()
    configure_logging("INFO", stream)
    client.post(f"/meetings/{meeting_id}/extract")

    lines = [json.loads(line) for line in stream.lines]
    started = next(line for line in lines if line["event"] == events.BACKGROUND_JOB_STARTED)
    assert started["route"] == "/meetings/{meeting_id}/extract"
    assert started["request_id"]
    # …and it is the same request id the final line carries.
    completed = next(line for line in lines if line["event"] == events.REQUEST_COMPLETED)
    assert completed["request_id"] == started["request_id"]
    assert completed["route"] == started["route"]
