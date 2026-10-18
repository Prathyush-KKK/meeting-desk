"""The Sheets page - in-place edits and Add row.

Saving re-reads the edited cells first: if any moved since they were shown, nothing is written and
both values come back so the person picks one. Only cells inside the table may be saved - the
header row names the columns the layout is read from, and below the last row is Add row's job.
Add row uses the same planner as Step 4 with a one-row plan at a chosen index, so a row can land
inside a section instead of at the table's end.

Both take a client ``batch_id`` and go through ``app/write_batch.py``, so a retry answers with the
result the first attempt gave rather than writing a second time.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.google import get_google
from app.google.interface import GoogleSuite, PermissionDenied, SetCell
from app.models import Meeting, Point, SheetEdit, Transfer, User
from app.routes.common import (
    TabState,
    get_clock,
    get_config,
    get_point,
    get_workbook,
    meeting_label,
    read_tab,
    require_editable,
)
from app.routes.transfers import _for_sheet
from app.schemas import AddRowIn, SheetSaveIn, point_out, sheet_edit_out, transfer_out
from app.sheets.layout import match_field, norm, parse_a1, row_hash
from app.sheets.ops import plan_to_ops
from app.sheets.planner import plan_add_row, plan_cells
from app.telemetry import events
from app.telemetry.events import FailureReason
from app.telemetry.logs import get_logger, log_event
from app.write_batch import Replay, begin, check, fail, settle

router = APIRouter(prefix="/sheets", tags=["sheets"])

telemetry_log = get_logger("sheets")


@router.post("/save")
def save_edits(
    body: SheetSaveIn,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    if not body.edits:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to save.")
    # A repeat of a save that landed answers with what it answered then: the cells now hold the new
    # values, so the pre-save re-read below would report a clash against the person's own write.
    guarded = body.model_dump(mode="json", exclude={"batch_id"})
    try:
        check(db, body.batch_id, guarded)
    except Replay as replay:
        return replay.result

    workbook = get_workbook(db, body.workbook_id)
    connection_email = require_editable(db, workbook, google)
    state = read_tab(db, google, workbook, body.sheet_id, clock)

    _reject_protected_cells(state, [e.cell for e in body.edits])
    _reject_cells_outside_the_table(state, [e.cell for e in body.edits])

    refs = [e.cell for e in body.edits]
    current = google.sheets.read_cells(connection_email, workbook.spreadsheet_id, body.sheet_id, refs)
    clashes = [
        {"cell": e.cell, "yours": e.after, "theirs": current.get(e.cell, ""), "was": e.before}
        for e in body.edits
        if current.get(e.cell, "") != e.before
    ]
    if clashes:
        log_event(
            telemetry_log,
            events.SHEETS_WRITE_CONFLICT,
            level=logging.WARNING,
            cells=len(clashes),
            failure_reason=FailureReason.CONFLICT,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "Some of these cells changed in Google Sheets while you were editing. Pick one.",
                "clashes": clashes,
                "read_at": state.read_at.isoformat(),
            },
        )

    ops = []
    for edit in body.edits:
        r, c = parse_a1(edit.cell)
        ops.append(
            SetCell(
                sheet_id=body.sheet_id,
                row=r,
                col=c,
                value=edit.after,
                as_date=c in state.layout.date_cols,
            )
        )

    now = clock.now()
    batch_id = body.batch_id or uuid.uuid4()
    batch = begin(
        db,
        batch_id=batch_id,
        kind="sheet_save",
        actor=user.email,
        workbook_id=workbook.id,
        sheet_id=body.sheet_id,
        payload=guarded,
        now=now,
    )

    try:
        google.sheets.batch_update(connection_email, workbook.spreadsheet_id, ops)
    except PermissionDenied as exc:
        fail(db, batch_id, f"{exc} ({exc.detail})", now)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{exc} ({exc.detail})") from exc
    except Exception as exc:
        fail(db, batch_id, str(exc), now)
        raise

    rows = []
    for edit in body.edits:
        row = SheetEdit(
            at=now,
            actor=user.email,
            workbook_id=workbook.id,
            sheet_id=body.sheet_id,
            cell=edit.cell,
            before=current.get(edit.cell, ""),
            after=edit.after,
            batch_id=batch_id,
        )
        db.add(row)
        rows.append(row)
    log(db, user.email, f"Saved {len(rows)} cell(s) on {state.read.title}")
    db.flush()
    result = {
        "ok": True,
        "batch_id": str(batch_id),
        "edits": [sheet_edit_out(r) for r in rows],
        "tab": read_tab(db, google, workbook, body.sheet_id, clock).to_dict(),
    }
    return settle(db, batch, result, now)


def _reject_protected_cells(state: TabState, refs: list[str]) -> None:
    """Key and formula columns are not editable; the cell says why."""
    for ref in refs:
        _, c = parse_a1(ref)
        if c in state.layout.formula_cols:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{ref} is in a formula column and is not editable here."
            )
        if state.layout.key_col >= 0 and c == state.layout.key_col:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{ref} is in the key column and is not editable here."
            )


def _reject_cells_outside_the_table(state: TabState, refs: list[str]) -> None:
    """The grid shows the header and some blank rows under the table; neither is editable here.

    Renaming a column from the Sheets page would silently re-map every write that follows it, and a
    value below the last row is not part of the table the layout was detected from. Both belong in
    Google Sheets, or in Add row, which extends the table on purpose.
    """
    layout = state.layout
    for ref in refs:
        r, _ = parse_a1(ref)
        if layout.header_row >= 0 and r <= layout.header_row:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{ref} is in or above the header row. Column names are changed in Google Sheets.",
            )
        if r > layout.last_table_row:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{ref} is below the last row of the table (row {layout.last_table_row + 1}). "
                "Use Add row to put a row in.",
            )


@router.get("/edits")
def list_edits(
    workbook_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_session),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    query = select(SheetEdit).order_by(SheetEdit.at.desc()).limit(limit)
    if workbook_id:
        query = query.where(SheetEdit.workbook_id == get_workbook(db, workbook_id).id)
    return [sheet_edit_out(e) for e in db.scalars(query).all()]


def _column_for(state: TabState, key: str) -> int | None:
    """Add row's form is built from headers, so values come back keyed by header text."""
    if key.isdigit():
        return int(key)
    header_row = state.layout.header_row
    if header_row >= 0:
        header = state.read.values[header_row]
        wanted = norm(key)
        for c, cell in enumerate(header):
            if norm(cell) == wanted:
                return c
        field = match_field(key)
        if field is not None and field in state.layout.columns:
            return state.layout.columns[field]
    return None


@router.post("/add-row")
def add_row(
    body: AddRowIn,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """A form row or a point, after the table by default or above a clicked row."""
    # A repeat answers with the stored result: the row is in, and the point it came from is gone.
    guarded = body.model_dump(mode="json", exclude={"batch_id", "region_hash"})
    try:
        check(db, body.batch_id, guarded)
    except Replay as replay:
        return replay.result

    workbook = get_workbook(db, body.workbook_id)
    connection_email = require_editable(db, workbook, google)
    state = read_tab(db, google, workbook, body.sheet_id, clock)
    # Always compared - the schema makes the digest mandatory, so there is no "no hash, no guard".
    if body.region_hash != state.region_hash:
        log_event(
            telemetry_log,
            events.SHEETS_WRITE_CONFLICT,
            level=logging.WARNING,
            reason="region_hash_changed",
            failure_reason=FailureReason.CONFLICT,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "The tab changed since it was read. Here it is again.",
                "tab": state.to_dict(),
            },
        )

    at: int | None = None
    if body.position.mode == "above":
        if body.position.row is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Click the row to insert above.")
        if state.layout.header_row >= 0 and body.position.row <= state.layout.header_row:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That row is in or above the header. Pick a row inside the table."
            )
        if body.position.row > state.layout.last_table_row + 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"That row is below the table (it ends at row {state.layout.last_table_row + 1}). "
                "Insert after the table instead.",
            )
        at = body.position.row

    point: Point | None = None
    meeting: Meeting | None = None
    if body.point_id:
        point = get_point(db, body.point_id)
        meeting = db.get(Meeting, point.meeting_id)

    values: dict[int, str] = {}
    unknown: list[str] = []
    for key, value in body.values.items():
        col = _column_for(state, key)
        if col is None:
            unknown.append(key)
            continue
        values[col] = value
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"No column matches: {', '.join(sorted(unknown))}."
        )
    if point is None and not values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Fill at least one field.")

    plan = plan_add_row(
        state.read.values,
        state.read.dropdowns,
        point=_for_sheet(point, meeting) if point else None,
        values=values,
        at=at,
        layout=state.layout,
    )

    now = clock.now()
    batch_id = body.batch_id or uuid.uuid4()
    batch = begin(
        db,
        batch_id=batch_id,
        kind="add_row",
        actor=user.email,
        workbook_id=workbook.id,
        sheet_id=body.sheet_id,
        payload=guarded,
        now=now,
    )

    try:
        google.sheets.batch_update(
            connection_email, workbook.spreadsheet_id, plan_to_ops(plan, body.sheet_id)
        )
    except PermissionDenied as exc:
        fail(db, batch_id, f"{exc} ({exc.detail})", now)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{exc} ({exc.detail})") from exc
    except Exception as exc:
        fail(db, batch_id, str(exc), now)
        raise

    fresh = read_tab(db, google, workbook, body.sheet_id, clock)
    written = {w.ref: w.value for w in plan.writes if not w.skipped}
    transfer = None
    if point is not None:
        # A point used this way is transferred: logged, then removed.
        transfer = Transfer(
            batch_id=batch_id,
            at=now,
            actor=user.email,
            meeting_id=point.meeting_id,
            meeting_title=meeting.title if meeting else "",
            point_text=point.text,
            text_norm=point.text_norm or "",
            snapshot={
                "point": point_out(point),
                "text_norm": point.text_norm,
                "written": written,
                "row": plan.insert_at,
                "row_hash": row_hash(fresh.read.values, plan.insert_at, fresh.layout),
            },
            workbook_id=workbook.id,
            sheet_id=body.sheet_id,
            mode="add_row",
            cells=list(written),
            previous={},
        )
        db.add(transfer)
        db.delete(point)
    else:
        for ref, value in written.items():
            db.add(
                SheetEdit(
                    at=now,
                    actor=user.email,
                    workbook_id=workbook.id,
                    sheet_id=body.sheet_id,
                    cell=ref,
                    before="",
                    after=value,
                    batch_id=batch_id,
                )
            )
    label = meeting_label(meeting) if meeting else state.read.title
    log(db, user.email, f"Added a row to {state.read.title}" + (f" from {label}" if point else ""))
    db.flush()
    result = {
        "ok": True,
        "batch_id": str(batch_id),
        "insert_at": plan.insert_at,
        "keys": plan.keys,
        "cells": plan_cells(plan),
        "transfer": transfer_out(transfer) if transfer else None,
        "tab": fresh.to_dict(),
    }
    return settle(db, batch, result, now)
