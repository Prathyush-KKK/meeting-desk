"""Extraction: one schema, one provider interface, four implementations and a fallback.

``build_provider`` picks by config: ``FAKE_LLM=1`` (or ``EXTRACTION_PROVIDER=fake``) is the
rule-based provider; ``vertex`` is Gemini on Vertex AI in asia-south1; ``bedrock`` is whichever
Bedrock credential is configured - the OpenAI-compatible endpoint with a Bedrock API key when
``BEDROCK_BASE_URL`` and ``AWS_BEARER_TOKEN_BEDROCK`` are both set, otherwise the Converse API in
ap-south-1 on the AWS credential chain; ``bedrock_openai`` forces the OpenAI-compatible endpoint.
With ``EXTRACT_FALLBACK_TO_BEDROCK=1`` a Vertex failure is retried on Bedrock (by the same rule) and
the result says which one answered.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.extract.bedrock import BedrockExtractionProvider
from app.extract.fake import FakeExtractionProvider
from app.extract.fallback import FallbackExtractionProvider
from app.extract.openai_compat import OpenAICompatExtractionProvider
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
    "build_bedrock_provider",
    "build_provider",
    "get_provider",
]

PROVIDERS = ("fake", "vertex", "bedrock", "bedrock_openai")


def build_bedrock_provider(settings: Settings) -> ExtractionProvider:
    """The bearer pair when both halves are set, else the Converse API."""
    if settings.bedrock_bearer_configured:
        return OpenAICompatExtractionProvider(settings)
    return BedrockExtractionProvider(settings)


def build_provider(settings: Settings) -> ExtractionProvider:
    if settings.fake_llm or settings.extraction_provider == "fake":
        return FakeExtractionProvider()
    if settings.extraction_provider == "bedrock_openai":
        return OpenAICompatExtractionProvider(settings)
    if settings.extraction_provider == "bedrock":
        return build_bedrock_provider(settings)
    if settings.extraction_provider != "vertex":
        raise ValueError(
            f"EXTRACTION_PROVIDER must be one of {', '.join(PROVIDERS)}, not {settings.extraction_provider!r}"
        )
    primary: ExtractionProvider = VertexExtractionProvider(settings)
    if settings.bedrock_fallback_enabled:
        return FallbackExtractionProvider(primary, build_bedrock_provider(settings))
    return primary


def get_provider(request: Request) -> ExtractionProvider:
    return request.app.state.extraction
