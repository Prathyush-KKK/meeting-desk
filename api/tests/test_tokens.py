"""Refresh tokens at rest (Fernet, key versions, dual-read) and in flight (the broker)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.google.interface import AuthExpired, GoogleError
from app.google.tokens import (
    DbRefreshTokens,
    InMemoryRefreshTokens,
    TokenBroker,
    TokenCipher,
    TokenDecryptError,
    generate_key,
    rotate_connections,
)
from app.main import create_app
from app.models import Connection
from tests.conftest import make_settings
from tests.google_mock import MockGoogleApi, json_response

KEY_V1 = generate_key()
KEY_V2 = generate_key()


# --- the cipher ---------------------------------------------------------------------------------


def test_encrypt_round_trips_and_records_the_key_version() -> None:
    cipher = TokenCipher(KEY_V1, version=1)
    enc, version = cipher.encrypt("1//refresh-token")
    assert version == 1
    assert enc != "1//refresh-token"
    assert cipher.decrypt(enc, 1) == "1//refresh-token"


def test_settings_carry_the_key_under_the_meeting_desk_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETING_DESK_TOKEN_KEY", KEY_V2)
    monkeypatch.setenv("MEETING_DESK_TOKEN_KEY_PREVIOUS", KEY_V1)
    monkeypatch.setenv("MEETING_DESK_TOKEN_KEY_VERSION", "2")
    settings = Settings(_env_file=None)
    assert settings.token_key == KEY_V2
    assert settings.token_key_previous == KEY_V1
    assert settings.token_key_version == 2
    cipher = TokenCipher.from_settings(settings)
    assert cipher is not None and cipher.version == 2
    # An explicit keyword still wins over the environment.
    assert Settings(_env_file=None, token_key="explicit").token_key == "explicit"


def test_no_key_means_no_cipher() -> None:
    assert TokenCipher.from_settings(Settings(_env_file=None, token_key="")) is None
    with pytest.raises(ValueError, match="MEETING_DESK_TOKEN_KEY"):
        TokenCipher("")


def test_rotation_reads_the_previous_key_and_re_encrypts_rows(tmp_path: Path) -> None:
    old = TokenCipher(KEY_V1, version=1)
    enc_v1, _ = old.encrypt("1//refresh-token")

    rotated = TokenCipher(KEY_V2, version=2, previous=KEY_V1)
    assert rotated.decrypt(enc_v1, 1) == "1//refresh-token"  # dual-read during the rotation window
    assert rotated.needs_rotation(1) is True

    app = create_app(make_settings(tmp_path))
    with TestClient(app):
        with app.state.db.session() as session:
            connection = session.query(Connection).filter_by(email="alex.s@example.com").one()
            connection.refresh_token_enc = enc_v1
            connection.key_version = 1
            session.commit()
        with app.state.db.session() as session:
            assert rotate_connections(session, rotated) == ["alex.s@example.com"]
            session.commit()
        with app.state.db.session() as session:
            connection = session.query(Connection).filter_by(email="alex.s@example.com").one()
            assert connection.key_version == 2
            assert connection.refresh_token_enc != enc_v1
            assert rotated.decrypt(connection.refresh_token_enc, 2) == "1//refresh-token"
            assert rotate_connections(session, rotated) == []  # nothing left on the old key

    # Once PREVIOUS is dropped, a row still on the old key cannot be read - the error says so.
    without_previous = TokenCipher(KEY_V2, version=2)
    with pytest.raises(TokenDecryptError):
        without_previous.decrypt(enc_v1, 1)


# --- the broker -----------------------------------------------------------------------------------


def _broker(api: MockGoogleApi, store: InMemoryRefreshTokens, now: list[float]) -> TokenBroker:
    return TokenBroker(
        client_id="cid",
        client_secret="secret",
        store=store,
        http=httpx.Client(transport=api.transport()),
        now=lambda: now[0],
    )


def test_the_broker_refreshes_once_and_caches_until_expiry() -> None:
    api = MockGoogleApi().on("POST", "/token", "token_refresh_ok.json")
    store = InMemoryRefreshTokens({"alex.s@example.com": "1//rt"})
    now = [1_000.0]
    broker = _broker(api, store, now)

    assert broker.access_token("alex.s@example.com") == "ya29.a0AfB_byC-fresh-token-0001"
    assert broker.access_token("alex.s@example.com") == "ya29.a0AfB_byC-fresh-token-0001"
    assert len(api.requests) == 1
    form = dict(httpx.QueryParams(api.requests[0].content.decode()))
    assert form == {
        "grant_type": "refresh_token",
        "client_id": "cid",
        "client_secret": "secret",
        "refresh_token": "1//rt",
    }
    now[0] += 3600  # past expires_in - margin
    broker.access_token("alex.s@example.com")
    assert len(api.requests) == 2
    broker.access_token("alex.s@example.com", force_refresh=True)
    assert len(api.requests) == 3


def test_invalid_grant_is_auth_expired_and_drops_the_cached_token() -> None:
    api = MockGoogleApi().on(
        "POST",
        "/token",
        [
            lambda r: json_response("token_refresh_ok.json"),
            lambda r: json_response("token_refresh_invalid_grant.json", 400),
        ],
    )
    store = InMemoryRefreshTokens({"alex.s@example.com": "1//rt"})
    broker = _broker(api, store, [0.0])
    broker.access_token("alex.s@example.com")
    with pytest.raises(AuthExpired) as err:
        broker.access_token("alex.s@example.com", force_refresh=True)
    assert str(err.value) == "alex.s@example.com: invalid_grant: Token has been expired or revoked."
    # Nothing cached any more: the next call asks Google again rather than reusing a dead token.
    with pytest.raises(AuthExpired):
        broker.access_token("alex.s@example.com")
    assert len(api.requests) == 3


def test_an_unknown_connection_or_a_server_error_are_distinct() -> None:
    api = MockGoogleApi().on("POST", "/token", lambda r: httpx.Response(503, text="try later"))
    store = InMemoryRefreshTokens({"alex.s@example.com": "1//rt"})
    broker = _broker(api, store, [0.0])
    with pytest.raises(AuthExpired):
        broker.access_token("nobody@example.com")
    with pytest.raises(GoogleError, match="token refresh failed"):
        broker.access_token("alex.s@example.com")  # a 503 is not a revoked token


def test_the_db_store_decrypts_with_the_row_key_version(tmp_path: Path) -> None:
    cipher = TokenCipher(KEY_V1, version=1)
    app = create_app(make_settings(tmp_path))
    with TestClient(app):
        with app.state.db.session() as session:
            connection = session.query(Connection).filter_by(email="alex.s@example.com").one()
            connection.refresh_token_enc, connection.key_version = cipher.encrypt("1//db-token")
            session.commit()
        store = DbRefreshTokens(app.state.db, cipher)
        assert store.refresh_token_for("alex.s@example.com") == "1//db-token"
        with pytest.raises(AuthExpired, match="no refresh token stored"):
            store.refresh_token_for("daniel.okafor@example.com")
        with pytest.raises(AuthExpired, match="not a connected account"):
            store.refresh_token_for("nobody@example.com")
        # A row on a key this deployment no longer has is reported as needing a reconnect.
        other = DbRefreshTokens(app.state.db, TokenCipher(KEY_V2, version=2))
        with pytest.raises(AuthExpired, match="no configured token key"):
            other.refresh_token_for("alex.s@example.com")
