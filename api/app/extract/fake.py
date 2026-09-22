"""Rule-based extraction - a port of ``meeting-desk/src/lib/extract.ts``.

Same line rules as the prototype, reshaped into the v3 schema so the fake and Gemini are
interchangeable. Owners stay verbatim here; resolution is ``postprocess.py``'s job, exactly as it
is for the real provider.
"""

from __future__ import annotations

import re
import time

from app.extract.provider import ExtractionContext, ProviderResult
from app.extract.schema import ActionItem, ExtractionOutput, Question, Statement

# re.ASCII keeps \w to [A-Za-z0-9_], the way the JavaScript original behaves.
_BULLET_RE = re.compile(r"^[\s*\-•\d.)]+")
_STEPS_RE = re.compile(r"^(the )?(next steps|action items|actions|next step)s?:?$", re.I)
_DISCUSSION_RE = re.compile(r"^(the )?(discussion|summary|details|goal):?$", re.I)
_BOLD_ONLY_RE = re.compile(r"^\*\*.*\*\*$")
_BRACKET_OWNER_RE = re.compile(r"^\[([^\]]+)\]\s*(.+)$")
_LABEL_OWNER_TO_RE = re.compile(r"^([^:]{3,60}):\s*([A-Z][\w.]*(?:\s[A-Z][\w.]*){0,2})\s+to\s+(.+)$", re.A)
_OWNER_LINE_RE = re.compile(r"^([A-Z][\w.]*(?:\s[A-Z][\w.]*){0,2}):\s*(.+)$", re.A)
_LABEL_LINE_RE = re.compile(r"^([^:]{3,60}):\s*(.+)$")
_LABEL_PREFIX_RE = re.compile(r"^[^:]{3,60}:\s*")
_DECIDED_TO_RE = re.compile(r"^decided to\s+", re.I)
_DECISION_RE = re.compile(r"\b(decided|agreed|decision)\b", re.I)
_QUESTION_RE = re.compile(r"\b(explored|open question|to be decided|needs a decision|undecided)\b", re.I)
_RISK_RE = re.compile(r"\b(risk|slipping|at risk|blocked|blocker|depends on)\b", re.I)
_DUE_RE = re.compile(r"\b(by|before|on|within|end of|eod|eow|next)\b\s+([^.;,]+)", re.I)
_WS_RE = re.compile(r"\s+")

MAX_INPUT_CHARS = 200_000


def due_from(text: str) -> str:
    m = _DUE_RE.search(text)
    if not m:
        return ""
    return _WS_RE.sub(" ", f"{m.group(1)} {m.group(2)}".strip())[:40]


def looks_like_person(raw: str, people: list[str]) -> bool:
    """The prototype's ``resolveOwner(...).known`` - only used to decide if a line is an owner line."""
    r = re.sub(r"[:\-\u2013]+$", "", raw.strip()).strip()
    if not r:
        return False
    lower = r.lower()
    for name in people:
        n = name.lower()
        first = n.split(" ")[0]
        if n == lower or n.startswith(lower) or lower.startswith(first):
            return True
        if lower.split(" ")[0] == first:
            return True
    return False


class FakeExtractionProvider:
    name = "fake"

    def __init__(self, model: str = "rule-based") -> None:
        self.model = model

    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        started = time.perf_counter()
        output = extract_output(text[:MAX_INPUT_CHARS], context.people_names())
        return ProviderResult(
            output=output,
            provider=self.name,
            model=self.model,
            region="local",
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage={"input_chars": len(text), "items": output.total()},
        )


def extract_output(text: str, people: list[str]) -> ExtractionOutput:
    out = ExtractionOutput()
    seen: set[str] = set()
    section = "other"

    def push(kind: str, item) -> None:
        body = item.title if isinstance(item, ActionItem) else item.statement
        key = f"{kind}|{body.lower()}"
        if key in seen:
            return
        seen.add(key)
        getattr(out, kind).append(item)

    lines = [ln for ln in (_BULLET_RE.sub("", ln).strip() for ln in text.splitlines()) if ln]
    for line in lines:
        low = line.lower()
        if _STEPS_RE.match(low):
            section = "steps"
            continue
        if _DISCUSSION_RE.match(low):
            section = "discussion"
            continue
        if _BOLD_ONLY_RE.match(line):
            continue
        clean = line.replace("**", "")

        m = _BRACKET_OWNER_RE.match(clean)
        if m:
            body = m.group(2).strip()
            push(
                "action_items",
                ActionItem(
                    title=body, owner_text=m.group(1).strip(), due_hint=due_from(body), evidence=clean
                ),
            )
            continue

        m = _LABEL_OWNER_TO_RE.match(clean)
        if m:
            body = f"{m.group(1).strip()}: {m.group(3).strip()}"
            push(
                "action_items",
                ActionItem(
                    title=body,
                    owner_text=m.group(2).strip(),
                    due_hint=due_from(m.group(3)),
                    evidence=clean,
                ),
            )
            continue

        m = _OWNER_LINE_RE.match(clean)
        if m and looks_like_person(m.group(1), people):
            body = m.group(2).strip()
            push(
                "action_items",
                ActionItem(
                    title=body, owner_text=m.group(1).strip(), due_hint=due_from(body), evidence=clean
                ),
            )
            continue

        if _DECISION_RE.search(clean):
            body = _LABEL_PREFIX_RE.sub("", clean)
            push("decisions", Statement(statement=_DECIDED_TO_RE.sub("", body).strip(), evidence=clean))
            continue

        if clean.rstrip().endswith("?") or _QUESTION_RE.search(clean):
            push("questions", Question(statement=_LABEL_PREFIX_RE.sub("", clean), evidence=clean))
            continue

        if _RISK_RE.search(clean):
            push("risks", Statement(statement=_LABEL_PREFIX_RE.sub("", clean), evidence=clean))
            continue

        if section == "steps":
            m2 = _LABEL_LINE_RE.match(clean)
            body = f"{m2.group(1).strip()}: {m2.group(2).strip()}" if m2 else clean
            push(
                "action_items",
                ActionItem(title=body, owner_text="", due_hint=due_from(clean), evidence=clean),
            )

    return out
