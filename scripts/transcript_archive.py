"""Read/export the retained evidence archive without the working meeting database."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="Override the configured archive file"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list", help="List session metadata; no transcript text"
    )
    listing.add_argument("--workspace")
    exporting = commands.add_parser(
        "export", help="Write complete accepted revision history"
    )
    exporting.add_argument("--workspace", required=True)
    exporting.add_argument("--session", required=True)
    exporting.add_argument("--output", required=True, type=Path)
    backup = commands.add_parser(
        "backup", help="Create a consistent independent SQLite backup"
    )
    backup.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = (args.archive or Settings().transcript_archive_path).resolve()
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            if args.command == "list":
                rows = db.execute(
                    "SELECT s.*, (SELECT count(*) FROM archive_events e WHERE e.session_id=s.session_id) "
                    "AS accepted_revisions FROM archive_sessions s "
                    "WHERE (? IS NULL OR workspace_id=?) ORDER BY created_at, session_id",
                    (args.workspace, args.workspace),
                )
                print(json.dumps([dict(row) for row in rows], indent=2))
                return
            db.execute("BEGIN")
            if args.command == "export":
                session = db.execute(
                    "SELECT * FROM archive_sessions WHERE session_id=? AND workspace_id=?",
                    (args.session, args.workspace),
                ).fetchone()
                if session is None:
                    parser.error("Session not found in this workspace")
                contexts = [
                    json.loads(row[0])
                    for row in db.execute(
                        "SELECT payload FROM archive_contexts WHERE session_id=? ORDER BY recorded_at, digest",
                        (args.session,),
                    )
                ]
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    header = {
                        "schema_version": 1,
                        "session": dict(session),
                        "contexts": contexts,
                    }
                    output.write(
                        json.dumps(header, ensure_ascii=False)[:-1]
                        + ',"accepted_revisions":['
                    )
                    separator = ""
                    for row in db.execute(
                        "SELECT payload FROM archive_events WHERE session_id=? ORDER BY segment_id, revision",
                        (args.session,),
                    ):
                        output.write(separator + row[0])
                        separator = ","
                    output.write("]}\n")
            else:
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                with sqlite3.connect(args.output) as destination:
                    db.backup(destination)
        print(f"Saved {args.output}")
    except (sqlite3.Error, OSError):
        parser.exit(
            1,
            "Archive operation failed. Check paths, permissions and available disk space.\n",
        )


if __name__ == "__main__":
    main()
