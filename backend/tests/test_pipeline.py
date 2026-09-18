import asyncio
import json

import httpx
import pytest

from app.analysis import GeminiAnalyzer, Suggestion
from app.broadcast import Broadcaster
from app.config import Settings
from app.models import TranscriptEvent
from app.pipeline import Pipeline, PlaybackCommand
from app.service import Service
from app.storage import Storage
from tests.prepared import automatic_session
from tests.test_api import payload


@pytest.fixture
async def pipeline(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    pipeline = Pipeline(service, Settings(data_dir=tmp_path))
    service.on_final = pipeline.notify
    yield pipeline
    await pipeline.close()


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():  # noqa: ASYNC110 - bounded observation of background state
            await asyncio.sleep(0.02)


async def test_next_pause_persistence_and_no_future_context(pipeline):
    sid = automatic_session(pipeline.service.storage, "Replay")["id"]
    contexts = []

    async def record(context):
        contexts.append(context)
        return Suggestion(question="", rationale="", source_ids=[]), {}

    pipeline.provider.analyze = record
    for _ in range(2):
        await pipeline.command(sid, PlaybackCommand(action="next"))
    await wait_until(lambda: len(contexts) == 1)
    assert len(contexts[0]["segments"]) == 2
    assert "Last Friday" not in json.dumps(contexts)
    state = await pipeline.view(sid)
    assert state["cursor"] == 2 and not state["playing"]
    await pipeline.command(sid, PlaybackCommand(action="play", speed=10))
    await wait_until(lambda: pipeline.states[sid]["cursor"] == 3)
    await pipeline.command(sid, PlaybackCommand(action="pause"))
    await asyncio.sleep(0.65)
    assert pipeline.states[sid]["cursor"] == 3
    await pipeline.service.stop(sid)
    await pipeline.stop(sid)
    saved = pipeline.service.storage.experiment(sid)
    assert saved["cursor"] == 3 and saved["analysis_status"] == "stopped"


async def test_duplicate_coalescing_stale_result_and_stop(pipeline):
    sid = automatic_session(pipeline.service.storage, "Concurrency")["id"]
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def slow(context):
        calls.append(context)
        entered.set()
        await release.wait()
        return Suggestion(question="Why?", rationale="test", source_ids=["segment-1"]), {}

    pipeline.provider.analyze = slow
    event = TranscriptEvent(**payload(segment_id="segment-1", is_final=True))
    await pipeline.service.ingest(sid, event)
    await entered.wait()
    await pipeline.service.ingest(sid, event)
    assert len(calls) == 1
    await pipeline.service.ingest(
        sid, event.model_copy(update={"event_id": "corrected", "revision": 5, "text": "Correction"})
    )
    release.set()
    await wait_until(lambda: bool(pipeline.states[sid]["runs"]))
    assert pipeline.states[sid]["runs"][0]["stale"]
    assert pipeline.states[sid]["result"] is None
    await pipeline.service.stop(sid)
    await pipeline.stop(sid)
    await asyncio.sleep(0.5)
    assert len(calls) == 1


async def test_missing_key_and_call_limit(pipeline):
    sid = automatic_session(pipeline.service.storage, "No key")["id"]
    from app.model_selection import ModelSelection

    pipeline.settings = Settings(
        data_dir=pipeline.settings.data_dir, analysis_provider="gemini", gemini_api_key=""
    )
    pipeline.models = ModelSelection(pipeline.service.storage, pipeline.settings)
    await pipeline.command(sid, PlaybackCommand(action="next"))
    await wait_until(lambda: pipeline.states[sid]["analysis_status"] == "unconfigured")
    assert pipeline.states[sid]["calls"] == 0
    pipeline.settings = Settings(data_dir=pipeline.settings.data_dir, analysis_max_calls=1)
    pipeline.models = ModelSelection(pipeline.service.storage, pipeline.settings)
    await pipeline.command(sid, PlaybackCommand(action="next"))
    await wait_until(lambda: pipeline.states[sid]["analysis_status"] == "ready")
    await pipeline.command(sid, PlaybackCommand(action="next"))
    await wait_until(lambda: pipeline.states[sid]["analysis_status"] == "limited")
    assert pipeline.states[sid]["calls"] == 1


async def test_gemini_http_contract(monkeypatch):
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.headers["x-goog-api-key"] == "fake-key"
        data = json.loads(request.content)
        assert "responseJsonSchema" in data["generationConfig"]
        assert "future" not in data["contents"][0]["parts"][0]["text"]
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
                                            "question": "When?",
                                            "rationale": "Concrete example",
                                            "source_ids": ["s1"],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {"promptTokenCount": 20},
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result, usage = await GeminiAnalyzer("fake-key", "gemini-3.1-flash-lite").analyze(
        {"segments": [{"segment_id": "s1", "text": "It takes time"}]}
    )
    assert result.question == "When?" and usage["promptTokenCount"] == 20


async def test_provider_failure_does_not_block_ingestion(pipeline):
    async def fail(context):
        raise httpx.ConnectError("test")

    pipeline.provider.analyze = fail
    sid = automatic_session(pipeline.service.storage, "Failure")["id"]
    await pipeline.command(sid, PlaybackCommand(action="next"))
    await wait_until(lambda: pipeline.states[sid]["analysis_status"] == "error")
    await pipeline.command(sid, PlaybackCommand(action="next"))
    assert len(pipeline.service.storage.snapshot(sid)["segments"]) == 2
