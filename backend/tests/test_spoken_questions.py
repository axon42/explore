"""Exact observations, not suggested questions or guessed participant identities."""

import asyncio
import json

from app.analysis import Suggestion
from app.discovery import Discovery
from app.models import AttributedTranscriptEvent, TranscriptEvent
from app.reports import Reports, report_markdown
from app.spoken_questions import SpokenQuestion, accepted, anchors, view
from app.storage import Storage
from tests.prepared import automatic_session
from tests.test_api import payload
from tests.test_pipeline import pipeline, wait_until  # noqa: F401
from tests.test_speakers import confirm, model  # noqa: F401


def event(text="What happened?", segment="q", start=0):
    return TranscriptEvent(
        **payload(
            event_id=segment,
            segment_id=segment,
            speaker_id="microphone",
            text=text,
            start_ms=start,
            end_ms=start + 1000,
            is_final=True,
        )
    )


def record(store, sid, questions, job="job", error="", stale=False):
    snapshot = store.snapshot(sid)
    repo = Discovery(store)
    context = {"segments": snapshot["segments"], "meeting": repo.context(sid), "job_id": job}
    result = Suggestion(question="", rationale="", source_ids=[], spoken_questions=questions)
    cleaned, rejected = accepted(result, context)
    run = {
        "input_version": snapshot["session"]["version"],
        "model": "synthetic",
        "prompt_version": "test",
        "suggestion": cleaned.model_dump(),
        "source_revisions": {s["segment_id"]: s["revision"] for s in snapshot["segments"]},
        "stale": stale,
        "error": error,
    }
    repo.record_run(sid, context, "mock", run)
    return rejected


def test_quotes_fragments_unicode_and_invalid_evidence():
    first = event("🗣 Walk me through", "a").model_dump()
    second = event("the last approval?", "b", 1200).model_dump()
    q = SpokenQuestion(text="Walk me through the last approval?", source_ids=["b", "a"])
    refs = anchors(q, [second, first])
    assert refs == [
        {"segment_id": "a", "revision": first["revision"], "start": 2, "end": len(first["text"])},
        {"segment_id": "b", "revision": second["revision"], "start": 0, "end": len(second["text"])},
    ]
    assert (
        anchors(
            q.model_copy(update={"text": "Walk me through  the last approval?"}), [first, second]
        )
        == refs
    )
    for changed in (
        q.model_copy(update={"text": "How was your approval?"}),
        q.model_copy(update={"source_ids": ["foreign"]}),
    ):
        assert anchors(changed, [first, second]) is None
    assert anchors(q, [first, {**second, "is_final": False}]) is None
    assert anchors(q, [first, event("Interruption", "between", 1100).model_dump(), second]) is None
    assert anchors(q, [first, {**second, "start_ms": 30000}]) is None
    repeated = event("Why? Why?").model_dump()
    assert anchors(SpokenQuestion(text="Why?", source_ids=["q"]), [repeated]) is None


def test_retries_repeated_questions_corrections_and_export(tmp_path):
    store = Storage(tmp_path / "spoken.sqlite3")
    store.initialize()
    s = store.create("Question history")
    sid, mid = s["id"], s["meeting_id"]
    first = event()
    store.ingest(sid, first)
    q = SpokenQuestion(text=first.text, source_ids=[first.segment_id])
    record(store, sid, [q])
    record(store, sid, [q])  # replay accepted job
    record(store, sid, [q], "overlap")  # same occurrence in another batch
    assert len(Discovery(store).detail(mid)["spoken_questions"]) == 1
    second = event(segment="later", start=60000)
    store.ingest(sid, second)
    record(store, sid, [q.model_copy(update={"source_ids": ["later"]})], "later")
    assert len(Discovery(store).detail(mid)["spoken_questions"]) == 2
    store.ingest(
        sid,
        first.model_copy(
            update={"event_id": "corrected", "revision": first.revision + 1, "text": "What failed?"}
        ),
    )
    record(store, sid, [SpokenQuestion(text="What failed?", source_ids=["q"])], "correction")
    rows = Discovery(store).detail(mid)["spoken_questions"]
    assert len(rows) == 3 and sum(q["superseded"] for q in rows) == 1
    earlier = next(q for q in rows if q["superseded"])
    assert earlier["evidence"][0]["text"] == "What happened?"
    assert all(q["interview_role"] == "unknown" for q in rows)
    source = Reports(store).export(mid)
    assert len(source["spoken_questions"]) == 3
    report = Reports(store).strategy.build(source, "mock")
    markdown = report_markdown({**report, "revision": 1})
    assert "Questions asked in conversation" in markdown
    assert "Earlier transcript revision" in markdown
    assert "What failed?" in markdown
    assert Discovery(store).detail(mid)["questions"] == []
    other = store.create("Different meeting")
    assert Discovery(store).detail(other["meeting_id"])["spoken_questions"] == []
    store.stop(sid)
    Discovery(store).reset(mid)
    with store.connection() as db:
        assert not db.execute("SELECT * FROM spoken_questions").fetchall()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert (
            db.execute(
                "SELECT count(*) FROM evidence.archive_events WHERE session_id=?", (sid,)
            ).fetchone()[0]
            == 3
        )


def test_bad_optional_observation_failed_and_stale_jobs_never_commit(tmp_path):
    store = Storage(tmp_path / "spoken.sqlite3")
    store.initialize()
    sid = store.create("Invalid")["id"]
    store.ingest(sid, event())
    bad = SpokenQuestion(text="Invented question?", source_ids=["q"])
    good = SpokenQuestion(text="What happened?", source_ids=["q"])
    assert record(store, sid, [bad], "bad") == 1
    record(store, sid, [good], "failed", error="Provider timeout")
    record(store, sid, [good], "stale", stale=True)
    with store.connection() as db:
        assert view(db, sid) == []
    record(store, sid, [good, bad], "success")
    with store.connection() as db:
        assert len(view(db, sid)) == 1


def test_confirmed_person_role_resolved_from_exact_spans(model):  # noqa: F811
    store, speakers, mid, sid, _ = model
    base = event("What failed? Nothing.").model_dump()
    captured = AttributedTranscriptEvent(
        **base,
        speaker_metadata={
            "capture_id": "sample",
            "channel": "microphone",
            "method": "diarized",
            "spans": [
                {"start": 0, "end": 12, "label": 0},
                {"start": 12, "end": len(base["text"]), "label": 1},
            ],
        },
    )
    store.ingest(sid, captured)
    q = SpokenQuestion(text="What failed?", source_ids=["q"])
    record(store, sid, [q])
    assert Discovery(store).detail(mid)["spoken_questions"][0]["participant_id"] is None
    # Resolve the track for the question's exact span, never the other voice in the segment.
    track = store.snapshot(sid)["segments"][0]["attributions"][0]["track_id"]
    confirm(model, track=track, person=0)
    row = Discovery(store).detail(mid)["spoken_questions"][0]
    assert row["interview_role"] == "interviewer"
    assert row["participant_id"] == speakers.view(mid, sid)["participants"][0]["participant_id"]
    confirm(model, track=track, person=None)
    assert Discovery(store).detail(mid)["spoken_questions"][0]["participant_id"] is None


async def test_pipeline_detects_when_suggestions_disabled_and_rejects_stale(pipeline):  # noqa: F811
    store = pipeline.service.storage
    s = automatic_session(store, "Disabled suggestions")
    Discovery(store).preferences(s["meeting_id"], 0, interval=0)
    arrived, release = asyncio.Event(), asyncio.Event()

    async def analyze(context):
        assert not context["question_allowed"]
        arrived.set()
        await release.wait()
        segment = context["segments"][0]
        return Suggestion(
            question="",
            rationale="",
            source_ids=[],
            spoken_questions=[
                SpokenQuestion(text=segment["text"], source_ids=[segment["segment_id"]])
            ],
        ), {}

    pipeline.provider.analyze = analyze
    first = event()
    await pipeline.service.ingest(s["id"], first)
    await asyncio.wait_for(arrived.wait(), 5)
    await pipeline.service.ingest(
        s["id"],
        first.model_copy(update={"revision": 2, "event_id": "correction", "text": "What failed?"}),
    )
    release.set()
    await wait_until(lambda: bool(pipeline.states[s["id"]]["runs"]))
    assert pipeline.states[s["id"]]["runs"][0]["stale"]
    assert Discovery(store).detail(s["meeting_id"])["spoken_questions"] == []
    await pipeline.process_batch(s["id"])
    rows = Discovery(store).detail(s["meeting_id"])
    assert [q["text"] for q in rows["spoken_questions"]] == ["What failed?"]
    assert rows["questions"] == []
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert json.loads(
            db.execute(
                "SELECT output_json FROM analysis_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()[0]
        )["suggestion"]["spoken_questions"]


def test_persistence_cannot_stitch_across_turn_omitted_from_model_context(tmp_path):
    from app.spoken_questions import persist

    store = Storage(tmp_path / "omitted.sqlite3")
    store.initialize()
    sid = store.create("Omitted turn")["id"]
    a, b = event("What", "a"), event("happened?", "b", 2000)
    for e in (a, event("Interruption", "middle", 1000), b):
        store.ingest(sid, e)
    record(store, sid, [], "base")
    context = {"segments": [a.model_dump(), b.model_dump()]}
    q = SpokenQuestion(text="What happened?", source_ids=["a", "b"])
    assert anchors(q, context["segments"])
    with store.connection() as db:
        persist(db, sid, "base", {"spoken_questions": [q.model_dump()]}, context, "test")
        assert view(db, sid) == []
