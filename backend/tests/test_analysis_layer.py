import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.analysis import MockAnalyzer, Suggestion
from app.analysis_state import (
    Claim,
    ContextBuilder,
    QuestionMatch,
    Workflow,
    WorkflowStep,
    empty_memory,
    reconcile,
    reduce_memory,
    validate_proposal,
)
from app.config import Settings
from app.discovery import Discovery
from app.main import create_app
from app.models import TranscriptEvent
from app.reports import SECTIONS, Reports, diagram
from app.storage import Storage
from tests.test_api import payload
from tests.test_discovery import setup_meeting
from tests.test_pipeline import pipeline as analysis_pipeline  # noqa: F401
from tests.test_pipeline import wait_until


def finished(client, mid, expected="complete"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(f"/meetings/{mid}/reports").json()
        if result["job"]["status"] == expected:
            return result
        if result["job"]["status"] == "failed" and expected != "failed":
            raise AssertionError(result)
        time.sleep(0.02)
    raise AssertionError("Report did not finish")


def test_context_batches_without_truncation_and_corrections():
    segments = [
        payload(
            event_id=f"e{i}",
            segment_id=f"s{i}",
            text="x" * 19000,
            is_final=True,
            start_ms=i,
            end_ms=i + 1,
        )
        for i in range(4)
    ]
    snapshot = {"segments": segments, "version": 4}
    meeting = {"brief": {}, "version": 0, "previous_questions": []}
    memory = empty_memory()
    seen = []
    for _ in segments:
        context = ContextBuilder().build(snapshot, meeting, memory, "Test")
        assert len(context["new_source_ids"]) == 1
        assert all(len(s["text"]) == 19000 for s in context["segments"])
        seen.extend(context["new_source_ids"])
        result = Suggestion(
            question="",
            rationale="",
            source_ids=[],
            claims=[
                Claim(
                    key=context["new_source_ids"][0],
                    section="workflows",
                    text="Observed",
                    basis="observed",
                    source_ids=context["new_source_ids"],
                )
            ],
        )
        memory = reduce_memory(memory, snapshot, context, result)
    assert seen == ["s0", "s1", "s2", "s3"]
    assert memory["cursor"] == 4
    assert ContextBuilder().build(snapshot, meeting, memory, "Test") is None
    segments[0] = {**segments[0], "revision": 20, "text": "Actually, no."}
    corrected = reconcile(memory, snapshot)
    assert "s0" not in corrected["coverage"]
    assert len(corrected["claims"]) == 3
    assert ContextBuilder().build(snapshot, meeting, corrected, "Test")["new_source_ids"] == ["s0"]


def test_proposal_rejects_cross_source_question_and_workflow_references():
    context = {
        "segments": [{"segment_id": "s1"}],
        "meeting": {"previous_questions": [{"id": "q1"}]},
    }
    suggestion = Suggestion(
        question="",
        rationale="",
        source_ids=[],
        matches=[QuestionMatch(question_id="other-meeting", status="answered", source_ids=["s1"])],
    )
    with pytest.raises(ValueError, match="Unknown question"):
        validate_proposal(suggestion, context)
    suggestion.matches = []
    suggestion.claims = [
        Claim(
            key="k",
            section="workflows",
            text="Made up",
            basis="observed",
            source_ids=["other-source"],
        )
    ]
    with pytest.raises(ValueError, match="evidence"):
        validate_proposal(suggestion, context)
    suggestion.claims = []
    suggestion.workflows = [
        Workflow(
            key="w",
            title="Flow",
            steps=[
                WorkflowStep(label="A", source_ids=["s1"]),
                WorkflowStep(label="B", source_ids=["s1"]),
            ],
            transitions=[["other-source"]],
        )
    ]
    with pytest.raises(ValueError, match="evidence"):
        validate_proposal(suggestion, context)
    suggestion.workflows[0].transitions = [[]]
    validate_proposal(suggestion, context)
    assert "order unknown" in diagram(suggestion.workflows[0].model_dump())


async def test_new_speech_commits_memory_but_defers_question(analysis_pipeline):  # noqa: F811
    pipeline = analysis_pipeline
    session = pipeline.service.storage.create("Streaming")
    sid = session["id"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = MockAnalyzer()

    async def slow(context):
        entered.set()
        await release.wait()
        return await original.analyze(context)

    pipeline.provider.analyze = slow
    await pipeline.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                is_final=True, speaker_id="customer", text="I copy a spreadsheet.", segment_id="s1"
            )
        ),
    )
    await asyncio.wait_for(entered.wait(), 3)
    await pipeline.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                event_id="e2",
                segment_id="s2",
                is_final=True,
                speaker_id="customer",
                text="It takes two hours.",
            )
        ),
    )
    release.set()
    await wait_until(lambda: bool(pipeline.states[sid]["runs"]))
    first = pipeline.states[sid]["runs"][0]
    assert not first["stale"] and not first["suggestion"]["question"]
    assert pipeline.discovery.memory(sid)["coverage"] == {"s1": 1}
    await wait_until(lambda: len(pipeline.states[sid]["runs"]) == 2)
    committed = await pipeline.service.read(pipeline.discovery.memory, sid)
    assert len(committed["coverage"]) == 2
    assert len(pipeline.discovery.detail(session["meeting_id"])["questions"]) == 1


def test_finalize_export_participants_revisions_and_isolation(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        _, mid, sid = setup_meeting(client)
        _, other, _ = setup_meeting(client)
        people = {
            "revision": 0,
            "participants": [
                {
                    "speaker_id": "cofounder",
                    "name": "Alex",
                    "interview_role": "interviewer",
                    "job_role": "Cofounder",
                }
            ],
        }
        assert client.put(f"/meetings/{mid}/participants", json=people).status_code == 200
        assert client.put(f"/meetings/{mid}/participants", json=people).status_code == 409
        event = payload(is_final=False, speaker_id="customer", text="Provisional")
        client.post(f"/sessions/{sid}/inject", json=event)
        final = {
            **event,
            "event_id": "final",
            "revision": 2,
            "is_final": True,
            "text": "I copy a spreadsheet. <script>alert(1)</script> [x](javascript:bad)",
        }
        client.post(f"/sessions/{sid}/inject", json=final)
        client.post(f"/meetings/{mid}/notes", json={"body": "Human context stays."})
        assert client.post(f"/meetings/{mid}/finalize", json={"session_id": sid}).status_code == 202
        listing = finished(client, mid)
        assert client.post(f"/sessions/{sid}/inject", json=payload()).status_code == 409
        rid = listing["reports"][0]["id"]
        report = client.get(f"/meetings/{mid}/reports/{rid}").json()
        assert [s["key"] for s in report["sections"]] == [k for k, _ in SECTIONS]
        assert report["sections"][0]["items"][0]["name"] == "Alex"
        assert report["sections"][0]["items"][1]["interview_role"] == "unknown"
        assert report["coverage"]["processed_segments"] == 1 and report["simulated"]
        assert client.get(f"/meetings/{other}/reports/{rid}").status_code == 404
        exported = client.get(f"/meetings/{mid}/transcript/export").json()
        assert len(exported["revisions"]) == 2 and exported["revisions"][0]["superseded"]
        markdown = client.get(f"/meetings/{mid}/transcript/export?format=markdown").text
        assert "<script>" not in markdown and "[x](javascript:" not in markdown
        assert "Provisional" in markdown and "Accepted revision history" in markdown
        assert (
            "Evidence and human notes"
            in client.get(f"/meetings/{mid}/reports/{rid}?format=markdown").text
        )
        client.post(f"/meetings/{mid}/finalize", json={"session_id": sid})
        assert len(finished(client, mid)["reports"]) == 1
        client.post(f"/meetings/{mid}/notes", json={"body": "Additional human context"})
        assert client.get(f"/meetings/{mid}/reports").json()["reports"][0]["outdated"]
        client.post(f"/meetings/{mid}/finalize", json={"session_id": sid})
        assert len(finished(client, mid)["reports"]) == 2
        assert client.get(f"/meetings/{mid}/reports/{rid}").json() == report
    with TestClient(create_app(settings)) as client:
        assert len(client.get(f"/meetings/{mid}/reports").json()["reports"]) == 2
        fresh = client.post(f"/meetings/{mid}/reset", json={"session_id": sid}).json()
        assert fresh["session"]["id"] != sid and len(fresh["notes"]) == 2
        assert client.get(f"/meetings/{mid}/reports").json()["reports"] == []
        assert (
            client.get(f"/meetings/{mid}/participants").json()["participants"][0]["name"] == "Alex"
        )
        with client.app.state.service.storage.connection() as db:
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_report_failure_retry_and_long_transcript(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        _, mid, sid = setup_meeting(client)

        async def fail(context):
            raise ValueError("provider unavailable")

        app.state.pipeline.provider.analyze = fail
        for i in range(40):
            event = payload(
                event_id=f"e{i}",
                segment_id=f"s{i}",
                is_final=True,
                speaker_id="customer",
                text=f"Statement {i}. " + "x" * 900,
                start_ms=i,
                end_ms=i + 1,
            )
            client.post(f"/sessions/{sid}/inject", json=event)
        client.post(f"/meetings/{mid}/finalize", json={"session_id": sid})
        assert not finished(client, mid, "failed")["reports"]
        assert not Discovery(app.state.service.storage).memory(sid)["coverage"]
        app.state.pipeline.provider = MockAnalyzer()
        client.post(f"/meetings/{mid}/finalize", json={"session_id": sid})
        rid = finished(client, mid)["reports"][0]["id"]
        report = client.get(f"/meetings/{mid}/reports/{rid}").json()
        assert report["coverage"]["processed_segments"] == 40
        assert len(report["evidence"]) == 40
        assert "Statement 0" in json.dumps(report) and "Statement 39" in json.dumps(report)


async def test_reset_cancels_report_and_old_result_cannot_write(analysis_pipeline):  # noqa: F811
    pipeline = analysis_pipeline
    session = pipeline.service.storage.create("Race")
    sid, mid = session["id"], session["meeting_id"]
    await pipeline.service.ingest(sid, TranscriptEvent(**payload(is_final=True)))
    await pipeline.service.stop(sid)
    await pipeline.stop(sid)
    entered = asyncio.Event()

    async def slow(context):
        entered.set()
        await asyncio.Event().wait()

    pipeline.provider.analyze = slow
    await pipeline.request_report(sid)
    await asyncio.wait_for(entered.wait(), 3)
    await pipeline.stop(sid)
    fresh = await pipeline.service.read(pipeline.discovery.reset, mid)
    assert fresh["session"]["id"] != sid
    assert Reports(pipeline.service.storage).list(mid)["reports"] == []
    assert not pipeline.discovery.memory(fresh["session"]["id"])["coverage"]


def test_migration_v2_preserves_source_and_is_idempotent(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    session = storage.create("Persist")
    storage.ingest(session["id"], TranscriptEvent(**payload(is_final=True)))
    with storage.connection() as db:
        for table in ("report_jobs", "reports", "meeting_participants", "analysis_state"):
            db.execute(f"DROP TABLE {table}")
        db.execute("DELETE FROM schema_migrations WHERE version=2")
    before = storage.snapshot(session["id"])["segments"]
    storage.initialize()
    storage.initialize()
    assert storage.snapshot(session["id"])["segments"] == before
    assert storage.path.with_suffix(".before-analysis.sqlite3").exists()
    with storage.connection() as db:
        assert [
            r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ] == [1, 2, 3, 4, 5]
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_question_matches_are_proposals_and_diagrams_have_evidence(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        _, mid, sid = setup_meeting(client)
        event = payload(is_final=True, speaker_id="customer", text="I copy a spreadsheet.")
        client.post(f"/sessions/{sid}/inject", json=event)
        from tests.test_discovery import wait_for

        question = wait_for(client, mid, lambda d: bool(d["questions"]))["questions"][0]

        async def proposal(context):
            return Suggestion(
                question="",
                rationale="",
                source_ids=[],
                matches=[
                    QuestionMatch(question_id=question["id"], status="answered", source_ids=["s2"])
                ],
                workflows=[
                    Workflow(
                        key="flow",
                        title="Observed workflow",
                        steps=[
                            WorkflowStep(
                                label='Copy "figures" <script>bad</script>', source_ids=["s2"]
                            ),
                            WorkflowStep(label="Check totals", source_ids=["s2"]),
                        ],
                        transitions=[["s2"]],
                    )
                ],
            ), {"promptTokenCount": 12}

        app.state.pipeline.provider.analyze = proposal
        client.post(
            f"/sessions/{sid}/inject",
            json=payload(
                event_id="answer",
                segment_id="s2",
                is_final=True,
                speaker_id="customer",
                text="First I copy figures, then I check totals.",
            ),
        )
        client.post(f"/meetings/{mid}/finalize", json={"session_id": sid})
        rid = finished(client, mid)["reports"][0]["id"]
        report = client.get(f"/meetings/{mid}/reports/{rid}").json()
        assert report["question_matches"][0]["status"] == "answered"
        assert client.get(f"/meetings/{mid}").json()["questions"][0]["status"] == "queued"
        assert report["workflows"][0]["sources"] == {"s2": 1}
        markdown = client.get(f"/meetings/{mid}/reports/{rid}?format=markdown").text
        assert "```mermaid" in markdown and "<script>" not in markdown
        assert "n0 --> n1" in markdown and "#evidence-" in markdown


def test_accepted_job_is_idempotent_and_failure_does_not_commit_memory(tmp_path):
    storage = Storage(tmp_path / "atomic.sqlite3")
    storage.initialize()
    sid = storage.create("Atomic")["id"]
    storage.ingest(sid, TranscriptEvent(**payload(is_final=True)))
    repo = Discovery(storage)
    context = {"job_id": "stable-job", "meeting": {"version": 0}}
    result = Suggestion(question="Specific?", rationale="test", source_ids=["seg-1"])
    run = {
        "input_version": 1,
        "source_revisions": {"seg-1": 1},
        "model": "simulated",
        "prompt_version": "test",
        "stale": False,
        "error": "",
        "suggestion": result.model_dump(),
    }
    memory = {**empty_memory(), "version": 1}
    repo.record_run(sid, context, "mock", run, memory)
    repo.record_run(sid, context, "mock", run, {**memory, "version": 99})
    assert repo.memory(sid)["version"] == 1
    with storage.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
    # An invalid FK rolls back the checkpoint and every artifact in the same transaction.
    import sqlite3

    context["job_id"] = "bad-job"
    run["suggestion"]["question"] = "Different question?"
    run["source_revisions"]["seg-1"] = 999
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_run(sid, context, "mock", run, {**memory, "version": 2})
    assert repo.memory(sid)["version"] == 1


async def test_trigger_coalesces_but_does_not_wait_forever():
    from app.analysis_state import TriggerPolicy

    wake = asyncio.Event()
    trigger = TriggerPolicy(idle_seconds=0.06, max_wait_seconds=0.15)
    started = time.monotonic()
    task = asyncio.create_task(trigger.collect(wake))
    for _ in range(8):
        await asyncio.sleep(0.025)
        wake.set()
    assert not await asyncio.wait_for(task, 0.2)
    assert 0.14 <= time.monotonic() - started < 0.5
