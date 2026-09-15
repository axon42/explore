"""Observed questions: exact, revision-bound quotes, independent of suggestion status."""

import hashlib
import json
import re
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from .speakers import resolved


class SpokenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1500)
    source_ids: list[str] = Field(min_length=1, max_length=6)


DDL = [
    """CREATE TABLE spoken_questions(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
        run_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(id,session_id), FOREIGN KEY(run_id,session_id)
        REFERENCES analysis_runs(id,session_id) ON DELETE CASCADE)""",
    """CREATE TABLE spoken_question_evidence(question_id TEXT NOT NULL, session_id TEXT NOT NULL,
        segment_id TEXT NOT NULL, revision INTEGER NOT NULL, start INTEGER NOT NULL CHECK(start>=0),
        end INTEGER NOT NULL CHECK(end>start), PRIMARY KEY(question_id,segment_id,revision,start),
        FOREIGN KEY(question_id,session_id) REFERENCES spoken_questions(id,session_id)
        ON DELETE CASCADE,
        FOREIGN KEY(session_id,segment_id,revision) 
        REFERENCES segment_revisions(session_id,segment_id,revision))""",
    "CREATE INDEX spoken_questions_session ON spoken_questions(session_id,created_at,id)",
]


def anchors(proposal, segments):
    """Require one unambiguous literal occurrence in adjacent finalized sources.

    Ignore whitespace differences only; offsets always address the stored Unicode text.
    Never allow a quote to stitch around an omitted speaker turn.
    """
    ordered = sorted(segments, key=lambda s: (s["start_ms"], s["segment_id"]))
    wanted = set(proposal.source_ids)
    indexes = [i for i, s in enumerate(ordered) if s["segment_id"] in wanted]
    if (
        not indexes
        or len(indexes) != len(wanted)
        or indexes != list(range(indexes[0], indexes[-1] + 1))
    ):
        return None
    sources = [ordered[i] for i in indexes]
    if any(not s["is_final"] for s in sources):
        return None
    # Prevent a fabricated continuous quotation over an unrelated later passage.
    if any(b["start_ms"] - a["end_ms"] > 15000 for a, b in zip(sources, sources[1:], strict=False)):
        return None
    text = " ".join(s["text"] for s in sources)
    words = proposal.text.split()
    if not words:
        return None
    matches = list(re.finditer(r"\s+".join(re.escape(w) for w in words), text))
    if len(matches) != 1:
        return None
    match = matches[0]
    if (match.start() and text[match.start() - 1].isalnum()) or (
        match.end() < len(text) and text[match.end()].isalnum()
    ):
        return None
    result, offset = [], 0
    for source in sources:
        start, end = max(0, match.start() - offset), min(len(source["text"]), match.end() - offset)
        if end > start:
            result.append(
                {
                    "segment_id": source["segment_id"],
                    "revision": source["revision"],
                    "start": start,
                    "end": end,
                }
            )
        offset += len(source["text"]) + 1
    return result


def accepted(result, context):
    """Optional quote failures do not discard otherwise valid analysis; retain a safe count."""
    good = [q for q in result.spoken_questions if anchors(q, context["segments"])]
    return result.model_copy(update={"spoken_questions": good}), len(result.spoken_questions) - len(
        good
    )


def persist(db, sid, rid, result, context, timestamp):
    if not result.get("spoken_questions"):
        return
    supplied = {s["segment_id"]: s for s in context["segments"]}
    # The model's bounded context can omit turns. Check adjacency against the full
    # received timeline without loading omitted transcript bodies into model context.
    timeline = [
        supplied.get(row["segment_id"], dict(row))
        for row in db.execute(
            "SELECT segment_id,json_extract(payload,'$.start_ms') AS start_ms "
            "FROM segments WHERE session_id=?",
            (sid,),
        )
    ]
    for item in result.get("spoken_questions", []):
        proposal = SpokenQuestion.model_validate(item)
        if not set(proposal.source_ids) <= supplied.keys():
            continue
        spans = anchors(proposal, timeline)
        if not spans:
            continue
        qid = hashlib.sha256(json.dumps([sid, spans], sort_keys=True).encode()).hexdigest()
        if not db.execute(
            "INSERT OR IGNORE INTO spoken_questions VALUES(?,?,?,?,?)",
            (qid, sid, rid, proposal.text, timestamp),
        ).rowcount:
            continue
        for span in spans:
            db.execute(
                "INSERT INTO spoken_question_evidence VALUES(?,?,?,?,?,?)",
                (qid, sid, span["segment_id"], span["revision"], span["start"], span["end"]),
            )


def view(db, sid):
    rows = db.execute(
        "SELECT * FROM spoken_questions WHERE session_id=? ORDER BY created_at,id", (sid,)
    ).fetchall()
    if not rows:
        return []
    by_question = defaultdict(list)
    sources = {}
    for ref in db.execute(
        "SELECT e.*,r.payload,CASE WHEN s.revision=e.revision THEN 0 ELSE 1 END AS superseded "
        "FROM spoken_question_evidence e JOIN segment_revisions r "
        "USING(session_id,segment_id,revision) "
        "LEFT JOIN segments s USING(session_id,segment_id) WHERE e.session_id=?",
        (sid,),
    ):
        by_question[ref["question_id"]].append(ref)
        sources[(ref["segment_id"], ref["revision"])] = {
            **json.loads(ref["payload"]),
            "superseded": bool(ref["superseded"]),
        }
    # Resolve the roster/assignment history once per view, not once per question.
    attributed = {
        (s["segment_id"], s["revision"]): s for s in resolved(db, sid, list(sources.values()))
    }
    items = []
    for row in rows:
        item = dict(row)
        refs = by_question[item["id"]]
        evidence = sorted(
            [attributed[(r["segment_id"], r["revision"])] for r in refs],
            key=lambda s: (s["start_ms"], s["segment_id"]),
        )
        ranges = {r["segment_id"]: (r["start"], r["end"]) for r in refs}
        people, unknown = {}, False
        for source in evidence:
            start, end = ranges[source["segment_id"]]
            attrs = [
                a for a in source.get("attributions", []) if a["start"] < end and a["end"] > start
            ]
            if not attrs or source["superseded"]:
                unknown = True
            for attr in attrs:
                if attr["status"] != "confirmed":
                    unknown = True
                else:
                    people[attr["participant_id"]] = attr
        person = next(iter(people.values())) if len(people) == 1 and not unknown else {}
        item.update(
            evidence=evidence,
            anchors=[{k: r[k] for k in ("segment_id", "revision", "start", "end")} for r in refs],
            speaker_name=person.get("name", "Unconfirmed speaker"),
            participant_id=person.get("participant_id"),
            interview_role=person.get("interview_role", "unknown"),
            superseded=any(e["superseded"] for e in evidence),
            start_ms=evidence[0]["start_ms"] if evidence else 0,
        )
        items.append(item)
    return sorted(items, key=lambda q: (q["start_ms"], q["id"]))


def mock_questions(segments):
    """A deliberately narrow fixture detector; semantic extraction belongs to the provider."""
    return [
        SpokenQuestion(text=m.group().strip(), source_ids=[s["segment_id"]])
        for s in segments
        if s["is_final"]
        for m in re.finditer(r"[^.!?]+\?", s["text"])
        if 0 < len(m.group().strip()) <= 1500
    ][:16]
