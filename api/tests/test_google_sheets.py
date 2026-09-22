"""Sheets contract tests: the five-call read, the one batchUpdate, dates, protection, retries."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.google.interface import (
    CopyFormula,
    DeleteRows,
    InsertRows,
    NotFoundError,
    PermissionDenied,
    RateLimited,
    SetCell,
)
from app.google.sheets import RealSheetsClient, a1_range, build_requests, cell_data, quote_title
from app.sheets.dates import parse_date, serial_for, serial_from_date
from app.sheets.layout import detect_date_cols, detect_formula_cols, detect_layout
from tests.google_mock import MockGoogleApi, json_response

IST = ZoneInfo("Asia/Kolkata")
ME = "prathyush.kodhanpur@simpleo.ai"
BOOK = "1RoadmapSpreadsheetId0000000000000000000000"
NOW = datetime(2026, 9, 22, 17, 2, tzinfo=IST)


def _values_router(request: httpx.Request) -> httpx.Response:
    """Answer ``values:batchGet`` by the range asked for, the way one tab reads."""
    params = MockGoogleApi.params(request)
    ranges = params.get("ranges", [])
    render = params.get("valueRenderOption", [""])[0]
    if render == "FORMULA":
        return json_response("sheets_values_formulas.json")
    if ranges == ["'P1 Resolve & Log'!1:40"]:
        return json_response("sheets_values_window.json")
    if ranges == ["'P1 Resolve & Log'!A41:H1000"]:
        return json_response("sheets_values_region_empty.json")
    if ranges == ["Lists!$A$2:$A$5"]:
        return json_response("sheets_values_lists_range.json")
    if ranges == ["'P1 Resolve & Log'!E4", "'P1 Resolve & Log'!H5"]:
        return json_response("sheets_values_cells.json")
    return httpx.Response(500, json={"error": {"message": f"unscripted ranges {ranges}"}})


def _meta_router(request: httpx.Request) -> httpx.Response:
    params = MockGoogleApi.params(request)
    if params.get("includeGridData") == ["true"]:
        return json_response("sheets_grid_data.json")
    if "protectedRanges" in params.get("fields", [""])[0]:
        return json_response("sheets_protected_ranges.json")
    return json_response("sheets_spreadsheet_get.json")


def _api() -> MockGoogleApi:
    return (
        MockGoogleApi()
        .on("GET", f"/spreadsheets/{BOOK}/values:batchGet", _values_router)
        .on("GET", f"/spreadsheets/{BOOK}", _meta_router)
        .on("POST", f"/spreadsheets/{BOOK}:batchUpdate", "sheets_batch_update_ok.json")
        .on("GET", f"/drive/v3/files/{BOOK}", "drive_file_get_can_edit.json")
    )


def _client(api: MockGoogleApi, **kw) -> RealSheetsClient:
    return RealSheetsClient(api.http(**kw), display_tz="Asia/Kolkata", wall_clock=lambda: NOW)


# --- metadata ---------------------------------------------------------------------------------------


def test_spreadsheets_get_carries_titles_sheet_ids_and_grid_properties_with_a_fields_mask() -> None:
    api = _api()
    meta = _client(api).get_spreadsheet(ME, BOOK)
    params = MockGoogleApi.params(api.requests[0])
    assert params["fields"] == [
        "spreadsheetId,properties.title,spreadsheetUrl,sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)))"
    ]
    assert meta.title == "Nutrition Sialet Product Roadmap"
    assert meta.url.endswith("/edit")
    assert [(t.sheet_id, t.title, t.index) for t in meta.tabs] == [
        ("0", "P1 Resolve & Log", 0),
        ("1487211930", "Decisions", 1),
        ("22", "Tiny", 2),
    ]


def test_metadata_is_cached_per_connection_and_dropped_after_a_write() -> None:
    api = _api()
    client = _client(api)
    client.get_spreadsheet(ME, BOOK)
    client.get_spreadsheet(ME, BOOK)
    assert len(api.sent("GET", f"/spreadsheets/{BOOK}")) == 1
    client.batch_update(ME, BOOK, [SetCell("0", 5, 1, "x")])
    client.get_spreadsheet(ME, BOOK)
    assert len(api.sent("GET", f"/spreadsheets/{BOOK}")) == 2


def test_can_edit_goes_through_drive_capabilities() -> None:
    api = _api()
    assert _client(api).can_edit(ME, BOOK) is True
    assert MockGoogleApi.params(api.requests[0])["fields"] == ["name,capabilities/canEdit"]


def test_an_unknown_tab_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        _client(_api()).read_tab(ME, BOOK, "999")


# --- the read ---------------------------------------------------------------------------------------


def test_read_tab_is_five_calls_each_limited_to_what_the_layout_needs() -> None:
    api = _api()
    read = _client(api).read_tab(ME, BOOK, "0")

    calls = [(r.method, r.url.path, MockGoogleApi.params(r)) for r in api.requests]
    assert calls[0][1] == f"/v4/spreadsheets/{BOOK}"  # 1. metadata
    assert calls[1][2]["ranges"] == ["'P1 Resolve & Log'!1:40"]  # 2. the detection window
    assert calls[2][2]["ranges"] == [
        "'P1 Resolve & Log'!A41:H1000"
    ]  # 3. the region below, header columns only
    assert calls[3][2]["ranges"] == ["'P1 Resolve & Log'!A4:H1000"]  # 4. formulas over the table region
    assert calls[3][2]["valueRenderOption"] == ["FORMULA"]
    assert calls[4][2]["includeGridData"] == ["true"]  # 5. header row + first data row only
    assert calls[4][2]["ranges"] == ["'P1 Resolve & Log'!A3:H4"]
    assert calls[4][2]["fields"] == [
        "sheets(data(rowData(values(effectiveFormat.numberFormat.type,dataValidation))))"
    ]
    assert calls[5][2]["ranges"] == ["Lists!$A$2:$A$5"]  # the ONE_OF_RANGE dropdown source
    assert len(calls) == 6

    assert read.sheet_id == "0"
    assert read.title == "P1 Resolve & Log"
    assert read.read_at == NOW
    assert read.values[2] == ["ID", "Task", "Owner", "Due", "Status", "Priority", "Days left", "Notes"]
    assert read.values[3][0] == "T-101"
    assert read.values[7][7] == "Note: keep P0 items at the top"
    assert read.formulas[3][6] == "=D4-TODAY()"
    assert read.formulas[3][3] == "46298"  # FORMULA render gives the date as its serial
    assert read.number_formats[3][3] == "DATE"
    assert read.number_formats[3][6] == "NUMBER"
    assert read.dropdowns == {
        4: ["Open", "In progress", "Blocked", "Done", "Dropped"],
        5: ["P0", "P1", "P2", "P3"],
    }


def test_the_layout_code_finds_the_formula_and_date_columns_from_the_read() -> None:
    read = _client(_api()).read_tab(ME, BOOK, "0")
    provisional = detect_layout(read.values)
    assert provisional.header_row == 2
    formula_cols = detect_formula_cols(read.formulas, header_row=provisional.header_row)
    date_cols = detect_date_cols(read.number_formats, header_row=provisional.header_row)
    assert formula_cols == [6]
    assert date_cols == [3]
    layout = detect_layout(read.values, formula_cols=formula_cols, date_cols=date_cols)
    assert layout.last_table_row == 5  # the stray note below the table is not the table
    assert layout.key_prefix == "T"


def test_a_small_tab_skips_the_region_read() -> None:
    def small_values(request: httpx.Request) -> httpx.Response:
        params = MockGoogleApi.params(request)
        if params.get("valueRenderOption") == ["FORMULA"]:
            return json_response({"valueRanges": [{"values": [["T-1", "a"]]}]})
        assert params["ranges"] == ["'Tiny'!1:40"]
        return json_response({"valueRanges": [{"values": [["ID", "Task"], ["T-1", "a"]]}]})

    api = (
        MockGoogleApi()
        .on("GET", f"/spreadsheets/{BOOK}/values:batchGet", small_values)
        .on("GET", f"/spreadsheets/{BOOK}", _meta_router)
    )
    read = _client(api).read_tab(ME, BOOK, "22")
    ranges = [MockGoogleApi.params(r).get("ranges") for r in api.sent("GET", "values:batchGet")]
    assert ranges == [["'Tiny'!1:40"], ["'Tiny'!A2:B30"]]
    assert read.values == [["ID", "Task"], ["T-1", "a"]]


def test_read_cells_asks_for_each_ref_and_returns_blank_for_empty_cells() -> None:
    api = _api()
    cells = _client(api).read_cells(ME, BOOK, "0", ["E4", "H5"])
    assert cells == {"E4": "In progress", "H5": ""}
    assert _client(api).read_cells(ME, BOOK, "0", []) == {}


# --- the write --------------------------------------------------------------------------------------


def test_build_requests_composes_insert_copy_paste_and_grouped_update_cells() -> None:
    ops = [
        InsertRows("0", at=6, count=2),
        CopyFormula("0", col=6, source_row=5, target_rows=[6, 7]),
        SetCell("0", 6, 0, "T-104"),
        SetCell("0", 6, 1, "Ship the flag"),
        SetCell("0", 6, 3, "2026-10-03", as_date=True),
        SetCell("0", 7, 1, "Second row"),
        DeleteRows("0", at=9, count=1),
    ]
    requests = build_requests(ops, 0, base=NOW)
    assert requests[0] == {
        "insertDimension": {
            "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 6, "endIndex": 8},
            "inheritFromBefore": True,
        }
    }
    assert requests[1] == {
        "copyPaste": {
            "source": {
                "sheetId": 0,
                "startRowIndex": 5,
                "endRowIndex": 6,
                "startColumnIndex": 6,
                "endColumnIndex": 7,
            },
            "destination": {
                "sheetId": 0,
                "startRowIndex": 6,
                "endRowIndex": 8,
                "startColumnIndex": 6,
                "endColumnIndex": 7,
            },
            "pasteType": "PASTE_FORMULA",
            "pasteOrientation": "NORMAL",
        }
    }
    # A6:B6 are adjacent and collapse into one updateCells; D6 is its own; B7 its own.
    assert requests[2] == {
        "updateCells": {
            "start": {"sheetId": 0, "rowIndex": 6, "columnIndex": 0},
            "rows": [
                {
                    "values": [
                        {"userEnteredValue": {"stringValue": "T-104"}},
                        {"userEnteredValue": {"stringValue": "Ship the flag"}},
                    ]
                }
            ],
            "fields": "userEnteredValue",
        }
    }
    assert requests[3]["updateCells"]["rows"] == [{"values": [{"userEnteredValue": {"numberValue": 46298}}]}]
    assert requests[4]["updateCells"]["start"] == {"sheetId": 0, "rowIndex": 7, "columnIndex": 1}
    assert requests[5] == {
        "deleteDimension": {"range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 9, "endIndex": 10}}
    }


def test_an_insert_at_the_top_cannot_inherit_from_before() -> None:
    (request,) = build_requests([InsertRows("0", at=0, count=1)], 0)
    assert request["insertDimension"]["inheritFromBefore"] is False


def test_values_are_strings_dates_are_serials_and_blank_clears() -> None:
    assert cell_data("3", as_date=False) == {"userEnteredValue": {"stringValue": "3"}}
    assert cell_data("TRUE", as_date=False) == {"userEnteredValue": {"stringValue": "TRUE"}}
    assert cell_data("", as_date=True) == {}
    assert cell_data("2026-10-03", as_date=True) == {"userEnteredValue": {"numberValue": 46298}}
    assert cell_data("by 3 Oct", as_date=True, base=NOW) == {"userEnteredValue": {"numberValue": 46298}}
    # A date column with a value that is not a date is written as text, per the spec.
    assert cell_data("when the clinician is free", as_date=True, base=NOW) == {
        "userEnteredValue": {"stringValue": "when the clinician is free"}
    }


def test_sheet_serials_round_trip() -> None:
    assert serial_from_date(datetime(1899, 12, 30).date()) == 0
    assert serial_from_date(datetime(2026, 10, 3).date()) == 46298
    assert parse_date("2026-10-03").isoformat() == "2026-10-03"
    assert parse_date("next Monday", NOW).isoformat() == "2026-09-28"
    assert parse_date("garbage", NOW) is None
    assert serial_for("", NOW) is None


def test_batch_update_is_one_post_with_the_requests_and_five_retries_on_429() -> None:
    api = _api()
    client = _client(api)
    ops = [InsertRows("0", at=6, count=1), SetCell("0", 6, 1, "Ship the flag")]
    client.batch_update(ME, BOOK, ops)
    (post,) = api.sent("POST", ":batchUpdate")
    body = MockGoogleApi.body(post)
    assert body["includeSpreadsheetInResponse"] is False
    assert [next(iter(r)) for r in body["requests"]] == ["insertDimension", "updateCells"]

    limited = _api().on(
        "POST",
        f"/spreadsheets/{BOOK}:batchUpdate",
        [lambda r: json_response("error_429_quota.json", 429)] * 3
        + [lambda r: json_response("sheets_batch_update_ok.json")],
    )
    slept: list[float] = []
    _client(limited, sleep=slept.append).batch_update(ME, BOOK, ops)
    assert len(limited.sent("POST", ":batchUpdate")) == 4
    assert slept == [0.5, 1.0, 2.0]

    exhausted = _api().on(
        "POST", f"/spreadsheets/{BOOK}:batchUpdate", lambda r: json_response("error_429_quota.json", 429)
    )
    with pytest.raises(RateLimited):
        _client(exhausted, sleep=lambda s: None).batch_update(ME, BOOK, ops)
    assert len(exhausted.sent("POST", ":batchUpdate")) == 6


def test_a_403_on_a_protected_range_names_the_protection_and_its_editors() -> None:
    api = _api().on(
        "POST", f"/spreadsheets/{BOOK}:batchUpdate", lambda r: json_response("error_403_protected.json", 403)
    )
    with pytest.raises(PermissionDenied) as err:
        _client(api).batch_update(ME, BOOK, [SetCell("0", 4, 6, "=1")])  # G5, inside "Days left formulas"
    assert "protected cell" in str(err.value)
    assert (
        err.value.detail
        == "Days left formulas on P1 Resolve & Log (editors: ansul.s@simpleo.ai, prathyush.kodhanpur@simpleo.ai)"
    )

    with pytest.raises(PermissionDenied) as err:
        _client(api).batch_update(ME, BOOK, [InsertRows("0", at=1, count=1)])  # inside the header rows
    assert err.value.detail == "Header rows on P1 Resolve & Log (editors: ansul.s@simpleo.ai)"

    with pytest.raises(PermissionDenied) as err:
        _client(api).batch_update(ME, BOOK, [SetCell("0", 10, 1, "x")])  # not inside any protection
    assert err.value.detail == "PERMISSION_DENIED"


def test_a1_helpers_quote_titles() -> None:
    assert quote_title("Ansul's tab") == "'Ansul''s tab'"
    assert a1_range("P1", 0, None, 39) == "'P1'!1:40"
    assert a1_range("P1", 40, 0, 999, 7) == "'P1'!A41:H1000"
