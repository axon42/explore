import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.discovery import Discovery
from app.lifecycle import Lifecycle
from app.main import create_app
from app.models import DomainError
from app.reports import Reports
from app.storage import Storage
from tests.prepared import PEOPLE


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path / "prepared.sqlite")
    storage.initialize()
    return storage


def draft(store):
    return Discovery(store).create("default", "Synthetic interview")["meeting_id"]


def test_draft_roster_revision_modes_and_concurrent_start(store):
    mid = draft(store)
    life = Lifecycle(store)
    assert Discovery(store).detail(mid)["session"] is None
    assert store.list_sessions() == []
    with pytest.raises(DomainError, match="named interviewer"):
        life.start(mid, 0, "real")
    one = Reports(store).participants(mid, 0, PEOPLE[:1])
    with pytest.raises(DomainError):
        life.start(mid, one["revision"], "real")
    with pytest.raises(DomainError, match="Test mode"):
        life.start(mid, one["revision"], "test")
    people = Reports(store).participants(mid, one["revision"], PEOPLE)
    with pytest.raises(DomainError, match="changed"):
        life.start(mid, 0, "real")
    with ThreadPoolExecutor(2) as pool:
        sessions = list(pool.map(lambda _: life.start(mid, people["revision"], "real"), range(2)))
    assert sessions[0]["id"] == sessions[1]["id"]
    assert json.loads(sessions[0]["roster_snapshot"]) == people["participants"]
    Reports(store).participants(mid, people["revision"], [])
    with pytest.raises(DomainError):
        life.claim(sessions[0]["id"], "capture")
    assert (
        json.loads(store.snapshot(sessions[0]["id"])["session"]["roster_snapshot"])
        == people["participants"]
    )


def test_solo_test_source_exclusivity_and_immutable_mode(store):
    life = Lifecycle(store)
    mid = draft(store)
    roster = Reports(store).participants(mid, 0, PEOPLE[:1])
    life.test_mode(True)
    session = life.start(mid, roster["revision"], "test")
    life.claim(session["id"], "capture")
    with pytest.raises(DomainError, match="another transcript source"):
        life.claim(session["id"], "test")
    life.test_mode(False)
    assert store.snapshot(session["id"])["session"]["mode"] == "test"
    with pytest.raises(DomainError):
        life.test_access(session["id"])
    store.stop(session["id"])
    with pytest.raises(DomainError):
        life.claim(session["id"], "capture")


def test_capture_audit_restart_reset_and_foreign_keys(store):
    mid = draft(store)
    roster = Reports(store).participants(mid, 0, PEOPLE)
    life = Lifecycle(store)
    session = life.start(mid, roster["revision"], "real")
    state = {"id": "synthetic-run", "sid": session["id"], "status": "capturing", "frames": 30}
    life.save_capture(state)
    store.initialize()
    saved = life.last_capture()
    assert saved["status"] == "failed" and saved["code"] == "capture_interrupted"
    assert saved["frames"] == 30
    Discovery(store).reset(mid)
    life.save_capture(state)  # A stale worker cannot recreate deleted audit data.
    assert life.last_capture() is None
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_http_gates_draft_exports_real_injection_and_reset(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        assert client.get("/settings/test-mode").json() == {"enabled": False}
        assert client.post("/sessions", json={}).status_code == 409
        detail = client.post("/workspaces/default/meetings", json={"title": "Prepared"}).json()
        mid = detail["meeting"]["id"]
        assert client.get(f"/meetings/{mid}/reports").json()["reports"] == []
        assert client.get(f"/meetings/{mid}/transcript/export?format=markdown").status_code == 200
        assert client.post(f"/meetings/{mid}/start", json={"revision": 0}).status_code == 409
        roster = client.put(
            f"/meetings/{mid}/participants", json={"revision": 0, "participants": PEOPLE}
        ).json()
        detail = client.post(f"/meetings/{mid}/start", json={"revision": roster["revision"]}).json()
        sid = detail["session"]["id"]
        client.put("/settings/test-mode", json={"enabled": True})
        assert client.post(f"/sessions/{sid}/playback", json={"action": "play"}).status_code == 409
        assert client.post(f"/sessions/{sid}/demo").status_code in (404, 409)
        assert client.post(f"/meetings/{mid}/reset", json={"session_id": sid}).status_code == 409
        assert client.post(f"/sessions/{sid}/stop").status_code == 200
        assert client.get(f"/meetings/{mid}").json()["session"]["status"] == "stopped"


def test_migration_six_preserves_legacy_evidence_and_notes(store):
    from app.models import TranscriptEvent
    from tests.test_api import payload

    old = store.create("Existing meeting")
    sid, mid = old["id"], old["meeting_id"]
    store.ingest(sid, TranscriptEvent(**payload(is_final=True)))
    Discovery(store).note(mid, "Synthetic human note")
    # Reconstruct the previous schema on a disposable database, then run the real migration.
    with store.connection() as db:
        for table in ("session_producers", "capture_runs", "runtime_preferences"):
            db.execute(f"DROP TABLE {table}")
        for table, column in (
            ("sessions", "mode"),
            ("sessions", "roster_snapshot"),
            ("findings", "topic_id"),
            ("findings", "workflow_key"),
        ):
            db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        db.execute("DELETE FROM schema_migrations WHERE version=6")
    store.initialize()
    store.initialize()
    assert store.snapshot(sid)["session"]["mode"] == "legacy"
    assert store.snapshot(sid)["segments"][0]["text"] == "Let's review"
    assert Discovery(store).detail(mid)["notes"][0]["body"] == "Synthetic human note"
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert (
            db.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=6").fetchone()[0] == 1
        )
