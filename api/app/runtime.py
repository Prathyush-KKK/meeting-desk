"""Everything a process needs to do the app's work, built once from settings.

The API hangs these off ``app.state``; a procrastinate worker builds the same ``Runtime`` and
runs the job functions against it. One place to construct them means a job and a route see the
same database, clock, Google suite and extraction provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.clock import Clock, build_clock
from app.config import Settings
from app.db import Database
from app.extract import build_provider
from app.extract.provider import ExtractionProvider
from app.google import build_google
from app.google.interface import GoogleSuite


@dataclass(slots=True)
class Runtime:
    settings: Settings
    db: Database
    clock: Clock
    google: GoogleSuite
    extraction: ExtractionProvider

    @classmethod
    def build(
        cls,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        extraction: ExtractionProvider | None = None,
    ) -> Runtime:
        db = Database(settings.database_url)
        clock = build_clock(settings)
        google = build_google(settings, db, transport=transport, wall_clock=clock.now)
        return cls(
            settings=settings,
            db=db,
            clock=clock,
            google=google,
            extraction=extraction or build_provider(settings),
        )

    def close(self) -> None:
        close = getattr(self.google, "close", None)
        if callable(close):
            close()
        self.db.dispose()

    def as_state(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "db": self.db,
            "clock": self.clock,
            "google": self.google,
            "extraction": self.extraction,
        }
