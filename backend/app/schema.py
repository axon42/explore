"""Forward-only, transactional migrations. Legacy transcript tables remain compatible."""

import json

from .speakers import migrate as migrate_speakers
from .spoken_questions import DDL as SPOKEN_DDL
from .topic_storage import DDL as TOPIC_DDL

DDL = [
    (
        "CREATE TABLE workspaces(id TEXT PRIMARY KEY, name TEXT NOT NULL "
        "CHECK(length(name)>0), created_at TEXT NOT NULL)"
    ),
    """CREATE TABLE meetings(id TEXT PRIMARY KEY,
       workspace_id TEXT NOT NULL REFERENCES workspaces(id),
       title TEXT NOT NULL, context_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
       updated_at TEXT NOT NULL)""",
    "ALTER TABLE sessions ADD COLUMN meeting_id TEXT REFERENCES meetings(id)",
    """CREATE TABLE meeting_briefs(meeting_id TEXT NOT NULL REFERENCES meetings(id),
       revision INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
       PRIMARY KEY(meeting_id, revision))""",
    """CREATE TABLE notes(id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id),
       body TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
       updated_at TEXT NOT NULL)""",
    """CREATE TABLE note_revisions(note_id TEXT NOT NULL REFERENCES notes(id),
       revision INTEGER NOT NULL,
       body TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(note_id, revision))""",
    """CREATE TABLE segment_revisions(session_id TEXT NOT NULL REFERENCES sessions(id),
       segment_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
       PRIMARY KEY(session_id, segment_id, revision))""",
    """CREATE TABLE analysis_runs(id TEXT PRIMARY KEY,
       session_id TEXT NOT NULL REFERENCES sessions(id),
       input_version INTEGER NOT NULL, context_version INTEGER NOT NULL, provider TEXT NOT NULL,
       model TEXT NOT NULL, prompt_version TEXT NOT NULL, input_json TEXT NOT NULL,
       output_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(id, session_id))""",
    """CREATE TABLE questions(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
       run_id TEXT NOT NULL REFERENCES analysis_runs(id), text TEXT NOT NULL,
       normalized TEXT NOT NULL,
       rationale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued'
       CHECK(status IN ('queued','asked','answered')), revision INTEGER NOT NULL DEFAULT 0,
       created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(session_id,
       normalized), UNIQUE(id, session_id),
       FOREIGN KEY(run_id, session_id) REFERENCES analysis_runs(id, session_id))""",
    """CREATE TABLE question_evidence(question_id TEXT NOT NULL REFERENCES questions(id),
       session_id TEXT NOT NULL, segment_id TEXT NOT NULL, revision INTEGER NOT NULL,
       PRIMARY KEY(question_id, segment_id, revision),
       FOREIGN KEY(question_id, session_id) REFERENCES questions(id, session_id),
       FOREIGN KEY(session_id, segment_id, revision) 
       REFERENCES segment_revisions(session_id, segment_id, revision))""",
    """CREATE TABLE question_status_events(id TEXT PRIMARY KEY, question_id TEXT NOT NULL 
       REFERENCES questions(id),
       status TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE findings(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
       run_id TEXT NOT NULL REFERENCES analysis_runs(id), kind TEXT NOT NULL
       CHECK(kind IN ('workflow','gap','opportunity')), title TEXT NOT NULL, body TEXT NOT NULL,
       basis TEXT NOT NULL CHECK(basis IN ('observed','inferred')),
       created_at TEXT NOT NULL, UNIQUE(id, session_id),
       FOREIGN KEY(run_id, session_id) REFERENCES analysis_runs(id, session_id))""",
    """CREATE TABLE finding_evidence(finding_id TEXT NOT NULL REFERENCES findings(id),
       session_id TEXT NOT NULL, segment_id TEXT NOT NULL, revision INTEGER NOT NULL,
       PRIMARY KEY(finding_id, segment_id, revision),
       FOREIGN KEY(finding_id, session_id) REFERENCES findings(id, session_id),
       FOREIGN KEY(session_id, segment_id, revision) 
       REFERENCES segment_revisions(session_id, segment_id, revision))""",
    "CREATE INDEX meetings_workspace ON meetings(workspace_id, updated_at)",
    "CREATE INDEX sessions_meeting ON sessions(meeting_id, created_at)",
    "CREATE INDEX notes_meeting ON notes(meeting_id)",
    "CREATE INDEX runs_session ON analysis_runs(session_id, created_at)",
]


def migrate_v1(db, timestamp):
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY "
        "KEY, applied_at TEXT NOT NULL)"
    )
    if db.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
        return
    db.execute("BEGIN IMMEDIATE")
    for statement in DDL:
        db.execute(statement)
    db.execute("INSERT INTO workspaces VALUES ('default', 'My workspace', ?)", (timestamp,))
    for row in db.execute("SELECT * FROM sessions").fetchall():
        db.execute(
            "INSERT INTO meetings VALUES (?, 'default', ?, 0, ?, ?)",
            (row["id"], row["title"], row["created_at"], timestamp),
        )
        db.execute("UPDATE sessions SET meeting_id=? WHERE id=?", (row["id"], row["id"]))
        db.execute(
            "INSERT INTO meeting_briefs VALUES (?, 0, ?, ?)",
            (
                row["id"],
                json.dumps({"title": row["title"], "objective": legacy_objective(db, row["id"])}),
                timestamp,
            ),
        )
    db.execute(
        "INSERT INTO segment_revisions SELECT session_id, segment_id, revision, "
        "payload FROM segments"
    )
    db.execute("""CREATE TRIGGER session_meeting_required BEFORE INSERT ON sessions
        WHEN NEW.meeting_id IS NULL BEGIN SELECT RAISE(ABORT, 'meeting_id required'); END""")
    db.execute("INSERT INTO schema_migrations VALUES (1, ?)", (timestamp,))


def legacy_objective(db, sid):
    row = db.execute("SELECT payload FROM experiments WHERE session_id=?", (sid,)).fetchone()
    return json.loads(row[0]).get("objective", "") if row else ""


DDL_V2 = [
    """CREATE TABLE analysis_state(session_id TEXT PRIMARY KEY REFERENCES sessions(id)
        ON DELETE CASCADE, payload TEXT NOT NULL)""",
    """CREATE TABLE meeting_participants(meeting_id TEXT PRIMARY KEY REFERENCES meetings(id)
        ON DELETE CASCADE, revision INTEGER NOT NULL, payload TEXT NOT NULL)""",
    """CREATE TABLE reports(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id)
        ON DELETE CASCADE, revision INTEGER NOT NULL, input_version INTEGER NOT NULL,
        context_version INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(session_id, revision), UNIQUE(session_id, input_version, context_version))""",
    """CREATE TABLE report_jobs(session_id TEXT PRIMARY KEY REFERENCES sessions(id)
        ON DELETE CASCADE, status TEXT NOT NULL CHECK(status IN ('pending','generating',
        'complete','failed')), error TEXT NOT NULL DEFAULT '')""",
]


def migrate(db, timestamp):
    migrate_v1(db, timestamp)
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        for statement in DDL_V2:
            db.execute(statement)
        db.execute("INSERT INTO schema_migrations VALUES (2, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute(
            "ALTER TABLE meetings ADD COLUMN archived INTEGER NOT NULL DEFAULT "
            "0 CHECK(archived IN (0,1))"
        )
        db.execute(
            "ALTER TABLE meetings ADD COLUMN question_interval INTEGER NOT "
            "NULL DEFAULT 60 CHECK(question_interval IN (30,60,120,0))"
        )
        db.execute(
            "ALTER TABLE questions ADD COLUMN discarded INTEGER NOT NULL "
            "DEFAULT 0 CHECK(discarded IN (0,1))"
        )
        db.execute("INSERT INTO schema_migrations VALUES (3, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        for statement in TOPIC_DDL:
            db.execute(statement)
        db.execute("INSERT INTO schema_migrations VALUES (4, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE analysis_preferences(id INTEGER PRIMARY KEY CHECK(id=1), "
            "strategy TEXT NOT NULL CHECK(strategy IN ('legacy','topics')), "
            "revision INTEGER NOT NULL CHECK(revision>=1))"
        )
        db.execute("INSERT INTO schema_migrations VALUES (5, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=6").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute(
            "ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'legacy' "
            "CHECK(mode IN ('legacy','real','test'))"
        )
        db.execute("ALTER TABLE sessions ADD COLUMN roster_snapshot TEXT NOT NULL DEFAULT '[]'")
        db.execute(
            "CREATE TABLE runtime_preferences(id INTEGER PRIMARY KEY CHECK(id=1), "
            "test_mode INTEGER NOT NULL DEFAULT 0 CHECK(test_mode IN (0,1)))"
        )
        db.execute("INSERT INTO runtime_preferences VALUES(1,0)")
        db.execute(
            "CREATE TABLE session_producers(session_id TEXT PRIMARY KEY REFERENCES "
            "sessions(id) ON DELETE CASCADE, kind TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE capture_runs(id TEXT PRIMARY KEY, session_id TEXT NOT NULL "
            "REFERENCES sessions(id) ON DELETE CASCADE, payload TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        db.execute("ALTER TABLE findings ADD COLUMN topic_id TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE findings ADD COLUMN workflow_key TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT INTO schema_migrations VALUES (6, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=7").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        migrate_speakers(db, timestamp)
        db.execute("INSERT INTO schema_migrations VALUES (7, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=8").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute(
            "ALTER TABLE workspaces ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 "
            "CHECK(archived IN (0,1))"
        )
        db.execute(
            "ALTER TABLE workspaces ADD COLUMN revision INTEGER NOT NULL DEFAULT 0 "
            "CHECK(revision>=0)"
        )
        db.execute("INSERT INTO schema_migrations VALUES (8, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=9").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        for statement in SPOKEN_DDL:
            db.execute(statement)
        db.execute("INSERT INTO schema_migrations VALUES (9, ?)", (timestamp,))
    if not db.execute("SELECT 1 FROM schema_migrations WHERE version=10").fetchone():
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE developer_traces(id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            job_id TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL,
            outcome TEXT NOT NULL, metadata TEXT NOT NULL, request_body TEXT, response_body TEXT)
            """)
        db.execute(
            "CREATE INDEX developer_traces_session ON developer_traces(session_id,created_at)"
        )
        db.execute("INSERT INTO schema_migrations VALUES(10,?)", (timestamp,))
    db.execute("UPDATE developer_traces SET outcome='interrupted' WHERE outcome='running'")
    db.execute(
        "UPDATE capture_runs SET payload=json_set(payload, '$.status', 'failed', "
        "'$.code','capture_interrupted','$.error','Capture interrupted by server restart.') "
        "WHERE json_extract(payload,'$.status') IN ('starting','capturing','stopping')"
    )
    db.execute("DELETE FROM session_producers")
    db.execute(
        "UPDATE report_jobs SET status='failed', error='Interrupted; retry finalization.' "
        "WHERE status IN ('pending','generating')"
    )
