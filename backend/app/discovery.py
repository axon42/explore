"""Relational discovery repository; all writes are invoked under Service.lock."""

import json
from uuid import uuid4

from .models import DomainError
from .storage import now


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
            db.execute("INSERT INTO workspaces VALUES (?, ?, ?)", (wid, name.strip(), now()))
            return require(db, "workspaces", wid)

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
        return self.storage.create(title, wid)

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
                        "SELECT id,text,status FROM questions WHERE session_id=? ORDER BY "
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
            sid = session["id"]
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
                q["evidence"] = self.evidence(db, "question", q["id"])
            run = db.execute(
                "SELECT id,input_version,context_version,output_json FROM analysis_runs "
                "WHERE session_id=? AND json_extract(output_json,'$.stale')=0 "
                "AND json_extract(output_json,'$.error')='' "
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
            return {
                "meeting": meeting,
                "session": dict(session),
                "brief": json.loads(brief_row["payload"]),
                "brief_revision": brief_row["revision"],
                "questions": questions,
                "findings": findings,
                "overview": json.loads(run["output_json"]).get("suggestion", {}).get("summary", "")
                if run
                else "",
                "overview_input_version": run["input_version"] if run else None,
                "overview_context_version": run["context_version"] if run else None,
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
            if q["status"] != status:
                db.execute(
                    "UPDATE questions SET status=?, revision=revision+1,updated_at=? WHERE id=?",
                    (status, now(), qid),
                )
                db.execute(
                    "INSERT INTO question_status_events VALUES (?, ?, ?, ?)",
                    (uid(), qid, status, now()),
                )
                db.execute(
                    "UPDATE meetings SET context_version=context_version+1 WHERE id=?", (mid,)
                )
            return require(db, "questions", qid)

    def record_run(self, sid, context, provider, run):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "sessions", sid)
            rid = uid()
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

            def link(kind, key, ids):
                for source in set(ids):
                    db.execute(
                        f"INSERT INTO {kind}_evidence VALUES (?, ?, ?, ?)",
                        (key, sid, source, refs[source]),
                    )

            if result["question"]:
                qid = uid()
                inserted = db.execute(
                    "INSERT OR IGNORE INTO questions VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)",
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
            for finding in result.get("findings", []):
                fid = uid()
                db.execute(
                    "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fid,
                        sid,
                        rid,
                        finding["kind"],
                        finding["title"],
                        finding["body"],
                        finding["basis"],
                        now(),
                    ),
                )
                link("finding", fid, finding["source_ids"])

    def reset(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            meeting = require(db, "meetings", mid)
            self._clear_runs(db, mid)
            sid = uid()
            db.execute(
                (
                    "INSERT INTO sessions(id,title,status,created_at,meeting_id) VALUES "
                    "(?,?,'live',?,?)"
                ),
                (sid, meeting["title"], now(), mid),
            )
            db.execute("UPDATE meetings SET updated_at=? WHERE id=?", (now(), mid))
        return self.detail(mid)

    @staticmethod
    def _clear_runs(db, mid):
        sessions = [r[0] for r in db.execute("SELECT id FROM sessions WHERE meeting_id=?", (mid,))]
        for sid in sessions:
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

    def clear_workspace(self, wid):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "workspaces", wid)
            for row in db.execute(
                "SELECT id FROM meetings WHERE workspace_id=?", (wid,)
            ).fetchall():
                mid = row[0]
                self._clear_runs(db, mid)
                db.execute(
                    (
                        "DELETE FROM note_revisions WHERE note_id IN (SELECT id FROM notes WHERE "
                        "meeting_id=?)"
                    ),
                    (mid,),
                )
                for table in ("notes", "meeting_briefs"):
                    db.execute(f"DELETE FROM {table} WHERE meeting_id=?", (mid,))
                db.execute("DELETE FROM meetings WHERE id=?", (mid,))
        return {"status": "cleared"}
