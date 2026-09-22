"""The app in real mode (FAKE_GOOGLE=0) against a scripted Google.

Proves the wiring rather than any one client: a route asks the picker, the picker asks the real
client, the client asks the HTTP layer, the HTTP layer asks the token broker, the broker decrypts
the refresh token from ``connections`` and refreshes it - and an ``invalid_grant`` on one
connection does not stop the other one serving the page.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient

from app.google.tokens import TokenCipher, generate_key
from app.main import create_app
from app.models import AllowListEntry, Connection
from app.telemetry.metrics import metrics
from app.telemetry.providers import provider_telemetry
from tests.conftest import ADMIN, make_settings
from tests.google_mock import MockGoogleApi, json_response

IST = ZoneInfo("Asia/Kolkata")
KEY = generate_key()
SECOND = "ansul.s@simpleo.ai"


def _real_app(tmp_path: Path, api: MockGoogleApi):
    settings = make_settings(
        tmp_path,
        fake_google=False,
        seed_demo=False,
        google_client_id="cid",
        google_client_secret="secret",
        token_key=KEY,
        calendar_lookback_days=7,
    )
    app = create_app(settings, transport=api.transport())
    cipher = TokenCipher(KEY)
    with app.state.db.session() as session:
        app.state.db.create_all()
        session.add(AllowListEntry(email=ADMIN, role="admin", added_by="setup"))
        for email, token in ((ADMIN, "1//rt-prathyush"), (SECOND, "1//rt-ansul")):
            enc, version = cipher.encrypt(token)
            session.add(
                Connection(
                    email=email,
                    name=email.split("@")[0],
                    scopes=["calendar.readonly", "spreadsheets"],
                    refresh_token_enc=enc,
                    key_version=version,
                    status="ok",
                    connected_at=datetime(2026, 9, 21, 10, 0, tzinfo=IST),
                )
            )
        session.commit()
    return app


def _token_endpoint(request: httpx.Request) -> httpx.Response:
    form = dict(httpx.QueryParams(request.content.decode()))
    if form["refresh_token"] == "1//rt-ansul":
        return json_response("token_refresh_invalid_grant.json", 400)
    return json_response(
        {"access_token": f"at-for-{form['refresh_token']}", "expires_in": 3599, "token_type": "Bearer"}
    )


def test_the_meeting_list_comes_from_google_and_a_dead_connection_is_marked_expired(tmp_path: Path) -> None:
    api = (
        MockGoogleApi()
        .on("POST", "/token", _token_endpoint)
        .on(
            "GET",
            "/calendars/primary/events",
            [
                lambda r: json_response("calendar_events_page1.json"),
                lambda r: json_response("calendar_events_page2.json"),
            ],
        )
    )
    app = _real_app(tmp_path, api)
    with TestClient(app) as client:
        body = client.get("/meetings/list").json()
        titles = [i["title"] for i in body["items"]]
        assert titles == ["Team offsite", "Sprinto vendor call", "Nutrition roadmap review"]
        assert body["items"][2]["start"] == "16:00"
        assert body["items"][2]["attachments"][0]["file_id"] == "1qX9Lm3kNotesDocIdForNutrition"

        # Only Prathyush's connection got a bearer token; Ansul's refresh was refused.
        events = api.sent("GET", "/calendars/primary/events")
        assert {r.headers["Authorization"] for r in events} == {"Bearer at-for-1//rt-prathyush"}
        assert len(api.sent("POST", "/token")) == 2

        connections = {c["email"]: c for c in client.get("/admin/connections").json()["connections"]}
        assert connections[SECOND]["status"] == "expired"
        assert "invalid_grant" in connections[SECOND]["last_error"]
        assert connections[ADMIN]["status"] == "ok"
        assert SECOND in client.get("/admin/connections").json()["banner"]

        # Selecting the event upserts the record with the Calendar fields.
        card = body["items"][2]
        created = client.post(
            "/meetings/from-calendar", json={"calendar_event_id": card["calendar_event_id"]}
        )
        assert created.status_code == 201
        assert created.json()["ical_uid"] == "3icfcbtqoeit5ggbjb4b5ukadq@google.com"
        assert created.json()["organizer_name"] == "Prathyush Kodhanpur"


def test_sources_and_the_doc_import_go_through_the_first_connection_that_can_read(tmp_path: Path) -> None:
    api = (
        MockGoogleApi()
        .on("POST", "/token", _token_endpoint)
        .on(
            "GET",
            "/calendars/primary/events",
            [
                lambda r: json_response("calendar_events_page1.json"),
                lambda r: json_response("calendar_events_page2.json"),
            ],
        )
        .on("GET", "/v1/documents/1qX9Lm3kNotesDocIdForNutrition", "docs_document_tabs.json")
        .on("GET", "/gmail/v1/users/me/messages/18f2c1a9b7e4d3f0", "gmail_message_full.json")
        .on("GET", "/gmail/v1/users/me/messages", "gmail_messages_list.json")
    )
    app = _real_app(tmp_path, api)
    with TestClient(app) as client:
        card = next(
            i
            for i in client.get("/meetings/list").json()["items"]
            if i["title"] == "Nutrition roadmap review"
        )
        meeting_id = client.post(
            "/meetings/from-calendar", json={"calendar_event_id": card["calendar_event_id"]}
        ).json()["id"]

        sources = {
            s["key"]: s
            for s in client.get("/notes/sources", params={"meeting_id": meeting_id}).json()["sources"]
        }
        assert sources["gemini_doc"]["available"] is True
        assert sources["gemini_doc"]["connection"] == ADMIN
        assert sources["gemini_doc"]["tabs"] == ["Quick notes", "Full notes", "Transcript"]
        assert sources["transcript"]["available"] is True
        assert sources["recap_email"]["available"] is True
        gmail_query = MockGoogleApi.params(api.sent("GET", "/gmail/v1/users/me/messages")[0])["q"][0]
        assert gmail_query == 'from:gemini-notes@google.com "Nutrition roadmap review" after:2026/09/19'

        imported = client.post(
            "/notes/import",
            json={
                "meeting_id": meeting_id,
                "source": "gemini_doc",
                "origin_ref": "1qX9Lm3kNotesDocIdForNutrition",
            },
        )
        assert imported.status_code == 201, imported.text
        assert imported.json()["tab"] == "Full notes"
        assert imported.json()["connection"] == ADMIN
        assert "The Next Steps" in imported.json()["note"]["text"]

        recap = client.post("/notes/import", json={"meeting_id": meeting_id, "source": "recap_email"})
        assert recap.status_code == 201, recap.text
        assert recap.json()["note"]["title"] == "Recap: Nutrition roadmap review"

        # Extraction (fake LLM) then runs on the real-mode notes, resolving owners from attendees.
        extracted = client.post(f"/meetings/{meeting_id}/extract").json()
        owners = {p["owner_text"]: p["owner_email"] for p in extracted["points"] if p["owner_text"]}
        assert owners["Anushka Mohanty"] == "anushka.mohanty@simpleo.ai"


def test_a_workbook_connects_reads_and_writes_through_the_real_sheets_client(tmp_path: Path) -> None:
    book = "1RoadmapSpreadsheetId0000000000000000000000"

    def values(request: httpx.Request) -> httpx.Response:
        params = MockGoogleApi.params(request)
        if params.get("valueRenderOption") == ["FORMULA"]:
            return json_response("sheets_values_formulas.json")
        ranges = params["ranges"]
        if ranges == ["'P1 Resolve & Log'!1:40"]:
            return json_response("sheets_values_window.json")
        if ranges == ["'P1 Resolve & Log'!A41:H1000"]:
            return json_response("sheets_values_region_empty.json")
        if ranges == ["Lists!$A$2:$A$5"]:
            return json_response("sheets_values_lists_range.json")
        return json_response({"valueRanges": [{"values": [["In progress"]]} for _ in ranges]})

    def meta(request: httpx.Request) -> httpx.Response:
        params = MockGoogleApi.params(request)
        if params.get("includeGridData") == ["true"]:
            return json_response("sheets_grid_data.json")
        return json_response("sheets_spreadsheet_get.json")

    api = (
        MockGoogleApi()
        .on("POST", "/token", _token_endpoint)
        .on("GET", f"/spreadsheets/{book}/values:batchGet", values)
        .on("GET", f"/spreadsheets/{book}", meta)
        .on("POST", f"/spreadsheets/{book}:batchUpdate", "sheets_batch_update_ok.json")
        .on("GET", f"/drive/v3/files/{book}", "drive_file_get_can_edit.json")
    )
    app = _real_app(tmp_path, api)
    with TestClient(app) as client:
        connected = client.post(
            "/workbooks/connect", json={"url": f"https://docs.google.com/spreadsheets/d/{book}/edit#gid=0"}
        )
        assert connected.status_code == 201, connected.text
        assert connected.json()["name"] == "Nutrition Sialet Product Roadmap"
        assert connected.json()["can_edit"] is True
        assert connected.json()["read_through"] == ADMIN
        assert [t["sheet_id"] for t in connected.json()["tabs"]] == ["0", "1487211930", "22"]
        workbook_id = connected.json()["id"]

        tab = client.get(f"/workbooks/{workbook_id}/tabs/0").json()
        assert tab["layout"]["header_row"] == 2
        assert tab["formula_cols"] == [6]
        assert tab["date_cols"] == [3]
        assert tab["dropdowns"]["4"] == ["Open", "In progress", "Blocked", "Done", "Dropped"]

        # A cell edit: re-read the edited cell, then one batchUpdate with a string value.
        saved = client.post(
            "/sheets/save",
            json={
                "workbook_id": workbook_id,
                "sheet_id": "0",
                "edits": [{"cell": "E4", "before": "In progress", "after": "Done"}],
            },
        )
        assert saved.status_code == 200, saved.text
        (post,) = api.sent("POST", ":batchUpdate")
        assert MockGoogleApi.body(post)["requests"] == [
            {
                "updateCells": {
                    "start": {"sheetId": 0, "rowIndex": 3, "columnIndex": 4},
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": "Done"}}]}],
                    "fields": "userEnteredValue",
                }
            }
        ]
        assert post.headers["Authorization"] == "Bearer at-for-1//rt-prathyush"


def test_a_sheets_429_becomes_a_503_with_retry_after_and_is_counted(tmp_path: Path) -> None:
    """The route level of "Sheets API limits - 429 retried with backoff; the UI shows the retry".

    The client retries in-call (five times by default; none here, so the test is quick), then backs
    the connection off and raises ``RateLimited``. ``create_app``'s handler turns that into 503 with
    a ``Retry-After`` header, which is what the web client shows. Telemetry counts it as an error
    on ``google_sheets`` with failure_reason ``rate_limited`` - and does *not* open the breaker,
    because Google is up and saying "slower".
    """
    book = "1RoadmapSpreadsheetId0000000000000000000000"
    api = (
        MockGoogleApi()
        .on("POST", "/token", _token_endpoint)
        .on("GET", f"/spreadsheets/{book}", lambda r: json_response("error_429_quota.json", 429))
        .on("GET", f"/drive/v3/files/{book}", "drive_file_get_can_edit.json")
    )
    settings = make_settings(
        tmp_path,
        fake_google=False,
        seed_demo=False,
        google_client_id="cid",
        google_client_secret="secret",
        token_key=KEY,
        google_max_retries=0,          # the retry loop itself is tested in test_google_http.py
        google_backoff_base_seconds=0,
    )
    app = create_app(settings, transport=api.transport())
    cipher = TokenCipher(KEY)
    with app.state.db.session() as session:
        app.state.db.create_all()
        session.add(AllowListEntry(email=ADMIN, role="admin", added_by="setup"))
        enc, version = cipher.encrypt("1//rt-prathyush")
        session.add(
            Connection(
                email=ADMIN,
                name="Prathyush",
                scopes=["spreadsheets"],
                refresh_token_enc=enc,
                key_version=version,
                status="ok",
                connected_at=datetime(2026, 9, 21, 10, 0, tzinfo=IST),
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.post(
            "/workbooks/connect", json={"url": f"https://docs.google.com/spreadsheets/d/{book}/edit"}
        )
        assert response.status_code == 503, response.text
        assert "rate-limiting" in response.json()["detail"]
        assert int(response.headers["Retry-After"]) >= 1
        assert response.json()["retry_after_seconds"] > 0

        # A second attempt fails fast from the per-connection cooldown, without another call out.
        calls = len(api.sent("GET", f"/spreadsheets/{book}"))
        again = client.post(
            "/workbooks/connect", json={"url": f"https://docs.google.com/spreadsheets/d/{book}/edit"}
        )
        assert again.status_code == 503
        assert len(api.sent("GET", f"/spreadsheets/{book}")) == calls

    samples = {
        (s.labels["provider"], s.labels["op"], s.labels["outcome"]): s.value
        for family in metrics().registry.collect()
        for s in family.samples
        if s.name == "external_provider_requests_total"
    }
    assert samples[("google_sheets", "spreadsheets_get", "error")] == 2
    breaker = provider_telemetry().breakers["google_sheets"]
    assert breaker.state == "closed", "a rate limit is not a dependency failure"
