"""Relational discovery repository; all writes are invoked under Service.lock."""

import json
from uuid import uuid4

from . import spoken_questions, topic_storage
from .analysis_state import empty_memory, reconcile
from .models import DomainError
from .storage import now
from .topics import normalize_intent


def uid():
    return str(uuid4())


def require(db, table, key):
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise DomainError("not_found", "Record not found", 404)
    return dict(row)


class Discovery:
    def __init__(self, storage):
        self.storage = storage

    def workspaces(self):
        with self.storage.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM workspaces ORDER BY created_at, id")]

    def create_workspace(self, name):
        with self.storage.connection() as db:
            wid = uid()
            db.execute(
                "INSERT INTO workspaces(id,name,created_at) VALUES (?, ?, ?)",
                (wid, name.strip(), now()),
            )
            return require(db, "workspaces", wid)

    def preferences(self, mid, revision, interval=None, archived=None):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            meeting = require(db, "meetings", mid)
            if meeting["context_version"] != revision:
                raise DomainError("conflict", "Meeting changed. Refresh and retry.")
            if archived is False and require(db, "workspaces", meeting["workspace_id"])["archived"]:
                raise DomainError(
                    "workspace_archived", "Restore the workspace before restoring this meeting."
                )
            if (
                archived
                and db.execute(
                    "SELECT 1 FROM sessions WHERE meeting_id=? AND status='live'", (mid,)
                ).fetchone()
            ):
                raise DomainError("conflict", "Stop the meeting before archiving it.")
            db.execute(
                "UPDATE meetings SET question_interval=?, archived=?, "
                "context_version=context_version+1, updated_at=? WHERE id=?",
                (
                    meeting["question_interval"] if interval is None else interval,
                    meeting["archived"] if archived is None else int(archived),
                    now(),
                    mid,
                ),
            )
            return require(db, "meetings", mid)

    def question_allowed(self, sid):
        with self.storage.connection() as db:
            row = db.execute(
                "SELECT m.question_interval FROM meetings m JOIN sessions s ON "
                "s.meeting_id=m.id WHERE s.id=?",
                (sid,),
            ).fetchone()
            interval = row[0]
            if not interval:
                return False
            latest = db.execute(
                "SELECT MAX(created_at) FROM questions WHERE session_id=?", (sid,)
            ).fetchone()[0]
            if latest:
                from datetime import datetime

                return (
                    datetime.fromisoformat(now()) - datetime.fromisoformat(latest)
                ).total_seconds() >= interval
            return True

    def meetings(self, wid):
        with self.storage.connection() as db:
            require(db, "workspaces", wid)
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM meetings WHERE workspace_id=? ORDER BY updated_at DESC, id",
                    (wid,),
                )
            ]

    def create(self, wid, title):
        return self.storage.create(title, wid, draft=True)

    def context(self, sid):
        with self.storage.connection() as db:
            session = require(db, "sessions", sid)
            meeting = require(db, "meetings", session["meeting_id"])
            brief = db.execute(
                (
                    "SELECT payload FROM meeting_briefs WHERE meeting_id=? ORDER BY revision "
                    "DESC LIMIT 1"
                ),
                (meeting["id"],),
            ).fetchone()
            notes = [
                dict(r)
                for r in db.execute(
                    (
                        "SELECT id,body,revision FROM notes WHERE meeting_id=? ORDER BY "
                        "created_at DESC LIMIT 10"
                    ),
                    (meeting["id"],),
                )
            ]
            questions = [
                dict(r)
                for r in db.execute(
                    (
                        "SELECT id,text,CASE WHEN discarded=1 THEN 'discarded' "
                        "ELSE status END AS status FROM questions WHERE session_id=? ORDER BY "
                        "created_at DESC LIMIT 30"
                    ),
                    (sid,),
                )
            ]
            return {
                "version": meeting["context_version"],
                "brief": json.loads(brief[0]),
                "notes": notes,
                "previous_questions": questions,
                "participants": json.loads(row[0])
                if (
                    row := db.execute(
                        "SELECT payload FROM meeting_participants WHERE meeting_id=?",
                        (meeting["id"],),
                    ).fetchone()
                )
                else [],
            }

    def detail(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            meeting = require(db, "meetings", mid)
            session = db.execute(
                (
                    "SELECT * FROM sessions WHERE meeting_id=? ORDER BY created_at DESC, id "
                    "DESC LIMIT 1"
                ),
                (mid,),
            ).fetchone()
            sid = session["id"] if session else None
            brief_row = db.execute(
                "SELECT * FROM meeting_briefs WHERE meeting_id=? ORDER BY revision DESC LIMIT 1",
                (mid,),
            ).fetchone()
            questions = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM questions WHERE session_id=? ORDER BY created_at, id", (sid,)
                )
            ]
            for q in questions:
                q["needs_review"] = not topic_storage.current_attribution(db, sid, q["run_id"])
                if q["discarded"]:
                    q["status"] = "discarded"
                q["evidence"] = self.evidence(db, "question", q["id"])
            run = db.execute(
                "SELECT id,input_version,context_version,output_json FROM analysis_runs "
                "WHERE session_id=? AND json_extract(output_json,'$.stale')=0 "
                "AND json_extract(output_json,'$.error')='' "
                "AND COALESCE(json_extract(input_json,'$.attribution_version'),0)="
                "(SELECT attribution_version FROM sessions WHERE id=analysis_runs.session_id) "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (sid,),
            ).fetchone()
            findings = []
            if run:
                findings = [
                    dict(r)
                    for r in db.execute("SELECT * FROM findings WHERE run_id=?", (run["id"],))
                ]
                for f in findings:
                    f["evidence"] = self.evidence(db, "finding", f["id"])
            state_row = db.execute(
                "SELECT payload FROM analysis_state WHERE session_id=?", (sid,)
            ).fetchone()
            memory = reconcile(
                json.loads(state_row[0]) if state_row else empty_memory(),
                {
                    "session": dict(session) if session else {},
                    "segments": [
                        json.loads(r[0])
                        for r in db.execute(
                            "SELECT payload FROM segments WHERE session_id=?", (sid,)
                        )
                    ],
                },
            )
            overview = memory.get("overview", {})
            return {
                "meeting": meeting,
                "session": dict(session) if session else None,
                "brief": json.loads(brief_row["payload"]),
                "brief_revision": brief_row["revision"],
                "questions": questions,
                "spoken_questions": spoken_questions.view(db, sid),
                "findings": findings,
                "workflows": memory.get("workflows", []),
                "overview": overview.get("summary")
                or (
                    json.loads(run["output_json"]).get("suggestion", {}).get("summary", "")
                    if run
                    else ""
                ),
                "overview_input_version": overview.get(
                    "input_version", run["input_version"] if run else None
                ),
                "overview_context_version": overview.get(
                    "context_version", run["context_version"] if run else None
                ),
                "notes": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM notes WHERE meeting_id=? ORDER BY created_at", (mid,)
                    )
                ],
            }

    @staticmethod
    def evidence(db, kind, key):
        rows = db.execute(
            f"""SELECT e.segment_id,e.revision,r.payload,
          CASE WHEN s.revision=e.revision THEN 0 ELSE 1 END AS superseded
          FROM {kind}_evidence e JOIN segment_revisions r USING(session_id,segment_id,revision)
          LEFT JOIN segments s USING(session_id,segment_id)
          WHERE e.{kind}_id=?""",
            (key,),
        ).fetchall()
        return [{**json.loads(r["payload"]), "superseded": bool(r["superseded"])} for r in rows]

    def save_brief(self, mid, revision, brief):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "meetings", mid)
            current = db.execute(
                "SELECT MAX(revision) FROM meeting_briefs WHERE meeting_id=?", (mid,)
            ).fetchone()[0]
            if current != revision:
                raise DomainError("conflict", "Meeting brief changed. Reload before saving.")
            db.execute(
                "INSERT INTO meeting_briefs VALUES (?, ?, ?, ?)",
                (mid, revision + 1, json.dumps(brief), now()),
            )
            db.execute(
                (
                    "UPDATE meetings SET "
                    "title=?,context_version=context_version+1,updated_at=? WHERE id=?"
                ),
                (brief["title"], now(), mid),
            )
            db.execute("UPDATE sessions SET title=? WHERE meeting_id=?", (brief["title"], mid))
        return self.detail(mid)

    def note(self, mid, body, nid=None, revision=0):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "meetings", mid)
            if nid:
                old = require(db, "notes", nid)
                if old["meeting_id"] != mid:
                    raise DomainError("not_found", "Note not found", 404)
                if old["revision"] != revision:
                    raise DomainError("conflict", "Note changed. Reload before saving.")
                revision += 1
                db.execute(
                    "UPDATE notes SET body=?,revision=?,updated_at=? WHERE id=?",
                    (body, revision, now(), nid),
                )
            else:
                nid = uid()
                db.execute(
                    "INSERT INTO notes VALUES (?, ?, ?, 0, ?, ?)", (nid, mid, body, now(), now())
                )
            db.execute(
                "INSERT INTO note_revisions VALUES (?, ?, ?, ?)", (nid, revision, body, now())
            )
            db.execute(
                "UPDATE meetings SET context_version=context_version+1,updated_at=? WHERE id=?",
                (now(), mid),
            )
            return require(db, "notes", nid)

    def question_status(self, mid, qid, revision, status):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            q = require(db, "questions", qid)
            session = require(db, "sessions", q["session_id"])
            if session["meeting_id"] != mid:
                raise DomainError("not_found", "Question not found", 404)
            if q["revision"] != revision:
                raise DomainError("conflict", "Question changed. Reload and try again.")
            if ("discarded" if q["discarded"] else q["status"]) != status:
                db.execute(
                    "UPDATE questions SET status=?, discarded=?, "
                    "revision=revision+1,updated_at=? WHERE id=?",
                    (
                        q["status"] if status == "discarded" else status,
                        int(status == "discarded"),
                        now(),
                        qid,
                    ),
                )
                db.execute(
                    "INSERT INTO question_status_events VALUES (?, ?, ?, ?)",
                    (uid(), qid, status, now()),
                )
                db.execute(
                    "UPDATE meetings SET context_version=context_version+1 WHERE id=?", (mid,)
                )
            result = require(db, "questions", qid)
            if result["discarded"]:
                result["status"] = "discarded"
            return result

    def topic_catalog(self, sid, context, memory):
        with self.storage.connection() as db:
            require(db, "sessions", sid)
            return topic_storage.catalog(db, sid, context, memory)

    def record_run(self, sid, context, provider, run, memory=None):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "sessions", sid)
            rid = context.get("job_id") or uid()
            if db.execute("SELECT 1 FROM analysis_runs WHERE id=?", (rid,)).fetchone():
                # Failed attempts retain their audit record; a successful retry is a new
                # attempt, while replaying an accepted job must not apply its patch twice.
                prior = db.execute(
                    "SELECT output_json FROM analysis_runs WHERE id=?", (rid,)
                ).fetchone()
                previous = json.loads(prior[0])
                if not previous["stale"] and not previous["error"]:
                    return
                rid = uid()
            if memory is not None:
                db.execute(
                    "INSERT INTO analysis_state VALUES (?, ?) ON CONFLICT(session_id) "
                    "DO UPDATE SET payload=excluded.payload",
                    (sid, json.dumps(memory)),
                )
            db.execute(
                "INSERT INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    sid,
                    run["input_version"],
                    context["meeting"]["version"],
                    provider,
                    run["model"],
                    run["prompt_version"],
                    json.dumps(context),
                    json.dumps(run),
                    now(),
                ),
            )
            if run["stale"] or run["error"] or not run["suggestion"]:
                return
            result = run["suggestion"]
            refs = run["source_revisions"]
            spoken_questions.persist(db, sid, rid, result, context, now())

            def link(kind, key, ids):
                for source in set(ids):
                    db.execute(
                        f"INSERT INTO {kind}_evidence VALUES (?, ?, ?, ?)",
                        (key, sid, source, refs[source]),
                    )

            if context.get("strategy") == "topics-v1":
                topic_storage.persist(db, sid, rid, context, result, memory)
            duplicate = context.get("strategy") == "topics-v1" and topic_storage.duplicate_intent(
                db, sid, result
            )
            if result["question"] and not duplicate:
                qid = uid()
                inserted = db.execute(
                    "INSERT OR IGNORE INTO "
                    "questions(id,session_id,run_id,text,normalized,rationale,"
                    "status,revision,created_at,updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)",
                    (
                        qid,
                        sid,
                        rid,
                        result["question"],
                        " ".join(result["question"].casefold().split()),
                        result["rationale"],
                        now(),
                        now(),
                    ),
                ).rowcount
                if inserted:
                    link("question", qid, result["source_ids"])
                    if context.get("strategy") == "topics-v1":
                        db.execute(
                            "INSERT INTO question_topics VALUES (?,?,?,?)",
                            (
                                qid,
                                result["topic"]["focus_id"],
                                sid,
                                normalize_intent(result["topic"]["question_intent"]),
                            ),
                        )
            for finding in result.get("findings", []):
                fid = uid()
                db.execute(
                    "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fid,
                        sid,
                        rid,
                        finding["kind"],
                        finding["title"],
                        finding["body"],
                        finding["basis"],
                        now(),
                        finding.get("topic_id", ""),
                        finding.get("workflow_key", ""),
                    ),
                )
                link("finding", fid, finding["source_ids"])

    def memory(self, sid):
        with self.storage.connection() as db:
            require(db, "sessions", sid)
            row = db.execute(
                "SELECT payload FROM analysis_state WHERE session_id=?", (sid,)
            ).fetchone()
            return json.loads(row[0]) if row else empty_memory()

    def reset(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            meeting = require(db, "meetings", mid)
            if meeting["archived"]:
                raise DomainError("conflict", "Restore the meeting before resetting it.")
            self._clear_runs(db, mid)
            db.execute("UPDATE meetings SET updated_at=? WHERE id=?", (now(), mid))
        return self.detail(mid)

    def _clear_runs(self, db, mid):
        sessions = [r[0] for r in db.execute("SELECT id FROM sessions WHERE meeting_id=?", (mid,))]
        for sid in sessions:
            self.storage.archive.preserve(db, sid)
            db.execute("DELETE FROM topics WHERE session_id=?", (sid,))
            for kind in ("question", "finding"):
                db.execute(f"DELETE FROM {kind}_evidence WHERE session_id=?", (sid,))
            db.execute(
                (
                    "DELETE FROM question_status_events WHERE question_id IN (SELECT id FROM "
                    "questions WHERE session_id=?)"
                ),
                (sid,),
            )
            for table in (
                "spoken_questions",
                "speaker_assignments",
                "speaker_spans",
                "speaker_tracks",
                "questions",
                "findings",
                "analysis_runs",
                "experiments",
                "seen_events",
                "segments",
                "segment_revisions",
            ):
                db.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))

    def _delete_meeting(self, db, mid):
        self._clear_runs(db, mid)
        db.execute(
            "DELETE FROM note_revisions WHERE note_id IN (SELECT id FROM notes WHERE meeting_id=?)",
            (mid,),
        )
        for table in ("notes", "meeting_briefs"):
            db.execute(f"DELETE FROM {table} WHERE meeting_id=?", (mid,))
        db.execute("DELETE FROM meetings WHERE id=?", (mid,))
