"""One pass through the whole flow: paste -> points -> transfer -> the Sheets page shows the rows.

This is the README's walkthrough, run against the fakes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import workbook_by_name

NOTES = """**Vendor call with Madhu**

The Next Steps
Ansul S: Send the Sprinto questionnaire by Friday
Prathyush Kodhanpur: Mirror Open Food Facts before 3 Oct
Decided: the Owner column holds a person, not a team
Risk: the upload flag has no rollback plan
"""


def test_quick_paste_to_sheet_rows(client: TestClient) -> None:
    # 1. Paste with nothing selected: a manual meeting appears, titled from the first line.
    quick = client.post("/notes/quick", json={"text": NOTES}).json()
    meeting_id = quick["meeting"]["id"]
    assert quick["meeting"]["title"] == "Vendor call with Madhu"

    # 2. Extract.
    extracted = client.post(f"/meetings/{meeting_id}/extract").json()
    assert extracted["extraction"]["created_points"] >= 4
    points = client.get("/points", params={"meeting_id": meeting_id}).json()
    kinds = {p["kind"] for p in points}
    assert {"action", "decision", "risk"} <= kinds

    ansul = next(p for p in points if p["owner_text"] == "Ansul S")
    assert ansul["due_text"] == "by Friday"
    assert ansul["due_date"] is not None

    # 3. Defer one, keep the rest.
    client.post(f"/points/{points[-1]['id']}/defer")
    active = client.get("/points", params={"meeting_id": meeting_id}).json()
    assert len(active) == len(points) - 1

    # 4. Transfer the actions to the roadmap.
    workbook = workbook_by_name(client, "Nutrition Sialet Product Roadmap")
    tab = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    actions = [p["id"] for p in active if p["kind"] == "action"]
    preview = client.post(
        "/transfers/preview",
        json={"workbook_id": workbook["id"], "sheet_id": "t1", "mode": "append", "point_ids": actions},
    ).json()
    assert preview["plan"]["insert_at"] == 16

    written = client.post(
        "/transfers/execute",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "mode": "append",
            "point_ids": actions,
            "region_hash": tab["region_hash"],
        },
    )
    assert written.status_code == 200, written.text

    # 5. The Sheets page shows the rows, keyed and linked back to the meeting.
    after = client.get(f"/workbooks/{workbook['id']}/tabs/t1").json()
    assert after["values"][16][0] == "T-108"
    assert after["values"][16][7].startswith("Vendor call with Madhu")
    assert after["layout"]["last_table_row"] == 15 + len(actions)

    # 6. The points are gone from the tool but the log keeps them.
    remaining = [p["id"] for p in client.get("/points", params={"meeting_id": meeting_id}).json()]
    assert not set(actions) & set(remaining)
    log = client.get("/transfers", params={"workbook_id": workbook["id"]}).json()
    assert len(log) == len(actions)

    # 7. Add a row inside the table from the deferred point.
    deferred = client.get("/points", params={"meeting_id": meeting_id, "lifecycle": "deferred"}).json()[0]
    added = client.post(
        "/sheets/add-row",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "region_hash": after["region_hash"],
            "point_id": deferred["id"],
            "position": {"mode": "above", "row": 10},
        },
    )
    assert added.status_code == 200
    assert added.json()["tab"]["values"][10][1] == deferred["text"]

    # 8. Edit a cell on the Sheets page.
    grid = added.json()["tab"]
    saved = client.post(
        "/sheets/save",
        json={
            "workbook_id": workbook["id"],
            "sheet_id": "t1",
            "edits": [{"cell": "G11", "before": grid["values"][10][6], "after": "in progress"}],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["tab"]["values"][10][6] == "in progress"

    # 9. Everything is in the activity log, attributed.
    activity = client.get("/admin/activity").json()
    assert any("Transferred" in a["text"] for a in activity)
    assert any("Added a row" in a["text"] for a in activity)
    assert all(a["actor"] for a in activity)
