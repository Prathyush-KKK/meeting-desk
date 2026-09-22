"""The Sheets page: in-place edits with the pre-save re-read, and Add row."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import connect_fixture_workbook, meeting_by_title, workbook_by_name


def _tab(client: TestClient, workbook_id: str, sheet_id: str) -> dict:
    return client.get(f"/workbooks/{workbook_id}/tabs/{sheet_id}").json()


def _roadmap(client: TestClient) -> dict:
    return workbook_by_name(client, "Nutrition Sialet Product Roadmap")


# --- edits ----------------------------------------------------------------------------------------


def test_saving_one_cell_writes_it_and_logs_the_edit(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    before = tab["values"][13][6]  # T-105 Status

    response = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "edits": [{"cell": "G14", "before": before, "after": "in progress"}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["tab"]["values"][13][6] == "in progress"
    edits = client.get("/sheets/edits", params={"workbook_id": workbook["id"]}).json()
    assert edits[0]["cell"] == "G14"
    assert edits[0]["before"] == before
    assert edits[0]["after"] == "in progress"
    assert edits[0]["actor"] == "prathyush.kodhanpur@simpleo.ai"


def test_several_cells_go_in_one_batch(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    google = client.app.state.google
    google.calls.clear()
    response = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "edits": [
                {"cell": "C14", "before": tab["values"][13][2], "after": "Nishchay S"},
                {"cell": "D14", "before": tab["values"][13][3], "after": "30 Sep"},
            ],
        },
    )
    assert response.status_code == 200
    assert len([c for c in google.calls if c.startswith("sheets.batchUpdate")]) == 1
    assert {e["cell"] for e in response.json()["edits"]} == {"C14", "D14"}


def test_a_cell_changed_in_google_sheets_stops_the_save_and_shows_both(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    shown = tab["values"][13][6]

    client.app.state.google.spreadsheets[workbook["spreadsheet_id"]].tab("t1").set_cell(13, 6, "done")

    response = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "edits": [{"cell": "G14", "before": shown, "after": "blocked"}],
        },
    )
    assert response.status_code == 409
    clash = response.json()["detail"]["clashes"][0]
    assert clash == {"cell": "G14", "yours": "blocked", "theirs": "done", "was": shown}
    # nothing was written
    assert _tab(client, workbook["id"], "t1")["values"][13][6] == "done"
    assert client.get("/sheets/edits").json() == []


def test_formula_and_key_cells_are_not_editable(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    formula = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "formula_col",
            "edits": [{"cell": "E2", "before": "18", "after": "99"}],
        },
    )
    assert formula.status_code == 409
    assert "formula column" in formula.json()["detail"]

    key = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "formula_col",
            "edits": [{"cell": "A2", "before": "T-301", "after": "T-999"}],
        },
    )
    assert key.status_code == 409
    assert "key column" in key.json()["detail"]


def test_an_empty_save_is_refused(client: TestClient) -> None:
    workbook = _roadmap(client)
    response = client.post(
        "/sheets/save", json={"workbook_id": workbook["id"], "sheet_id": "t1", "edits": []}
    )
    assert response.status_code == 422


def test_saving_into_a_read_only_workbook_is_refused(client: TestClient) -> None:
    connected = client.post(
        "/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/boardmetrics"}
    ).json()
    response = client.post(
        "/sheets/save",
        json={
            "workbook_id": connected["id"],
            "sheet_id": "b1",
            "edits": [{"cell": "E2", "before": "open", "after": "done"}],
        },
    )
    assert response.status_code == 409


# --- add row --------------------------------------------------------------------------------------


def test_add_row_from_a_form_lands_after_the_table(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "values": {"Task": "Write the transfer runbook", "Owner": "Nishchay S", "Status": "open"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insert_at"] == 16
    assert body["keys"] == ["T-108"]
    values = body["tab"]["values"]
    assert values[16][0] == "T-108"
    assert values[16][1] == "Write the transfer runbook"
    assert values[16][6] == "open"
    # the stray note below the table was pushed down, not overwritten
    assert values[18][7] == "check dropdown on Status"


def test_add_row_above_a_clicked_row_lands_inside_the_section(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    was_at_11 = tab["values"][11]
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "values": {"Task": "Menu scan accuracy spike"},
            "position": {"mode": "above", "row": 11},
        },
    )
    assert response.status_code == 200
    values = response.json()["tab"]["values"]
    assert values[11][1] == "Menu scan accuracy spike"
    assert values[12] == was_at_11
    assert len(values) == len(tab["values"]) + 1


def test_add_row_above_the_header_is_refused(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "values": {"Task": "nope"},
            "position": {"mode": "above", "row": 3},
        },
    )
    assert response.status_code == 409
    assert "header" in response.json()["detail"]


def test_add_row_from_a_point_transfers_it(client: TestClient) -> None:
    workbook = _roadmap(client)
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    point = client.get("/points", params={"meeting_id": meeting_id}).json()[0]
    tab = _tab(client, workbook["id"], "t1")

    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "point_id": point["id"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transfer"]["mode"] == "add_row"
    assert body["transfer"]["point_text"] == point["text"]
    assert body["tab"]["values"][16][1] == point["text"]
    remaining = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]
    assert point["id"] not in remaining


def test_a_deferred_point_can_be_added_as_a_row(client: TestClient) -> None:
    workbook = _roadmap(client)
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    point = client.get("/points", params={"meeting_id": meeting_id}).json()[0]
    client.post(f"/points/{point['id']}/defer")
    tab = _tab(client, workbook["id"], "t1")

    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "point_id": point["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["tab"]["values"][16][1] == point["text"]


def test_add_row_uses_the_stale_hash_guard(client: TestClient) -> None:
    workbook = _roadmap(client)
    stale = _tab(client, workbook["id"], "t1")["region_hash"]
    client.app.state.google.spreadsheets[workbook["spreadsheet_id"]].tab("t1").set_cell(9, 1, "moved")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": stale,
            "values": {"Task": "nope"},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["tab"]["values"][9][1] == "moved"


def test_add_row_rejects_a_header_it_does_not_know(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": tab["region_hash"],
            "values": {"Sprint": "24"},
        },
    )
    assert response.status_code == 422
    assert "Sprint" in response.json()["detail"]


def test_add_row_copies_formulas_and_skips_formula_columns(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    tab = _tab(client, workbook["id"], "formula_col")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "formula_col",
            "region_hash": tab["region_hash"],
            "values": {"Task": "Mirror Open Food Facts", "Owner": "Prathyush Kodhanpur"},
            "position": {"mode": "above", "row": 2},
        },
    )
    assert response.status_code == 200
    assert not [c for c in response.json()["cells"] if c.startswith(("E", "F"))]
    formulas = client.app.state.google.spreadsheets["plannerfixtures"].tab("formula_col").formulas
    assert formulas[2][4].startswith("=DATEDIF")


def test_add_row_on_a_task_keyed_tab_needs_no_key(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    tab = _tab(client, workbook["id"], "task_keyed_no_id")
    response = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "task_keyed_no_id",
            "region_hash": tab["region_hash"],
            "values": {"Task": "Refer a friend", "Points": "150", "Status": "planned"},
        },
    )
    assert response.status_code == 200
    assert response.json()["keys"] == [""]
    assert response.json()["cells"] == ["A5", "B5", "D5"]


def test_add_row_with_nothing_to_write_is_refused(client: TestClient) -> None:
    workbook = _roadmap(client)
    tab = _tab(client, workbook["id"], "t1")
    response = client.post(
        "/sheets/add-row",
        json={"workbook_id": workbook["id"], "sheet_id": "t1", "region_hash": tab["region_hash"]},
    )
    assert response.status_code == 422
