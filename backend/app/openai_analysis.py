"""OpenAI Responses adapter. Same validated proposals; no storage or implicit retries."""

import json

import httpx
from pydantic import ValidationError

from .analysis import (
    FULL_SYSTEM,
    SYSTEM,
    TOPIC_SYSTEM,
    ProviderError,
    output_contract,
    serialized_request,
)
from .analysis_errors import contract_errors
from .diagnostics import provider_metadata, request_sent, response_received


def output_schema(context):
    schema = output_contract(context).model_json_schema()

    def strict(node):
        if isinstance(node, list):
            return [strict(value) for value in node]
        if not isinstance(node, dict):
            return node
        result = {
            key: {name: strict(child) for name, child in value.items()}
            if key in {"properties", "$defs"}
            else strict(value)
            for key, value in node.items()
            if key not in {"default", "title"}
        }
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result

    return strict(schema)


def request_payload(context, model):
    payload = {
        "model": model,
        "store": False,
        "instructions": SYSTEM
        + (TOPIC_SYSTEM if context.get("strategy") == "topics-v1" else "")
        + (FULL_SYSTEM if context.get("scope") == "full-transcript" else ""),
        "input": [{"role": "user", "content": json.dumps(context)}],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 16384 if context.get("scope") == "full-transcript" else 4096,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "meeting_analysis",
                "strict": True,
                "schema": output_schema(context),
            }
        },
    }
    if context.get("scope") == "full-transcript" and len(serialized_request(payload)) > 1_000_000:
        raise ProviderError(
            "Full transcript request exceeds the 1 MB analysis limit. Nothing was sent.",
            "full_input_limit",
        )
    return payload


class OpenAIAnalyzer:
    def __init__(self, key, model, timeout=40):
        self.key, self.model, self.timeout = key, model, timeout

    async def analyze(self, context):
        payload = request_payload(context, self.model)
        request_sent(payload)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=min(10, self.timeout))
            ) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.key}",
                        "content-type": "application/json",
                    },
                    content=serialized_request(payload),
                )
            response_received(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            message = {
                400: "OpenAI rejected the request. Check model/schema in Developer tools.",
                401: "OpenAI authentication failed. Check OPENAI_API_KEY on the server.",
                403: "OpenAI access denied. Check project permissions.",
                404: "OpenAI model is unavailable for this project.",
                429: "OpenAI quota or rate limit reached. Check API billing and limits.",
            }.get(status, "OpenAI is temporarily unavailable. Transcript is saved; retry later.")
            provider_metadata(error_stage="http_status")
            raise ProviderError(message, f"provider_http_{status}") from None
        except httpx.TimeoutException:
            provider_metadata(error_stage="request")
            raise ProviderError(
                "OpenAI timed out. Transcript is saved; retry analysis.", "provider_timeout_request"
            ) from None
        except httpx.RequestError:
            raise ProviderError(
                "Could not reach OpenAI. Check network access.", "provider_network"
            ) from None
        try:
            body = response.json()
            raw = body.get("usage") or {}
            usage = {
                target: raw[source]
                for source, target in [
                    ("input_tokens", "promptTokenCount"),
                    ("output_tokens", "candidatesTokenCount"),
                    ("total_tokens", "totalTokenCount"),
                ]
                if type(raw.get(source)) is int and raw[source] >= 0
            }
            provider_metadata(usage=usage)
            if body.get("status") != "completed":
                raise ProviderError(
                    "OpenAI returned incomplete analysis. Nothing was applied; retry analysis.",
                    "provider_incomplete",
                )
            parts = [
                part
                for item in body.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
            ]
            if any(part.get("type") == "refusal" for part in parts):
                raise ProviderError(
                    "OpenAI declined this analysis request. Transcript is saved.",
                    "provider_refusal",
                )
            text = "".join(
                part.get("text", "") for part in parts if part.get("type") == "output_text"
            )
            contract = output_contract(context)
            return contract.model_validate_json(text), usage
        except ValidationError as exc:
            provider_metadata(validation_details=contract_errors(exc, output_contract(context)))
            raise ProviderError(
                "OpenAI returned invalid structured analysis. Nothing was applied.",
                "provider_invalid_output",
            ) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError(
                "OpenAI returned an unreadable response. Nothing was applied.",
                "provider_invalid_output",
            ) from None
