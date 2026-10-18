"""Every router the app mounts."""

from __future__ import annotations

from fastapi import APIRouter

from app.routes import admin, extract, meetings, notes, points, sheets, transfers, workbooks

ROUTERS: list[APIRouter] = [
    meetings.router,
    notes.router,
    extract.router,
    points.router,
    workbooks.router,
    transfers.router,
    sheets.router,
    admin.router,
]

__all__ = ["ROUTERS"]
