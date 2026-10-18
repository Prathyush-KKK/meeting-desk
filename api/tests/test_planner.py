"""Planner parity with the TypeScript reference, plus the server-only additions.

``expect`` in each fixture is what ``meeting-desk/src/lib/sheet.ts`` produced for the same grid,
points and anchor; ``with_hooks`` is hand-written for the formula/date behaviour the prototype does
not have.
"""

from __future__ import annotations

import pytest

from app.sheets.layout import detect_layout
from app.sheets.planner import (
    PointForSheet,
    apply_plan,
    map_status,
    plan_add_row,
    plan_append,
    plan_cells,
    plan_fill,
    plan_previous,
    values_for,
)
from tests.sheet_fixtures import NAMES, load

CONFLICTS = ["skip", "overwrite", "insert"]


def _writes(plan) -> list[dict]:
    return [
        {"ref": w.ref, "r": w.r, "c": w.c, "value": w.value, "kind": w.kind, "existing": w.existing}
        for w in plan.writes
    ]


# --- append --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_append_cells_match_reference(name: str) -> None:
    fx = load(name)
    plan = plan_append(fx.rows, fx.dropdowns, fx.points)
    want = fx.expect["append"]
    assert plan_cells(plan) == want["cells"], name
    assert plan.insert_at == want["insert_at"]
    assert plan.count == want["count"]
    assert plan.keys == want["keys"]
    assert _writes(plan) == want["writes"]
    assert plan.moved == want["moved"]


@pytest.mark.parametrize("name", NAMES)
def test_append_applied_grid_matches_reference(name: str) -> None:
    fx = load(name)
    plan = plan_append(fx.rows, fx.dropdowns, fx.points)
    assert apply_plan(fx.rows, plan) == fx.expect["append"]["applied"]


# --- fill ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("conflict", CONFLICTS)
def test_fill_cells_match_reference(name: str, conflict: str) -> None:
    fx = load(name)
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, fx.anchor, fx.write_keys, conflict)
    want = fx.expect["fill"][conflict]
    assert plan_cells(plan) == want["cells"], f"{name}/{conflict}"
    assert _writes(plan) == want["writes"]
    assert plan.conflicts == want["conflicts"]
    assert plan.field_order == want["field_order"]
    assert plan.insert_at == want["insert_at"]
    assert plan.count == want["count"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("conflict", CONFLICTS)
def test_fill_applied_grid_matches_reference(name: str, conflict: str) -> None:
    fx = load(name)
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, fx.anchor, fx.write_keys, conflict)
    assert apply_plan(fx.rows, plan) == fx.expect["fill"][conflict]["applied"]


def test_fill_skip_keeps_existing_values() -> None:
    fx = load("headers_row_9_banner")
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, (10, 1), True, "skip")
    assert plan.conflicts, "the anchor sits on existing rows"
    for w in plan.writes:
        if w.kind == "conflict":
            assert w.value == w.existing
            assert w.ref not in plan_cells(plan)
    after = apply_plan(fx.rows, plan)
    assert after[10][1] == fx.rows[10][1]


def test_fill_overwrite_replaces_existing_values() -> None:
    fx = load("headers_row_9_banner")
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, (10, 1), True, "overwrite")
    after = apply_plan(fx.rows, plan)
    assert after[10][1] == fx.points[0].text
    assert "B11" in plan_cells(plan)


def test_fill_insert_pushes_rows_down() -> None:
    fx = load("headers_row_9_banner")
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, (10, 1), True, "insert")
    assert plan.insert_at == 10
    assert plan.conflicts == []
    after = apply_plan(fx.rows, plan)
    assert len(after) == len(fx.rows) + 3
    assert after[10][1] == fx.points[0].text
    assert after[13][1] == fx.rows[10][1]  # the row that used to be at the anchor


# --- formula and date hooks ----------------------------------------------------------------------


def test_formula_columns_are_never_written() -> None:
    fx = load("formula_col")
    hooks = fx.with_hooks
    layout = detect_layout(fx.rows, formula_cols=fx.formula_cols, date_cols=fx.date_cols)
    plan = plan_append(fx.rows, fx.dropdowns, fx.points, layout=layout)
    assert plan_cells(plan) == hooks["append_cells"]
    assert [f.to_dict() for f in plan.formula_fill] == hooks["formula_fill"]
    assert all(w.c not in fx.formula_cols for w in plan.writes)
    # Without the hooks the planner is byte-for-byte the TypeScript reference again.
    assert plan_cells(plan_append(fx.rows, fx.dropdowns, fx.points)) == fx.expect["append"]["cells"]


def test_formula_columns_are_skipped_on_fill_too() -> None:
    fx = load("formula_col")
    layout = detect_layout(fx.rows, formula_cols=fx.formula_cols)
    plan = plan_fill(fx.rows, fx.dropdowns, fx.points, fx.anchor, fx.write_keys, "skip", layout=layout)
    assert plan_cells(plan) == fx.with_hooks["fill_skip_cells"]
    assert plan.conflicts == fx.with_hooks["fill_skip_conflicts"]


def test_date_columns_are_flagged_on_the_write() -> None:
    fx = load("date_col")
    layout = detect_layout(fx.rows, date_cols=fx.date_cols)
    plan = plan_append(fx.rows, fx.dropdowns, fx.points, layout=layout)
    assert plan_cells(plan) == fx.with_hooks["append_cells"]
    assert [w.ref for w in plan.writes if w.date] == fx.with_hooks["date_cells"]


# --- add row -------------------------------------------------------------------------------------


def test_add_row_after_the_table_by_default() -> None:
    fx = load("headers_row_9_banner")
    point = fx.points[0]
    plan = plan_add_row(fx.rows, fx.dropdowns, point=point)
    assert plan.mode == "add_row"
    assert plan.insert_at == 16
    assert plan.keys == ["T-108"]
    assert plan_cells(plan) == ["A17", "B17", "C17", "D17", "G17", "H17"]
    after = apply_plan(fx.rows, plan)
    assert after[16][0] == "T-108"
    assert after[16][1] == point.text


def test_add_row_above_a_clicked_row_lands_inside_the_section() -> None:
    fx = load("headers_row_9_banner")
    plan = plan_add_row(fx.rows, fx.dropdowns, point=fx.points[0], at=11)
    assert plan.insert_at == 11
    assert plan_cells(plan) == ["A12", "B12", "C12", "D12", "G12", "H12"]
    after = apply_plan(fx.rows, plan)
    assert after[11][1] == fx.points[0].text
    assert after[12][0] == "T-103"  # the row that was there is pushed down, not overwritten
    assert len(after) == len(fx.rows) + 1


def test_add_row_from_a_form_uses_the_given_columns() -> None:
    fx = load("headers_row_9_banner")
    plan = plan_add_row(fx.rows, fx.dropdowns, values={1: "Write the runbook", 2: "Noah S", 6: "open"})
    assert plan_cells(plan) == ["A17", "B17", "C17", "G17"]
    assert [w.value for w in plan.writes] == ["T-108", "Write the runbook", "Noah S", "open"]


def test_add_row_copies_formulas_from_the_row_above() -> None:
    fx = load("formula_col")
    layout = detect_layout(fx.rows, formula_cols=fx.formula_cols)
    plan = plan_add_row(fx.rows, fx.dropdowns, point=fx.points[0], at=2, layout=layout)
    assert [f.to_dict() for f in plan.formula_fill] == [
        {"col": 4, "source_row": 1, "target_rows": [2]},
        {"col": 5, "source_row": 1, "target_rows": [2]},
    ]
    assert all(w.c not in (4, 5) for w in plan.writes)


def test_add_row_without_a_key_column() -> None:
    fx = load("task_keyed_no_id")
    plan = plan_add_row(fx.rows, fx.dropdowns, values={0: "Refer a friend", 1: "150", 3: "planned"})
    assert plan.keys == [""]
    assert plan_cells(plan) == ["A5", "B5", "D5"]


# --- helpers -------------------------------------------------------------------------------------


def test_map_status_uses_the_columns_dropdown() -> None:
    assert map_status("in_progress") == "in progress"
    assert map_status("in_progress", ["Open", "In Progress", "Done"]) == "In Progress"
    assert map_status("open", ["Not started", "Doing", "Shipped"]) == "Not started"
    assert map_status("dropped", ["Open", "Done"]) == ""  # unmapped stays blank and is flagged


def test_unmapped_status_is_reported() -> None:
    fx = load("headers_row_1")
    plan = plan_append(fx.rows, fx.dropdowns, fx.points)
    # The Decisions tab's dropdown has no "blocked", so the risk point's status is left blank.
    assert plan.unmapped == ["p3"]


def test_values_for_routes_text_to_the_matching_column() -> None:
    rows = [["ID", "Decision", "Owner", "Status"], ["D-1", "something", "", "decided"]]
    layout = detect_layout(rows)
    decision = PointForSheet(id="x", kind="decision", text="Owner holds a person", status="decided")
    assert values_for(decision, layout, {})["decision"] == "Owner holds a person"
    action = PointForSheet(id="y", kind="action", text="Do the thing", status="open")
    assert values_for(action, layout, {})["task"] == "Do the thing"


def test_plan_previous_only_for_overwriting_plans() -> None:
    fx = load("headers_row_9_banner")
    append = plan_append(fx.rows, fx.dropdowns, fx.points)
    assert plan_previous(fx.rows, append) == {}
    fill = plan_fill(fx.rows, fx.dropdowns, fx.points, (10, 1), True, "overwrite")
    previous = plan_previous(fx.rows, fill)
    assert previous["B11"] == fx.rows[10][1]
