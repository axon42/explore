"""Allowlisted validation diagnostics: no model content or exception values leave here."""

REASONS = {
    "Invalid evidence references": "evidence_missing",
    "Opportunities must be hypotheses": "hypothesis_required",
    "Unknown question": "question_unknown",
    "Unknown workflow relationship": "workflow_reference_unknown",
    "Duplicate workflow keys": "workflow_duplicate_key",
    "Workflow transition count mismatch": "workflow_transition_count",
    "Duplicate topic update": "topic_duplicate_update",
    "Topic already exists; use its ID": "topic_duplicate_title",
    "Unknown topic": "topic_unknown",
    "Invalid topic evidence": "topic_evidence_invalid",
    "Topic detail must be loaded before updating it": "topic_context_missing",
    "Unknown focus": "topic_focus_unknown",
    "Invalid routing evidence": "topic_routing_evidence",
    "Routing needs evidence": "topic_routing_incomplete",
    "Continue cannot change focus": "topic_focus_changed",
    "Resume requires an existing paused topic": "topic_resume_invalid",
    "Provisional topic cannot become focus": "topic_focus_provisional",
    "Unknown artifact topic": "artifact_topic_unknown",
    "Provisional topic cannot own accepted artifacts": "artifact_topic_provisional",
    "Artifact topic needs context": "artifact_context_missing",
    "Question needs an intent": "question_intent_missing",
}


def validation_failure(error):
    code = REASONS.get(str(error), "proposal_invalid")
    if code.startswith("topic_") or code.startswith("artifact_"):
        message = "Analysis returned inconsistent discussion-thread references."
    elif code == "hypothesis_required":
        message = "Analysis labeled an opportunity as a fact instead of a hypothesis."
    elif code == "workflow_transition_count":
        message = "Analysis returned workflow steps with mismatched connections."
    elif code == "question_intent_missing":
        message = "Analysis returned a question without its follow-up intent."
    else:
        message = "Analysis returned unsupported evidence or question references."
    return code, f"{message} Transcript is saved. Retry analysis. [{code}]"


def contract_errors(exc, contract):
    """Report schema-owned paths/counts only; never input values or arbitrary object keys."""
    schema = contract.model_json_schema()
    definitions = schema.get("$defs", {})
    details = []
    for error in exc.errors(include_input=False, include_url=False)[:12]:
        node, path = schema, []
        for part in error["loc"]:
            if "$ref" in node:
                node = definitions.get(node["$ref"].split("/")[-1], {})
            if isinstance(part, int) and "items" in node:
                path.append("[]")
                node = node["items"]
            elif isinstance(part, str) and part in node.get("properties", {}):
                path.append(part)
                node = node["properties"][part]
            else:
                path.append("<field>")
                break
        detail = {"type": error["type"], "path": ".".join(path).replace(".[]", "[]")}
        for name in ("actual_length", "max_length", "min_length"):
            value = error.get("ctx", {}).get(name)
            if type(value) is int:
                detail[name] = value
        details.append(detail)
    return details
