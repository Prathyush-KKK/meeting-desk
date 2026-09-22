"""Step 2: sources, imports, paste, quick paste, include, move, delete."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import meeting_by_title, saved_meeting_id


def _sources(client: TestClient, meeting_id: str) -> dict[str, dict]:
    body = client.get("/notes/sources", params={"meeting_id": meeting_id}).json()
    return {s["key"]: s for s in body["sources"]}


def test_sources_come_from_the_record(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    sources = _sources(client, meeting_id)
    assert sources["gemini_doc"]["available"] is True
    assert "Full notes" in sources["gemini_doc"]["tabs"]
    assert sources["transcript"]["available"] is True
    assert sources["recap_email"]["available"] is True
    assert sources["paste"]["available"] is True


def test_a_doc_shared_with_only_the_second_admin_is_still_readable(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Eshan Interview Task Handover")
    sources = _sources(client, meeting_id)
    assert sources["gemini_doc"]["available"] is True
    assert sources["gemini_doc"]["connection"] == "ansul.s@simpleo.ai"


def test_a_doc_shared_with_nobody_says_so_and_offers_paste(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Household and wealth workflows")
    sources = _sources(client, meeting_id)
    assert sources["gemini_doc"]["available"] is False
    assert "not shared with an admin account" in sources["gemini_doc"]["message"]
    assert sources["paste"]["available"] is True


def test_a_meeting_without_a_doc_says_not_generated_yet(client: TestClient) -> None:
    meeting_id = meeting_by_title(client, "Sprinto call prep")["id"]
    sources = _sources(client, meeting_id)
    assert sources["gemini_doc"]["message"] == "not generated yet"


def test_import_prefers_the_full_notes_tab(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    doc = _sources(client, meeting_id)["gemini_doc"]
    response = client.post(
        "/notes/import",
        json={"meeting_id": meeting_id, "source": "gemini_doc", "origin_ref": doc["origin_ref"]},
    )
    assert response.status_code == 201
    assert response.json()["tab"] == "Full notes"
    assert "Mirror Open Food Facts" in response.json()["note"]["text"]


def test_importing_the_transcript_tab(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    doc = _sources(client, meeting_id)["gemini_doc"]
    response = client.post(
        "/notes/import",
        json={"meeting_id": meeting_id, "source": "transcript", "origin_ref": doc["origin_ref"]},
    )
    assert response.status_code == 201
    assert response.json()["tab"] == "Transcript"


def test_importing_an_unshared_doc_is_refused_with_a_reason(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Household and wealth workflows")
    response = client.post(
        "/notes/import", json={"meeting_id": meeting_id, "source": "gemini_doc", "origin_ref": "doc-m5"}
    )
    assert response.status_code == 409
    assert "not shared with an admin account" in response.json()["detail"]


def test_recap_email_import(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    response = client.post("/notes/import", json={"meeting_id": meeting_id, "source": "recap_email"})
    assert response.status_code == 201
    assert response.json()["connection"] == "prathyush.kodhanpur@simpleo.ai"
    assert "Next steps" in response.json()["note"]["text"]


def test_the_same_text_twice_is_reported_not_stored_twice(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    payload = {"meeting_id": meeting_id, "text": "Nishchay: finish the alert standard"}
    first = client.post("/notes/paste", json=payload)
    second = client.post("/notes/paste", json=payload)
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert second.json()["note"]["id"] == first.json()["note"]["id"]
    assert len(client.get("/notes", params={"meeting_id": meeting_id}).json()) == 1


def test_markdown_from_a_gemini_chat_is_normalised_on_save(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    response = client.post(
        "/notes/paste",
        json={
            "meeting_id": meeting_id,
            "text": "**The Next Steps**\n* Ansul S: call Madhu\n- Nishchay: alerts",
        },
    )
    text = response.json()["note"]["text"]
    assert "**" not in text
    assert text.splitlines() == ["The Next Steps", "Ansul S: call Madhu", "Nishchay: alerts"]


def test_paste_moves_the_meeting_to_the_notes_step(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "something"})
    assert client.get(f"/meetings/{meeting_id}").json()["step"] == "notes"


def test_quick_paste_with_a_meeting_saves_a_note_on_it(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    response = client.post("/notes/quick", json={"meeting_id": meeting_id, "text": "quick thought"})
    assert response.status_code == 201
    assert response.json()["created_meeting"] is False
    assert response.json()["meeting"]["id"] == meeting_id


def test_quick_paste_without_a_meeting_creates_one_from_the_first_line(client: TestClient) -> None:
    response = client.post(
        "/notes/quick",
        json={"text": "**Vendor call with Madhu**\nAnsul S: send the questionnaire\nNishchay: book the slot"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created_meeting"] is True
    assert body["meeting"]["title"] == "Vendor call with Madhu"
    assert body["meeting"]["source"] == "manual"
    assert body["meeting"]["step"] == "notes"
    assert body["note"]["text"].startswith("Vendor call with Madhu")


def test_quick_paste_of_nothing_is_refused(client: TestClient) -> None:
    assert client.post("/notes/quick", json={"text": "   "}).status_code == 422


def test_include_toggle(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    note = client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "raw transcript"}).json()[
        "note"
    ]
    off = client.patch(f"/notes/{note['id']}", json={"include": False})
    assert off.json()["include"] is False
    assert client.patch(f"/notes/{note['id']}", json={"include": True}).json()["include"] is True


def test_a_note_can_be_moved_to_another_meeting(client: TestClient) -> None:
    wrong = saved_meeting_id(client, "Platform squad sync")
    right = meeting_by_title(client, "Sprinto call prep")["id"]
    note = client.post("/notes/paste", json={"meeting_id": wrong, "text": "belongs to Sprinto"}).json()[
        "note"
    ]

    moved = client.post(f"/notes/{note['id']}/move", json={"meeting_id": right})
    assert moved.status_code == 200
    assert moved.json()["meeting_id"] == right
    assert client.get("/notes", params={"meeting_id": wrong}).json() == []
    assert len(client.get("/notes", params={"meeting_id": right}).json()) == 1


def test_moving_onto_a_meeting_that_already_has_the_note_is_refused(client: TestClient) -> None:
    a = saved_meeting_id(client, "Platform squad sync")
    b = meeting_by_title(client, "Sprinto call prep")["id"]
    text = "the same words"
    note = client.post("/notes/paste", json={"meeting_id": a, "text": text}).json()["note"]
    client.post("/notes/paste", json={"meeting_id": b, "text": text})
    assert client.post(f"/notes/{note['id']}/move", json={"meeting_id": b}).status_code == 409


def test_delete_a_note(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    note = client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "delete me"}).json()["note"]
    assert client.delete(f"/notes/{note['id']}").json()["ok"] is True
    assert client.get("/notes", params={"meeting_id": meeting_id}).json() == []
