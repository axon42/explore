"""Provider-independent batching, context selection and validated state reduction."""

import copy
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpeakerEvidence(Contract):
    source_id: str = Field(min_length=1, max_length=200)
    span_index: int = Field(ge=0, le=1999)


class AttributedProposal(Contract):
    attributed_to: str = Field(default="", max_length=200)
    speaker_evidence: list[SpeakerEvidence] = Field(default_factory=list, max_length=10)


class Claim(AttributedProposal):
    key: str = Field(min_length=1, max_length=100)
    topic_id: str = Field(default="", max_length=100)
    section: Literal["workflows", "pain_impact", "alternatives", "opportunities", "next_steps"]
    text: str = Field(min_length=1, max_length=1000)
    basis: Literal["observed", "inferred"]
    source_ids: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def inferred_opportunity(self):
        if self.section == "opportunities":
            # Opportunities remain hypotheses even when the provider overstates certainty.
            # Source references and confirmed attribution are still validated separately.
            self.basis = "inferred"
        return self


class QuestionMatch(Contract):
    question_id: str = Field(min_length=1, max_length=200)
    status: Literal["asked", "answered"]
    source_ids: list[str] = Field(min_length=1, max_length=10)


class WorkflowStep(Contract):
    label: str = Field(min_length=1, max_length=180)
    source_ids: list[str] = Field(min_length=1, max_length=10)


class Workflow(Contract):
    key: str = Field(min_length=1, max_length=100)
    topic_id: str = Field(default="", max_length=100)
    title: str = Field(min_length=1, max_length=150)
    steps: list[WorkflowStep] = Field(min_length=2, max_length=12)
    # Every transition has its own supporting passage; an empty list means unknown order.
    transitions: list[list[str]] = Field(
        max_length=11,
        description=(
            "One entry per adjacent step pair, in order. Each entry contains only "
            "supporting transcript segment IDs, never step names or labels. "
            "Use [] when the ordering is not established."
        ),
    )


@dataclass
class TriggerPolicy:
    idle_seconds: float = 1.0
    max_wait_seconds: float = 5.0

    async def collect(self, wake):
        import asyncio

        deadline = time.monotonic() + self.max_wait_seconds
        while True:
            wake.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(wake.wait(), min(self.idle_seconds, remaining))
            except TimeoutError:
                return remaining >= self.idle_seconds


def empty_memory():
    return {
        "version": 0,
        "context_version": -1,
        "cursor": 0,
        "coverage": {},
        "claims": [],
        "matches": [],
        "workflows": [],
    }


def reconcile(memory, snapshot):
    """Remove only derived records dependent on corrected sources; keep run history."""
    memory = copy.deepcopy(memory)
    attribution_version = snapshot.get("session", {}).get("attribution_version", 0)
    if memory.get("attribution_version", 0) != attribution_version:
        memory = {
            **empty_memory(),
            "version": memory["version"],
            "attribution_version": attribution_version,
        }
    current = {s["segment_id"]: s["revision"] for s in snapshot["segments"] if s["is_final"]}
    memory["coverage"] = {k: v for k, v in memory["coverage"].items() if current.get(k) == v}
    for field in ("claims", "matches", "workflows"):
        memory[field] = [
            item
            for item in memory[field]
            if all(current.get(k) == v for k, v in item["sources"].items())
        ]
    state = memory.get("topic_state")
    if state and any(current.get(k) != v for k, v in state.get("sources", {}).items()):
        state.update(focus_id="", action="uncertain", readiness="uncertain", sources={})
    return memory


class ContextBuilder:
    def build(self, snapshot, meeting, memory, objective, batch_reduction=0):
        memory = reconcile(memory, snapshot)
        finals = [s for s in snapshot["segments"] if s["is_final"]]
        pending = [s for s in finals if memory["coverage"].get(s["segment_id"]) != s["revision"]]
        if not pending and memory["context_version"] == meeting["version"]:
            return None
        # Never truncate an unprocessed segment. The event contract bounds one at 20K chars.
        selected, size, words = [], 0, 0
        factor = 2 ** min(3, max(0, batch_reduction))
        char_limit, segment_limit = 24000 // factor, max(1, 60 // factor)
        for s in pending:
            # A reduced fragment cap must still let short STT fragments reach the
            # existing 35-word readiness gate; otherwise a retry can wait forever.
            count_full = len(selected) >= segment_limit and (words >= 35 or factor == 1)
            if selected and (
                size + len(s["text"]) > char_limit or count_full or len(selected) >= 60
            ):
                break
            selected.append(s)
            size += len(s["text"])
            words += len(s["text"].split())
        new_ids = {s["segment_id"] for s in selected}
        recent = []
        budget = 4000
        for s in reversed(finals):
            if s["segment_id"] in new_ids or s in pending:
                continue
            if len(s["text"]) <= budget:
                recent.append(s)
                budget -= len(s["text"])
            if len(recent) == 10:
                break
        if not selected and not recent and finals:
            recent = finals[-1:]
        segments = sorted(selected + recent, key=lambda s: (s["start_ms"], s["segment_id"]))
        return {
            "attribution_version": snapshot.get("session", {}).get("attribution_version", 0),
            "objective": meeting["brief"].get("objective") or objective,
            "meeting": meeting,
            "segments": analysis_segments(segments),
            "new_source_ids": sorted(new_ids),
            "memory": {k: memory[k][-40:] for k in ("claims", "matches", "workflows")},
            "base_state_version": memory["version"],
            "input_version": snapshot["version"],
        }


def analysis_segments(segments):
    """Exclude raw adapter metadata and redundant labels from bounded model context."""
    result = []
    for segment in segments:
        item = {k: v for k, v in segment.items() if k != "speaker_metadata"}
        if "attributions" in item:
            item["attributions"] = [
                {
                    k: a[k]
                    for k in ("index", "start", "end", "participant_id", "interview_role", "status")
                }
                for a in item["attributions"]
            ]
        result.append(item)
    return result


class AnalysisStrategy:
    """Replaceable reasoning boundary; the provider only supplies a proposal."""

    async def analyze(self, provider, context):
        return await provider.analyze(context)


def validate_proposal(result, context):
    refs = {s["segment_id"] for s in context["segments"]}

    def check(ids):
        if not ids or not set(ids) <= refs:
            raise ValueError("Invalid evidence references")

    def check_person(item):
        if not item.attributed_to:
            if item.speaker_evidence:
                raise ValueError("Speaker evidence requires a confirmed person")
            return
        if not item.speaker_evidence:
            raise ValueError("Person attribution requires exact speaker spans")
        available = {
            (s["segment_id"], a["index"]): a
            for s in context["segments"]
            for a in s.get("attributions", [])
            if s["is_final"]
        }
        for ref in item.speaker_evidence:
            span = available.get((ref.source_id, ref.span_index))
            if (
                ref.source_id not in item.source_ids
                or not span
                or span["status"] != "confirmed"
                or span["participant_id"] != item.attributed_to
            ):
                raise ValueError("Unconfirmed or inconsistent speaker evidence")

    if result.question:
        check(result.source_ids)
    workflow_keys = {
        (w.get("topic_id", ""), w["key"]) for w in context.get("memory", {}).get("workflows", [])
    }
    proposed_keys = [(w.topic_id, w.key) for w in result.workflows]
    if len(set(proposed_keys)) != len(proposed_keys):
        raise ValueError("Duplicate workflow keys")
    workflow_keys.update(proposed_keys)
    for finding in result.findings:
        check(finding.source_ids)
        check_person(finding)
        if finding.workflow_key and (finding.topic_id, finding.workflow_key) not in workflow_keys:
            raise ValueError("Unknown workflow relationship")
    for claim in result.claims:
        check(claim.source_ids)
        check_person(claim)
        if claim.section == "opportunities" and claim.basis != "inferred":
            raise ValueError("Opportunities must be hypotheses")
    questions = {q["id"] for q in context["meeting"]["previous_questions"]}
    for match in result.matches:
        check(match.source_ids)
        if match.question_id not in questions:
            raise ValueError("Unknown question")
    for workflow in result.workflows:
        for step in workflow.steps:
            check(step.source_ids)
        for ids in workflow.transitions:
            if ids:
                check(ids)
        if len(workflow.transitions) != len(workflow.steps) - 1:
            # Positional alignment is ambiguous. Validate all supplied references above,
            # then preserve supported steps without claiming any established ordering.
            workflow.transitions = [[] for _ in range(len(workflow.steps) - 1)]


def reduce_memory(memory, snapshot, context, result):
    memory = reconcile(memory, snapshot)
    refs = {s["segment_id"]: s["revision"] for s in context["segments"]}
    for field in ("claims", "matches", "workflows"):
        items = {
            (item.get("topic_id", ""), item.get("key", item.get("question_id"))): item
            for item in memory[field]
        }
        for proposal in getattr(result, field):
            item = proposal.model_dump()
            ids = item.get("source_ids", [])
            if field == "workflows":
                ids = [s for step in item["steps"] for s in step["source_ids"]]
                ids += [s for transition in item["transitions"] for s in transition]
            item["sources"] = {s: refs[s] for s in ids}
            items[(item.get("topic_id", ""), item.get("key", item.get("question_id")))] = item
        memory[field] = list(items.values())
    memory["coverage"].update({k: refs[k] for k in context["new_source_ids"]})
    memory.update(
        version=memory["version"] + 1,
        context_version=context["meeting"]["version"],
        cursor=(
            context["input_version"]
            if all(
                not s["is_final"] or memory["coverage"].get(s["segment_id"]) == s["revision"]
                for s in snapshot["segments"]
            )
            else memory["cursor"]
        ),
    )
    return memory
