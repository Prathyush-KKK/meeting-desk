"""The due phrases a meeting actually produces, resolved before dateparser sees them.

``dateparser`` is good at dates and bad at the shorthand people type in notes: it reads "EOD" as
nothing, "end of month" as today, "by the 31st" as a date in whatever month has a 31st, and "next
Thursday" as the Thursday two days away. Those five shapes cover most of what lands in a due
column, so they are resolved here, deterministically, against the meeting's own date - and anything
this module does not recognise is handed on to dateparser unchanged.

One rule decides the ambiguous cases, and it is the one people mean when they say it out loud:

* the week runs Monday to Sunday, and its end is the Friday;
* "next <weekday>" is the weekday in the week after the meeting's week, never the one two days
  away - saying "next Thursday" on a Tuesday and meaning tomorrow-but-one is what the phrase is
  for avoiding;
* a day of the month is a day of *this* month, clamped: "by the 31st" in February is the 28th (the
  29th in a leap year), because the person means the end of the month they are in.

Used by ``app/extract/postprocess.parse_due`` (the due date on a point) and
``app/sheets/dates.parse_date`` (writing a date column), so both read a note the same way.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

_ONE_DAY = timedelta(days=1)

WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

FRIDAY = 4

# Prepositions the notes put in front of the phrase. Stripped one at a time, longest first, so
# "by the end of the month" reduces to "end of the month".
_PREFIXES = ("by", "before", "on", "due", "due by", "until", "till", "no later than", "at", "the")

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile("^[\\s\\-–—:,;.]+|[\\s\\-–—:,;.]+$")  # noqa: RUF001
_DAY_OF_MONTH_RE = re.compile(r"^(?:the\s+)?(\d{1,2})\s*(?:st|nd|rd|th)$")
_PERIOD_WORDS = {
    "day": "day",
    "today": "day",
    "week": "week",
    "month": "month",
    "quarter": "quarter",
    "year": "year",
    "eod": "day",
    "cob": "day",
    "eow": "week",
    "eom": "month",
    "eoq": "quarter",
    "eoy": "year",
}


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub("", (text or "").lower())).strip()


def _strip_prefixes(text: str) -> str:
    out = text
    for _ in range(4):
        for word in sorted(_PREFIXES, key=len, reverse=True):
            if out.startswith(word + " "):
                out = out[len(word) + 1 :].strip()
                break
        else:
            return out
    return out


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def end_of_day(base: date) -> date:
    return base


def end_of_week(base: date) -> date:
    """The Friday of the meeting's week; from a Saturday or Sunday, the Friday coming."""
    friday = base + (FRIDAY - base.weekday()) * _ONE_DAY
    return friday if friday >= base else friday + 7 * _ONE_DAY


def end_of_month(base: date) -> date:
    return base.replace(day=calendar.monthrange(base.year, base.month)[1])


def end_of_quarter(base: date) -> date:
    last_month = ((base.month - 1) // 3) * 3 + 3
    return date(base.year, last_month, calendar.monthrange(base.year, last_month)[1])


def end_of_year(base: date) -> date:
    return date(base.year, 12, 31)


def next_weekday(base: date, weekday: int) -> date:
    """That weekday in the week *after* the base's week (Monday-start weeks)."""
    monday_next = base - base.weekday() * _ONE_DAY + 7 * _ONE_DAY
    return monday_next + weekday * _ONE_DAY


def day_of_month(base: date, day: int) -> date:
    """The day in the base's month, clamped to its last day: the 31st of February is the 28th."""
    return base.replace(day=min(day, calendar.monthrange(base.year, base.month)[1]))


def _shift(base: date, period: str, steps: int) -> date:
    if steps == 0:
        return base
    if period == "day":
        return base + steps * _ONE_DAY
    if period == "week":
        return base + 7 * steps * _ONE_DAY
    if period == "month":
        month = base.month - 1 + steps
        year = base.year + month // 12
        month = month % 12 + 1
        return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))
    if period == "quarter":
        return _shift(base, "month", 3 * steps)
    year = base.year + steps
    return date(year, base.month, min(base.day, calendar.monthrange(year, base.month)[1]))


_END_OF = {
    "day": end_of_day,
    "week": end_of_week,
    "month": end_of_month,
    "quarter": end_of_quarter,
    "year": end_of_year,
}


def resolve(text: str, base: date | datetime) -> date | None:
    """The due date for one of the shapes above, or ``None`` to let dateparser try."""
    value = _strip_prefixes(_clean(text))
    if not value:
        return None
    day = _as_date(base)

    # "eod", "eow", "eom", "cob", "month end", "week end"
    direct = value.replace("close of business", "cob").replace(" ", "")
    if direct in _PERIOD_WORDS and direct not in ("day", "week", "month", "quarter", "year", "today"):
        return _END_OF[_PERIOD_WORDS[direct]](day)
    if value == "today":
        return day
    ending = re.fullmatch(r"(day|week|month|quarter|year)\s*-?\s*end", value)
    if ending:
        return _END_OF[ending.group(1)](day)

    # "end of month", "end of the week", "end of next month", "end of this quarter"
    end_of = re.fullmatch(r"end of(?: the)?\s+(this |next |current |coming )?(\w+)", value)
    if end_of:
        period = _PERIOD_WORDS.get(end_of.group(2))
        if period is not None:
            steps = 1 if (end_of.group(1) or "").strip() in ("next", "coming") else 0
            return _END_OF[period](_shift(day, period, steps))
        weekday = WEEKDAYS.get(end_of.group(2))
        if weekday is not None:  # "end of Friday" is that Friday
            return _weekday_on_or_after(day, weekday)

    # "next Thursday" - the following week, never the day after tomorrow.
    following = re.fullmatch(r"next\s+(\w+)", value)
    if following:
        weekday = WEEKDAYS.get(following.group(1))
        if weekday is not None:
            return next_weekday(day, weekday)
        period = _PERIOD_WORDS.get(following.group(1))
        if period in ("week", "month", "quarter", "year"):
            # "next week" with nothing else said: the end of it, the way "by next week" is meant.
            return _END_OF[period](_shift(day, period, 1))

    # "by the 31st", "the 15th"
    numbered = _DAY_OF_MONTH_RE.fullmatch(value)
    if numbered:
        return day_of_month(day, int(numbered.group(1)))
    return None


def _weekday_on_or_after(base: date, weekday: int) -> date:
    ahead = (weekday - base.weekday()) % 7
    return base + ahead * _ONE_DAY
