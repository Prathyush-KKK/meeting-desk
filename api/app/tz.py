"""The one display timezone: ``DISPLAY_TIMEZONE`` (an IANA name, default UTC).

Times are stored aware and shown in this zone everywhere - the meeting list, manual meetings, the
"read HH:MM" line, due dates. It is set once per process from the settings the runtime is built
with, and read lazily so a module never pins a zone at import time.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE = "UTC"

_zone: ZoneInfo | None = None


def _load(name: str) -> ZoneInfo:
    try:
        return ZoneInfo((name or DEFAULT_ZONE).strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_ZONE)


def configure(name: str) -> ZoneInfo:
    global _zone
    _zone = _load(name)
    return _zone


def display_zone() -> ZoneInfo:
    if _zone is None:
        from app.config import get_settings

        return configure(get_settings().display_timezone)
    return _zone


def display_zone_name() -> str:
    return display_zone().key


def as_zone(value: ZoneInfo | str | None) -> ZoneInfo:
    """A zone given by name or object; empty means the display zone."""
    if isinstance(value, ZoneInfo):
        return value
    return _load(value) if value else display_zone()
