"""``BOOTSTRAP_ADMINS``: the first admin on a fresh real-mode database comes from configuration.

Without it, ``FAKE_GOOGLE=0`` starts with an empty allow-list, every sign-in is refused, and the
refusal names no admin to ask. These tests run the startup path with the fakes off and the seed
off, which is exactly the shape of a first deployment.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.google.tokens import generate_key
from app.main import create_app
from app.models import Activity, AllowListEntry, User
from tests.conftest import ADMIN, MEMBER, make_settings

FIRST = "first.admin@simpleo.ai"
SECOND = "second.admin@simpleo.ai"


def _real_mode(tmp_path: Path, **overrides) -> Settings:
    values = {
        "fake_google": False,
        "seed_demo": False,
        "auth_dev_user": None,
        "bootstrap_admins": "",
        "token_key": generate_key(),
        "google_client_id": "client-id.apps.googleusercontent.com",
        "google_client_secret": "client-secret",
        "session_secret": "a-real-session-secret-of-forty-chars-xxx",
    }
    values.update(overrides)
    return make_settings(tmp_path, **values)


def _entries(app) -> dict[str, str]:
    with app.state.db.session() as db:
        return {row.email: row.role for row in db.scalars(select(AllowListEntry)).all()}


def test_parsing_trims_lowercases_and_dedupes(tmp_path: Path) -> None:
    raw = " First.Admin@simpleo.ai ,, second.admin@simpleo.ai,First.Admin@simpleo.ai,notanemail "
    s = _real_mode(tmp_path, bootstrap_admins=raw)
    assert s.bootstrap_admin_emails == [FIRST, SECOND]


def test_fresh_real_mode_database_gets_the_admins(tmp_path: Path) -> None:
    settings = _real_mode(tmp_path, bootstrap_admins=f"{FIRST},{SECOND}")
    app = create_app(settings)
    with TestClient(app):
        assert _entries(app) == {FIRST: "admin", SECOND: "admin"}
        with app.state.db.session() as db:
            texts = [a.text for a in db.scalars(select(Activity)).all()]
        assert any(FIRST in t and "BOOTSTRAP_ADMINS" in t for t in texts)


def test_without_it_a_fresh_real_mode_database_has_nobody(tmp_path: Path) -> None:
    app = create_app(_real_mode(tmp_path))
    with TestClient(app):
        assert _entries(app) == {}


def test_second_startup_changes_nothing(tmp_path: Path) -> None:
    settings = _real_mode(tmp_path, bootstrap_admins=FIRST)
    app = create_app(settings)
    with TestClient(app):
        pass
    app = create_app(settings)
    with TestClient(app):
        assert _entries(app) == {FIRST: "admin"}
        with app.state.db.session() as db:
            adds = [a for a in db.scalars(select(Activity)).all() if "BOOTSTRAP_ADMINS" in a.text]
        assert len(adds) == 1


def test_member_is_promoted_never_demoted_and_others_kept(tmp_path: Path) -> None:
    # Fake mode seeds MEMBER as a member and ADMIN as an admin; the env names MEMBER.
    settings = make_settings(tmp_path, bootstrap_admins=MEMBER)
    app = create_app(settings)
    with TestClient(app):
        entries = _entries(app)
        assert entries[MEMBER] == "admin"
        assert entries[ADMIN] == "admin"
        assert len(entries) >= 3  # the rest of the seed is untouched

    # Dropping the email from the env later does not remove or demote the entry.
    app = create_app(make_settings(tmp_path, bootstrap_admins=""))
    with TestClient(app):
        assert _entries(app)[MEMBER] == "admin"


def test_promoted_member_is_admin_on_the_next_request(tmp_path: Path) -> None:
    # Sign in once as a member so a users row exists with role=member ...
    app = create_app(make_settings(tmp_path, auth_dev_user=MEMBER))
    with TestClient(app) as client:
        assert client.get("/auth/me").json()["is_admin"] is False
        assert client.get("/admin/allow-list").status_code == 403
    # ... then restart with the env naming them: both the entry and the user row carry admin.
    app = create_app(make_settings(tmp_path, auth_dev_user=MEMBER, bootstrap_admins=MEMBER))
    with TestClient(app) as client:
        assert client.get("/auth/me").json()["is_admin"] is True
        assert client.get("/admin/allow-list").status_code == 200
        with app.state.db.session() as db:
            user = db.scalar(select(User).where(User.email == MEMBER))
        assert user is not None and user.role == "admin"


def test_local_real_mode_sign_in_refuses_a_weak_session_secret(tmp_path: Path) -> None:
    """The Mac launch: ENVIRONMENT=local, FAKE_GOOGLE=0, no dev user - the cookie secret must be real."""
    import pytest

    from app.main import UnsafeConfiguration

    for bad in ("", "short-secret"):
        with pytest.raises(UnsafeConfiguration):
            create_app(_real_mode(tmp_path, environment="local", session_secret=bad))
    # A real secret starts; the same weak secret is fine while AUTH_DEV_USER carries sign-in.
    create_app(_real_mode(tmp_path, environment="local", session_secret="x" * 40))
    create_app(_real_mode(tmp_path, environment="local", session_secret="short", auth_dev_user=ADMIN))
