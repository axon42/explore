from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.analysis import Suggestion
from app.config import Settings
from app.discovery import Discovery
from app.main import create_app
from app.models import TranscriptEvent
from app.storage import Storage
from tests.test_api import payload
from tests.test_discovery import setup_meeting, wait_for
from tests.test_pipeline import pipeline  # noqa: F401


def test_preferences_discard_archive_and_migration(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, mid, sid = setup_meeting(client)
        _, other, _ = setup_meeting(client)
        pref = f"/meetings/{mid}/preferences"
        assert client.patch(pref, json={"revision": 1, "archived": True}).status_code == 409
        assert client.patch(pref, json={"revision": 1, "question_interval": 7}).status_code == 422
        assert client.patch(pref, json={"revision": 1, "question_interval": 120}).status_code == 200
        assert client.patch(pref, json={"revision": 1, "question_interval": 30}).status_code == 409
        client.post(
            f"/sessions/{sid}/inject",
            json=payload(
                is_final=True, speaker_id="customer", text="I use a spreadsheet to prepare reports."
            ),
        )
        q = wait_for(client, mid, lambda d: d["questions"])["questions"][0]
        path = f"/meetings/{mid}/questions/{q['id']}"
        assert (
            client.patch(
                f"/meetings/{other}/questions/{q['id']}",
                json={"revision": 0, "status": "discarded"},
            ).status_code
            == 404
        )
        assert (
            client.patch(path, json={"revision": 0, "status": "discarded"}).json()["status"]
            == "discarded"
        )
        assert client.patch(path, json={"revision": 0, "status": "queued"}).status_code == 409
        detail = client.get(f"/meetings/{mid}").json()
        assert detail["questions"][0]["evidence"] == q["evidence"]
        repo = Discovery(client.app.state.service.storage)
        assert not repo.question_allowed(sid)
        assert repo.context(sid)["previous_questions"][0]["status"] == "discarded"
        client.app.state.service.storage.stop(sid)
        assert (
            client.patch(
                pref, json={"revision": detail["meeting"]["context_version"], "archived": True}
            ).status_code
            == 200
        )
    with TestClient(create_app(settings)) as client:
        detail = client.get(f"/meetings/{mid}").json()
        assert detail["meeting"]["archived"] == 1
        assert detail["meeting"]["question_interval"] == 120
        assert detail["questions"][0]["status"] == "discarded"
        assert (
            client.patch(path, json={"revision": 1, "status": "queued"}).json()["status"]
            == "queued"
        )
        revision = client.get(f"/meetings/{mid}").json()["meeting"]["context_version"]
        assert client.patch(pref, json={"revision": revision, "archived": False}).status_code == 200
        with client.app.state.service.storage.connection() as db:
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_live_fragments_wait_and_questions_respect_cooldown(pipeline):  # noqa: F811
    pipeline.service.on_final = lambda sid: None
    session = pipeline.service.storage.create("Synthetic pacing")
    sid, mid = session["id"], session["meeting_id"]
    calls = []

    async def propose(context):
        calls.append(context)
        return Suggestion(
            question=f"Follow up {len(calls)}?",
            rationale="test",
            source_ids=[context["segments"][-1]["segment_id"]],
        ), {}

    pipeline.provider.analyze = propose

    async def inject(i, text):
        await pipeline.service.ingest(
            sid,
            TranscriptEvent(
                **payload(
                    event_id=f"event-{i}", segment_id=f"audio-test-{i}", is_final=True, text=text
                )
            ),
        )

    await inject(1, "Let me explain our weekly reporting process.")
    assert not await pipeline.process_batch(sid)
    assert not calls
    await inject(
        2,
        "Every Friday we collect totals from three tools and compare "
        "the results in a spreadsheet. We check each line manually "
        "before preparing the report for review by the customer operations team.",
    )
    await pipeline.process_batch(sid)
    assert len(pipeline.discovery.detail(mid)["questions"]) == 1
    await inject(3, "The manual checks often take two hours.")
    await pipeline.process_batch(sid)
    assert len(calls) == 2 and not calls[-1]["question_allowed"]
    assert len(pipeline.discovery.detail(mid)["questions"]) == 1
    with pipeline.service.storage.connection() as db:
        db.execute(
            "UPDATE questions SET created_at=? WHERE session_id=?",
            ((datetime.now(UTC) - timedelta(seconds=61)).isoformat(), sid),
        )
    await inject(4, "Last week a mistake delayed delivery.")
    await pipeline.process_batch(sid, allow_questions=False)
    assert len(pipeline.discovery.detail(mid)["questions"]) == 1
    await inject(6, "A reviewer had to repeat the entire check before delivery.")
    await pipeline.process_batch(sid)
    assert len(pipeline.discovery.detail(mid)["questions"]) == 2
    revision = pipeline.discovery.detail(mid)["meeting"]["context_version"]
    pipeline.discovery.preferences(mid, revision, interval=0)
    await inject(5, "We want to understand where the mistakes happen.")
    await pipeline.process_batch(sid)
    assert len(pipeline.discovery.detail(mid)["questions"]) == 2
    assert "audio-test-5" in pipeline.discovery.memory(sid)["coverage"]


def test_v3_migration_backfills_without_losing_transcript(tmp_path):
    storage = Storage(tmp_path / "migration.sqlite3")
    storage.initialize()
    session = storage.create("Legacy")
    storage.ingest(session["id"], TranscriptEvent(**payload(is_final=True)))
    before = storage.snapshot(session["id"])
    with storage.connection() as db:
        db.execute("ALTER TABLE meetings DROP COLUMN archived")
        db.execute("ALTER TABLE meetings DROP COLUMN question_interval")
        db.execute("ALTER TABLE questions DROP COLUMN discarded")
        db.execute("DELETE FROM schema_migrations WHERE version=3")
    storage.initialize()
    storage.initialize()
    assert storage.snapshot(session["id"])["segments"] == before["segments"]
    detail = Discovery(storage).detail(session["meeting_id"])
    assert detail["meeting"]["question_interval"] == 60
    assert detail["meeting"]["archived"] == 0
    with storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
