"""Extraction: the rule-based provider, owner resolution, due dates, and the route."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import seed_data
from app.extract.fake import FakeExtractionProvider, extract_output
from app.extract.postprocess import Person, normalise_text, parse_due, postprocess, resolve_owner
from app.extract.provider import ExtractionContext
from app.extract.schema import EXTRACTION_JSON_SCHEMA, ExtractionOutput
from tests.conftest import saved_meeting_id

IST = ZoneInfo("Asia/Kolkata")
PEOPLE = [p["name"] for p in seed_data.PEOPLE]


# --- the rule-based provider ----------------------------------------------------------------------


def test_next_steps_lines_become_action_items_with_verbatim_owners() -> None:
    output = extract_output(seed_data.GEMINI_CHAT_NOTE, PEOPLE)
    titles = [a.title for a in output.action_items]
    assert "Review dataset for weight information" in titles
    owners = {a.owner_text for a in output.action_items}
    assert "Anushka Mohanty" in owners
    assert "Nishchay" in owners  # verbatim, not normalised to "Nishchay S"


def test_a_decision_line_becomes_a_decision() -> None:
    output = extract_output("Decided: the Owner column holds a person, not a team", PEOPLE)
    assert [d.statement for d in output.decisions] == ["the Owner column holds a person, not a team"]


def test_a_question_line_becomes_a_question() -> None:
    output = extract_output("Open question: do we fund the payments spike this quarter?", PEOPLE)
    assert len(output.questions) == 1
    assert output.questions[0].statement.endswith("?")


def test_a_risk_line_becomes_a_risk() -> None:
    output = extract_output("Risk: the upload flag has no rollback plan", PEOPLE)
    assert [r.statement for r in output.risks] == ["the upload flag has no rollback plan"]


def test_bracketed_owner_style_is_understood() -> None:
    output = extract_output("[Prathyush Kodhanpur] Mirror Open Food Facts before 3 Oct", PEOPLE)
    item = output.action_items[0]
    assert item.owner_text == "Prathyush Kodhanpur"
    assert item.title == "Mirror Open Food Facts before 3 Oct"
    assert item.due_hint == "before 3 Oct"


def test_the_same_line_twice_yields_one_item() -> None:
    output = extract_output("Ansul S: call Madhu\nAnsul S: call Madhu", PEOPLE)
    assert len(output.action_items) == 1


def test_the_provider_reports_its_name_and_usage() -> None:
    context = ExtractionContext(attendees=[{"name": "Ansul S", "email": "ansul.s@simpleo.ai"}])
    result = FakeExtractionProvider().extract("Ansul S: call Madhu", context)
    assert result.provider == "fake"
    assert result.usage["items"] == 1
    assert isinstance(result.output, ExtractionOutput)


def test_the_json_schema_is_the_v3_shape() -> None:
    assert set(EXTRACTION_JSON_SCHEMA["required"]) == {"action_items", "decisions", "risks", "questions"}
    action = EXTRACTION_JSON_SCHEMA["properties"]["action_items"]["items"]
    assert set(action["required"]) == {"title", "owner_text", "due_hint", "evidence"}


# --- owner resolution -----------------------------------------------------------------------------

ROOM = [
    Person("Prathyush Kodhanpur", "prathyush.kodhanpur@simpleo.ai"),
    Person("Anushka Mohanty", "anushka.mohanty@simpleo.ai"),
    Person("Nishchay S", "nishchay.s@simpleo.ai"),
]


def test_full_name_wins() -> None:
    resolved = resolve_owner("Anushka Mohanty", ROOM)
    assert resolved.owner_email == "anushka.mohanty@simpleo.ai"
    assert resolved.matched_by == "attendee_full"
    assert resolved.ambiguous is False


def test_first_name_resolves_when_unique_in_the_room() -> None:
    resolved = resolve_owner("Nishchay", ROOM)
    assert resolved.owner_email == "nishchay.s@simpleo.ai"
    assert resolved.matched_by == "attendee_first"


def test_two_candidates_set_the_flag_and_keep_the_text() -> None:
    room = [*ROOM, Person("Nishchay Rao", "nishchay.rao@simpleo.ai")]
    resolved = resolve_owner("Nishchay", room)
    assert resolved.ambiguous is True
    assert resolved.owner_email is None
    assert resolved.owner_text == "Nishchay"
    assert set(resolved.candidates) == {"nishchay.s@simpleo.ai", "nishchay.rao@simpleo.ai"}


def test_similar_spellings_do_not_collide() -> None:
    room = [
        Person("Prathyush Kodhanpur", "prathyush.kodhanpur@simpleo.ai"),
        Person("Pratyush Chaudhary", "pratyush.chaudhary@simpleo.ai"),
    ]
    assert resolve_owner("Prathyush Kodhanpur", room).owner_email == "prathyush.kodhanpur@simpleo.ai"
    assert resolve_owner("Pratyush Chaudhary", room).owner_email == "pratyush.chaudhary@simpleo.ai"


def test_a_bare_prathyush_with_both_spellings_in_the_room_is_ambiguous() -> None:
    """The spec's case: Prathyush Kodhanpur and Pratyush Chaudhary are both attendees."""
    room = [
        Person("Prathyush Kodhanpur", "prathyush.kodhanpur@simpleo.ai"),
        Person("Pratyush Chaudhary", "pratyush.chaudhary@simpleo.ai"),
        Person("Ansul S", "ansul.s@simpleo.ai"),
    ]
    for mention in ("Prathyush", "Pratyush", "prathyush"):
        resolved = resolve_owner(mention, room, seed_data.DIRECTORY, seed_data.ALIASES)
        assert resolved.ambiguous is True, mention
        assert resolved.owner_email is None
        assert resolved.owner_text == mention
        assert set(resolved.candidates) == {"prathyush.kodhanpur@simpleo.ai", "pratyush.chaudhary@simpleo.ai"}
    # With only one of them in the room, the near spelling is that person.
    alone = resolve_owner("Pratyush", room[:1] + room[2:])
    assert alone.owner_email == "prathyush.kodhanpur@simpleo.ai"
    assert alone.ambiguous is False
    # Short names never fuzz: "Ana" is not "Anu".
    assert resolve_owner("Ana", [Person("Anu Rao", "anu@simpleo.ai")]).owner_email is None


def test_postprocess_keeps_the_ambiguous_owner_empty_with_both_candidates() -> None:
    output = ExtractionOutput.model_validate(
        {
            "action_items": [
                {
                    "title": "Mirror Open Food Facts before launch",
                    "owner_text": "Prathyush",
                    "due_hint": "",
                    "evidence": "Prathyush: Mirror Open Food Facts before launch",
                },
                {
                    "title": "Review the dataset",
                    "owner_text": "Prathyush Kodhanpur",
                    "due_hint": "by 3 Oct",
                    "evidence": "Prathyush Kodhanpur: Review the dataset by 3 Oct",
                },
            ],
            "decisions": [],
            "risks": [],
            "questions": [],
        }
    )
    context = ExtractionContext(
        meeting_title="Platform squad sync",
        meeting_start=BASE,
        attendees=[
            {"name": "Prathyush Kodhanpur", "email": "prathyush.kodhanpur@simpleo.ai"},
            {"name": "Pratyush Chaudhary", "email": "pratyush.chaudhary@simpleo.ai"},
        ],
    )
    bare, full = postprocess(output, context, seed_data.DIRECTORY, seed_data.ALIASES)
    assert bare.owner_ambiguous is True
    assert bare.owner_email is None
    assert bare.owner_text == "Prathyush"
    assert set(bare.owner_candidates) == {"prathyush.kodhanpur@simpleo.ai", "pratyush.chaudhary@simpleo.ai"}
    assert full.owner_ambiguous is False
    assert full.owner_email == "prathyush.kodhanpur@simpleo.ai"


def test_the_recorded_gemini_output_resolves_owners_the_same_way(client: TestClient) -> None:
    """The Vertex fixture through the real job: a bare first name in a room with both spellings."""
    import json
    from pathlib import Path

    from app.extract.provider import ProviderResult
    from app.jobs.extract import run_extraction
    from app.models import Meeting

    recorded = json.loads(
        (Path(__file__).parent / "fixtures" / "llm" / "vertex_nutrition_review.json").read_text()
    )

    class Recorded:
        name = "vertex"

        def extract(self, text, context):
            return ProviderResult(
                output=ExtractionOutput.model_validate(json.loads(recorded["response"]["text"])),
                provider="vertex",
                model="gemini-2.5-flash",
                region="asia-south1",
            )

    meeting_id = saved_meeting_id(client, "Platform squad sync")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": recorded["notes"]})
    with client.app.state.db.session() as session:
        meeting = session.get(Meeting, __import__("uuid").UUID(meeting_id))
        meeting.attendees = [
            {"name": "Prathyush Kodhanpur", "email": "prathyush.kodhanpur@simpleo.ai"},
            {"name": "Pratyush Chaudhary", "email": "pratyush.chaudhary@simpleo.ai"},
            {"name": "Anushka Mohanty", "email": "anushka.mohanty@simpleo.ai"},
        ]
        extraction, created = run_extraction(
            session, meeting, Recorded(), client.app.state.clock, actor="test"
        )
        session.commit()
        by_owner = {p.owner_text: p for p in created if p.owner_text}
        assert by_owner["Prathyush"].owner_ambiguous is True
        assert by_owner["Prathyush"].owner_email is None
        assert by_owner["Anushka Mohanty"].owner_email == "anushka.mohanty@simpleo.ai"
        assert by_owner["Nishchay"].owner_email == "nishchay.s@simpleo.ai"  # via the directory
        assert by_owner["Anushka Mohanty"].due_date.date().isoformat() == "2026-10-03"
        assert extraction.provider == "vertex"
        assert extraction.output["decisions"][0]["statement"] == "The Owner column holds a person, not a team"


def test_someone_not_in_the_room_falls_through_to_the_directory() -> None:
    resolved = resolve_owner("Shambhavi Singh", ROOM, seed_data.DIRECTORY)
    assert resolved.matched_by == "directory"
    assert resolved.owner_email == "shambhavi.singh@simpleo.ai"


def test_the_alias_table_is_the_last_resort() -> None:
    resolved = resolve_owner("PK", ROOM, [], seed_data.ALIASES)
    assert resolved.matched_by == "alias"
    assert resolved.owner_email == "prathyush.kodhanpur@simpleo.ai"


def test_unassigned_is_not_a_person() -> None:
    resolved = resolve_owner("Unassigned", ROOM, seed_data.DIRECTORY, seed_data.ALIASES)
    assert resolved.owner_email is None
    assert resolved.ambiguous is False


def test_nothing_is_guessed_when_nothing_matches() -> None:
    resolved = resolve_owner("the growth team", ROOM, seed_data.DIRECTORY, seed_data.ALIASES)
    assert resolved.owner_text == "the growth team"
    assert resolved.owner_email is None
    assert resolved.matched_by == "none"


# --- due dates ------------------------------------------------------------------------------------

BASE = datetime(2026, 9, 19, 11, 0, tzinfo=IST)


def test_a_bare_day_and_month_is_parsed_against_the_meeting_start() -> None:
    parsed = parse_due("3 Oct", BASE)
    assert parsed.date().isoformat() == "2026-10-03"
    assert parsed.tzinfo is not None


def test_a_relative_date_uses_the_meeting_start_as_the_base() -> None:
    parsed = parse_due("next Monday", BASE)
    assert parsed.date().isoformat() == "2026-09-21"


def test_nonsense_stays_empty() -> None:
    assert parse_due("when the clinician is free", BASE) is None
    assert parse_due("", BASE) is None


def test_normalise_text_is_stable_for_re_extraction() -> None:
    assert normalise_text("Review  dataset, for WEIGHT!") == "review dataset for weight"


def test_postprocess_maps_every_kind_and_carries_the_workstream() -> None:
    output = extract_output(
        "The Next Steps\nAnushka Mohanty: Review the dataset by 3 Oct\n"
        "Decided: owner is one person\nRisk: portion accuracy is unmeasured\nIs a drink a meal?",
        PEOPLE,
    )
    context = ExtractionContext(
        meeting_title="Nutrition roadmap review",
        meeting_start=BASE,
        workstream="Nutrition",
        attendees=[{"name": p.name, "email": p.email} for p in ROOM],
    )
    points = postprocess(output, context, seed_data.DIRECTORY, seed_data.ALIASES)
    kinds = {p.kind for p in points}
    assert kinds == {"action", "decision", "risk", "question"}
    assert all(p.workstream == "Nutrition" for p in points)
    action = next(p for p in points if p.kind == "action")
    assert action.owner_email == "anushka.mohanty@simpleo.ai"
    assert action.due_date.date().isoformat() == "2026-10-03"
    assert next(p for p in points if p.kind == "decision").status == "decided"


# --- the route ------------------------------------------------------------------------------------


def test_extract_runs_through_the_job_and_creates_points(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    doc = next(
        s
        for s in client.get("/notes/sources", params={"meeting_id": meeting_id}).json()["sources"]
        if s["key"] == "gemini_doc"
    )
    client.post(
        "/notes/import",
        json={"meeting_id": meeting_id, "source": "gemini_doc", "origin_ref": doc["origin_ref"]},
    )

    response = client.post(f"/meetings/{meeting_id}/extract")
    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is False
    assert body["extraction"]["provider"] == "fake"
    assert body["extraction"]["status"] == "done"
    assert body["extraction"]["created_points"] == len(body["points"])
    assert body["extraction"]["created_points"] > 0

    kinds = {p["kind"] for p in body["points"]}
    assert "action" in kinds and "decision" in kinds
    assert client.get(f"/meetings/{meeting_id}").json()["step"] == "points"


def test_re_extracting_adds_only_new_points(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    doc_ref = "doc-m1"
    client.post(
        "/notes/import", json={"meeting_id": meeting_id, "source": "gemini_doc", "origin_ref": doc_ref}
    )
    first = client.post(f"/meetings/{meeting_id}/extract").json()
    assert first["extraction"]["created_points"] > 0

    again = client.post(f"/meetings/{meeting_id}/extract").json()
    assert again["extraction"]["created_points"] == 0
    assert len(client.get("/points", params={"meeting_id": meeting_id}).json()) == len(first["points"])


def test_an_excluded_note_is_not_extracted(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    note = client.post(
        "/notes/paste", json={"meeting_id": meeting_id, "text": "Ansul S: buy the clinician hour"}
    ).json()["note"]
    client.patch(f"/notes/{note['id']}", json={"include": False})
    assert client.post(f"/meetings/{meeting_id}/extract").status_code == 409


def test_extracting_with_no_notes_says_so(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    response = client.post(f"/meetings/{meeting_id}/extract")
    assert response.status_code == 409
    assert "No notes" in response.json()["detail"]


def test_the_extraction_record_is_readable(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Ansul S: call Madhu by Friday"})
    extraction_id = client.post(f"/meetings/{meeting_id}/extract").json()["extraction"]["id"]

    record = client.get(f"/extractions/{extraction_id}").json()
    assert record["schema_version"] == "v3"
    assert record["output"]["action_items"][0]["owner_text"] == "Ansul S"
    assert len(client.get(f"/meetings/{meeting_id}/extractions").json()) == 1
