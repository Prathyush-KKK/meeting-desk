"""Dates the way Sheets stores them: a serial number of days since 1899-12-30.

A date column is written as a date when the value can be read as one (ISO first, then the same
``dateparser`` rules the extractor uses for due hints) and as text otherwise - spec section 7,
"Date columns".
"""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import dateparser

from app.relative_dates import resolve as resolve_relative

EPOCH = date(1899, 12, 30)
_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_LEADING_WORDS = ("by", "before", "on", "due", "until", "till", "within", "next", "end of", "eod", "eow")


def serial_from_date(value: date | datetime) -> int:
    day = value.date() if isinstance(value, datetime) else value
    return (day - EPOCH).days


def date_from_serial(serial: float) -> date:
    return date.fromordinal(EPOCH.toordinal() + int(serial))


def parse_date(value: str, base: datetime | None = None, timezone: str = "Asia/Kolkata") -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    m = _ISO_RE.match(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    tz = ZoneInfo(timezone)
    base_dt = (base.astimezone(tz) if base and base.tzinfo else base) or datetime.now(tz)
    explicit = resolve_relative(text, base_dt.date())
    if explicit is not None:
        return explicit
    settings = {
        "RELATIVE_BASE": base_dt.replace(tzinfo=None),
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "TIMEZONE": timezone,
        "DATE_ORDER": "DMY",
    }
    candidates = [text]
    current = text
    for _ in range(3):
        lower = current.lower()
        for word in _LEADING_WORDS:
            if lower.startswith(word + " "):
                current = current[len(word) + 1 :].strip()
                candidates.append(current)
                break
        else:
            break
    for candidate in candidates:
        parsed = dateparser.parse(candidate, languages=["en"], settings=settings)
        if parsed is not None:
            return parsed.date()
    return None


def serial_for(value: str, base: datetime | None = None) -> int | None:
    parsed = parse_date(value, base)
    return serial_from_date(parsed) if parsed else None
