"""WEB_DIST: the API serves the built web app so one container answers both."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

INDEX = "<!doctype html><html><head><title>Meeting Desk</title></head><body><div id=root></div></body></html>"


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "index-abc.js").write_text("console.log('meeting desk')")
    return dist


def test_without_web_dist_the_api_is_api_only(client: TestClient) -> None:
    assert client.get("/health").json()["ok"] is True
    assert client.get("/").status_code == 404


def test_web_dist_serves_the_app_and_its_assets(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    app = create_app(make_settings(tmp_path, web_dist=str(dist)))
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "Meeting Desk" in root.text

        asset = client.get("/assets/index-abc.js")
        assert asset.status_code == 200
        assert "meeting desk" in asset.text


def test_unknown_paths_fall_back_to_index_but_api_routes_do_not(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    app = create_app(make_settings(tmp_path, web_dist=str(dist)))
    with TestClient(app) as client:
        deep = client.get("/anything/deep/link")
        assert deep.status_code == 200
        assert "<div id=root>" in deep.text

        # The routers are matched first, so the API keeps answering as itself.
        assert client.get("/health").json()["ok"] is True
        assert client.get("/auth/me").json()["email"]
        assert client.get("/meetings/list").status_code == 200
        assert client.get("/points/not-a-uuid").status_code == 404
        assert client.get("/points/not-a-uuid").json()["detail"] == "unknown point"


def test_a_missing_build_is_ignored(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, web_dist=str(tmp_path / "nope")))
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/health").status_code == 200
