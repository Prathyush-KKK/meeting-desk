"""NOTIFY_WEBHOOK_URL: one chat message per transfer, sent after the response, never in its way."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import notify
from app.main import create_app
from app.telemetry.metrics import metrics
from app.telemetry.providers import WEBHOOK
from tests.conftest import make_settings, meeting_by_title, workbook_by_name

HOOK = "https://hooks.slack.com/services/T000/B000/XXXX"


def _transfer(client: TestClient, n: int = 2) -> httpx.Response:
    workbook = workbook_by_name(client, "Mobile App Product Roadmap")
    meeting_id = meeting_by_title(client, "Mobile roadmap review")["id"]
    point_ids = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()[:n]]
    tab = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    return client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": tab["region_hash"],
        },
    )


def _app(tmp_path: Path, answer: int = 200, **overrides):
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(answer, text="ok")

    app = create_app(make_settings(tmp_path, **overrides))
    app.state.notify_transport = httpx.MockTransport(handler)
    return app, sent


def test_a_transfer_posts_who_sent_what_where(tmp_path: Path) -> None:
    app, sent = _app(tmp_path, notify_webhook_url=HOOK)
    with TestClient(app) as client:
        response = _transfer(client)
    assert response.status_code == 200, response.text
    (request,) = sent
    assert str(request.url) == HOOK
    text = json.loads(request.content)["text"]
    lines = text.split("\n")
    assert lines[0] == "Daniel Okafor sent 2 points from Mobile roadmap review to Mobile App Product Roadmap > P1 Resolve & Log"
    assert lines[1] == "• Review dataset for currency information - Anna Moreno, 26 Sep"
    assert lines[-1].startswith("https://docs.google.com/spreadsheets/d/")


def test_no_url_no_message(tmp_path: Path) -> None:
    app, sent = _app(tmp_path)
    with TestClient(app) as client:
        assert _transfer(client).status_code == 200
    assert sent == []


def test_a_refusing_webhook_never_fails_the_transfer(tmp_path: Path) -> None:
    app, sent = _app(tmp_path, answer=500, notify_webhook_url=HOOK)
    with TestClient(app) as client:
        assert _transfer(client).status_code == 200
    assert len(sent) == 1
    errors = metrics().registry.get_sample_value(
        "external_provider_requests_total", {"provider": WEBHOOK, "op": "post", "outcome": "error"}
    )
    assert errors == 1.0


def test_a_long_transfer_is_cut_to_ten_lines() -> None:
    points = [{"text": f"point {i}", "owner": "", "due": ""} for i in range(13)]
    text = notify.transfer_message(
        actor="a", workbook_name="W", sheet_title="T", sheet_url="", meeting_titles=[], points=points
    )
    lines = text.split("\n")
    assert lines[0] == "a sent 13 points to W > T"
    assert lines[-1] == "…and 3 more"
    assert len(lines) == 12
