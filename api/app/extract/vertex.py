"""Gemini on Vertex AI, in VERTEX_LOCATION (default us-central1).

``GenerativeModel.generate_content`` with ``response_mime_type=application/json``,
``response_schema=EXTRACTION_JSON_SCHEMA`` and temperature 0. One retry on an answer that is not
the schema, then ``ExtractionError`` with the notes untouched. The Vertex SDK is imported lazily
so a FAKE_LLM run never needs it; ``model_factory`` lets a test hand in a stand-in model.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.extract.parse import InvalidModelOutput, parse_output
from app.extract.prompt import build_prompt
from app.extract.provider import ExtractionContext, ExtractionError, ProviderResult
from app.extract.schema import EXTRACTION_JSON_SCHEMA
from app.telemetry.breaker import BreakerOpen
from app.telemetry.providers import VERTEX, track_provider

ATTEMPTS = 2  # the call, then one retry on invalid output

ModelFactory = Callable[[str, str], Any]


class VertexExtractionProvider:
    name = "vertex"

    def __init__(self, settings: Settings, model_factory: ModelFactory | None = None) -> None:
        self.settings = settings
        self.model = settings.vertex_model
        self.region = settings.vertex_location
        self.project = settings.vertex_project
        self._factory = model_factory or self._sdk_model
        self._models: dict[str, Any] = {}

    # --- the SDK ---------------------------------------------------------------------------------
    def _sdk_model(self, model_name: str, system_instruction: str) -> Any:
        if not self.project:
            raise ExtractionError("VERTEX_PROJECT is not set; Vertex extraction cannot run.")
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as exc:  # pragma: no cover - the extra is not installed
            raise ExtractionError("google-cloud-aiplatform is not installed (pip install '.[llm]').") from exc
        vertexai.init(project=self.project, location=self.region)
        return GenerativeModel(model_name, system_instruction=system_instruction)

    def _generation_config(self) -> dict[str, Any]:
        return {
            "temperature": 0,
            "response_mime_type": "application/json",
            "response_schema": EXTRACTION_JSON_SCHEMA,
            "max_output_tokens": self.settings.extraction_max_output_tokens,
        }

    # --- the call --------------------------------------------------------------------------------
    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        """Wrapped in the provider telemetry, so a Vertex outage counts, stalls the last-success
        gauge and opens the breaker - which is what makes the Bedrock fallback fail fast rather than
        wait for a timeout per extraction."""
        try:
            with track_provider(VERTEX, "generate_content"):
                return self._extract(text, context)
        except BreakerOpen as exc:
            raise ExtractionError(str(exc)) from exc

    def _extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        prompt = build_prompt(text, context)
        model = self._models.get(prompt.system)
        if model is None:
            model = self._factory(self.model, prompt.system)
            self._models[prompt.system] = model

        started = time.perf_counter()
        usage: dict[str, Any] = {}
        last_error: ExtractionError | None = None
        for attempt in range(ATTEMPTS):
            try:
                response = model.generate_content(prompt.user, generation_config=self._generation_config())
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError(f"Vertex AI refused the call: {exc}") from exc
            usage = usage_from(response)
            usage["attempts"] = attempt + 1
            try:
                output = parse_output(response_text(response))
            except InvalidModelOutput as exc:
                last_error = exc
                continue
            return ProviderResult(
                output=output,
                provider=self.name,
                model=self.model,
                region=self.region,
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
            )
        raise ExtractionError(f"Gemini did not return valid JSON after {ATTEMPTS} attempts: {last_error}")


def response_text(response: Any) -> str:
    """The SDK's ``response.text`` raises when a candidate was blocked; say so instead."""
    try:
        return str(response.text or "")
    except Exception as exc:
        candidates = getattr(response, "candidates", None) or []
        reason = getattr(candidates[0], "finish_reason", "") if candidates else ""
        raise InvalidModelOutput(f"no text in the answer ({reason or exc})") from exc


def usage_from(response: Any) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    out: dict[str, Any] = {}
    for src, dst in (
        ("prompt_token_count", "input_tokens"),
        ("candidates_token_count", "output_tokens"),
        ("total_token_count", "total_tokens"),
    ):
        value = getattr(meta, src, None)
        if value is None and isinstance(meta, dict):
            value = meta.get(src)
        if value is not None:
            out[dst] = int(value)
    return out
