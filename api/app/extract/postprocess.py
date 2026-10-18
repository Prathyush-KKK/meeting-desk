"""Post-processing: owners and due dates.

Spec section 5. Owners resolve deterministically - attendees by full name, then first name if it is
unique among them, then the directory, then the alias table. Two candidates set
``owner_ambiguous`` and leave the verbatim text alone; nothing is ever guessed. Due dates are
parsed by code, never by the model, with the meeting start in the display timezone as the base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import dateparser

from app.extract.provider import ExtractionContext
from app.extract.schema import ExtractionOutput
from app.relative_dates import resolve as resolve_relative
from app.tz import as_zone

# Words that look like an owner but are not a person.
NON_PERSONS = {"unassigned", "everyone", "all", "team", "tbd", "product", "someone", "n a", "na", "none"}

_TRAILING_PUNCT_RE = re.compile(r"[:\-\u2013\u2014,;.]+$")
_WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class OwnerResolution:
    owner_text: str
    owner_email: str | None = None
    ambiguous: bool = False
    candidates: list[str] | None = None
    matched_by: str = "none"  # attendee_full | attendee_first | directory | alias | none


@dataclass(slots=True)
class Person:
    name: str
    email: str


def _clean(raw: str) -> str:
    return _WS_RE.sub(" ", _TRAILING_PUNCT_RE.sub("", (raw or "").strip())).strip()


def _first(name: str) -> str:
    return name.strip().lower().split(" ")[0] if name.strip() else ""


def _edit_distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _first_name_matches(mention: str, name: str) -> bool:
    """Exact, or one letter apart on a name of four letters or more.

    Notes are transcribed by ear: "Daniel" and "Daniela" are the same sound, and when both are
    in the room neither may be guessed. When only one of them is, the near match is the person.
    """
    first = _first(name)
    if not first or not mention:
        return False
    if first == mention:
        return True
    return len(mention) >= 4 and len(first) >= 4 and _edit_distance(first, mention) <= 1


def resolve_owner(
    raw: str,
    attendees: list[Person] | list[dict[str, str]],
    directory: list[Person] | list[dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
) -> OwnerResolution:
    text = _clean(raw)
    if not text or text.lower() in NON_PERSONS:
        return OwnerResolution(owner_text=text)

    people = [
        p if isinstance(p, Person) else Person(p.get("name", ""), p.get("email", "")) for p in attendees
    ]
    dir_people = [
        p if isinstance(p, Person) else Person(p.get("name", ""), p.get("email", ""))
        for p in (directory or [])
    ]
    lower = text.lower()

    # 1. an attendee's full name, or their email
    full = [p for p in people if p.name.lower() == lower or p.email.lower() == lower]
    if len(full) == 1:
        return OwnerResolution(text, full[0].email, matched_by="attendee_full")
    if len(full) > 1:
        return OwnerResolution(text, None, True, [p.email for p in full], "attendee_full")

    # 2. a first name, but only when it is unique among the attendees
    if " " not in lower:
        by_first = [p for p in people if _first_name_matches(lower, p.name)]
        if len(by_first) == 1:
            return OwnerResolution(text, by_first[0].email, matched_by="attendee_first")
        if len(by_first) > 1:
            # Two similar names in the room: show both, guess neither.
            return OwnerResolution(text, None, True, [p.email for p in by_first], "attendee_first")

    # 3. the directory
    hits = [p for p in dir_people if p.name.lower() == lower or p.email.lower() == lower]
    if not hits and " " not in lower:
        hits = [p for p in dir_people if _first(p.name) == lower]
        if not hits:
            hits = [p for p in dir_people if _first_name_matches(lower, p.name)]
    if len(hits) == 1:
        return OwnerResolution(text, hits[0].email, matched_by="directory")
    if len(hits) > 1:
        return OwnerResolution(text, None, True, [p.email for p in hits], "directory")

    # 4. the alias table
    alias = (aliases or {}).get(lower)
    if alias:
        return OwnerResolution(text, alias, matched_by="alias")

    return OwnerResolution(owner_text=text)


# The verbatim hint usually starts with the preposition the notes used ("by Friday", "next Monday").
# dateparser reads the date, not the preposition, so they come off one at a time.
_LEADING_WORDS = ("by", "before", "on", "due", "until", "till", "within", "next", "end of", "eod", "eow")


def parse_due(text: str, base: datetime | None = None, timezone: str = "") -> datetime | None:
    """The meeting's own shorthand first, then dateparser. What neither reads stays empty."""
    value = _clean(text)
    if not value:
        return None
    tz = as_zone(timezone)
    base_dt = (base.astimezone(tz) if base.tzinfo else base.replace(tzinfo=tz)) if base else datetime.now(tz)
    explicit = resolve_relative(value, base_dt.date())
    if explicit is not None:
        return datetime(explicit.year, explicit.month, explicit.day, tzinfo=tz)
    settings = {
        "RELATIVE_BASE": base_dt.replace(tzinfo=None),
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "TIMEZONE": tz.key,
        "DATE_ORDER": "DMY",
    }
    for candidate in _candidates(value):
        parsed = dateparser.parse(candidate, languages=["en"], settings=settings)
        if parsed is not None:
            return parsed.replace(tzinfo=tz)
    return None


def _candidates(value: str) -> list[str]:
    out = [value]
    current = value
    for _ in range(3):
        lower = current.lower()
        for word in _LEADING_WORDS:
            if lower.startswith(word + " "):
                current = current[len(word) + 1 :].strip()
                out.append(current)
                break
        else:
            break
    return out


@dataclass(slots=True)
class ResolvedPoint:
    kind: str
    text: str
    evidence: str
    owner_text: str = ""
    owner_email: str | None = None
    owner_ambiguous: bool = False
    owner_candidates: list[str] | None = None
    due_text: str = ""
    due_date: datetime | None = None
    status: str = "open"
    workstream: str = ""


def postprocess(
    output: ExtractionOutput,
    context: ExtractionContext,
    directory: list[dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[ResolvedPoint]:
    points: list[ResolvedPoint] = []
    attendees = context.attendees

    for item in output.action_items:
        owner = resolve_owner(item.owner_text, attendees, directory, aliases)
        points.append(
            ResolvedPoint(
                kind="action",
                text=item.title,
                evidence=item.evidence,
                owner_text=owner.owner_text,
                owner_email=owner.owner_email,
                owner_ambiguous=owner.ambiguous,
                owner_candidates=owner.candidates,
                due_text=item.due_hint,
                due_date=parse_due(item.due_hint, context.meeting_start, context.timezone),
                status=item.status_hint or "open",
                workstream=context.workstream,
            )
        )
    for d in output.decisions:
        points.append(
            ResolvedPoint(
                kind="decision",
                text=d.statement,
                evidence=d.evidence,
                status="decided",
                workstream=context.workstream,
            )
        )
    for r in output.risks:
        points.append(
            ResolvedPoint(
                kind="risk",
                text=r.statement,
                evidence=r.evidence,
                status="open",
                workstream=context.workstream,
            )
        )
    for q in output.questions:
        points.append(
            ResolvedPoint(
                kind="question",
                text=q.statement,
                evidence=q.evidence,
                status="open",
                workstream=context.workstream,
            )
        )
    return points


def normalise_text(text: str) -> str:
    """``text_norm``: what re-extract compares against so nothing is added twice."""
    return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def normalise_note(text: str) -> str:
    """Markdown from a Gemini chat paste: strip bold and bullets, keep the line breaks."""
    out = []
    for line in (text or "").splitlines():
        line = line.replace("**", "")
        line = re.sub(r"^[\s*•\-]+", "", line)
        out.append(line.rstrip())
    return "\n".join(out).strip()
