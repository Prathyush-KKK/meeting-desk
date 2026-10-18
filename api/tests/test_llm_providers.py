"""The prompt builder, the response parser, Vertex and Bedrock on recorded outputs, the fallback."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.extract import build_provider
from app.extract.bedrock import TOOL_NAME, BedrockExtractionProvider, tool_config
from app.extract.fake import FakeExtractionProvider
from app.extract.fallback import FallbackExtractionProvider
from app.extract.parse import InvalidModelOutput, parse_output
from app.extract.prompt import MAX_INPUT_CHARS, build_prompt
from app.extract.provider import ExtractionContext, ExtractionError
from app.extract.schema import EXTRACTION_JSON_SCHEMA, PROMPT_RULES
from app.extract.vertex import VertexExtractionProvider

IST = ZoneInfo("Asia/Kolkata")
LLM = Path(__file__).resolve().parent / "fixtures" / "llm"

CONTEXT = ExtractionContext(
    meeting_title="Mobile roadmap review",
    meeting_start=datetime(2026, 9, 19, 16, 0, tzinfo=IST),
    timezone="Asia/Kolkata",
    workstream="Mobile",
    attendees=[
        {"name": "Daniel Okafor", "email": "daniel.okafor@example.com"},
        {"name": "Anna Moreno", "email": "anna.moreno@example.com"},
        {"name": "Noah S", "email": "noah.s@example.com"},
    ],
)


def recorded(name: str) -> dict[str, Any]:
    return json.loads((LLM / name).read_text())


# --- the prompt -------------------------------------------------------------------------------------


def test_the_prompt_carries_the_rules_the_context_and_the_notes_verbatim() -> None:
    prompt = build_prompt("The Next Steps\nNoah: finish the standard by Friday", CONTEXT)
    assert PROMPT_RULES.splitlines()[0] in prompt.system
    assert "Weight the Next steps section" in prompt.system
    assert "never invent" in prompt.system
    assert "- title: Mobile roadmap review" in prompt.user
    assert "- held on: Saturday 19 September 2026, 16:00 (Asia/Kolkata)" in prompt.user
    assert "- workstream: Mobile" in prompt.user
    assert "  - Anna Moreno" in prompt.user
    fence = prompt.delimiter
    assert prompt.user.endswith(f"{fence}\nThe Next Steps\nNoah: finish the standard by Friday\n{fence}")
    assert prompt.text == f"{prompt.system}\n\n{prompt.user}"


def test_the_prompt_is_deterministic_and_capped() -> None:
    # Everything but the per-call delimiter is a pure function of the notes and the context.
    one, two = build_prompt("x", CONTEXT), build_prompt("x", CONTEXT)
    assert one.system == two.system
    assert one.user.replace(one.delimiter, "") == two.user.replace(two.delimiter, "")
    long = "a" * (MAX_INPUT_CHARS + 500)
    capped = build_prompt(long, None)
    body = capped.user.split(capped.delimiter)[1]
    assert len(body.strip()) == MAX_INPUT_CHARS
    bare = build_prompt("notes", None)
    assert "- title: (untitled)" in bare.user
    assert "attendees" not in bare.user


# --- the parser -------------------------------------------------------------------------------------


def test_clean_json_fenced_json_and_prose_around_json_all_parse() -> None:
    payload = recorded("vertex_roadmap_review.json")["response"]["text"]
    output = parse_output(payload)
    assert [a.owner_text for a in output.action_items] == ["Anna Moreno", "Noah", "Daniel"]
    assert output.action_items[0].status_hint == "open"
    assert output.action_items[1].status_hint is None
    assert output.total() == 7
    assert parse_output(f"```json\n{payload}\n```").total() == 7
    assert parse_output(f"Here you go:\n{payload}\nAnything else?").total() == 7
    assert parse_output(json.loads(payload)).total() == 7


def test_small_liberties_are_tolerated_and_real_breakage_is_not() -> None:
    lenient = {
        "action_items": [
            {
                "title": "Ship it",
                "owner_text": None,
                "due_hint": None,
                "status_hint": "In Progress",
                "evidence": None,
            },
            {"title": "   ", "owner_text": "x"},  # an empty title is dropped
            "not an object",
        ],
        "decisions": [{"statement": "Go", "evidence": "Go"}],
        "risks": None,
        "questions": [],
    }
    output = parse_output(lenient)
    assert len(output.action_items) == 1
    assert output.action_items[0].owner_text == ""
    assert output.action_items[0].status_hint == "in_progress"
    assert output.risks == []

    for broken in (
        "",
        "   ",
        "no json here",
        "[1, 2]",
        '{"action_items": "nope"}',
        '{"action_items": [',
        None,
    ):
        with pytest.raises(InvalidModelOutput):
            parse_output(broken)


# --- Vertex -----------------------------------------------------------------------------------------


class RecordedVertexModel:
    """Stands in for ``GenerativeModel``: answers from the recorded responses, in order."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, prompt: str, generation_config: dict[str, Any]) -> Any:
        self.calls.append({"prompt": prompt, "generation_config": generation_config})
        raw = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        usage = SimpleNamespace(**raw["usage_metadata"])
        candidates = [SimpleNamespace(finish_reason=raw.get("finish_reason", "STOP"))]
        if raw["text"] == "":
            return BlockedResponse(usage, candidates)
        return SimpleNamespace(text=raw["text"], usage_metadata=usage, candidates=candidates)


class BlockedResponse:
    """What the SDK hands back when the candidate was blocked: ``.text`` raises."""

    def __init__(self, usage: Any, candidates: list[Any]) -> None:
        self.usage_metadata = usage
        self.candidates = candidates

    @property
    def text(self) -> str:
        raise ValueError("Response has no text; finish_reason=SAFETY")


def _vertex(responses: list[dict[str, Any]]) -> tuple[VertexExtractionProvider, RecordedVertexModel, list]:
    model = RecordedVertexModel(responses)
    made: list[tuple[str, str]] = []

    def factory(model_name: str, system_instruction: str) -> RecordedVertexModel:
        made.append((model_name, system_instruction))
        return model

    settings = Settings(
        _env_file=None, fake_llm=False, extraction_provider="vertex", vertex_project="my-gcp-project"
    )
    return VertexExtractionProvider(settings, model_factory=factory), model, made


def test_vertex_calls_gemini_in_the_configured_location_with_the_schema_and_temperature_zero() -> None:
    fixture = recorded("vertex_roadmap_review.json")
    provider, model, made = _vertex([fixture["response"]])
    result = provider.extract(fixture["notes"], CONTEXT)

    assert made == [("gemini-2.5-flash", build_prompt("", CONTEXT).system)]
    config = model.calls[0]["generation_config"]
    assert config["temperature"] == 0
    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] == EXTRACTION_JSON_SCHEMA
    assert "Anna Moreno: Review dataset for currency information by 3 Oct" in model.calls[0]["prompt"]

    assert result.provider == "vertex"
    assert result.model == "gemini-2.5-flash"
    assert result.region == "us-central1"
    assert result.usage == {"input_tokens": 1412, "output_tokens": 388, "total_tokens": 1800, "attempts": 1}
    assert result.output.total() == 7
    assert result.output.decisions[0].statement == "The Owner column holds a person, not a team"


def test_vertex_retries_once_on_invalid_output_then_succeeds() -> None:
    fixture = recorded("vertex_invalid_then_valid.json")
    provider, model, _ = _vertex(fixture["responses"])
    result = provider.extract(fixture["notes"], CONTEXT)
    assert len(model.calls) == 2
    assert result.usage["attempts"] == 2
    assert result.output.total() == 7


def test_vertex_gives_up_after_two_bad_answers_with_the_notes_untouched() -> None:
    fixture = recorded("vertex_always_invalid.json")
    provider, model, _ = _vertex(fixture["responses"])
    with pytest.raises(ExtractionError) as err:
        provider.extract(fixture["notes"], CONTEXT)
    assert len(model.calls) == 2
    assert "did not return valid JSON after 2 attempts" in str(err.value)
    assert "SAFETY" in str(err.value)


def test_vertex_sdk_failures_are_extraction_errors() -> None:
    class Down:
        def generate_content(self, prompt: str, generation_config: dict[str, Any]) -> Any:
            raise RuntimeError("503 The service is currently unavailable")

    settings = Settings(_env_file=None, fake_llm=False, extraction_provider="vertex", vertex_project="p")
    provider = VertexExtractionProvider(settings, model_factory=lambda name, system: Down())
    with pytest.raises(ExtractionError, match="Vertex AI refused the call"):
        provider.extract("notes", CONTEXT)


# --- Bedrock ----------------------------------------------------------------------------------------


class RecordedBedrock:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def test_bedrock_uses_converse_with_the_schema_as_a_forced_tool() -> None:
    fixture = recorded("bedrock_roadmap_review.json")
    client = RecordedBedrock([fixture["response"]])
    settings = Settings(
        _env_file=None,
        fake_llm=False,
        extraction_provider="bedrock",
        bedrock_model="anthropic.claude-3-5-sonnet-20240620-v1:0",
    )
    result = BedrockExtractionProvider(settings, client=client).extract(fixture["notes"], CONTEXT)

    call = client.calls[0]
    assert call["modelId"] == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert call["inferenceConfig"] == {"temperature": 0, "maxTokens": 8192}
    assert call["toolConfig"] == tool_config()
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert call["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"] == {"json": EXTRACTION_JSON_SCHEMA}
    assert call["system"][0]["text"] == build_prompt("", CONTEXT).system
    assert (
        "Noah: Finish the alert emission standard v1.2 by end of week"
        in call["messages"][0]["content"][0]["text"]
    )

    assert result.provider == "bedrock"
    assert result.region == "us-east-1"
    assert result.usage == {
        "input_tokens": 1655,
        "output_tokens": 421,
        "total_tokens": 2076,
        "model_latency_ms": 6120,
        "attempts": 1,
    }
    assert [a.title for a in result.output.action_items][:2] == [
        "Review dataset for currency information",
        "Finish the alert emission standard v1.2",
    ]


def test_bedrock_without_a_tool_call_retries_then_fails() -> None:
    fixture = recorded("bedrock_no_tool_call.json")
    client = RecordedBedrock([fixture["response"]])
    settings = Settings(_env_file=None, fake_llm=False, extraction_provider="bedrock")
    with pytest.raises(ExtractionError, match="did not return the schema after 2 attempts"):
        BedrockExtractionProvider(settings, client=client).extract(fixture["notes"], CONTEXT)
    assert len(client.calls) == 2


# --- the fallback and provider selection -----------------------------------------------------------


class Failing:
    name = "vertex"

    def extract(self, text: str, context: ExtractionContext) -> Any:
        raise ExtractionError("quota exceeded in asia-south1")


def test_the_fallback_answers_from_bedrock_and_says_so() -> None:
    fixture = recorded("bedrock_roadmap_review.json")
    settings = Settings(_env_file=None, fake_llm=False)
    bedrock = BedrockExtractionProvider(settings, client=RecordedBedrock([fixture["response"]]))
    provider = FallbackExtractionProvider(Failing(), bedrock)
    result = provider.extract(fixture["notes"], CONTEXT)
    assert result.provider == "bedrock"
    assert result.usage["fallback_from"] == "vertex"
    assert result.usage["fallback_reason"] == "quota exceeded in asia-south1"


def test_both_failing_names_both() -> None:
    provider = FallbackExtractionProvider(
        Failing(), BedrockExtractionProvider(Settings(_env_file=None), client=RecordedBedrock([{}]))
    )
    with pytest.raises(ExtractionError) as err:
        provider.extract("notes", CONTEXT)
    assert "vertex: quota exceeded" in str(err.value)
    assert "bedrock:" in str(err.value)


def test_build_provider_follows_the_flags() -> None:
    assert isinstance(build_provider(Settings(_env_file=None, fake_llm=True)), FakeExtractionProvider)
    assert isinstance(
        build_provider(Settings(_env_file=None, fake_llm=False, extraction_provider="fake")),
        FakeExtractionProvider,
    )
    vertex = build_provider(Settings(_env_file=None, fake_llm=False, extraction_provider="vertex"))
    assert isinstance(vertex, VertexExtractionProvider)
    bedrock = build_provider(Settings(_env_file=None, fake_llm=False, extraction_provider="bedrock"))
    assert isinstance(bedrock, BedrockExtractionProvider)
    with_fallback = build_provider(
        Settings(_env_file=None, fake_llm=False, extraction_provider="vertex", bedrock_fallback_enabled=True)
    )
    assert isinstance(with_fallback, FallbackExtractionProvider)
    assert with_fallback.name == "vertex"
    assert isinstance(with_fallback.fallback, BedrockExtractionProvider)
    with pytest.raises(ValueError):
        build_provider(Settings(_env_file=None, fake_llm=False, extraction_provider="mistral"))


def test_the_fallback_flag_answers_to_its_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACT_FALLBACK_TO_BEDROCK", "1")
    assert Settings(_env_file=None).bedrock_fallback_enabled is True
    monkeypatch.setenv("EXTRACT_FALLBACK_TO_BEDROCK", "0")
    assert Settings(_env_file=None).bedrock_fallback_enabled is False
