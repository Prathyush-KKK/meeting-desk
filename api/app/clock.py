"""The app's idea of "now".

In fake mode it is pinned to the demo world's clock so the seeded calendar window, the "read HH:MM"
line and the tests do not drift with the wall clock.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app import seed_data
from app.config import Settings

IST = ZoneInfo("Asia/Kolkata")


class Clock:
    def __init__(self, fixed: datetime | None = None, tz: ZoneInfo = IST) -> None:
        self._fixed = fixed
        self.tz = tz

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now(self.tz)

    def advance(self, **kwargs: float) -> None:
        from datetime import timedelta

        if self._fixed is None:
            raise RuntimeError("only a fixed clock can be advanced")
        self._fixed = self._fixed + timedelta(**kwargs)


def build_clock(settings: Settings) -> Clock:
    tz = ZoneInfo(settings.display_timezone)
    return Clock(seed_data.now(), tz) if settings.fake_google else Clock(None, tz)
