"""One bounded capture. Lifecycle belongs here; sources/providers own no persistence."""

import asyncio
import logging
import platform
import struct
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import ROOT
from ..models import DomainError
from .deepgram import DeepgramNormalizer, DeepgramStream
from .source import AudioError, MacOSSource

HELPER = ROOT / "native/macos/build/Explore Capture.app/Contents/MacOS/ExploreCapture"
ERRORS = {
    "microphone_permission": "Allow Microphone access for Explore Capture in macOS Settings.",
    "screen_permission": "Allow Screen Recording access for Explore Capture, then retry.",
    "audio_device": "No microphone is available. Connect one and retry.",
    "audio_format": "The audio device format could not be converted. Stop and retry.",
    "audio_overflow": "Audio processing fell behind. Capture stopped to avoid dropping audio.",
    "system_capture": "System audio capture failed. Check macOS permissions and your audio device.",
    "helper_stopped": "The macOS helper stopped. Accepted transcripts are saved.",
    "helper_protocol": "The capture helper stopped responding or sent an invalid audio frame.",
    "transcription_failed": "Deepgram failed. Check the API key, credits and network.",
    "transcription_invalid": "Deepgram returned an invalid transcript. Capture stopped.",
    "session_stopped": "This meeting ended. Capture stopped.",
}


class AudioCapture:
    def __init__(self, service, settings, source_factory=None, provider_factory=None):
        self.service, self.settings = service, settings
        self.source_factory = source_factory or (lambda: MacOSSource(HELPER))
        self.provider_factory = provider_factory or (
            lambda: DeepgramStream(settings.deepgram_api_key.get_secret_value())
        )
        self.custom_source = source_factory is not None
        self.lock = asyncio.Lock()
        self.task = None
        self.stop_event = asyncio.Event()
        self.state = None

    def view(self):
        return {
            "supported": self.custom_source or platform.system() == "Darwin",
            "helper_ready": self.custom_source or Path(HELPER).is_file(),
            "configured": bool(self.settings.deepgram_api_key.get_secret_value()),
            "max_seconds": self.settings.audio_capture_max_seconds,
            "capture": dict(self.state) if self.state else None,
        }

    async def start(self, sid):
        async with self.lock:
            if self.task and not self.task.done():
                raise DomainError(
                    "capture_busy", "Stop the active capture before starting another."
                )
            readiness = self.view()
            if not readiness["supported"] or not readiness["helper_ready"]:
                raise DomainError("capture_helper_missing", "Build the macOS capture helper first.")
            if not readiness["configured"]:
                raise DomainError(
                    "capture_key_missing", "Add DEEPGRAM_API_KEY to .env and restart."
                )
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            if snapshot["session"]["status"] != "live":
                raise DomainError("session_stopped", "Choose a live meeting.")
            offset = max((s["end_ms"] for s in snapshot["segments"]), default=0)
            self.state = {
                "id": str(uuid4()),
                "sid": sid,
                "status": "starting",
                "error": "",
                "code": "",
                "elapsed_seconds": 0,
                "frames": 0,
                "segments": 0,
                "microphone_level": 0.0,
                "system_level": 0.0,
            }
            self.stop_event = asyncio.Event()
            self.task = asyncio.create_task(self.run(self.state, offset))
            return self.view()

    async def stop_locked(self, sid=None, capture_id=None):
        if self.state and sid and self.state["sid"] != sid:
            return
        if capture_id and (not self.state or self.state["id"] != capture_id):
            raise DomainError("capture_stale", "That capture has already ended. Refresh.")
        if self.task and not self.task.done():
            self.stop_event.set()
            if self.state["status"] == "starting":
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
                self.state["status"] = "stopped"
                return
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 8)
            except TimeoutError:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)

    async def stop(self, sid=None, capture_id=None):
        async with self.lock:
            await self.stop_locked(sid, capture_id)
        return self.view()

    async def finish_session(self, sid):
        # Starting a new capture cannot interleave between stopping capture and session stop.
        async with self.lock:
            await self.stop_locked(sid)
            return await self.service.stop(sid)

    async def run(self, state, offset):
        source = self.source_factory()
        streams = {name: self.provider_factory() for name in ("microphone", "system")}
        tasks = []
        receivers = []
        finalized = set()
        started = time.monotonic()
        try:
            async with asyncio.timeout(min(35, self.settings.audio_capture_max_seconds)):
                await source.start()
            if self.stop_event.is_set():
                return
            async with asyncio.TaskGroup() as group:
                for stream in streams.values():
                    group.create_task(stream.start())
            state["status"] = "capturing"

            async def receive(channel, stream):
                normalizer = DeepgramNormalizer(state["id"], channel, offset)
                while True:
                    message = await stream.receive()
                    if message is None:
                        return
                    event = normalizer.event(message)
                    if event:
                        await self.service.ingest(state["sid"], event)
                        if event.is_final:
                            finalized.add(event.segment_id)
                            state["segments"] = len(finalized)

            async def pump():
                while True:
                    frame = await source.read()
                    await asyncio.wait_for(streams[frame.channel].send(frame.pcm), 3)
                    samples = struct.unpack("<1600h", frame.pcm)
                    state[frame.channel + "_level"] = round(
                        min(1, (sum(s * s for s in samples) / len(samples)) ** 0.5 / 32768), 4
                    )
                    state["frames"] += 1
                    state["elapsed_seconds"] = int(time.monotonic() - started)
                    if state["frames"] % 20 == 0:
                        snapshot = await self.service.read(
                            self.service.storage.snapshot, state["sid"]
                        )
                        if snapshot["session"]["status"] != "live":
                            raise AudioError("session_stopped")

            receivers = [asyncio.create_task(receive(c, s)) for c, s in streams.items()]
            producer = asyncio.create_task(pump())
            stopper = asyncio.create_task(self.stop_event.wait())
            tasks = [*receivers, producer, stopper]
            done, _ = await asyncio.wait(
                tasks,
                timeout=max(
                    1, self.settings.audio_capture_max_seconds - (time.monotonic() - started)
                ),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                if task is not stopper:
                    try:
                        await task
                        raise AudioError("transcription_failed")
                    except AudioError as exc:
                        if str(exc) != "capture_stopped":
                            raise
            state["status"] = "stopping"
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            await source.close()
            # Flush provider finals before stopping the Explore session/report pipeline.
            for stream in streams.values():
                await asyncio.wait_for(stream.finish(), 2)
            done, pending = await asyncio.wait(receivers, timeout=3)
            for task in done:
                await task
            if pending:
                state["error"] = "Capture stopped; some speech may not have finalized."
                state["code"] = "transcription_drain_timeout"
        except asyncio.CancelledError:
            state["code"] = "capture_cancelled"
            state["error"] = "Capture stopped; pending speech may not have finalized."
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, AudioError) else "transcription_failed"
            if isinstance(exc, DomainError) and exc.code == "session_stopped":
                code = "session_stopped"
            state.update(
                status="failed", code=code, error=ERRORS.get(code, ERRORS["transcription_failed"])
            )
            logging.getLogger("meeting").warning("audio_capture_failed code=%s", code)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await source.close()
            await asyncio.gather(*(s.close() for s in streams.values()), return_exceptions=True)
            if state["status"] != "failed":
                state["status"] = "stopped"
            state["microphone_level"] = state["system_level"] = 0


class StartCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    consent: bool


class StopCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capture_id: str = Field(min_length=1, max_length=100)


def router(capture, settings):
    routes = APIRouter()

    def origin(request):
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required.", 403)

    @routes.get("/audio-capture")
    async def status():
        return capture.view()

    @routes.post("/sessions/{sid}/audio-capture")
    async def start(sid: str, body: StartCapture, request: Request):
        origin(request)
        if not body.consent:
            raise DomainError("capture_consent", "Confirm consent before starting capture.", 400)
        return await capture.start(sid)

    @routes.post("/sessions/{sid}/audio-capture/stop")
    async def stop(sid: str, body: StopCapture, request: Request):
        origin(request)
        if capture.state and capture.state["sid"] != sid:
            raise DomainError("capture_stale", "This capture belongs to another meeting.")
        return await capture.stop(sid, body.capture_id)

    return routes
