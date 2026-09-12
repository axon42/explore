"""Bounded transcript-only RTMS transport. No storage or meeting selection logic."""

import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

from .models import TranscriptEvent


class StreamError(Exception):
    """Fixed safe errors only; never forward provider payloads or URLs."""


def zoom_url(value):
    if not isinstance(value, str):
        raise StreamError("Invalid Zoom stream endpoint")
    url = urlsplit(value)
    if (
        url.scheme != "wss"
        or not url.hostname
        or not url.hostname.endswith(".zoom.us")
        or not url.hostname.startswith("rtms-")
        or url.port not in (None, 443)
        or url.username
        or url.password
        or url.fragment
    ):
        raise StreamError("Unapproved Zoom stream endpoint")
    return value


class TranscriptNormalizer:
    def __init__(self, stream_id):
        self.stream_id = stream_id
        self.origin = None

    def event(self, content):
        timestamp = content["timestamp"]
        user = content["user_id"]
        text = content["data"]
        if type(timestamp) is not int or timestamp < 0 or type(user) is not int:
            raise StreamError("Invalid Zoom transcript metadata")
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise StreamError("Invalid Zoom transcript text")
        if self.origin is None:
            self.origin = timestamp
        # RTMS exposes utterance start, not duration/revision semantics. Preserve every
        # distinct packet; exact retries deduplicate. Never infer a correction from time alone.
        identity = hashlib.sha256(
            json.dumps([self.stream_id, user, timestamp, text]).encode()
        ).hexdigest()
        return TranscriptEvent(
            event_id="zoom-" + identity,
            segment_id="zoom-" + identity,
            revision=0,
            speaker_id=f"zoom-{user}",
            speaker_name=content.get("user_name"),
            start_ms=max(0, timestamp - self.origin),
            end_ms=max(0, timestamp - self.origin),
            text=text,
            is_final=True,
        )


class RTMSClient:
    def __init__(self, key, secret, connector=connect):
        self.key, self.secret, self.connector = key, secret, connector

    async def receive(self, ws):
        while True:
            raw = await asyncio.wait_for(ws.recv(), 35)
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise StreamError("Invalid Zoom stream message")
            if message.get("msg_type") != 12:
                return message
            await ws.send(json.dumps({"msg_type": 13, "timestamp": message.get("timestamp")}))

    async def run(self, payload, deliver, ready):
        identity = f"{self.key},{payload['session_id']},{payload['rtms_stream_id']}"
        signature = hmac.new(self.secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
        fields = {
            "protocol_version": 1,
            "sequence": 0,
            "meeting_uuid": payload["session_id"],
            "rtms_stream_id": payload["rtms_stream_id"],
            "signature": signature,
        }
        options = dict(open_timeout=10, close_timeout=3, max_size=65536, max_queue=16, proxy=None)
        async with self.connector(zoom_url(payload["server_urls"]), **options) as signaling:
            await signaling.send(json.dumps({**fields, "msg_type": 1}))
            async with asyncio.timeout(15):
                reply = await self.receive(signaling)
            if reply.get("msg_type") != 2 or reply.get("status_code") != 0:
                raise StreamError("Zoom signaling handshake rejected")
            url = zoom_url(reply["media_server"]["server_urls"]["transcript"])
            async with self.connector(url, **options) as media:
                await media.send(json.dumps({**fields, "msg_type": 3, "media_type": 8}))
                async with asyncio.timeout(15):
                    reply = await self.receive(media)
                if reply.get("msg_type") != 4 or reply.get("status_code") != 0:
                    raise StreamError("Zoom transcript handshake rejected")
                await signaling.send(
                    json.dumps({"msg_type": 7, "rtms_stream_id": payload["rtms_stream_id"]})
                )
                await ready()
                normalizer = TranscriptNormalizer(payload["rtms_stream_id"])

                async def signal_loop():
                    while True:
                        message = await self.receive(signaling)
                        # Any state change after readiness needs reconciliation. Do not silently
                        # treat a paused/interrupted stream as complete in this first adapter.
                        if message.get("msg_type") in (6, 8, 9):
                            raise StreamError(
                                "Zoom stream state changed; check the host capture controls"
                            )

                async def media_loop():
                    while True:
                        message = await self.receive(media)
                        if message.get("msg_type") == 17:
                            await deliver(normalizer.event(message["content"]))

                async with asyncio.TaskGroup() as group:
                    group.create_task(signal_loop())
                    group.create_task(media_loop())
