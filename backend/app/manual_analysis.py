"""Full-input construction and durable manual receipts; no provider calls or scheduling."""

import hashlib
import json

from .analysis_state import analysis_segments
from .discovery import require
from .models import DomainError
from .storage import now
from .topic_storage import read_topics
from .topics import topic_state

# Application request envelope, not a claim about a model's tokenizer/context window.
MAX_REQUEST_BYTES = 1_000_000


def fingerprint(snapshot, meeting, preferences):
    value = {
        "sources": [
            (s["segment_id"], s["revision"]) for s in snapshot["segments"] if s["is_final"]
        ],
        "attribution": snapshot["session"].get("attribution_version", 0),
        "context": meeting["version"],
        "reasoning": preferences,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def full_context(snapshot, meeting, memory, objective):
    segments = analysis_segments([s for s in snapshot["segments"] if s["is_final"]])
    return {
        "attribution_version": snapshot["session"].get("attribution_version", 0),
        "objective": meeting["brief"].get("objective") or objective,
        "meeting": meeting,
        "segments": segments,
        "new_source_ids": [s["segment_id"] for s in segments],
        "memory": {k: memory[k] for k in ("claims", "matches", "workflows")},
        "base_state_version": memory["version"],
        "input_version": snapshot["version"],
        "scheduling_mode": "manual",
        "scope": "full-transcript",
    }


class ManualAnalysis:
    def __init__(self, storage):
        self.storage = storage

    def settings(self, sid, writable=False):
        with self.storage.connection() as db:
            session = require(db, "sessions", sid)
            meeting = require(db, "meetings", session["meeting_id"])
            if writable:
                workspace = require(db, "workspaces", meeting["workspace_id"])
                latest = db.execute(
                    "SELECT id FROM sessions WHERE meeting_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT 1",
                    (meeting["id"],),
                ).fetchone()
                if latest[0] != sid or meeting["archived"] or workspace["archived"]:
                    raise DomainError(
                        "analysis_unavailable",
                        "Restore and open the current meeting before analyzing.",
                    )
            return {"mode": meeting["analysis_schedule"], "revision": meeting["schedule_revision"]}

    def update(self, sid, mode, revision):
        self.settings(sid, True)
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE meetings SET analysis_schedule=?,schedule_revision=schedule_revision+1 "
                "WHERE id=(SELECT meeting_id FROM sessions WHERE id=?) AND schedule_revision=?",
                (mode, sid, revision),
            ).rowcount
            if not changed:
                raise DomainError(
                    "conflict", "Analysis scheduling changed in another tab. Refresh and retry."
                )
        return self.settings(sid)

    def receipt(self, sid, job_id=None):
        with self.storage.connection() as db:
            if job_id:
                row = db.execute(
                    "SELECT * FROM manual_analysis_jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row and row["session_id"] != sid:
                    raise DomainError("not_found", "Analysis request not found", 404)
            else:
                row = db.execute(
                    "SELECT * FROM manual_analysis_jobs WHERE session_id=? ORDER BY "
                    "rowid DESC LIMIT 1",
                    (sid,),
                ).fetchone()
            return {k: row[k] for k in row.keys() if k != "input_json"} if row else None

    def final_attempts(self, sid):
        with self.storage.connection() as db:
            return db.execute(
                "SELECT count(*) FROM manual_analysis_jobs WHERE session_id=? "
                "AND json_extract(input_json,'$.review_kind')='final'",
                (sid,),
            ).fetchone()[0]

    def begin(self, sid, context, state):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO "
                "manual_analysis_jobs(id,session_id,fingerprint,status,created_at,input_json) "
                "VALUES(?,?,?,'running',?,?)",
                (context["job_id"], sid, context["input_fingerprint"], now(), json.dumps(context)),
            )
            # Allowance reservation and receipt are one durable transaction, before provider I/O.
            db.execute(
                "INSERT INTO experiments VALUES (?,?) ON CONFLICT(session_id) DO UPDATE "
                "SET payload=excluded.payload",
                (sid, json.dumps(state)),
            )

    def interrupt(self, sid, job_id, message="Analysis interrupted. Retry explicitly."):
        with self.storage.connection() as db:
            db.execute(
                "UPDATE manual_analysis_jobs SET status='interrupted',error=? WHERE id=? "
                "AND session_id=? AND status='running'",
                (message, job_id, sid),
            )

    def catalog(self, sid, context, memory):
        with self.storage.connection() as db:
            topics = read_topics(db, sid, context["segments"], topic_state(memory))
            questions = [
                dict(r)
                for r in db.execute(
                    "SELECT qt.topic_id,qt.intent,q.id,CASE WHEN q.discarded=1 THEN "
                    "'discarded' ELSE q.status END AS status "
                    "FROM question_topics qt JOIN questions q ON q.id=qt.question_id "
                    "WHERE qt.session_id=? ORDER BY q.created_at,q.id",
                    (sid,),
                )
            ]
        return {
            "focus_id": topic_state(memory).get("focus_id", ""),
            "index": [{"id": t["id"], "title": t["title"]} for t in topics],
            "details": [
                {
                    "id": t["id"],
                    "summary": t["summary"],
                    "summary_sources": t["summary_sources"],
                    "needs_review": t["needs_review"],
                    "questions_complete": True,
                }
                for t in topics
            ],
            "questions": questions,
            "omitted_topics": 0,
            "evidence": [],
        }
