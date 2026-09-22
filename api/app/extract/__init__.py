"""Extraction: one schema, one provider interface, three implementations and a fallback.

``build_provider`` picks by config: ``FAKE_LLM=1`` (or ``EXTRACTION_PROVIDER=fake``) is the
rule-based provider; ``vertex`` is Gemini on Vertex AI in asia-south1; ``bedrock`` is the
Converse API in ap-south-1. With ``EXTRACT_FALLBACK_TO_BEDROCK=1`` a Vertex failure is retried on
Bedrock and the result says which one answered.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.extract.bedrock import BedrockExtractionProvider
from app.extract.fake import FakeExtractionProvider
from app.extract.fallback import FallbackExtractionProvider
from app.extract.provider import ExtractionContext, ExtractionError, ExtractionProvider, ProviderResult
from app.extract.schema import EXTRACTION_JSON_SCHEMA, SCHEMA_VERSION, ExtractionOutput
from app.extract.vertex import VertexExtractionProvider

__all__ = [
    "EXTRACTION_JSON_SCHEMA",
    "SCHEMA_VERSION",
    "ExtractionContext",
    "ExtractionError",
    "ExtractionOutput",
    "ExtractionProvider",
    "FallbackExtractionProvider",
    "ProviderResult",
    "build_provider",
    "get_provider",
]


def build_provider(settings: Settings) -> ExtractionProvider:
    if settings.fake_llm or settings.extraction_provider == "fake":
        return FakeExtractionProvider()
    if settings.extraction_provider == "bedrock":
        return BedrockExtractionProvider(settings)
    if settings.extraction_provider != "vertex":
        raise ValueError(
            f"EXTRACTION_PROVIDER must be fake, vertex or bedrock, not {settings.extraction_provider!r}"
        )
    primary: ExtractionProvider = VertexExtractionProvider(settings)
    if settings.bedrock_fallback_enabled:
        return FallbackExtractionProvider(primary, BedrockExtractionProvider(settings))
    return primary


def get_provider(request: Request) -> ExtractionProvider:
    return request.app.state.extraction
