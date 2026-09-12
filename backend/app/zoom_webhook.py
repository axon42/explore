"""Isolated webhook ingress. No UI, join-token, transcript or database-control routes."""

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings

MAX_BODY = 32768
MAX_EVENTS = 1000
EVENTS = {"session.rtms_started", "session.rtms_stopped"}


class Envelope(BaseModel):
    model_config = ConfigDict(strict=True)
    event: str = Field(min_length=1, max_length=100)
    event_ts: int = Field(ge=0)
    payload: dict


class StreamPayload(BaseModel):
    model_config = ConfigDict(strict=True)
    session_id: str = Field(min_length=1, max_length=200)
    rtms_stream_id: str = Field(min_length=1, max_length=200)
    session_key: str | None = Field(default=None, max_length=200)
    account_id: str | None = Field(default=None, max_length=200)
    server_urls: str | None = Field(default=None, max_length=4000)
    stop_reason: int | None = None


class Inbox:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=1) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS zoom_events (
                id TEXT PRIMARY KEY, event TEXT NOT NULL, event_ts INTEGER NOT NULL,
                payload TEXT NOT NULL, received_at INTEGER NOT NULL)""")

    def put(self, event: Envelope) -> bool:
        # Re-signed retries retain event identity. Store metadata only, never a signature/secret.
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
        identity = hashlib.sha256(f"{event.event}:{event.event_ts}:{payload}".encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=1) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM zoom_events WHERE id=?", (identity,)).fetchone():
                return True
            if db.execute("SELECT count(*) FROM zoom_events").fetchone()[0] >= MAX_EVENTS:
                return False
            db.execute(
                "INSERT INTO zoom_events VALUES (?, ?, ?, ?, ?)",
                (identity, event.event, event.event_ts, payload, int(time.time())),
            )
        return True


def create_webhook_app(settings: Settings | None = None):
    settings = settings or Settings()
    secret = settings.zoom_webhook_secret_token.get_secret_value().encode()
    inbox = Inbox(settings.data_dir / "zoom-webhooks.sqlite3")

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(inbox.initialize)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/webhooks/zoom")
    async def receive(request: Request):
        def fail(code: str, status: int):
            return JSONResponse({"code": code}, status_code=status)

        if not secret:
            return fail("webhook_unconfigured", 503)
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return fail("invalid_content_type", 415)
        timestamp = request.headers.get("x-zm-request-timestamp", "")
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
            return fail("invalid_signature", 401)
        if abs(time.time() - int(timestamp)) > 300:
            return fail("stale_signature", 401)
        body = bytearray()
        try:
            async with asyncio.timeout(2):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return fail("body_too_large", 413)
        except TimeoutError:
            return fail("body_timeout", 408)
        expected = (
            "v0="
            + hmac.new(
                secret, b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
            ).hexdigest()
        )
        supplied = request.headers.get("x-zm-signature", "")
        if not supplied.isascii() or not hmac.compare_digest(expected, supplied):
            return fail("invalid_signature", 401)
        try:
            event = Envelope.model_validate_json(body)
        except ValidationError:
            return fail("invalid_event", 400)
        if event.event == "endpoint.url_validation":
            token = event.payload.get("plainToken")
            if not isinstance(token, str) or not 1 <= len(token) <= 256:
                return fail("invalid_challenge", 400)
            return JSONResponse(
                {
                    "plainToken": token,
                    "encryptedToken": hmac.new(secret, token.encode(), hashlib.sha256).hexdigest(),
                },
                headers={"Cache-Control": "no-store"},
            )
        if event.event not in EVENTS:
            return JSONResponse({"status": "ignored"})
        try:
            payload = StreamPayload.model_validate(event.payload)
        except ValidationError:
            return fail("invalid_stream_event", 400)
        if event.event == "session.rtms_started" and not payload.server_urls:
            return fail("missing_stream_server", 400)
        # URLs are retained as untrusted metadata, never fetched by ingress.
        event.payload = payload.model_dump(exclude_none=True)
        try:
            accepted = await asyncio.to_thread(inbox.put, event)
        except sqlite3.Error:
            return fail("inbox_unavailable", 503)
        if not accepted:
            return fail("inbox_full", 503)
        return JSONResponse({"status": "received"})

    return app


app = create_webhook_app()
