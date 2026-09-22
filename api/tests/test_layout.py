"""Layout detection, checked cell-for-cell against the TypeScript reference's own output."""

from __future__ import annotations

import pytest

from app.sheets.layout import (
    a1,
    col_letter,
    detect_date_cols,
    detect_formula_cols,
    detect_layout,
    match_field,
    next_keys,
    norm,
    parse_a1,
    region_hash,
)
from tests.sheet_fixtures import NAMES, load


@pytest.mark.parametrize("name", NAMES)
def test_layout_matches_reference(name: str) -> None:
    fx = load(name)
    layout = detect_layout(fx.rows)
    want = fx.expect["layout"]
    assert layout.header_row == want["header_row"], name
    assert layout.first_col == want["first_col"]
    assert layout.last_col == want["last_col"]
    assert layout.columns == dict(want["columns"])
    assert layout.key_col == want["key_col"]
    assert layout.key_prefix == want["key_prefix"]
    assert layout.last_table_row == want["last_table_row"]
    assert layout.header_score == want["header_score"]


@pytest.mark.parametrize("name", NAMES)
def test_next_keys_matches_reference(name: str) -> None:
    fx = load(name)
    layout = detect_layout(fx.rows)
    assert next_keys(fx.rows, layout, 3) == fx.expect["next_keys"]


def test_banner_rows_do_not_win_the_header() -> None:
    fx = load("headers_row_9_banner")
    layout = detect_layout(fx.rows)
    assert layout.header_row == 8
    # The stray note two rows below the last task is outside the table.
    assert layout.last_table_row == 15
    assert layout.key_prefix == "T"


def test_lower_of_two_header_rows_wins_when_it_scores_higher() -> None:
    fx = load("two_header_rows")
    layout = detect_layout(fx.rows)
    assert layout.header_row == 1
    assert layout.columns["task"] == 1


def test_no_header_falls_back_to_content_extent() -> None:
    layout = detect_layout(load("no_header").rows)
    assert layout.header_row == -1
    assert layout.key_col == -1
    assert layout.last_table_row == 1


def test_task_keyed_tab_has_no_key_column() -> None:
    layout = detect_layout(load("task_keyed_no_id").rows)
    assert layout.key_col == -1
    assert layout.columns["task"] == 0
    assert next_keys(load("task_keyed_no_id").rows, layout, 2) == ["", ""]


def test_col_letter_and_a1_round_trip() -> None:
    assert [col_letter(i) for i in (0, 1, 25, 26, 27, 51, 52)] == ["A", "B", "Z", "AA", "AB", "AZ", "BA"]
    assert a1(0, 0) == "A1"
    assert a1(9, 2) == "C10"
    assert parse_a1("C10") == (9, 2)
    assert parse_a1("AA1") == (0, 26)
    with pytest.raises(ValueError):
        parse_a1("C")


def test_norm_and_match_field() -> None:
    assert norm("  Due  Date! ") == "due date"
    assert match_field("Assigned To") == "owner"
    assert match_field("Target") == "due"
    assert match_field("Workstream") is None
    assert match_field("") is None
    assert match_field("P") == "priority"  # exact synonym
    assert match_field("Sprint P") is None  # the suffix rule needs a word longer than two characters
    assert match_field("Target Date") == "due"  # suffix rule
    assert match_field("Open Question") == "question"


def test_reader_hooks_find_formula_and_date_columns() -> None:
    fx = load("formula_col")
    assert detect_formula_cols(fx.formulas, header_row=0) == [4, 5]
    date_fx = load("date_col")
    assert detect_date_cols(date_fx.number_formats, header_row=0) == [3]


def test_region_hash_tracks_only_the_table_region() -> None:
    fx = load("headers_row_9_banner")
    rows = fx.rows
    base = region_hash(rows)
    # A change outside the region (a banner line) leaves the digest alone.
    outside = [list(r) for r in rows]
    outside[1][1] = "changed banner text"
    assert region_hash(outside) == base
    # A change inside it does not.
    inside = [list(r) for r in rows]
    inside[9][2] = "Someone Else"
    assert region_hash(inside) != base
