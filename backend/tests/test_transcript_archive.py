import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.archives import Archives
from app.config import ROOT, Settings
from app.discovery import Discovery
from app.models import DomainError, TranscriptEvent
from app.storage import Storage
from tests.test_api import payload


@pytest.fixture
def store(tmp_path):
    storage = Storage(
        tmp_path / "working" / "meetings.sqlite3", tmp_path / "vault" / "history.sqlite3"
    )
    storage.initialize()
    return storage


def records(store):
    with sqlite3.connect(store.archive.path) as db:
        return [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM archive_events ORDER BY revision")
        ]


def delete_working_meetings(store):
    for session in store.list_sessions():
        if session["status"] == "live":
            store.stop(session["id"])
    archives = Archives(store)
    archives.clear("default")
    for meeting in Discovery(store).meetings("default"):
        archives.delete("default", meeting["id"], meeting["context_version"], True)


def test_all_accepted_revisions_survive_reset_clear_restart_and_working_db_removal(store):
    first = store.create("Synthetic interview")
    sid, mid = first["id"], first["meeting_id"]
    versions = [
        payload(),
        payload(event_id="final", revision=2, is_final=True),
        payload(event_id="correction", revision=3, is_final=True, text="Corrected synthetic text"),
    ]
    for value in versions:
        assert store.ingest(sid, TranscriptEvent(**value))[0]["outcome"] == "accepted"
    assert store.ingest(sid, TranscriptEvent(**versions[0]))[0]["reason"] == "duplicate"
    assert (
        store.ingest(sid, TranscriptEvent(**payload(event_id="stale")))[0]["reason"]
        == "stale_revision"
    )
    assert (
        store.ingest(sid, TranscriptEvent(**payload(event_id="interim", revision=4)))[0]["reason"]
        == "finalized_segment"
    )
    assert records(store) == versions
    discovery = Discovery(store)
    store.stop(sid)
    discovery.reset(mid)
    with pytest.raises(DomainError):
        store.ingest(sid, TranscriptEvent(**payload(event_id="late", revision=5)))
    other = store.create("Other interview")
    store.ingest(other["id"], TranscriptEvent(**payload(event_id="other")))
    delete_working_meetings(store)
    store.initialize()
    assert len(records(store)) == 4
    store.path.unlink()  # Disposable synthetic working DB, not the archive.
    assert len(records(store)) == 4


def test_failed_write_rolls_back_both_databases_and_can_retry(store, monkeypatch):
    sid = store.create("Rollback")["id"]
    original = store.archive.event

    def fail_after_archive(*args):
        original(*args)
        raise sqlite3.OperationalError("synthetic failure")

    monkeypatch.setattr(store.archive, "event", fail_after_archive)
    with pytest.raises(sqlite3.Error):
        store.ingest(sid, TranscriptEvent(**payload()))
    assert store.snapshot(sid)["segments"] == []
    assert records(store) == []
    monkeypatch.setattr(store.archive, "event", original)
    assert store.ingest(sid, TranscriptEvent(**payload()))[0]["outcome"] == "accepted"
    assert len(records(store)) == 1


def test_archive_is_append_only_and_failure_blocks_ingestion(store):
    sid = store.create("Immutable")["id"]
    store.ingest(sid, TranscriptEvent(**payload()))
    with store.connection() as db:
        for table in ("archive_events", "archive_contexts", "archive_sessions"):
            for sql in (
                f"DELETE FROM evidence.{table}",
                f"UPDATE evidence.{table} SET session_id=session_id",
            ):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    db.execute(sql)
        db.execute(
            "CREATE TRIGGER evidence.reject_write BEFORE INSERT ON archive_events "
            "BEGIN SELECT RAISE(ABORT, 'synthetic full disk'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.ingest(sid, TranscriptEvent(**payload(event_id="new", revision=2)))
    assert store.snapshot(sid)["segments"] == [payload()]
    assert records(store) == [payload()]


def test_missing_archive_blocks_delete_and_restart(store):
    sid = store.create("Unavailable")["id"]
    store.ingest(sid, TranscriptEvent(**payload()))
    moved = store.archive.path.with_suffix(".moved")
    store.archive.path.rename(moved)
    with pytest.raises(sqlite3.Error):
        delete_working_meetings(store)
    with pytest.raises(sqlite3.Error, match="missing or replaced"):
        store.initialize()
    assert not store.archive.path.exists()
    moved.rename(store.archive.path)
    assert store.snapshot(sid)["segments"] == [payload()]


def test_backfill_and_duplicate_concurrency(store, monkeypatch):
    sid = store.create("Backfill")["id"]
    with monkeypatch.context() as m:
        m.setattr(store.archive, "event", lambda *args: None)
        store.ingest(sid, TranscriptEvent(**payload()))
    assert records(store) == []
    store.initialize()
    store.initialize()
    assert records(store) == [payload()]
    live = store.create("Concurrent")["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(
            pool.map(
                lambda _: store.ingest(live, TranscriptEvent(**payload()))[0]["outcome"], range(8)
            )
        )
    assert outcomes.count("accepted") == 1
    assert len(records(store)) == 2
    with store.connection() as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA evidence.foreign_key_check").fetchall() == []


def test_process_crash_before_commit_leaves_neither_partial_record(store):
    sid = store.create("Crash")["id"]
    code = """
import os
from pathlib import Path
from app.storage import Storage
from app.models import TranscriptEvent
import json, sys
s = Storage(Path(sys.argv[1]), Path(sys.argv[2]))
original = s.archive.event
def crash(*args):
    original(*args)
    os._exit(23)
s.archive.event = crash
s.ingest(sys.argv[3], TranscriptEvent(**json.loads(sys.argv[4])))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(store.path),
            str(store.archive.path),
            sid,
            json.dumps(payload()),
        ],
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
    )
    assert result.returncode == 23
    assert store.snapshot(sid)["segments"] == []
    assert records(store) == []
    assert store.ingest(sid, TranscriptEvent(**payload()))[0]["outcome"] == "accepted"


def test_offline_export_and_backup_are_scoped_and_never_overwrite(store, tmp_path):
    sid = store.create("Export")["id"]
    store.ingest(sid, TranscriptEvent(**payload()))
    delete_working_meetings(store)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "transcript_archive.py"),
        "--archive",
        str(store.archive.path),
    ]
    output = tmp_path / "export.json"
    exporting = [
        *command,
        "export",
        "--workspace",
        "default",
        "--session",
        sid,
        "--output",
        str(output),
    ]
    wrong = exporting.copy()
    wrong[wrong.index("default")] = "other-workspace"
    assert subprocess.run(wrong, capture_output=True).returncode != 0
    assert not output.exists()
    assert subprocess.run(exporting, capture_output=True).returncode == 0
    exported = json.loads(output.read_text())
    assert exported["accepted_revisions"] == [payload()]
    assert exported["contexts"]
    assert subprocess.run(exporting, capture_output=True).returncode != 0
    backup = tmp_path / "backup.sqlite3"
    assert (
        subprocess.run(
            [*command, "backup", "--output", str(backup)], capture_output=True
        ).returncode
        == 0
    )
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT count(*) FROM archive_events").fetchone()[0] == 1
    assert output.stat().st_mode & 0o777 == 0o600


def test_config_archive_outside_disposable_data(tmp_path):
    settings = Settings(data_dir=tmp_path / "working")
    assert not settings.transcript_archive_path.is_relative_to(settings.data_dir)
    assert settings.transcript_archive_path.is_relative_to(tmp_path)


def test_upgrade_existing_wal_database_preserves_transcript(store):
    sid = store.create("WAL upgrade")["id"]
    store.ingest(sid, TranscriptEvent(**payload()))
    db = sqlite3.connect(store.path)
    try:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    finally:
        db.close()
    store.initialize()
    assert store.snapshot(sid)["segments"] == [payload()]
    assert records(store) == [payload()]


def test_replaced_archive_is_rejected_without_restart(store):
    store.create("Original")
    saved = store.archive.path.with_suffix(".saved")
    store.archive.path.rename(saved)
    store.archive.initialize()  # Synthetic replacement with another identity.
    with pytest.raises(sqlite3.Error, match="missing or replaced"):
        store.list_sessions()


def test_archive_write_error_never_emits_success_ack(store):
    import asyncio

    from app.broadcast import Broadcaster
    from app.service import Service

    async def run():
        sid = store.create("No false success")["id"]
        service = Service(store, Broadcaster(10))
        subscriber = await service.subscribe(sid)
        await subscriber.queue.get()
        with store.connection() as db:
            db.execute(
                "CREATE TRIGGER evidence.no_events BEFORE INSERT ON archive_events "
                "BEGIN SELECT RAISE(ABORT, 'synthetic archive failure'); END"
            )
        with pytest.raises(sqlite3.Error):
            await service.ingest(sid, TranscriptEvent(**payload()))
        assert subscriber.queue.empty()
        assert records(store) == []

    asyncio.run(run())
