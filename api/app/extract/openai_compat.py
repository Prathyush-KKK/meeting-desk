"""Bedrock's OpenAI-compatible endpoint, with a Bedrock API key.

The credential the nutrition service already runs on, under its names: ``BEDROCK_BASE_URL`` (for
example ``https://bedrock-mantle.us-east-1.api.aws/openai/v1``), ``AWS_BEARER_TOKEN_BEDROCK`` and
``BEDROCK_MODEL_ID``. One ``POST {base_url}/chat/completions`` with plain httpx - no SDK and no
SigV4, the key is a bearer token - so the image needs no extra for it.

What it shares with Vertex and the Converse API: the prompt from ``prompt.py`` (the rules, the
meeting context, the fenced notes and the injection guard, unchanged), ``parse.py`` into the strict
schema, one retry on an answer that is not the schema, and the telemetry - one
``track_provider("bedrock", "chat_completions")`` per extraction, the same ``bedrock`` breaker.

What differs, and why:

* JSON mode (``response_format: {"type": "json_object"}``) only promises *an* object; nothing
  enforces the schema the way Vertex's ``response_schema`` or Converse's forced tool does. So the
  schema travels in the system message, after prompt.py's text, and the retry tells the model what
  was wrong with its answer instead of asking the same question twice.
* Not every model behind the endpoint takes ``response_format``. A 400 with it is retried once
  without it; if that works, the endpoint and model are remembered for the process and not asked
  again.
* The output cap is sent as ``max_completion_tokens``, the name the endpoint is known to take
  for Gemma 4 (the nutrition service saw ``max_tokens`` refused with 400 "unsupported_parameter"
  in August 2026). A 400 that names ``max_completion_tokens`` is retried once under the older
  name, and remembered. ``reasoning_effort: "none"`` pins thinking off: the extraction is a
  transcription into a schema, and a minute of reasoning tokens is the difference between an
  answer and a timeout.
* The status codes are the endpoint's own: 401/403 is the key, 404 is the model, 429 is backed
  off once. Those are answers, not outages - ``EndpointRefusal`` tells the telemetry so, and the
  breaker never moves on them. Timeouts, unreachable hosts and 5xx do count.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.extract.parse import InvalidModelOutput, parse_output
from app.extract.prompt import Prompt, build_prompt
from app.extract.provider import ExtractionContext, ExtractionError, ProviderResult
from app.extract.schema import EXTRACTION_JSON_SCHEMA
from app.telemetry.breaker import BreakerOpen
from app.telemetry.events import FailureReason
from app.telemetry.logs import get_logger, log_event
from app.telemetry.providers import BEDROCK, track_provider

log = get_logger("extract.bedrock_openai")

NAME = "bedrock_openai"
OP = "chat_completions"
ATTEMPTS = 2  # the call, then one retry with a corrective message
TIMEOUT_SECONDS = 180.0  # default read timeout; BEDROCK_TIMEOUT_SECONDS overrides it
TOKEN_CAP = "max_completion_tokens"  # the OpenAI-current name; the endpoint refused max_tokens for Gemma 4
TOKEN_CAP_LEGACY = "max_tokens"
CONNECT_TIMEOUT_SECONDS = 10.0
BACKOFF_SECONDS = 2.0  # the one wait on a 429 without a usable Retry-After
MAX_RETRY_AFTER_SECONDS = 8.0  # the request is holding a person's browser open
DETAIL_CHARS = 300

_REGION_RE = re.compile(r"\.([a-z]{2}(?:-gov)?-[a-z]+-\d+)\.")

# (chat/completions URL, model) pairs that answered 400 to response_format and then worked without
# it. Process-wide on purpose: the provider is built once per process, and a worker or a test that
# builds another one should not pay the 400 again.
_JSON_MODE_REFUSED: set[tuple[str, str]] = set()
# The same, for (URL, model) pairs that refused ``max_completion_tokens`` and took ``max_tokens``.
_LEGACY_TOKEN_CAP: set[tuple[str, str]] = set()


def forget_json_mode_refusals() -> None:
    """Tests only: start again from asking for JSON mode and the current token cap everywhere."""
    _JSON_MODE_REFUSED.clear()
    _LEGACY_TOKEN_CAP.clear()


# --- refusals ---------------------------------------------------------------------------------------


class EndpointRefusal(ExtractionError):
    """A 4xx: the endpoint is up and said no. Counted as an error, never against the breaker."""

    failure_reason: str = FailureReason.CLIENT_ERROR
    counts_against_breaker = False

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class CredentialsRefused(EndpointRefusal):
    failure_reason = FailureReason.PERMISSION_DENIED


class ModelNotFound(EndpointRefusal):
    failure_reason = FailureReason.NOT_FOUND


class EndpointRateLimited(EndpointRefusal):
    failure_reason = FailureReason.RATE_LIMITED


# --- the pieces, pure ----------------------------------------------------------------------------------


def chat_completions_url(base_url: str) -> str:
    """``BEDROCK_BASE_URL`` as the nutrition service has it, with or without the trailing path."""
    base = base_url.strip().rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def region_of(base_url: str) -> str:
    """``us-east-1`` from ``bedrock-mantle.us-east-1.api.aws``; empty when the host does not say."""
    host = urlsplit(base_url.strip()).hostname or ""
    match = _REGION_RE.search(f".{host}.")
    return match.group(1) if match else ""


def _without_ordering(node: Any) -> Any:
    """``propertyOrdering`` is a Vertex extension; to this model it is only noise."""
    if isinstance(node, dict):
        return {k: _without_ordering(v) for k, v in node.items() if k != "propertyOrdering"}
    if isinstance(node, list):
        return [_without_ordering(v) for v in node]
    return node


SCHEMA_TEXT = json.dumps(_without_ordering(EXTRACTION_JSON_SCHEMA), separators=(",", ":"))


def system_text(prompt: Prompt) -> str:
    """prompt.py's system text, byte for byte, then the schema it refers to."""
    return (
        f"{prompt.system}\n\n"
        "The schema, as JSON Schema - answer with one JSON object that validates against it:\n"
        f"{SCHEMA_TEXT}"
    )


def corrective(reason: str) -> str:
    return (
        f"That answer could not be used: {reason}. Answer again with only the JSON object the schema "
        "describes - the keys action_items, decisions, risks and questions, each a list - with no "
        "prose before or after it and no code fence."
    )


def answer_text(body: dict[str, Any]) -> tuple[str | None, str]:
    """(the first choice's text, its finish_reason). Content may be a string or a list of parts."""
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise InvalidModelOutput("no choices in the answer")
    choice = choices[0]
    finish = str(choice.get("finish_reason") or "")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    elif content is not None and not isinstance(content, str):
        content = str(content)
    return content, finish


def reasoning_tokens(body: dict[str, Any]) -> int | None:
    """``usage.completion_tokens_details.reasoning_tokens`` when the endpoint reports it."""
    raw = body.get("usage") if isinstance(body, dict) else None
    details = raw.get("completion_tokens_details") if isinstance(raw, dict) else None
    value = details.get("reasoning_tokens") if isinstance(details, dict) else None
    return int(value) if isinstance(value, int | float) else None


def usage_from(body: dict[str, Any]) -> dict[str, Any]:
    raw = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for src, dst in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = raw.get(src)
        if isinstance(value, int | float):
            out[dst] = int(value)
    return out


def retry_after(response: httpx.Response) -> float:
    """Seconds to wait before the one retry: the header if it is a number, capped; else the default."""
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return BACKOFF_SECONDS
    if not seconds >= 0:  # negative or NaN
        return BACKOFF_SECONDS
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def error_detail(response: httpx.Response) -> str:
    """The endpoint's own words: OpenAI's ``error.message``, Bedrock's ``message``, or the text."""
    try:
        body = response.json()
    except ValueError:
        text = response.text
    else:
        text = ""
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                text = str(error.get("message") or "")
            elif isinstance(error, str):
                text = error
            text = text or str(body.get("message") or body.get("Message") or "")
        text = text or json.dumps(body)
    return " ".join(text.split())[:DETAIL_CHARS]


# --- the provider ---------------------------------------------------------------------------------------


class OpenAICompatExtractionProvider:
    name = NAME

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.model = settings.bedrock_model.strip()
        self.base_url = settings.bedrock_base_url.strip()
        self.url = chat_completions_url(self.base_url) if self.base_url else ""
        self.region = region_of(self.base_url)
        self._api_key = settings.bedrock_api_key.strip()
        self.timeout_seconds = float(getattr(settings, "bedrock_timeout_seconds", 0) or TIMEOUT_SECONDS)
        self._transport = transport
        self._client = client
        self._sleep = sleep

    def _http(self) -> httpx.Client:
        """Built on first use, so building the provider at startup costs nothing."""
        if self._client is None:
            self._client = httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(self.timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
            )
        return self._client

    def _missing(self) -> list[str]:
        return [
            name
            for name, value in (
                ("BEDROCK_BASE_URL", self.base_url),
                ("AWS_BEARER_TOKEN_BEDROCK", self._api_key),
                ("BEDROCK_MODEL_ID (or BEDROCK_MODEL)", self.model),
            )
            if not value
        ]

    # --- the call ------------------------------------------------------------------------------------
    def extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        missing = self._missing()
        if missing:
            # Configuration, not a call: checked before the telemetry so it is neither counted
            # nor held against the breaker.
            raise ExtractionError(
                "Bedrock's OpenAI-compatible endpoint is not configured: "
                f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set."
            )
        try:
            with track_provider(BEDROCK, OP):
                return self._extract(text, context)
        except BreakerOpen as exc:
            raise ExtractionError(str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise ExtractionError(
                f"Bedrock did not answer within the timeout at {self.url} ({type(exc).__name__})."
            ) from exc
        except httpx.HTTPError as exc:
            raise ExtractionError(f"could not reach Bedrock at {self.url}: {exc}") from exc

    def _extract(self, text: str, context: ExtractionContext) -> ProviderResult:
        prompt = build_prompt(text, context)
        conversation = [
            {"role": "system", "content": system_text(prompt)},
            {"role": "user", "content": prompt.user},
        ]
        messages = conversation
        started = time.perf_counter()
        last_reason = ""
        for attempt in range(ATTEMPTS):
            body, json_mode = self._complete(messages)
            usage = {
                **usage_from(body),
                "attempts": attempt + 1,
                "response_format": "json_object" if json_mode else "none",
            }
            content: str | None = None
            finish = ""
            try:
                content, finish = answer_text(body)
            except InvalidModelOutput:
                pass
            log_event(
                log,
                "bedrock_answered",
                attempt=attempt + 1,
                json_mode=json_mode,
                finish_reason=finish,
                content_chars=len(content or ""),
                reasoning_tokens=reasoning_tokens(body),
                duration_ms=(time.perf_counter() - started) * 1000,
                **{k: v for k, v in usage.items() if k.endswith("_tokens")},
            )
            try:
                if content is None and finish == "":
                    answer_text(body)  # raises with the reason
                output = parse_output(content)
            except InvalidModelOutput as exc:
                cut = f" (finish_reason={finish})" if finish and finish != "stop" else ""
                last_reason = f"{exc}{cut}"
                log_event(log, "bedrock_answer_rejected", level=logging.WARNING, attempt=attempt + 1, reason=last_reason[:DETAIL_CHARS])
                # The bad answer goes back as the assistant's turn - a placeholder when it was
                # empty, so user and assistant still alternate for chat templates that insist.
                messages = [
                    *conversation,
                    {"role": "assistant", "content": content or "(no answer)"},
                    {"role": "user", "content": corrective(last_reason)},
                ]
                continue
            return ProviderResult(
                output=output,
                # The vendor that answered: the label the telemetry, the extraction record and the
                # UI already use for Bedrock. ``name`` says which API path it went through.
                provider=BEDROCK,
                model=self.model,
                region=self.region,
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
            )
        raise InvalidModelOutput(
            f"Bedrock ({self.model}) did not return the schema after {ATTEMPTS} attempts: {last_reason}"
        )

    def _complete(self, messages: list[dict[str, str]]) -> tuple[dict[str, Any], bool]:
        """One logical completion: at most one 429 backoff, one retry under the older token-cap
        name, and one retry without JSON mode."""
        key = (self.url, self.model)
        json_mode = key not in _JSON_MODE_REFUSED
        legacy_cap = key in _LEGACY_TOKEN_CAP
        backed_off = False
        dropped_json_mode = False
        switched_cap = False
        while True:
            started = time.perf_counter()
            response = self._http().post(
                self.url, headers=self._headers(), json=self._body(messages, json_mode, legacy_cap)
            )
            status = response.status_code
            detail = "" if response.is_success else self._scrub(error_detail(response))
            log_event(
                log,
                "bedrock_round",
                level=logging.INFO if response.is_success else logging.WARNING,
                status=status,
                json_mode=json_mode,
                token_cap=TOKEN_CAP_LEGACY if legacy_cap else TOKEN_CAP,
                duration_ms=(time.perf_counter() - started) * 1000,
                detail=detail,
            )
            if status == 429 and not backed_off:
                backed_off = True
                self._sleep(retry_after(response))
                continue
            if status == 400 and not legacy_cap and TOKEN_CAP in detail:
                # "Unsupported parameter: 'max_completion_tokens'": the endpoint wants the older
                # name for this model. Retried under it before anything else is given up.
                legacy_cap = True
                switched_cap = True
                continue
            if status == 400 and json_mode:
                json_mode = False
                dropped_json_mode = True
                continue
            if response.is_success:
                # Only now: a 400 that was about something else fails on the retry too, and must
                # not switch JSON mode (or the token-cap name) for good.
                if dropped_json_mode:
                    _JSON_MODE_REFUSED.add(key)
                if switched_cap:
                    _LEGACY_TOKEN_CAP.add(key)
                return self._json(response), json_mode
            raise self._refusal(response)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}

    def _body(self, messages: list[dict[str, str]], json_mode: bool, legacy_cap: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            (TOKEN_CAP_LEGACY if legacy_cap else TOKEN_CAP): self.settings.extraction_max_output_tokens,
            # Thinking off, explicitly (see the module docstring); a model that ignores it is unharmed.
            "reasoning_effort": "none",
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ExtractionError(
                f"Bedrock answered {response.status_code} but the body is not JSON: "
                f"{self._scrub(response.text[:DETAIL_CHARS])}"
            ) from exc
        if not isinstance(body, dict):
            raise ExtractionError(f"Bedrock answered {response.status_code} with JSON that is not an object")
        return body

    def _scrub(self, text: str) -> str:
        """Should an endpoint ever echo the key, it still never reaches a message or a log."""
        return text.replace(self._api_key, "[AWS_BEARER_TOKEN_BEDROCK]") if self._api_key else text

    def _refusal(self, response: httpx.Response) -> ExtractionError:
        status = response.status_code
        detail = self._scrub(error_detail(response))
        where = self.region or "the endpoint's region"
        if status in (401, 403):
            return CredentialsRefused(
                f"Bedrock credentials refused ({status}): check AWS_BEARER_TOKEN_BEDROCK - a Bedrock API "
                f"key that is current and may invoke {self.model!r} in {where}. The endpoint said: {detail}",
                status,
            )
        if status == 404:
            return ModelNotFound(
                f"Bedrock has no model {self.model!r} at {self.url} (404): check BEDROCK_MODEL_ID, and that "
                f"the model is offered in {where}. The endpoint said: {detail}",
                status,
            )
        if status == 429:
            return EndpointRateLimited(
                f"Bedrock is rate-limiting this key (429), still after one backoff; try again in a "
                f"minute. The endpoint said: {detail}",
                status,
            )
        if 400 <= status < 500:
            return EndpointRefusal(f"Bedrock refused the request ({status}): {detail}", status)
        return ExtractionError(f"Bedrock answered {status}: {detail}")
