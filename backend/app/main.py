import asyncio
import hmac
import json
import logging
import sqlite3
from contextlib import asynccontextmanager, suppress

from anyio import CancelScope
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .broadcast import Broadcaster
from .config import Settings
from .discovery_api import router
from .models import CreateSession, DomainError, TranscriptEvent
from .pipeline import FIXTURE, Pipeline, PlaybackCommand
from .replay import replay
from .service import Service
from .storage import Storage

logger = logging.getLogger("meeting")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log(event: str, **fields):
    logger.info(json.dumps({"event": event, **fields}))


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    storage = Storage(settings.data_dir / "meetings.sqlite3")
    broker = Broadcaster(settings.subscriber_queue_size)
    service = Service(storage, broker)
    pipeline = Pipeline(service, settings)
    service.on_final = pipeline.notify
    replays: dict[str, asyncio.Task] = {}
    sockets: set[WebSocket] = set()

    @asynccontextmanager
    async def lifespan(app):
        recovered = await asyncio.to_thread(storage.initialize)
        log("startup", interrupted_sessions=recovered)
        yield
        await pipeline.close()
        for task in replays.values():
            task.cancel()
        await asyncio.gather(*replays.values(), return_exceptions=True)
        for socket in tuple(sockets):
            with suppress(RuntimeError, WebSocketDisconnect):
                await socket.close(code=1001)
        await service.read(storage_stop_live)
        log("shutdown")

    def storage_stop_live():
        for session in storage.list_sessions():
            if session["status"] == "live":
                storage.stop(session["id"])

    app = FastAPI(title="Explore", lifespan=lifespan)
    app.state.pipeline = pipeline
    app.state.service = service
    app.state.replays = replays

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        # CORS alone does not prevent cross-origin writes. Reject their origins.
        origin = request.headers.get("origin")
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"code": "invalid_host", "message": "Local hosts only"}, 403)
        if origin and origin not in settings.origins:
            return JSONResponse({"code": "invalid_origin", "message": "Origin not allowed"}, 403)
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        log("request_error", code=exc.code)
        return JSONResponse({"code": exc.code, "message": exc.message}, exc.status)

    @app.get("/health")
    async def health():
        return {"status": "ok", "demo_enabled": settings.demo_enabled}

    @app.post("/sessions", status_code=201)
    async def create(body: CreateSession):
        session = await service.read(storage.create, body.title)
        log("session_created", session_id=session["id"])
        return session

    @app.get("/sessions")
    async def sessions():
        return await service.read(storage.list_sessions)

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        return await service.read(storage.snapshot, session_id)

    async def stop_session(session_id: str, finalize: bool = True):
        session = await service.stop(session_id)
        active = pipeline.report_workers.get(session_id)
        if finalize and active and not active.done():
            return session
        await pipeline.stop(session_id)
        task = replays.get(session_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if finalize:
            await pipeline.request_report(session_id)
        log("session_stopped", session_id=session_id)
        return session

    @app.post("/sessions/{session_id}/stop")
    async def stop(session_id: str):
        return await stop_session(session_id)

    @app.get("/fixtures")
    async def fixtures():
        return [{k: FIXTURE[k] for k in ("id", "title", "objective")}]

    @app.get("/sessions/{session_id}/experiment")
    async def experiment(session_id: str):
        return await pipeline.view(session_id)

    @app.post("/sessions/{session_id}/playback")
    async def playback(session_id: str, command: PlaybackCommand):
        return await pipeline.command(session_id, command)

    @app.post("/sessions/{session_id}/inject")
    async def inject(session_id: str, event: TranscriptEvent):
        return await service.ingest(session_id, event)

    app.include_router(router(service, pipeline, stop_session))

    async def run_demo(session_id: str):
        try:
            await replay(
                f"ws://127.0.0.1:{settings.backend_port}/sessions/{session_id}/ingest",
                settings.ingestion_token.get_secret_value(),
            )
            log("demo_finished", session_id=session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never include exception strings that may contain producer payloads/headers.
            log("demo_failed", session_id=session_id, error_type=type(exc).__name__)
            async with service.lock:
                broker.publish(session_id, {"type": "demo_error", "message": "Demo replay failed"})
        finally:
            replays.pop(session_id, None)

    @app.post("/sessions/{session_id}/demo", status_code=202)
    async def start_demo(session_id: str):
        if not settings.demo_enabled:
            raise DomainError("demo_disabled", "Demo mode is disabled", 404)
        async with service.lock:
            snapshot = await asyncio.to_thread(storage.snapshot, session_id)
            if snapshot["session"]["status"] != "live":
                raise DomainError("session_stopped", "This session has stopped")
            if session_id in replays:
                raise DomainError("demo_running", "A demo is already running")
            if any(s["event_id"].startswith("demo-") for s in snapshot["segments"]):
                raise DomainError("demo_completed", "Create a new session to replay the demo again")
            replays[session_id] = asyncio.create_task(run_demo(session_id))
        log("demo_started", session_id=session_id)
        return {"status": "started"}

    async def authorize(ws: WebSocket, ingest: bool):
        origin = ws.headers.get("origin")
        # UI sockets require an explicit local origin; headless producers use a token if set.
        valid = ws.url.hostname in {"127.0.0.1", "localhost", "testserver"}
        valid = valid and (origin in settings.origins or (ingest and origin is None))
        token = settings.ingestion_token.get_secret_value()
        if ingest and token:
            valid = valid and hmac.compare_digest(
                ws.headers.get("authorization", ""), f"Bearer {token}"
            )
        if not valid:
            log("connection_rejected", channel="ingest" if ingest else "events")
            await ws.close(code=1008)
        return valid

    @app.websocket("/sessions/{session_id}/ingest")
    async def ingest(ws: WebSocket, session_id: str):
        if not await authorize(ws, True):
            return
        await ws.accept()
        sockets.add(ws)
        log("connected", channel="ingest", session_id=session_id)
        try:
            while True:
                frame = await ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                try:
                    raw = frame.get("text")
                    if raw is None:
                        raise DomainError("invalid_frame", "Send a JSON text frame", 400)
                    if len(raw) > 65536:
                        raise DomainError("payload_too_large", "Event exceeds 64 KiB", 413)
                    event = TranscriptEvent.model_validate_json(raw)
                    await ws.send_json(await service.ingest(session_id, event))
                except ValidationError as exc:
                    # Pydantic's default errors include input; omit it and arbitrary ctx.
                    details = [{"field": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "invalid_event",
                            "message": "Invalid transcript event",
                            "details": details,
                        }
                    )
                    log("ingest_error", session_id=session_id, code="invalid_event")
                except DomainError as exc:
                    await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
                    log("ingest_error", session_id=session_id, code=exc.code)
                except sqlite3.Error as exc:
                    log("storage_error", session_id=session_id, error_type=type(exc).__name__)
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "storage_error",
                            "message": "Could not persist event; retry with the same event_id",
                        }
                    )
                except (OSError, RuntimeError) as exc:
                    log("ingest_failure", session_id=session_id, error_type=type(exc).__name__)
                    raise
        except WebSocketDisconnect:
            pass
        finally:
            sockets.discard(ws)
            log("disconnected", channel="ingest", session_id=session_id)

    @app.websocket("/sessions/{session_id}/events")
    async def events(ws: WebSocket, session_id: str):
        if not await authorize(ws, False):
            return
        await ws.accept()
        sockets.add(ws)
        subscriber = None
        tasks = []
        try:
            subscriber = await service.subscribe(session_id)
            log("connected", channel="events", session_id=session_id)

            async def send():
                while True:
                    message = await subscriber.queue.get()
                    await asyncio.wait_for(ws.send_json(message), timeout=10)

            async def receive():
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        return

            tasks = [
                asyncio.create_task(send()),
                asyncio.create_task(receive()),
                asyncio.create_task(subscriber.overflow.wait()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if subscriber.overflow.is_set():
                log("subscriber_overflow", session_id=session_id)
                # Cancel a potentially blocked send before closing the socket.
                tasks[0].cancel()
                await asyncio.gather(tasks[0], return_exceptions=True)
                await ws.close(code=1013, reason="Resynchronize from snapshot")
            for task in done:
                task.result()
        except DomainError as exc:
            await ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await ws.close(code=1008)
        except (WebSocketDisconnect, RuntimeError, TimeoutError):
            pass
        finally:
            if subscriber:
                broker.remove(session_id, subscriber)
            sockets.discard(ws)
            for task in tasks:
                task.cancel()
            # ASGI test clients and servers may cancel their enclosing scope during cleanup.
            with CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)
            log("disconnected", channel="events", session_id=session_id)

    return app


app = create_app()
