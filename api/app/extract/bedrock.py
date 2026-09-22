"""Bedrock, ap-south-1: the configured fallback.

The Converse API with the extraction schema enforced through a tool definition
(``toolConfig`` with ``toolChoice`` forcing ``record_points``), so the answer is the tool's input,
already structured. Used on its own with ``EXTRACTION_PROVIDER=bedrock`` or as the fallback behind
``EXTRACT_FALLBACK_TO_BEDROCK``. boto3 is imported lazily; ``client`` lets a test hand in a stub.
"""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.extract.parse import InvalidModelOutput, parse_output
from app.extract.prompt import build_prompt
from app.extract.provider import ExtractionContext, ExtractionError, ProviderResult
from app.extract.schema import EXTRACTION_JSON_SCHEMA
from app.telemetry.breaker import BreakerOpen
from app.telemetry.providers import BEDROCK, track_provider

ATTEMPTS = 2
TOOL_NAME = "record_points"


def tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": "Record the action items, decisions, risks and questions in the notes.",
                    "inputSchema": {"json": EXTRACTION_JSON_SCHEMA},
                }
            }
        ],
        "toolChoice": {"tool": {"name": TOOL_NAME}},
    }


class BedrockExtractionProvider:
    name = "bedrock"

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.model = settings.bedrock_model
        self.region = settings.bedrock_region
        self._client = client

    def _runtime(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - the extra is not installed
                raise ExtractionError("boto3 is not installed (pip install '.[llm]').") from exc
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        try:
            with track_provider(BEDROCK, "converse"):
                return self._extract(text, context)
        except BreakerOpen as exc:
            raise ExtractionError(str(exc)) from exc

    def _extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        prompt = build_prompt(text, context)
        client = self._runtime()
        started = time.perf_counter()
        usage: dict[str, Any] = {}
        last_error: ExtractionError | None = None
        for attempt in range(ATTEMPTS):
            try:
                response = client.converse(
                    modelId=self.model,
                    system=[{"text": prompt.system}],
                    messages=[{"role": "user", "content": [{"text": prompt.user}]}],
                    inferenceConfig={
                        "temperature": 0,
                        "maxTokens": self.settings.extraction_max_output_tokens,
                    },
                    toolConfig=tool_config(),
                )
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError(f"Bedrock refused the call: {exc}") from exc
            usage = usage_from(response)
            usage["attempts"] = attempt + 1
            try:
                output = parse_output(tool_input(response))
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
        raise ExtractionError(f"Bedrock did not return the schema after {ATTEMPTS} attempts: {last_error}")


def tool_input(response: dict[str, Any]) -> dict[str, Any] | str:
    """The forced tool's input; a plain text answer is handed to the JSON parser as a fallback."""
    message = (response.get("output") or {}).get("message") or {}
    text_parts: list[str] = []
    for block in message.get("content") or []:
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == TOOL_NAME:
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload
        if block.get("text"):
            text_parts.append(str(block["text"]))
    if text_parts:
        return "\n".join(text_parts)
    stop = response.get("stopReason", "")
    raise InvalidModelOutput(f"no {TOOL_NAME} tool call in the answer (stopReason={stop or 'unknown'})")


def usage_from(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("usage") or {}
    out: dict[str, Any] = {}
    for src, dst in (
        ("inputTokens", "input_tokens"),
        ("outputTokens", "output_tokens"),
        ("totalTokens", "total_tokens"),
    ):
        if raw.get(src) is not None:
            out[dst] = int(raw[src])
    latency = (response.get("metrics") or {}).get("latencyMs")
    if latency is not None:
        out["model_latency_ms"] = int(latency)
    return out
