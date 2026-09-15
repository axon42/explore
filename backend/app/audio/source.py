"""Native source boundary: fixed-size PCM frames, no credentials or public listener."""

import asyncio
import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AudioError(Exception):
    """Contains only a predefined diagnostic code."""


@dataclass(frozen=True)
class AudioFrame:
    channel: str
    sequence: int
    pcm: bytes
    input_samples: int | None = None


class AudioSource(Protocol):
    async def start(self): ...
    async def read(self) -> AudioFrame: ...
    async def close(self): ...


HELPER_ERRORS = {
    "microphone_permission",
    "screen_permission",
    "audio_device",
    "audio_device_changed",
    "audio_format",
    "audio_overflow",
    "system_capture",
    "helper_stopped",
}


class MacOSSource:
    def __init__(self, executable: Path):
        self.executable = executable
        self.process = None
        self.server = None
        self.writer = None
        self.reader = None
        self.directory = None
        self.sequences = {"microphone": 0, "system": 0}

    async def message(self):
        try:
            raw = await asyncio.wait_for(self.reader.readline(), 30)
            if not raw or len(raw) > 8192:
                raise AudioError("helper_stopped")
            message = json.loads(raw)
            if message.get("type") == "stopped":
                raise AudioError("capture_stopped")
            if message.get("type") == "error":
                code = message.get("code")
                raise AudioError(code if code in HELPER_ERRORS else "system_capture")
            return message
        except (ValueError, TimeoutError) as exc:
            raise AudioError("helper_protocol") from exc

    def launch_arguments(self, socket_path):
        # Launch Services gives the .app its own TCC identity, rather than attributing
        # microphone access to the backend's terminal/IDE process.
        return [
            "/usr/bin/open",
            "-n",
            "-W",
            str(self.executable.parents[2]),
            "--args",
            "--socket",
            str(socket_path),
        ]

    async def start(self):
        self.directory = tempfile.TemporaryDirectory(prefix="explore-audio-", dir="/tmp")
        socket_path = Path(self.directory.name) / "capture.sock"
        connected = asyncio.get_running_loop().create_future()

        def accept(reader, writer):
            if connected.done():
                writer.close()
                return
            self.reader, self.writer = reader, writer
            connected.set_result(None)

        # A 0700 private directory protects the socket; no TCP listener or provider key.
        self.server = await asyncio.start_unix_server(accept, path=socket_path, limit=8192)
        os.chmod(socket_path, 0o600)
        self.process = await asyncio.create_subprocess_exec(
            *self.launch_arguments(socket_path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(connected, 10)
        message = await self.message()
        if message != {"type": "ready", "version": 1, "sample_rate": 16000}:
            raise AudioError("helper_protocol")

    async def read(self):
        message = await self.message()
        try:
            channel, sequence = message["channel"], message["sequence"]
            if channel not in self.sequences or type(sequence) is not int:
                raise ValueError
            pcm = base64.b64decode(message["pcm"], validate=True)
            if (
                message.get("type") != "audio"
                or len(pcm) != 3200
                or sequence != self.sequences[channel]
            ):
                raise ValueError
            self.sequences[channel] += 1
            count = message.get("input_samples")
            if count is not None and (type(count) is not int or not 0 <= count <= 1600):
                raise ValueError
            return AudioFrame(channel, sequence, pcm, count)
        except (KeyError, TypeError, ValueError) as exc:
            raise AudioError("helper_protocol") from exc

    async def close(self):
        if self.server:
            self.server.close()
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass
        if self.server:
            await asyncio.wait_for(self.server.wait_closed(), 1)
        if self.process:
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.directory:
            self.directory.cleanup()
