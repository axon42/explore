"""Evidence snapshots, structured reports and deterministic, escaped exports."""

import hashlib
import html
import json
from uuid import uuid4

from .analysis_state import empty_memory, reconcile
from .discovery import Discovery, require
from .models import DomainError
from .storage import now
from .topic_storage import read_topics

SECTIONS = (
    ("people", "People and meeting"),
    ("purpose", "Purpose"),
    ("summary", "Discussion summary"),
    ("workflows", "Workflows"),
    ("pain_impact", "Pain and impact"),
    ("alternatives", "Current alternatives"),
    ("opportunities", "Opportunities and uncertainty"),
    ("questions", "Question progress"),
    ("next_steps", "Next steps"),
    ("evidence_notes", "Evidence and human notes"),
)


def safe_text(value):
    """Plain text embedded in Markdown, never executable HTML/links/code fences."""
    text = html.escape(str(value), quote=True)
    for char in "\\`*_{}[]()#+-.!|>":
        text = text.replace(char, "\\" + char)
    return text


def diagram(workflow):
    lines = ["flowchart TD"]
    for i, step in enumerate(workflow["steps"]):
        # Numeric entities keep user/model labels out of Mermaid syntax entirely.
        label = "".join(f"#{ord(c)};" for c in step["label"])
        lines.append(f'  n{i}["{label}"]')
    for i, refs in enumerate(workflow["transitions"]):
        edge = "-->" if refs else '-. "order unknown" .->'
        lines.append(f"  n{i} {edge} n{i + 1}")
    return "\n".join(lines)


class ReportStrategy:
    """Pure synthesis over accepted state; swappable without storage/model coupling."""

    def build(self, source, provider):
        memory = source["memory"]
        sections = {key: [] for key, _ in SECTIONS}
        sections["people"] = source["participants"]
        sections["purpose"] = [{"origin": "human_brief", "brief": source["brief"]}]
        for claim in memory["claims"]:
            sections[claim["section"]].append(claim)
        sections["summary"] = memory["claims"][:8]
        sections["questions"] = source["questions"]
        sections["evidence_notes"] = source["notes"]
        topics = source.get("topics", [])
        topic_titles = {t["id"]: t["title"] for t in topics}
        return {
            "schema_version": 2 if topics else 1,
            "topics": topics,
            "meeting": source["meeting"],
            "session": source["session"],
            "duration_ms": max((s["end_ms"] for s in source["segments"]), default=0),
            "provider": provider,
            "simulated": provider == "mock",
            "strategy_version": "evidence-report-v2" if topics else "evidence-report-v1",
            "generated_at": now(),
            "sections": [
                {
                    "key": k,
                    "title": title,
                    "items": sections[k],
                    "empty_text": "Not established",
                    "topic_groups": [
                        {
                            "topic_id": tid,
                            "title": topic_titles.get(tid, "Unassigned"),
                            "items": [
                                item for item in sections[k] if item.get("topic_id", "") == tid
                            ],
                        }
                        for tid in dict.fromkeys(item.get("topic_id", "") for item in sections[k])
                    ]
                    if topics
                    else [],
                }
                for k, title in SECTIONS
            ],
            "workflows": [{**w, "mermaid": diagram(w)} for w in memory["workflows"]],
            "question_matches": memory["matches"],
            "evidence": source["segments"],
            "coverage": {
                "final_segments": sum(s["is_final"] for s in source["segments"]),
                "processed_segments": len(memory["coverage"]),
                "provisional_segments": sum(not s["is_final"] for s in source["segments"]),
                "input_version": source["session"]["version"],
                "context_version": source["meeting"]["context_version"],
                "source_scope": "Received and accepted transcript only",
            },
            "analysis_provenance": source["analysis_provenance"],
        }


class Reports:
    def __init__(self, storage, strategy=None):
        self.storage = storage
        self.strategy = strategy or ReportStrategy()

    def participants(self, mid, revision=None, participants=None):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE" if participants is not None else "BEGIN")
            require(db, "meetings", mid)
            row = db.execute(
                "SELECT * FROM meeting_participants WHERE meeting_id=?", (mid,)
            ).fetchone()
            current = row["revision"] if row else 0
            if participants is not None:
                if current != revision:
                    raise DomainError("conflict", "Participants changed. Reload before saving.")
                current += 1
                db.execute(
                    "INSERT INTO meeting_participants VALUES (?, ?, ?) "
                    "ON CONFLICT(meeting_id) DO UPDATE SET revision=excluded.revision, "
                    "payload=excluded.payload",
                    (mid, current, json.dumps(participants)),
                )
                db.execute(
                    "UPDATE meetings SET context_version=context_version+1 WHERE id=?", (mid,)
                )
            else:
                participants = json.loads(row["payload"]) if row else []
            return {"revision": current, "participants": participants}

    def snapshot(self, db, sid):
        session = require(db, "sessions", sid)
        meeting = require(db, "meetings", session["meeting_id"])
        mid = meeting["id"]
        segments = [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM segments WHERE session_id=?", (sid,))
        ]
        segments.sort(key=lambda s: (s["start_ms"], s["segment_id"]))
        row = db.execute("SELECT payload FROM analysis_state WHERE session_id=?", (sid,)).fetchone()
        memory = reconcile(json.loads(row[0]) if row else empty_memory(), {"segments": segments})
        row = db.execute(
            "SELECT payload FROM meeting_participants WHERE meeting_id=?", (mid,)
        ).fetchone()
        participants = json.loads(row[0]) if row else []
        mapped = {p["speaker_id"] for p in participants}
        for s in segments:
            if s["speaker_id"] not in mapped:
                participants.append(
                    {
                        "speaker_id": s["speaker_id"],
                        "name": s.get("speaker_name") or "Not established",
                        "interview_role": "unknown",
                        "job_role": "Not established",
                        "origin": "transcript_label",
                    }
                )
                mapped.add(s["speaker_id"])
        participants.sort(key=lambda p: p["interview_role"] != "interviewer")
        brief = json.loads(
            db.execute(
                "SELECT payload FROM meeting_briefs WHERE meeting_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (mid,),
            ).fetchone()[0]
        )
        questions = [
            dict(r)
            for r in db.execute(
                "SELECT id,text,CASE WHEN discarded=1 THEN 'discarded' ELSE "
                "status END AS status,revision FROM questions WHERE session_id=? "
                "ORDER BY created_at,id",
                (sid,),
            )
        ]
        for question in questions:
            question["evidence"] = Discovery.evidence(db, "question", question["id"])
            link = db.execute(
                "SELECT topic_id,intent FROM question_topics WHERE question_id=? AND session_id=?",
                (question["id"], sid),
            ).fetchone()
            if link:
                question.update(dict(link))
        return {
            "schema_version": 1,
            "exported_at": now(),
            "meeting": meeting,
            "session": session,
            "segments": segments,
            "memory": memory,
            "topics": read_topics(db, sid, segments, memory.get("topic_state", {})),
            "participants": participants,
            "brief": brief,
            "notes": [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM notes WHERE meeting_id=? ORDER BY created_at,id", (mid,)
                )
            ],
            "questions": questions,
            "analysis_provenance": [
                dict(r)
                for r in db.execute(
                    "SELECT id,input_version,context_version,provider,model,prompt_version,"
                    "created_at "
                    "FROM analysis_runs WHERE session_id=? ORDER BY created_at,id",
                    (sid,),
                )
            ],
        }

    def current_sid(self, db, mid):
        require(db, "meetings", mid)
        return db.execute(
            "SELECT id FROM sessions WHERE meeting_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (mid,),
        ).fetchone()[0]

    def export(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            sid = self.current_sid(db, mid)
            source = self.snapshot(db, sid)
            current = {s["segment_id"]: s["revision"] for s in source["segments"]}
            revisions = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM segment_revisions WHERE session_id=? "
                    "ORDER BY segment_id,revision",
                    (sid,),
                )
            ]
            source["revisions"] = [
                {**r, "superseded": current.get(r["segment_id"]) != r["revision"]}
                for r in revisions
            ]
            source["evidence_scope"] = (
                "All accepted revisions; rejected/duplicate deliveries excluded."
            )
            return source

    def live(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            sid = self.current_sid(db, mid)
            source = self.snapshot(db, sid)
            provider = (
                source["analysis_provenance"][-1]["provider"]
                if source["analysis_provenance"]
                else "not_started"
            )
            return {
                "provider": provider,
                "simulated": provider == "mock",
                "state": source["memory"],
                "topics": source["topics"],
                "notes": self.strategy.build(source, "derived")["sections"],
            }

    def job(self, sid, status, error):
        with self.storage.connection() as db:
            require(db, "sessions", sid)
            db.execute(
                "INSERT INTO report_jobs VALUES (?, ?, ?) ON CONFLICT(session_id) "
                "DO UPDATE SET status=excluded.status,error=excluded.error",
                (sid, status, error),
            )

    def generate(self, sid, provider):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self.snapshot(db, sid)
            if source["session"]["status"] != "stopped":
                raise DomainError("conflict", "End the meeting before generating its final report.")
            finals = [s for s in source["segments"] if s["is_final"]]
            memory = source["memory"]
            if any(memory["coverage"].get(s["segment_id"]) != s["revision"] for s in finals):
                raise DomainError("incomplete_analysis", "Transcript analysis is incomplete.")
            if finals and memory["context_version"] != source["meeting"]["context_version"]:
                raise DomainError("incomplete_analysis", "Meeting context analysis is incomplete.")
            existing = db.execute(
                "SELECT id FROM reports WHERE session_id=? AND input_version=? "
                "AND context_version=?",
                (sid, source["session"]["version"], source["meeting"]["context_version"]),
            ).fetchone()
            if not existing:
                revision = db.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM reports WHERE session_id=?", (sid,)
                ).fetchone()[0]
                report = self.strategy.build(source, provider)
                report["revision"] = revision
                db.execute(
                    "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        sid,
                        revision,
                        source["session"]["version"],
                        source["meeting"]["context_version"],
                        json.dumps(report),
                        now(),
                    ),
                )
            db.execute(
                "UPDATE report_jobs SET status='complete',error='' WHERE session_id=?", (sid,)
            )

    def list(self, mid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            sid = self.current_sid(db, mid)
            meeting = require(db, "meetings", mid)
            session = require(db, "sessions", sid)
            job = db.execute(
                "SELECT status,error FROM report_jobs WHERE session_id=?", (sid,)
            ).fetchone()
            reports = [
                dict(r)
                for r in db.execute(
                    "SELECT id,revision,input_version,context_version,created_at FROM reports "
                    "WHERE session_id=? ORDER BY revision DESC",
                    (sid,),
                )
            ]
            for r in reports:
                r["outdated"] = (
                    r["context_version"] != meeting["context_version"]
                    or r["input_version"] != session["version"]
                )
            return {
                "job": dict(job) if job else {"status": "not_started", "error": ""},
                "reports": reports,
            }

    def get(self, mid, rid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            sid = self.current_sid(db, mid)
            row = db.execute(
                "SELECT payload FROM reports WHERE session_id=? AND id=?", (sid, rid)
            ).fetchone()
            if not row:
                raise DomainError("not_found", "Report not found", 404)
            return json.loads(row[0])


def transcript_markdown(source):
    lines = [
        f"# {safe_text(source['meeting']['title'])} — transcript",
        f"Session: {safe_text(source['session']['id'])}",
        "",
        "## Current transcript",
    ]
    for s in source["segments"]:
        lines.extend(
            [
                f"\n### {s['start_ms']}–{s['end_ms']} ms · "
                f"{safe_text(s.get('speaker_name') or s['speaker_id'])}",
                f"ID: {safe_text(s['segment_id'])} · revision {s['revision']} · "
                f"{'final' if s['is_final'] else 'provisional'}",
                safe_text(s["text"]),
            ]
        )
    lines.extend(["", "## Accepted revision history"])
    for s in source["revisions"]:
        lines.append(
            f"\n- {safe_text(s['segment_id'])} / r{s['revision']} "
            f"({'superseded' if s['superseded'] else 'current'}; "
            f"{'final' if s['is_final'] else 'provisional'}): {safe_text(s['text'])}"
        )
    return "\n".join(lines) + "\n"


def evidence_anchor(sid, revision):
    return "evidence-" + hashlib.sha256(f"{sid}:{revision}".encode()).hexdigest()[:16]


def report_markdown(report):
    lines = [
        f"# {safe_text(report['meeting']['title'])} — final report",
        f"Revision {report['revision']} · "
        f"{'Simulated analysis' if report['simulated'] else 'AI-assisted analysis'}",
        f"Date: {safe_text(report['session']['created_at'])} · "
        f"Transcript duration: {report['duration_ms'] / 60000:.1f} minutes",
    ]

    def citations(sources):
        return ", ".join(
            f"[source {i + 1}](#{evidence_anchor(sid, revision)})"
            for i, (sid, revision) in enumerate(sources.items())
        )

    for section in report["sections"]:
        lines.extend(["", f"## {section['title']}", ""])
        topic_labels = {t["id"]: t["title"] for t in report.get("topics", [])}
        items = (
            sorted(section["items"], key=lambda item: item.get("topic_id", ""))
            if topic_labels
            else section["items"]
        )
        previous_topic = None
        for item in items:
            tid = item.get("topic_id", "")
            if (
                topic_labels
                and section["key"] not in ("people", "purpose", "evidence_notes")
                and tid != previous_topic
            ):
                lines.append(f"### {safe_text(topic_labels.get(tid, 'Unassigned'))}")
                previous_topic = tid
            if section["key"] == "people":
                lines.append(
                    f"- {safe_text(item.get('name') or 'Not established')} — "
                    f"{safe_text(item['interview_role'])}; job role: "
                    f"{safe_text(item.get('job_role') or 'Not established')}"
                )
            elif section["key"] == "purpose":
                for key, value in item["brief"].items():
                    lines.append(
                        f"- {safe_text(key.title())}: {safe_text(value or 'Not established')}"
                    )
            elif section["key"] == "evidence_notes":
                lines.append(f"- Human note: {safe_text(item['body'])}")
            elif section["key"] == "questions":
                refs = {s["segment_id"]: s["revision"] for s in item["evidence"]}
                lines.append(f"- [{item['status']}] {safe_text(item['text'])} ({citations(refs)})")
            else:
                lines.append(
                    f"- {safe_text(item['text'])} ({item['basis']}; {citations(item['sources'])})"
                )
        if not section["items"]:
            lines.append("Not established")
    if report.get("topics"):
        lines.extend(["", "## Discussion topics", ""])
        for topic in report["topics"]:
            label = (
                "Evidence revised; topic needs review"
                if topic["needs_review"]
                else topic["summary"]
            )
            if topic.get("provisional"):
                label = "Provisional topic assignment: " + label
            refs = {} if topic["needs_review"] else topic["summary_sources"]
            lines.append(
                f"- {safe_text(topic['title'])} ({topic['status']}): "
                f"{safe_text(label)} ({citations(refs)})"
            )
    for match in report["question_matches"]:
        lines.append(
            f"- Suggested {match['status']} for question "
            f"{safe_text(match['question_id'])} (requires human review): "
            f"{citations(match['sources'])}"
        )
    for w in report["workflows"]:
        lines.extend(
            ["", f"### {safe_text(w['title'])}", "", "```mermaid", w["mermaid"], "```", ""]
        )
        lines.extend(
            f"{i + 1}. {safe_text(step['label'])} — "
            f"{citations({sid: w['sources'][sid] for sid in step['source_ids']})}"
            for i, step in enumerate(w["steps"])
        )
    lines.extend(["", "## Transcript evidence", ""])
    evidence = {(s["segment_id"], s["revision"]): s for s in report["evidence"]}
    # Preserve older question premises as well as current transcript revisions.
    for section in report["sections"]:
        if section["key"] == "questions":
            for q in section["items"]:
                evidence.update({(s["segment_id"], s["revision"]): s for s in q["evidence"]})
    for s in evidence.values():
        lines.extend(
            [
                f'<a id="{evidence_anchor(s["segment_id"], s["revision"])}"></a>',
                f"- {safe_text(s['segment_id'])} / r{s['revision']} · {s['start_ms']} ms · "
                f"{safe_text(s.get('speaker_name') or s['speaker_id'])} "
                f"({'final' if s['is_final'] else 'provisional'}"
                f"{'; superseded' if s.get('superseded') else ''}): {safe_text(s['text'])}",
            ]
        )
    coverage = report["coverage"]
    lines.extend(
        [
            "",
            f"Coverage: {coverage['processed_segments']}/{coverage['final_segments']} "
            f"final segments analyzed; {coverage['provisional_segments']} provisional segments.",
            "Scope: received and accepted transcript only.",
        ]
    )
    return "\n".join(lines) + "\n"
