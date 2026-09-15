"""Source observations and human attribution; independent of audio and model providers."""

import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from .models import DomainError

DDL = [
    "ALTER TABLE sessions ADD COLUMN attribution_version INTEGER NOT NULL DEFAULT 0",
    "CREATE UNIQUE INDEX sessions_identity_meeting ON sessions(id,meeting_id)",
    """CREATE TABLE participant_identities(
        id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        legacy_id TEXT NOT NULL, UNIQUE(id,meeting_id), UNIQUE(meeting_id,legacy_id))""",
    """CREATE TABLE participant_rosters(
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(meeting_id,revision))""",
    """CREATE TABLE speaker_tracks(
        id TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        capture_id TEXT NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('microphone','system')),
        label INTEGER, method TEXT NOT NULL CHECK(method IN ('diarized','single_person_source')),
        PRIMARY KEY(session_id,id), UNIQUE(session_id,capture_id,channel,method,label))""",
    """CREATE TABLE speaker_spans(
        session_id TEXT NOT NULL, segment_id TEXT NOT NULL, revision INTEGER NOT NULL,
        span_index INTEGER NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
        track_id TEXT, CHECK(start>=0 AND end>start),
        PRIMARY KEY(session_id,segment_id,revision,span_index),
        FOREIGN KEY(session_id,segment_id,revision)
            REFERENCES segment_revisions(session_id,segment_id,revision) ON DELETE CASCADE,
        FOREIGN KEY(session_id,track_id) REFERENCES speaker_tracks(session_id,id))""",
    """CREATE TABLE speaker_assignments(
        session_id TEXT NOT NULL, version INTEGER NOT NULL, meeting_id TEXT NOT NULL,
        track_id TEXT, segment_id TEXT, segment_revision INTEGER, span_index INTEGER,
        participant_id TEXT, roster_revision INTEGER NOT NULL, actor TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(session_id,version),
        CHECK((track_id IS NOT NULL AND segment_id IS NULL AND segment_revision IS NULL
            AND span_index IS NULL) OR (track_id IS NULL AND segment_id IS NOT NULL
            AND segment_revision IS NOT NULL AND span_index IS NOT NULL)),
        FOREIGN KEY(session_id,meeting_id) REFERENCES sessions(id,meeting_id) ON DELETE CASCADE,
        FOREIGN KEY(session_id,track_id) REFERENCES speaker_tracks(session_id,id),
        FOREIGN KEY(session_id,segment_id,segment_revision,span_index)
            REFERENCES speaker_spans(session_id,segment_id,revision,span_index) ON DELETE CASCADE,
        FOREIGN KEY(participant_id,meeting_id) REFERENCES participant_identities(id,meeting_id),
        FOREIGN KEY(meeting_id,roster_revision)
            REFERENCES participant_rosters(meeting_id,revision))""",
]


def stamp():
    return datetime.now(UTC).isoformat()


def roster(db, mid):
    row = db.execute(
        "SELECT revision,payload FROM meeting_participants WHERE meeting_id=?", (mid,)
    ).fetchone()
    return (row[0], json.loads(row[1])) if row else (0, [])


def identify(db, mid, people):
    """Legacy source IDs remain stable. Caller-supplied foreign identities are rejected."""
    result = []
    for person in people:
        row = db.execute(
            "SELECT id FROM participant_identities WHERE meeting_id=? AND legacy_id=?",
            (mid, person["speaker_id"]),
        ).fetchone()
        pid = row[0] if row else str(uuid5(NAMESPACE_URL, f"explore:{mid}:{person['speaker_id']}"))
        if person.get("participant_id") and person["participant_id"] != pid:
            raise DomainError(
                "participant_identity", "Participant identity changed. Reload the roster."
            )
        db.execute(
            "INSERT OR IGNORE INTO participant_identities VALUES (?,?,?)",
            (pid, mid, person["speaker_id"]),
        )
        result.append({**person, "participant_id": pid})
    return result


def migrate(db, timestamp):
    for statement in DDL:
        db.execute(statement)
    for row in db.execute("SELECT * FROM meeting_participants").fetchall():
        people = identify(db, row["meeting_id"], json.loads(row["payload"]))
        payload = json.dumps(people)
        db.execute(
            "UPDATE meeting_participants SET payload=? WHERE meeting_id=?",
            (payload, row["meeting_id"]),
        )
        db.execute(
            "INSERT INTO participant_rosters VALUES (?,?,?,?)",
            (row["meeting_id"], row["revision"], payload, timestamp),
        )
    # Historical channel-only analysis must be reviewed under the new identity policy.
    db.execute(
        "UPDATE sessions SET attribution_version=1,version=version+1 WHERE id IN "
        "(SELECT session_id FROM segments WHERE "
        "json_extract(payload,'$.speaker_id') IN ('microphone','system'))"
    )
    db.execute(
        "UPDATE meetings SET context_version=context_version+1 WHERE id IN "
        "(SELECT meeting_id FROM sessions WHERE attribution_version=1)"
    )


def track_key(capture_id, channel, label, method):
    return f"{capture_id}:{channel}:{'single' if method == 'single_person_source' else label}"


def observe(db, sid, event):
    metadata = event.get("speaker_metadata")
    if not metadata:
        return
    for index, span in enumerate(metadata["spans"]):
        key = None
        if span["label"] is not None:
            key = track_key(
                metadata["capture_id"], metadata["channel"], span["label"], metadata["method"]
            )
            db.execute(
                "INSERT OR IGNORE INTO speaker_tracks VALUES (?,?,?,?,?,?)",
                (
                    key,
                    sid,
                    metadata["capture_id"],
                    metadata["channel"],
                    span["label"],
                    metadata["method"],
                ),
            )
        db.execute(
            "INSERT INTO speaker_spans VALUES (?,?,?,?,?,?,?)",
            (
                sid,
                event["segment_id"],
                event["revision"],
                index,
                span["start"],
                span["end"],
                key,
            ),
        )


def assignments(db, sid):
    return [
        dict(r)
        for r in db.execute(
            "SELECT * FROM speaker_assignments WHERE session_id=? ORDER BY version", (sid,)
        )
    ]


def resolved(db, sid, segments):
    """The same resolver supplies browser, analysis and exports. Raw segments are untouched."""
    if not any(s.get("speaker_metadata") for s in segments):
        return segments
    session = db.execute("SELECT meeting_id,mode FROM sessions WHERE id=?", (sid,)).fetchone()
    current_revision, people = roster(db, session[0])
    people = {p["participant_id"]: p for p in people}
    by_track, by_span, passage_history = {}, {}, {}
    for row in assignments(db, sid):
        if row["track_id"]:
            by_track[row["track_id"]] = row
        else:
            by_span[(row["segment_id"], row["segment_revision"], row["span_index"])] = row
            passage_history[row["segment_id"]] = row
    # Resolve just the supplied events; ingestion need not scan the whole meeting per frame.
    observations = {}
    for segment in segments:
        metadata = segment.get("speaker_metadata")
        if not metadata:
            continue
        observations[(segment["segment_id"], segment["revision"])] = [
            {
                **span,
                "span_index": index,
                "channel": metadata["channel"],
                "track_id": track_key(
                    metadata["capture_id"], metadata["channel"], span["label"], metadata["method"]
                )
                if span["label"] is not None
                else None,
            }
            for index, span in enumerate(metadata["spans"])
        ]
    result = []
    for segment in segments:
        spans = []
        for span in observations.get((segment["segment_id"], segment["revision"]), []):
            override = by_span.get((segment["segment_id"], segment["revision"], span["span_index"]))
            assignment = override if override is not None else by_track.get(span["track_id"])
            person = people.get(assignment["participant_id"]) if assignment else None
            previous_passage = passage_history.get(segment["segment_id"])
            changed_passage = bool(
                previous_passage
                and previous_passage["segment_revision"] != segment["revision"]
                and (not assignment or assignment["version"] <= previous_passage["version"])
            )
            # Changing a roster invalidates the previous role confirmation.
            if assignment and assignment["roster_revision"] != current_revision:
                person = None
            if changed_passage:
                person = None
            channel = span["channel"] or segment["speaker_metadata"]["channel"]
            label = "Microphone" if channel == "microphone" else "Remote"
            label += " speaker" if span["label"] is None else f" speaker {span['label'] + 1}"
            spans.append(
                {
                    "index": span["span_index"],
                    "start": span["start"],
                    "end": span["end"],
                    "track_id": span["track_id"],
                    "name": person["name"] if person else label,
                    "participant_id": person["participant_id"] if person else None,
                    "interview_role": person["interview_role"] if person else "unknown",
                    "status": "confirmed" if person else "unassigned",
                    "scope": "passage" if override is not None else "track",
                    "needs_review": changed_passage
                    or bool(assignment and not person and assignment["participant_id"]),
                }
            )
        result.append({**segment, "attributions": spans} if spans else segment)
    return result


def invalidate(db, sid):
    db.execute(
        "UPDATE sessions SET attribution_version=attribution_version+1,"
        "version=version+1 WHERE id=?",
        (sid,),
    )
    db.execute(
        "UPDATE meetings SET context_version=context_version+1 "
        "WHERE id=(SELECT meeting_id FROM sessions WHERE id=?)",
        (sid,),
    )


class Speakers:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def session(db, mid, sid):
        row = db.execute(
            "SELECT * FROM sessions WHERE id=? AND meeting_id=?", (sid, mid)
        ).fetchone()
        if row is None:
            raise DomainError("not_found", "Meeting session not found", 404)
        return row

    def view(self, mid, sid):
        with self.storage.connection() as db:
            db.execute("BEGIN")
            session = self.session(db, mid, sid)
            revision, people = roster(db, mid)
            history = assignments(db, sid)
            tracks = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM speaker_tracks WHERE session_id=? ORDER BY rowid", (sid,)
                )
            ]
            segments = resolved(
                db,
                sid,
                [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT payload FROM segments WHERE session_id=? ORDER BY rowid", (sid,)
                    )
                ],
            )
            for track in tracks:
                latest = next((r for r in reversed(history) if r["track_id"] == track["id"]), None)
                track["participant_id"] = latest["participant_id"] if latest else None
                track["needs_review"] = bool(
                    latest and latest["participant_id"] and latest["roster_revision"] != revision
                )
                track["excerpt"] = next(
                    (
                        s["text"][a["start"] : a["end"]][:180]
                        for s in segments
                        if s["is_final"]
                        for a in s.get("attributions", [])
                        if a["track_id"] == track["id"]
                    ),
                    "",
                )
            return {
                "version": session["attribution_version"],
                "roster_revision": revision,
                "participants": people,
                "tracks": tracks,
                "history": history,
            }

    def assign(
        self,
        mid,
        sid,
        version,
        roster_revision,
        participant_id=None,
        track_id=None,
        segment_id=None,
        segment_revision=None,
        span_index=None,
    ):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self.session(db, mid, sid)
            revision, people = roster(db, mid)
            if session["attribution_version"] != version or revision != roster_revision:
                raise DomainError(
                    "conflict", "Speaker or participant details changed. Reload before confirming."
                )
            if participant_id and participant_id not in {p["participant_id"] for p in people}:
                raise DomainError(
                    "participant_missing", "Choose a participant from this meeting.", 400
                )
            if track_id:
                target = db.execute(
                    "SELECT 1 FROM speaker_tracks WHERE session_id=? AND id=?", (sid, track_id)
                ).fetchone()
                if segment_id is not None or segment_revision is not None or span_index is not None:
                    target = None
            else:
                target = db.execute(
                    "SELECT 1 FROM speaker_spans p JOIN segments s ON s.session_id=p.session_id "
                    "AND s.segment_id=p.segment_id AND s.revision=p.revision "
                    "WHERE p.session_id=? AND p.segment_id=? AND p.revision=? "
                    "AND p.span_index=? AND s.is_final=1",
                    (sid, segment_id, segment_revision, span_index),
                ).fetchone()
            if not target:
                raise DomainError(
                    "speaker_stale",
                    "This voice or passage is no longer current. Reload before confirming.",
                )
            if revision == 0:
                db.execute(
                    "INSERT OR IGNORE INTO participant_rosters VALUES (?,0,'[]',?)", (mid, stamp())
                )
            invalidate(db, sid)
            db.execute(
                "INSERT INTO speaker_assignments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    version + 1,
                    mid,
                    track_id,
                    segment_id,
                    segment_revision,
                    span_index,
                    participant_id,
                    revision,
                    "local_operator",
                    stamp(),
                ),
            )
            self.storage.archive.context(db, sid)
        return self.view(mid, sid)

    def prepare_capture(self, sid, capture_id, participant_id, revision):
        """Persist the explicit single-person assertion before the first audio result."""
        from .lifecycle import Lifecycle

        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            Lifecycle(self.storage).claim_in(db, sid, "capture")
            session = self.storage._session(db, sid)
            if session["status"] != "live":
                raise DomainError("session_stopped", "Choose a live meeting.")
            current, people = roster(db, session["meeting_id"])
            if participant_id is None:
                return
            if current != revision or participant_id not in {p["participant_id"] for p in people}:
                raise DomainError("conflict", "Participant details changed. Reopen capture setup.")
            key = track_key(capture_id, "microphone", 0, "single_person_source")
            db.execute(
                "INSERT INTO speaker_tracks VALUES (?,?,?,'microphone',0,'single_person_source')",
                (key, sid, capture_id),
            )
            invalidate(db, sid)
            db.execute(
                "INSERT INTO speaker_assignments VALUES (?,?,?,?,NULL,NULL,NULL,?,?,?,?)",
                (
                    sid,
                    session["attribution_version"] + 1,
                    session["meeting_id"],
                    key,
                    participant_id,
                    current,
                    "local_operator",
                    stamp(),
                ),
            )
            self.storage.archive.context(db, sid)
