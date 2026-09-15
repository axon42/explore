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
from tests.prepared import session


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
    sid = session(service.storage, "Synthetic")["id"]
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
    one = session(service.storage, "One")["id"]
    two = session(service.storage, "Two")["id"]
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
    sid = session(service.storage, "Synthetic")["id"]
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
    sid = session(service.storage, "Synthetic")["id"]
    await capture.start(sid)
    await asyncio.wait_for(capture.task, 3)
    assert capture.state["status"] == "stopped"
    assert sources[0].closed and all(s.closed for s in streams)


async def test_manual_capture_has_no_deadline_and_still_flushes_on_stop(setup, monkeypatch):
    from types import SimpleNamespace

    import app.audio.capture as capture_module

    capture, service, sources, streams = setup
    assert capture.settings.audio_capture_max_seconds == 0
    clock = [100.0]
    monkeypatch.setattr(capture_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original_wait = asyncio.wait
    deadlines = []

    async def observe_wait(*args, **kwargs):
        deadlines.append(kwargs.get("timeout"))
        return await original_wait(*args, **kwargs)

    monkeypatch.setattr(capture_module.asyncio, "wait", observe_wait)
    sid = session(service.storage, "Manual capture")["id"]
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")
    clock[0] += 125
    await sources[0].frames.put(AudioFrame("microphone", 0, bytes(3200), 1600))
    await streams[0].messages.put(result("Still speaking", start=124))
    await wait_until(lambda: capture.state["frames"] == 1 and capture.state["segments"] == 1)
    assert capture.state["elapsed_seconds"] == 125
    assert deadlines[0] is None and not capture.task.done()
    await capture.finish_session(sid)
    assert capture.state["status"] == "stopped"
    assert sources[0].closed and all(s.closed for s in streams)
    assert len(service.storage.snapshot(sid)["segments"]) == 3


def test_optional_cutoff_and_long_capture_timestamps():
    from pydantic import ValidationError

    assert Settings(_env_file=None, audio_capture_max_seconds=0).audio_capture_max_seconds == 0
    assert Settings(_env_file=None, audio_capture_max_seconds=120).audio_capture_max_seconds == 120
    for invalid in (-1, 1, 29, 601):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, audio_capture_max_seconds=invalid)
    normalizer = DeepgramNormalizer("long-capture", "microphone", 5000)
    assert normalizer.event(result(start=7200)).start_ms == 7205000
    with pytest.raises(AudioError, match="transcription_invalid"):
        normalizer.event(result(start=9007199254740991))


def test_routes_require_local_origin_consent_and_hide_key(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, deepgram_api_key="not-public"))
    with TestClient(app) as client:
        state = client.get("/audio-capture")
        assert "not-public" not in state.text
        from tests.test_api import create

        sid = create(client)
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
    sid = session(service.storage, "Synthetic")["id"]
    await capture.start(sid)
    await started.wait()
    await asyncio.wait_for(capture.stop(sid), 1)
    assert source.closed and capture.state["status"] == "stopped"
    assert all(s.closed and not s.sent for s in streams)


async def test_native_menu_stop_flushes_final_speech(setup):
    capture, service, sources, _ = setup
    sid = session(service.storage, "Synthetic")["id"]
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


def test_capture_health_detects_padding_but_allows_silence():
    from app.audio.health import check_health

    mic = {"last_frame_seconds": 29, "last_input_seconds": 3, "input_observable": True}
    with pytest.raises(AudioError, match="audio_input_stalled"):
        check_health({"microphone": mic}, 30, 30)
    mic["last_input_seconds"] = 29
    # Zero amplitude still has real samples. An ordinary pause must not stop capture.
    check_health({"microphone": mic}, 30, 30)
    mic["last_frame_seconds"] = 3
    with pytest.raises(AudioError, match="audio_transport_stalled"):
        check_health({"microphone": mic}, 30, 30)
    check_health({"microphone": mic}, 30, 2)  # Permission/connection grace period.


async def test_capture_counters_survive_stop_without_transcript_bodies(setup):
    capture, service, sources, streams = setup
    sid = session(service.storage, "Diagnostics")["id"]
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")
    await sources[0].frames.put(AudioFrame("microphone", 0, bytes(3200), 1600))
    await streams[0].messages.put(result("Synthetic diagnostics speech"))
    await wait_until(lambda: capture.state["segments"] == 1 and capture.state["frames"] == 1)
    await capture.stop()
    saved = capture.audit.last_capture()
    assert saved["status"] == "stopped"
    assert saved["diagnostics"]["microphone"]["input_samples"] == 1600
    assert saved["diagnostics"]["microphone"]["results"] >= 1
    assert "Synthetic diagnostics speech" not in json.dumps(saved)
    assert len(service.storage.snapshot(sid)["segments"]) >= 1


async def test_microphone_choice_is_confirmed_and_not_reused_on_resume(setup):
    from app.reports import Reports
    from app.speakers import Speakers

    capture, service, _, streams = setup
    current = session(service.storage, "Confirmed microphone")
    sid, mid = current["id"], current["meeting_id"]
    roster = Reports(service.storage).participants(mid)
    pid = roster["participants"][0]["participant_id"]
    with pytest.raises(DomainError, match="changed"):
        await capture.start(sid, pid, roster["revision"] - 1)
    with service.storage.connection() as db:
        assert not db.execute(
            "SELECT * FROM session_producers WHERE session_id=?", (sid,)
        ).fetchone()
    await capture.start(sid, pid, roster["revision"])
    await wait_until(lambda: capture.state["status"] == "capturing")
    await streams[0].messages.put(result())
    await wait_until(lambda: capture.state["segments"] == 1)
    projected = service.storage.snapshot(sid)["segments"][0]
    assert projected["attributions"][0]["participant_id"] == pid
    first_capture = capture.state["id"]
    await capture.stop()
    await capture.start(sid)
    await wait_until(lambda: capture.state["status"] == "capturing")
    assert capture.state["id"] != first_capture
    await streams[2].messages.put(result())
    await wait_until(lambda: capture.state["segments"] == 1)
    latest = service.storage.snapshot(sid)["segments"][-1]
    assert latest["attributions"][0]["status"] == "unassigned"
    assert len(Speakers(service.storage).view(mid, sid)["history"]) == 1


@pytest.mark.parametrize("diarize", [True, False])
async def test_provider_diarization_parameter_is_pinned_and_optional(diarize):
    from urllib.parse import parse_qs, urlparse

    async def connector(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        assert query.get("diarize_model") == (["v1"] if diarize else None)
        assert "diarize" not in query
        assert query["channels"] == ["1"]
        assert "synthetic" not in url
        return object()

    await DeepgramStream("synthetic", connector, diarize=diarize).start()
