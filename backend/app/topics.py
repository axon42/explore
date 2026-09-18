"""Bounded topic contracts and pure routing/context rules; no provider or storage access."""

import copy
import json
import re
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

MAX_CONTEXT_CHARS = 64000


class TopicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1200)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    assignment: Literal["accepted", "provisional"] = "accepted"


class TopicProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["continue", "switch", "resume", "uncertain"] = "uncertain"
    focus_id: str = Field(default="", max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    readiness: Literal["developing", "ready", "uncertain"] = "uncertain"
    reason: str = Field(default="", max_length=300)
    question_intent: str = Field(default="", max_length=160)
    updates: list[TopicUpdate] = Field(default_factory=list, max_length=4)


def normalize_intent(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def topic_state(memory):
    return memory.get("topic_state", {"schema_version": 1, "focus_id": "", "sources": {}})


def normalize_topic_routing(result, context):
    """Resolve redundant omissions only from explicit routing/update declarations.

    Never choose a topic from a title, question, unrelated update or previous evidence.
    The complete normalized proposal still passes all semantic/ownership validators.
    """
    result = result.model_copy(deep=True)
    topic = result.topic
    catalog = context["topics"]
    known = {t["id"] for t in catalog["index"]}
    if topic.action == "continue" and not topic.focus_id and catalog["focus_id"] in known:
        topic.focus_id = catalog["focus_id"]

    declared = [t for t in topic.updates if t.topic_id == topic.focus_id]
    update = declared[0] if len(declared) == 1 and declared[0].assignment == "accepted" else None
    if topic.action == "continue" and not catalog["focus_id"] and not catalog["index"]:
        if update and update.topic_id.startswith("new:"):
            topic.action = "switch"
    if topic.action != "uncertain" and not topic.source_ids and update:
        topic.source_ids = list(update.source_ids)
    return result


def validate_topics(result, context):
    topic = result.topic
    refs = {s["segment_id"] for s in context["segments"]}
    known = {t["id"] for t in context["topics"]["index"]}
    hydrated = {t["id"] for t in context["topics"]["details"]}
    updates = {t.topic_id: t for t in topic.updates}
    if len(updates) != len(topic.updates):
        raise ValueError("Duplicate topic update")
    titles = {" ".join(t["title"].casefold().split()) for t in context["topics"]["index"]}
    for item in topic.updates:
        if item.topic_id.startswith("new:") and " ".join(item.title.casefold().split()) in titles:
            raise ValueError("Topic already exists; use its ID")
        if item.topic_id.startswith("new:"):
            titles.add(" ".join(item.title.casefold().split()))
        if item.topic_id not in known and not re.fullmatch(r"new:[a-z0-9_-]{1,60}", item.topic_id):
            raise ValueError("Unknown topic")
        if not set(item.source_ids) <= refs:
            raise ValueError("Invalid topic evidence")
        if item.topic_id in known and item.topic_id not in hydrated:
            raise ValueError("Topic detail must be loaded before updating it")
    available = known | set(updates)
    if topic.focus_id and topic.focus_id not in available:
        raise ValueError("Unknown focus")
    if not set(topic.source_ids) <= refs:
        raise ValueError("Invalid routing evidence")
    if topic.action != "uncertain":
        if not topic.focus_id or not topic.source_ids:
            raise ValueError("Routing needs evidence")
        prior = context["topics"]["focus_id"]
        if topic.action == "continue" and topic.focus_id != prior:
            raise ValueError("Continue cannot change focus")
        if topic.action == "resume" and (topic.focus_id not in known or topic.focus_id == prior):
            raise ValueError("Resume requires an existing paused topic")
        if topic.focus_id in updates and updates[topic.focus_id].assignment != "accepted":
            raise ValueError("Provisional topic cannot become focus")
    for item in [*result.claims, *result.workflows, *result.findings]:
        if item.topic_id and item.topic_id not in available:
            raise ValueError("Unknown artifact topic")
        if item.topic_id in updates and updates[item.topic_id].assignment == "provisional":
            raise ValueError("Provisional topic cannot own accepted artifacts")
        if item.topic_id in known and item.topic_id not in hydrated:
            raise ValueError("Artifact topic needs context")
    if result.question and not normalize_intent(topic.question_intent):
        raise ValueError("Question needs an intent")


def resolve_topics(result, context):
    """IDs depend on job identity; a retried accepted proposal cannot create another topic."""
    proposal = result.model_copy(deep=True)
    mapping = {
        item.topic_id: str(uuid5(NAMESPACE_URL, context["job_id"] + ":" + item.topic_id))
        for item in proposal.topic.updates
        if item.topic_id.startswith("new:")
    }
    for item in proposal.topic.updates:
        item.topic_id = mapping.get(item.topic_id, item.topic_id)
    proposal.topic.focus_id = mapping.get(proposal.topic.focus_id, proposal.topic.focus_id)
    for item in [*proposal.claims, *proposal.workflows, *proposal.findings]:
        item.topic_id = mapping.get(item.topic_id, item.topic_id)
    return proposal


def question_block_reason(result, context):
    proposal = result.topic
    focus = proposal.focus_id
    explicit_live_review = (
        context.get("scheduling_mode") == "manual" and context.get("review_kind") == "live"
    )
    ready = proposal.readiness == "ready" or (
        explicit_live_review and proposal.readiness == "developing"
    )
    if proposal.action == "uncertain" or not ready or not focus:
        return "topic_not_ready"
    if not proposal.reason.strip() or not context["new_source_ids"]:
        return "question_context_missing"
    # An index-only topic must be hydrated on a later batch before questions are considered.
    new = {t.topic_id for t in proposal.updates if t.topic_id.startswith("new:")}
    details = {t["id"]: t for t in context["topics"]["details"]}
    if focus not in new and (focus not in details or not details[focus]["questions_complete"]):
        return "question_history_incomplete"
    allowed_sources = set(proposal.source_ids)
    if focus in details:
        allowed_sources.update(details[focus].get("summary_sources", {}))
    for update in proposal.updates:
        if update.topic_id == focus:
            allowed_sources.update(update.source_ids)
    if explicit_live_review and context.get("scope") == "full-transcript":
        # Full review can cite any supplied passage, not only the summary's short citation set.
        # validate_proposal independently rejects missing/foreign/superseded references.
        allowed_sources.update(s["segment_id"] for s in context["segments"])
    if not set(result.source_ids) <= allowed_sources:
        return "question_evidence_outside_topic_context"
    intent = normalize_intent(proposal.question_intent)
    if not intent:
        return "question_intent_missing"
    duplicate = any(
        q["topic_id"] == focus and q["intent"] == intent for q in context["topics"]["questions"]
    )

    return "question_intent_duplicate" if duplicate else ""


def question_ready(result, context):
    return not question_block_reason(result, context)


def add_topic_context(context, memory, catalog):
    """Topic data shares a hard serialized-character ceiling with the existing envelope."""
    context = copy.deepcopy(context)
    catalog = copy.deepcopy(catalog)
    context["strategy"] = "topics-v1"
    context["topics"] = catalog
    # Select memory for hydrated topics before unrelated recent memory, with bounded output.
    ids = {t["id"] for t in catalog["details"]}
    for field in ("claims", "workflows"):
        items = memory[field]
        context["memory"][field] = sorted(items, key=lambda item: item.get("topic_id", "") in ids)[
            -20:
        ]
    present = {s["segment_id"] for s in context["segments"]}
    for source in catalog.pop("evidence", []):
        if source["segment_id"] not in present:
            context["segments"].append(source)
            present.add(source["segment_id"])
    context["segments"].sort(key=lambda s: (s["start_ms"], s["segment_id"]))
    context["omitted"] = {}
    # Never truncate an unprocessed segment. Drop lower-priority derived/context material.
    for label, items in [
        ("claims", context["memory"]["claims"]),
        ("workflows", context["memory"]["workflows"]),
        ("matches", context["memory"]["matches"]),
        ("notes", context["meeting"]["notes"]),
        ("previous_questions", context["meeting"]["previous_questions"]),
    ]:
        while items and len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS - 1024:
            items.pop(0)
            context["omitted"][label] = context["omitted"].get(label, 0) + 1
    if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS - 1024:
        # Refuse a provider call rather than send unbounded context or damaged evidence.
        raise ValueError("Topic context exceeds its budget")
    return context


def advance_topic_state(memory, context, result):
    state = copy.deepcopy(topic_state(memory))
    proposal = result.topic
    if proposal.action != "uncertain":
        state["focus_id"] = proposal.focus_id
        refs = {s["segment_id"]: s["revision"] for s in context["segments"]}
        state["sources"] = {key: refs[key] for key in proposal.source_ids}
    state.update(action=proposal.action, readiness=proposal.readiness, reason=proposal.reason)
    memory["topic_state"] = state
    return memory
