"""'Connect an account': the authorization-code flow, token storage and the reconnect."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.google.oauth import CONNECTION_SCOPES, SCOPE_LABELS, granted_scopes, missing_scopes
from app.google.tokens import TokenCipher, generate_key
from app.main import create_app
from app.models import Connection
from tests.conftest import ADMIN, make_settings
from tests.google_mock import MockGoogleApi, json_response

KEY = generate_key()


def _app(tmp_path: Path, api: MockGoogleApi, **overrides):
    values = {
        "google_client_id": "client-id.apps.googleusercontent.com",
        "google_client_secret": "client-secret",
        "token_key": KEY,
        "token_key_version": 3,
        "google_connect_redirect_uri": "http://localhost:8000/admin/connections/callback",
        **overrides,
    }
    return create_app(make_settings(tmp_path, **values), transport=api.transport())


def test_connect_redirects_to_google_with_offline_access_forced_consent_and_the_scope_list(tmp_path) -> None:
    app = _app(tmp_path, MockGoogleApi())
    with TestClient(app) as client:
        response = client.get("/admin/connections/connect", follow_redirects=False)
        assert response.status_code == 307
        target = urlparse(response.headers["location"])
        assert target.netloc == "accounts.google.com"
        query = parse_qs(target.query)
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["client-id.apps.googleusercontent.com"]
        assert query["redirect_uri"] == ["http://localhost:8000/admin/connections/callback"]
        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]
        assert query["include_granted_scopes"] == ["true"]
        assert query["hd"] == ["example.com"]
        assert query["scope"][0].split() == CONNECTION_SCOPES
        assert query["state"][0]

        # A reconnect pre-selects the account.
        again = client.get(
            "/admin/connections/connect", params={"email": "alex.s@example.com"}, follow_redirects=False
        )
        assert parse_qs(urlparse(again.headers["location"]).query)["login_hint"] == ["alex.s@example.com"]


def test_the_callback_exchanges_the_code_and_stores_the_encrypted_refresh_token(tmp_path) -> None:
    api = (
        MockGoogleApi()
        .on("POST", "/token", "oauth_token_exchange.json")
        .on("GET", "/v1/userinfo", "oauth_userinfo.json")
    )
    app = _app(tmp_path, api)
    with TestClient(app) as client:
        start = client.get("/admin/connections/connect", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

        done = client.get(
            "/admin/connections/callback",
            params={"code": "4/0AbCdEf", "state": state},
            follow_redirects=False,
        )
        assert done.status_code == 303
        assert done.headers["location"] == "http://localhost:5173/admin?connected=alex.s%40example.com"

        exchange = api.sent("POST", "/token")[0]
        form = dict(httpx.QueryParams(exchange.content.decode()))
        assert form["grant_type"] == "authorization_code"
        assert form["code"] == "4/0AbCdEf"
        assert form["redirect_uri"] == "http://localhost:8000/admin/connections/callback"
        assert form["client_id"] == "client-id.apps.googleusercontent.com"
        assert (
            api.sent("GET", "/v1/userinfo")[0].headers["Authorization"]
            == "Bearer ya29.a0AfB_byC-exchange-0001"
        )

        with app.state.db.session() as session:
            connection = session.query(Connection).filter_by(email="alex.s@example.com").one()
            assert connection.status == "ok"
            assert connection.name == "Alex S"
            assert connection.key_version == 3
            assert connection.refresh_token_enc and "1//0gXyZ" not in connection.refresh_token_enc
            cipher = TokenCipher(KEY, version=3)
            assert (
                cipher.decrypt(connection.refresh_token_enc, connection.key_version)
                == "1//0gXyZ-refresh-token-for-alex"
            )
            assert connection.scopes == list(SCOPE_LABELS.values())
            assert connection.last_error is None

        activity = client.get("/admin/activity").json()
        assert activity[0]["text"] == "Reconnected Google account alex.s@example.com"
        assert activity[0]["actor"] == ADMIN


def test_a_new_account_is_created_and_a_missing_scope_is_reported(tmp_path) -> None:
    token = json_response("oauth_token_exchange.json").json()
    token["scope"] = token["scope"].replace(" https://www.googleapis.com/auth/gmail.readonly", "")
    info = {
        **json_response("oauth_userinfo.json").json(),
        "email": "new.admin@example.com",
        "name": "New Admin",
    }
    api = MockGoogleApi().on("POST", "/token", token).on("GET", "/v1/userinfo", info)
    app = _app(tmp_path, api)
    with TestClient(app) as client:
        start = client.get("/admin/connections/connect", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        done = client.get(
            "/admin/connections/callback", params={"code": "c", "state": state}, follow_redirects=False
        )
        assert done.headers["location"].endswith(
            "/admin?connected=new.admin%40example.com&missing=gmail.readonly"
        )
        emails = [c["email"] for c in client.get("/admin/connections").json()["connections"]]
        assert "new.admin@example.com" in emails


def test_a_wrong_state_or_a_foreign_domain_is_refused(tmp_path) -> None:
    info = {**json_response("oauth_userinfo.json").json(), "email": "someone@gmail.com", "hd": ""}
    api = MockGoogleApi().on("POST", "/token", "oauth_token_exchange.json").on("GET", "/v1/userinfo", info)
    app = _app(tmp_path, api)
    with TestClient(app) as client:
        assert (
            client.get("/admin/connections/callback", params={"code": "c", "state": "nope"}).status_code
            == 400
        )
        start = client.get("/admin/connections/connect", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        refused = client.get("/admin/connections/callback", params={"code": "c", "state": state})
        assert refused.status_code == 403
        assert "example.com" in refused.json()["detail"]


def test_google_saying_no_goes_back_to_the_admin_page_with_the_error(tmp_path) -> None:
    app = _app(tmp_path, MockGoogleApi())
    with TestClient(app) as client:
        client.get("/admin/connections/connect", follow_redirects=False)
        back = client.get(
            "/admin/connections/callback", params={"error": "access_denied"}, follow_redirects=False
        )
        assert back.status_code == 303
        assert back.headers["location"].endswith("/admin?error=access_denied")


def test_connect_is_admin_only_and_needs_configuration(tmp_path, member_client: TestClient) -> None:
    assert member_client.get("/admin/connections/connect", follow_redirects=False).status_code == 403
    unconfigured = create_app(make_settings(tmp_path))
    with TestClient(unconfigured) as client:
        response = client.get("/admin/connections/connect", follow_redirects=False)
        assert response.status_code == 503
        assert "GOOGLE_CLIENT_ID" in response.json()["detail"]
    no_key = create_app(make_settings(tmp_path, google_client_id="x", google_client_secret="y"))
    with TestClient(no_key) as client:
        assert (
            "MEETING_DESK_TOKEN_KEY"
            in client.get("/admin/connections/connect", follow_redirects=False).json()["detail"]
        )


def test_scope_helpers() -> None:
    assert granted_scopes({"scope": "openid https://www.googleapis.com/auth/spreadsheets"}) == [
        "spreadsheets"
    ]
    assert missing_scopes(["spreadsheets"]) == [
        "calendar.readonly",
        "drive.readonly",
        "documents.readonly",
        "gmail.readonly",
        "directory.readonly",
    ]


def test_rotate_keys_re_encrypts_stored_tokens(tmp_path) -> None:
    old = TokenCipher(KEY, version=1)
    new_key = generate_key()
    api = MockGoogleApi()
    app = _app(tmp_path, api, token_key=new_key, token_key_previous=KEY, token_key_version=2)
    with TestClient(app) as client:
        with app.state.db.session() as session:
            row = session.query(Connection).filter_by(email="alex.s@example.com").one()
            row.refresh_token_enc, row.key_version = old.encrypt("1//old")
            session.commit()
        response = client.post("/admin/connections/rotate-keys")
        assert response.json() == {"key_version": 2, "rotated": ["alex.s@example.com"]}
        with app.state.db.session() as session:
            row = session.query(Connection).filter_by(email="alex.s@example.com").one()
            assert row.key_version == 2
            assert TokenCipher(new_key, version=2).decrypt(row.refresh_token_enc, 2) == "1//old"
        assert client.post("/admin/connections/rotate-keys").json()["rotated"] == []
