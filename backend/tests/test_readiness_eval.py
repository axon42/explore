import json
from pathlib import Path

import pytest

from app.analysis import TopicSuggestion
from app.topics import question_ready

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures/evaluation/readiness-v1.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_readiness_contract_on_held_out_scenarios(case):
    context = {
        "new_source_ids": ["passage"],
        "topics": {
            "questions": [],
            "details": [
                {
                    "id": "stock",
                    "questions_complete": case["history_complete"],
                    "summary_sources": {},
                    "question_intents": [],
                }
            ],
        },
    }
    result = TopicSuggestion(
        question="What happened to the order while it was waiting?",
        rationale="Clarify consequence",
        source_ids=["passage"],
        topic={
            "action": case["action"],
            "readiness": case["readiness"],
            "focus_id": "stock",
            "source_ids": ["passage"],
            "reason": case["text"],
            "question_intent": "consequence of waiting",
            "updates": [],
        },
    )
    assert question_ready(result, context) == case["expected_question"]
