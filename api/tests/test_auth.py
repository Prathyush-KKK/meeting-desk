"""Sign-in, the allow-list and roles."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import session as session_cookie
from app.config import Settings
from app.main import create_app
from tests.conftest import ADMIN, MEMBER, OUTSIDER, make_settings


def test_dev_user_is_signed_in_with_its_allow_list_role(client: TestClient) -> None:
    me = client.get("/auth/me").json()
    assert me["email"] == ADMIN
    assert me["role"] == "admin"
    assert me["is_admin"] is True


def test_member_role_comes_from_the_allow_list(member_client: TestClient) -> None:
    assert member_client.get("/auth/me").json()["role"] == "member"


def test_account_off_the_allow_list_is_refused_with_the_admins_named(outsider_client: TestClient) -> None:
    response = outsider_client.get("/auth/me")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert OUTSIDER not in detail
    assert ADMIN in detail


def test_allow_list_entry_binds_to_the_google_sub_on_first_sign_in(client: TestClient) -> None:
    client.get("/auth/me")
    entry = next(e for e in client.get("/admin/allow-list").json() if e["email"] == ADMIN)
    assert entry["signed_in"] is True
    never = next(e for e in client.get("/admin/allow-list").json() if e["email"] == MEMBER)
    assert never["signed_in"] is False


def test_without_a_dev_user_and_without_a_cookie_the_answer_is_401(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, auth_dev_user=None))
    with TestClient(app) as client:
        assert client.get("/auth/me").status_code == 401


def test_a_valid_session_cookie_signs_in(tmp_path: Path) -> None:
    seeded = create_app(make_settings(tmp_path))
    with TestClient(seeded) as bootstrap:
        bootstrap.get("/auth/me")  # seeds and binds

    settings: Settings = make_settings(tmp_path, auth_dev_user=None)
    app = create_app(settings)
    with TestClient(app) as client:
        token = session_cookie.serializer(settings).dumps({"sub": f"dev|{ADMIN}", "email": ADMIN})
        client.cookies.set(settings.session_cookie, token)
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == ADMIN


def test_a_tampered_cookie_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, auth_dev_user=None)
    app = create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie, "not.a.valid.token")
        assert client.get("/auth/me").status_code == 401


def test_login_without_google_configured_says_so(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, auth_dev_user=None))
    with TestClient(app) as client:
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 503
        assert "AUTH_DEV_USER" in response.json()["detail"]


def test_members_cannot_change_or_read_the_allow_list(member_client: TestClient) -> None:
    response = member_client.post("/admin/allow-list", json={"email": "new.person@example.com"})
    assert response.status_code == 403
    assert member_client.get("/admin/allow-list").status_code == 403


def test_logout_clears_the_cookie(client: TestClient) -> None:
    assert client.post("/auth/logout").json() == {"ok": True}


def test_a_lost_race_on_the_first_sign_in_recovers_instead_of_500(tmp_path: Path, monkeypatch) -> None:
    """A first load fires four list requests at once; two can reach the INSERT together.

    One of them loses the unique index on ``users.google_sub``. That is not an error - the row the
    other request wrote is the row this one wanted - so the insert is retried as a read rather than
    becoming a 500 on the very first page the person sees.
    """
    from app.auth import deps
    from app.db import Database
    from app.models import User

    sub, email = "dev|racer@example.com", "racer@example.com"
    db = Database(f"sqlite:///{tmp_path / 'race.db'}")
    db.create_all()
    with db.session() as seed:  # the request that got there first
        seed.add(User(google_sub=sub, email=email, name="Racer", role="admin"))
        seed.commit()

    real = deps._find_user
    calls = {"n": 0}

    def blind_once(session, google_sub: str, address: str):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, google_sub, address)

    monkeypatch.setattr(deps, "_find_user", blind_once)

    with db.session() as second:
        user = deps._ensure_user(second, sub, email, "Racer", "admin")
        second.commit()
        assert user.google_sub == sub
        assert user.email == email
    assert calls["n"] == 2, "the insert should have been retried as a read"

    with db.session() as check:
        assert len(list(check.query(User).all())) == 1


def test_last_seen_is_written_once_a_minute_not_once_a_request(tmp_path: Path) -> None:
    """Every request used to UPDATE users.last_seen_at inside its own transaction. The row lock
    that takes is held until the request answers - and an inline extraction answers a minute or
    two later, so every other request of the same person queued behind it and the app looked dead.
    """
    from datetime import datetime, timedelta

    from app.auth import deps
    from app.db import Database

    sub, email = "dev|steady@example.com", "steady@example.com"
    db = Database(f"sqlite:///{tmp_path / 'seen.db'}")
    db.create_all()
    with db.session() as first:
        user = deps._ensure_user(first, sub, email, "Steady", "admin")
        first.commit()
        stamped = user.last_seen_at
    assert stamped is not None

    with db.session() as second:  # seconds later: read, not written
        user = deps._ensure_user(second, sub, email, "Steady", "admin")
        assert user.last_seen_at.replace(tzinfo=None) == stamped.replace(tzinfo=None)
        assert not second.is_modified(user), "nothing to UPDATE, so no row lock to hold"

    with db.session() as aged:  # a minute later: written
        row = aged.get(deps.User, user.id)
        row.last_seen_at = datetime.now(UTC) - timedelta(seconds=deps.LAST_SEEN_INTERVAL_SECONDS + 1)
        aged.commit()
    with db.session() as third:
        user = deps._ensure_user(third, sub, email, "Steady", "admin")
        assert user.last_seen_at.replace(tzinfo=None) > stamped.replace(tzinfo=None)


def test_sign_in_commits_before_the_route_runs(client: TestClient) -> None:
    """``authenticate`` ends its own transaction, so a long route holds no lock on the users row."""
    from app.auth import deps

    seen: list[bool] = []
    original = deps.Session.commit

    def spy(self):
        seen.append(True)
        return original(self)

    deps.Session.commit = spy  # type: ignore[method-assign]
    try:
        assert client.get("/auth/me").status_code == 200
    finally:
        deps.Session.commit = original  # type: ignore[method-assign]
    assert len(seen) >= 2, "one commit inside authenticate, one when the request ends"


# --- the Google callback, end to end ------------------------------------------------------------------


def test_the_google_callback_checks_a_signed_id_token_and_signs_the_person_in(tmp_path: Path) -> None:
    """The whole sign-in round trip on the HTTP client authlib really uses (httpx2): the code is
    exchanged with its PKCE verifier, the RS256 id_token is checked against Google's keys and the
    nonce from the login, and the person on the allow-list gets the session cookie."""
    import base64
    import json
    import time
    from urllib.parse import parse_qs, urlparse

    import httpx2
    from itsdangerous import TimestampSigner
    from joserfc import jwt
    from joserfc.jwk import RSAKey

    from app.auth.oidc import build_oauth

    client_id = "client-id.apps.googleusercontent.com"
    settings = make_settings(tmp_path, auth_dev_user="", google_client_id=client_id, google_client_secret="s")
    key = RSAKey.generate_key(2048, parameters={"kid": "google-1"})
    seen: list[httpx2.Request] = []
    nonce_box: dict[str, str] = {}

    def google(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/oauth2/v3/certs":
            return httpx2.Response(200, json={"keys": [key.as_dict(private=False)]})
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": client_id,
            "sub": "google-sub-daniel",
            "email": ADMIN,
            "email_verified": True,
            "hd": "example.com",
            "nonce": nonce_box["nonce"],
            "iat": now,
            "exp": now + 3600,
        }
        id_token = jwt.encode({"alg": "RS256", "kid": "google-1"}, claims, key)
        return httpx2.Response(
            200,
            json={
                "access_token": "ya29.token",
                "id_token": id_token,
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    app = create_app(settings)
    oauth = build_oauth(settings)
    oauth.google.server_metadata.update(
        {
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            "id_token_signing_alg_values_supported": ["RS256"],
            "_loaded_at": 1,
        }
    )
    oauth.google.client_kwargs["transport"] = httpx2.MockTransport(google)
    app.state.oauth = oauth

    with TestClient(app) as client:
        login = client.get("/auth/login", follow_redirects=False)
        query = parse_qs(urlparse(login.headers["location"]).query)
        raw = TimestampSigner(settings.session_secret).unsign(
            client.cookies[settings.state_cookie], max_age=settings.state_cookie_max_age_seconds
        )
        stored = next(
            v for k, v in json.loads(base64.urlsafe_b64decode(raw)).items() if k.startswith("_state_google_")
        )
        nonce_box["nonce"] = query["nonce"][0]

        done = client.get(
            "/auth/callback", params={"code": "4/sign-in", "state": query["state"][0]}, follow_redirects=False
        )

    assert done.status_code in (302, 303, 307), done.text
    assert settings.session_cookie in done.cookies or settings.session_cookie in client.cookies
    token_request = next(r for r in seen if r.url.path == "/token")
    form = dict(httpx2.QueryParams(token_request.content.decode()))
    assert form["code"] == "4/sign-in"
    assert form["code_verifier"] == stored["data"]["code_verifier"]
    assert any(r.url.path == "/oauth2/v3/certs" for r in seen), (
        "the id_token was not checked against Google's keys"
    )
