from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app

ORIGIN = {"origin": "http://127.0.0.1:5173"}


def payload(**changes):
    return {
        "event_id": "evt-1",
        "segment_id": "seg-1",
        "revision": 1,
        "speaker_id": "speaker-1",
        "speaker_name": "Alex",
        "start_ms": 100,
        "end_ms": 900,
        "text": "Let's review",
        "is_final": False,
        **changes,
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        yield client


def create(client):
    from tests.prepared import start

    draft = client.post("/workspaces/default/meetings", json={"title": "Planning"}).json()
    return start(client, draft["meeting"]["id"])["session"]["id"]


def send(client, session_id, **changes):
    with client.websocket_connect(f"/sessions/{session_id}/ingest") as ws:
        ws.send_json(payload(**changes))
        return ws.receive_json()


def test_persistence_and_recovery(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        session_id = create(client)
        assert send(client, session_id)["outcome"] == "accepted"
        snapshot = client.get(f"/sessions/{session_id}").json()
        assert snapshot["segments"] == [payload()]
        assert snapshot["version"] == 1
        assert len(client.get("/sessions").json()) == 1
    with TestClient(create_app(settings)) as restarted:
        snapshot = restarted.get(f"/sessions/{session_id}").json()
        assert snapshot["segments"] == [payload()]
        assert snapshot["session"]["status"] == "stopped"
        assert snapshot["version"] == 2


def test_duplicates_and_revision_rules(client):
    session_id = create(client)
    assert send(client, session_id)["outcome"] == "accepted"
    assert send(client, session_id)["reason"] == "duplicate"
    assert (
        send(client, session_id, event_id="evt-2", revision=2, is_final=True, text="Final text")[
            "version"
        ]
        == 2
    )
    assert send(client, session_id, event_id="evt-3", revision=1)["reason"] == "stale_revision"
    assert send(client, session_id, event_id="evt-4", revision=3)["reason"] == "finalized_segment"
    assert (
        send(
            client, session_id, event_id="evt-5", revision=4, is_final=True, text="Corrected final"
        )["outcome"]
        == "accepted"
    )
    snapshot = client.get(f"/sessions/{session_id}").json()
    assert snapshot["version"] == 3
    assert len(snapshot["segments"]) == 1
    assert snapshot["segments"][0]["text"] == "Corrected final"
    other = create(client)
    assert send(client, other)["outcome"] == "accepted"


@pytest.mark.parametrize(
    "changes",
    [
        {"start_ms": -1},
        {"end_ms": 99},
        {"revision": -1},
        {"revision": 10**40},
        {"revision": "2"},
        {"is_final": "true"},
        {"text": ""},
        {"unexpected": True},
        {"speaker_id": ""},
    ],
)
def test_invalid_payload_does_not_break_socket(client, changes):
    session_id = create(client)
    with client.websocket_connect(f"/sessions/{session_id}/ingest") as ws:
        ws.send_json(payload(**changes))
        error = ws.receive_json()
        assert error["code"] == "invalid_event"
        assert "input" not in str(error)
        ws.send_text("{not json")
        assert ws.receive_json()["code"] == "invalid_event"
        ws.send_json(payload())
        assert ws.receive_json()["outcome"] == "accepted"
    assert client.get(f"/sessions/{session_id}").json()["version"] == 1


def test_stop_rejects_ingestion_and_is_idempotent(client):
    session_id = create(client)
    with client.websocket_connect(f"/sessions/{session_id}/events", headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        response = client.post(f"/sessions/{session_id}/stop")
        assert response.json()["status"] == "stopped"
        assert ws.receive_json()["type"] == "status"
        assert client.post(f"/sessions/{session_id}/stop").json()["version"] == 1
    assert send(client, session_id)["code"] == "session_stopped"
    assert client.post(f"/sessions/{session_id}/demo").status_code == 409


def test_reconnection_snapshot_then_updates(client):
    session_id = create(client)
    with client.websocket_connect(f"/sessions/{session_id}/events", headers=ORIGIN) as ws:
        assert ws.receive_json()["version"] == 0
        send(client, session_id)
        assert ws.receive_json()["segment"] == payload()
    send(client, session_id, event_id="evt-2", revision=2, is_final=True)
    with client.websocket_connect(f"/sessions/{session_id}/events", headers=ORIGIN) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["version"] == 2
        assert snapshot["segments"][0]["is_final"] is True
        send(client, session_id, event_id="evt-3", segment_id="seg-2")
        assert ws.receive_json()["version"] == 3


def test_concurrent_duplicate_is_committed_once(client):
    session_id = create(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: send(client, session_id), range(8)))
    assert sum(result["outcome"] == "accepted" for result in results) == 1
    assert client.get(f"/sessions/{session_id}").json()["version"] == 1


def test_origin_token_and_missing_sessions(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, ingestion_token="test-secret", demo_enabled=False))
    ) as client:
        session_id = create(client)
        for headers in (
            {},
            {"authorization": "Bearer wrong"},
            {"authorization": "Bearer test-secret", "origin": "https://evil.test"},
        ):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/sessions/{session_id}/ingest", headers=headers):
                    pass
        with client.websocket_connect(
            f"/sessions/{session_id}/ingest", headers={"authorization": "Bearer test-secret"}
        ) as ws:
            ws.send_json(payload())
            assert ws.receive_json()["outcome"] == "accepted"
        for headers in ({}, {"origin": "https://evil.test"}):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/sessions/{session_id}/events", headers=headers):
                    pass
        assert (
            client.post("/sessions", json={}, headers={"origin": "https://evil.test"}).status_code
            == 403
        )
        assert client.get("/sessions/missing").status_code == 404
        assert client.post(f"/sessions/{session_id}/demo").status_code == 404
        with client.websocket_connect("/sessions/missing/events", headers=ORIGIN) as ws:
            assert ws.receive_json()["code"] == "not_found"


def test_default_title(client):
    draft = client.post("/workspaces/default/meetings", json={}).json()
    assert draft["meeting"]["title"] == "Untitled interview"
    assert draft["session"] is None
    assert client.post("/sessions", json={}).json()["code"] == "meeting_preparation_required"


def test_only_one_demo_task_and_stop_cleans_it(client, monkeypatch):
    import asyncio

    async def waiting_replay(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.main.replay", waiting_replay)
    session_id = create(client)
    assert client.post(f"/sessions/{session_id}/demo").status_code == 202
    assert client.post(f"/sessions/{session_id}/demo").json()["code"] == "demo_running"
    assert len(client.app.state.replays) == 1
    client.post(f"/sessions/{session_id}/stop")
    assert client.app.state.replays == {}


def test_binary_frame_and_storage_failure_are_retryable(client, monkeypatch):
    import sqlite3

    session_id = create(client)
    storage = client.app.state.service.storage
    original = storage.ingest
    with client.websocket_connect(f"/sessions/{session_id}/ingest") as ws:
        ws.send_bytes(b"not a text frame")
        assert ws.receive_json()["code"] == "invalid_frame"

        def fail(*args):
            raise sqlite3.OperationalError("Synthetic unavailable database")

        monkeypatch.setattr(storage, "ingest", fail)
        ws.send_json(payload())
        assert ws.receive_json()["code"] == "storage_error"
        monkeypatch.setattr(storage, "ingest", original)
        ws.send_json(payload())
        assert ws.receive_json()["outcome"] == "accepted"
