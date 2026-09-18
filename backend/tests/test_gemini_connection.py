import httpx
import pytest

from app.analysis import GeminiAnalyzer, ProviderError, Suggestion
from app.config import Settings
from app.gemini_smoke import check


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "rejected"),
        (401, "authentication"),
        (403, "access denied"),
        (404, "model not found"),
        (429, "quota"),
        (503, "temporarily unavailable"),
    ],
)
async def test_safe_provider_error_without_automatic_retries(monkeypatch, status, expected):
    client = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private-transcript-and-secret"})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(ProviderError) as exc:
        await GeminiAnalyzer("private-key", "gemini-3.1-flash-lite").analyze({})
    assert expected in str(exc.value)
    assert exc.value.code == f"provider_http_{status}"
    if status == 503:
        assert "Transcript is saved" in str(exc.value)
        assert "API key" not in str(exc.value)
    assert "private" not in str(exc.value)
    assert len(calls) == 1


async def test_smoke_is_one_call_and_uses_only_synthetic_data(monkeypatch, tmp_path):
    calls = []

    async def analyze(self, context):
        calls.append(context)
        assert len(context["segments"]) == 4
        assert all(s["event_id"].startswith("smoke-") for s in context["segments"])
        return Suggestion(
            question="What delayed the reporting work?", rationale="Test", source_ids=["turn-4"]
        ), {"promptTokenCount": 10}

    monkeypatch.setattr(GeminiAnalyzer, "analyze", analyze)
    result = await check(Settings(data_dir=tmp_path / "untouched", gemini_api_key="fake"))
    assert result["status"] == "passed" and result["report_created"]
    assert result["calls"] == 1 and len(calls) == 1
    assert not (tmp_path / "untouched").exists()


async def test_missing_key_never_calls_provider(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Must not call provider")

    monkeypatch.setattr(GeminiAnalyzer, "analyze", forbidden)
    result = await check(Settings(gemini_api_key=""))
    assert result["status"] == "unconfigured"


def test_wire_schema_is_simple_but_local_limits_remain():
    import json

    from pydantic import ValidationError

    from app.analysis import gemini_output_schema

    schema = gemini_output_schema()
    wire = json.dumps(schema)
    assert "$ref" not in wire and "maxLength" not in wire
    assert schema["properties"]["workflows"]["items"]["type"] == "object"
    assert schema["properties"]["findings"]["items"]["properties"]["kind"]["enum"]
    with pytest.raises(ValidationError):
        Suggestion(question="x" * 501, rationale="", source_ids=[])
    with pytest.raises(ValidationError):
        Suggestion(question="", rationale="", source_ids=[], unexpected="untrusted")


def test_workflow_transition_schema_requires_evidence_ids_not_step_labels():
    from app.analysis import gemini_output_schema
    from app.analysis_state import validate_proposal

    context = {"segments": [{"segment_id": "turn-4"}], "meeting": {"previous_questions": []}}
    schema = gemini_output_schema(context)
    transitions = schema["properties"]["workflows"]["items"]["properties"]["transitions"]
    assert transitions["items"]["items"]["enum"] == ["turn-4"]
    assert "never step names" in transitions["description"]
    proposal = Suggestion.model_validate(
        {
            "question": "",
            "rationale": "",
            "source_ids": [],
            "workflows": [
                {
                    "key": "reporting",
                    "title": "Reporting",
                    "steps": [
                        {"label": "Export numbers", "source_ids": ["turn-4"]},
                        {"label": "Paste numbers", "source_ids": ["turn-4"]},
                    ],
                    "transitions": [["Export numbers", "Paste numbers"]],
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="evidence"):
        validate_proposal(proposal, context)
    proposal.workflows[0].transitions = [["turn-4"]]
    validate_proposal(proposal, context)


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "output token limit"),
        ({"promptFeedback": {"blockReason": "private"}}, "blocked"),
        ({"candidates": []}, "no analysis candidate"),
        ({"candidates": [{"finishReason": "SAFETY"}]}, "stopped without"),
        (
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "private"}]}}]},
            "malformed JSON",
        ),
        (
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"question":"private"}'}]},
                    }
                ]
            },
            "analysis contract",
        ),
    ],
)
async def test_structured_failures_are_distinct_safe_and_single_call(monkeypatch, body, expected):
    client = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(ProviderError) as exc:
        await GeminiAnalyzer("private", "test-model").analyze({})
    assert expected in str(exc.value)
    assert "private" not in str(exc.value)
    assert len(calls) == 1


def test_wire_describes_local_bounds_without_complicating_grammar():
    from app.analysis import gemini_output_schema

    schema = gemini_output_schema()
    assert "Maximum characters: 500" in schema["properties"]["question"]["description"]
    assert "Maximum items: 12" in schema["properties"]["claims"]["description"]
