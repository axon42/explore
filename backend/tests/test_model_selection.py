import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.analysis import FullSuggestion
from app.config import Settings
from app.main import create_app
from app.model_selection import ModelSelection
from app.models import DomainError
from app.storage import Storage
from tests.test_manual_analysis import ingest
from tests.test_pipeline import pipeline  # noqa: F401


def test_selection_persists_migrates_without_changing_sources(tmp_path):
    store = Storage(tmp_path / "test.sqlite3")
    store.initialize()
    settings = Settings(data_dir=tmp_path, analysis_provider="mock", openai_api_key="fake-key")
    selection = ModelSelection(store, settings)
    assert selection.get() == {"provider": "mock", "model": "simulated", "revision": 0}
    selection.update("openai", "gpt-5.6-terra", 0)
    with pytest.raises(DomainError, match="another tab"):
        selection.update("mock", "simulated", 0)
    store.initialize()
    assert ModelSelection(store, settings).get()["model"] == "gpt-5.6-terra"
    assert "fake-key" not in json.dumps(selection.view())
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        db.execute("DROP TABLE model_selection")
        db.execute("DELETE FROM schema_migrations WHERE version=12")
    store.initialize()
    assert selection.get()["provider"] == "mock"


def test_model_api_rejects_missing_credentials_and_unknown_models(tmp_path):
    settings = Settings(
        data_dir=tmp_path, analysis_provider="mock", openai_api_key="", gemini_api_key=""
    )
    with TestClient(create_app(settings)) as client:
        before = client.get("/settings/model").json()
        assert before["provider"] == "mock"
        for provider, model in [
            ("openai", "gpt-5.6-terra"),
            ("gemini", "other"),
            ("mock", "../bad"),
        ]:
            response = client.patch(
                "/settings/model", json={"provider": provider, "model": model, "revision": 0}
            )
            assert response.status_code == 422
        assert client.get("/settings/model").json() == before


async def test_model_switch_does_not_relabel_inflight_result_or_dispatch(pipeline):  # noqa: F811
    p = pipeline
    p.models.settings = Settings(data_dir=p.settings.data_dir, gemini_api_key="fake")
    sid = p.service.storage.create("Synthetic selection race")["id"]
    await ingest(p, sid)
    entered, release = asyncio.Event(), asyncio.Event()

    async def model(context):
        entered.set()
        await release.wait()
        assert context["model_selection"]["provider"] == "mock"
        return FullSuggestion(complete=True, question="", rationale="", source_ids=[]), {}

    p.provider.analyze = model
    await p.submit_manual(sid, str(uuid4()))
    await entered.wait()
    p.models.update("gemini", "gemini-3.1-flash-lite", 0)
    release.set()
    await p.manual_workers[sid]
    state = await p.view(sid)
    assert state["calls"] == 1
    assert state["provider"] == "gemini"
    assert state["runs"][-1]["model"] == "simulated"
    assert state["runs"][-1]["provider"] == "mock"
    assert state["scheduling"]["changed"]
    assert state["result"]["review"]["empty"]


@pytest.mark.parametrize("valid_evidence", [True, False])
async def test_selected_openai_uses_shared_validation_and_preserves_transcript(
    pipeline,  # noqa: F811
    monkeypatch,
    valid_evidence,
):
    import httpx

    p = pipeline
    p.models.settings = Settings(data_dir=p.settings.data_dir, openai_api_key="synthetic-key")
    p.models.update("openai", "gpt-5.6-terra", 0)
    sid = p.service.storage.create("Synthetic OpenAI integration")["id"]
    await ingest(p, sid)
    before = p.service.storage.snapshot(sid)["segments"]
    original = httpx.AsyncClient
    calls = []

    def response(request):
        calls.append(request)
        proposal = FullSuggestion(
            complete=True,
            question="Can you describe the last example?",
            rationale="Clarify the synthetic statement.",
            source_ids=["source-0" if valid_evidence else "missing-evidence"],
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": proposal.model_dump_json()}],
                    }
                ],
                "usage": {"input_tokens": 42, "output_tokens": 12, "total_tokens": 54},
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw)
    )
    await p.submit_manual(sid, str(uuid4()))
    await p.manual_workers[sid]
    state = await p.view(sid)
    assert len(calls) == 1 and state["calls"] == 1
    assert state["runs"][-1]["provider"] == "openai"
    assert state["runs"][-1]["model"] == "gpt-5.6-terra"
    assert p.service.storage.snapshot(sid)["segments"] == before
    assert state["scheduling"]["pending_segments"] == (0 if valid_evidence else 1)
    assert bool(state["runs"][-1]["error"]) is not valid_evidence
    with p.service.storage.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM questions WHERE session_id=?", (sid,)).fetchone()[
            0
        ] == int(valid_evidence)


@pytest.mark.parametrize("provider", ["gemini", "openai"])
@pytest.mark.parametrize("valid_evidence", [True, False])
async def test_manual_opportunity_does_not_block_threads_or_question(
    pipeline,  # noqa: F811
    monkeypatch,
    provider,
    valid_evidence,
):
    import httpx

    from app.reports import Reports

    p = pipeline
    p.models.settings = Settings(
        data_dir=p.settings.data_dir, gemini_api_key="synthetic", openai_api_key="synthetic"
    )
    model = "gemini-3.1-flash-lite" if provider == "gemini" else "gpt-5.6-terra"
    p.models.update(provider, model, 0)
    p.preferences.update("topics", 0)
    session = p.service.storage.create("Synthetic full review")
    sid = session["id"]
    await ingest(p, sid, text="We manually compile reports.")
    await ingest(p, sid, 1, text="Separately we reconcile transfers every day.")
    raw = dict(
        complete=True,
        question="What happened during the last transfer reconciliation?",
        rationale="Explore the concrete workflow.",
        source_ids=["source-1"],
        findings=[
            dict(
                kind="opportunity",
                title="Reporting assistance",
                body="Possible automation.",
                basis="observed",
                topic_id="new:reporting",
                source_ids=["source-0" if valid_evidence else "foreign-source"],
            )
        ],
        topic=dict(
            action="switch",
            focus_id="new:transfers",
            source_ids=["source-1"],
            readiness="ready",
            question_intent="last reconciliation",
            reason="The reconciliation workflow is established; a concrete example is missing.",
            updates=[
                dict(
                    topic_id="new:reporting",
                    title="Reporting",
                    summary="Manual reports.",
                    source_ids=["source-0"],
                ),
                dict(
                    topic_id="new:transfers",
                    title="Transfers",
                    summary="Daily reconciliation.",
                    source_ids=["source-1"],
                ),
            ],
        ),
    )
    calls = []
    original = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        text = json.dumps(raw)
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
            if provider == "gemini"
            else {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    await p.submit_manual(sid, str(uuid4()))
    await p.manual_workers[sid]
    state = await p.view(sid)
    assert len(calls) == 1
    assert raw["findings"][0]["basis"] == "observed"
    assert len(Reports(p.service.storage).live(session["meeting_id"])["topics"]) == (
        2 if valid_evidence else 0
    )
    assert state["scheduling"]["pending_segments"] == (0 if valid_evidence else 2)
    if valid_evidence:
        assert not state["error"]
        assert state["result"]["suggestion"]["findings"][0]["basis"] == "inferred"
    else:
        assert state["error"]
    with p.service.storage.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM questions WHERE session_id=?", (sid,)).fetchone()[
            0
        ] == int(valid_evidence)
