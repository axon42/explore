"""Bounded local diagnostics. Content is opt-in; ordinary logs stay content-free."""

import json
import logging
import os
import re
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from uuid import uuid4

from pydantic import SecretStr

ACTIVE_TRACE = ContextVar("explore_model_trace", default=None)
MAX_BODY = 131072
MAX_TRACES = 100


def safe_body(value, secrets):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    text = re.sub(r"AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{16,}", "[REDACTED]", text)
    return text[:MAX_BODY], len(text) > MAX_BODY


@dataclass
class ModelTrace:
    session_id: str
    job_id: str
    model: str
    capture: bool
    epoch: int
    generation: int
    id: str = field(default_factory=lambda: str(uuid4()))
    started: float = field(default_factory=time.monotonic)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict = field(default_factory=dict)
    request: object = None
    response: object = None


def request_sent(payload):
    trace = ACTIVE_TRACE.get()
    if trace:
        trace.metadata["request_kind"] = "provider_payload"
        trace.metadata["request_bytes"] = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        if trace.capture:
            trace.request = payload


def response_received(response):
    trace = ACTIVE_TRACE.get()
    if trace:
        trace.metadata.update(
            http_status=response.status_code, response_bytes=len(response.content)
        )
        if trace.capture:
            trace.response = response.text


def provider_metadata(**fields):
    trace = ACTIVE_TRACE.get()
    if trace:
        trace.metadata.update(fields)


class PrivateRotatingLog(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.baseFilename, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")


class SafeEvents(logging.Handler):
    """A bounded in-memory tail; accept known structured fields, never arbitrary messages."""

    fields = {
        "event",
        "code",
        "session_id",
        "job_id",
        "request_id",
        "status",
        "elapsed_ms",
        "error_type",
        "count",
        "interrupted_sessions",
        "outcome",
    }

    def __init__(self):
        super().__init__()
        self.events = deque(maxlen=500)
        self.file = None

    def initialize(self, directory):
        path = directory / "developer-events.jsonl"
        if path.exists():
            with path.open() as handle:
                lines = deque(handle, maxlen=200)
            for line in lines:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and isinstance(value.get("event"), str):
                        self.events.append(self.clean(value))
                except ValueError:
                    continue
        self.file = PrivateRotatingLog(path, maxBytes=512000, backupCount=2)
        path.chmod(0o600)
        self.file.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        try:
            value = json.loads(record.getMessage())
            if not isinstance(value, dict) or not isinstance(value.get("event"), str):
                return
            clean = self.clean(value)
            clean.update(time=datetime.now(UTC).isoformat(), level=record.levelname)
            self.events.append(clean)
            if self.file:
                self.file.emit(
                    logging.LogRecord(
                        "diagnostics", record.levelno, "", 0, json.dumps(clean), (), None
                    )
                )
        except (ValueError, TypeError, OSError):
            return

    @classmethod
    def clean(cls, value):
        return {
            k: v
            for k, v in value.items()
            if k in cls.fields | {"time", "level"}
            and (
                isinstance(v, (int, float, bool))
                or isinstance(v, str)
                and re.fullmatch(r"[a-zA-Z0-9_.:+-]{1,200}", v)
            )
        }

    def tail(self):
        self.acquire()
        try:
            return list(self.events)[-200:]
        finally:
            self.release()


class Diagnostics:
    def __init__(self, storage, settings):
        self.storage = storage
        self.secrets = [
            v.get_secret_value() for v in settings.__dict__.values() if isinstance(v, SecretStr)
        ]
        self.bodies_until = 0.0
        self.epoch = 0
        self.generation = 0
        self.events = SafeEvents()

    def recording(self, enabled=None):
        if enabled is not None:
            self.epoch += 1
            self.bodies_until = time.monotonic() + 900 if enabled else 0
        return {
            "enabled": time.monotonic() < self.bodies_until,
            "remaining_seconds": max(0, round(self.bodies_until - time.monotonic())),
            "retention_hours": 24,
            "max_traces": MAX_TRACES,
        }

    def begin(self, sid, context, model, timeout):
        trace = ModelTrace(
            sid, context["job_id"], model, self.recording()["enabled"], self.epoch, self.generation
        )
        trace.metadata.update(
            provider=context.get("model_selection", {}).get("provider"),
            timeout_seconds=timeout,
            scheduling_mode=context.get("scheduling_mode", "automatic"),
            scope=context.get("scope", "incremental"),
            review_kind=context.get("review_kind", "live"),
            input_watermark=context.get("input_version"),
            input_chars=len(json.dumps(context)),
            segment_count=len(context["segments"]),
            new_segments=len(context["new_source_ids"]),
        )
        if trace.capture:
            trace.request = {"analysis_context": context}
        trace.metadata["request_kind"] = "analysis_context"
        self.save(trace, "running")
        return trace

    def save(self, trace, outcome, code="", usage=None):
        if trace.generation != self.generation:
            return
        request, response, truncated = None, None, False
        if trace.capture and trace.epoch == self.epoch and self.recording()["enabled"]:
            if trace.request is not None:
                request, cut = safe_body(trace.request, self.secrets)
                truncated |= cut
            if trace.response is not None:
                response, cut = safe_body(trace.response, self.secrets)
                truncated |= cut
        metadata = {
            **trace.metadata,
            "elapsed_ms": round((time.monotonic() - trace.started) * 1000),
            "code": code,
            "usage": usage or {},
            "body_truncated": truncated,
            "body_recording": trace.capture,
        }
        try:
            with self.storage.connection() as db:
                if not db.execute(
                    "SELECT 1 FROM sessions WHERE id=?", (trace.session_id,)
                ).fetchone():
                    return  # A reset/deletion wins over an old diagnostic completion.
                db.execute(
                    "INSERT INTO developer_traces VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) "
                    "DO UPDATE SET outcome=excluded.outcome,metadata=excluded.metadata,"
                    "request_body=excluded.request_body,response_body=excluded.response_body",
                    (
                        trace.id,
                        trace.session_id,
                        trace.job_id,
                        trace.model,
                        trace.created_at,
                        outcome,
                        json.dumps(metadata),
                        request,
                        response,
                    ),
                )
                self.prune(db)
        except Exception:
            # Diagnostics cannot fail ingestion or an otherwise successful model commit.
            logging.getLogger("meeting").warning('{"event":"diagnostics_write_failed"}')

    @staticmethod
    def prune(db):
        before = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        db.execute("DELETE FROM developer_traces WHERE created_at<?", (before,))
        db.execute(
            "DELETE FROM developer_traces WHERE id IN (SELECT id FROM developer_traces "
            "ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET ?)",
            (MAX_TRACES,),
        )

    def list(self, sid=None):
        with self.storage.connection() as db:
            self.prune(db)
            rows = db.execute(
                "SELECT t.id,t.session_id,t.job_id,t.model,t.created_at,t.outcome,t.metadata,"
                "m.title AS meeting_title,m.id AS meeting_id,m.workspace_id "
                "FROM developer_traces t "
                "JOIN sessions s ON s.id=t.session_id JOIN meetings m ON m.id=s.meeting_id "
                "WHERE (? IS NULL OR t.session_id=?) "
                "ORDER BY t.created_at DESC,t.id DESC LIMIT 100",
                (sid, sid),
            ).fetchall()
            return [{**dict(r), "metadata": json.loads(r["metadata"])} for r in rows]

    def detail(self, trace_id):
        from .models import DomainError

        with self.storage.connection() as db:
            self.prune(db)
            row = db.execute("SELECT * FROM developer_traces WHERE id=?", (trace_id,)).fetchone()
            if not row:
                raise DomainError("not_found", "Diagnostic request expired or was removed.", 404)
            return {**dict(row), "metadata": json.loads(row["metadata"])}

    def maintain(self):
        with self.storage.connection() as db:
            self.prune(db)

    def clear(self):
        self.generation += 1
        self.recording(False)
        with self.storage.connection() as db:
            db.execute("DELETE FROM developer_traces")
        self.events.acquire()
        try:
            self.events.events.clear()
            if self.events.file:
                path = self.storage.path.parent / "developer-events.jsonl"
                self.events.file.stream.seek(0)
                self.events.file.stream.truncate()
                for suffix in (".1", ".2"):
                    path.with_name(path.name + suffix).unlink(missing_ok=True)
        finally:
            self.events.release()
        return {"cleared": True}
