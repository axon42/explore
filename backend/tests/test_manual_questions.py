"""Manual follow-ups and cumulative topic state; synthetic providers only."""

from app.analysis import FullTopicProposal, FullTopicSuggestion, request_payload
from app.analysis_state import Workflow, WorkflowStep
from app.openai_analysis import request_payload as openai_payload
from app.reports import Reports
from app.topics import TopicUpdate, question_ready
from tests.test_manual_analysis import create, ingest, run
from tests.test_pipeline import pipeline  # noqa: F401


async def test_two_manual_reviews_keep_threads_workflows_and_accept_grounded_question(pipeline):  # noqa: F811
    p = pipeline
    p.preferences.update("topics", p.preferences.get()["revision"])
    sid = create(p)
    contexts = []

    async def analyze(context):
        contexts.append(context)
        index = len(contexts) - 1
        source = f"source-{index}"
        topic = f"new:workflow-{index}"
        return FullTopicSuggestion(
            complete=True,
            question="How long does checking the totals take?" if index == 0 else "",
            rationale="Timing is not established." if index == 0 else "No new useful question.",
            source_ids=["source-2"] if index == 0 else [],
            topic=FullTopicProposal(
                action="switch",
                focus_id=topic,
                source_ids=[source],
                readiness="developing",
                reason="A concrete workflow has been described.",
                question_intent="time spent checking" if index == 0 else "",
                updates=[
                    TopicUpdate(
                        topic_id=topic,
                        title=f"Workflow {index}",
                        summary=f"Supported synthetic workflow {index}",
                        source_ids=[source],
                    )
                ],
            ),
            workflows=[
                Workflow(
                    key="process",
                    topic_id=topic,
                    title=f"Process {index}",
                    steps=[
                        WorkflowStep(label="Export", source_ids=[source]),
                        WorkflowStep(label="Check", source_ids=[source]),
                    ],
                    transitions=[[source]],
                )
            ],
        ), {}

    p.provider.analyze = analyze
    await ingest(p, sid, 0, text="I export a spreadsheet and check the totals manually.")
    await ingest(p, sid, 2, text="The manual check is the difficult part; we have not timed it.")
    await run(p, sid)
    mid = p.service.storage.snapshot(sid)["session"]["meeting_id"]
    first = Reports(p.service.storage).live(mid)
    assert len(p.discovery.detail(mid)["questions"]) == 1
    assert (await p.view(sid))["result"]["suggestion"]["question"]
    await ingest(p, sid, 1, text="Separately, I export account records and check each transfer.")
    await run(p, sid)
    second = Reports(p.service.storage).live(mid)
    assert len(second["topics"]) == 2
    old = next(t for t in second["topics"] if t["id"] == first["topics"][0]["id"])
    assert old["summary"] == first["topics"][0]["summary"]
    assert old["status"] == "paused"
    assert len(p.discovery.memory(sid)["workflows"]) == 2
    assert len(contexts[1]["topics"]["index"]) == 1
    assert contexts[1]["memory"]["workflows"][0]["title"] == "Process 0"
    assert len(p.discovery.detail(mid)["questions"]) == 1
    with p.service.storage.connection() as db:
        import json

        metadata = json.loads(
            db.execute(
                "SELECT metadata FROM developer_traces ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
        )
    assert metadata["question_decision"] == "model_empty"


def test_explicit_manual_question_still_needs_routing_evidence_and_new_intent():
    result = FullTopicSuggestion(
        complete=True,
        question="How long?",
        rationale="Missing duration",
        source_ids=["s"],
        topic=FullTopicProposal(
            action="continue",
            focus_id="t",
            source_ids=["s"],
            readiness="developing",
            reason="Known workflow",
            question_intent="duration",
        ),
    )
    context = {
        "scheduling_mode": "manual",
        "review_kind": "live",
        "new_source_ids": ["s"],
        "topics": {
            "details": [{"id": "t", "questions_complete": True, "summary_sources": {"s": 0}}],
            "questions": [],
        },
    }
    assert question_ready(result, context)
    assert not question_ready(result, {**context, "scheduling_mode": "automatic"})
    result.topic.readiness = "uncertain"
    assert not question_ready(result, context)
    result.topic.readiness = "developing"
    result.source_ids = ["other"]
    assert not question_ready(result, context)
    result.source_ids = ["s"]
    context["topics"]["questions"] = [{"topic_id": "t", "intent": "duration"}]
    assert not question_ready(result, context)


def test_providers_receive_phase_specific_instructions():
    context = {"scope": "full-transcript", "review_kind": "live"}
    for build in (request_payload, lambda c: openai_payload(c, "synthetic-model")):
        payload = build(context)
        instruction = (
            payload.get("instructions") or payload["systemInstruction"]["parts"][0]["text"]
        )
        assert "explicit Analyze now" in instruction
        assert "Do not generate an in-meeting question" not in instruction
        payload = build({**context, "review_kind": "final"})
        instruction = (
            payload.get("instructions") or payload["systemInstruction"]["parts"][0]["text"]
        )
        assert "explicit Analyze now" not in instruction
        assert "Do not generate an in-meeting question" in instruction


def test_manual_question_can_cite_full_input_beyond_summary_citations():
    import pytest

    from app.analysis_state import validate_proposal
    from app.topics import question_block_reason

    result = FullTopicSuggestion(
        complete=True,
        question="How long does the check take?",
        rationale="Duration not stated",
        source_ids=["detail"],
        topic=FullTopicProposal(
            action="continue",
            focus_id="t",
            source_ids=["summary"],
            readiness="ready",
            reason="Known workflow",
            question_intent="duration",
        ),
    )
    context = {
        "scheduling_mode": "manual",
        "review_kind": "live",
        "scope": "full-transcript",
        "new_source_ids": ["summary", "detail"],
        "segments": [{"segment_id": "summary"}, {"segment_id": "detail"}],
        "meeting": {"previous_questions": []},
        "topics": {
            "details": [{"id": "t", "questions_complete": True, "summary_sources": {"summary": 0}}],
            "questions": [],
        },
    }
    validate_proposal(result, context)
    assert question_ready(result, context)
    assert (
        question_block_reason(result, {**context, "scheduling_mode": "automatic"})
        == "question_evidence_outside_topic_context"
    )
    result.source_ids = ["foreign"]
    with pytest.raises(ValueError, match="evidence"):
        validate_proposal(result, context)
    assert not question_ready(result, context)
