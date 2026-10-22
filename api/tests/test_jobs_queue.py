"""The jobs as plain functions, and the procrastinate wrapping around them."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from procrastinate.testing import InMemoryConnector

from app.google.fake import FakeGoogle
from app.google.interface import AuthExpired
from app.jobs.fetch_doc import RETRY_EVERY, RETRY_FOR, fetch_missing_docs, meetings_due_for_check
from app.jobs.queue import (
    EXTRACT_TASK,
    FETCH_DOCS_CRON,
    FETCH_DOCS_TASK,
    TOKEN_HEALTH_CRON,
    TOKEN_HEALTH_TASK,
    build_job_app,
    configure,
    run_extraction_job,
    run_fetch_missing_docs,
    run_token_health,
)
from app.models import Connection, Extraction, Meeting, Note
from tests.conftest import ADMIN, make_settings, saved_meeting_id

# --- fetch_doc: every 5 minutes for an hour after the meeting ends ---------------------------------


def test_the_doc_fetch_picks_up_a_meeting_that_just_ended_and_imports_the_full_notes(
    client: TestClient,
) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")  # ended 16:48, the clock says 17:02
    google = client.app.state.google
    clock = client.app.state.clock
    with client.app.state.db.session() as session:
        first = fetch_missing_docs(session, google, clock)
        session.commit()
        assert first.to_dict() == {"checked": [meeting_id], "imported": [meeting_id], "still_missing": []}
        note = session.query(Note).filter_by(meeting_id=uuid.UUID(meeting_id), source="gemini_doc").one()
        assert note.title == "Platform squad sync - Notes by Gemini - Full notes"
        assert "The Next Steps" in note.text
        assert note.created_by == "meeting-desk (doc fetch)"
        meeting = session.get(Meeting, uuid.UUID(meeting_id))
        assert meeting.step == "notes"

        # Five minutes later the meeting has its note: nothing to check.
        clock.advance(minutes=5)
        again = fetch_missing_docs(session, google, clock)
        assert again.to_dict() == {"checked": [], "imported": [], "still_missing": []}

    sources = {
        s["key"]: s for s in client.get("/notes/sources", params={"meeting_id": meeting_id}).json()["sources"]
    }
    assert sources["gemini_doc"]["available"] is True
    activity = client.get("/admin/activity").json()
    assert any("Picked up the Notes by Gemini doc" in a["text"] for a in activity)


def test_a_meeting_without_a_doc_stays_missing_until_the_hour_is_up(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")
    clock = client.app.state.clock
    with client.app.state.db.session() as session:
        meeting = session.get(Meeting, uuid.UUID(meeting_id))
        meeting.attachments = []
        meeting.title = "Nothing was recorded here"  # no doc under this name either
        session.commit()

        checks = 0
        while True:
            report = fetch_missing_docs(session, client.app.state.google, clock)
            if not report.checked:
                break
            assert report.still_missing == [meeting_id]
            checks += 1
            clock.advance(seconds=int(RETRY_EVERY.total_seconds()))
        # 16:48 + 60 min = 17:48; checks at 17:02, :07, ... :47 - then the window has closed.
        assert checks == 10
        assert timedelta(hours=1) == RETRY_FOR


def test_only_calendar_meetings_that_ended_in_the_last_hour_are_due(client: TestClient) -> None:
    saved_meeting_id(client, "Platform squad sync")
    with client.app.state.db.session() as session:
        now = client.app.state.clock.now()
        due = {m.title for m in meetings_due_for_check(session, now)}
        assert due == {"Platform squad sync"}
        assert meetings_due_for_check(session, now + timedelta(hours=2)) == []
        assert meetings_due_for_check(session, now - timedelta(hours=1)) == []


def test_a_doc_only_the_second_admin_can_read_is_imported_through_that_connection(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Ethan Interview Task Handover")
    clock = client.app.state.clock
    with client.app.state.db.session() as session:
        meeting = session.get(Meeting, uuid.UUID(meeting_id))
        meeting.end_at = clock.now() - timedelta(minutes=20)
        session.commit()
        report = fetch_missing_docs(session, client.app.state.google, clock)
        session.commit()
        assert report.imported == [meeting_id]
    activity = client.get("/admin/activity").json()
    assert any(a["text"].endswith("through alex.s@example.com") for a in activity)


def test_an_expired_connection_met_on_the_way_is_marked_in_the_jobs_session(client: TestClient) -> None:
    meeting_id = saved_meeting_id(client, "Platform squad sync")

    class Revoked(FakeGoogle):
        def get_document(self, connection_email, document_id, include_tabs_content=True):
            if connection_email == ADMIN:
                raise AuthExpired(f"{connection_email}: invalid_grant")
            return super().get_document(connection_email, document_id, include_tabs_content)

    with client.app.state.db.session() as session:
        report = fetch_missing_docs(session, Revoked(), client.app.state.clock)
        session.commit()
        assert report.imported == [meeting_id]  # the second connection carried it
        row = session.query(Connection).filter_by(email=ADMIN).one()
        assert row.status == "expired"
        assert "invalid_grant" in row.last_error


# --- the queue --------------------------------------------------------------------------------------


def _queued_app(tmp_path: Path):
    settings = make_settings(tmp_path, jobs_enabled=True)
    connector = InMemoryConnector()
    return create_app_with(settings, connector), connector


def create_app_with(settings, connector):
    from app.main import create_app

    return create_app(settings, jobs=build_job_app(settings, connector=connector))


def test_the_job_app_registers_the_three_tasks_with_their_schedules(tmp_path: Path) -> None:
    job_app = build_job_app(make_settings(tmp_path), connector=InMemoryConnector())
    assert {EXTRACT_TASK, FETCH_DOCS_TASK, TOKEN_HEALTH_TASK} <= set(job_app.tasks)
    periodic = {p.task.name: p.cron for p in job_app.periodic_registry.periodic_tasks.values()}
    assert periodic == {FETCH_DOCS_TASK: FETCH_DOCS_CRON, TOKEN_HEALTH_TASK: TOKEN_HEALTH_CRON}
    assert FETCH_DOCS_CRON == "*/5 * * * *"
    assert TOKEN_HEALTH_CRON.split()[2:] == ["*", "*", "*"]  # daily


def test_extract_enqueues_and_polling_reports_queued_then_done(tmp_path: Path) -> None:
    app, connector = _queued_app(tmp_path)
    with TestClient(app) as client:
        meeting_id = saved_meeting_id(client, "Platform squad sync")
        client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: call Maya by Friday"})

        queued = client.post(f"/meetings/{meeting_id}/extract").json()
        assert queued["queued"] is True
        assert queued["points"] == []
        assert queued["extraction"]["status"] == "queued"
        assert queued["poll"] == f"/extractions/{queued['extraction']['id']}"
        (job,) = connector.jobs.values()
        assert job["task_name"] == EXTRACT_TASK
        assert job["args"] == {"extraction_id": queued["extraction"]["id"], "actor": ADMIN}
        assert job["status"] == "todo"

        polled = client.get(queued["poll"]).json()
        assert polled["status"] == "queued"
        assert polled["points"] == []

        # The worker's half, called directly.
        result = run_extraction_job(app.state.runtime, queued["extraction"]["id"], ADMIN)
        assert result["status"] == "done"
        assert result["created_points"] == 1

        done = client.get(queued["poll"]).json()
        assert done["status"] == "done"
        assert done["provider"] == "fake"
        assert [p["owner_email"] for p in done["points"]] == ["alex.s@example.com"]
        assert client.get(f"/meetings/{meeting_id}").json()["step"] == "points"
        activity = client.get("/admin/activity").json()
        assert activity[0]["text"] == "Extracted 1 points from Platform squad sync"
        assert activity[1]["text"] == "Queued extraction for Platform squad sync"


def test_a_failing_provider_leaves_the_row_in_error_and_the_notes_untouched(tmp_path: Path) -> None:
    from app.extract.provider import ExtractionError
    from app.main import create_app

    class Broken:
        name = "vertex"

        def extract(self, text, context):
            raise ExtractionError("Vertex AI refused the call: 429 quota")

    settings = make_settings(tmp_path, jobs_enabled=True)
    connector = InMemoryConnector()
    app = create_app(settings, jobs=build_job_app(settings, connector=connector), extraction=Broken())
    with TestClient(app) as client:
        meeting_id = saved_meeting_id(client, "Platform squad sync")
        client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: call Maya by Friday"})
        queued = client.post(f"/meetings/{meeting_id}/extract").json()
        result = run_extraction_job(app.state.runtime, queued["extraction"]["id"], ADMIN)
        assert result["status"] == "error"
        assert "429 quota" in result["error"]
        polled = client.get(queued["poll"]).json()
        assert polled["status"] == "error"
        assert len(client.get("/notes", params={"meeting_id": meeting_id}).json()) == 1
        assert client.get("/points", params={"meeting_id": meeting_id}).json() == []


def test_the_periodic_task_bodies_run_against_the_runtime(tmp_path: Path) -> None:
    app, _ = _queued_app(tmp_path)
    with TestClient(app) as client:
        saved_meeting_id(client, "Platform squad sync")
        configure(app.state.runtime)
        docs = run_fetch_missing_docs(app.state.runtime)
        assert len(docs["imported"]) == 1
        health = run_token_health(app.state.runtime)
        assert health == {"checked": True, "unhealthy": []}
        with app.state.db.session() as session:
            extraction = Extraction(meeting_id=uuid.uuid4())
            session.add(extraction)
            session.commit()
            orphan = str(extraction.id)
        assert run_extraction_job(app.state.runtime, orphan)["status"] == "error"
        with pytest.raises(LookupError):
            run_extraction_job(app.state.runtime, str(uuid.uuid4()))
    configure(None)


def test_health_reports_the_queue(tmp_path: Path) -> None:
    app, _ = _queued_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/health").json()["jobs"] is True


# --- the entry points -------------------------------------------------------------------------------------

API_DIR = Path(__file__).resolve().parents[1]


def _fresh_python(*args: str) -> subprocess.CompletedProcess[str]:
    """A new interpreter: the tests import app.main first, which hides an import cycle that only
    shows when a job module is the first thing loaded, as it is in the worker."""
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JOBS_ENABLED")}
    return subprocess.run(
        [sys.executable, *args], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=60
    )


@pytest.mark.parametrize(
    "module", ["app.jobs.queue", "app.jobs.schema", "app.jobs", "app.notes_store", "app.main"]
)
def test_every_entry_module_imports_on_its_own(module: str) -> None:
    result = _fresh_python("-c", f"import {module}")
    assert result.returncode == 0, result.stderr


def test_the_worker_starts_and_stops_on_its_own_config_check() -> None:
    """``python -m app.jobs.queue`` is what the chart's worker runs. With jobs off it must reach
    the settings check, not die on an import."""
    result = _fresh_python("-m", "app.jobs.queue")
    assert "JOBS_ENABLED is off" in result.stderr, result.stderr
