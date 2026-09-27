"""Admin: connections, the allow-list and the activity log."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ADMIN, make_settings, meeting_by_title


def test_connections_are_listed_with_their_status(client: TestClient) -> None:
    body = client.get("/admin/connections").json()
    emails = [c["email"] for c in body["connections"]]
    assert emails == ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"]
    assert all(c["status"] == "ok" for c in body["connections"])
    assert body["warning"] == ""  # two connections, so no warning
    assert body["banner"] == ""


def test_an_expired_connection_raises_a_banner(client: TestClient) -> None:
    from app.models import Connection

    with client.app.state.db.session() as session:
        connection = session.query(Connection).filter_by(email="ansul.s@simpleo.ai").one()
        connection.status = "expired"
        connection.last_error = "token revoked"
        session.commit()

    body = client.get("/admin/connections").json()
    assert "ansul.s@simpleo.ai" in body["banner"]
    assert "keep working" in body["banner"]


def test_one_connection_warns_until_there_are_two(tmp_path: Path) -> None:
    from app.models import Connection

    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        with app.state.db.session() as session:
            session.delete(session.query(Connection).filter_by(email="ansul.s@simpleo.ai").one())
            session.commit()
        assert "Connect a second" in client.get("/admin/connections").json()["warning"]


def test_the_health_job_marks_nothing_when_everything_is_fine(client: TestClient) -> None:
    response = client.post("/admin/connections/health")
    assert response.status_code == 200
    assert response.json() == {"checked": True, "unhealthy": []}


def test_allow_list_crud_is_admin_only(client: TestClient, member_client: TestClient) -> None:
    added = client.post("/admin/allow-list", json={"email": "New.Person@simpleo.ai", "role": "member"})
    assert added.status_code == 201
    assert added.json()["email"] == "new.person@simpleo.ai"
    assert added.json()["added_by"] == ADMIN
    assert added.json()["signed_in"] is False

    assert client.post("/admin/allow-list", json={"email": "new.person@simpleo.ai"}).status_code == 409

    promoted = client.patch("/admin/allow-list/new.person@simpleo.ai", json={"role": "admin"})
    assert promoted.json()["role"] == "admin"

    removed = client.delete("/admin/allow-list/new.person@simpleo.ai")
    assert removed.json()["ok"] is True
    assert "new.person@simpleo.ai" not in [e["email"] for e in client.get("/admin/allow-list").json()]

    assert member_client.delete("/admin/allow-list/nishchay.s@simpleo.ai").status_code == 403


def test_an_admin_can_fix_an_email_in_place(client: TestClient) -> None:
    client.post("/admin/allow-list", json={"email": "arya.kumari@simpleo.ai"})
    patched = client.patch(
        "/admin/allow-list/arya.kumari@simpleo.ai", json={"email": "arya.kumari1@simpleo.ai"}
    )
    assert patched.status_code == 200
    assert patched.json()["email"] == "arya.kumari1@simpleo.ai"
    emails = [e["email"] for e in client.get("/admin/allow-list").json()]
    assert "arya.kumari1@simpleo.ai" in emails
    assert "arya.kumari@simpleo.ai" not in emails


def test_you_cannot_remove_your_own_access(client: TestClient) -> None:
    response = client.delete(f"/admin/allow-list/{ADMIN}")
    assert response.status_code == 409


def test_patching_an_unknown_entry_is_a_404(client: TestClient) -> None:
    assert client.patch("/admin/allow-list/nobody@simpleo.ai", json={"role": "admin"}).status_code == 404


def test_activity_records_who_did_what(client: TestClient) -> None:
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "a fresh note"})
    activity = client.get("/admin/activity").json()
    assert activity[0]["actor"] == ADMIN
    assert activity[0]["text"] == "Saved a note on Nutrition roadmap review"
    assert len(activity) > 1  # the seeded entries are there too


def test_review1_28_the_admin_readers_are_admin_only(
    client: TestClient, member_client: TestClient
) -> None:
    """Who is connected, who may sign in and what everyone did are the admin page's own data.

    A member could read all three before: the allow-list is every colleague's email, the activity
    log is everyone's actions, and the connections list names the admin accounts. None of it is
    needed to capture a meeting.
    """
    for path in ("/admin/connections", "/admin/allow-list", "/admin/activity", "/admin/health"):
        assert member_client.get(path).status_code == 403, path
        assert client.get(path).status_code == 200, path


def test_workspace_health(client: TestClient) -> None:
    body = client.get("/admin/health").json()
    assert body["connections_ok"] == 2
    assert body["allow_list"] is True


def test_the_service_health_endpoint_needs_no_sign_in(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, auth_dev_user=None))
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["ok"] is True
        assert body["fake_google"] is True


def test_the_banner_reaches_members_too(client: TestClient, member_client: TestClient) -> None:
    """Screen review R1-23. Spec section 7: an expired admin connection puts a banner on every page.
    The banner came from the admin-only connections list, so members never saw it."""
    from app.models import Connection

    assert member_client.get("/admin/connections/status").json() == {
        "banner": "",
        "first_run": False,
        "first_run_notice": "",
        "can_connect": False,
    }

    with client.app.state.db.session() as session:
        connection = session.query(Connection).filter_by(email="ansul.s@simpleo.ai").one()
        connection.status = "expired"
        session.commit()

    for who, can_connect in ((member_client, False), (client, True)):
        body = who.get("/admin/connections/status").json()
        assert "ansul.s@simpleo.ai" in body["banner"]
        assert "keep working" in body["banner"]
        assert body["can_connect"] is can_connect
        # Only what the banner says: no scopes, no list of accounts.
        assert set(body) == {"banner", "first_run", "first_run_notice", "can_connect"}


def test_first_run_tells_a_member_whom_to_ask(tmp_path: Path) -> None:
    from app.models import Connection

    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        with app.state.db.session() as session:
            for connection in session.query(Connection).all():
                session.delete(connection)
            session.commit()
        admin = client.get("/admin/connections/status").json()
        assert admin["first_run"] is True
        assert "Connect yours" in admin["first_run_notice"]
        # No connections at all is the first run, not "only one connected".
        assert client.get("/admin/connections").json()["warning"] == ""


def test_first_run_notice_for_a_member_names_the_admins(tmp_path: Path) -> None:
    from app.models import Connection

    app = create_app(make_settings(tmp_path, auth_dev_user="nishchay.s@simpleo.ai"))
    with TestClient(app) as member:
        with app.state.db.session() as session:
            for connection in session.query(Connection).all():
                session.delete(connection)
            session.commit()
        body = member.get("/admin/connections/status").json()
        assert body["first_run"] is True
        assert body["can_connect"] is False
        assert "ask an admin" in body["first_run_notice"]
        assert ADMIN in body["first_run_notice"]
