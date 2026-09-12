import asyncio
import time

import pytest

from app.broadcast import Broadcaster
from app.config import Settings
from app.models import DomainError
from app.service import Service
from app.storage import Storage
from app.zoom_capture import ZoomCapture
from app.zoom_rtms import TranscriptNormalizer
from app.zoom_webhook import Envelope


@pytest.fixture
async def capture(tmp_path):
    storage = Storage(tmp_path / "meetings.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    capture = ZoomCapture(service, Settings(data_dir=tmp_path, zoom_webhook_secret_token="fake"))
    yield capture
    await capture.close()


async def test_binding_one_run_and_stopped_rejected(capture):
    sid = capture.service.storage.create("Synthetic")["id"]
    key = await capture.bind(sid)
    assert await capture.bind(sid) == key
    other = capture.service.storage.create("Other")["id"]
    with pytest.raises(DomainError):
        await capture.bind(other)
    await capture.service.stop(sid)
    with pytest.raises(DomainError):
        await capture.bind(sid)


async def test_only_bound_events_connect_and_duplicate_packets_commit_once(capture):
    sid = capture.service.storage.create("Synthetic")["id"]
    key = await capture.bind(sid)
    payload = {
        "session_id": "zoom-session",
        "session_key": key,
        "rtms_stream_id": "stream",
        "server_urls": "wss://rtms-us.zoom.us/test",
    }
    called = asyncio.Event()
    calls = []

    async def run(payload, deliver, ready):
        calls.append(payload)
        await ready()
        event = TranscriptNormalizer("stream").event(
            {"timestamp": 100, "user_id": 1, "data": "Synthetic speech"}
        )
        await deliver(event)
        await deliver(event)
        called.set()
        await asyncio.Future()

    capture.client.run = run
    capture.inbox.put(
        Envelope(
            event="session.rtms_started",
            event_ts=int(time.time() * 1000),
            payload={**payload, "session_key": "other"},
        )
    )
    await capture.arm()
    await asyncio.sleep(0.02)
    assert calls == []
    capture.inbox.put(
        Envelope(event="session.rtms_started", event_ts=int(time.time() * 1000), payload=payload)
    )
    await asyncio.wait_for(called.wait(), 2)
    assert len(capture.service.storage.snapshot(sid)["segments"]) == 1
    await capture.close()
    assert len(calls) == 1 and capture.view()["status"] == "stopped"
    with pytest.raises(DomainError):
        await capture.arm()


async def test_stop_before_start_does_not_connect(capture):
    sid = capture.service.storage.create("Synthetic")["id"]
    key = await capture.bind(sid)
    payload = {
        "session_id": "zoom-session",
        "session_key": key,
        "rtms_stream_id": "stream",
        "server_urls": "wss://rtms-us.zoom.us/test",
    }
    for event in ("session.rtms_stopped", "session.rtms_started"):
        capture.inbox.put(Envelope(event=event, event_ts=int(time.time() * 1000), payload=payload))

    async def forbidden(*args):
        raise AssertionError("No stream should connect")

    capture.client.run = forbidden
    await capture.arm()
    await asyncio.wait_for(capture.task, 2)
    assert capture.view()["status"] == "stopped"


async def test_release_cancels_worker_and_allows_fresh_binding(capture):
    sid = capture.service.storage.create("First")["id"]
    old_key = await capture.bind(sid)
    await capture.arm()
    await capture.release()
    assert capture.binding is None and capture.task is None
    sid2 = capture.service.storage.create("Next")["id"]
    assert await capture.bind(sid2) != old_key
    assert capture.service.storage.snapshot(sid)["session"]["status"] == "live"
