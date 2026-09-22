"""The extraction provider interface.

One call, one schema. The fake, Vertex and Bedrock all satisfy it, so the job never knows which one
it ran on beyond the provider name it records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.extract.schema import ExtractionOutput


class ExtractionError(RuntimeError):
    """The provider failed or returned something that is not the schema. Notes are untouched."""


@dataclass(slots=True)
class ExtractionContext:
    """Everything the prompt and the post-processing need about the meeting."""

    meeting_title: str = ""
    meeting_start: datetime | None = None
    timezone: str = "Asia/Kolkata"
    workstream: str = ""
    attendees: list[dict[str, str]] = field(default_factory=list)
    directory: list[dict[str, str]] = field(default_factory=list)

    def attendee_names(self) -> list[str]:
        return [a.get("name", "") for a in self.attendees if a.get("name")]

    def people_names(self) -> list[str]:
        """Attendees first, then the directory.

        Only used to recognise the *shape* of an owner line ("Ansul S: do the thing"); a manual
        meeting has no attendee list but its notes still name people. Deciding who that is stays
        with post-processing.
        """
        seen: list[str] = []
        for name in [*self.attendee_names(), *(p.get("name", "") for p in self.directory)]:
            if name and name not in seen:
                seen.append(name)
        return seen


@dataclass(slots=True)
class ProviderResult:
    output: ExtractionOutput
    provider: str
    model: str
    region: str = ""
    latency_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExtractionProvider(Protocol):
    name: str

    def extract(self, text: str, context: ExtractionContext) -> ProviderResult: ...
