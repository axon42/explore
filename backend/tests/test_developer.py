import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.analysis import GeminiAnalyzer, ProviderError, Suggestion
from app.analysis_state import ContextBuilder, empty_memory
from app.broadcast import Broadcaster
from app.config import Settings
from app.developer_access import LocalAdmin
from app.diagnostics import ACTIVE_TRACE, MAX_BODY, Diagnostics, SafeEvents
from app.main import create_app
from app.models import DomainError, TranscriptEvent
from app.pipeline import Pipeline
from app.service import Service
from app.storage import Storage
from tests.prepared import automatic_session
from tests.test_api import create, payload

ORIGIN = {"origin": "http://127.0.0.1:5173"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        yield client


def unlock(client):
    key = client.app.state.developer_admin.path.read_text()
    return client.post("/developer/unlock", headers=ORIGIN, json={"key": key})


def make_trace(diagnostics, sid):
    return diagnostics.begin(
        sid, {"job_id": "test-job", "segments": [], "new_source_ids": []}, "synthetic", 45
    )


def test_admin_boundary_origin_cookie_and_revocation(client):
    for path in ("/developer/status", "/developer/requests", "/developer/requests/nope"):
        assert client.get(path, headers={"X-Role": "admin"}).status_code == 403
    assert client.delete("/developer/history", headers=ORIGIN).status_code == 403
    assert client.put("/developer/recording", json={"enabled": True}).status_code == 403
    assert client.post("/developer/unlock", json={"key": "wrong"}).status_code == 403
    assert (
        client.post(
            "/developer/unlock", headers={"origin": "https://evil.test"}, json={"key": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post("/developer/unlock", headers=ORIGIN, json={"key": "wrong"}).status_code == 403
    )
    response = unlock(client)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    token = client.cookies.get("explore_developer")
    assert client.get("/developer/status").headers["cache-control"] == "no-store"
    assert client.put("/developer/recording", json={"enabled": True}).status_code == 403
    assert (
        client.put("/developer/recording", headers=ORIGIN, json={"enabled": "true"}).status_code
        == 422
    )
    assert client.put("/developer/recording", headers=ORIGIN, json={"enabled": True}).json()[
        "enabled"
    ]
    assert client.post("/developer/lock", headers=ORIGIN).status_code == 200
    client.cookies.set("explore_developer", token)
    assert client.get("/developer/status").status_code == 403
    assert not client.app.state.pipeline.diagnostics.recording()["enabled"]


def test_admin_key_permissions_rate_limit_and_expiry(tmp_path, monkeypatch):
    admin = LocalAdmin(tmp_path)
    key = admin.initialize()
    assert admin.path.stat().st_mode & 0o777 == 0o600
    assert LocalAdmin(tmp_path).initialize() == key
    admin.path.chmod(0o644)
    with pytest.raises(RuntimeError, match="private regular"):
        LocalAdmin(tmp_path).initialize()
    for _ in range(5):
        with pytest.raises(DomainError) as error:
            admin.unlock("wrong")
        assert error.value.code == "admin_required"
    with pytest.raises(DomainError) as error:
        admin.unlock(key)
    assert error.value.code == "admin_rate_limited"
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + 61)
    token = admin.unlock(key)
    request = type("Request", (), {"cookies": {"explore_developer": token}})()
    assert admin.authorized(request)
    monkeypatch.setattr(time, "monotonic", lambda: now + 3662)
    assert not admin.authorized(request)


def test_body_opt_in_redaction_limits_and_clear_wins(client):
    sid = create(client)
    diagnostics = client.app.state.pipeline.diagnostics
    trace = make_trace(diagnostics, sid)
    trace.request = "Private synthetic dialogue"
    trace.response = "Synthetic model answer"
    diagnostics.save(trace, "ok")
    assert diagnostics.detail(trace.id)["request_body"] is None
    assert diagnostics.detail(trace.id)["response_body"] is None
    unlock(client)
    client.put("/developer/recording", headers=ORIGIN, json={"enabled": True})
    trace = make_trace(diagnostics, sid)
    diagnostics.secrets.append("known-synthetic-key")
    trace.request = {"text": "known-synthetic-key", "test": "Bearer synthetic-token"}
    trace.response = "known-synthetic-key " + "x" * (MAX_BODY + 100)
    diagnostics.save(trace, "error", "provider_invalid_json")
    detail = client.get(f"/developer/requests/{trace.id}").json()
    assert "known-synthetic-key" not in json.dumps(detail)
    assert "synthetic-token" not in json.dumps(detail)
    assert "[REDACTED]" in detail["request_body"]
    assert len(detail["response_body"]) == MAX_BODY
    assert detail["metadata"]["body_truncated"]
    # List and normal experiment responses never expose raw diagnostic bodies.
    assert "request_body" not in client.get("/developer/requests").text
    assert "known-synthetic-key" not in client.get(f"/sessions/{sid}/experiment").text
    diagnostics.recording(False)
    diagnostics.save(trace, "ok")
    assert diagnostics.detail(trace.id)["request_body"] is None
    diagnostics.recording(True)
    late = make_trace(diagnostics, sid)
    assert client.delete("/developer/history", headers=ORIGIN).status_code == 200
    diagnostics.save(late, "ok")
    assert diagnostics.list() == []
    assert client.get(f"/sessions/{sid}").status_code == 200


def test_trace_retention_isolation_restart_and_migration(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    sid, other = storage.create("First")["id"], storage.create("Second")["id"]
    diagnostics = Diagnostics(storage, Settings(data_dir=tmp_path))
    for _ in range(102):
        make_trace(diagnostics, sid)
    assert len(diagnostics.list()) == 100
    other_trace = make_trace(diagnostics, other)
    assert [r["id"] for r in diagnostics.list(other)] == [other_trace.id]
    diagnostics.recording(True)
    expired = make_trace(diagnostics, sid)
    expired.created_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    diagnostics.save(expired, "ok")
    # An upsert preserves the original creation time; explicitly age the synthetic row.
    with storage.connection() as db:
        db.execute(
            "UPDATE developer_traces SET created_at=? WHERE id=?",
            (
                expired.created_at,
                expired.id,
            ),
        )
    assert expired.id not in {r["id"] for r in diagnostics.list()}
    diagnostics.bodies_until = time.monotonic() - 1
    diagnostics.save(other_trace, "ok")
    assert diagnostics.detail(other_trace.id)["request_body"] is None
    storage.initialize()
    assert all(r["outcome"] != "running" for r in diagnostics.list())
    with storage.connection() as db:
        db.execute("DROP TABLE developer_traces")
        db.execute("DELETE FROM schema_migrations WHERE version=10")
    storage.initialize()
    assert storage.snapshot(sid)["session"]["title"] == "First"
    with storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert diagnostics.list() == []


def test_logs_whitelist_rotation_and_restart(tmp_path):
    logs = SafeEvents()
    logs.initialize(tmp_path)
    logs.file.maxBytes = 180
    for _ in range(4):
        logs.handle(
            logging.LogRecord(
                "meeting",
                30,
                "",
                0,
                json.dumps(
                    {
                        "event": "analysis_error",
                        "code": "provider_timeout_read",
                        "status": 504,
                        "body": "DO NOT LOG THIS",
                        "headers": {"Authorization": "secret"},
                        "error_type": "private dialogue with spaces",
                    }
                ),
                (),
                None,
            )
        )
    logs.handle(logging.LogRecord("meeting", 40, "", 0, "private unstructured message", (), None))
    logs.file.close()
    for path in tmp_path.glob("developer-events.jsonl*"):
        assert path.stat().st_mode & 0o777 == 0o600
        assert "DO NOT LOG" not in path.read_text()
        assert "secret" not in path.read_text()
        assert "private" not in path.read_text()
    assert len(logs.tail()) == 4
    restored = SafeEvents()
    restored.initialize(tmp_path)
    assert restored.tail()[-1]["code"] == "provider_timeout_read"
    restored.file.close()


@pytest.mark.parametrize(
    "exception,stage", [(httpx.ConnectTimeout, "connect"), (httpx.ReadTimeout, "read")]
)
async def test_provider_timeout_classification_and_request_body(
    tmp_path, monkeypatch, exception, stage
):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    diagnostics = Diagnostics(storage, Settings(data_dir=tmp_path, gemini_api_key="fake-key"))
    sid = storage.create("Timeout")["id"]
    diagnostics.recording(True)
    trace = make_trace(diagnostics, sid)
    token = ACTIVE_TRACE.set(trace)
    real_client = httpx.AsyncClient

    def respond(request):
        raise exception("PRIVATE provider message", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await GeminiAnalyzer("fake-key", "test-model").analyze({"segments": []})
        assert error.value.code == f"provider_timeout_{stage}"
        assert "PRIVATE" not in str(error.value)
    finally:
        ACTIVE_TRACE.reset(token)
    diagnostics.save(trace, "error", error.value.code)
    detail = diagnostics.detail(trace.id)
    assert detail["metadata"]["error_stage"] == stage
    assert detail["metadata"]["request_kind"] == "provider_payload"
    assert "fake-key" not in detail["request_body"]
    assert detail["response_body"] is None


async def test_timeout_reduces_next_batch_without_advancing_checkpoint(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    pipeline = Pipeline(service, Settings(data_dir=tmp_path))
    sid = automatic_session(storage, "Adaptive batching")["id"]
    for n in range(50):
        storage.ingest(
            sid,
            TranscriptEvent(
                **payload(
                    segment_id=f"s{n}",
                    event_id=f"e{n}",
                    text="Synthetic context " * 20,
                    start_ms=n * 1000,
                    end_ms=n * 1000 + 900,
                    is_final=True,
                )
            ),
        )
    contexts = []

    async def analyze(context):
        contexts.append(context)
        if len(contexts) == 1:
            raise ProviderError("Synthetic timeout", "provider_timeout_read")
        return Suggestion(question="", rationale="", source_ids=[]), {}

    pipeline.provider.analyze = analyze
    pipeline.wakes[sid] = asyncio.Event()
    try:
        assert not await pipeline.process_batch(sid)
        assert pipeline.discovery.memory(sid)["coverage"] == {}
        assert pipeline.states[sid]["calls"] == 1
        assert len(contexts) == 1
        assert await pipeline.process_batch(sid)
        assert len(contexts[1]["new_source_ids"]) < len(contexts[0]["new_source_ids"])
        assert contexts[1]["new_source_ids"][0] == contexts[0]["new_source_ids"][0]
        assert len(storage.snapshot(sid)["segments"]) == 50
        assert len(contexts) == pipeline.states[sid]["calls"] == 2
        assert len(pipeline.diagnostics.list(sid)) == 2
    finally:
        await pipeline.close()


async def test_cancelled_request_keeps_evidence_and_records_cancellation(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    pipeline = Pipeline(service, Settings(data_dir=tmp_path))
    sid = automatic_session(storage, "Cancellation")["id"]
    storage.ingest(sid, TranscriptEvent(**payload(is_final=True)))
    entered = asyncio.Event()

    async def analyze(context):
        entered.set()
        await asyncio.Event().wait()

    pipeline.provider.analyze = analyze
    task = asyncio.create_task(pipeline.process_batch(sid))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pipeline.diagnostics.list(sid)[0]["outcome"] == "cancelled"
    assert len(storage.snapshot(sid)["segments"]) == 1
    assert pipeline.discovery.memory(sid)["coverage"] == {}
    await pipeline.close()


def test_reduced_batches_still_coalesce_short_audio_fragments():
    snapshot = {
        "version": 60,
        "segments": [
            payload(
                segment_id=f"audio-{n}",
                text="testing",
                start_ms=n * 1000,
                end_ms=n * 1000 + 900,
                is_final=True,
            )
            for n in range(60)
        ],
    }
    context = ContextBuilder().build(snapshot, {"version": 0, "brief": {}}, empty_memory(), "", 3)
    assert len(context["new_source_ids"]) == 35
    assert sum(len(s["text"].split()) for s in context["segments"]) >= 35


@pytest.mark.parametrize(
    "status,body,code",
    [
        (504, {"error": {"message": "PRIVATE remote error"}}, "provider_deadline"),
        (
            200,
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "PRIVATE malformed output"},
                            ]
                        },
                    }
                ],
                "usageMetadata": {"promptTokenCount": 12},
            },
            "provider_invalid_json",
        ),
    ],
)
async def test_failed_response_body_and_usage_available_only_in_opt_in_trace(
    tmp_path,
    monkeypatch,
    status,
    body,
    code,
):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    diagnostics = Diagnostics(storage, Settings(data_dir=tmp_path))
    sid = storage.create("Response failure")["id"]
    diagnostics.recording(True)
    trace = make_trace(diagnostics, sid)
    token = ACTIVE_TRACE.set(trace)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
            **kwargs,
        ),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await GeminiAnalyzer("synthetic-key", "test-model").analyze({"segments": []})
        assert error.value.code == code
        assert "PRIVATE" not in str(error.value)
    finally:
        ACTIVE_TRACE.reset(token)
    diagnostics.save(trace, "error", code, trace.metadata.get("usage"))
    detail = diagnostics.detail(trace.id)
    assert json.loads(detail["response_body"]) == body
    assert detail["metadata"]["http_status"] == status
    if status == 200:
        assert detail["metadata"]["usage"]["promptTokenCount"] == 12
