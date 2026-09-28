"""Step 4: preview, the re-read guard, the one batch write, and undo."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import connect_fixture_workbook, meeting_by_title, workbook_by_name


def _tab(client: TestClient, workbook_id: str, sheet_id: str) -> dict:
    return client.get(f"/workbooks/{workbook_id}/tabs/{sheet_id}").json()


def _points(client: TestClient, n: int = 2) -> list[str]:
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    return [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()[:n]]


def test_append_preview_plans_rows_after_the_table(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    point_ids = _points(client, 2)
    response = client.post(
        "/transfers/preview",
        json={"workbook_id": workbook["id"], "sheet_id": "t1", "mode": "append", "point_ids": point_ids},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["mode"] == "append"
    assert body["plan"]["insert_at"] == 16  # directly after T-107, above the stray note
    assert body["plan"]["keys"] == ["T-108", "T-109"]
    assert body["plan"]["cells"][:4] == ["A17", "B17", "C17", "D17"]
    assert [p["row"] for p in body["per_point"]] == [16, 17]
    assert len(body["region_hash"]) == 64


def test_append_writes_one_batch_and_records_the_transfer(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    point_ids = _points(client, 2)
    tab = _tab(client, workbook["id"], "t1")
    google = client.app.state.google
    google.calls.clear()

    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["transfers"]) == 2
    assert body["transfers"][0]["cells"][0] == "A17"
    assert body["undo_until"]

    # Exactly one batchUpdate for the whole transfer.
    assert len([c for c in google.calls if c.startswith("sheets.batchUpdate")]) == 1

    after = _tab(client, workbook["id"], "t1")
    assert after["values"][16][0] == "T-108"
    assert after["values"][16][1] == "Review dataset for weight information"
    assert after["values"][16][2] == "Anushka Mohanty"


def test_transferred_points_are_removed_from_the_tool(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    point_ids = _points(client, 2)
    tab = _tab(client, workbook["id"], "t1")

    client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": tab["region_hash"],
        },
    )
    remaining = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]
    assert not set(point_ids) & set(remaining)
    assert len(remaining) == 4
    # the transfer log keeps the text and the cells
    log = client.get("/transfers", params={"workbook_id": workbook["id"]}).json()
    assert len(log) == 2
    assert log[0]["snapshot"]["point"]["id"] in point_ids
    # and the meeting's own history is the same two lines, asked for by meeting
    mine = client.get("/transfers", params={"meeting_id": meeting_id}).json()
    assert [t["id"] for t in mine] == [t["id"] for t in log]


def test_a_changed_tab_between_preview_and_write_gives_409_with_the_fresh_grid(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    point_ids = _points(client, 1)
    stale = _tab(client, workbook["id"], "t1")["region_hash"]

    # Somebody edits the tab in Google Sheets.
    google = client.app.state.google
    google.spreadsheets[workbook["spreadsheet_id"]].tab("t1").set_cell(9, 2, "Someone Else")

    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": stale,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["expected_region_hash"] == stale
    assert detail["region_hash"] != stale
    assert detail["plan"]["mode"] == "append"  # the plan was rebuilt
    assert detail["tab"]["values"][9][2] == "Someone Else"
    # nothing was written
    assert len(client.get("/transfers").json()) == 0


def test_keys_are_allocated_after_the_re_read(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    point_ids = _points(client, 1)
    tab = _tab(client, workbook["id"], "t1")

    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": tab["region_hash"],
        },
    )
    assert response.json()["tab"]["values"][16][0] == "T-108"


def test_status_is_mapped_to_the_columns_dropdown_and_unmapped_is_flagged(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]

    # "in progress" is in the P1 tab's dropdown, so it is written as the sheet spells it.
    in_progress = next(
        p
        for p in client.get("/points", params={"meeting_id": meeting_id}).json()
        if p["status"] == "in_progress"
    )
    mapped = client.post(
        "/transfers/preview",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": [in_progress["id"]],
        },
    ).json()
    assert mapped["plan"]["unmapped"] == []
    assert next(w for w in mapped["plan"]["writes"] if w["ref"] == "G17")["value"] == "in progress"

    # The Decisions tab allows only decided/open/superseded, so a blocked point's status stays blank.
    blocked = client.post(
        "/points", json={"meeting_id": meeting_id, "text": "Mirror Open Food Facts", "status": "blocked"}
    ).json()
    preview = client.post(
        "/transfers/preview",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t3",
            "mode": "append",
            "point_ids": [blocked["id"]],
        },
    ).json()
    assert preview["plan"]["unmapped"] == [blocked["id"]]
    assert not [c for c in preview["plan"]["cells"] if c.startswith("F")]
    assert any("dropdown" in w for w in preview["warnings"])


def test_the_notes_column_carries_the_meeting_title_and_date(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    preview = client.post(
        "/transfers/preview",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": _points(client, 1),
        },
    ).json()
    notes_cell = next(w for w in preview["plan"]["writes"] if w["ref"] == "H17")
    assert notes_cell["value"] == "Nutrition roadmap review · 19 Sep"


def test_custom_fill_with_skip_leaves_existing_cells_alone(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    point_ids = _points(client, 2)
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "fill",
            "point_ids": point_ids,
            "anchor": {"r": 10, "c": 1},
            "conflict": "skip",
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 200
    after = response.json()["tab"]["values"]
    assert after[10][1] == tab["values"][10][1]  # the existing task survived


def test_custom_fill_with_overwrite_records_the_previous_values(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    before = tab["values"][10][1]
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "fill",
            "point_ids": _points(client, 1),
            "anchor": {"r": 10, "c": 1},
            "conflict": "overwrite",
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 200
    transfer = response.json()["transfers"][0]
    assert transfer["previous"]["B11"] == before
    assert response.json()["tab"]["values"][10][1] != before


def test_an_anchor_in_the_header_is_blocked(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    response = client.post(
        "/transfers/preview",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "fill",
            "point_ids": _points(client, 1),
            "anchor": {"r": 8, "c": 1},
        },
    )
    assert response.status_code == 409
    assert "header" in response.json()["detail"]


def test_a_protected_range_names_the_protection_and_its_owner(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t4")  # Risks is protected in the fake
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t4",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 403
    assert "protected" in response.json()["detail"]
    assert "ansul.s@simpleo.ai" in response.json()["detail"]


def test_a_read_only_workbook_cannot_be_written_to(client: TestClient) -> None:
    connected = client.post(
        "/workbooks/connect", json={"url": "https://docs.google.com/spreadsheets/d/boardmetrics"}
    ).json()
    tab = _tab(client, connected["id"], "b1")
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": connected["id"],
            "sheet_id": "b1",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 409
    assert "No admin connection can edit" in response.json()["detail"]


def test_transferring_the_same_text_twice_needs_an_explicit_choice(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    point = client.get("/points", params={"meeting_id": meeting_id}).json()[0]
    tab = _tab(client, workbook["id"], "t1")
    client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": [point["id"]],
            "region_hash": tab["region_hash"],
        },
    )
    again = client.post(
        "/points", json={"meeting_id": meeting_id, "text": point["text"], "kind": point["kind"]}
    ).json()
    tab = _tab(client, workbook["id"], "t1")
    payload = {
        "workbook_id": workbook["id"],
        "sheet_id": "t1",
        "mode": "append",
        "point_ids": [again["id"]],
        "region_hash": tab["region_hash"],
    }
    refused = client.post("/transfers/execute", json=payload)
    assert refused.status_code == 409
    assert refused.json()["detail"]["point_ids"] == [again["id"]]

    allowed = client.post("/transfers/execute", json={**payload, "allow_repeat": True})
    assert allowed.status_code == 200


def test_formula_columns_are_never_written_and_are_copied_down(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    tab = _tab(client, workbook["id"], "formula_col")
    assert tab["formula_cols"] == [4, 5]
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "formula_col",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    )
    assert response.status_code == 200
    assert not [c for c in response.json()["cells"] if c.startswith(("E", "F"))]
    formulas = client.app.state.google.spreadsheets["plannerfixtures"].tab("formula_col").formulas
    assert formulas[3][4].startswith("=DATEDIF")  # copied down from the row above
    assert "D4" in formulas[3][4]


def test_date_columns_are_written_as_dates(client: TestClient) -> None:
    workbook = connect_fixture_workbook(client)
    tab = _tab(client, workbook["id"], "date_col")
    client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "date_col",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    )
    formats = client.app.state.google.spreadsheets["plannerfixtures"].tab("date_col").number_formats
    assert formats[3][3] == "DATE"


def test_undo_removes_inserted_rows_and_brings_the_points_back(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    point_ids = _points(client, 2)
    tab = _tab(client, workbook["id"], "t1")
    rows_before = len(tab["values"])

    batch = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": point_ids,
            "region_hash": tab["region_hash"],
        },
    ).json()["batch_id"]

    undone = client.post(f"/transfers/{batch}/undo")
    assert undone.status_code == 200
    assert len(undone.json()["tab"]["values"]) == rows_before
    assert sorted(p["id"] for p in undone.json()["restored_points"]) == sorted(point_ids)
    back = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]
    assert set(point_ids) <= set(back)
    assert client.post(f"/transfers/{batch}/undo").status_code == 409


def test_undo_refuses_when_the_rows_were_touched_since(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    batch = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    ).json()["batch_id"]

    client.app.state.google.spreadsheets[workbook["spreadsheet_id"]].tab("t1").set_cell(
        16, 1, "edited by hand"
    )
    response = client.post(f"/transfers/{batch}/undo")
    assert response.status_code == 409
    assert response.json()["detail"]["changed"]["B17"] == "edited by hand"


def test_undo_expires_after_ten_minutes(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    batch = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    ).json()["batch_id"]

    client.app.state.clock.advance(minutes=11)
    response = client.post(f"/transfers/{batch}/undo")
    assert response.status_code == 409
    assert "10 minutes" in response.json()["detail"]


def test_a_transfer_with_no_points_is_refused(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    response = client.post(
        "/transfers/preview",
        json={"workbook_id": workbook["id"], "sheet_id": "t1", "mode": "append", "point_ids": []},
    )
    assert response.status_code == 422


def test_the_meeting_step_becomes_done_when_the_last_point_leaves(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    meeting_id = meeting_by_title(client, "Nutrition roadmap review")["id"]
    all_ids = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]
    tab = _tab(client, workbook["id"], "t1")
    response = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": all_ids,
            "region_hash": tab["region_hash"],
            "allow_repeat": True,
        },
    )
    assert response.status_code == 200
    assert client.get(f"/meetings/{meeting_id}").json()["step"] == "done"


def test_the_log_says_which_lines_can_still_be_undone(client: TestClient) -> None:
    """Screen review R1-20: the Sheets page offers Undo on the recent-transfer lines, which needs the
    server's word on the ten-minute window - the toast that carried Undo is gone after ten seconds."""
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    batch = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    ).json()["batch_id"]

    log = client.get("/transfers", params={"workbook_id": workbook["id"]}).json()
    assert [(t["batch_id"], t["can_undo"]) for t in log] == [(batch, True)]

    client.app.state.clock.advance(minutes=11)
    log = client.get("/transfers", params={"workbook_id": workbook["id"]}).json()
    assert log[0]["can_undo"] is False


def test_an_undone_transfer_cannot_be_undone_again_from_the_log(client: TestClient) -> None:
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = _tab(client, workbook["id"], "t1")
    batch = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": _points(client, 1),
            "region_hash": tab["region_hash"],
        },
    ).json()["batch_id"]
    assert client.post(f"/transfers/{batch}/undo").status_code == 200

    log = client.get("/transfers", params={"workbook_id": workbook["id"]}).json()
    assert log[0]["undone_at"]
    assert log[0]["can_undo"] is False


def test_the_preview_counts_in_words_not_with_brackets(client: TestClient) -> None:
    """Screen review R3-01: "11 cell(s) already have content" and "1 point(s)" on screen."""
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    one = _points(client, 1)
    fill = client.post(
        "/transfers/preview",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "fill",
            "point_ids": one,
            "anchor": {"r": 14, "c": 1},
            "conflict": "skip",
        },
    ).json()
    warning = next(w for w in fill["warnings"] if "content" in w)
    assert "(s)" not in warning
    assert warning.endswith("cells already have content.") or warning == "1 cell already has content."

    tab = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": one,
            "region_hash": tab["region_hash"],
        },
    )
    activity = client.get("/admin/activity").json()
    assert activity[0]["text"].startswith("Transferred 1 point to ")
