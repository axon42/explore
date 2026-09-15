"""Organization is reversible; only explicit archived deletion purges working records."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.archives import Archives
from app.config import Settings
from app.discovery import Discovery
from app.lifecycle import Lifecycle
from app.main import create_app
from app.models import DomainError, TranscriptEvent
from app.storage import Storage
from tests.test_api import payload


@pytest.fixture
def setup(tmp_path):
    store = Storage(tmp_path / "working.sqlite3")
    store.initialize()
    repo = Discovery(store)
    workspace = repo.create_workspace("Synthetic team")
    one = store.create("Interview", workspace["id"])
    other = store.create("Unrelated")
    event = TranscriptEvent(**payload(text="Original evidence", is_final=True))
    store.ingest(one["id"], event)
    store.stop(one["id"])
    repo.note(one["meeting_id"], "Keep human note")
    return store, repo, workspace, one, other


def test_archive_clear_restore_and_permanent_delete_retains_evidence(setup):
    store, repo, w, one, other = setup
    archives = Archives(store)
    wid, mid = w["id"], one["meeting_id"]
    assert archives.clear(wid) == {"status": "archived", "count": 1}
    assert archives.clear(wid)["count"] == 0
    detail = repo.detail(mid)
    assert detail["notes"][0]["body"] == "Keep human note"
    assert [m["id"] for m in archives.list()] == [mid]
    assert not repo.detail(other["meeting_id"])["meeting"]["archived"]
    repo.preferences(mid, detail["meeting"]["context_version"], archived=False)
    assert not archives.list()
    with pytest.raises(DomainError, match="Archive the meeting"):
        archives.delete(wid, mid, 0, True)
    archives.clear(wid)
    revision = repo.detail(mid)["meeting"]["context_version"]
    with pytest.raises(DomainError, match="confirm deletion"):
        archives.delete(wid, mid, revision, False)
    with pytest.raises(DomainError, match="Meeting changed"):
        archives.delete(wid, mid, revision - 1, True)
    with pytest.raises(DomainError, match="not found in this workspace"):
        archives.delete("default", mid, revision, True)
    assert archives.delete(wid, mid, revision, True)["transcript_archive_retained"]
    with pytest.raises(DomainError):
        repo.detail(mid)
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM evidence.archive_events WHERE session_id=?", (one["id"],)
            ).fetchone()[0]
            == 1
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert not db.execute("SELECT * FROM notes WHERE meeting_id=?", (mid,)).fetchall()
    assert repo.detail(other["meeting_id"])


def test_workspace_archive_atomic_live_gate_and_restore_preserves_flags(setup):
    store, repo, w, one, _ = setup
    a = Archives(store)
    live = store.create("Still running", w["id"])
    for action in (lambda: a.clear(w["id"]), lambda: a.workspace(w["id"], 0, True)):
        with pytest.raises(DomainError, match="End active meetings"):
            action()
    assert not repo.detail(one["meeting_id"])["meeting"]["archived"]
    store.stop(live["id"])
    repo.preferences(
        one["meeting_id"],
        repo.detail(one["meeting_id"])["meeting"]["context_version"],
        archived=True,
    )
    a.workspace(w["id"], 0, True)
    assert len(a.list()) == 2
    with pytest.raises(DomainError, match="Restore the workspace"):
        repo.create(w["id"], "No creation")
    with pytest.raises(DomainError, match="Restore the workspace"):
        Lifecycle(store).start(live["meeting_id"], 0, "real")
    with pytest.raises(DomainError, match="Restore the workspace"):
        repo.preferences(
            one["meeting_id"],
            repo.detail(one["meeting_id"])["meeting"]["context_version"],
            archived=False,
        )
    with pytest.raises(DomainError, match="Workspace changed"):
        a.workspace(w["id"], 0, False)
    a.workspace(w["id"], 1, False)
    assert [m["id"] for m in a.list()] == [one["meeting_id"]]
    assert not repo.detail(live["meeting_id"])["meeting"]["archived"]


def test_failed_preservation_rolls_back_delete_and_pending_report_blocks(setup, monkeypatch):
    store, repo, w, one, _ = setup
    a = Archives(store)
    a.clear(w["id"])
    revision = repo.detail(one["meeting_id"])["meeting"]["context_version"]
    with store.connection() as db:
        db.execute("INSERT INTO report_jobs VALUES(?,'generating','')", (one["id"],))
    with pytest.raises(DomainError, match="Wait for the report"):
        a.delete(w["id"], one["meeting_id"], revision, True)
    with store.connection() as db:
        db.execute("DELETE FROM report_jobs")

    def fail(*_):
        raise OSError("synthetic archive failure")

    monkeypatch.setattr(store.archive, "preserve", fail)
    with pytest.raises(OSError):
        a.delete(w["id"], one["meeting_id"], revision, True)
    assert repo.detail(one["meeting_id"])["notes"]
    assert store.snapshot(one["id"])["segments"][0]["text"] == "Original evidence"


def test_concurrent_workspace_edits_and_api_normal_mode(setup):
    store, _, w, _, _ = setup

    def archive():
        try:
            Archives(store).workspace(w["id"], 0, True)
            return "saved"
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: archive(), range(2))) == ["conflict", "saved"]


def test_archive_api_without_test_mode(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        w = client.post("/workspaces", json={"name": "Archive API"}).json()
        detail = client.post(f"/workspaces/{w['id']}/meetings", json={"title": "Draft"}).json()
        mid = detail["meeting"]["id"]
        assert not client.get("/settings/test-mode").json()["enabled"]
        assert client.delete(f"/workspaces/{w['id']}/meetings").json()["status"] == "archived"
        row = client.get("/archives/meetings").json()[0]
        path = f"/workspaces/{w['id']}/meetings/{mid}"
        assert (
            client.request(
                "DELETE", path, json={"revision": row["context_version"], "confirmed": "yes"}
            ).status_code
            == 422
        )
        assert (
            client.request(
                "DELETE", path, json={"revision": row["context_version"], "confirmed": True}
            ).status_code
            == 200
        )
        assert client.get("/archives/meetings").json() == []


def test_v7_migration_preserves_existing_workspaces_transcripts_and_notes(setup):
    store, repo, w, one, _ = setup
    with store.connection() as db:
        db.execute("DROP TABLE spoken_question_evidence")
        db.execute("DROP TABLE spoken_questions")
        db.execute("ALTER TABLE workspaces DROP COLUMN archived")
        db.execute("ALTER TABLE workspaces DROP COLUMN revision")
        db.execute("DELETE FROM schema_migrations WHERE version IN (8,9)")
    store.initialize()
    assert repo.workspaces()[-1]["archived"] == 0
    assert repo.detail(one["meeting_id"])["notes"][0]["body"] == "Keep human note"
    assert store.snapshot(one["id"])["segments"][0]["text"] == "Original evidence"
    store.initialize()  # idempotent
    with store.connection() as db:
        assert (
            db.execute("SELECT count(*) FROM schema_migrations WHERE version IN (8,9)").fetchone()[
                0
            ]
            == 2
        )
        assert (
            db.execute(
                "SELECT count(*) FROM evidence.archive_events WHERE session_id=?", (one["id"],)
            ).fetchone()[0]
            == 1
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
