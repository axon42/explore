"""Local pilot coordinator: one explicit binding, one stream attempt, no reconnects."""

import asyncio
import json
import sqlite3
import time
from uuid import uuid4

from .models import DomainError
from .zoom_rtms import RTMSClient
from .zoom_webhook import Inbox


class ZoomCapture:
    def __init__(self, service, settings):
        self.service, self.settings = service, settings
        self.inbox = Inbox(settings.data_dir / "zoom-webhooks.sqlite3")
        self.binding = None
        self.task = None
        self.lock = asyncio.Lock()
        self.client = RTMSClient(
            settings.zoom_video_sdk_key.get_secret_value(),
            settings.zoom_video_sdk_secret.get_secret_value(),
        )

    async def bind(self, sid):
        async with self.lock:
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            if snapshot["session"]["status"] != "live":
                raise DomainError("zoom_stopped", "Choose a live test session")
            if self.binding and self.binding["sid"] != sid:
                raise DomainError(
                    "zoom_bound", "This Zoom test is already bound to another meeting"
                )
            if not self.binding:
                if snapshot["segments"]:
                    raise DomainError("zoom_not_empty", "Create a fresh meeting for the Zoom test")
                await asyncio.to_thread(self.inbox.initialize)
                self.binding = {
                    "sid": sid,
                    "key": str(uuid4()),
                    "status": "ready",
                    "error": "",
                    "started": time.time(),
                    "count": 0,
                }
            return self.binding["key"]

    def view(self):
        if not self.binding:
            return {"status": "unbound", "error": "", "count": 0}
        return {key: self.binding[key] for key in ("sid", "status", "error", "count")}

    async def arm(self):
        async with self.lock:
            if not self.binding or self.binding["status"] != "ready":
                raise DomainError("zoom_capture_state", "Capture can be started only once per test")
            if not self.settings.zoom_webhook_secret_token.get_secret_value():
                raise DomainError("zoom_webhook_missing", "Configure the Zoom webhook secret first")
            self.binding["status"] = "waiting"
            self.task = asyncio.create_task(self.watch())

    def events(self):
        with sqlite3.connect(self.inbox.path, timeout=1) as db:
            rows = db.execute(
                "SELECT event,payload FROM zoom_events WHERE received_at>=? ORDER BY rowid",
                (int(self.binding["started"]),),
            ).fetchall()
        return [
            (event, json.loads(payload))
            for event, payload in rows
            if json.loads(payload).get("session_key") == self.binding["key"]
        ]

    async def watch(self):
        binding = self.binding
        stream = None
        try:
            async with asyncio.timeout(120):
                while True:
                    snapshot = await self.service.read(
                        self.service.storage.snapshot, binding["sid"]
                    )
                    if snapshot["session"]["status"] != "live":
                        raise DomainError("zoom_stopped", "Explore session ended")
                    events = await asyncio.to_thread(self.events)
                    starts = [
                        payload for event, payload in events if event == "session.rtms_started"
                    ]
                    stops = {
                        p["rtms_stream_id"]
                        for event, p in events
                        if event == "session.rtms_stopped"
                    }
                    if starts:
                        payload = starts[0]
                        if payload["rtms_stream_id"] in stops:
                            binding.update(status="stopped")
                            return
                        if not stream:

                            async def deliver(event):
                                await self.service.ingest(binding["sid"], event)
                                binding["count"] += 1

                            async def ready():
                                binding["status"] = "streaming"

                            stream = asyncio.create_task(self.client.run(payload, deliver, ready))
                        if stream.done():
                            await stream
                            raise RuntimeError("Stream ended")
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            binding["status"] = "stopped"
            raise
        except TimeoutError:
            binding.update(
                status="stopped", error="Two-minute capture window ended. End Zoom for everyone."
            )
        except Exception:
            binding.update(
                status="failed",
                error=(
                    "Zoom capture interrupted or handshake failed. "
                    "End Zoom and check configuration. "
                    "Transcript already received is saved."
                ),
            )
        finally:
            if stream:
                stream.cancel()
                await asyncio.gather(stream, return_exceptions=True)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def release(self):
        async with self.lock:
            await self.close()
            self.task = None
            self.binding = None
