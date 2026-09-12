import asyncio
import json
from pathlib import Path

import pytest

from app.analysis import TopicSuggestion, gemini_output_schema
from app.models import TranscriptEvent
from app.reports import Reports, report_markdown
from app.storage import Storage
from app.topics import TopicProposal, TopicUpdate, validate_topics
from tests.test_api import payload
from tests.test_pipeline import pipeline  # noqa: F401

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/topic-switching-v1.json").read_text())


@pytest.mark.parametrize("invalid_evidence", [False, True])
async def test_first_topic_continuation_keeps_evidence_validation(pipeline, invalid_evidence):  # noqa: F811
    from app.analysis import MockAnalyzer

    sid, mid = setup(pipeline)
    mock = MockAnalyzer()
    proposals = []

    async def first_topic(context):
        result, _ = await mock.analyze(context)
        result.topic.action = "continue"
        if invalid_evidence:
            result.topic.source_ids = ["not-in-this-session"]
        proposals.append(result)
        return result, {"totalTokenCount": 123}

    pipeline.provider.analyze = first_topic
    await inject(pipeline, sid, 0, FIXTURE["turns"][0]["text"])
    await pipeline.process_batch(sid)
    state = await pipeline.view(sid)
    topics = Reports(pipeline.service.storage).live(mid)["topics"]
    assert proposals[0].topic.action == "continue"  # normalization is pure
    assert state["calls"] == 1
    assert state["runs"][-1]["usage"]["totalTokenCount"] == 123
    if invalid_evidence:
        assert topics == []
        assert not pipeline.discovery.memory(sid)["coverage"]
        assert state["runs"][-1]["validation_code"] == "topic_routing_evidence"
        assert "not-in-this-session" not in state["error"]
    else:
        assert len(topics) == 1 and topics[0]["status"] == "active"
        assert state["error"] == ""
        assert pipeline.discovery.memory(sid)["topic_state"]["action"] == "switch"
        assert pipeline.discovery.memory(sid)["coverage"] == {"part-0": 1}


def test_first_topic_schema_and_safe_validation_codes():
    from app.analysis_errors import validation_failure

    ctx = {"strategy": "topics-v1", "topics": {"index": [], "focus_id": ""}}
    schema = gemini_output_schema(ctx)
    assert schema["properties"]["topic"]["properties"]["action"]["enum"] == ["switch", "uncertain"]
    ctx["topics"]["index"] = [{"id": "a", "title": "Reporting"}]
    assert (
        "resume" in gemini_output_schema(ctx)["properties"]["topic"]["properties"]["action"]["enum"]
    )
    code, error = validation_failure(ValueError("private-text-and-key"))
    assert code == "proposal_invalid"
    assert "private-text-and-key" not in error


def setup(pipeline):  # noqa: F811
    pipeline.preferences.update("topics", pipeline.preferences.get()["revision"])
    pipeline.service.on_final = lambda sid: None
    session = pipeline.service.storage.create("Synthetic topic interview")
    pipeline.wakes[session["id"]] = asyncio.Event()
    return session["id"], session["meeting_id"]


async def inject(pipeline, sid, index, text, revision=1, final=True):  # noqa: F811
    await pipeline.service.ingest(
        sid,
        TranscriptEvent(
            **payload(
                event_id=f"event-{index}-{revision}",
                segment_id=f"part-{index}",
                revision=revision,
                speaker_id="customer",
                text=text,
                start_ms=index * 5000,
                end_ms=index * 5000 + 4000,
                is_final=final,
            )
        ),
    )


async def run_fixture(pipeline, sid):  # noqa: F811
    for i, turn in enumerate(FIXTURE["turns"]):
        await inject(pipeline, sid, i, turn["text"])
        assert await pipeline.process_batch(sid)


async def test_switch_resume_short_correction_and_final_report(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    topics = []
    for i, turn in enumerate(FIXTURE["turns"]):
        await inject(pipeline, sid, i, turn["text"])
        assert await pipeline.process_batch(sid)
        memory = pipeline.discovery.memory(sid)
        topics.append(memory["topic_state"]["focus_id"])
        assert memory["topic_state"]["readiness"] == turn["readiness"]
        if not turn["question_allowed"]:
            assert not pipeline.states[sid]["runs"][-1]["suggestion"]["question"]
    assert topics[0] == topics[1] == topics[4] == topics[5]
    assert topics[2] == topics[3] != topics[0]
    assert len(pipeline.discovery.memory(sid)["coverage"]) == 6
    source = Reports(pipeline.service.storage).export(mid)
    assert len(source["topics"]) == 2
    reporting = next(t for t in source["topics"] if t["title"] == "Operational reporting")
    assert {e["segment_id"] for e in reporting["evidence"]} >= {"part-0", "part-4", "part-5"}
    assert all(s["text"] == FIXTURE["turns"][i]["text"] for i, s in enumerate(source["segments"]))
    await pipeline.service.stop(sid)
    await pipeline.finalize(sid)
    reports = Reports(pipeline.service.storage)
    with pipeline.service.storage.connection() as db:
        saved = json.loads(
            db.execute("SELECT payload FROM reports WHERE session_id=?", (sid,)).fetchone()[0]
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert saved["schema_version"] == 2
    assert len(saved["topics"]) == 2
    assert any(t["status"] == "paused" for t in saved["topics"])
    markdown = report_markdown(saved)
    assert "Operational reporting" in markdown and "Recruiting" in markdown
    assert all(turn["text"].split()[0] in markdown for turn in FIXTURE["turns"])
    assert reports.list(mid)["job"]["status"] == "complete"


async def test_corrected_evidence_invalidates_summary_and_reset_clears_topics(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    await inject(
        pipeline, sid, 4, "The reporting delay was five minutes, not six hours.", revision=2
    )
    export = Reports(pipeline.service.storage).export(mid)
    topic = next(t for t in export["topics"] if t["title"] == "Operational reporting")
    assert topic["needs_review"] and topic["summary"] == ""
    assert any(e["superseded"] for e in topic["evidence"])
    await pipeline.process_batch(sid)
    before = pipeline.discovery.detail(mid)
    revision = before["meeting"]["context_version"]
    await pipeline.service.stop(sid)
    pipeline.discovery.preferences(mid, revision, archived=True)
    assert Reports(pipeline.service.storage).export(mid)["topics"]
    pipeline.discovery.preferences(mid, revision + 1, archived=False)
    fresh = pipeline.discovery.reset(mid)
    assert fresh["session"]["id"] != sid
    assert not Reports(pipeline.service.storage).export(mid)["topics"]
    with pipeline.service.storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_topic_claim_keys_are_independent_and_discarded_intent_is_durable(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    questions = pipeline.discovery.detail(mid)["questions"]
    assert len(questions) == 1
    q = questions[0]
    pipeline.discovery.question_status(mid, q["id"], q["revision"], "discarded")
    # Age the disposable test question to isolate intent dedupe from cooldown.
    with pipeline.service.storage.connection() as db:
        db.execute(
            "UPDATE questions SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (q["id"],)
        )
    await inject(pipeline, sid, 6, "Reporting still follows the same process we discussed earlier.")
    await pipeline.process_batch(sid)
    assert len(pipeline.discovery.detail(mid)["questions"]) == 1
    assert pipeline.discovery.detail(mid)["questions"][0]["status"] == "discarded"
    pipeline.states.clear()
    assert pipeline.discovery.memory(sid)["topic_state"]["focus_id"]


def context():
    return {
        "segments": [
            {
                "segment_id": "s1",
                "revision": 1,
                "text": "Synthetic",
                "is_final": True,
                "start_ms": 0,
            }
        ],
        "new_source_ids": ["s1"],
        "topics": {
            "focus_id": "a",
            "index": [{"id": "a", "title": "Reporting"}, {"id": "b", "title": "Hiring"}],
            "details": [{"id": "a", "questions_complete": True}],
            "questions": [],
        },
    }


def proposal(**kwargs):
    return TopicSuggestion(question="", rationale="", source_ids=[], topic=TopicProposal(**kwargs))


@pytest.mark.parametrize(
    "change",
    [
        {"action": "switch", "focus_id": "foreign", "source_ids": ["s1"]},
        {"action": "continue", "focus_id": "b", "source_ids": ["s1"]},
        {"action": "resume", "focus_id": "a", "source_ids": ["s1"]},
        {"action": "switch", "focus_id": "b", "source_ids": ["foreign-source"]},
        {
            "updates": [
                TopicUpdate(
                    topic_id="b", title="Hiring", summary="Needs evidence", source_ids=["s1"]
                )
            ]
        },
    ],
)
def test_invalid_routing_fails_closed(change):
    with pytest.raises(ValueError):
        validate_topics(proposal(**change), context())


def test_gemini_schema_requires_topic_object_only_for_topic_strategy():
    assert "topic" not in gemini_output_schema()["properties"]
    schema = gemini_output_schema({"strategy": "topics-v1"})
    assert "topic" in schema["required"]
    assert "readiness" in schema["properties"]["topic"]["properties"]


def test_migration_preserves_existing_data_and_old_reports(tmp_path):
    storage = Storage(tmp_path / "migration.sqlite3")
    storage.initialize()
    session = storage.create("Legacy")
    storage.ingest(session["id"], TranscriptEvent(**payload(is_final=True)))
    with storage.connection() as db:
        for table in ("question_topics", "topic_artifacts", "topic_evidence", "topics"):
            db.execute(f"DROP TABLE {table}")
        db.execute("DELETE FROM schema_migrations WHERE version=4")
    before = storage.snapshot(session["id"])["segments"]
    storage.initialize()
    storage.initialize()
    assert storage.snapshot(session["id"])["segments"] == before
    assert Reports(storage).export(session["meeting_id"])["topics"] == []
    with storage.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_index_only_resume_hydrates_before_question(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    # Create additional real topics through the validated pipeline, not fabricated database rows.
    captured = []

    async def extra(ctx):
        captured.append(ctx)
        ref = ctx["new_source_ids"][-1]
        i = len(captured)
        return proposal(
            action="switch",
            focus_id=f"new:extra-{i}",
            source_ids=[ref],
            updates=[
                TopicUpdate(
                    topic_id=f"new:extra-{i}",
                    title=f"Extra {i}",
                    summary="Synthetic detail",
                    source_ids=[ref],
                )
            ],
        ), {}

    pipeline.provider.analyze = extra
    for i in range(3):
        await inject(pipeline, sid, i + 6, "A separate workflow needs more discussion.")
        assert await pipeline.process_batch(sid)
    target = Reports(pipeline.service.storage).export(mid)["topics"][0]["id"]

    async def resume(ctx):
        captured.append(ctx)
        return TopicSuggestion(
            question="What happened during that wait?",
            rationale="test",
            source_ids=ctx["new_source_ids"],
            topic=TopicProposal(
                action="resume" if ctx["topics"]["focus_id"] != target else "continue",
                focus_id=target,
                source_ids=ctx["new_source_ids"],
                readiness="ready",
                reason="Synthetic return",
                question_intent="new unresolved detail",
            ),
        ), {}

    pipeline.provider.analyze = resume
    await inject(pipeline, sid, 9, "Returning to the earlier issue, there is more to explain.")
    assert await pipeline.process_batch(sid)
    assert target not in {d["id"] for d in captured[-1]["topics"]["details"]}
    assert not pipeline.states[sid]["runs"][-1]["suggestion"]["question"]
    await inject(pipeline, sid, 10, "The earlier reporting work also includes a review stage.")
    assert await pipeline.process_batch(sid)
    assert target in {d["id"] for d in captured[-1]["topics"]["details"]}
    assert any(s["segment_id"] == "part-4" for s in captured[-1]["segments"])


async def test_same_claim_key_different_topics_and_invalid_proposal_atomicity(pipeline):  # noqa: F811
    from app.analysis_state import Claim

    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    topics = Reports(pipeline.service.storage).export(mid)["topics"]

    async def claims(ctx):
        ref = ctx["new_source_ids"][0]
        result = proposal()
        result.claims = [
            Claim(
                key="duration",
                topic_id=t["id"],
                section="pain_impact",
                text=t["title"],
                basis="observed",
                source_ids=[ref],
            )
            for t in topics
        ]
        return result, {}

    pipeline.provider.analyze = claims
    await inject(pipeline, sid, 6, "These are two independent processes with different durations.")
    assert await pipeline.process_batch(sid)
    stored = pipeline.discovery.memory(sid)
    assert len([c for c in stored["claims"] if c["key"] == "duration"]) == 2

    async def invalid(ctx):
        return proposal(
            action="switch", focus_id="foreign-topic", source_ids=ctx["new_source_ids"]
        ), {}

    pipeline.provider.analyze = invalid
    await inject(pipeline, sid, 7, "Another update.")
    assert not await pipeline.process_batch(sid)
    assert pipeline.discovery.memory(sid) == stored
    assert pipeline.states[sid]["analysis_status"] == "error"
    assert len(Reports(pipeline.service.storage).export(mid)["topics"]) == 2


async def test_question_readiness_new_speech_and_context_changes(pipeline):  # noqa: F811
    import asyncio

    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    started, release = asyncio.Event(), asyncio.Event()
    original = pipeline.provider.analyze

    async def delayed(ctx):
        started.set()
        await release.wait()
        return await original(ctx)

    pipeline.provider.analyze = delayed
    await inject(pipeline, sid, 6, "Reporting includes several additional checks.")
    task = asyncio.create_task(pipeline.process_batch(sid))
    await started.wait()
    detail = pipeline.discovery.detail(mid)
    pipeline.discovery.preferences(mid, detail["meeting"]["context_version"], interval=0)
    release.set()
    assert not await task
    assert "part-6" not in pipeline.discovery.memory(sid)["coverage"]
    assert pipeline.states[sid]["runs"][-1]["stale"]


def test_context_budget_reduces_derived_memory_without_truncating_evidence():
    from app.topics import MAX_CONTEXT_CHARS, add_topic_context

    ctx = context()
    ctx.update(
        meeting={"notes": [{"body": "x" * 4000} for _ in range(10)], "previous_questions": []},
        memory={"claims": [], "workflows": [], "matches": []},
    )
    ctx["segments"][0]["text"] = "x" * 20000
    catalog = ctx.pop("topics")
    catalog["evidence"] = []
    catalog["omitted_topics"] = 0
    memory = {"claims": [{"text": "y" * 1000} for _ in range(40)], "workflows": []}
    built = add_topic_context(ctx, memory, catalog)
    assert len(json.dumps(built, ensure_ascii=False)) <= MAX_CONTEXT_CHARS
    assert built["segments"][0]["text"] == "x" * 20000
    assert built["omitted"]["claims"] > 0
    assert catalog["evidence"] == []
    assert memory["claims"][0]["text"] == "y" * 1000


async def test_topic_commit_is_idempotent_and_cross_session_update_rolls_back(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    await run_fixture(pipeline, sid)
    with pipeline.service.storage.connection() as db:
        row = db.execute(
            "SELECT * FROM analysis_runs WHERE session_id=? ORDER BY rowid DESC LIMIT 1", (sid,)
        ).fetchone()
        ctx, run = json.loads(row["input_json"]), json.loads(row["output_json"])
    memory = pipeline.discovery.memory(sid)
    before = Reports(pipeline.service.storage).export(mid)["topics"]
    pipeline.discovery.record_run(sid, ctx, "mock", run, memory)
    assert Reports(pipeline.service.storage).export(mid)["topics"] == before
    other = pipeline.service.storage.create("Other workspace interview")
    foreign = copy = json.loads(json.dumps(ctx))
    foreign["job_id"] = "foreign-job"
    foreign["session_id"] = other["id"]
    # Same source IDs in another session must still not authorize updating the first topic.
    for i, turn in enumerate(FIXTURE["turns"]):
        await inject(pipeline, other["id"], i, turn["text"])
    run["suggestion"]["topic"]["updates"] = [
        {
            "topic_id": before[0]["id"],
            "title": "Wrong owner",
            "summary": "Synthetic",
            "source_ids": ["part-4"],
            "assignment": "accepted",
        }
    ]
    with pytest.raises(ValueError, match="another session"):
        pipeline.discovery.record_run(other["id"], copy, "mock", run, memory)
    assert Reports(pipeline.service.storage).export(mid)["topics"] == before
    assert pipeline.discovery.memory(other["id"])["coverage"] == {}
    with pipeline.service.storage.connection() as db:
        assert not db.execute("SELECT 1 FROM analysis_runs WHERE id='foreign-job'").fetchone()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_reset_cancels_topic_job_and_budget_preserves_pending_sources(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    await inject(pipeline, sid, 0, FIXTURE["turns"][0]["text"])
    entered = asyncio.Event()

    async def blocked(ctx):
        entered.set()
        await asyncio.Event().wait()

    pipeline.provider.analyze = blocked
    pipeline.workers[sid] = asyncio.create_task(pipeline.process_batch(sid))
    await entered.wait()
    await pipeline.service.stop(sid)
    await pipeline.stop(sid)
    fresh = pipeline.discovery.reset(mid)
    assert not Reports(pipeline.service.storage).export(mid)["topics"]
    assert fresh["session"]["id"] != sid
    with pipeline.service.storage.connection() as db:
        assert not db.execute("SELECT 1 FROM topics WHERE session_id=?", (sid,)).fetchone()
    pipeline.settings.analysis_max_calls = 1
    from app.analysis import MockAnalyzer

    pipeline.provider = MockAnalyzer()
    new_sid = fresh["session"]["id"]
    await inject(pipeline, new_sid, 0, FIXTURE["turns"][0]["text"])
    assert await pipeline.process_batch(new_sid)
    await inject(pipeline, new_sid, 1, "No, that happened once.")
    assert not await pipeline.process_batch(new_sid)
    assert pipeline.states[new_sid]["analysis_status"] == "limited"
    assert "part-1" not in pipeline.discovery.memory(new_sid)["coverage"]
    assert len(Reports(pipeline.service.storage).export(mid)["segments"]) == 2


async def test_gemini_topic_contract_roundtrip_uses_one_mocked_call(monkeypatch):
    import httpx

    from app.analysis import GeminiAnalyzer, ProviderError

    client = httpx.AsyncClient
    calls = []
    output = proposal(
        action="switch",
        focus_id="new:reporting",
        source_ids=["s1"],
        updates=[
            TopicUpdate(
                topic_id="new:reporting", title="Reporting", summary="Synthetic", source_ids=["s1"]
            )
        ],
    )

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": output.model_dump_json()}]},
                    }
                ],
                "usageMetadata": {"totalTokenCount": 42},
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )
    ctx = context()
    ctx["strategy"] = "topics-v1"
    result, usage = await GeminiAnalyzer("synthetic-key", "synthetic-model").analyze(ctx)
    assert isinstance(result, TopicSuggestion) and usage["totalTokenCount"] == 42
    assert len(calls) == 1
    assert calls[0]["generationConfig"]["maxOutputTokens"] == 4096
    assert "topic" in calls[0]["generationConfig"]["responseJsonSchema"]["required"]
    assert "Track persistent topics" in calls[0]["systemInstruction"]["parts"][0]["text"]
    # Removing the required topic cannot silently fall back to eager legacy behavior.
    from app.analysis import Suggestion

    output = Suggestion(question="", rationale="", source_ids=[])
    with pytest.raises(ProviderError, match="outside the analysis contract"):
        await GeminiAnalyzer("synthetic-key", "synthetic-model").analyze(ctx)


def test_duplicate_new_topic_titles_and_blank_labels_are_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TopicUpdate(topic_id="new:blank", title="   ", summary="Synthetic", source_ids=["s1"])
    with pytest.raises(ValueError, match="already exists"):
        validate_topics(
            proposal(
                updates=[
                    TopicUpdate(
                        topic_id="new:first",
                        title="Billing",
                        summary="Synthetic",
                        source_ids=["s1"],
                    ),
                    TopicUpdate(
                        topic_id="new:second",
                        title="billing",
                        summary="Synthetic",
                        source_ids=["s1"],
                    ),
                ]
            ),
            context(),
        )
