"""Sign-in, the allow-list and roles."""

from __future__ import annotations

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
    response = member_client.post("/admin/allow-list", json={"email": "new.person@simpleo.ai"})
    assert response.status_code == 403
    assert member_client.get("/admin/allow-list").status_code == 403


def test_logout_clears_the_cookie(client: TestClient) -> None:
    assert client.post("/auth/logout").json() == {"ok": True}


def test_a_lost_race_on_the_first_sign_in_recovers_instead_of_500(
    tmp_path: Path, monkeypatch
) -> None:
    """A first load fires four list requests at once; two can reach the INSERT together.

    One of them loses the unique index on ``users.google_sub``. That is not an error - the row the
    other request wrote is the row this one wanted - so the insert is retried as a read rather than
    becoming a 500 on the very first page the person sees.
    """
    from app.auth import deps
    from app.db import Database
    from app.models import User

    sub, email = "dev|racer@simpleo.ai", "racer@simpleo.ai"
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
