"""EXTRACTION_PROVIDER=openai (any OpenAI-compatible endpoint) and EXTRACTION_PROVIDER=anthropic.

The generic endpoint shares its client with Bedrock's OpenAI-compatible path (covered in depth by
test_extract_openai_compat.py); these tests pin what differs: the names it reads, the optional key,
no ``reasoning_effort`` unless asked for, its own telemetry provider and its own messages. The
Claude provider is driven with a stub client shaped like the SDK's response.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import Settings
from app.extract import build_provider
from app.extract.anthropic_api import OUTPUT_SCHEMA, AnthropicExtractionProvider
from app.extract.openai_compat import (
    CredentialsRefused,
    OpenAICompatExtractionProvider,
    forget_json_mode_refusals,
    generic_endpoint,
)
from app.extract.parse import InvalidModelOutput
from app.extract.provider import ExtractionContext, ExtractionError
from app.telemetry.metrics import metrics
from app.telemetry.providers import ANTHROPIC, OPENAI

LLM = Path(__file__).parent / "fixtures" / "llm"
FIXTURE = json.loads((LLM / "bedrock_openai_roadmap_review.json").read_text())
GOOD_CONTENT = FIXTURE["response"]["choices"][0]["message"]["content"]

CONTEXT = ExtractionContext(
    meeting_title="Mobile roadmap review",
    meeting_start=datetime(2026, 9, 19, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    timezone="Asia/Kolkata",
    attendees=[{"name": "Anna Moreno", "email": "anna.moreno@example.com"}],
)


@pytest.fixture(autouse=True)
def _fresh_json_mode_memory() -> None:
    forget_json_mode_refusals()


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"_env_file": None, "fake_llm": False, "extraction_provider": "openai"}
    values.update(overrides)
    return Settings(**values)


def requests_to(answer: httpx.Response) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    return seen, httpx.MockTransport(handler)


def ok() -> httpx.Response:
    body = json.loads(json.dumps(FIXTURE["response"]))
    body["choices"][0]["message"]["content"] = GOOD_CONTENT
    return httpx.Response(200, json=body)


# --- openai -------------------------------------------------------------------------------------------


def test_openai_is_built_from_the_llm_names() -> None:
    provider = build_provider(settings(llm_api_key="sk-test", llm_model="gpt-test"))
    assert isinstance(provider, OpenAICompatExtractionProvider)
    assert provider.name == "openai"
    assert provider.url == "https://api.openai.com/v1/chat/completions"
    assert provider.model == "gpt-test"


def test_openai_api_key_is_read_from_the_openai_name_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert Settings(_env_file=None).llm_api_key == "sk-from-env"


def test_a_local_server_needs_no_key_and_gets_no_authorization_header() -> None:
    seen, transport = requests_to(ok())
    s = settings(llm_base_url="http://localhost:11434/v1", llm_model="llama3.1")
    result = OpenAICompatExtractionProvider(s, endpoint=generic_endpoint(s), transport=transport).extract(
        FIXTURE["notes"], CONTEXT
    )
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in seen[0].headers
    body = json.loads(seen[0].content)
    assert body["model"] == "llama3.1"
    assert "reasoning_effort" not in body  # only Bedrock pins it, or LLM_REASONING_EFFORT asks for it
    assert result.provider == OPENAI
    assert result.output.action_items


def test_the_key_is_a_bearer_token_and_reasoning_effort_is_sent_when_set() -> None:
    seen, transport = requests_to(ok())
    s = settings(llm_api_key="sk-test", llm_reasoning_effort="low")
    OpenAICompatExtractionProvider(s, endpoint=generic_endpoint(s), transport=transport).extract(
        FIXTURE["notes"], CONTEXT
    )
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert json.loads(seen[0].content)["reasoning_effort"] == "low"


def test_a_missing_model_is_named_by_its_llm_name() -> None:
    s = settings(llm_model="")
    with pytest.raises(ExtractionError, match="LLM_MODEL"):
        OpenAICompatExtractionProvider(s, endpoint=generic_endpoint(s)).extract("notes", CONTEXT)


def test_a_refused_key_names_llm_api_key_and_never_echoes_it() -> None:
    _, transport = requests_to(httpx.Response(401, json={"error": {"message": "bad key sk-secret"}}))
    s = settings(llm_api_key="sk-secret")
    with pytest.raises(CredentialsRefused) as caught:
        OpenAICompatExtractionProvider(s, endpoint=generic_endpoint(s), transport=transport).extract(
            "notes", CONTEXT
        )
    assert "LLM_API_KEY" in str(caught.value)
    assert "sk-secret" not in str(caught.value)
    sample = metrics().registry.get_sample_value(
        "external_provider_requests_total", {"provider": OPENAI, "op": "chat_completions", "outcome": "error"}
    )
    assert sample == 1.0


# --- anthropic ----------------------------------------------------------------------------------------


class StubMessages:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def stub_client(*responses: Any) -> tuple[Any, StubMessages]:
    messages = StubMessages(*responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def claude_answer(text: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=0),
    )


def test_anthropic_is_built_from_the_anthropic_names() -> None:
    provider = build_provider(settings(extraction_provider="anthropic", anthropic_api_key="sk-ant-test"))
    assert isinstance(provider, AnthropicExtractionProvider)
    assert provider.model == "claude-opus-5-5"


def test_anthropic_asks_for_the_schema_as_a_structured_output() -> None:
    client, messages = stub_client(claude_answer(GOOD_CONTENT))
    s = settings(extraction_provider="anthropic", anthropic_api_key="sk-ant-test")
    result = AnthropicExtractionProvider(s, client=client).extract(FIXTURE["notes"], CONTEXT)
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert call["output_config"]["effort"] == "medium"
    assert call["fallbacks"] == "default"
    assert call["max_tokens"] >= 16000
    assert "propertyOrdering" not in json.dumps(OUTPUT_SCHEMA)
    assert "temperature" not in call
    assert result.provider == ANTHROPIC
    assert result.output.action_items
    assert result.usage["input_tokens"] == 1200


def test_anthropic_retries_an_answer_that_is_not_the_schema_once() -> None:
    client, messages = stub_client(claude_answer("not json"), claude_answer(GOOD_CONTENT))
    s = settings(extraction_provider="anthropic", anthropic_api_key="sk-ant-test")
    result = AnthropicExtractionProvider(s, client=client).extract(FIXTURE["notes"], CONTEXT)
    assert len(messages.calls) == 2
    assert result.usage["attempts"] == 2

    client, _ = stub_client(claude_answer("still not json"))
    with pytest.raises(InvalidModelOutput, match="after 2 attempts"):
        AnthropicExtractionProvider(s, client=client).extract(FIXTURE["notes"], CONTEXT)


def test_anthropic_a_refusal_is_an_error_not_an_empty_result() -> None:
    client, _ = stub_client(claude_answer("", stop="refusal"))
    s = settings(extraction_provider="anthropic", anthropic_api_key="sk-ant-test")
    with pytest.raises(ExtractionError, match="refusal"):
        AnthropicExtractionProvider(s, client=client).extract(FIXTURE["notes"], CONTEXT)


def test_anthropic_without_a_key_says_so_before_any_call() -> None:
    s = settings(extraction_provider="anthropic")
    with pytest.raises(ExtractionError, match="ANTHROPIC_API_KEY"):
        AnthropicExtractionProvider(s).extract("notes", CONTEXT)
