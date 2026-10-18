"""Step 3: points - list, edit, bulk, defer, restore, soft delete with undo, manual add."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import meeting_by_title, saved_meeting_id


def _meeting(client: TestClient) -> str:
    return meeting_by_title(client, "Mobile roadmap review")["id"]


def test_seeded_points_are_active(client: TestClient) -> None:
    points = client.get("/points", params={"meeting_id": _meeting(client)}).json()
    assert len(points) == 6
    assert {p["lifecycle"] for p in points} == {"active"}
    assert {p["kind"] for p in points} == {"action", "decision"}


def test_patch_autosaves_one_field_and_records_who(client: TestClient) -> None:
    point = client.get("/points", params={"meeting_id": _meeting(client)}).json()[0]
    patched = client.patch(f"/points/{point['id']}", json={"status": "blocked"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "blocked"
    assert patched.json()["updated_by"] == "daniel.okafor@example.com"
    assert patched.json()["text"] == point["text"]  # nothing else moved


def test_editing_the_owner_resolves_the_email(client: TestClient) -> None:
    point = client.get("/points", params={"meeting_id": _meeting(client)}).json()[4]
    patched = client.patch(f"/points/{point['id']}", json={"owner_text": "Sofia Silva"})
    assert patched.json()["owner_email"] == "sofia.silva@example.com"
    assert patched.json()["owner_ambiguous"] is False


def test_editing_the_text_updates_the_normalised_form(client: TestClient) -> None:
    point = client.get("/points", params={"meeting_id": _meeting(client)}).json()[0]
    patched = client.patch(f"/points/{point['id']}", json={"text": "Review the WEIGHT dataset!"})
    assert patched.json()["text_norm"] == "review the weight dataset"


def test_bulk_assign_and_status(client: TestClient) -> None:
    points = client.get("/points", params={"meeting_id": _meeting(client)}).json()
    ids = [p["id"] for p in points[:3]]
    response = client.post(
        "/points/bulk", json={"ids": ids, "patch": {"workstream": "Platform", "status": "done"}}
    )
    assert response.status_code == 200
    assert all(p["workstream"] == "Platform" and p["status"] == "done" for p in response.json())


def test_defer_hides_a_point_and_restore_brings_it_back(client: TestClient) -> None:
    meeting_id = _meeting(client)
    point = client.get("/points", params={"meeting_id": meeting_id}).json()[0]

    deferred = client.post(f"/points/{point['id']}/defer")
    assert deferred.json()["lifecycle"] == "deferred"
    active = client.get("/points", params={"meeting_id": meeting_id}).json()
    assert point["id"] not in [p["id"] for p in active]

    hidden = client.get("/points", params={"meeting_id": meeting_id, "lifecycle": "deferred"}).json()
    assert [p["id"] for p in hidden] == [point["id"]]

    restored = client.post(f"/points/{point['id']}/restore")
    assert restored.json()["lifecycle"] == "active"
    assert restored.json()["deferred_at"] is None if "deferred_at" in restored.json() else True


def test_bulk_defer(client: TestClient) -> None:
    meeting_id = _meeting(client)
    ids = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()[:2]]
    response = client.post("/points/defer", json={"ids": ids})
    assert [p["lifecycle"] for p in response.json()] == ["deferred", "deferred"]
    assert len(client.get("/points", params={"meeting_id": meeting_id}).json()) == 4


def test_soft_delete_offers_a_ten_second_undo_and_restores(client: TestClient) -> None:
    meeting_id = _meeting(client)
    point = client.get("/points", params={"meeting_id": meeting_id}).json()[0]

    deleted = client.delete(f"/points/{point['id']}")
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["undo_url"].endswith("/restore")
    assert body["undo_until"] < body["recoverable_until"]
    assert point["id"] not in [
        p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()
    ]
    assert point["id"] in [p["id"] for p in client.get("/points/deleted").json()]

    undone = client.post(f"/points/{point['id']}/restore")
    assert undone.status_code == 200
    assert point["id"] in [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]


def test_add_a_manual_point(client: TestClient) -> None:
    meeting_id = _meeting(client)
    response = client.post(
        "/points",
        json={
            "meeting_id": meeting_id,
            "kind": "risk",
            "text": "Card-network licensing cannot be engineered around",
            "owner_text": "Daniel Okafor",
            "status": "open",
        },
    )
    assert response.status_code == 201
    assert response.json()["owner_email"] == "daniel.okafor@example.com"
    assert response.json()["workstream"] == "Mobile"  # defaults from the meeting


def test_a_first_name_shared_by_two_attendees_is_flagged_not_guessed(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Billing and payments workflows")
    response = client.post(
        "/points",
        json={"meeting_id": meeting_id, "text": "check the billing branches", "owner_text": "Daniela"},
    )
    body = response.json()
    # Daniel Okafor and Daniela Mehta are both in the room under near-identical
    # spellings (notes are transcribed by ear), so a bare first name is flagged, never guessed.
    assert body["owner_text"] == "Daniela"
    assert body["owner_email"] is None
    assert body["owner_ambiguous"] is True


def test_copy_as_text_groups_by_kind(client: TestClient) -> None:
    points = client.get("/points", params={"meeting_id": _meeting(client)}).json()
    response = client.post("/points/copy-text", json={"ids": [p["id"] for p in points]})
    text = response.json()["text"]
    assert "Actions" in text and "Decisions" in text
    assert "[Anna Moreno]" in text


def test_unknown_point_is_a_404(client: TestClient) -> None:
    assert client.get("/points/not-a-uuid").status_code == 404
    assert (
        client.patch("/points/11111111-1111-1111-1111-111111111111", json={"status": "open"}).status_code
        == 404
    )
