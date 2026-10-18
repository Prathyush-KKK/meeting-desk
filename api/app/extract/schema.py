"""The extraction contract - schema v3.

``EXTRACTION_JSON_SCHEMA`` goes to Vertex as ``response_schema`` and to Bedrock as the forced tool's
input schema; the Pydantic models validate whatever comes back, fake or real, before anything is
written.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "v3"

STATUS_HINTS = ("open", "in_progress", "blocked", "done")

# The four keys the answer must carry. A payload with none of them is not a thin extraction, it is
# a different shape - see ``app/extract/parse.py``.
TOP_LEVEL_KEYS = ("action_items", "decisions", "risks", "questions")

# Strict at every level: ``additionalProperties: false`` so a model cannot invent a field and have
# it quietly ignored, and ``propertyOrdering`` because Vertex generates the keys in the order the
# schema lists them - which keeps the JSON stable across calls and the retry comparable.
EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(TOP_LEVEL_KEYS),
    "additionalProperties": False,
    "propertyOrdering": list(TOP_LEVEL_KEYS),
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "owner_text", "due_hint", "evidence"],
                "additionalProperties": False,
                "propertyOrdering": [
                    "title",
                    "detail",
                    "owner_text",
                    "due_hint",
                    "status_hint",
                    "evidence",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "owner_text": {"type": "string"},
                    "due_hint": {"type": "string"},
                    "status_hint": {"type": "string", "enum": list(STATUS_HINTS)},
                    "evidence": {"type": "string"},
                },
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement", "evidence"],
                "additionalProperties": False,
                "propertyOrdering": ["statement", "evidence"],
                "properties": {"statement": {"type": "string"}, "evidence": {"type": "string"}},
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement", "evidence"],
                "additionalProperties": False,
                "propertyOrdering": ["statement", "evidence"],
                "properties": {"statement": {"type": "string"}, "evidence": {"type": "string"}},
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement", "evidence"],
                "additionalProperties": False,
                "propertyOrdering": ["statement", "needs", "evidence"],
                "properties": {
                    "statement": {"type": "string"},
                    "needs": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}

PROMPT_RULES = """Only what the notes state. Owner and due dates verbatim - never invent, never
normalise, leave empty when the notes do not say. A decision only when the text says decided or
agreed, otherwise it is a question. status_hint only when the notes say it is done or in progress.
Weight the Next steps section. Evidence is the line the item came from, unedited."""


class ActionItem(BaseModel):
    # extra="forbid" everywhere: a field the schema does not have is the model answering a
    # different question, and that has to reach the retry rather than be dropped in silence.
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str = ""
    owner_text: str = ""
    due_hint: str = ""
    status_hint: Literal["open", "in_progress", "blocked", "done"] | None = None
    evidence: str = ""


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence: str = ""


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    needs: str = ""
    evidence: str = ""


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_items: list[ActionItem] = Field(default_factory=list)
    decisions: list[Statement] = Field(default_factory=list)
    risks: list[Statement] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)

    def total(self) -> int:
        return len(self.action_items) + len(self.decisions) + len(self.risks) + len(self.questions)
