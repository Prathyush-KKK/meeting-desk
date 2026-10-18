"""Step 4 - preview, write and undo.

Every write follows the same four beats: re-read the region, compare ``region_hash``, record the
intent (``app/write_batch.py`` - committed *before* Google is called, so a repeat of the same
``batch_id`` answers with the stored result and a refusal leaves a ``failed`` record with no point
deleted), one ``batchUpdate``. On a hash mismatch nothing is written; the caller gets 409 with the
fresh grid and a re-planned preview so the person can see the diff and decide.

Undo is guarded twice over: the cells the transfer wrote must still hold what it wrote, and an
inserted row must still hash to what it left there - otherwise deleting the row would take
somebody else's work with it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import notify
from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.config import Settings
from app.db import get_session
from app.google import get_google
from app.google.interface import DeleteRows, GoogleSuite, PermissionDenied
from app.models import Meeting, Point, Transfer, User
from app.routes.common import (
    TabState,
    get_clock,
    get_config,
    get_meeting,
    get_point,
    get_workbook,
    meeting_label,
    read_tab,
    require_editable,
)
from app.schemas import TransferExecuteIn, TransferPreviewIn, point_out, transfer_out
from app.sheets.layout import a1, region_hash, row_hash, row_values
from app.sheets.ops import plan_to_ops, rows_for_points
from app.sheets.planner import Plan, PointForSheet, plan_append, plan_cells, plan_fill, plan_previous
from app.telemetry import events
from app.telemetry.events import FailureReason
from app.telemetry.logs import get_logger, log_event
from app.write_batch import Replay, begin, check, fail, settle

router = APIRouter(prefix="/transfers", tags=["transfers"])

telemetry_log = get_logger("transfers")


def _for_sheet(point: Point, meeting: Meeting | None) -> PointForSheet:
    return PointForSheet(
        id=str(point.id),
        kind=point.kind,
        text=point.text,
        owner=point.owner_text or "",
        due=point.due_text or "",
        status=point.status,
        meeting_label=meeting_label(meeting),
        # The date post-processing resolved when the point was made. A date column is written from
        # this, never from re-reading "by EOW" months later against today.
        due_date=point.due_date.date() if point.due_date else None,
    )


def plan_rows(plan: Plan) -> list[int]:
    """The existing rows this plan writes over, so the guard hashes exactly those as well.

    Only a Custom fill has any: an append or an Add row writes into rows that do not exist yet, and
    where they go - directly after the table - is inside the guarded region by construction. A fill
    can be anchored anywhere, including far below the region, which is the case the region digest
    on its own could not see.
    """
    if plan.mode != "fill" or plan.insert_at is not None:
        return []
    return sorted({w.r for w in plan.writes if not w.skipped})


def guard_hash(state: TabState, plan: Plan) -> str:
    """The region digest the preview hands out and the write compares against."""
    return region_hash(state.read.values, state.layout, plan_rows(plan))


def _load_points(db: Session, ids: list[str]) -> list[Point]:
    points = [get_point(db, pid) for pid in ids]
    if not points:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick at least one point to transfer.")
    return points


def _build_plan(state: TabState, body: TransferPreviewIn, points: list[PointForSheet]) -> Plan:
    values = state.read.values
    dropdowns = state.read.dropdowns
    if body.mode == "append":
        if state.layout.header_row < 0 and state.layout.header_score >= 2:  # pragma: no cover
            raise HTTPException(status.HTTP_409_CONFLICT, "No header row was found; use Custom fill.")
        return plan_append(values, dropdowns, points, layout=state.layout)
    if body.anchor is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Custom fill needs an anchor cell.")
    if state.layout.header_row >= 0 and body.anchor.r <= state.layout.header_row:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The anchor is in or above the header row. Pick a cell below it."
        )
    return plan_fill(
        values,
        dropdowns,
        points,
        (body.anchor.r, body.anchor.c),
        body.write_keys,
        body.conflict,
        layout=state.layout,
    )


def _preview_payload(state: TabState, plan: Plan, points: list[Point]) -> dict[str, Any]:
    rows = rows_for_points(plan, len(points))
    by_point = []
    for point, row in zip(points, rows, strict=True):
        cells = [w.ref for w in plan.writes if w.r == row and not w.skipped]
        by_point.append({"point_id": str(point.id), "row": row, "cells": cells})
    return {
        "plan": plan.to_dict(),
        "per_point": by_point,
        "region_hash": guard_hash(state, plan),
        "read_at": state.read_at.isoformat(),
        "tab": {
            "workbook_id": str(state.workbook.id),
            "sheet_id": state.read.sheet_id,
            "title": state.read.title,
            "values": state.read.values,
        },
        "warnings": _warnings(state, plan),
    }


def _count(n: int, one: str, many: str) -> str:
    """ "1 cell", "3 cells" - the preview is read by people, so no "1 cell(s)"."""
    return f"{n} {one if n == 1 else many}"


def _warnings(state: TabState, plan: Plan) -> list[str]:
    out = []
    if plan.unmapped:
        n = len(plan.unmapped)
        out.append(
            f"{_count(n, 'point has', 'points have')} a status the column's dropdown does not allow; "
            f"{'that cell stays' if n == 1 else 'those cells stay'} blank."
        )
    if state.layout.formula_cols:
        cols = state.layout.formula_cols
        letters = ", ".join(a1(0, c)[:-1] for c in cols)
        if len(cols) == 1:
            out.append(f"Column {letters} holds a formula; it is never written, only copied down.")
        else:
            out.append(f"Columns {letters} hold formulas; they are never written, only copied down.")
    if plan.conflicts:
        out.append(f"{_count(len(plan.conflicts), 'cell already has', 'cells already have')} content.")
    if not state.workbook.can_edit:
        out.append("This workbook is connected read-only.")
    return out


@router.post("/preview")
def preview(
    body: TransferPreviewIn,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    workbook = get_workbook(db, body.workbook_id)
    state = read_tab(db, google, workbook, body.sheet_id, clock)
    points = _load_points(db, body.point_ids)
    meetings = {p.meeting_id: db.get(Meeting, p.meeting_id) for p in points}
    plan = _build_plan(state, body, [_for_sheet(p, meetings[p.meeting_id]) for p in points])
    return _preview_payload(state, plan, points)


@router.post("/execute")
def execute(
    body: TransferExecuteIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    # Before anything else: a repeat of a write that already landed answers with what it answered
    # then. Its points are gone, so every line below this would fail on them.
    guarded = body.model_dump(mode="json", exclude={"batch_id", "region_hash"})
    try:
        check(db, body.batch_id, guarded)
    except Replay as replay:
        return replay.result

    workbook = get_workbook(db, body.workbook_id)
    connection_email = require_editable(db, workbook, google)
    points = _load_points(db, body.point_ids)
    meetings = {p.meeting_id: db.get(Meeting, p.meeting_id) for p in points}

    if not body.allow_repeat:
        repeats = _already_transferred(db, points, workbook.id)
        if repeats:
            log_event(
                telemetry_log,
                events.TRANSFER_CONFLICT,
                level=logging.WARNING,
                reason="already_transferred",
                points=len(repeats),
                failure_reason=FailureReason.CONFLICT,
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": "Some of these points went across before. Confirm to send them again.",
                    "point_ids": repeats,
                },
            )

    # The re-read guard.
    state = read_tab(db, google, workbook, body.sheet_id, clock)
    for_sheet = [_for_sheet(p, meetings[p.meeting_id]) for p in points]
    plan = _build_plan(state, body, for_sheet)
    if body.region_hash != guard_hash(state, plan):
        log_event(
            telemetry_log,
            events.TRANSFER_CONFLICT,
            level=logging.WARNING,
            reason="region_hash_changed",
            failure_reason=FailureReason.CONFLICT,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "The tab changed since the preview. Here it is again with the plan rebuilt.",
                "expected_region_hash": body.region_hash,
                **_preview_payload(state, plan, points),
            },
        )

    now = clock.now()
    batch_id = body.batch_id or uuid.uuid4()
    batch = begin(
        db,
        batch_id=batch_id,
        kind="transfer",
        actor=user.email,
        workbook_id=workbook.id,
        sheet_id=body.sheet_id,
        payload=guarded,
        now=now,
    )

    previous = plan_previous(state.read.values, plan)
    ops = plan_to_ops(plan, body.sheet_id)
    try:
        google.sheets.batch_update(connection_email, workbook.spreadsheet_id, ops)
    except PermissionDenied as exc:
        fail(db, batch_id, f"{exc} ({exc.detail})", now)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{exc} ({exc.detail})") from exc
    except Exception as exc:
        fail(db, batch_id, str(exc), now)
        raise

    # The rows as they are now: the undo guard hashes the whole row, and only a read shows what a
    # copied-down formula computed into it.
    fresh = read_tab(db, google, workbook, body.sheet_id, clock)
    rows = rows_for_points(plan, len(points))
    inserted = plan.mode in ("append", "add_row") or plan.insert_at is not None
    records: list[Transfer] = []
    for point, row in zip(points, rows, strict=True):
        written = {w.ref: w.value for w in plan.writes if w.r == row and not w.skipped}
        meeting = meetings[point.meeting_id]
        record = Transfer(
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
                "row": row,
                # Names, for the meeting's history: a sheet id means nothing to a person.
                "workbook_name": workbook.name,
                "sheet_title": fresh.read.title,
                "row_hash": row_hash(fresh.read.values, row, fresh.layout) if inserted else "",
            },
            workbook_id=workbook.id,
            sheet_id=body.sheet_id,
            mode=plan.mode,
            cells=list(written.keys()),
            previous={ref: value for ref, value in previous.items() if ref in written},
        )
        db.add(record)
        records.append(record)

    for point in points:
        db.delete(point)
    db.flush()

    for meeting in {m.id: m for m in meetings.values() if m}.values():
        remaining = db.scalar(
            select(Point.id)
            .where(Point.meeting_id == meeting.id, Point.deleted_at.is_(None), Point.lifecycle == "active")
            .limit(1)
        )
        meeting.step = "done" if remaining is None else "points"

    log(
        db,
        user.email,
        f"Transferred {_count(len(points), 'point', 'points')} to {state.read.title} in {workbook.name}",
    )
    db.flush()
    result = {
        "batch_id": str(batch_id),
        "mode": plan.mode,
        "cells": plan_cells(plan),
        "transfers": [transfer_out(t) for t in records],
        "undo_until": (now + timedelta(minutes=settings.transfer_undo_minutes)).isoformat(),
        "tab": fresh.to_dict(),
    }
    if settings.notify_webhook_url:
        # After the response, and never in the way of it: the rows are in the sheet either way.
        text = notify.transfer_message(
            actor=user.name or user.email,
            workbook_name=workbook.name,
            sheet_title=fresh.read.title,
            sheet_url=workbook.url or f"https://docs.google.com/spreadsheets/d/{workbook.spreadsheet_id}",
            meeting_titles=sorted({m.title for m in meetings.values() if m and m.title}),
            points=[{"text": t.point_text, **_owner_due(t)} for t in records],
        )
        transport = getattr(request.app.state, "notify_transport", None)
        background.add_task(notify.post, settings.notify_webhook_url, text, transport)
    return settle(db, batch, result, now)


def _owner_due(record: Transfer) -> dict[str, str]:
    point = (record.snapshot or {}).get("point") or {}
    return {"owner": str(point.get("owner_text") or ""), "due": str(point.get("due_text") or "")}


def _already_transferred(db: Session, points: list[Point], workbook_id: uuid.UUID) -> list[str]:
    """Which of these points went into this workbook before.

    Indexed on ``transfers.text_norm`` and scoped to the workbook: the question is "is this row
    already in that sheet", and the answer must not get slower every time anyone transfers
    anything anywhere.
    """
    norms = {p.text_norm for p in points if p.text_norm}
    if not norms:
        return []
    seen = set(
        db.scalars(
            select(Transfer.text_norm).where(
                Transfer.workbook_id == workbook_id,
                Transfer.undone_at.is_(None),
                Transfer.text_norm.in_(norms),
            )
        ).all()
    )
    return sorted({str(p.id) for p in points if p.text_norm in seen})


@router.get("")
def list_transfers(
    workbook_id: str | None = None,
    meeting_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    """The log, newest first. ``can_undo`` says whether ``POST /{batch_id}/undo`` is still open for
    that line, by the server's clock - the Sheets page offers Undo on it rather than only in a
    toast that is gone after ten seconds, and the browser's clock is not the one that decides."""
    query = select(Transfer).order_by(Transfer.at.desc()).limit(limit)
    if workbook_id:
        query = query.where(Transfer.workbook_id == get_workbook(db, workbook_id).id)
    if meeting_id:
        # A meeting's own history: what left it, for which sheet, and whether it came back.
        query = query.where(Transfer.meeting_id == get_meeting(db, meeting_id).id)
    now = clock.now()
    window = timedelta(minutes=settings.transfer_undo_minutes)
    return [
        {**transfer_out(t), "can_undo": t.undone_at is None and now - _aware(t.at) <= window}
        for t in db.scalars(query).all()
    ]


@router.post("/{batch_id}/undo")
def undo(
    batch_id: str,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_config),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """Within 10 minutes: inserted rows go if untouched, filled cells go back to ``previous``."""
    try:
        batch = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown transfer") from exc
    records = list(db.scalars(select(Transfer).where(Transfer.batch_id == batch)).all())
    if not records:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown transfer")
    if any(t.undone_at for t in records):
        raise HTTPException(status.HTTP_409_CONFLICT, "That transfer was already undone.")

    now = clock.now()
    at = _aware(records[0].at)
    if now - at > timedelta(minutes=settings.transfer_undo_minutes):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Undo is only available for {settings.transfer_undo_minutes} minutes after a transfer.",
        )

    workbook = get_workbook(db, str(records[0].workbook_id))
    sheet_id = records[0].sheet_id
    connection_email = require_editable(db, workbook, google)
    state = read_tab(db, google, workbook, sheet_id, clock)

    written: dict[str, str] = {}
    rows: set[int] = set()
    for record in records:
        snapshot = record.snapshot or {}
        written.update(snapshot.get("written") or {})
        if snapshot.get("row") is not None:
            rows.add(int(snapshot["row"]))

    current = google.sheets.read_cells(connection_email, workbook.spreadsheet_id, sheet_id, list(written))
    changed = {ref: current.get(ref, "") for ref, value in written.items() if current.get(ref, "") != value}
    if changed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "Those cells have been edited since the transfer, so undo would lose work.",
                "changed": changed,
            },
        )

    mode = records[0].mode
    if mode in ("append", "add_row"):
        # The cells the transfer wrote are untouched, but the row is deleted whole: anything
        # somebody has since put in its *other* columns would go with it. The row hash taken at
        # write time is the only thing that can see that.
        touched = _touched_rows(records, state)
        if touched:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": "Those rows have been filled in since the transfer, so undo would delete "
                    "somebody's work. Remove the rows in Google Sheets if that is what you want.",
                    "rows": touched,
                },
            )
    if mode in ("append", "add_row"):
        ops = [DeleteRows(sheet_id=sheet_id, at=min(rows), count=len(rows))]
    else:
        from app.google.interface import SetCell
        from app.sheets.layout import parse_a1

        ops = []
        for record in records:
            for ref, value in (record.previous or {}).items():
                r, c = parse_a1(ref)
                ops.append(SetCell(sheet_id=sheet_id, row=r, col=c, value=value))
            for ref in record.cells or []:
                if ref not in (record.previous or {}):
                    r, c = parse_a1(ref)
                    ops.append(SetCell(sheet_id=sheet_id, row=r, col=c, value=""))
    google.sheets.batch_update(connection_email, workbook.spreadsheet_id, ops)

    restored = []
    for record in records:
        record.undone_at = now
        snapshot = (record.snapshot or {}).get("point") or {}
        if snapshot:
            restored.append(_restore_point(db, record, snapshot))
    log(db, user.email, f"Undid a transfer to {state.read.title}")
    db.flush()
    return {
        "ok": True,
        "batch_id": batch_id,
        "restored_points": [point_out(p) for p in restored],
        "tab": read_tab(db, google, workbook, sheet_id, clock).to_dict(),
    }


def _touched_rows(records: list[Transfer], state: TabState) -> dict[str, list[str]]:
    """The inserted rows whose contents no longer hash to what the transfer left there."""
    out: dict[str, list[str]] = {}
    for record in records:
        snapshot = record.snapshot or {}
        row = snapshot.get("row")
        expected = snapshot.get("row_hash")
        if row is None or not expected:
            continue
        row = int(row)
        if row_hash(state.read.values, row, state.layout) != expected:
            out[str(row + 1)] = row_values(state.read.values, row, state.layout)
    return out


def _restore_point(db: Session, record: Transfer, snapshot: dict[str, Any]) -> Point:
    """The snapshot is why a transferred point can come back on undo.

    The row may already be there: undo is replayable in the sense that a point removed by a
    transfer that is later undone twice (two tabs, a retry) must not try to insert the same primary
    key a second time - that was a 500. Every field the snapshot carries comes back with it,
    ``due_date`` and ``extraction_id`` included, or the restored point would quietly lose its date.
    """
    point_id = uuid.UUID(snapshot["id"])
    point = db.get(Point, point_id)
    if point is None:
        point = Point(id=point_id, meeting_id=record.meeting_id)
        db.add(point)
    point.meeting_id = record.meeting_id
    point.extraction_id = _as_uuid(snapshot.get("extraction_id"))
    point.kind = snapshot.get("kind", "action")
    point.text = snapshot.get("text", "")
    point.text_norm = (record.snapshot or {}).get("text_norm", "")
    point.evidence = snapshot.get("evidence", "")
    point.owner_text = snapshot.get("owner_text", "")
    point.owner_email = snapshot.get("owner_email")
    point.owner_ambiguous = bool(snapshot.get("owner_ambiguous"))
    point.due_text = snapshot.get("due_text", "")
    point.due_date = _as_datetime(snapshot.get("due_date"))
    point.status = snapshot.get("status", "open")
    point.workstream = snapshot.get("workstream", "")
    point.lifecycle = "active"
    point.deleted_at = None
    point.selected = False
    point.created_by = point.created_by or snapshot.get("updated_by", "")
    point.updated_by = snapshot.get("updated_by", "")
    return point


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, AttributeError, TypeError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def _aware(value: datetime) -> datetime:
    from app.tz import display_zone

    return value if value.tzinfo else value.replace(tzinfo=display_zone())
