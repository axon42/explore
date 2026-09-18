import json

import httpx
import pytest

from app.analysis import ProviderError
from app.openai_analysis import OpenAIAnalyzer, output_schema, request_payload


def test_strict_schema_requires_all_fields_and_no_extra_keys():
    schema = output_schema({"scope": "full-transcript", "strategy": "topics-v1"})

    def visit(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    body = request_payload({"scope": "full-transcript"}, "gpt-5.6-terra")
    assert body["store"] is False and body["max_output_tokens"] == 16384
    assert body["reasoning"] == {"effort": "low"}
    with pytest.raises(ProviderError, match="1 MB"):
        request_payload({"scope": "full-transcript", "text": "x" * 1_000_000}, "gpt-5.6-terra")


@pytest.mark.parametrize(
    "case", ["success", "503", "401", "timeout", "refusal", "incomplete", "invalid", "bad_json"]
)
async def test_openai_adapter_safe_errors_single_call_and_contract(monkeypatch, case):
    original = httpx.AsyncClient
    calls = []
    proposal = {
        "complete": True,
        "question": "What happened last time?",
        "rationale": "Synthetic",
        "source_ids": ["s1"],
    }

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-terra" and body["store"] is False
        assert request.headers["authorization"] == "Bearer private-key"
        if case in {"503", "401"}:
            return httpx.Response(
                int(case), json={"error": {"message": "private-key private transcript"}}
            )
        if case == "timeout":
            raise httpx.ReadTimeout("private-key", request=request)
        if case == "bad_json":
            return httpx.Response(200, content=b"not json")
        item = {
            "type": "output_text",
            "text": json.dumps(
                proposal if case != "invalid" else {**proposal, "unknown": "private"}
            ),
        }
        if case == "refusal":
            item = {"type": "refusal", "refusal": "private"}
        return httpx.Response(
            200,
            json={
                "status": "incomplete" if case == "incomplete" else "completed",
                "output": [{"type": "message", "content": [item]}],
                "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    analyzer = OpenAIAnalyzer("private-key", "gpt-5.6-terra")
    if case == "success":
        result, usage = await analyzer.analyze({"scope": "full-transcript"})
        assert result.complete and result.question == proposal["question"]
        assert usage["totalTokenCount"] == 15
    else:
        with pytest.raises(ProviderError) as exc:
            await analyzer.analyze({"scope": "full-transcript"})
        assert "private" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize("scope", ["incremental", "full-transcript"])
@pytest.mark.parametrize("strategy", ["legacy", "topics-v1"])
def test_wire_schema_preserves_every_contract_property(scope, strategy):
    from app.analysis import output_contract

    context = {"scope": scope, "strategy": strategy}
    original = output_contract(context).model_json_schema()
    wire = output_schema(context)

    def compare(source, target):
        if isinstance(source, dict):
            for key, value in source.items():
                if key in {"properties", "$defs"}:
                    assert set(target[key]) == set(value)
                    for name, child in value.items():
                        compare(child, target[key][name])
                elif key not in {"default", "title", "required"}:
                    compare(value, target[key])
        elif isinstance(source, list):
            assert len(source) == len(target)
            for child, converted in zip(source, target, strict=True):
                compare(child, converted)
        else:
            assert source == target

    compare(original, wire)
    finding = wire["$defs"]["Finding"]
    assert "title" in finding["properties"] and "title" in finding["required"]
