"""Small synthetic routing simulation. Not a semantic-quality evaluator."""

from .analysis import TopicSuggestion
from .topics import TopicProposal, TopicUpdate


def with_topics(result, context):
    new = [s for s in context["segments"] if s["segment_id"] in context["new_source_ids"]]
    if not new:
        return TopicSuggestion(**result.model_dump(), topic=TopicProposal())
    latest = new[-1]
    text = latest["text"].casefold()
    focus = context["topics"]["focus_id"]
    label = next(
        (
            title
            for word, title in (
                ("recruit", "Recruiting"),
                ("access", "Access approvals"),
                ("report", "Operational reporting"),
                ("spreadsheet", "Operational reporting"),
            )
            if word in text
        ),
        "",
    )
    known = next((t["id"] for t in context["topics"]["index"] if t["title"] == label), "")
    target = known or ("new:" + label.lower().replace(" ", "-") if label else focus)
    if not target:
        return TopicSuggestion(**result.model_dump(), topic=TopicProposal())
    action = "continue" if target == focus else "resume" if known else "switch"
    hydrated = {t["id"] for t in context["topics"]["details"]}
    updates = []
    if label and (not known or known in hydrated):
        updates = [
            TopicUpdate(
                topic_id=target,
                title=label,
                summary=latest["text"][:1200],
                source_ids=[latest["segment_id"]],
            )
        ]
    if target.startswith("new:") or target in hydrated:
        for item in [*result.claims, *result.workflows, *result.findings]:
            # Only attach this passage; unrelated earlier material remains unassigned.
            refs = (
                item.source_ids
                if hasattr(item, "source_ids")
                else [s for step in item.steps for s in step.source_ids]
            )
            if set(refs) == {latest["segment_id"]}:
                item.topic_id = target
    developing = text.endswith(("…", "...")) or "let me explain" in text
    return TopicSuggestion(
        **result.model_dump(),
        topic=TopicProposal(
            action=action,
            focus_id=target,
            source_ids=[latest["segment_id"]],
            readiness="developing" if developing else "ready",
            reason="Synthetic routing fixture",
            question_intent="impact of this process",
            updates=updates,
        ),
    )
