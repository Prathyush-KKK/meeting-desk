"""Vertex first, Bedrock when Vertex is out or over quota - behind ``EXTRACT_FALLBACK_TO_BEDROCK``.

The result names the provider that answered (``ProviderResult.provider``) and carries
``usage.fallback_from`` and ``usage.fallback_reason`` so the UI can toast it. A provider that
fails because the *notes* are the problem (invalid output twice) still falls through: the second
model gets its own chance, and only if both fail does the error reach the person.
"""

from __future__ import annotations

from app.extract.provider import ExtractionContext, ExtractionError, ExtractionProvider, ProviderResult


class FallbackExtractionProvider:
    def __init__(self, primary: ExtractionProvider, fallback: ExtractionProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name

    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        try:
            return self.primary.extract(text, context)
        except ExtractionError as first:
            try:
                result = self.fallback.extract(text, context)
            except ExtractionError as second:
                raise ExtractionError(
                    f"{self.primary.name}: {first}; {self.fallback.name}: {second}"
                ) from second
            result.usage = {
                **(result.usage or {}),
                "fallback_from": self.primary.name,
                "fallback_reason": str(first),
            }
            return result
