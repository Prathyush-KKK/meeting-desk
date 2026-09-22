"""The workbook registry.

Any allow-listed person may connect a workbook. The title and tabs are read through whichever admin
connection can see it, then every admin connection is tried for ``can_edit`` and the first that can
becomes the workbook's connection. None means the workbook is saved read-only with a message naming
the accounts to share with.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import log
from app.auth.deps import authenticate
from app.clock import Clock
from app.db import get_session
from app.google import get_google
from app.google.interface import GoogleSuite
from app.models import User, Workbook
from app.routes.common import (
    admin_emails,
    get_clock,
    get_workbook,
    healthy_connections,
    pick_for,
    read_tab,
    spreadsheet_id_from_url,
)
from app.schemas import WorkbookConnectIn, workbook_out

router = APIRouter(prefix="/workbooks", tags=["workbooks"])


def _tabs_out(google: GoogleSuite, email: str, spreadsheet_id: str) -> list[dict[str, Any]]:
    meta = google.sheets.get_spreadsheet(email, spreadsheet_id)
    return [{"sheet_id": t.sheet_id, "title": t.title, "index": t.index} for t in meta.tabs]


@router.post("/connect", status_code=status.HTTP_201_CREATED)
def connect(
    body: WorkbookConnectIn,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    spreadsheet_id = spreadsheet_id_from_url(body.url)
    connections = healthy_connections(db)
    if not connections:
        raise HTTPException(status.HTTP_409_CONFLICT, "No Google account is connected yet. Ask an admin.")

    pick = pick_for(
        db, [c.email for c in connections], lambda email: google.sheets.get_spreadsheet(email, spreadsheet_id)
    )
    if not pick.ok:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No admin account can open that workbook. Share it with "
            f"{', '.join(c.email for c in connections)} and try again. ({pick.detail})",
        )
    reader_email: str = pick.email
    meta = pick.value

    editor = next((c for c in connections if google.sheets.can_edit(c.email, spreadsheet_id)), None)

    workbook = db.scalar(select(Workbook).where(Workbook.spreadsheet_id == spreadsheet_id))
    if workbook is None:
        workbook = Workbook(spreadsheet_id=spreadsheet_id, connected_by=user.email)
        db.add(workbook)
    workbook.deleted_at = None
    workbook.name = meta.title
    workbook.url = meta.url or body.url
    workbook.connection_id = editor.id if editor else None
    workbook.can_edit = editor is not None
    workbook.last_error = None if editor else "read-only: no admin connection can edit it"
    db.flush()

    tabs = [{"sheet_id": t.sheet_id, "title": t.title, "index": t.index} for t in meta.tabs]
    log(db, user.email, f"Connected workbook {workbook.name}")
    share_request = ""
    if editor is None:
        accounts = ", ".join(c.email for c in connections)
        share_request = (
            f"Please give edit access to {accounts} on {meta.title} "
            f"({meta.url}) so Meeting Desk can write to it."
        )
    return {
        **workbook_out(workbook, tabs),
        "read_through": reader_email,
        "share_request": share_request,
        "needs_edit_access_from": [] if editor else [c.email for c in connections],
    }


@router.get("")
def list_workbooks(
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    user: User = Depends(authenticate),
) -> list[dict[str, Any]]:
    out = []
    emails = admin_emails(db)
    for workbook in db.scalars(
        select(Workbook).where(Workbook.deleted_at.is_(None)).order_by(Workbook.connected_at)
    ).all():
        pick = pick_for(db, emails, lambda email, wb=workbook: _tabs_out(google, email, wb.spreadsheet_id))
        out.append(workbook_out(workbook, pick.value if pick.ok else []))
    return out


@router.get("/{workbook_id}")
def get_one(
    workbook_id: str,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    workbook = get_workbook(db, workbook_id)
    pick = pick_for(db, admin_emails(db), lambda email: _tabs_out(google, email, workbook.spreadsheet_id))
    return workbook_out(workbook, pick.value if pick.ok else [])


@router.get("/{workbook_id}/tabs/{sheet_id}")
def read_one_tab(
    workbook_id: str,
    sheet_id: str,
    db: Session = Depends(get_session),
    google: GoogleSuite = Depends(get_google),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    """The live tab: values, layout, dropdowns, formula and date columns, and the region hash."""
    workbook = get_workbook(db, workbook_id)
    state = read_tab(db, google, workbook, sheet_id, clock)
    return {**state.to_dict(), "workbook": workbook_out(workbook)}


@router.delete("/{workbook_id}")
def disconnect(
    workbook_id: str,
    db: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    user: User = Depends(authenticate),
) -> dict[str, Any]:
    workbook = get_workbook(db, workbook_id)
    workbook.deleted_at = clock.now()
    log(db, user.email, f"Disconnected workbook {workbook.name}")
    return {"ok": True, "id": str(workbook.id)}
