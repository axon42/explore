"""Synthetic full-meeting tests: no network, credentials, microphone or user database."""

import asyncio
import json
from uuid import uuid4

import pytest

from app.analysis import FullSuggestion, ProviderError, request_payload, serialized_request
from app.analysis_state import TriggerPolicy
from app.discovery import Discovery
from app.models import DomainError, TranscriptEvent
from app.storage import Storage
from tests.test_api import payload
from tests.test_pipeline import pipeline as manual_pipeline  # noqa: F401


def create(p):
    return p.service.storage.create("Synthetic manual meeting")["id"]


async def ingest(p, sid, index=0, **changes):
    event = payload(
        event_id=f"event-{index}",
        segment_id=f"source-{index}",
        revision=0,
        text=f"Synthetic finalized interview statement {index}.",
        start_ms=index * 1000,
        end_ms=(index + 1) * 1000,
        is_final=True,
    )
    event.update(changes)
    await p.service.ingest(sid, TranscriptEvent(**event))


async def run(p, sid, job=None):
    await p.submit_manual(sid, job or str(uuid4()))
    await p.manual_workers[sid]
    return await p.view(sid)


def answer(**kwargs):
    return FullSuggestion(complete=True, question="", rationale="", source_ids=[], **kwargs), {}


async def test_manual_no_calls_until_explicit_analysis_or_final_review(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    p.trigger = TriggerPolicy(idle_seconds=0.005, max_wait_seconds=0.01)
    sid = create(p)
    await ingest(p, sid)
    await asyncio.sleep(0.03)
    assert (await p.view(sid))["scheduling"]["mode"] == "manual"
    assert not await p.process_batch(sid)
    await p.set_schedule(sid, "automatic", 0)
    await asyncio.sleep(0.03)
    assert (await p.view(sid))["calls"] == 0
    await p.set_schedule(sid, "manual", 1)
    await p.service.stop(sid)
    await p.stop(sid)
    await p.request_report(sid)
    await p.report_workers[sid]
    state = await p.view(sid)
    assert state["calls"] == 0 and state["scheduling"]["pending_segments"] == 0
    assert not Discovery(p.service.storage).detail(
        p.service.storage.snapshot(sid)["session"]["meeting_id"]
    )["questions"]
    await p.request_report(sid)
    await p.report_workers[sid]
    with p.service.storage.connection() as db:
        assert (
            db.execute("SELECT status FROM report_jobs WHERE session_id=?", (sid,)).fetchone()[0]
            == "complete"
        )


async def test_full_input_no_fragment_truncation_and_idempotency(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    for i in range(75):
        await ingest(p, sid, i, text=(f"Synthetic statement {i}. " * 25))
    seen = []

    async def model(context):
        seen.append(context)
        return answer()

    p.provider.analyze = model
    job = str(uuid4())
    state = await run(p, sid, job)
    assert len(seen) == 1 and len(seen[0]["segments"]) == 75
    assert len(seen[0]["new_source_ids"]) == 75
    assert sum(len(s["text"]) for s in seen[0]["segments"]) > 24000
    assert state["scheduling"]["pending_segments"] == 0
    assert state["scheduling"]["analyzed_through_ms"] == 75000
    assert not state["scheduling"]["changed"]
    assert (await p.submit_manual(sid, job))["status"] == "succeeded"
    with pytest.raises(DomainError, match="already been analyzed"):
        await p.submit_manual(sid, str(uuid4()))
    assert (await p.view(sid))["calls"] == 1
    with p.service.storage.connection() as db:
        receipt = db.execute("SELECT * FROM manual_analysis_jobs WHERE id=?", (job,)).fetchone()
        assert len(json.loads(receipt["input_json"])["segments"]) == 75
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("new_speech_final", [False, True])
async def test_concurrent_clicks_new_speech_and_cross_session_receipts(
    manual_pipeline,  # noqa: F811
    new_speech_final,
):
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)
    started, release = asyncio.Event(), asyncio.Event()

    async def model(context):
        started.set()
        await release.wait()
        return FullSuggestion(
            complete=True, question="What happened?", rationale="Test", source_ids=["source-0"]
        ), {}

    p.provider.analyze = model
    job = str(uuid4())
    await p.submit_manual(sid, job)
    await started.wait()
    assert (await p.submit_manual(sid, job))["status"] == "running"
    with pytest.raises(DomainError, match="already running"):
        await p.submit_manual(sid, str(uuid4()))
    with pytest.raises(DomainError, match="current analysis"):
        await p.set_schedule(sid, "automatic", 0)
    other = create(p)
    with pytest.raises(DomainError, match="not found"):
        await p.submit_manual(other, job)
    await ingest(p, sid, 1, is_final=new_speech_final)
    release.set()
    await p.manual_workers[sid]
    state = await p.view(sid)
    assert state["calls"] == 1
    assert state["scheduling"]["pending_segments"] == int(new_speech_final)
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    questions = Discovery(p.service.storage).detail(mid)["questions"]
    assert len(questions) == 1 and questions[0]["text"] == "What happened?"
    with p.service.storage.connection() as db:
        metadata = json.loads(
            db.execute(
                "SELECT metadata FROM developer_traces WHERE session_id=?", (sid,)
            ).fetchone()[0]
        )
    assert metadata["question_decision"] == "accepted"
    assert metadata["spoken_questions_rejected"] == 0
    await asyncio.sleep(0.03)
    assert (await p.view(sid))["calls"] == 1


@pytest.mark.parametrize("failure", ["timeout", "invalid", "incomplete", "provider"])
async def test_failure_does_not_advance_or_retry(manual_pipeline, failure):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)

    async def model(context):
        if failure == "timeout":
            raise TimeoutError()
        if failure == "provider":
            raise ProviderError("Gemini is temporarily unavailable (503).", "provider_http_503")
        if failure == "invalid":
            return answer(
                claims=[
                    {
                        "key": "bad",
                        "section": "workflows",
                        "text": "Unsupported",
                        "basis": "observed",
                        "source_ids": ["other-session"],
                    }
                ]
            )
        return FullSuggestion(complete=False, question="", rationale="", source_ids=[]), {}

    p.provider.analyze = model
    state = await run(p, sid)
    assert state["scheduling"]["job"]["status"] == "failed"
    assert state["calls"] == 1 and state["scheduling"]["pending_segments"] == 1
    assert Discovery(p.service.storage).memory(sid)["coverage"] == {}
    p.provider.analyze = lambda context: asyncio.sleep(0, result=answer())
    state = await run(p, sid)
    assert state["calls"] == 2 and state["scheduling"]["pending_segments"] == 0


async def test_correction_fences_output_and_full_retry_keeps_human_notes(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def model(context):
        entered.set()
        await release.wait()
        return answer()

    p.provider.analyze = model
    await p.submit_manual(sid, str(uuid4()))
    await entered.wait()
    await p.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                event_id="correction",
                segment_id="source-0",
                revision=1,
                text="Corrected text",
                is_final=True,
            )
        ),
    )
    release.set()
    await p.manual_workers[sid]
    assert (await p.view(sid))["scheduling"]["job"]["status"] == "stale"
    assert not Discovery(p.service.storage).memory(sid)["coverage"]
    state = await run(p, sid)
    assert state["scheduling"]["job"]["status"] == "succeeded"
    assert Discovery(p.service.storage).memory(sid)["coverage"] == {"source-0": 1}
    assert Discovery(p.service.storage).detail(mid)["notes"] == []


async def test_call_limit_and_input_limit_reserve_nothing(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)
    state = await p.state(sid)
    state["calls"] = p.settings.analysis_max_calls
    with pytest.raises(DomainError, match="limit reached"):
        await p.submit_manual(sid, str(uuid4()))
    assert p.manual.receipt(sid) is None
    context = {"scope": "full-transcript", "segments": [], "meeting": {"notes": ["x" * 1_000_000]}}
    with pytest.raises(ProviderError, match="Nothing was truncated"):
        request_payload(context)
    small = request_payload({"scope": "full-transcript", "segments": []})
    assert small["generationConfig"]["maxOutputTokens"] == 16384
    assert len(serialized_request(small)) < 1_000_000


async def test_cancel_and_restart_preserve_reserved_allowance(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)
    entered = asyncio.Event()

    async def model(context):
        entered.set()
        await asyncio.Event().wait()

    p.provider.analyze = model
    job = str(uuid4())
    await p.submit_manual(sid, job)
    await entered.wait()
    await p.stop(sid)
    assert p.manual.receipt(sid, job)["status"] == "interrupted"
    assert p.service.storage.experiment(sid)["calls"] == 1
    storage = Storage(p.service.storage.path)
    storage.initialize()
    assert storage.experiment(sid)["calls"] == 1
    assert not Discovery(storage).memory(sid)["coverage"]


async def test_full_topics_and_history_not_trimmed(manual_pipeline):  # noqa: F811
    from app.analysis import FullTopicSuggestion
    from app.topics import TopicUpdate

    p = manual_pipeline
    sid = create(p)
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    p.preferences.update("topics", 0)
    for i in range(8):
        await ingest(p, sid, i)

    async def model(context):
        return FullTopicSuggestion(
            complete=True,
            question="",
            rationale="",
            source_ids=[],
            topic={
                "action": "switch",
                "focus_id": "new:topic-7",
                "source_ids": ["source-7"],
                "updates": [
                    TopicUpdate(
                        topic_id=f"new:topic-{i}",
                        title=f"Discussion {i}",
                        summary=f"Synthetic topic {i}",
                        source_ids=[f"source-{i}"],
                    )
                    for i in range(8)
                ],
            },
        ), {}

    p.provider.analyze = model
    state = await run(p, sid)
    assert state["scheduling"]["job"]["status"] == "succeeded"
    repo = Discovery(p.service.storage)
    for i in range(12):
        repo.note(mid, f"Human note {i}")
    with p.service.storage.connection() as db:
        rid = db.execute("SELECT id FROM analysis_runs WHERE session_id=?", (sid,)).fetchone()[0]
        for i in range(35):
            db.execute(
                "INSERT INTO questions(id,session_id,run_id,text,normalized,rationale,status,"
                "revision,created_at,updated_at,discarded) "
                "VALUES(?,?,?,?,?,'test','asked',0,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',?)",
                (f"q-{i}", sid, rid, f"Question {i}", f"question {i}", i % 2),
            )
    seen = []

    async def review(context):
        seen.append(context)
        return FullTopicSuggestion(
            complete=True, question="", rationale="", source_ids=[], topic={}
        ), {}

    p.provider.analyze = review
    state = await run(p, sid)
    assert state["scheduling"]["job"]["status"] == "succeeded"
    assert len(seen[0]["topics"]["details"]) == 8
    assert len(seen[0]["meeting"]["notes"]) == 12
    assert len(seen[0]["meeting"]["previous_questions"]) == 35
    assert any(q["status"] == "discarded" for q in seen[0]["meeting"]["previous_questions"])
    assert len(repo.detail(mid)["notes"]) == 12
    assert len(repo.detail(mid)["questions"]) == 35


def test_migration_preserves_existing_schedule_and_source(tmp_path):
    from app.manual_analysis import ManualAnalysis

    storage = Storage(tmp_path / "migration.sqlite3")
    storage.initialize()
    old = storage.create("Existing meeting")
    storage.ingest(old["id"], TranscriptEvent(**payload(is_final=True)))
    before = storage.snapshot(old["id"])["segments"]
    # Reconstruct the previous schema using only this test's disposable database.
    with storage.connection() as db:
        db.execute("DROP TABLE manual_analysis_jobs")
        db.execute("ALTER TABLE meetings DROP COLUMN analysis_schedule")
        db.execute("ALTER TABLE meetings DROP COLUMN schedule_revision")
        db.execute("DELETE FROM schema_migrations WHERE version=11")
    storage.initialize()
    storage.initialize()
    assert ManualAnalysis(storage).settings(old["id"])["mode"] == "automatic"
    fresh = storage.create("New meeting")
    assert ManualAnalysis(storage).settings(fresh["id"])["mode"] == "manual"
    assert storage.snapshot(old["id"])["segments"] == before
    with storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_failed_commit_rolls_back_coverage_and_ack(manual_pipeline):  # noqa: F811
    p = manual_pipeline
    sid = create(p)
    await ingest(p, sid)
    with p.service.storage.connection() as db:
        db.execute(
            "CREATE TRIGGER reject_analysis BEFORE INSERT ON analysis_runs "
            "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
    job = str(uuid4())
    await p.submit_manual(sid, job)
    with pytest.raises(Exception, match="synthetic failure"):
        await p.manual_workers[sid]
    assert not p.discovery.memory(sid)["coverage"]
    assert p.manual.receipt(sid, job)["status"] == "interrupted"
    assert p.service.storage.experiment(sid)["calls"] == 1
