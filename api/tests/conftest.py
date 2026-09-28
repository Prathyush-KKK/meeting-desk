"""Test harness: one app, one SQLite file, the fakes, and AUTH_DEV_USER.

Nothing here touches the network, and the socket guard below makes sure of it: any test that
opens an internet socket fails. Each test gets a fresh database seeded from ``app/seed_data.py``
(the prototype's store), the in-memory Google, and the rule-based extraction provider. The real
Google clients are tested against ``httpx.MockTransport`` with the fixtures under
``tests/fixtures/google/``.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import seed_data
from app.config import Settings
from app.google.fake import FakeGoogle
from app.main import create_app

ADMIN = "prathyush.kodhanpur@simpleo.ai"
MEMBER = "nishchay.s@simpleo.ai"
OUTSIDER = "someone.else@simpleo.ai"

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --- the socket guard ------------------------------------------------------------------------------


class NetworkAccessBlocked(RuntimeError):
    pass


_INTERNET_FAMILIES = {socket.AF_INET, socket.AF_INET6, -1}  # -1: the default, which is AF_INET
_real_socket_init = socket.socket.__init__


def _guarded_socket_init(self, family=-1, type=-1, proto=-1, fileno=None):
    # A socket built from an existing fd (asyncio's self-pipe, socketpair) is not a network call.
    if fileno is None and family in _INTERNET_FAMILIES:
        raise NetworkAccessBlocked(
            "This test tried to open a network socket. Tests run with FAKE_GOOGLE / FAKE_LLM or "
            "httpx.MockTransport; nothing may reach the network."
        )
    _real_socket_init(self, family, type, proto, fileno)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "__init__", _guarded_socket_init)


# The nutrition service's Bedrock names. A developer shell that exports them (for that service)
# would otherwise switch ``EXTRACTION_PROVIDER=bedrock`` to the OpenAI-compatible endpoint, or swap
# the model, in every test that builds ``Settings`` - so no test sees them unless it sets them.
BEDROCK_ENV = (
    "AWS_BEARER_TOKEN_BEDROCK",
    "BEDROCK_API_KEY",
    "BEDROCK_BASE_URL",
    "BEDROCK_MODEL_ID",
    "BEDROCK_MODEL",
)


@pytest.fixture(autouse=True)
def _no_bedrock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in BEDROCK_ENV:
        monkeypatch.delenv(name, raising=False)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "database_url": f"sqlite:///{tmp_path / 'meeting-desk-test.db'}",
        "fake_google": True,
        "fake_llm": True,
        "seed_demo": True,
        "auth_dev_user": ADMIN,
        "session_secret": "test-secret",
        # The metrics port is a real listening socket, which the guard above forbids. The metrics
        # app itself is exercised through an ASGI client in tests/test_telemetry_metrics.py.
        "metrics_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def _fresh_telemetry() -> Iterator[None]:
    """Counters, gauges and breakers start empty in every test.

    They are process-wide by design (one registry per process), so without this a test would read
    another test's numbers.
    """
    from app.telemetry.metrics import reset_metrics
    from app.telemetry.providers import reset_provider_telemetry

    reset_provider_telemetry(reset_metrics())
    yield


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def member_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path, auth_dev_user=MEMBER))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def outsider_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path, auth_dev_user=OUTSIDER))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def google(client: TestClient) -> FakeGoogle:
    return client.app.state.google


@pytest.fixture
def clock(client: TestClient):
    return client.app.state.clock


# --- small helpers the route tests share ----------------------------------------------------------


def meeting_by_title(client: TestClient, title: str) -> dict:
    items = client.get("/meetings/list").json()["items"]
    return next(i for i in items if i["title"] == title)


def saved_meeting_id(client: TestClient, title: str) -> str:
    item = meeting_by_title(client, title)
    if item["id"]:
        return item["id"]
    created = client.post("/meetings/from-calendar", json={"calendar_event_id": item["calendar_event_id"]})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def workbook_by_name(client: TestClient, name: str) -> dict:
    return next(w for w in client.get("/workbooks").json() if w["name"] == name)


def connect_fixture_workbook(client: TestClient) -> dict:
    from app.google.fake import FIXTURE_SPREADSHEET_ID

    response = client.post(
        "/workbooks/connect",
        json={"url": f"https://docs.google.com/spreadsheets/d/{FIXTURE_SPREADSHEET_ID}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


__all__ = [
    "ADMIN",
    "FIXTURES",
    "MEMBER",
    "OUTSIDER",
    "NetworkAccessBlocked",
    "connect_fixture_workbook",
    "make_settings",
    "meeting_by_title",
    "saved_meeting_id",
    "seed_data",
    "workbook_by_name",
]
