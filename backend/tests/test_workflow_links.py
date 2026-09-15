import pytest

from app.analysis import Finding, Suggestion
from app.analysis_state import Workflow, validate_proposal
from tests.test_pipeline import pipeline  # noqa: F401


def test_workflow_links_require_matching_topic_and_known_workflow():
    workflow = Workflow(
        key="approval",
        topic_id="billing",
        title="Invoice approval",
        steps=[
            {"label": "Prepare", "source_ids": ["s"]},
            {"label": "Approve", "source_ids": ["s"]},
        ],
        transitions=[["s"]],
    )
    finding = Finding(
        kind="gap",
        title="Waiting",
        body="Approval waits.",
        basis="observed",
        source_ids=["s"],
        topic_id="billing",
        workflow_key="approval",
    )
    context = {
        "segments": [{"segment_id": "s"}],
        "meeting": {"previous_questions": []},
        "memory": {"workflows": []},
    }
    result = Suggestion(
        question="", rationale="", source_ids=[], findings=[finding], workflows=[workflow]
    )
    validate_proposal(result, context)
    # A similarly named workflow in a different topic is not a valid relationship.
    result.findings[0].topic_id = "recruiting"
    with pytest.raises(ValueError, match="Unknown workflow"):
        validate_proposal(result, context)
    result.findings[0].workflow_key = ""
    validate_proposal(result, context)  # Unassigned is truthful and supported.
    result.findings[0].source_ids = ["another-meeting"]
    with pytest.raises(ValueError, match="Invalid evidence"):
        validate_proposal(result, context)


def test_existing_workflow_reference_and_ambiguous_proposal():
    context = {
        "segments": [{"segment_id": "s"}],
        "meeting": {"previous_questions": []},
        "memory": {"workflows": [{"key": "approval", "topic_id": "billing"}]},
    }
    result = Suggestion(
        question="",
        rationale="",
        source_ids=[],
        findings=[
            Finding(
                kind="opportunity",
                title="Explore reminders",
                body="May reduce waiting; validate.",
                basis="inferred",
                source_ids=["s"],
                topic_id="billing",
                workflow_key="approval",
            )
        ],
    )
    validate_proposal(result, context)
    context["memory"]["workflows"] = []
    with pytest.raises(ValueError, match="Unknown workflow"):
        validate_proposal(result, context)


async def test_linked_findings_persist_with_workflow_memory(pipeline):  # noqa: F811
    from app.models import TranscriptEvent
    from tests.test_api import payload

    pipeline.service.on_final = lambda sid: None
    session = pipeline.service.storage.create("Synthetic relationship")
    sid = session["id"]
    await pipeline.service.ingest(sid, TranscriptEvent(**payload(is_final=True)))

    async def analyze(context):
        return Suggestion(
            question="",
            rationale="",
            source_ids=[],
            workflows=[
                Workflow(
                    key="approval",
                    title="Invoice approval",
                    steps=[
                        {"label": "Prepare", "source_ids": ["seg-1"]},
                        {"label": "Approve", "source_ids": ["seg-1"]},
                    ],
                    transitions=[["seg-1"]],
                )
            ],
            findings=[
                Finding(
                    kind="gap",
                    title="Waiting",
                    body="Approval waits.",
                    basis="observed",
                    source_ids=["seg-1"],
                    workflow_key="approval",
                )
            ],
        ), {}

    pipeline.provider.analyze = analyze
    await pipeline.process_batch(sid)
    detail = pipeline.discovery.detail(session["meeting_id"])
    assert detail["findings"][0]["workflow_key"] == detail["workflows"][0]["key"] == "approval"
    assert detail["findings"][0]["evidence"][0]["segment_id"] == "seg-1"
