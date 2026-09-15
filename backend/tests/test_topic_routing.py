"""Routing omissions must not lose evidence or require extra provider calls."""

import pytest

from app.analysis import TopicSuggestion
from app.reports import Reports
from app.topics import TopicProposal, TopicUpdate
from tests.test_pipeline import pipeline  # noqa: F401
from tests.test_topics import inject, setup

TEXT = (
    "Last Friday our weekly reporting process took six hours because the operations team "
    "was waiting for access approval. Checking the figures took two hours once access was "
    "available, and we had to delay sending the report to the customer."
)


def routed(source, *, focus="new:reporting", action="switch", evidence=None):
    return TopicSuggestion(
        question="What happened to the customer waiting for Friday's report?",
        rationale="Clarify the impact of the stated delay.",
        source_ids=[source],
        topic=TopicProposal(
            action=action,
            focus_id=focus,
            source_ids=[] if evidence is None else evidence,
            readiness="ready",
            reason="A concrete incident has been described.",
            question_intent="impact of delayed report",
            updates=[
                TopicUpdate(
                    topic_id=focus,
                    title="Reporting",
                    summary="Friday's report waited for access approval.",
                    source_ids=[source],
                )
            ],
        ),
    )


async def test_explicit_focus_update_recovers_missing_routing_citations(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    output = routed("part-0")

    async def analyze(context):
        assert context["new_source_ids"] == ["part-0"]
        return output, {"totalTokenCount": 37}

    pipeline.provider.analyze = analyze
    await inject(pipeline, sid, 0, TEXT)
    assert await pipeline.process_batch(sid)
    state = await pipeline.view(sid)
    assert state["error"] == "" and state["calls"] == 1
    assert state["runs"][-1]["usage"]["totalTokenCount"] == 37
    assert state["runs"][-1]["suggestion"]["question"] == output.question
    assert state["runs"][-1]["suggestion"]["topic"]["source_ids"] == ["part-0"]
    assert output.topic.source_ids == []  # Provider proposal remains immutable.
    assert pipeline.discovery.memory(sid)["coverage"] == {"part-0": 1}
    assert len(Reports(pipeline.service.storage).live(mid)["topics"]) == 1
    assert len(pipeline.discovery.context(sid)["previous_questions"]) == 1
    assert not await pipeline.process_batch(sid)
    assert (await pipeline.view(sid))["calls"] == 1


def test_continue_can_repeat_known_focus_but_not_guess_a_switch():
    from app.topics import normalize_topic_routing, validate_topics
    from tests.test_topics import context

    ctx = context()
    output = routed("s1", focus="a", action="continue")
    output.topic.focus_id = ""
    normalized = normalize_topic_routing(output, ctx)
    validate_topics(normalized, ctx)
    assert normalized.topic.focus_id == "a"
    assert normalized.topic.source_ids == ["s1"]
    assert output.topic.focus_id == "" and output.topic.source_ids == []

    for action in ("switch", "resume"):
        output.topic.action = action
        normalized = normalize_topic_routing(output, ctx)
        assert normalized.topic.focus_id == ""
        with pytest.raises(ValueError, match="Routing needs evidence"):
            validate_topics(normalized, ctx)


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_evidence",
        "foreign_focus",
        "invalid_supplied_evidence",
        "no_update",
        "unrelated_update",
        "provisional",
        "duplicate_update",
    ],
)
async def test_unsafe_routing_is_atomic_and_can_retry_saved_transcript(pipeline, fault):  # noqa: F811
    sid, mid = setup(pipeline)
    output = routed("part-0")
    if fault == "foreign_evidence":
        output.topic.updates[0].source_ids = ["foreign-source"]
    elif fault == "foreign_focus":
        output.topic.focus_id = "foreign-topic"
    elif fault == "invalid_supplied_evidence":
        output.topic.source_ids = ["foreign-source"]
    elif fault == "no_update":
        output.topic.updates = []
    elif fault == "unrelated_update":
        output.topic.updates[0].topic_id = "new:unrelated"
    elif fault == "provisional":
        output.topic.updates[0].assignment = "provisional"
    else:
        output.topic.updates.append(output.topic.updates[0].model_copy(deep=True))

    async def analyze(ctx):
        assert ctx["new_source_ids"] == ["part-0"]
        return output, {"totalTokenCount": 37}

    pipeline.provider.analyze = analyze
    await inject(pipeline, sid, 0, TEXT)
    assert not await pipeline.process_batch(sid)
    assert pipeline.discovery.memory(sid)["coverage"] == {}
    assert Reports(pipeline.service.storage).live(mid)["topics"] == []
    assert pipeline.discovery.context(sid)["previous_questions"] == []
    state = await pipeline.view(sid)
    assert state["analysis_status"] == "error" and state["calls"] == 1
    assert "foreign-" not in state["error"]
    assert pipeline.service.storage.snapshot(sid)["segments"][0]["text"] == TEXT

    # Corrected provider output retries the same unprocessed evidence; no reinjection.
    output = routed("part-0")
    assert await pipeline.process_batch(sid)
    assert (await pipeline.view(sid))["error"] == ""
    assert len(pipeline.discovery.context(sid)["previous_questions"]) == 1
    assert not await pipeline.process_batch(sid)
    assert (await pipeline.view(sid))["calls"] == 2


async def test_no_question_batch_still_updates_threads_with_its_own_evidence(pipeline):  # noqa: F811
    sid, mid = setup(pipeline)
    output = routed("part-0")
    output.question = ""
    output.source_ids = []
    output.topic.readiness = "developing"

    async def analyze(ctx):
        assert not ctx["question_allowed"]
        return output, {}

    pipeline.provider.analyze = analyze
    await inject(pipeline, sid, 0, TEXT)
    assert await pipeline.process_batch(sid, allow_questions=False)
    assert len(Reports(pipeline.service.storage).live(mid)["topics"]) == 1
    assert pipeline.discovery.context(sid)["previous_questions"] == []
    assert pipeline.discovery.memory(sid)["coverage"] == {"part-0": 1}


def test_uncertain_and_unrelated_citations_are_never_promoted():
    from app.topics import normalize_topic_routing, question_ready, validate_topics
    from tests.test_topics import context

    ctx = context()
    output = routed("s1", focus="a", action="uncertain")
    normalized = normalize_topic_routing(output, ctx)
    assert normalized.topic.source_ids == []
    validate_topics(normalized, ctx)
    assert not question_ready(normalized, ctx)

    output.topic.action = "continue"
    ctx["topics"]["details"].append({"id": "b", "questions_complete": True})
    output.topic.updates.append(
        TopicUpdate(topic_id="b", title="Hiring", summary="A separate topic.", source_ids=["s2"])
    )
    ctx["segments"].append({**ctx["segments"][0], "segment_id": "s2"})
    normalized = normalize_topic_routing(output, ctx)
    validate_topics(normalized, ctx)
    assert normalized.topic.source_ids == ["s1"]  # Never union unrelated topic evidence.


def test_provider_contract_requires_routing_separately_from_question_evidence():
    from app.analysis import SYSTEM, TOPIC_SYSTEM, gemini_output_schema
    from tests.test_topics import context

    ctx = {**context(), "strategy": "topics-v1"}
    schema = gemini_output_schema(ctx)
    topic = schema["properties"]["topic"]
    assert {"action", "focus_id", "source_ids", "readiness"} <= set(topic["required"])
    assert topic["properties"]["source_ids"]["items"]["enum"] == ["s1"]
    assert topic["anyOf"][0]["properties"]["action"]["enum"] == ["uncertain"]
    routed_schema = topic["anyOf"][1]["properties"]
    assert "uncertain" not in routed_schema["action"]["enum"]
    assert routed_schema["source_ids"]["minItems"] == 1
    assert "minItems" not in schema["properties"]["source_ids"]
    assert (
        "top-level source_ids" in SYSTEM
        and "no question still needs routing evidence" in TOPIC_SYSTEM
    )
