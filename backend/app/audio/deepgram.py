"""Deepgram streaming adapter. Owns no database, session selection or UI state."""

import hashlib
import json
import math
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK

from ..models import AttributedTranscriptEvent, SpeakerMetadata, SpeakerSpan
from .source import AudioError


def speaker_spans(text, words, final, single_person):
    """Only exact sequential word alignment establishes a voice; retain unknown text."""
    unknown = [SpeakerSpan(start=0, end=len(text), label=None)]
    if single_person:
        return [SpeakerSpan(start=0, end=len(text), label=0)]
    if not final or not isinstance(words, list) or not words or len(words) > 2000:
        return unknown
    spans, cursor, last_time = [], 0, 0
    for word in words:
        if not isinstance(word, dict):
            return unknown
        token = word.get("punctuated_word", word.get("word"))
        if not isinstance(token, str) or not token:
            return unknown
        start = cursor
        while start < len(text) and text[start].isspace():
            start += 1
        if not text.startswith(token, start):
            return unknown
        end = start + len(token)
        label = word.get("speaker")
        times = (word.get("start"), word.get("end"))
        valid_time = all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in times)
        if (
            type(label) is not int
            or not 0 <= label <= 999
            or not valid_time
            or times[1] < times[0]
            or times[0] < last_time - 0.02
        ):
            label = None
        if valid_time:
            last_time = times[1]
        if spans and spans[-1].label == label:
            spans[-1].end = end
        else:
            spans.append(SpeakerSpan(start=cursor, end=end, label=label))
        cursor = end
    if text[cursor:].strip():
        return unknown
    spans[-1].end = len(text)
    return spans


class DeepgramNormalizer:
    def __init__(self, capture_id, channel, offset_ms, single_person=False):
        self.prefix = f"audio-{capture_id}-{channel}"
        self.capture_id, self.single_person = capture_id, single_person
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
                or (start + duration) * 1000 + self.offset_ms > 9007199254740991
            ):
                raise ValueError
            text = message["channel"]["alternatives"][0]["transcript"]
            final = message["is_final"]
            if not isinstance(text, str) or len(text) > 20000 or type(final) is not bool:
                raise ValueError
            if not text.strip():
                return None
            key = round(start * 1000)
            text = text.strip()
            metadata = SpeakerMetadata(
                capture_id=self.capture_id,
                channel=self.channel,
                method="single_person_source" if self.single_person else "diarized",
                spans=speaker_spans(
                    text,
                    message["channel"]["alternatives"][0].get("words"),
                    final,
                    self.single_person,
                ),
            )
            signature = hashlib.sha256(
                json.dumps([text, final, duration, metadata.model_dump()]).encode()
            ).hexdigest()
            previous = self.revisions.get(key)
            if previous and previous[1] == signature:
                return None
            if previous and previous[2] and not final:
                return None
            revision = previous[0] + 1 if previous else 0
            self.revisions[key] = (revision, signature, final)
            return AttributedTranscriptEvent(
                speaker_metadata=metadata,
                event_id=f"{self.prefix}-{key}-{signature}",
                segment_id=f"{self.prefix}-{key}",
                revision=revision,
                speaker_id=self.channel,
                speaker_name="Microphone" if self.channel == "microphone" else "System audio",
                start_ms=self.offset_ms + key,
                end_ms=self.offset_ms + round((start + duration) * 1000),
                text=text,
                is_final=final,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AudioError("transcription_invalid") from exc


class DeepgramStream:
    def __init__(self, key, connector=connect, *, diarize=True):
        self.key, self.connector = key, connector
        self.diarize = diarize
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
                **({"diarize_model": "v1"} if self.diarize else {}),
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
