"""Final review uses isolated synthetic transcripts and a fake provider."""

from uuid import uuid4

import pytest

from app.analysis import ProviderError
from app.reports import Reports
from tests.test_manual_analysis import answer, create, ingest, run
from tests.test_pipeline import pipeline  # noqa: F401


async def finalize(p, sid):
    await p.service.stop(sid)
    await p.stop(sid)
    await p.request_report(sid)
    await p.report_workers[sid]


@pytest.mark.parametrize("mode", ["manual", "automatic"])
async def test_final_reviews_already_analyzed_input_once(pipeline, mode):  # noqa: F811
    p = pipeline
    sid = create(p)
    contexts = []

    async def analyze(context):
        contexts.append(context)
        return answer()

    p.provider.analyze = analyze
    await ingest(p, sid)
    await run(p, sid)
    if mode == "automatic":
        await p.set_schedule(sid, mode, 0)
    await finalize(p, sid)
    assert len(contexts) == 2
    assert contexts[-1]["review_kind"] == "final"
    assert contexts[-1]["scope"] == "full-transcript"
    assert not contexts[-1]["question_allowed"]
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    repo = Reports(p.service.storage)
    first = repo.list(mid)
    assert first["job"]["status"] == "complete"
    assert len(first["reports"]) == 1
    await p.request_report(sid)
    await p.report_workers[sid]
    assert len(contexts) == 2
    assert repo.list(mid)["reports"] == first["reports"]


async def test_failed_final_preserves_report_then_explicit_retry(pipeline):  # noqa: F811
    p = pipeline
    sid = create(p)
    await ingest(p, sid)
    await run(p, sid)
    await p.service.stop(sid)
    repo = Reports(p.service.storage)
    repo.generate(sid, "mock")
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    original = repo.list(mid)["reports"]
    before = p.discovery.memory(sid)

    async def fail(context):
        raise ProviderError("Synthetic unavailable", "provider_unavailable")

    p.provider.analyze = fail
    await p.request_report(sid)
    await p.report_workers[sid]
    assert repo.list(mid)["job"]["status"] == "failed"
    assert repo.list(mid)["reports"] == original
    assert p.discovery.memory(sid) == before

    async def success(context):
        return answer()

    p.provider.analyze = success
    await p.request_report(sid)
    await p.report_workers[sid]
    reports = repo.list(mid)["reports"]
    assert len(reports) == 2
    assert reports[1]["id"] == original[0]["id"]
    assert reports[0]["revision"] == 2


async def test_empty_end_uses_no_model_and_live_final_rejected(pipeline):  # noqa: F811
    p = pipeline
    sid = create(p)
    with pytest.raises(Exception, match="End the meeting"):
        await p.submit_manual(sid, str(uuid4()), final_review=True)
    await finalize(p, sid)
    assert (await p.view(sid))["calls"] == 0


async def test_duplicate_finalization_and_context_edit_reject_stale(pipeline):  # noqa: F811
    import asyncio

    p = pipeline
    sid = create(p)
    await ingest(p, sid)
    await p.service.stop(sid)
    started, release = asyncio.Event(), asyncio.Event()
    contexts = []

    async def blocked(context):
        contexts.append(context)
        started.set()
        await release.wait()
        return answer()

    p.provider.analyze = blocked
    await p.request_report(sid)
    await started.wait()
    worker = p.report_workers[sid]
    await p.request_report(sid)
    assert p.report_workers[sid] is worker
    with p.service.storage.connection() as db:
        db.execute(
            "UPDATE meetings SET context_version=context_version+1 WHERE id="
            "(SELECT meeting_id FROM sessions WHERE id=?)",
            (sid,),
        )
    release.set()
    await worker
    assert len(contexts) == 1
    assert p.manual.receipt(sid)["status"] == "stale"
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    assert Reports(p.service.storage).list(mid)["reports"] == []


def test_report_migration_preserves_legacy_payload_and_foreign_keys(tmp_path):
    from app.schema import migrate
    from app.storage import Storage

    storage = Storage(tmp_path / "migration.sqlite3")
    storage.initialize()
    sid = storage.create("Synthetic migration")["id"]
    with storage.connection() as db:
        db.execute("DROP TABLE reports")
        db.execute("""CREATE TABLE reports(id TEXT PRIMARY KEY, session_id TEXT NOT NULL
            REFERENCES sessions(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
            input_version INTEGER NOT NULL, context_version INTEGER NOT NULL,
            payload TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(session_id,revision), UNIQUE(session_id,input_version,context_version))""")
        db.execute("INSERT INTO reports VALUES('old',?,1,0,0,'{}','synthetic')", (sid,))
        db.execute("DELETE FROM schema_migrations WHERE version=13")
        migrate(db, "synthetic")
        assert tuple(db.execute("SELECT * FROM reports").fetchone()) == (
            "old",
            sid,
            1,
            0,
            0,
            "{}",
            "synthetic",
        )
        db.execute("INSERT INTO reports VALUES('new',?,2,0,0,'{}','synthetic')", (sid,))
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "invalid_evidence", "incomplete"])
async def test_final_recovers_failed_live_analysis_with_all_saved_speech(pipeline, failure):  # noqa: F811
    from app.analysis_state import Claim

    p = pipeline
    sid = create(p)
    await ingest(p, sid, 0)
    await run(p, sid)  # Earlier successful live analysis remains available.
    prior = p.discovery.memory(sid)
    await ingest(p, sid, 1)

    async def fail(context):
        if failure == "unavailable":
            raise ProviderError("Synthetic unavailable", "provider_unavailable")
        if failure == "timeout":
            raise TimeoutError()
        if failure == "incomplete":
            result, usage = answer()
            return result.model_copy(update={"complete": False}), usage
        return answer(
            claims=[
                Claim(
                    key="bad",
                    section="workflows",
                    text="Unsupported",
                    source_ids=["missing-source"],
                )
            ]
        )

    p.provider.analyze = fail
    await run(p, sid)
    assert p.manual.receipt(sid)["status"] == "failed"
    assert p.discovery.memory(sid) == prior
    contexts = []

    async def recover(context):
        contexts.append(context)
        return answer()

    p.provider.analyze = recover
    await finalize(p, sid)
    assert len(contexts) == 1
    assert {s["segment_id"] for s in contexts[0]["segments"]} == {"source-0", "source-1"}
    assert contexts[0]["memory"]["claims"] == prior["claims"]
    assert p.manual.receipt(sid)["status"] == "succeeded"
    assert (await p.view(sid))["scheduling"]["pending_segments"] == 0
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    assert Reports(p.service.storage).list(mid)["job"]["status"] == "complete"


async def test_final_limit_explains_block_without_provider_request(pipeline):  # noqa: F811
    p = pipeline
    sid = create(p)
    await ingest(p, sid)
    p.settings.final_review_max_calls = 0
    calls = []

    async def unexpected(context):
        calls.append(context)
        return answer()

    p.provider.analyze = unexpected
    await finalize(p, sid)
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    result = Reports(p.service.storage).list(mid)
    assert result["job"]["status"] == "failed"
    assert "call limit is exhausted" in result["job"]["error"]
    assert "No model request was sent" in result["job"]["error"]
    assert not calls and not result["reports"]
    assert p.manual.receipt(sid) is None


async def test_final_allowance_survives_live_exhaustion_and_restart(pipeline):  # noqa: F811
    from app.manual_analysis import ManualAnalysis

    p = pipeline
    sid = create(p)
    await ingest(p, sid)
    state = await p.state(sid)
    state["calls"] = p.settings.analysis_max_calls
    await p.save(sid)
    calls = []

    async def fail(context):
        calls.append(context)
        raise ProviderError("Synthetic failure")

    p.provider.analyze = fail
    await finalize(p, sid)
    assert len(calls) == 1
    p.manual = ManualAnalysis(p.service.storage)
    assert p.manual.final_attempts(sid) == 1
    await p.request_report(sid)
    await p.report_workers[sid]
    assert len(calls) == 2
    await p.request_report(sid)
    await p.report_workers[sid]
    assert len(calls) == 2
    assert (await p.state(sid))["calls"] == p.settings.analysis_max_calls
    other = create(p)
    assert p.manual.final_attempts(other) == 0


@pytest.mark.parametrize("valid_evidence", [True, False])
async def test_final_opportunity_claim_downgrades_certainty_not_evidence(pipeline, valid_evidence):  # noqa: F811
    from app.analysis import FullSuggestion

    p = pipeline
    sid = create(p)
    await ingest(p, sid)

    async def analyze(context):
        return FullSuggestion.model_validate(
            {
                "complete": True,
                "question": "",
                "rationale": "",
                "source_ids": [],
                "claims": [
                    {
                        "key": "automation",
                        "section": "opportunities",
                        "text": "Potential automation to validate",
                        "basis": "observed",
                        "source_ids": ["source-0" if valid_evidence else "unknown"],
                    }
                ],
            }
        ), {}

    p.provider.analyze = analyze
    await finalize(p, sid)
    memory = p.discovery.memory(sid)
    if valid_evidence:
        assert memory["claims"][0]["basis"] == "inferred"
        assert p.manual.receipt(sid)["status"] == "succeeded"
    else:
        assert not memory["claims"]
        assert p.manual.receipt(sid)["status"] == "failed"


@pytest.mark.parametrize("transitions", [[], [["source-0"], ["source-0"]]])
async def test_final_misaligned_connections_are_unknown(pipeline, transitions):  # noqa: F811
    from app.analysis_state import Workflow, WorkflowStep

    p = pipeline
    sid = create(p)
    await ingest(p, sid)

    async def analyze(context):
        return answer(
            workflows=[
                Workflow(
                    key="flow",
                    title="Synthetic workflow",
                    steps=[
                        WorkflowStep(label="A", source_ids=["source-0"]),
                        WorkflowStep(label="B", source_ids=["source-0"]),
                    ],
                    transitions=transitions,
                )
            ]
        )

    p.provider.analyze = analyze
    await finalize(p, sid)
    assert p.manual.receipt(sid)["status"] == "succeeded"
    assert p.discovery.memory(sid)["workflows"][0]["transitions"] == [[]]


async def test_misaligned_connections_cannot_hide_invalid_evidence(pipeline):  # noqa: F811
    from app.analysis_state import Workflow, WorkflowStep

    p = pipeline
    sid = create(p)
    await ingest(p, sid)

    async def analyze(context):
        return answer(
            workflows=[
                Workflow(
                    key="flow",
                    title="Synthetic workflow",
                    steps=[
                        WorkflowStep(label="A", source_ids=["source-0"]),
                        WorkflowStep(label="B", source_ids=["source-0"]),
                    ],
                    transitions=[["source-0"], ["unknown"]],
                )
            ]
        )

    p.provider.analyze = analyze
    await finalize(p, sid)
    assert p.manual.receipt(sid)["status"] == "failed"
    assert not p.discovery.memory(sid)["workflows"]
