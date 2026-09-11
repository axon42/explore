import asyncio
import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.analysis import Suggestion
from app.config import Settings
from app.discovery import Discovery
from app.main import create_app
from app.models import TranscriptEvent
from app.storage import Storage
from tests.test_api import payload


def wait_for(client, mid, predicate):
    for _ in range(150):
        detail = client.get(f"/meetings/{mid}").json()
        if predicate(detail):
            return detail
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for discovery state")


def setup_meeting(client):
    workspace = client.post("/workspaces", json={"name": "Agencies"}).json()
    detail = client.post(
        f"/workspaces/{workspace['id']}/meetings", json={"title": "Discovery"}
    ).json()
    return workspace["id"], detail["meeting"]["id"], detail["session"]["id"]


def test_persist_evidence_notes_status_and_restart(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        wid, mid, sid = setup_meeting(client)
        assert (
            client.put(
                f"/meetings/{mid}/brief",
                json={
                    "revision": 0,
                    "brief": {"title": "Agency", "objective": "Find workflow gaps"},
                },
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/meetings/{mid}/brief", json={"revision": 0, "brief": {"title": "Stale"}}
            ).status_code
            == 409
        )
        note = client.post(
            f"/meetings/{mid}/notes", json={"body": "Customer uses a spreadsheet."}
        ).json()
        assert (
            client.put(
                f"/meetings/{mid}/notes/{note['id']}",
                json={"body": "Corrected note", "revision": 0},
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/meetings/{mid}/notes/{note['id']}", json={"body": "Overwrite", "revision": 0}
            ).status_code
            == 409
        )
        event = payload(
            is_final=True, speaker_id="customer", text="Last Friday I used a spreadsheet."
        )
        client.post(f"/sessions/{sid}/inject", json=event)
        detail = wait_for(client, mid, lambda d: len(d["questions"]) == 1)
        q = detail["questions"][0]
        assert len(detail["findings"]) == 3
        assert q["evidence"][0]["text"] == event["text"]
        assert (
            client.patch(
                f"/meetings/{mid}/questions/{q['id']}", json={"revision": 0, "status": "asked"}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/meetings/{mid}/questions/{q['id']}", json={"revision": 0, "status": "answered"}
            ).status_code
            == 409
        )
        corrected = {
            **event,
            "event_id": "correction",
            "revision": 2,
            "text": "Actually it only took five minutes.",
        }
        client.post(f"/sessions/{sid}/inject", json=corrected)
        detail = client.get(f"/meetings/{mid}").json()
        assert detail["questions"][0]["evidence"][0]["superseded"]
        assert detail["questions"][0]["evidence"][0]["text"] == event["text"]
    with TestClient(create_app(settings)) as client:
        detail = client.get(f"/meetings/{mid}").json()
        assert detail["questions"][0]["status"] == "asked"
        assert detail["notes"][0]["body"] == "Corrected note"
        assert detail["meeting"]["workspace_id"] == wid
        with client.app.state.service.storage.connection() as db:
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
            assert db.execute("SELECT COUNT(*) FROM note_revisions").fetchone()[0] == 2


def test_reset_replaces_run_and_clear_is_workspace_scoped(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        wid, mid, sid = setup_meeting(client)
        other_wid, other_mid, _ = setup_meeting(client)
        client.post(f"/meetings/{mid}/notes", json={"body": "Keep this context"})
        client.post(f"/sessions/{sid}/playback", json={"action": "play", "speed": 10})
        fresh = client.post(f"/meetings/{mid}/reset", json={"session_id": sid}).json()
        assert client.post(f"/meetings/{mid}/reset", json={"session_id": sid}).status_code == 409
        assert fresh["session"]["id"] != sid
        assert fresh["meeting"]["id"] == mid and fresh["notes"][0]["body"] == "Keep this context"
        assert client.post(f"/sessions/{sid}/inject", json=payload()).status_code == 404
        time.sleep(0.8)
        assert client.get(f"/sessions/{fresh['session']['id']}").json()["segments"] == []
        assert client.delete(f"/workspaces/{wid}/meetings").status_code == 200
        assert client.get(f"/meetings/{mid}").status_code == 404
        assert len(client.get(f"/workspaces/{other_wid}/meetings").json()) == 1
        assert client.get(f"/meetings/{other_mid}").status_code == 200


def test_cross_meeting_references_and_validation(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        _, mid, sid = setup_meeting(client)
        _, other, _ = setup_meeting(client)
        note = client.post(f"/meetings/{mid}/notes", json={"body": "Note"}).json()
        assert (
            client.put(
                f"/meetings/{other}/notes/{note['id']}",
                json={"body": "Wrong meeting", "revision": 0},
            ).status_code
            == 404
        )
        assert client.post("/workspaces", json={"name": "  "}).status_code == 422
        client.post(f"/sessions/{sid}/inject", json=payload(speaker_id="customer", is_final=True))
        q = wait_for(client, mid, lambda d: bool(d["questions"]))["questions"][0]
        assert (
            client.patch(
                f"/meetings/{other}/questions/{q['id']}", json={"status": "answered", "revision": 0}
            ).status_code
            == 404
        )


def test_migration_preserves_legacy_transcript_and_objective(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,status TEXT,created_at TEXT,
      stopped_at TEXT,version INTEGER);
      CREATE TABLE segments(session_id TEXT,segment_id TEXT,revision INTEGER,is_final INTEGER,
      payload TEXT,PRIMARY KEY(session_id,segment_id));
      CREATE TABLE experiments(session_id TEXT PRIMARY KEY,payload TEXT);
    """)
    db.execute("INSERT INTO sessions VALUES ('old','Legacy','stopped','2026-01-01',NULL,1)")
    event = payload()
    db.execute(
        "INSERT INTO segments VALUES (?, ?, ?, ?, ?)",
        ("old", event["segment_id"], 1, 0, json.dumps(event)),
    )
    db.execute(
        "INSERT INTO experiments VALUES (?, ?)",
        ("old", json.dumps({"objective": "Original objective"})),
    )
    db.commit()
    db.close()
    storage = Storage(path)
    storage.initialize()
    storage.initialize()
    assert path.with_suffix(".before-discovery.sqlite3").exists()
    assert storage.snapshot("old")["segments"] == [event]
    detail = Discovery(storage).detail("old")
    assert detail["brief"]["objective"] == "Original objective"
    assert detail["meeting"]["workspace_id"] == "default"


async def test_context_edit_discards_inflight_result(tmp_path):
    from app.broadcast import Broadcaster
    from app.pipeline import Pipeline
    from app.service import Service

    storage = Storage(tmp_path / "context.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    pipeline = Pipeline(service, Settings(data_dir=tmp_path))
    service.on_final = pipeline.notify
    session = storage.create("Context")
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(context):
        entered.set()
        await release.wait()
        return Suggestion(question="When?", rationale="test", source_ids=["seg-1"]), {}

    pipeline.provider.analyze = slow
    try:
        await service.ingest(session["id"], TranscriptEvent(**payload(is_final=True)))
        await asyncio.wait_for(entered.wait(), 2)
        await service.read(pipeline.discovery.note, session["meeting_id"], "New context")
        release.set()
        for _ in range(100):
            if pipeline.states[session["id"]]["runs"]:
                break
            await asyncio.sleep(0.01)
        assert pipeline.states[session["id"]]["runs"][0]["stale"]
        assert not pipeline.discovery.detail(session["meeting_id"])["questions"]
    finally:
        await pipeline.close()


async def test_cancelled_database_write_finishes_before_lock_release(tmp_path):
    from app.broadcast import Broadcaster
    from app.service import Service

    storage = Storage(tmp_path / "cancel.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    entered, release = threading.Event(), threading.Event()

    def slow_write():
        entered.set()
        release.wait(2)
        return storage.create("Committed")

    task = asyncio.create_task(service.read(slow_write))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0.02)
    assert service.lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(storage.list_sessions()) == 1
    assert not service.lock.locked()
