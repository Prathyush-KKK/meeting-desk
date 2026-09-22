"""Step 1: the merged list, calendar upserts, manual meetings, re-sync."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import meeting_by_title, saved_meeting_id


def test_list_merges_calendar_and_saved_meetings(client: TestClient) -> None:
    body = client.get("/meetings/list").json()
    titles = [i["title"] for i in body["items"]]
    # Calendar-only, and saved-from-the-seed, both show up.
    assert "Platform squad sync" in titles
    assert "Nutrition roadmap review" in titles
    assert "Sprinto call prep" in titles  # manual
    assert body["connections"]
    assert body["age_minutes"] == 0


def test_the_same_event_on_two_calendars_appears_once(client: TestClient) -> None:
    items = client.get("/meetings/list").json()["items"]
    # Platform squad sync is on both admin calendars (organizer Ansul, attendee Prathyush).
    matching = [i for i in items if i["title"] == "Platform squad sync"]
    assert len(matching) == 1
    assert matching[0]["ical_uid"].endswith("@google.com")


def test_calendar_cards_are_read_only_until_they_are_captured(client: TestClient) -> None:
    card = meeting_by_title(client, "Platform squad sync")
    assert card["saved"] is False
    assert card["editable"] is False
    assert card["id"] is None


def test_selecting_a_calendar_event_upserts_the_record(client: TestClient) -> None:
    card = meeting_by_title(client, "Platform squad sync")
    first = client.post("/meetings/from-calendar", json={"calendar_event_id": card["calendar_event_id"]})
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["key"].startswith("M-")

    again = client.post("/meetings/from-calendar", json={"calendar_event_id": card["calendar_event_id"]})
    assert again.json()["created"] is False
    assert again.json()["id"] == first.json()["id"]

    listed = [i for i in client.get("/meetings/list").json()["items"] if i["title"] == "Platform squad sync"]
    assert len(listed) == 1
    assert listed[0]["saved"] is True


def test_unknown_calendar_event_is_a_404(client: TestClient) -> None:
    response = client.post("/meetings/from-calendar", json={"calendar_event_id": "nope"})
    assert response.status_code == 404


def test_times_are_shown_in_asia_kolkata(client: TestClient) -> None:
    card = meeting_by_title(client, "Platform squad sync")
    assert card["start"] == "16:00"
    assert card["start_at"].endswith("+05:30")
    assert card["timezone"] == "Asia/Kolkata"


def test_manual_meeting_create_patch_and_soft_delete(client: TestClient) -> None:
    created = client.post(
        "/meetings/manual",
        json={
            "title": "Sprinto follow-up",
            "date": "2026-09-22",
            "start": "18:00",
            "end": "18:30",
            "workstream": "Platform",
            "attendees": [{"name": "Ansul S", "email": "ansul.s@simpleo.ai"}],
        },
    )
    assert created.status_code == 201
    meeting = created.json()
    assert meeting["source"] == "manual"
    assert meeting["editable"] is True

    patched = client.patch(
        f"/meetings/{meeting['id']}", json={"title": "Sprinto follow-up v2", "start": "19:00"}
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Sprinto follow-up v2"
    assert patched.json()["start"] == "19:00"

    deleted = client.delete(f"/meetings/{meeting['id']}")
    assert deleted.status_code == 200
    assert "recoverable_until" in deleted.json()
    assert client.get(f"/meetings/{meeting['id']}").status_code == 404

    restored = client.post(f"/meetings/{meeting['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["title"] == "Sprinto follow-up v2"


def test_calendar_meetings_are_not_editable_or_deletable(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    assert client.patch(f"/meetings/{meeting_id}", json={"title": "nope"}).status_code == 409
    assert client.delete(f"/meetings/{meeting_id}").status_code == 409
    # the workstream and the step are the exceptions
    assert client.patch(f"/meetings/{meeting_id}", json={"workstream": "Platform"}).status_code == 200


def test_resync_updates_calendar_fields_and_keeps_notes(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "a note that must survive"})

    google = client.app.state.google
    event = next(e for e, _ in google.events if e.id == "7jt039pupf1l0iu9b995v8pjj8")
    event.title = "Platform squad sync (moved)"

    response = client.post(f"/meetings/{meeting_id}/resync")
    assert response.status_code == 200
    assert response.json()["resynced"] is True
    assert response.json()["title"] == "Platform squad sync (moved)"
    assert len(client.get("/notes", params={"meeting_id": meeting_id}).json()) == 1


def test_resync_of_a_manual_meeting_is_refused(client: TestClient) -> None:
    meeting_id = meeting_by_title(client, "Sprinto call prep")["id"]
    assert client.post(f"/meetings/{meeting_id}/resync").status_code == 409


def test_list_counts_notes_and_active_points(client: TestClient) -> None:
    item = meeting_by_title(client, "Nutrition roadmap review")
    assert item["notes_count"] == 1
    assert item["points_count"] == 6
