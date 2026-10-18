"""Google access: one Protocol suite, two implementations, chosen by config."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request

from app.config import Settings
from app.google.fake import FakeGoogle
from app.google.interface import GoogleSuite
from app.google.real import RealGoogle

__all__ = ["FakeGoogle", "GoogleSuite", "RealGoogle", "build_google", "get_google"]


def build_google(
    settings: Settings,
    database: Any = None,
    transport: httpx.BaseTransport | None = None,
    wall_clock: Any = None,
) -> GoogleSuite:
    if settings.fake_google:
        return FakeGoogle()
    return RealGoogle.from_settings(settings, database, transport=transport, wall_clock=wall_clock)


def get_google(request: Request) -> GoogleSuite:
    return request.app.state.google
