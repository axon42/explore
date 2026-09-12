import asyncio
import base64
import json
from collections import deque

import pytest
from fastapi.testclient import TestClient

from app.audio.capture import AudioCapture
from app.audio.deepgram import DeepgramNormalizer, DeepgramStream
from app.audio.source import AudioError, AudioFrame, MacOSSource
from app.broadcast import Broadcaster
from app.config import Settings
from app.main import create_app
from app.models import DomainError
from app.service import Service
from app.storage import Storage


def result(text="Synthetic speech", final=True, start=0):
    return {
        "type": "Results",
        "start": start,
        "duration": 1.2,
        "is_final": final,
        "channel": {"alternatives": [{"transcript": text}]},
    }


def test_deepgram_revisions_duplicates_finality_and_source_isolation():
    normalizer = DeepgramNormalizer("capture", "microphone", 5000)
    draft = normalizer.event(result("Synthetic", False))
    assert draft.start_ms == 5000 and not draft.is_final
    assert normalizer.event(result("Synthetic", False)) is None
    final = normalizer.event(result())
    assert final.segment_id == draft.segment_id and final.revision == 1
    assert normalizer.event(result("Late draft", False)) is None
    other = DeepgramNormalizer("capture", "system", 5000).event(result())
    assert other.segment_id != final.segment_id and other.speaker_name == "System audio"
    fresh = DeepgramNormalizer("new", "microphone", 0).event(result())
    assert fresh.segment_id != final.segment_id


@pytest.mark.parametrize(
    "change",
    [
        {"start": -1},
        {"start": float("nan")},
        {"duration": "1"},
        {"is_final": "true"},
        {"channel": {"alternatives": []}},
    ],
)
def test_invalid_provider_data(change):
    with pytest.raises(AudioError):
        DeepgramNormalizer("c", "system", 0).event({**result(), **change})


async def test_pcm_protocol_rejects_duplicates_and_wrong_size(tmp_path):
    source = MacOSSource(tmp_path / "not-used")
    frames = deque(
        [
            {
                "type": "audio",
                "channel": "microphone",
                "sequence": 0,
                "pcm": base64.b64encode(bytes(3200)).decode(),
            },
        ]
    )

    async def message():
        return frames[0]

    source.message = message
    assert len((await source.read()).pcm) == 3200
    with pytest.raises(AudioError):
        await source.read()
    frames[0]["sequence"] = 1
    frames[0]["pcm"] = "eA=="
    with pytest.raises(AudioError):
        await source.read()


class FakeSource:
    def __init__(self):
        self.frames = asyncio.Queue()
        self.closed = False

    async def start(self):
        pass

    async def read(self):
        return await self.frames.get()

    async def close(self):
        self.closed = True


class FakeStream:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.closed = False
        self.sent = []

    async def start(self):
        pass

    async def send(self, data):
        self.sent.append(data)

    async def receive(self):
        return await self.messages.get()

    async def finish(self):
        await self.messages.put(result("Final speech on stop", start=2))
        await self.messages.put(None)

    async def close(self):
        self.closed = True


@pytest.fixture
async def setup(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    service = Service(storage, Broadcaster(128))
    sources, streams = [], []

    def source_factory():
        source = FakeSource()
        sources.append(source)
        return source

    def provider_factory():
        stream = FakeStream()
        streams.append(stream)
        return stream

    capture = AudioCapture(
        service,
        Settings(_env_file=None, data_dir=tmp_path, deepgram_api_key="synthetic"),
        source_factory,
        provider_factory,
    )
    yield capture, service, sources, streams
    await capture.stop()


async def wait_until(check):
    async with asyncio.timeout(2):
        while not check():  # noqa: ASYNC110 - observes production state without test hooks
            await asyncio.sleep(0.01)


async def test_capture_stops_and_flushes_before_session_finalization(setup):
    capture, service, sources, streams = setup
    sid = service.storage.create("Synthetic")["id"]
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")
    await sources[0].frames.put(AudioFrame("microphone", 0, bytes(3200)))
    await streams[0].messages.put(result())
    await wait_until(lambda: capture.state["segments"] == 1)
    await capture.finish_session(sid)
    snapshot = service.storage.snapshot(sid)
    assert snapshot["session"]["status"] == "stopped"
    assert len(snapshot["segments"]) == 3
    assert sources[0].closed and all(s.closed for s in streams)
    assert capture.state["status"] == "stopped"
    with pytest.raises(DomainError):
        await capture.start(sid)


async def test_concurrent_start_wrong_session_stop_and_stale_capture(setup):
    capture, service, _, _ = setup
    one = service.storage.create("One")["id"]
    two = service.storage.create("Two")["id"]
    outcomes = await asyncio.gather(capture.start(one), capture.start(two), return_exceptions=True)
    assert sum(isinstance(item, DomainError) for item in outcomes) == 1
    sid, identity = capture.state["sid"], capture.state["id"]
    await wait_until(lambda: capture.state["status"] == "capturing")
    await capture.stop(two if sid == one else one)
    assert not capture.task.done()
    await capture.stop(sid, identity)
    await capture.start(two if sid == one else one)
    with pytest.raises(DomainError):
        await capture.stop(capture.state["sid"], identity)


async def test_provider_failure_is_safe_and_releases_source(setup):
    capture, service, sources, streams = setup
    sid = service.storage.create("Synthetic")["id"]
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")
    await streams[0].messages.put({"type": "Error", "description": "SECRET BODY"})
    await wait_until(lambda: capture.task.done())
    assert sources[0].closed and all(s.closed for s in streams)
    assert capture.state["status"] == "failed"
    assert "SECRET" not in json.dumps(capture.view())


async def test_time_limit_stops_without_another_user_action(setup):
    capture, service, sources, streams = setup
    # Shorten only this synthetic in-memory test; real settings validate >=30 seconds.
    capture.settings.audio_capture_max_seconds = 1
    sid = service.storage.create("Synthetic")["id"]
    await capture.start(sid)
    await asyncio.wait_for(capture.task, 3)
    assert capture.state["status"] == "stopped"
    assert sources[0].closed and all(s.closed for s in streams)


def test_routes_require_local_origin_consent_and_hide_key(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, deepgram_api_key="not-public"))
    with TestClient(app) as client:
        state = client.get("/audio-capture")
        assert "not-public" not in state.text
        sid = client.post("/sessions", json={}).json()["id"]
        path = f"/sessions/{sid}/audio-capture"
        assert client.post(path, json={"consent": True}).status_code == 403
        assert (
            client.post(
                path, json={"consent": False}, headers={"Origin": "http://127.0.0.1:5173"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                path, json={"consent": "true"}, headers={"Origin": "http://127.0.0.1:5173"}
            ).status_code
            == 422
        )


async def test_provider_uses_fixed_endpoint_secret_header_and_bounded_socket():
    called = {}

    async def connector(url, **kwargs):
        called.update(url=url, **kwargs)
        return object()

    provider = DeepgramStream("synthetic-key", connector)
    await provider.start()
    assert called["url"].startswith("wss://api.deepgram.com/v1/listen?")
    assert "synthetic-key" not in called["url"]
    assert called["additional_headers"] == {"Authorization": "Token synthetic-key"}
    assert called["max_size"] == 65536 and called["open_timeout"] == 10


async def test_stop_during_startup_closes_helper_without_provider_calls(setup):
    capture, service, sources, streams = setup
    started = asyncio.Event()
    source = FakeSource()

    async def start():
        started.set()
        await asyncio.Future()

    source.start = start
    capture.source_factory = lambda: source
    sid = service.storage.create("Synthetic")["id"]
    await capture.start(sid)
    await started.wait()
    await asyncio.wait_for(capture.stop(sid), 1)
    assert source.closed and capture.state["status"] == "stopped"
    assert all(s.closed and not s.sent for s in streams)


async def test_native_menu_stop_flushes_final_speech(setup):
    capture, service, sources, _ = setup
    sid = service.storage.create("Synthetic")["id"]
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")

    async def stopped():
        raise AudioError("capture_stopped")

    # Release the already-pending first read, then simulate the helper's menu stop.
    sources[0].read = stopped
    await sources[0].frames.put(AudioFrame("system", 0, bytes(3200)))
    await asyncio.wait_for(capture.task, 2)
    assert capture.state["status"] == "stopped"
    assert len(service.storage.snapshot(sid)["segments"]) == 2


async def test_app_launch_private_socket_and_close(tmp_path):
    import os
    import stat
    import sys

    class TestSource(MacOSSource):
        def launch_arguments(self, socket_path):
            self.socket_path = socket_path
            return [
                sys.executable,
                "-c",
                (
                    "import socket,sys,json; s=socket.socket(socket.AF_UNIX); "
                    "s.connect(sys.argv[1]); "
                    's.sendall(b\'{"type":"ready","version":1,"sample_rate":16000}\\n\'); '
                    "s.recv(1); s.close()"
                ),
                str(socket_path),
            ]

    source = TestSource(tmp_path / "Capture.app/Contents/MacOS/ExploreCapture")
    try:
        await source.start()
        assert stat.S_IMODE(os.stat(source.socket_path.parent).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(source.socket_path).st_mode) == 0o600
        assert source.process.returncode is None
    finally:
        await source.close()
    assert source.process.returncode == 0
    assert not source.socket_path.exists()


def test_macos_launch_uses_app_identity_not_backend_subprocess(tmp_path):
    executable = tmp_path / "Capture.app/Contents/MacOS/ExploreCapture"
    args = MacOSSource(executable).launch_arguments(tmp_path / "capture.sock")
    assert args[:4] == ["/usr/bin/open", "-n", "-W", str(tmp_path / "Capture.app")]
    assert "--socket" in args
