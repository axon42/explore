"""Provider-independent batching, context selection and validated state reduction."""

import copy
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(Contract):
    key: str = Field(min_length=1, max_length=100)
    topic_id: str = Field(default="", max_length=100)
    section: Literal["workflows", "pain_impact", "alternatives", "opportunities", "next_steps"]
    text: str = Field(min_length=1, max_length=1000)
    basis: Literal["observed", "inferred"]
    source_ids: list[str] = Field(min_length=1, max_length=10)


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
    def build(self, snapshot, meeting, memory, objective):
        memory = reconcile(memory, snapshot)
        finals = [s for s in snapshot["segments"] if s["is_final"]]
        pending = [s for s in finals if memory["coverage"].get(s["segment_id"]) != s["revision"]]
        if not pending and memory["context_version"] == meeting["version"]:
            return None
        # Never truncate an unprocessed segment. The event contract bounds one at 20K chars.
        selected, size = [], 0
        for s in pending:
            if selected and (size + len(s["text"]) > 24000 or len(selected) >= 60):
                break
            selected.append(s)
            size += len(s["text"])
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
            "objective": meeting["brief"].get("objective") or objective,
            "meeting": meeting,
            "segments": segments,
            "new_source_ids": sorted(new_ids),
            "memory": {k: memory[k][-40:] for k in ("claims", "matches", "workflows")},
            "base_state_version": memory["version"],
            "input_version": snapshot["version"],
        }


class AnalysisStrategy:
    """Replaceable reasoning boundary; the provider only supplies a proposal."""

    async def analyze(self, provider, context):
        return await provider.analyze(context)


def validate_proposal(result, context):
    refs = {s["segment_id"] for s in context["segments"]}

    def check(ids):
        if not ids or not set(ids) <= refs:
            raise ValueError("Invalid evidence references")

    if result.question:
        check(result.source_ids)
    for finding in result.findings:
        check(finding.source_ids)
    for claim in result.claims:
        check(claim.source_ids)
        if claim.section == "opportunities" and claim.basis != "inferred":
            raise ValueError("Opportunities must be hypotheses")
    questions = {q["id"] for q in context["meeting"]["previous_questions"]}
    for match in result.matches:
        check(match.source_ids)
        if match.question_id not in questions:
            raise ValueError("Unknown question")
    for workflow in result.workflows:
        if len(workflow.transitions) != len(workflow.steps) - 1:
            raise ValueError("Workflow transition count mismatch")
        for step in workflow.steps:
            check(step.source_ids)
        for ids in workflow.transitions:
            if ids:
                check(ids)


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
