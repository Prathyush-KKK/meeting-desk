"""The workbook registry and the live tab read."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import connect_fixture_workbook, workbook_by_name


def test_seeded_workbooks_are_listed_with_their_tabs(client: TestClient) -> None:
    workbooks = client.get("/workbooks").json()
    names = [w["name"] for w in workbooks]
    assert "Mobile App Product Roadmap" in names
    roadmap = workbook_by_name(client, "Mobile App Product Roadmap")
    assert [t["title"] for t in roadmap["tabs"]][:2] == ["P1 Resolve & Log", "P4 Regional & AI"]
    assert roadmap["can_edit"] is True


def test_connect_by_url_picks_the_first_admin_connection_that_can_edit(client: TestClient) -> None:
    response = client.post(
        "/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/rewards"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Rewards - Earn Points"
    assert body["can_edit"] is True
    # Only the second admin account can edit it, so that is the one that was chosen.
    connections = {c["id"]: c["email"] for c in client.get("/admin/connections").json()["connections"]}
    assert connections[body["connection_id"]] == "alex.s@example.com"


def test_a_workbook_no_connection_can_edit_is_saved_read_only(client: TestClient) -> None:
    response = client.post(
        "/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/boardmetrics"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["can_edit"] is False
    assert body["connection_id"] is None
    assert "daniel.okafor@example.com" in body["needs_edit_access_from"]
    assert "give edit access" in body["share_request"]


def test_a_member_may_connect_a_workbook(member_client: TestClient) -> None:
    body = connect_fixture_workbook(member_client)
    assert body["connected_by"] == "noah.s@example.com"
    assert body["can_edit"] is True


def test_a_workbook_no_admin_can_open_is_refused_with_the_accounts_named(client: TestClient) -> None:
    client.app.state.google.add_spreadsheet(
        spreadsheet_id="secretbook",
        name="Someone else's book",
        url="https://docs.google.com/spreadsheets/d/secretbook",
        tabs=[{"sheet_id": "s1", "title": "Sheet1", "rows": [["ID", "Task"]]}],
        editors=[],
        readers=[],
    )
    response = client.post(
        "/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/secretbook"}
    )
    assert response.status_code == 409
    assert "daniel.okafor@example.com" in response.json()["detail"]


def test_a_bad_url_is_rejected(client: TestClient) -> None:
    assert client.post("/workbooks/connect", json={"url": "not a link at all"}).status_code == 422


def test_reconnecting_updates_in_place(client: TestClient) -> None:
    first = client.post("/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/rewards"})
    second = client.post("/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/rewards"})
    assert first.json()["id"] == second.json()["id"]
    assert len([w for w in client.get("/workbooks").json() if w["spreadsheet_id"] == "rewards"]) == 1


def test_disconnect_removes_it_from_the_registry(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Rewards - Earn Points")
    assert client.delete(f"/workbooks/{workbook['id']}").json()["ok"] is True
    assert "Rewards - Earn Points" not in [w["name"] for w in client.get("/workbooks").json()]


def test_tab_read_returns_values_layout_dropdowns_and_a_region_hash(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Mobile App Product Roadmap")
    response = client.get(f"/workbooks/{workbook['id']}/tabs/t1")
    assert response.status_code == 200
    tab = response.json()
    assert tab["title"] == "P1 Resolve & Log"
    assert tab["layout"]["header_row"] == 8
    assert tab["layout"]["key_prefix"] == "T"
    assert tab["layout"]["last_table_row"] == 15
    assert tab["dropdowns"]["6"] == ["open", "in progress", "blocked", "done", "dropped"]
    assert len(tab["region_hash"]) == 64
    assert tab["can_edit"] is True
    assert tab["read_at"]


def test_tab_read_reports_formula_and_date_columns(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    formula = client.get(f"/workbooks/{workbook['id']}/tabs/formula_col").json()
    assert formula["formula_cols"] == [4, 5]
    dates = client.get(f"/workbooks/{workbook['id']}/tabs/date_col").json()
    assert dates["date_cols"] == [3]


def test_the_layout_is_remembered_between_reads(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Mobile App Product Roadmap")
    first = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    second = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    assert first["region_hash"] == second["region_hash"]


def test_an_unknown_tab_is_an_error(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Mobile App Product Roadmap")
    assert client.get(f"/workbooks/{workbook['id']}/tabs/nope").status_code in (404, 500, 502)
