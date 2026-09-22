"""Transfer planning.

A faithful port of ``meeting-desk/src/lib/sheet.ts`` (``mapStatus``, ``valuesFor``, ``planAppend``,
``planFill``, ``applyPlan``, ``planCells``) with three server-side additions:

* ``plan_add_row`` - a one-row plan at a chosen index, for the Sheets page's "Add row".
* formula columns are never written; after an insert the planner records which columns to copy
  down from the row above.
* date columns are flagged on the write so the caller can send ``USER_ENTERED`` dates.

With ``formula_cols``/``date_cols`` empty the output is cell-for-cell identical to the TypeScript
reference; ``tests/fixtures/sheets/*.json`` carries expectations generated from that reference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.sheets.layout import (
    Field,
    Layout,
    a1,
    cell,
    detect_layout,
    grid_width,
    match_field,
    next_keys,
    norm,
)

Kind = Literal["action", "decision", "risk", "question"]
Conflict = Literal["skip", "overwrite", "insert"]
WriteKind = Literal["new", "key", "conflict"]

STATUS_WORDS: dict[str, list[str]] = {
    "open": ["open", "to do", "todo", "not started", "new", "backlog"],
    "in_progress": ["in progress", "doing", "started", "wip", "moving"],
    "blocked": ["blocked", "waiting", "on hold"],
    "done": ["done", "complete", "completed", "shipped", "closed"],
    "dropped": ["dropped", "cancelled", "canceled", "won't do", "removed"],
    "decided": ["decided", "agreed", "done"],
}

DEFAULT_ORDER: list[Field] = ["task", "owner", "due", "status"]


def _date_value(point: PointForSheet | None, name: str) -> str:
    """The resolved date for the due column, so the writer never re-reads "EOW" on its own."""
    if point is None or name != "due" or point.due_date is None:
        return ""
    return point.due_date.isoformat()


@dataclass(slots=True)
class PointForSheet:
    id: str
    kind: Kind
    text: str
    owner: str = ""
    due: str = ""
    status: str = "open"
    meeting_label: str = ""
    # ``points.due_date``: the date post-processing already resolved from the notes, with the
    # meeting start as its base. The cell shows ``due`` (what the notes said); a date column is
    # written from this, so "EOW" cannot land on a different day than the point says it is.
    due_date: date | None = None


@dataclass(slots=True)
class CellWrite:
    r: int
    c: int
    value: str
    kind: WriteKind
    existing: str | None = None
    date: bool = False
    # ISO yyyy-mm-dd when the value's date is already known; empty means "read it off the text".
    date_value: str = ""

    @property
    def ref(self) -> str:
        return a1(self.r, self.c)

    @property
    def skipped(self) -> bool:
        """A ``skip`` conflict is recorded so the preview can show it, but nothing is written."""
        return self.kind == "conflict" and self.existing is not None and self.value == self.existing

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "r": self.r,
            "c": self.c,
            "value": self.value,
            "kind": self.kind,
            "existing": self.existing,
            "date": self.date,
            "date_value": self.date_value,
        }


@dataclass(slots=True)
class FormulaFill:
    """After an insert, copy this column's formula down from ``source_row`` into ``target_rows``."""

    col: int
    source_row: int
    target_rows: list[int]

    def to_dict(self) -> dict:
        return {"col": self.col, "source_row": self.source_row, "target_rows": list(self.target_rows)}


@dataclass(slots=True)
class Plan:
    mode: Literal["append", "fill", "add_row"]
    writes: list[CellWrite] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    field_order: list[dict] = field(default_factory=list)
    formula_fill: list[FormulaFill] = field(default_factory=list)
    insert_at: int | None = None
    anchor: dict | None = None
    count: int = 0
    layout: Layout | None = None
    unmapped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "insert_at": self.insert_at,
            "anchor": self.anchor,
            "count": self.count,
            "keys": list(self.keys),
            "cells": plan_cells(self),
            "writes": [w.to_dict() for w in self.writes],
            "moved": list(self.moved),
            "conflicts": list(self.conflicts),
            "field_order": list(self.field_order),
            "formula_fill": [f.to_dict() for f in self.formula_fill],
            "unmapped": list(self.unmapped),
            "layout": self.layout.to_dict() if self.layout else None,
        }


def map_status(status: str, allowed: Sequence[str] | None = None) -> str:
    """Map a point status onto the column's data validation values, or blank when nothing fits."""
    if not allowed:
        return status.replace("_", " ", 1)
    words = STATUS_WORDS.get(status, [status])
    for value in allowed:
        if norm(value) in words:
            return value
    return ""


def values_for(
    point: PointForSheet, layout: Layout, dropdowns: Mapping[int, Sequence[str]]
) -> dict[Field, str]:
    """Field -> value for one point. Insertion order drives the order of the writes."""
    values: dict[Field, str] = {}
    if point.kind == "decision" and "decision" in layout.columns:
        text_field: Field = "decision"
    elif point.kind == "risk" and "risk" in layout.columns:
        text_field = "risk"
    else:
        text_field = "task"
    values[text_field] = point.text
    values["owner"] = point.owner
    values["due"] = point.due
    status_col = layout.columns.get("status")
    values["status"] = map_status(point.status, dropdowns.get(status_col) if status_col is not None else None)
    values["notes"] = point.meeting_label
    return values


def _blank_row(width: int) -> list[str]:
    return [""] * width


def insert_blank(rows: list[list[str]], at: int, count: int) -> list[list[str]]:
    width = grid_width(rows)
    blanks = [_blank_row(width) for _ in range(count)]
    return [*rows[:at], *blanks, *rows[at:]]


def _moved_refs(rows: list[list[str]], from_row: int) -> list[str]:
    moved: list[str] = []
    for r in range(from_row, len(rows)):
        for c, value in enumerate(rows[r]):
            if (value or "").strip():
                moved.append(a1(r, c))
    return moved


def _formula_fill(layout: Layout, insert_at: int, count: int) -> list[FormulaFill]:
    """Which column to copy a formula from, and from where.

    Normally the row above the insert. Not when that row is the header (or a banner above it): its
    cells are labels, not formulas, and copying them down puts the word "Days left" in a data row.
    The row below the insert - the one the new rows pushed down, which is a data row of the same
    table - is the source then, and if there is no such row nothing is copied.

    Rows are post-insert indexes: ``insert_at - 1`` is still the row that was above, and the row
    that was at ``insert_at`` has moved to ``insert_at + count``.
    """
    if not layout.formula_cols:
        return []
    source = insert_at - 1
    targets = list(range(insert_at, insert_at + count))
    if source < 0 or (layout.header_row >= 0 and source <= layout.header_row):
        below = insert_at + count
        if layout.last_table_row < insert_at:  # nothing below either: an empty table
            return []
        source = below
    return [FormulaFill(col=c, source_row=source, target_rows=targets) for c in layout.formula_cols]


def _status_dropdown_missing(
    point: PointForSheet, layout: Layout, dropdowns: Mapping[int, Sequence[str]]
) -> bool:
    status_col = layout.columns.get("status")
    if status_col is None or not dropdowns.get(status_col):
        return False
    return not map_status(point.status, dropdowns.get(status_col))


def plan_append(
    rows: list[list[str]],
    dropdowns: Mapping[int, Sequence[str]],
    points: Sequence[PointForSheet],
    layout: Layout | None = None,
) -> Plan:
    """Smart append: rows land directly after the last table row."""
    resolved = layout or detect_layout(rows)
    insert_at = resolved.last_table_row + 1
    keys = next_keys(rows, resolved, len(points))
    writes: list[CellWrite] = []
    unmapped: list[str] = []

    for i, point in enumerate(points):
        r = insert_at + i
        if resolved.key_col >= 0 and resolved.is_writable_col(resolved.key_col):
            writes.append(CellWrite(r=r, c=resolved.key_col, value=keys[i], kind="key"))
        for name, value in values_for(point, resolved, dropdowns).items():
            c = resolved.columns.get(name)
            if c is None or not value:
                continue
            if not resolved.is_writable_col(c):
                continue
            writes.append(
                CellWrite(
                    r=r,
                    c=c,
                    value=value,
                    kind="new",
                    date=c in resolved.date_cols,
                    date_value=_date_value(point, name),
                )
            )
        if resolved.header_row < 0:
            # No header: default order from the first column.
            order = [point.text, point.owner, point.due, point.status.replace("_", " ", 1)]
            for c, value in enumerate(order):
                if value and resolved.is_writable_col(c):
                    writes.append(CellWrite(r=r, c=c, value=value, kind="new", date=c in resolved.date_cols))
        if _status_dropdown_missing(point, resolved, dropdowns):
            unmapped.append(point.id)

    return Plan(
        mode="append",
        insert_at=insert_at,
        count=len(points),
        writes=writes,
        keys=keys,
        moved=_moved_refs(rows, insert_at),
        formula_fill=_formula_fill(resolved, insert_at, len(points)),
        layout=resolved,
        unmapped=unmapped,
    )


def plan_fill(
    rows: list[list[str]],
    dropdowns: Mapping[int, Sequence[str]],
    points: Sequence[PointForSheet],
    anchor: tuple[int, int] | Mapping[str, int],
    write_keys: bool = False,
    conflict: Conflict = "skip",
    layout: Layout | None = None,
) -> Plan:
    """Custom fill: fields rightward from the anchor by header, points downward."""
    if isinstance(anchor, Mapping):
        anchor_r, anchor_c = int(anchor["r"]), int(anchor["c"])
    else:
        anchor_r, anchor_c = anchor
    resolved = layout or detect_layout(rows)

    field_order: list[dict] = []
    header = rows[resolved.header_row] if resolved.header_row >= 0 else []
    header_cell = header[anchor_c] if anchor_c < len(header) else ""
    anchor_field = match_field(header_cell) if resolved.header_row >= 0 else None
    if resolved.header_row >= 0 and anchor_field:
        for c in range(anchor_c, resolved.last_col + 1):
            f = match_field(header[c] if c < len(header) else "")
            if f:
                field_order.append({"c": c, "field": f})
    else:
        for k, f in enumerate(DEFAULT_ORDER):
            field_order.append({"c": anchor_c + k, "field": f})

    writes: list[CellWrite] = []
    conflicts: list[str] = []
    unmapped: list[str] = []
    keys = next_keys(rows, resolved, len(points))
    effective = insert_blank(rows, anchor_r, len(points)) if conflict == "insert" else rows

    for i, point in enumerate(points):
        r = anchor_r + i
        values = values_for(point, resolved, dropdowns)
        if not anchor_field:
            values["task"] = point.text
            values["status"] = point.status.replace("_", " ", 1)
        planned: list[tuple[int, str, str]] = []
        for fo in field_order:
            name = "task" if fo["field"] == "default" else fo["field"]
            value = values.get(name, "")
            if value:
                planned.append((fo["c"], value, _date_value(point, name)))
        if write_keys and resolved.key_col >= 0 and resolved.key_col < anchor_c:
            planned.append((resolved.key_col, keys[i], ""))

        for c, value, date_value in planned:
            if not resolved.is_writable_col(c):
                continue
            existing = cell(effective, r, c).strip()
            is_key = c == resolved.key_col
            is_date = c in resolved.date_cols
            if existing and conflict != "insert":
                conflicts.append(a1(r, c))
                if conflict == "skip":
                    writes.append(CellWrite(r=r, c=c, value=existing, kind="conflict", existing=existing))
                    continue
                writes.append(
                    CellWrite(
                        r=r,
                        c=c,
                        value=value,
                        kind="conflict",
                        existing=existing,
                        date=is_date,
                        date_value=date_value,
                    )
                )
            else:
                writes.append(
                    CellWrite(
                        r=r,
                        c=c,
                        value=value,
                        kind="key" if is_key else "new",
                        date=is_date,
                        date_value=date_value,
                    )
                )
        if _status_dropdown_missing(point, resolved, dropdowns):
            unmapped.append(point.id)

    insert_at = anchor_r if conflict == "insert" else None
    return Plan(
        mode="fill",
        anchor={"r": anchor_r, "c": anchor_c},
        writes=writes,
        conflicts=conflicts,
        field_order=field_order,
        insert_at=insert_at,
        count=len(points),
        keys=keys,
        moved=_moved_refs(rows, anchor_r) if conflict == "insert" else [],
        formula_fill=_formula_fill(resolved, anchor_r, len(points)) if conflict == "insert" else [],
        layout=resolved,
        unmapped=unmapped,
    )


def plan_add_row(
    rows: list[list[str]],
    dropdowns: Mapping[int, Sequence[str]],
    point: PointForSheet | None = None,
    values: Mapping[int, str] | None = None,
    at: int | None = None,
    layout: Layout | None = None,
) -> Plan:
    """One row, either after the table (``at`` omitted) or above row ``at`` inside a section.

    ``values`` is keyed by column index; the route builds it from the tab's headers. A point and a
    values map can be combined - the explicit values win.
    """
    resolved = layout or detect_layout(rows)
    insert_at = resolved.last_table_row + 1 if at is None else at
    keys = next_keys(rows, resolved, 1)
    row_values: dict[int, str] = {}
    row_dates: dict[int, str] = {}

    if resolved.key_col >= 0 and keys[0]:
        row_values[resolved.key_col] = keys[0]
    if point is not None:
        for name, value in values_for(point, resolved, dropdowns).items():
            c = resolved.columns.get(name)
            if c is None or not value:
                continue
            row_values[c] = value
            row_dates[c] = _date_value(point, name)
        if resolved.header_row < 0:
            for c, value in enumerate(
                [point.text, point.owner, point.due, point.status.replace("_", " ", 1)]
            ):
                if value:
                    row_values[c] = value
    for c, value in (values or {}).items():
        row_values[int(c)] = value
        row_dates.pop(int(c), None)  # an explicit value wins, text and date alike

    writes = [
        CellWrite(
            r=insert_at,
            c=c,
            value=value,
            kind="key" if c == resolved.key_col else "new",
            date=c in resolved.date_cols,
            date_value=row_dates.get(c, ""),
        )
        for c, value in sorted(row_values.items())
        if value != "" and resolved.is_writable_col(c)
    ]
    unmapped = [point.id] if point and _status_dropdown_missing(point, resolved, dropdowns) else []

    return Plan(
        mode="add_row",
        insert_at=insert_at,
        count=1,
        writes=writes,
        keys=keys,
        moved=_moved_refs(rows, insert_at),
        formula_fill=_formula_fill(resolved, insert_at, 1),
        layout=resolved,
        unmapped=unmapped,
    )


def apply_plan(rows: list[list[str]], plan: Plan) -> list[list[str]]:
    """The grid as it will look after the write. Used for the preview and by the fake sheets client."""
    width = grid_width(rows)
    out = [[*r, *_blank_row(max(0, width - len(r)))] for r in rows]
    if plan.insert_at is not None:
        out = insert_blank(out, plan.insert_at, plan.count)
    for w in plan.writes:
        if w.skipped:
            continue
        while len(out) <= w.r:
            out.append(_blank_row(width))
        if len(out[w.r]) <= w.c:
            out[w.r].extend(_blank_row(w.c + 1 - len(out[w.r])))
        out[w.r][w.c] = w.value
    return out


def plan_cells(plan: Plan) -> list[str]:
    """A1 refs actually written, in write order. This is what lands in ``transfers.cells``."""
    return [w.ref for w in plan.writes if not w.skipped]


def plan_previous(rows: list[list[str]], plan: Plan) -> dict[str, str]:
    """Values the written cells held before the write, for undo.

    Inserted rows have no previous value; only a fill over existing content does.
    """
    if plan.mode in ("append", "add_row") or plan.insert_at is not None:
        return {}
    return {w.ref: cell(rows, w.r, w.c) for w in plan.writes if not w.skipped}
