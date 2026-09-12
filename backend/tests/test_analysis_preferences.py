import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.analysis import MockAnalyzer
from app.analysis_preferences import AnalysisPreferences
from app.config import Settings
from app.main import create_app
from app.models import TranscriptEvent
from app.storage import Storage
from tests.test_api import payload
from tests.test_pipeline import pipeline  # noqa: F401


def test_preferences_validation_concurrency_and_restart(tmp_path):
    settings = Settings(data_dir=tmp_path, analysis_strategy="legacy")
    with TestClient(create_app(settings)) as client:
        sid = client.post("/sessions", json={"title": "Settings test"}).json()["id"]
        assert client.get("/settings/analysis").json() == {"strategy": "legacy", "revision": 0}
        for body in [
            {"strategy": "unknown", "revision": 0},
            {"strategy": "topics", "revision": True},
            {"strategy": "topics", "revision": -1},
            {"strategy": "topics", "revision": 0, "gemini_api_key": "synthetic"},
        ]:
            assert client.patch("/settings/analysis", json=body).status_code == 422
        assert (
            client.patch(
                "/settings/analysis",
                headers={"origin": "https://untrusted.example"},
                json={"strategy": "topics", "revision": 0},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                "/settings/analysis",
                headers={"host": "untrusted.example"},
                json={"strategy": "topics", "revision": 0},
            ).status_code
            == 403
        )
        with ThreadPoolExecutor(2) as pool:
            responses = list(
                pool.map(
                    lambda _: client.patch(
                        "/settings/analysis", json={"strategy": "topics", "revision": 0}
                    ),
                    range(2),
                )
            )
        assert sorted(r.status_code for r in responses) == [200, 409]
        assert client.get(f"/sessions/{sid}/experiment").json()["strategy"] == "topics"
        assert client.get(f"/sessions/{sid}/experiment").json()["calls"] == 0
        # Global settings expose exactly the selected mode and its optimistic revision.
        assert client.get("/settings/analysis").json() == {"strategy": "topics", "revision": 1}
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/settings/analysis").json() == {"strategy": "topics", "revision": 1}
        assert restarted.get(f"/sessions/{sid}/experiment").json()["strategy"] == "topics"


def test_migration_and_reset_preserve_choice_and_evidence(tmp_path):
    from app.discovery import Discovery

    storage = Storage(tmp_path / "migrate.sqlite3")
    storage.initialize()
    session = storage.create("Keep evidence")
    storage.ingest(session["id"], TranscriptEvent(**payload(is_final=True)))
    before = storage.snapshot(session["id"])["segments"]
    with storage.connection() as db:
        db.execute("DROP TABLE analysis_preferences")
        db.execute("DELETE FROM schema_migrations WHERE version=5")
    storage.initialize()
    storage.initialize()
    assert storage.snapshot(session["id"])["segments"] == before
    prefs = AnalysisPreferences(storage, "topics")
    assert prefs.get() == {"strategy": "topics", "revision": 0}
    prefs.update("legacy", 0)
    assert AnalysisPreferences(storage, "topics").get()["strategy"] == "legacy"
    repo = Discovery(storage)
    repo.reset(session["meeting_id"])
    assert prefs.get() == {"strategy": "legacy", "revision": 1}
    with storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_mode_change_keeps_inflight_contract_and_applies_to_next_batch(pipeline):  # noqa: F811
    pipeline.service.on_final = lambda sid: None
    session = pipeline.service.storage.create("Switching modes")
    sid = session["id"]
    pipeline.wakes[sid] = asyncio.Event()
    pipeline.preferences.update("topics", 0)
    entered, release = asyncio.Event(), asyncio.Event()
    inputs = []
    mock = MockAnalyzer()

    async def delayed(context):
        inputs.append(context)
        entered.set()
        await release.wait()
        return await mock.analyze(context)

    pipeline.provider.analyze = delayed
    await pipeline.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                is_final=True,
                text=(
                    "Our weekly reporting process uses several spreadsheets. We collect all the "
                    "figures on Monday, wait for access approval from another team, review the "
                    "totals, and then send a report to finance. This took six hours last week."
                ),
            )
        ),
    )
    task = asyncio.create_task(pipeline.process_batch(sid))
    await asyncio.wait_for(entered.wait(), 3)
    pipeline.preferences.update("legacy", 1)
    release.set()
    await task
    assert inputs[0]["strategy"] == "topics-v1"
    assert inputs[0]["analysis_settings_revision"] == 1
    assert pipeline.discovery.memory(sid)["topic_state"]["focus_id"]
    assert (await pipeline.view(sid))["error"] == ""
    await pipeline.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                event_id="new",
                segment_id="new",
                is_final=True,
                text="We also review the figures on Friday.",
            )
        ),
    )
    await pipeline.process_batch(sid)
    assert inputs[-1].get("strategy") != "topics-v1"
    assert inputs[-1]["analysis_mode"] == "legacy"
    assert inputs[-1]["analysis_settings_revision"] == 2
    state = await pipeline.view(sid)
    assert state["calls"] == 2 and state["error"] == ""
    # Switching back never replays accepted history or makes a call on its own.
    pipeline.preferences.update("topics", 2)
    assert not await pipeline.process_batch(sid)
    assert (await pipeline.view(sid))["calls"] == 2
    assert len(pipeline.service.storage.snapshot(sid)["segments"]) == 2
