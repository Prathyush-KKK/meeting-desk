"""The connection picker: first healthy connection able to see the item, and what it reports."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.google.http import GoogleApiError
from app.google.interface import AuthExpired, NotFoundError, PermissionDenied, RateLimited
from app.google.picker import first_able
from app.models import Connection
from app.routes.common import pick_for

A, B, C = "a@simpleo.ai", "b@simpleo.ai", "c@simpleo.ai"


def test_the_first_connection_that_answers_wins_and_the_rest_are_not_asked() -> None:
    asked: list[str] = []

    def attempt(email: str) -> str:
        asked.append(email)
        return f"seen by {email}"

    pick = first_able([A, B, C], attempt)
    assert pick.ok and pick.email == A and pick.value == "seen by a@simpleo.ai"
    assert asked == [A]
    assert pick.tried == [A]


def test_refusals_are_skipped_in_order_and_the_last_one_is_the_detail() -> None:
    answers = {
        A: PermissionDenied("not shared", detail="doc-1 is not shared with a@simpleo.ai"),
        B: RateLimited("b is backed off"),
        C: "the doc",
    }

    def attempt(email: str) -> str:
        answer = answers[email]
        if isinstance(answer, Exception):
            raise answer
        return answer

    pick = first_able([A, B, C], attempt)
    assert pick.email == C
    assert pick.tried == [A, B, C]
    assert pick.errors == {A: "not shared (doc-1 is not shared with a@simpleo.ai)", B: "b is backed off"}
    assert pick.detail == "b is backed off"


def test_nobody_able_reports_the_last_refusal_and_which_are_expired() -> None:
    def attempt(email: str) -> str:
        raise {
            A: AuthExpired(f"{A}: invalid_grant"),
            B: NotFoundError("gone"),
            C: GoogleApiError(503, "down"),
        }[email]

    pick = first_able([A, B, C], attempt)
    assert not pick.ok
    assert pick.email is None and pick.value is None
    assert pick.detail == "503 down"
    assert pick.expired == {A: "a@simpleo.ai: invalid_grant"}


def test_an_unaccepted_answer_moves_on_to_the_next_connection() -> None:
    hits = {A: [], B: ["found"]}
    pick = first_able([A, B], lambda email: hits[email], accept=bool)
    assert pick.email == B and pick.value == ["found"]
    nothing = first_able([A], lambda email: hits[email], accept=bool)
    assert not nothing.ok and nothing.detail == ""


def test_pick_for_marks_an_expired_connection_in_the_session(client: TestClient) -> None:
    def attempt(email: str) -> str:
        if email == "prathyush.kodhanpur@simpleo.ai":
            raise AuthExpired(f"{email}: invalid_grant: Token has been expired or revoked.")
        return "ok"

    with client.app.state.db.session() as session:
        pick = pick_for(session, ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"], attempt)
        session.commit()
        assert pick.email == "ansul.s@simpleo.ai"
        row = session.query(Connection).filter_by(email="prathyush.kodhanpur@simpleo.ai").one()
        assert row.status == "expired"
        assert row.last_error.endswith("Token has been expired or revoked.")
    banner = client.get("/admin/connections").json()["banner"]
    assert "prathyush.kodhanpur@simpleo.ai" in banner
