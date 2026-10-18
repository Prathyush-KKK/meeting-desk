"""Claude through the Anthropic API (``EXTRACTION_PROVIDER=anthropic``).

One ``messages.create`` per extraction with the extraction schema as a structured output
(``output_config.format``), so the answer is JSON that already matches ``schema.py``. The prompt
is ``prompt.py``'s, unchanged. ``ANTHROPIC_API_KEY`` and ``ANTHROPIC_MODEL`` configure it,
``ANTHROPIC_EFFORT`` sets ``output_config.effort``. Server-side refusal fallbacks are on
(``fallbacks: "default"``), so a declined request is retried on a fallback model inside the same
call; a refusal that survives that is an extraction error, not an empty result.

The SDK is the ``anthropic`` extra (``make install-llm``) and is imported lazily; ``client`` lets a
test hand in a stub. A 401/403/404/429 is an answer, not an outage: counted, never held against
the breaker.
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
from app.telemetry.events import FailureReason
from app.telemetry.providers import ANTHROPIC, track_provider

NAME = "anthropic"
OP = "messages_create"
ATTEMPTS = 2
# Thinking shares max_tokens with the answer; below this a long meeting could be cut off.
MIN_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _without_ordering(node: Any) -> Any:
    """``propertyOrdering`` is a Vertex extension; structured outputs take plain JSON Schema."""
    if isinstance(node, dict):
        return {k: _without_ordering(v) for k, v in node.items() if k != "propertyOrdering"}
    if isinstance(node, list):
        return [_without_ordering(v) for v in node]
    return node


OUTPUT_SCHEMA = _without_ordering(EXTRACTION_JSON_SCHEMA)


class AnthropicRefusal(ExtractionError):
    """A 4xx from the API: it is up and said no. Counted as an error, never against the breaker."""

    failure_reason: str = FailureReason.CLIENT_ERROR
    counts_against_breaker = False


class AnthropicExtractionProvider:
    name = NAME

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.model = settings.anthropic_model.strip()
        self.effort = settings.anthropic_effort.strip()
        self._client = client

    def _api(self) -> Any:
        if self._client is None:
            if not self.settings.anthropic_api_key.strip():
                raise ExtractionError("The Anthropic API is not configured: ANTHROPIC_API_KEY is not set.")
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - the extra is not installed
                raise ExtractionError(
                    "The anthropic SDK is not installed (pip install '.[anthropic]')."
                ) from exc
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key.strip())
        return self._client

    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        client = self._api()  # configuration, not a call: neither counted nor held against the breaker
        try:
            with track_provider(ANTHROPIC, OP):
                return self._extract(client, text, context)
        except BreakerOpen as exc:
            raise ExtractionError(str(exc)) from exc

    def _request(self) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
        if self.effort:
            output_config["effort"] = self.effort
        return {
            "model": self.model,
            "max_tokens": max(self.settings.extraction_max_output_tokens, MIN_MAX_TOKENS),
            "output_config": output_config,
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }

    def _extract(self, client: Any, text: str, context: ExtractionContext) -> ProviderResult:
        prompt = build_prompt(text, context)
        started = time.perf_counter()
        usage: dict[str, Any] = {}
        last_error: InvalidModelOutput | None = None
        for attempt in range(ATTEMPTS):
            response = self._call(client, prompt.system, prompt.user)
            usage = {**usage_from(response), "attempts": attempt + 1}
            stop = getattr(response, "stop_reason", "") or ""
            if stop == "refusal":
                # An answer, not an outage: these notes were declined, others will not be. Kept off
                # the breaker so a run of declined notes cannot shut extraction off for everyone.
                raise _refusal("Claude declined to extract these notes (stop_reason=refusal).")
            try:
                output = parse_output(answer_text(response))
            except InvalidModelOutput as exc:
                cut = f" (stop_reason={stop})" if stop and stop != "end_turn" else ""
                last_error = InvalidModelOutput(f"{exc}{cut}")
                continue
            return ProviderResult(
                output=output,
                provider=NAME,
                model=getattr(response, "model", "") or self.model,
                region="",
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
            )
        raise InvalidModelOutput(
            f"Claude ({self.model}) did not return the schema after {ATTEMPTS} attempts: {last_error}"
        )

    def _call(self, client: Any, system: str, user: str) -> Any:
        try:
            import anthropic
        except ImportError:  # a stub client in a test without the extra
            anthropic = None  # type: ignore[assignment]
        try:
            return client.beta.messages.create(
                system=system,
                messages=[{"role": "user", "content": user}],
                **self._request(),
            )
        except Exception as exc:
            if anthropic is not None:
                if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
                    raise _refusal(
                        f"Anthropic API key refused: check ANTHROPIC_API_KEY. {exc}",
                        FailureReason.PERMISSION_DENIED,
                    ) from exc
                if isinstance(exc, anthropic.NotFoundError):
                    raise _refusal(
                        f"The Anthropic API has no model {self.model!r}: check ANTHROPIC_MODEL. {exc}",
                        FailureReason.NOT_FOUND,
                    ) from exc
                if isinstance(exc, anthropic.RateLimitError):
                    raise _refusal(
                        f"The Anthropic API is rate-limiting this key (429); try again in a minute. {exc}",
                        FailureReason.RATE_LIMITED,
                    ) from exc
                if isinstance(exc, anthropic.BadRequestError):
                    raise _refusal(f"The Anthropic API refused the request: {exc}") from exc
            raise ExtractionError(f"The Anthropic API call failed: {exc}") from exc


def _refusal(message: str, reason: str = FailureReason.CLIENT_ERROR) -> AnthropicRefusal:
    error = AnthropicRefusal(message)
    error.failure_reason = reason
    return error


def answer_text(response: Any) -> str:
    """The text block structured outputs put the JSON in."""
    parts = [
        getattr(block, "text", "")
        for block in getattr(response, "content", None) or []
        if getattr(block, "type", "") == "text"
    ]
    text = "".join(parts).strip()
    if not text:
        raise InvalidModelOutput("no text block in the answer")
    return text


def usage_from(response: Any) -> dict[str, Any]:
    raw = getattr(response, "usage", None)
    out: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
        value = getattr(raw, key, None) if raw is not None else None
        if isinstance(value, int):
            out[key] = value
    return out
