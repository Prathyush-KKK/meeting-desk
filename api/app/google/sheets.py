"""Sheets: the tab read the planner runs on, and the one ``batchUpdate`` that carries a plan out.

Reading a tab is five calls, each limited to what the layout code needs:

1. ``spreadsheets.get`` - sheet titles, ``sheetId``, ``gridProperties`` (cached 60 s);
2. ``values.batchGet`` on the detection window (the first 40 rows);
3. ``values.batchGet`` on the rest of the table region (the header's columns, rows 41 onward);
4. ``values.batchGet`` with ``valueRenderOption=FORMULA`` on the table region, to flag formula
   columns;
5. ``spreadsheets.get`` with ``includeGridData`` on the header row and the first data row only,
   with a fields mask, for data validation (dropdowns) and number formats (date columns).

Writing is one ``spreadsheets.batchUpdate``: ``insertDimension`` (``inheritFromBefore``),
``copyPaste`` with ``PASTE_FORMULA`` for formula columns, ``updateCells`` for values (dates as
serial numbers when the value reads as a date, text otherwise, and text is always ``stringValue``
so nothing is auto-parsed). 429 is retried with exponential backoff, five times. A 403 on a
protected range comes back as ``PermissionDenied`` naming the protection and its editors.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.google.drive import RealDriveClient
from app.google.http import GoogleHttp
from app.google.interface import (
    BatchOp,
    CopyFormula,
    DeleteRows,
    InsertRows,
    NotFoundError,
    PermissionDenied,
    SetCell,
    SpreadsheetMeta,
    TabMeta,
    TabRead,
)
from app.sheets.dates import serial_for, serial_from_date
from app.sheets.layout import HEADER_SCAN_ROWS, col_letter, detect_layout, grid_width

BASE = "https://sheets.googleapis.com/v4/spreadsheets"
META_FIELDS = (
    "spreadsheetId,properties.title,spreadsheetUrl,"
    "sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)))"
)
GRID_FIELDS = "sheets(data(rowData(values(effectiveFormat.numberFormat.type,dataValidation))))"
PROTECTION_FIELDS = (
    "sheets(properties(sheetId,title),"
    "protectedRanges(protectedRangeId,description,range,editors,warningOnly))"
)
WRITE_RETRIES = 5


@dataclass(slots=True)
class SheetProps:
    sheet_id: int
    title: str
    index: int
    row_count: int
    column_count: int


@dataclass(slots=True)
class _Meta:
    spreadsheet: SpreadsheetMeta
    sheets: list[SheetProps]
    at: float


class RealSheetsClient:
    def __init__(
        self,
        http: GoogleHttp,
        drive: RealDriveClient | None = None,
        display_tz: ZoneInfo | str = "Asia/Kolkata",
        max_rows: int = 5000,
        meta_cache_seconds: float = 60.0,
        now: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.http = http
        self.drive = drive or RealDriveClient(http, display_tz)
        self.tz = ZoneInfo(display_tz) if isinstance(display_tz, str) else display_tz
        self.max_rows = max_rows
        self.meta_cache_seconds = meta_cache_seconds
        self._now = now
        self._wall = wall_clock or (lambda: datetime.now(self.tz))
        self._meta: dict[tuple[str, str], _Meta] = {}

    # --- metadata ------------------------------------------------------------------------------
    def _load_meta(self, connection_email: str, spreadsheet_id: str) -> _Meta:
        key = (connection_email, spreadsheet_id)
        cached = self._meta.get(key)
        if cached and self._now() - cached.at < self.meta_cache_seconds:
            return cached
        body = self.http.get(connection_email, f"{BASE}/{spreadsheet_id}", params={"fields": META_FIELDS})
        sheets: list[SheetProps] = []
        for raw in body.get("sheets") or []:
            props = raw.get("properties") or {}
            grid = props.get("gridProperties") or {}
            sheets.append(
                SheetProps(
                    sheet_id=int(props.get("sheetId", 0)),
                    title=str(props.get("title") or ""),
                    index=int(props.get("index", len(sheets))),
                    row_count=int(grid.get("rowCount", 1000)),
                    column_count=int(grid.get("columnCount", 26)),
                )
            )
        sheets.sort(key=lambda s: s.index)
        meta = _Meta(
            spreadsheet=SpreadsheetMeta(
                spreadsheet_id=str(body.get("spreadsheetId") or spreadsheet_id),
                title=str((body.get("properties") or {}).get("title") or ""),
                url=str(
                    body.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
                ),
                tabs=[TabMeta(sheet_id=str(s.sheet_id), title=s.title, index=s.index) for s in sheets],
            ),
            sheets=sheets,
            at=self._now(),
        )
        self._meta[key] = meta
        return meta

    def forget(self, connection_email: str | None = None, spreadsheet_id: str | None = None) -> None:
        for key in list(self._meta):
            if (connection_email is None or key[0] == connection_email) and (
                spreadsheet_id is None or key[1] == spreadsheet_id
            ):
                self._meta.pop(key, None)

    def _sheet(self, connection_email: str, spreadsheet_id: str, sheet_id: str) -> SheetProps:
        meta = self._load_meta(connection_email, spreadsheet_id)
        wanted = str(sheet_id).strip()
        for sheet in meta.sheets:
            if str(sheet.sheet_id) == wanted or sheet.title == wanted:
                return sheet
        raise NotFoundError(f"no tab {sheet_id} in {meta.spreadsheet.title or spreadsheet_id}")

    def get_spreadsheet(self, connection_email: str, spreadsheet_id: str) -> SpreadsheetMeta:
        return self._load_meta(connection_email, spreadsheet_id).spreadsheet

    def can_edit(self, connection_email: str, spreadsheet_id: str) -> bool:
        return self.drive.can_edit(connection_email, spreadsheet_id)

    # --- reads -----------------------------------------------------------------------------------
    def _values(
        self, connection_email: str, spreadsheet_id: str, ranges: list[str], render: str | None = None
    ) -> list[list[list[str]]]:
        params: dict[str, Any] = {"ranges": ranges, "majorDimension": "ROWS"}
        if render:
            params["valueRenderOption"] = render
        body = self.http.get(connection_email, f"{BASE}/{spreadsheet_id}/values:batchGet", params=params)
        out: list[list[list[str]]] = []
        for vr in body.get("valueRanges") or []:
            out.append([[_cell_text(v) for v in row] for row in vr.get("values") or []])
        while len(out) < len(ranges):
            out.append([])
        return out

    def read_tab(self, connection_email: str, spreadsheet_id: str, sheet_id: str) -> TabRead:
        sheet = self._sheet(connection_email, spreadsheet_id, sheet_id)
        last_row = min(sheet.row_count, self.max_rows)  # 1-indexed, inclusive

        # 2. the detection window
        (window,) = self._values(
            connection_email, spreadsheet_id, [a1_range(sheet.title, 0, None, HEADER_SCAN_ROWS - 1)]
        )
        provisional = detect_layout(window)
        header_row = provisional.header_row
        if header_row >= 0:
            # The table region is the header's columns; that is all the rows below need.
            first_col, last_col = provisional.first_col, provisional.last_col
        else:
            first_col, last_col = 0, max(grid_width(window) - 1, 0)
        first_data = header_row + 1  # 0-indexed

        # 3. the rest of the table region, below the window
        region: list[list[str]] = []
        if last_row > HEADER_SCAN_ROWS:
            (region,) = self._values(
                connection_email,
                spreadsheet_id,
                [a1_range(sheet.title, HEADER_SCAN_ROWS, first_col, last_row - 1, last_col)],
            )

        # 4. formulas over the table region
        formulas_region: list[list[str]] = []
        if last_row > first_data:
            (formulas_region,) = self._values(
                connection_email,
                spreadsheet_id,
                [a1_range(sheet.title, first_data, first_col, last_row - 1, last_col)],
                render="FORMULA",
            )

        # 5. validation and number formats on the header row and the first data row
        grid_top = max(0, header_row)
        grid_rows = self._grid_rows(
            connection_email,
            spreadsheet_id,
            a1_range(sheet.title, grid_top, first_col, first_data, last_col),
        )

        width = max(last_col + 1, grid_width(window), 1)
        values = [_pad(list(r), width) for r in window]
        values.extend(_pad([""] * first_col + list(r), width) for r in region)
        height = max(len(values), first_data + len(formulas_region))
        while len(values) < height:
            values.append([""] * width)

        formulas = [list(row) for row in values]
        for i, row in enumerate(formulas_region):
            r = first_data + i
            for j, value in enumerate(row):
                c = first_col + j
                if c < width:
                    formulas[r][c] = value

        number_formats = [["TEXT"] * width for _ in values]
        dropdowns: dict[int, list[str]] = {}
        data_index = first_data - grid_top
        data_row = grid_rows[data_index] if len(grid_rows) > data_index else []
        if first_data < len(number_formats):
            for j, cell in enumerate(data_row):
                c = first_col + j
                if c >= width:
                    continue
                kind = ((cell.get("effectiveFormat") or {}).get("numberFormat") or {}).get("type")
                if kind:
                    number_formats[first_data][c] = str(kind)
                allowed = self._validation_values(
                    connection_email, spreadsheet_id, cell.get("dataValidation")
                )
                if allowed:
                    dropdowns[c] = allowed

        return TabRead(
            sheet_id=str(sheet.sheet_id),
            title=sheet.title,
            values=values,
            formulas=formulas,
            number_formats=number_formats,
            dropdowns=dropdowns,
            read_at=self._wall(),
        )

    def _grid_rows(self, connection_email: str, spreadsheet_id: str, a1: str) -> list[list[dict[str, Any]]]:
        body = self.http.get(
            connection_email,
            f"{BASE}/{spreadsheet_id}",
            params={"includeGridData": True, "ranges": [a1], "fields": GRID_FIELDS},
        )
        rows: list[list[dict[str, Any]]] = []
        for sheet in body.get("sheets") or []:
            for data in sheet.get("data") or []:
                for row in data.get("rowData") or []:
                    rows.append(list(row.get("values") or []))
        return rows

    def _validation_values(
        self, connection_email: str, spreadsheet_id: str, validation: dict[str, Any] | None
    ) -> list[str]:
        if not validation:
            return []
        condition = validation.get("condition") or {}
        kind = condition.get("type")
        raw_values = [str(v.get("userEnteredValue") or "") for v in condition.get("values") or []]
        if kind == "ONE_OF_LIST":
            return [v for v in raw_values if v.strip()]
        if kind == "ONE_OF_RANGE" and raw_values:
            source = raw_values[0].lstrip("=")
            try:
                (cells,) = self._values(connection_email, spreadsheet_id, [source])
            except NotFoundError:
                return []
            return [v for row in cells for v in row if (v or "").strip()]
        return []

    def read_cells(
        self, connection_email: str, spreadsheet_id: str, sheet_id: str, refs: list[str]
    ) -> dict[str, str]:
        if not refs:
            return {}
        sheet = self._sheet(connection_email, spreadsheet_id, sheet_id)
        ranges = [f"{quote_title(sheet.title)}!{ref}" for ref in refs]
        blocks = self._values(connection_email, spreadsheet_id, ranges)
        out: dict[str, str] = {}
        for ref, block in zip(refs, blocks, strict=True):
            out[ref] = block[0][0] if block and block[0] else ""
        return out

    # --- writes ----------------------------------------------------------------------------------
    def batch_update(self, connection_email: str, spreadsheet_id: str, ops: list[BatchOp]) -> None:
        if not ops:
            return
        sheet = self._sheet(connection_email, spreadsheet_id, ops[0].sheet_id)
        requests = build_requests(ops, sheet.sheet_id, base=self._wall())
        try:
            self.http.post(
                connection_email,
                f"{BASE}/{spreadsheet_id}:batchUpdate",
                json={"requests": requests, "includeSpreadsheetInResponse": False},
                retries=WRITE_RETRIES,
            )
        except PermissionDenied as exc:
            detail = self._protection_detail(connection_email, spreadsheet_id, sheet, ops)
            raise PermissionDenied(str(exc), detail=detail or exc.detail) from exc
        finally:
            # Row counts moved; the next read must not trust the cached grid properties.
            self.forget(spreadsheet_id=spreadsheet_id)

    def _protection_detail(
        self, connection_email: str, spreadsheet_id: str, sheet: SheetProps, ops: list[BatchOp]
    ) -> str:
        """Name the protected range (and who may edit it) that the write ran into, when there is one."""
        try:
            body = self.http.get(
                connection_email, f"{BASE}/{spreadsheet_id}", params={"fields": PROTECTION_FIELDS}, retries=0
            )
        except Exception:
            return ""
        touched = touched_cells(ops)
        for raw in body.get("sheets") or []:
            if int((raw.get("properties") or {}).get("sheetId", -1)) != sheet.sheet_id:
                continue
            for pr in raw.get("protectedRanges") or []:
                if pr.get("warningOnly") or not _overlaps(pr.get("range") or {}, touched):
                    continue
                name = pr.get("description") or f"protected range {pr.get('protectedRangeId', '')}".strip()
                editors = (pr.get("editors") or {}).get("users") or []
                who = f" (editors: {', '.join(editors)})" if editors else ""
                return f"{name} on {sheet.title}{who}"
        return ""


# --- request building ---------------------------------------------------------------------------------


def build_requests(ops: list[BatchOp], sheet_id: int, base: datetime | None = None) -> list[dict[str, Any]]:
    """Ops in order; adjacent cell writes on one row collapse into one ``updateCells``."""
    requests: list[dict[str, Any]] = []
    run: list[SetCell] = []

    def flush() -> None:
        if run:
            requests.append(_update_cells(run, sheet_id, base))
            run.clear()

    for op in ops:
        if isinstance(op, SetCell):
            if run and (op.row != run[-1].row or op.col != run[-1].col + 1):
                flush()
            run.append(op)
            continue
        flush()
        if isinstance(op, InsertRows):
            requests.append(
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": op.at,
                            "endIndex": op.at + op.count,
                        },
                        "inheritFromBefore": op.at > 0 and op.inherit_from_before,
                    }
                }
            )
        elif isinstance(op, DeleteRows):
            requests.append(
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": op.at,
                            "endIndex": op.at + op.count,
                        }
                    }
                }
            )
        elif isinstance(op, CopyFormula):
            for start, end in _runs(sorted(op.target_rows)):
                requests.append(
                    {
                        "copyPaste": {
                            "source": _grid_range(
                                sheet_id, op.source_row, op.source_row + 1, op.col, op.col + 1
                            ),
                            "destination": _grid_range(sheet_id, start, end + 1, op.col, op.col + 1),
                            "pasteType": "PASTE_FORMULA",
                            "pasteOrientation": "NORMAL",
                        }
                    }
                )
    flush()
    return requests


def cell_data(
    value: str, as_date: bool, base: datetime | None = None, date_value: str = ""
) -> dict[str, Any]:
    """A date column takes the date the caller resolved; the text is only read when there is none."""
    if value == "":
        return {}  # with fields=userEnteredValue this clears the cell (undo)
    if as_date:
        serial = serial_from_iso(date_value)
        if serial is None:
            serial = serial_for(value, base)
        if serial is not None:
            return {"userEnteredValue": {"numberValue": serial}}
    return {"userEnteredValue": {"stringValue": value}}


def serial_from_iso(value: str) -> int | None:
    try:
        return serial_from_date(date.fromisoformat(value)) if value else None
    except ValueError:  # pragma: no cover - the planner only ever writes isoformat()
        return None


def _update_cells(run: list[SetCell], sheet_id: int, base: datetime | None) -> dict[str, Any]:
    return {
        "updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": run[0].row, "columnIndex": run[0].col},
            "rows": [{"values": [cell_data(op.value, op.as_date, base, op.date_value) for op in run]}],
            "fields": "userEnteredValue",
        }
    }


def _grid_range(sheet_id: int, r0: int, r1: int, c0: int, c1: int) -> dict[str, int]:
    return {
        "sheetId": sheet_id,
        "startRowIndex": r0,
        "endRowIndex": r1,
        "startColumnIndex": c0,
        "endColumnIndex": c1,
    }


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for r in rows:
        if out and r == out[-1][1] + 1:
            out[-1] = (out[-1][0], r)
        else:
            out.append((r, r))
    return out


def touched_cells(ops: list[BatchOp]) -> list[tuple[int, int]]:
    cells: list[tuple[int, int]] = []
    for op in ops:
        if isinstance(op, SetCell):
            cells.append((op.row, op.col))
        elif isinstance(op, InsertRows | DeleteRows):
            cells.extend((op.at + i, -1) for i in range(op.count))
        elif isinstance(op, CopyFormula):
            cells.extend((r, op.col) for r in op.target_rows)
    return cells


def _overlaps(grid_range: dict[str, Any], cells: list[tuple[int, int]]) -> bool:
    r0 = grid_range.get("startRowIndex")
    r1 = grid_range.get("endRowIndex")
    c0 = grid_range.get("startColumnIndex")
    c1 = grid_range.get("endColumnIndex")
    if r0 is None and r1 is None and c0 is None and c1 is None:
        return True  # the whole sheet is protected
    for r, c in cells:
        if r0 is not None and r < r0:
            continue
        if r1 is not None and r >= r1:
            continue
        if c >= 0:
            if c0 is not None and c < c0:
                continue
            if c1 is not None and c >= c1:
                continue
        return True
    return False


# --- A1 helpers ---------------------------------------------------------------------------------------


def quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def a1_range(title: str, r0: int, c0: int | None, r1: int, c1: int | None = None) -> str:
    """0-indexed inclusive rows/cols to ``'Title'!A1:H40``; ``c0`` None means whole rows."""
    if c0 is None:
        return f"{quote_title(title)}!{r0 + 1}:{r1 + 1}"
    last_col = c1 if c1 is not None else c0
    return f"{quote_title(title)}!{col_letter(c0)}{r0 + 1}:{col_letter(last_col)}{r1 + 1}"


def _pad(row: list[str], width: int) -> list[str]:
    if len(row) < width:
        return [*row, *[""] * (width - len(row))]
    return row[:width] if len(row) > width else row


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


__all__ = [
    "RealSheetsClient",
    "SheetProps",
    "a1_range",
    "build_requests",
    "cell_data",
    "quote_title",
    "touched_cells",
]
