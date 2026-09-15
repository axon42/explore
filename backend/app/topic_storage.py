"""SQLite topic projections, written inside the owning analysis transaction."""

import json
import re

from .analysis_state import analysis_segments
from .speakers import resolved
from .topics import normalize_intent, topic_state


def current_attribution(db, sid, run_id):
    return bool(
        db.execute(
            "SELECT 1 FROM analysis_runs r JOIN sessions s ON s.id=r.session_id "
            "WHERE r.id=? AND s.id=? "
            "AND COALESCE(json_extract(r.input_json,'$.attribution_version'),0)"
            "=s.attribution_version",
            (run_id, sid),
        ).fetchone()
    )


DDL = [
    """CREATE TABLE topics(
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        title TEXT NOT NULL, summary TEXT NOT NULL, summary_sources TEXT NOT NULL,
        revision INTEGER NOT NULL, run_id TEXT NOT NULL,
        UNIQUE(id,session_id),
        FOREIGN KEY(run_id,session_id) REFERENCES analysis_runs(id,session_id))""",
    """CREATE TABLE topic_evidence(
        topic_id TEXT NOT NULL, session_id TEXT NOT NULL, segment_id TEXT NOT NULL,
        revision INTEGER NOT NULL, assignment TEXT NOT NULL
        CHECK(assignment IN ('accepted','provisional')),
        PRIMARY KEY(topic_id,segment_id,revision),
        FOREIGN KEY(topic_id,session_id) REFERENCES topics(id,session_id) ON DELETE CASCADE,
        FOREIGN KEY(session_id,segment_id,revision)
        REFERENCES segment_revisions(session_id,segment_id,revision))""",
    """CREATE TABLE topic_artifacts(
        topic_id TEXT NOT NULL, session_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('claim','workflow')), artifact_key TEXT NOT NULL,
        PRIMARY KEY(topic_id,kind,artifact_key),
        FOREIGN KEY(topic_id,session_id) REFERENCES topics(id,session_id) ON DELETE CASCADE)""",
    """CREATE TABLE question_topics(
        question_id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, session_id TEXT NOT NULL,
        intent TEXT NOT NULL CHECK(length(intent)>0), UNIQUE(session_id,topic_id,intent),
        FOREIGN KEY(question_id,session_id) REFERENCES questions(id,session_id) ON DELETE CASCADE,
        FOREIGN KEY(topic_id,session_id) REFERENCES topics(id,session_id) ON DELETE CASCADE)""",
    "CREATE INDEX topics_session ON topics(session_id)",
    "CREATE INDEX topic_evidence_session ON topic_evidence(session_id,segment_id)",
]


def read_topics(db, sid, segments, state):
    """Complete reconciled view for reports, independent of LLM context limits."""
    current = {s["segment_id"]: s["revision"] for s in segments if s["is_final"]}
    focus = state.get("focus_id", "")
    result = []
    for row in db.execute("SELECT * FROM topics WHERE session_id=? ORDER BY rowid", (sid,)):
        topic = dict(row)
        sources = json.loads(topic.pop("summary_sources"))
        topic["needs_review"] = not current_attribution(db, sid, topic["run_id"]) or not all(
            current.get(k) == v for k, v in sources.items()
        )
        if topic["needs_review"]:
            topic["summary"] = ""
        topic["summary_sources"] = sources
        topic["status"] = "active" if topic["id"] == focus else "paused"
        topic["evidence"] = [
            {**dict(r), "superseded": current.get(r["segment_id"]) != r["revision"]}
            for r in db.execute(
                "SELECT segment_id,revision,assignment FROM topic_evidence "
                "WHERE topic_id=? AND session_id=? ORDER BY rowid",
                (topic["id"], sid),
            )
        ]
        topic["provisional"] = not any(e["assignment"] == "accepted" for e in topic["evidence"])
        result.append(topic)
    return result


def catalog(db, sid, context, memory):
    """Retrieve a compact index, focus and at most two candidate details, with exact evidence."""
    focus = topic_state(memory).get("focus_id", "")
    text = " ".join(
        s["text"] for s in context["segments"] if s["segment_id"] in context["new_source_ids"]
    )
    words = list(dict.fromkeys(re.findall(r"\w{4,}", text.casefold())))[:20]
    score = " + ".join("(instr(lower(title),?)>0)" for _ in words) or "0"
    rows = db.execute(
        "SELECT * FROM topics WHERE session_id=? ORDER BY (id=?) DESC, "
        f"({score}) DESC, rowid DESC LIMIT 40",
        (sid, focus, *words),
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM topics WHERE session_id=?", (sid,)).fetchone()[0]
    segments = {
        r["segment_id"]: json.loads(r["payload"])
        for r in db.execute("SELECT segment_id,payload FROM segments WHERE session_id=?", (sid,))
    }
    segments = {s["segment_id"]: s for s in resolved(db, sid, list(segments.values()))}
    details, evidence, questions = [], {}, []
    evidence_budget = 8000
    for row in rows[:3]:
        sources = json.loads(row["summary_sources"])
        valid = current_attribution(db, sid, row["run_id"]) and all(
            k in segments and segments[k]["is_final"] and segments[k]["revision"] == v
            for k, v in sources.items()
        )
        history = [
            dict(r)
            for r in db.execute(
                "SELECT qt.topic_id,qt.intent,q.id,CASE WHEN q.discarded=1 THEN 'discarded' "
                "ELSE q.status END AS status FROM question_topics qt JOIN questions q "
                "ON q.id=qt.question_id WHERE qt.topic_id=? AND qt.session_id=? "
                "ORDER BY q.created_at DESC,q.id LIMIT 31",
                (row["id"], sid),
            )
        ]
        questions.extend(history[:30])
        details.append(
            {
                "id": row["id"],
                "summary": row["summary"] if valid else "",
                "summary_sources": sources,
                "needs_review": not valid,
                "questions_complete": len(history) <= 30 and valid,
            }
        )
        # Summary sources first; then recent accepted evidence. Never trim quoted passages.
        refs = list(sources) + [
            r[0]
            for r in db.execute(
                "SELECT segment_id FROM topic_evidence WHERE topic_id=? AND session_id=? "
                "AND assignment='accepted' ORDER BY rowid DESC LIMIT 10",
                (row["id"], sid),
            )
        ]
        for key in refs:
            item = segments.get(key)
            if (
                item
                and item["is_final"]
                and key not in evidence
                and len(item["text"]) <= evidence_budget
            ):
                evidence[key] = item
                evidence_budget -= len(item["text"])
    return {
        "focus_id": focus,
        "index": [{"id": r["id"], "title": r["title"]} for r in rows],
        "omitted_topics": max(0, total - len(rows)),
        "details": details,
        "questions": questions,
        "evidence": analysis_segments(list(evidence.values())),
    }


def persist(db, sid, run_id, context, result, memory):
    refs = {s["segment_id"]: s["revision"] for s in context["segments"]}
    for update in result["topic"]["updates"]:
        old = db.execute(
            "SELECT session_id FROM topics WHERE id=?", (update["topic_id"],)
        ).fetchone()
        if old and old[0] != sid:
            raise ValueError("Topic belongs to another session")
        db.execute(
            "INSERT INTO topics VALUES (?,?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET "
            "title=excluded.title,summary=excluded.summary,summary_sources=excluded.summary_sources,"
            "revision=topics.revision+1,run_id=excluded.run_id",
            (
                update["topic_id"],
                sid,
                update["title"],
                update["summary"],
                json.dumps({k: refs[k] for k in update["source_ids"]}),
                run_id,
            ),
        )
        for key in set(update["source_ids"]):
            db.execute(
                "INSERT INTO topic_evidence VALUES (?,?,?,?,?) ON CONFLICT DO UPDATE SET "
                "assignment=excluded.assignment",
                (update["topic_id"], sid, key, refs[key], update["assignment"]),
            )
    # Routing itself links the latest passage when resuming without a summary change.
    topic = result["topic"]
    if topic["action"] != "uncertain":
        for key in set(topic["source_ids"]):
            db.execute(
                "INSERT INTO topic_evidence VALUES (?,?,?,?,'accepted') "
                "ON CONFLICT DO UPDATE SET assignment='accepted'",
                (topic["focus_id"], sid, key, refs[key]),
            )
    db.execute("DELETE FROM topic_artifacts WHERE session_id=?", (sid,))
    for field, kind in (("claims", "claim"), ("workflows", "workflow")):
        for item in memory[field]:
            if item.get("topic_id"):
                db.execute(
                    "INSERT INTO topic_artifacts VALUES (?,?,?,?)",
                    (item["topic_id"], sid, kind, item["key"]),
                )


def duplicate_intent(db, sid, result):
    topic = result["topic"]
    return db.execute(
        "SELECT 1 FROM question_topics WHERE session_id=? AND topic_id=? AND intent=?",
        (sid, topic["focus_id"], normalize_intent(topic["question_intent"])),
    ).fetchone()
