"""Turning a plan into the one ``batchUpdate`` that carries it out."""

from __future__ import annotations

from app.google.interface import BatchOp, CopyFormula, InsertRows, SetCell
from app.sheets.planner import Plan


def plan_to_ops(plan: Plan, sheet_id: str) -> list[BatchOp]:
    """Insert first (formatting inherits from a data row), then formulas, then values."""
    ops: list[BatchOp] = []
    if plan.insert_at is not None and plan.count:
        ops.append(
            InsertRows(
                sheet_id=sheet_id,
                at=plan.insert_at,
                count=plan.count,
                inherit_from_before=inherits_from_above(plan),
            )
        )
    for fill in plan.formula_fill:
        ops.append(
            CopyFormula(
                sheet_id=sheet_id,
                col=fill.col,
                source_row=fill.source_row,
                target_rows=list(fill.target_rows),
            )
        )
    for write in plan.writes:
        if write.skipped:
            continue
        ops.append(
            SetCell(
                sheet_id=sheet_id,
                row=write.r,
                col=write.c,
                value=write.value,
                as_date=write.date,
                date_value=write.date_value,
            )
        )
    return ops


def inherits_from_above(plan: Plan) -> bool:
    """False when the row above the insert is the header (or nothing): inherit from below instead.

    A row inserted directly under the header would otherwise arrive wearing the header's bold,
    borders and fill - spec section 7, "Anchor in or above the header", and the same mistake one
    row lower.
    """
    at = plan.insert_at or 0
    if at <= 0:
        return False
    header_row = plan.layout.header_row if plan.layout else -1
    return not (header_row >= 0 and at - 1 <= header_row)


def rows_for_points(plan: Plan, count: int) -> list[int]:
    """Which grid row each point lands on."""
    inserted = plan.mode in ("append", "add_row")
    base = (plan.insert_at or 0) if inserted else (plan.anchor or {}).get("r", 0)
    return [base + i for i in range(count)]
