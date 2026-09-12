"""Synchronous SQLite operations; the service runs every call in a worker thread."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import DomainError, TranscriptEvent
from .schema import migrate


def now() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with sqlite3.connect(self.path) as source:
                tables = {
                    r[0]
                    for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                backup = self.path.with_suffix(".before-discovery.sqlite3")
                if (
                    "sessions" in tables
                    and "schema_migrations" not in tables
                    and not backup.exists()
                ):
                    with sqlite3.connect(backup) as destination:
                        source.backup(destination)
                if (
                    "schema_migrations" in tables
                    and not source.execute(
                        "SELECT 1 FROM schema_migrations WHERE version=2"
                    ).fetchone()
                ):
                    analysis_backup = self.path.with_suffix(".before-analysis.sqlite3")
                    if not analysis_backup.exists():
                        with sqlite3.connect(analysis_backup) as destination:
                            source.backup(destination)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id), payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('live', 'stopped')),
                    created_at TEXT NOT NULL, stopped_at TEXT,
                    version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0)
                );
                CREATE TABLE IF NOT EXISTS segments (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    segment_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision >= 0),
                    is_final INTEGER NOT NULL CHECK(is_final IN (0, 1)),
                    payload TEXT NOT NULL, PRIMARY KEY(session_id, segment_id)
                );
                CREATE TABLE IF NOT EXISTS seen_events (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    event_id TEXT NOT NULL, PRIMARY KEY(session_id, event_id)
                );
            """)
            migrate(db, now())
            interrupted = db.execute(
                "UPDATE sessions SET status='stopped', stopped_at=?, version=version+1 "
                "WHERE status='live'",
                (now(),),
            ).rowcount
        return interrupted

    def create(self, title: str | None, workspace_id: str = "default"):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)).fetchone():
                raise DomainError("not_found", "Workspace not found", 404)
            session_id, meeting_id = str(uuid4()), str(uuid4())
            title = (title or "").strip() or "Untitled session"
            db.execute(
                "INSERT INTO "
                "meetings(id,workspace_id,title,context_version,"
                "created_at,updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (meeting_id, workspace_id, title, now(), now()),
            )
            db.execute(
                "INSERT INTO meeting_briefs VALUES (?, 0, ?, ?)",
                (meeting_id, json.dumps({"title": title, "objective": ""}), now()),
            )
            db.execute(
                (
                    "INSERT INTO sessions(id,title,status,created_at,meeting_id) VALUES "
                    "(?,?,'live',?,?)"
                ),
                (session_id, title, now(), meeting_id),
            )
            return self._session(db, session_id)

    def list_sessions(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM sessions ORDER BY created_at DESC, id DESC")
            ]

    @staticmethod
    def _session(db, session_id):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise DomainError("not_found", "Session not found", 404)
        return dict(row)

    def snapshot(self, session_id):
        with self.connection() as db:
            db.execute("BEGIN")
            session = self._session(db, session_id)
            segments = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM segments WHERE session_id=?", (session_id,)
                )
            ]
            segments.sort(key=lambda x: (x["start_ms"], x["segment_id"]))
            return {
                "type": "snapshot",
                "version": session["version"],
                "session": session,
                "segments": segments,
            }

    def stop(self, session_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id)
            if session["status"] == "stopped":
                return session, False
            db.execute(
                "UPDATE sessions SET status='stopped', stopped_at=?, version=version+1 WHERE id=?",
                (now(), session_id),
            )
            return self._session(db, session_id), True

    def ingest(self, session_id: str, event: TranscriptEvent):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id)
            if session["status"] != "live":
                raise DomainError("session_stopped", "This session has stopped")
            inserted = db.execute(
                "INSERT OR IGNORE INTO seen_events VALUES (?, ?)", (session_id, event.event_id)
            ).rowcount
            reason = None
            if not inserted:
                reason = "duplicate"
            else:
                previous = db.execute(
                    "SELECT revision, is_final FROM segments WHERE session_id=? AND segment_id=?",
                    (session_id, event.segment_id),
                ).fetchone()
                if previous and event.revision <= previous["revision"]:
                    reason = "stale_revision"
                elif previous and previous["is_final"] and not event.is_final:
                    reason = "finalized_segment"
            change = None
            if reason is None:
                payload = event.model_dump()
                db.execute(
                    "INSERT INTO segment_revisions VALUES (?, ?, ?, ?)",
                    (session_id, event.segment_id, event.revision, json.dumps(payload)),
                )
                db.execute(
                    "INSERT INTO segments VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_id, segment_id) DO UPDATE SET "
                    "revision=excluded.revision, is_final=excluded.is_final, "
                    "payload=excluded.payload",
                    (
                        session_id,
                        event.segment_id,
                        event.revision,
                        event.is_final,
                        json.dumps(payload),
                    ),
                )
                db.execute("UPDATE sessions SET version=version+1 WHERE id=?", (session_id,))
                session["version"] += 1
                change = {"type": "segment", "version": session["version"], "segment": payload}
            ack = {
                "type": "ack",
                "event_id": event.event_id,
                "outcome": "ignored" if reason else "accepted",
                "version": session["version"],
            }
            if reason:
                ack["reason"] = reason
        # The transaction has committed before the acknowledgement leaves storage.
        return ack, change

    def experiment(self, session_id):
        with self.connection() as db:
            self._session(db, session_id)
            row = db.execute(
                "SELECT payload FROM experiments WHERE session_id=?", (session_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_experiment(self, session_id, payload):
        with self.connection() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, ?) ON CONFLICT(session_id) "
                "DO UPDATE SET payload=excluded.payload",
                (session_id, json.dumps(payload)),
            )
