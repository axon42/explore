"""Deepgram streaming adapter. Owns no database, session selection or UI state."""

import hashlib
import json
import math
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK

from ..models import TranscriptEvent
from .source import AudioError


class DeepgramNormalizer:
    def __init__(self, capture_id, channel, offset_ms):
        self.prefix = f"audio-{capture_id}-{channel}"
        self.channel, self.offset_ms = channel, offset_ms
        self.revisions = {}

    def event(self, message):
        if message.get("type") != "Results":
            if message.get("type") == "Error":
                raise AudioError("transcription_failed")
            return None
        try:
            start, duration = message["start"], message["duration"]
            if (
                any(
                    type(v) not in (int, float) or not math.isfinite(v) or v < 0
                    for v in (start, duration)
                )
                or start + duration > 3700
            ):
                raise ValueError
            text = message["channel"]["alternatives"][0]["transcript"]
            final = message["is_final"]
            if not isinstance(text, str) or len(text) > 20000 or type(final) is not bool:
                raise ValueError
            if not text.strip():
                return None
            key = round(start * 1000)
            signature = hashlib.sha256(json.dumps([text, final, duration]).encode()).hexdigest()
            previous = self.revisions.get(key)
            if previous and previous[1] == signature:
                return None
            if previous and previous[2] and not final:
                return None
            revision = previous[0] + 1 if previous else 0
            self.revisions[key] = (revision, signature, final)
            return TranscriptEvent(
                event_id=f"{self.prefix}-{key}-{signature}",
                segment_id=f"{self.prefix}-{key}",
                revision=revision,
                speaker_id=self.channel,
                speaker_name="Microphone" if self.channel == "microphone" else "System audio",
                start_ms=self.offset_ms + key,
                end_ms=self.offset_ms + round((start + duration) * 1000),
                text=text.strip(),
                is_final=final,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AudioError("transcription_invalid") from exc


class DeepgramStream:
    def __init__(self, key, connector=connect):
        self.key, self.connector = key, connector
        self.socket = None

    async def start(self):
        query = urlencode(
            {
                "model": "nova-3",
                "language": "en",
                "encoding": "linear16",
                "sample_rate": 16000,
                "channels": 1,
                "interim_results": "true",
                "punctuate": "true",
                "endpointing": 300,
            }
        )
        self.socket = await self.connector(
            "wss://api.deepgram.com/v1/listen?" + query,
            additional_headers={"Authorization": "Token " + self.key},
            open_timeout=10,
            close_timeout=2,
            max_size=65536,
            max_queue=16,
            proxy=None,
        )

    async def send(self, pcm):
        await self.socket.send(pcm)

    async def receive(self):
        try:
            value = json.loads(await self.socket.recv())
            if not isinstance(value, dict):
                raise ValueError
            return value
        except ConnectionClosedOK:
            return None
        except (ValueError, TypeError) as exc:
            raise AudioError("transcription_invalid") from exc

    async def finish(self):
        await self.socket.send(json.dumps({"type": "CloseStream"}))

    async def close(self):
        if self.socket:
            await self.socket.close()
