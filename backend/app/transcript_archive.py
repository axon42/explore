"""Independent, append-only evidence database. Writes share the working DB transaction."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class TranscriptArchive:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise sqlite3.DatabaseError("Unsupported transcript archive version")
            if version == 0:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE archive_sessions (
                        session_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL, created_at TEXT NOT NULL,
                        title TEXT NOT NULL, mode TEXT NOT NULL
                    );
                    CREATE TABLE archive_identity (id TEXT PRIMARY KEY);
                    CREATE TABLE archive_contexts (
                        session_id TEXT NOT NULL REFERENCES archive_sessions(session_id),
                        digest TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL,
                        PRIMARY KEY(session_id, digest)
                    );
                    CREATE TABLE archive_events (
                        session_id TEXT NOT NULL REFERENCES archive_sessions(session_id),
                        segment_id TEXT NOT NULL, revision INTEGER NOT NULL,
                        event_id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
                        archived_at TEXT NOT NULL,
                        PRIMARY KEY(session_id, segment_id, revision)
                    );
                    PRAGMA user_version=1;
                """)
                db.execute("INSERT INTO archive_identity VALUES (?)", (str(uuid4()),))
            for table in ("archive_sessions", "archive_contexts", "archive_events"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} "
                        f"BEFORE {operation} ON {table} BEGIN "
                        "SELECT RAISE(ABORT, 'Transcript archive is append-only'); END"
                    )
        self.path.chmod(0o600)

    def identity(self):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT id FROM archive_identity").fetchone()[0]

    def attach(self, db):
        # mode=rw refuses to silently recreate a lost/moved archive during normal operation.
        db.execute("ATTACH DATABASE ? AS evidence", (self.path.as_uri() + "?mode=rw",))
        if db.execute(
            "SELECT 1 FROM main.sqlite_master WHERE name='transcript_archive_binding'"
        ).fetchone():
            bound = db.execute("SELECT archive_id FROM main.transcript_archive_binding").fetchone()
            identity = db.execute("SELECT id FROM evidence.archive_identity").fetchone()
            if bound and (not identity or identity[0] != bound[0]):
                raise sqlite3.DatabaseError("Original transcript archive is missing or replaced")
        for schema in ("main", "evidence"):
            if db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] != "delete":
                raise sqlite3.DatabaseError("Transcript archive requires rollback journaling")
            db.execute(f"PRAGMA {schema}.synchronous=FULL")

    @staticmethod
    def context(db, sid):
        row = db.execute(
            "SELECT s.*, m.workspace_id, m.title AS meeting_title FROM sessions s "
            "JOIN meetings m ON m.id=s.meeting_id WHERE s.id=?",
            (sid,),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Transcript archive session missing")
        session = dict(row)
        db.execute(
            "INSERT INTO evidence.archive_sessions VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (
                sid,
                row["meeting_id"],
                row["workspace_id"],
                row["created_at"],
                row["meeting_title"],
                row["mode"],
            ),
        )
        context = {"session": session}
        context["schema_version"] = 2
        # Each correction appends a distinct context snapshot. Earlier states stay immutable.
        context["speaker_assignments"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM speaker_assignments WHERE session_id=? AND version IN "
                "(SELECT MAX(version) FROM speaker_assignments WHERE session_id=? "
                "GROUP BY track_id,segment_id,segment_revision,span_index) ORDER BY version",
                (sid, sid),
            )
        ]
        for key, query in {
            "participants": "SELECT * FROM meeting_participants WHERE meeting_id=?",
            "brief": (
                "SELECT * FROM meeting_briefs WHERE meeting_id=? ORDER BY revision DESC LIMIT 1"
            ),
            "source": "SELECT * FROM session_producers WHERE session_id=?",
        }.items():
            item = db.execute(query, (sid if key == "source" else row["meeting_id"],)).fetchone()
            context[key] = dict(item) if item else None
        # Session version changes every event; it is not a change of interview context.
        context["session"].pop("version", None)
        payload = canonical(context)
        db.execute(
            "INSERT INTO evidence.archive_contexts VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (
                sid,
                hashlib.sha256(payload.encode()).hexdigest(),
                payload,
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def event(db, sid, value):
        payload = canonical(value)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        key = (sid, value["segment_id"], value["revision"])
        db.execute(
            "INSERT INTO evidence.archive_events VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (*key, value["event_id"], payload, digest, datetime.now(UTC).isoformat()),
        )
        saved = db.execute(
            "SELECT digest FROM evidence.archive_events "
            "WHERE session_id=? AND segment_id=? AND revision=?",
            key,
        ).fetchone()
        if saved[0] != digest:
            raise sqlite3.DatabaseError("Transcript archive revision conflict")

    def preserve(self, db, sid):
        self.context(db, sid)
        for row in db.execute("SELECT payload FROM segment_revisions WHERE session_id=?", (sid,)):
            self.event(db, sid, json.loads(row[0]))
