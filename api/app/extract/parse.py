"""Turning a model answer into ``ExtractionOutput``, or a clear refusal.

Both providers are schema-constrained, so an answer is normally clean JSON. When it is not (a
fenced block, a stray preamble, a truncated document), ``parse_output`` recovers what it safely
can and otherwise raises ``InvalidModelOutput``; the provider retries once and then gives up with
the notes untouched (spec section 7, "Model output is not valid JSON").
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.extract.provider import ExtractionError
from app.extract.schema import TOP_LEVEL_KEYS, ExtractionOutput

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class InvalidModelOutput(ExtractionError):
    """The answer is not the schema. Retry once, then fail."""


def parse_output(raw: str | dict[str, Any] | None) -> ExtractionOutput:
    if raw is None:
        raise InvalidModelOutput("the model returned nothing")
    data = raw if isinstance(raw, dict) else _loads(str(raw))
    if not isinstance(data, dict):
        raise InvalidModelOutput("the model returned JSON that is not an object")
    cleaned = _coerce(data)
    try:
        return ExtractionOutput.model_validate(cleaned)
    except ValidationError as exc:
        raise InvalidModelOutput(
            f"the model's JSON does not match the schema: {exc.errors()[0]['msg']}"
        ) from exc


def _loads(text: str) -> Any:
    candidate = text.strip()
    if not candidate:
        raise InvalidModelOutput("the model returned an empty answer")
    m = _FENCE_RE.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # A preamble before the object, or trailing prose: take the outermost braces.
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise InvalidModelOutput(f"the model returned invalid JSON: {exc.msg} at {exc.pos}") from exc
    raise InvalidModelOutput("the model returned no JSON object")


def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    """Tolerate the small liberties a model takes: nulls for strings, a status outside the enum.

    Not this one, though: an object with none of the four keys is not "a meeting with nothing in
    it", it is an answer to another question (``{}``, ``{"error": ...}``, a chat reply). It has to
    raise, or the single retry never runs and the person is told the notes held no outcomes.
    """
    if not any(key in data for key in TOP_LEVEL_KEYS):
        raise InvalidModelOutput(
            "the model's JSON has none of " + ", ".join(TOP_LEVEL_KEYS) + "; it is not the schema"
        )
    out: dict[str, Any] = {}
    for key in TOP_LEVEL_KEYS:
        items = data.get(key) or []
        if not isinstance(items, list):
            raise InvalidModelOutput(f"{key} is not a list")
        cleaned: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = {k: ("" if v is None else v) for k, v in item.items()}
            if key == "action_items":
                status = entry.get("status_hint")
                if status in ("", None):
                    entry.pop("status_hint", None)
                elif status not in ("open", "in_progress", "blocked", "done"):
                    entry["status_hint"] = _map_status(str(status))
                entry.setdefault("title", "")
                if not str(entry["title"]).strip():
                    continue
            else:
                entry.setdefault("statement", "")
                if not str(entry["statement"]).strip():
                    continue
            cleaned.append(entry)
        out[key] = cleaned
    return out


def _map_status(value: str) -> str | None:
    lower = value.strip().lower().replace("-", " ").replace("_", " ")
    if lower in ("in progress", "doing", "started", "wip"):
        return "in_progress"
    if lower in ("done", "complete", "completed", "closed"):
        return "done"
    if lower in ("blocked", "waiting", "on hold"):
        return "blocked"
    if lower in ("open", "todo", "to do", "not started"):
        return "open"
    return None
