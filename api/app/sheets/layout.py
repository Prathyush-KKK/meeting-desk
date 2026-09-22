"""Sheet layout detection.

A faithful port of ``meeting-desk/src/lib/sheet.ts`` (``detectLayout``, ``nextKeys``, the A1 helpers)
plus the two things the server needs that the prototype does not have: a hash of the table region so
a write can tell whether the sheet moved under it, and hooks for the formula and date columns that
the reader discovers from the Sheets API (``valueRenderOption=FORMULA`` and the number formats).

Rows are 0-indexed lists of strings; the UI shows them 1-indexed like Sheets.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

Field = Literal[
    "id",
    "task",
    "owner",
    "due",
    "priority",
    "effort",
    "status",
    "notes",
    "decision",
    "risk",
    "severity",
    "question",
]

# Insertion order is load-bearing: matchField returns the first field that matches.
SYNONYMS: dict[Field, list[str]] = {
    "id": ["id", "key", "ref", "#"],
    "task": ["task", "item", "title", "action", "action item", "work item", "deliverable"],
    "owner": ["owner", "assignee", "who", "person", "assigned to", "responsible"],
    "due": ["due", "deadline", "eta", "target", "due date", "by"],
    "priority": ["priority", "prio", "p"],
    "effort": ["effort", "size", "estimate", "t-shirt"],
    "status": ["status", "state", "progress"],
    "notes": ["notes", "note", "remarks", "source", "comment", "comments", "context"],
    "decision": ["decision", "decided", "rule"],
    "risk": ["risk"],
    "severity": ["severity", "sev", "impact"],
    "question": ["question", "open question", "open"],
}

KEY_RE = re.compile(r"^([A-Z]{1,4})-(\d+)$")
_NON_WORD_RE = re.compile(r"[^a-z0-9# ]+")
_SPACE_RE = re.compile(r"\s+")

HEADER_SCAN_ROWS = 40
MIN_HEADER_SCORE = 2


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    n = index
    while True:
        out = chr(65 + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            return out


def a1(row: int, col: int) -> str:
    return f"{col_letter(col)}{row + 1}"


def parse_a1(ref: str) -> tuple[int, int]:
    """ "C10" -> (9, 2). Raises ValueError on anything else."""
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref.strip())
    if not m:
        raise ValueError(f"not an A1 cell reference: {ref!r}")
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1


def norm(value: str | None) -> str:
    s = (value or "").strip().lower()
    s = _NON_WORD_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def match_field(header: str | None) -> Field | None:
    h = norm(header)
    if not h:
        return None
    for name, words in SYNONYMS.items():
        if h in words:
            return name
    for name, words in SYNONYMS.items():
        if any(len(w) > 2 and (h.startswith(w + " ") or h.endswith(" " + w)) for w in words):
            return name
    return None


def cell(rows: list[list[str]], row: int, col: int) -> str:
    """Out-of-range reads are empty strings, the way ``rows[r][c] || ""`` behaves in JS."""
    if row < 0 or row >= len(rows):
        return ""
    line = rows[row]
    if col < 0 or col >= len(line):
        return ""
    return line[col] or ""


def grid_width(rows: list[list[str]]) -> int:
    return max((len(r) for r in rows), default=0)


@dataclass(slots=True)
class Layout:
    header_row: int = -1  # 0-indexed, -1 when none
    first_col: int = 0
    last_col: int = 0
    columns: dict[Field, int] = field(default_factory=dict)
    key_col: int = -1  # -1 when none
    key_prefix: str = ""
    last_table_row: int = -1  # equals header_row when the table is empty
    header_score: int = 0
    # Supplied by the reader, never inferred from values: see detect_formula_cols / detect_date_cols.
    formula_cols: list[int] = field(default_factory=list)
    date_cols: list[int] = field(default_factory=list)

    @property
    def has_header(self) -> bool:
        return self.header_row >= 0

    def column_of(self, name: Field) -> int | None:
        return self.columns.get(name)

    def is_writable_col(self, col: int) -> bool:
        return col not in self.formula_cols

    def to_dict(self) -> dict:
        return {
            "header_row": self.header_row,
            "first_col": self.first_col,
            "last_col": self.last_col,
            "columns": dict(self.columns),
            "key_col": self.key_col,
            "key_prefix": self.key_prefix,
            "last_table_row": self.last_table_row,
            "header_score": self.header_score,
            "formula_cols": list(self.formula_cols),
            "date_cols": list(self.date_cols),
        }


def detect_layout(
    rows: list[list[str]],
    formula_cols: list[int] | None = None,
    date_cols: list[int] | None = None,
) -> Layout:
    """Header row by synonym score, then columns, key column, and the table extent.

    Ties between two candidate header rows go to the *upper* row, exactly as ``lib/sheet.ts`` does
    (the comparison is a strict ``>``). The spec's "a second matching row directly below wins" case
    is the common one where a merged/banner row above scores lower than the real header row; that
    resolves to the lower row here too.
    """
    width = grid_width(rows)
    best_row, best_score = -1, 0
    limit = min(len(rows), HEADER_SCAN_ROWS)
    for r in range(limit):
        score = sum(1 for c in rows[r] if match_field(c))
        if score > best_score:
            best_row, best_score = r, score

    layout = Layout(
        header_row=-1,
        first_col=0,
        last_col=max(0, width - 1),
        columns={},
        key_col=-1,
        key_prefix="",
        last_table_row=-1,
        header_score=best_score,
        formula_cols=sorted(formula_cols or []),
        date_cols=sorted(date_cols or []),
    )

    if best_score < MIN_HEADER_SCORE:
        # No header: the table is everything that has content.
        last = -1
        for i, row in enumerate(rows):
            if any((c or "").strip() for c in row):
                last = i
        layout.last_table_row = last
        return layout

    layout.header_row = best_row
    header = rows[best_row]
    first = -1
    last = -1
    for c, value in enumerate(header):
        if (value or "").strip():
            if first < 0:
                first = c
            last = c
            f = match_field(value)
            if f is not None and f not in layout.columns:
                layout.columns[f] = c
    layout.first_col = max(0, first)
    layout.last_col = max(0, last)

    # Key column: the "id" header, else a column whose values mostly look like T-101.
    if "id" in layout.columns:
        layout.key_col = layout.columns["id"]
    else:
        for c in range(layout.first_col, layout.last_col + 1):
            values = [v for v in (cell(rows, r, c).strip() for r in range(best_row + 1, len(rows))) if v]
            if values and sum(1 for v in values if KEY_RE.match(v)) / len(values) > 0.6:
                layout.key_col = c
                break

    if layout.key_col >= 0:
        sample = next(
            (
                v
                for v in (cell(rows, r, layout.key_col).strip() for r in range(best_row + 1, len(rows)))
                if KEY_RE.match(v)
            ),
            None,
        )
        m = KEY_RE.match(sample) if sample else None
        layout.key_prefix = m.group(1) if m else ""

    # Table extent: the last row with a value in the key, task, decision or risk column.
    probe = [
        c
        for c in (
            layout.key_col,
            layout.columns.get("task", -1),
            layout.columns.get("decision", -1),
            layout.columns.get("risk", -1),
        )
        if c >= 0
    ]
    last_row = best_row
    for r in range(best_row + 1, len(rows)):
        if any(cell(rows, r, c).strip() for c in probe):
            last_row = r
    layout.last_table_row = last_row
    return layout


def next_keys(rows: list[list[str]], layout: Layout, count: int) -> list[str]:
    """Allocate ``count`` keys after the highest existing one. Always called after the re-read."""
    if layout.key_col < 0:
        return [""] * count
    highest = 0
    for r in range(len(rows)):
        m = KEY_RE.match(cell(rows, r, layout.key_col).strip())
        if m and m.group(1) == (layout.key_prefix or m.group(1)):
            highest = max(highest, int(m.group(2)))
    prefix = layout.key_prefix or "T"
    return [f"{prefix}-{str(highest + 1 + i).zfill(3)}" for i in range(count)]


# The table itself plus its shoulders. A banner or a second header line moving above the header,
# and a total, a note or a stray value written just under the last row, all change what a plan
# means; the strict header..last_table_row window could not see any of them.
REGION_ROWS_ABOVE = 2
REGION_ROWS_BELOW = 5


def region_bounds(layout: Layout, row_count: int | None = None) -> tuple[int, int, int, int]:
    """(first_row, last_row, first_col, last_col) of the guarded region, inclusive.

    A few rows either side of the table, clamped to the grid: never below row 0, and never past the
    last row the read returned (a read that returns more rows changes the bounds, which changes the
    digest by itself).
    """
    first_row = max(0, (layout.header_row if layout.header_row >= 0 else 0) - REGION_ROWS_ABOVE)
    last_row = max(first_row, layout.last_table_row)
    ceiling = last_row if row_count is None else max(last_row, row_count - 1)
    last_row = min(last_row + REGION_ROWS_BELOW, ceiling)
    return first_row, last_row, layout.first_col, layout.last_col


def region_values(rows: list[list[str]], layout: Layout) -> list[list[str]]:
    r0, r1, c0, c1 = region_bounds(layout, len(rows))
    return [[cell(rows, r, c) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]


def row_values(rows: list[list[str]], row: int, layout: Layout) -> list[str]:
    _, _, c0, c1 = region_bounds(layout, len(rows))
    return [cell(rows, row, c) for c in range(c0, c1 + 1)]


def region_hash(
    rows: list[list[str]], layout: Layout | None = None, touched_rows: Iterable[int] | None = None
) -> str:
    """sha256 over the guarded region's values, plus any row the plan touches outside it.

    Compared before every write: if the digest moved, somebody edited the tab since the preview and
    the plan is rebuilt instead of writing over them. ``touched_rows`` is what makes a Custom fill
    far below the table as safe as an append: those rows are guarded whether or not the region
    reaches them, and a plan that touches nothing outside the region hashes exactly as before.
    """
    resolved = layout or detect_layout(rows)
    body = "\x1e".join("\x1f".join(row) for row in region_values(rows, resolved))
    head = f"{resolved.header_row}:{resolved.first_col}:{resolved.last_col}:{resolved.last_table_row}"
    r0, r1, _, _ = region_bounds(resolved, len(rows))
    outside = sorted({r for r in (touched_rows or ()) if r < r0 or r > r1})
    if outside:
        body += "\x1d" + "\x1e".join(
            f"{r}\x1f" + "\x1f".join(row_values(rows, r, resolved)) for r in outside
        )
    return hashlib.sha256(f"{head}\x1d{body}".encode()).hexdigest()


def row_hash(rows: list[list[str]], row: int, layout: Layout | None = None) -> str:
    """sha256 over one whole row of the region, for the undo guard.

    Undo deletes rows it inserted. It may only do that while they still hold what the transfer put
    there - so the check is the entire row, not just the cells that were written: somebody filling
    a *different* column of that row has done work that a delete would throw away.
    """
    resolved = layout or detect_layout(rows)
    return hashlib.sha256("\x1f".join(row_values(rows, row, resolved)).encode()).hexdigest()


# --- reader hooks --------------------------------------------------------------------------------
# Both take what the Sheets reader already has to fetch and turn it into column indexes. They are
# deliberately dumb: nothing here guesses from displayed values.


def detect_formula_cols(
    formulas: list[list[str]], header_row: int, first_data_row: int | None = None
) -> list[int]:
    """Columns whose data cells hold formulas (grid read with ``valueRenderOption=FORMULA``)."""
    start = first_data_row if first_data_row is not None else max(0, header_row + 1)
    found: set[int] = set()
    for r in range(start, len(formulas)):
        for c, value in enumerate(formulas[r]):
            if (value or "").startswith("="):
                found.add(c)
    return sorted(found)


DATE_FORMAT_TYPES = {"DATE", "DATE_TIME"}


def detect_date_cols(
    number_formats: list[list[str]], header_row: int, first_data_row: int | None = None
) -> list[int]:
    """Columns whose data cells carry a DATE/DATE_TIME number format."""
    start = first_data_row if first_data_row is not None else max(0, header_row + 1)
    found: set[int] = set()
    for r in range(start, len(number_formats)):
        for c, kind in enumerate(number_formats[r]):
            if (kind or "").upper() in DATE_FORMAT_TYPES:
                found.add(c)
    return sorted(found)
