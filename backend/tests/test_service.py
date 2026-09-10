import asyncio

from app.broadcast import Broadcaster
from app.models import TranscriptEvent
from app.service import Service
from app.storage import Storage
from tests.test_api import payload


async def test_overflow_drops_only_slow_subscriber(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    await asyncio.to_thread(storage.initialize)
    broker = Broadcaster(queue_size=1)
    service = Service(storage, broker)
    session = await service.read(storage.create, "Overflow")
    slow = await service.subscribe(session["id"])
    fast = await service.subscribe(session["id"])
    await fast.queue.get()
    ack = await service.ingest(session["id"], TranscriptEvent(**payload()))
    assert ack["outcome"] == "accepted"
    assert slow.overflow.is_set()
    assert not fast.overflow.is_set()
    assert (await fast.queue.get())["version"] == 1
    reconnect = await service.subscribe(session["id"])
    assert (await reconnect.queue.get())["version"] == 1


async def test_snapshot_and_subscription_have_no_gap(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    await asyncio.to_thread(storage.initialize)
    service = Service(storage, Broadcaster(128))
    session = await service.read(storage.create, "Race")
    session_id = session["id"]

    async def ingest():
        for revision in range(1, 31):
            await service.ingest(
                session_id,
                TranscriptEvent(**payload(revision=revision, event_id=f"evt-{revision}")),
            )

    producer = asyncio.create_task(ingest())
    subscriber = await service.subscribe(session_id)
    snapshot = await subscriber.queue.get()
    versions = [snapshot["version"]]
    await producer
    while not subscriber.queue.empty():
        versions.append((await subscriber.queue.get())["version"])
    assert versions == list(range(versions[0], 31))


def test_crash_recovery_marks_live_session_stopped(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    session = storage.create("Interrupted")
    assert storage.initialize() == 1
    snapshot = storage.snapshot(session["id"])
    assert snapshot["session"]["status"] == "stopped"
    assert snapshot["version"] == 1
