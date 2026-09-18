import json

import httpx
import pytest
from pydantic import ValidationError

from app.analysis import FullTopicSuggestion, GeminiAnalyzer, ProviderError, gemini_output_schema
from app.analysis_errors import contract_errors


def test_full_schema_bounds_evidence_without_expanding_nested_object_grammar():
    schema = gemini_output_schema({"scope": "full-transcript", "strategy": "topics-v1"})
    props = schema["properties"]
    assert "maxItems" not in props["claims"]
    assert "Maximum items: 80" in props["claims"]["description"]
    assert "maxItems" not in props["topic"]["properties"]["updates"]
    assert "Maximum items: 24" in props["topic"]["properties"]["updates"]["description"]
    with pytest.raises(ValidationError) as caught:
        FullTopicSuggestion.model_validate(
            {
                "complete": True,
                "question": "",
                "rationale": "",
                "source_ids": [],
                "spoken_questions": [{"text": "Why?", "source_ids": ["s"]}] * 201,
            }
        )
    assert any(e["type"] == "too_long" for e in caught.value.errors())
    refs = props["topic"]["properties"]["updates"]["items"]["properties"]["source_ids"]
    assert refs["maxItems"] == 10 and refs["minItems"] == 1


def test_validation_diagnostics_do_not_expose_values_or_unknown_keys():
    with pytest.raises(ValidationError) as caught:
        FullTopicSuggestion.model_validate(
            {
                "complete": True,
                "question": "",
                "rationale": "",
                "source_ids": [],
                "topic": {
                    "updates": [
                        {
                            "topic_id": "new:one",
                            "title": "private",
                            "summary": "secret",
                            "source_ids": ["private"] * 11,
                        }
                    ]
                },
                "secret object key": "private",
            }
        )
    details = contract_errors(caught.value, FullTopicSuggestion)
    assert details[0] == {
        "type": "too_long",
        "path": "topic.updates[].source_ids",
        "actual_length": 11,
        "max_length": 10,
    }
    assert "private" not in json.dumps(details) and "secret" not in json.dumps(details)


async def test_provider_rejects_oversized_evidence_without_silent_truncation(monkeypatch):
    original = httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        assert (
            body["generationConfig"]["responseJsonSchema"]["properties"]["source_ids"]["maxItems"]
            == 10
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "complete": True,
                                            "question": "Synthetic question",
                                            "rationale": "test",
                                            "source_ids": [f"s{i}" for i in range(11)],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(ProviderError, match="source_ids") as error:
        await GeminiAnalyzer("synthetic", "synthetic").analyze(
            {"scope": "full-transcript", "segments": []}
        )
    assert error.value.code == "provider_output_limit"


def test_opportunity_certainty_is_downgraded_without_relaxing_contract():
    from app.analysis import Finding

    finding = dict(
        kind="opportunity",
        title="Explore a workflow",
        body="Synthetic hypothesis",
        basis="observed",
        source_ids=["s1"],
    )
    assert Finding.model_validate(finding).basis == "inferred"
    assert finding["basis"] == "observed"  # Original provider payload is not rewritten.
    assert Finding.model_validate({**finding, "kind": "workflow"}).basis == "observed"
    for invalid in ({**finding, "basis": "proven"}, {**finding, "extra": True}):
        with pytest.raises(ValidationError):
            Finding.model_validate(invalid)
