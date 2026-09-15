"""Prepared sessions and one transcript producer per run; transactions own the gate."""

import json
from uuid import uuid4

from .models import DomainError
from .storage import now


class Lifecycle:
    def __init__(self, storage):
        self.storage = storage

    def test_mode(self, enabled=None):
        with self.storage.connection() as db:
            if enabled is not None:
                db.execute("UPDATE runtime_preferences SET test_mode=? WHERE id=1", (int(enabled),))
            return {
                "enabled": bool(
                    db.execute("SELECT test_mode FROM runtime_preferences WHERE id=1").fetchone()[0]
                )
            }

    @staticmethod
    def require_test(db):
        if not db.execute("SELECT test_mode FROM runtime_preferences WHERE id=1").fetchone()[0]:
            raise DomainError("test_mode_required", "Enable Test mode in the sidebar first.", 409)

    @staticmethod
    def roster(db, mid, mode):
        row = db.execute(
            "SELECT revision,payload FROM meeting_participants WHERE meeting_id=?", (mid,)
        ).fetchone()
        people = json.loads(row[1]) if row else []
        named = [p for p in people if p.get("name", "").strip()]
        roles = {p["interview_role"] for p in named}
        if (
            len(named) != len(people)
            or not named
            or (mode != "test" and not {"interviewer", "customer"} <= roles)
        ):
            raise DomainError(
                "participants_required",
                "Add and save a named interviewer and customer. Solo tests require Test mode.",
                409,
            )
        return (row[0] if row else 0), people

    def start(self, mid, revision, mode):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            meeting = db.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
            if not meeting:
                raise DomainError("not_found", "Meeting not found", 404)
            if db.execute(
                "SELECT archived FROM workspaces WHERE id=?", (meeting["workspace_id"],)
            ).fetchone()[0]:
                raise DomainError("workspace_archived", "Restore the workspace before starting.")
            if meeting["archived"]:
                raise DomainError("conflict", "Restore the meeting before starting.")
            if mode == "test":
                self.require_test(db)
            actual, people = self.roster(db, mid, mode)
            if actual != revision:
                raise DomainError("conflict", "Participants changed. Refresh and retry.")
            existing = db.execute(
                "SELECT * FROM sessions WHERE meeting_id=? "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (mid,),
            ).fetchone()
            if existing:
                if (
                    existing["status"] == "live"
                    and existing["mode"] == mode
                    and json.loads(existing["roster_snapshot"]) == people
                ):
                    return dict(existing)
                raise DomainError(
                    "conflict",
                    "This meeting already has a session. Create a new meeting or reset the test.",
                )
            sid = str(uuid4())
            db.execute(
                "INSERT INTO sessions(id,title,status,created_at,meeting_id,mode,roster_snapshot) "
                "VALUES(?,?,'live',?,?,?,?)",
                (sid, meeting["title"], now(), mid, mode, json.dumps(people)),
            )
            return dict(db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())

    def test_access(self, sid=None):
        with self.storage.connection() as db:
            self.require_test(db)
            if sid:
                session = self.storage._session(db, sid)
                if session["mode"] == "real":
                    raise DomainError(
                        "test_session_required", "Test tools cannot change a real interview.", 409
                    )

    def claim(self, sid, kind):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.claim_in(db, sid, kind)

    def claim_in(self, db, sid, kind):
        session = self.storage._session(db, sid)
        if session["status"] != "live":
            raise DomainError("session_stopped", "This meeting has ended.")
        if session["mode"] != "legacy":
            self.roster(db, session["meeting_id"], session["mode"])
        elif kind == "capture":
            # Old meetings keep their evidence, but must satisfy the same roster gate.
            self.roster(db, session["meeting_id"], "real")
        existing = db.execute(
            "SELECT kind FROM session_producers WHERE session_id=?", (sid,)
        ).fetchone()
        if existing and existing[0] != kind:
            raise DomainError(
                "producer_conflict",
                "This session uses another transcript source. Start a separate meeting.",
                409,
            )
        db.execute("INSERT OR IGNORE INTO session_producers VALUES(?,?)", (sid, kind))

    def save_capture(self, state):
        with self.storage.connection() as db:
            if db.execute("SELECT 1 FROM sessions WHERE id=?", (state["sid"],)).fetchone():
                db.execute(
                    "INSERT INTO capture_runs VALUES(?,?,?,?) ON CONFLICT(id) "
                    "DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                    (state["id"], state["sid"], json.dumps(state), now()),
                )

    def last_capture(self):
        with self.storage.connection() as db:
            row = db.execute(
                "SELECT payload FROM capture_runs ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            return json.loads(row[0]) if row else None
