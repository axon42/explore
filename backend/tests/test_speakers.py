"""Synthetic end-to-end attribution checks; no microphone, network or user storage."""

import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.analysis import Suggestion
from app.analysis_state import Claim, ContextBuilder, empty_memory, reduce_memory, validate_proposal
from app.audio.deepgram import DeepgramNormalizer
from app.config import Settings
from app.discovery import Discovery
from app.main import create_app
from app.models import DomainError, TranscriptEvent
from app.reports import Reports
from app.speakers import Speakers
from app.storage import Storage
from tests.prepared import session
from tests.test_audio_capture import result
from tests.test_pipeline import pipeline as analysis_pipeline  # noqa: F401


def dialogue(labels=(0, 1), text="Slow approval. No, it works.", final=True):
    words = ["Slow", "approval.", "No,", "it", "works."]
    message = result(text, final)
    message["duration"] = 5
    message["channel"]["alternatives"][0]["words"] = [
        {
            "punctuated_word": w,
            "start": i,
            "end": i + 0.8,
            "speaker": labels[0] if i < 2 else labels[1],
        }
        for i, w in enumerate(words)
    ]
    return message


@pytest.fixture
def model(tmp_path):
    store = Storage(tmp_path / "working.sqlite3")
    store.initialize()
    s = session(store, "Synthetic attribution")
    speaker = Speakers(store)
    people = Reports(store).participants(s["meeting_id"])
    return store, speaker, s["meeting_id"], s["id"], people


def confirm(model, track=None, person=0, **target):
    _, speakers, mid, sid, _ = model
    view = speakers.view(mid, sid)
    return speakers.assign(
        mid,
        sid,
        view["version"],
        view["roster_revision"],
        view["participants"][person]["participant_id"] if person is not None else None,
        track_id=track,
        **target,
    )


def add(model, capture="one", channel="system", labels=(0, 1)):
    event = DeepgramNormalizer(capture, channel, 0).event(dialogue(labels))
    model[0].ingest(model[3], event)
    return event


def test_exact_spans_duplicate_and_speaker_only_correction():
    normalizer = DeepgramNormalizer("run", "system", 1000)
    first = normalizer.event(dialogue())
    spans = first.speaker_metadata.spans
    assert [first.text[s.start : s.end] for s in spans] == ["Slow approval.", " No, it works."]
    assert normalizer.event(dialogue()) is None
    corrected = normalizer.event(dialogue((1, 0)))
    assert corrected.segment_id == first.segment_id and corrected.revision == 1
    assert corrected.text == first.text
    assert [s.label for s in corrected.speaker_metadata.spans] == [1, 0]
    assert normalizer.event(dialogue(final=False)) is None


@pytest.mark.parametrize("bad", [None, [], "bad", [{"word": "mismatch", "speaker": 0}]])
def test_unaligned_metadata_never_discards_or_attributes_text(bad):
    message = dialogue()
    message["channel"]["alternatives"][0]["words"] = bad
    event = DeepgramNormalizer("r", "system", 0).event(message)
    assert event.text == "Slow approval. No, it works."
    assert [(s.start, s.end, s.label) for s in event.speaker_metadata.spans] == [
        (0, len(event.text), None)
    ]


def test_invalid_label_and_overlap_remain_unknown():
    message = dialogue()
    words = message["channel"]["alternatives"][0]["words"]
    words[0]["speaker"] = True
    words[1]["start"] = 0.2  # overlapped word is not trustworthy attribution
    event = DeepgramNormalizer("r", "system", 0).event(message)
    assert event.speaker_metadata.spans[0].label is None
    assert event.speaker_metadata.spans[-1].label == 1


def test_namespace_explicit_confirmation_and_passage_override(model):
    store, speakers, mid, sid, _ = model
    first = add(model)
    add(model, channel="microphone")
    add(model, capture="resumed")
    view = speakers.view(mid, sid)
    assert len(view["tracks"]) == 6
    assert all(t["participant_id"] is None for t in view["tracks"])
    track = view["tracks"][0]["id"]
    confirm(model, track, 0)
    snapshot = store.snapshot(sid)
    originals = [s for s in snapshot["segments"] if s["segment_id"] == first.segment_id][0]
    assert originals["attributions"][0]["interview_role"] == "interviewer"
    assert originals["attributions"][1]["interview_role"] == "unknown"
    assert (
        sum(a["status"] == "confirmed" for s in snapshot["segments"] for a in s["attributions"])
        == 1
    )
    confirm(model, person=1, segment_id=first.segment_id, segment_revision=0, span_index=0)
    projected = next(
        s for s in store.snapshot(sid)["segments"] if s["segment_id"] == first.segment_id
    )
    assert projected["attributions"][0]["interview_role"] == "customer"
    assert projected["text"] == first.text and projected["revision"] == first.revision
    # An explicit clear overrides the track, rather than falling back to its person.
    confirm(model, person=None, segment_id=first.segment_id, segment_revision=0, span_index=0)
    projected = next(
        s for s in store.snapshot(sid)["segments"] if s["segment_id"] == first.segment_id
    )
    assert projected["attributions"][0]["status"] == "unassigned"


def test_correction_never_moves_a_passage_override(model):
    store, _, _, sid, _ = model
    normalizer = DeepgramNormalizer("one", "system", 0)
    first = normalizer.event(dialogue())
    store.ingest(sid, first)
    confirm(model, "one:system:0")
    confirm(model, person=1, segment_id=first.segment_id, segment_revision=0, span_index=0)
    store.ingest(sid, normalizer.event(dialogue((1, 0))))
    spans = store.snapshot(sid)["segments"][0]["attributions"]
    assert all(s["status"] == "unassigned" and s["needs_review"] for s in spans)
    with pytest.raises(DomainError, match="no longer current"):
        confirm(model, person=1, segment_id=first.segment_id, segment_revision=0, span_index=0)


def test_roster_history_and_stale_choices(model):
    store, speakers, mid, sid, people = model
    add(model)
    view = confirm(model, "one:system:0")
    person_id = view["participants"][0]["participant_id"]
    edited = copy.deepcopy(people["participants"])
    edited[0]["interview_role"] = "observer"
    saved = Reports(store).participants(mid, people["revision"], edited)
    assert saved["participants"][0]["participant_id"] == person_id
    assert store.snapshot(sid)["segments"][0]["attributions"][0]["status"] == "unassigned"
    assert speakers.view(mid, sid)["tracks"][0]["needs_review"]
    with pytest.raises(DomainError, match="changed"):
        speakers.assign(
            mid, sid, view["version"], view["roster_revision"], person_id, "one:system:0"
        )
    confirm(model, "one:system:0")
    assert store.snapshot(sid)["segments"][0]["attributions"][0]["interview_role"] == "observer"
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM participant_rosters WHERE meeting_id=?", (mid,)
            ).fetchone()[0]
            == 2
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_cross_meeting_and_concurrent_assignment_rejected(model):
    store, speakers, mid, sid, _ = model
    add(model)
    other = session(store, "Other")
    foreign = Reports(store).participants(other["meeting_id"])["participants"][0]["participant_id"]
    view = speakers.view(mid, sid)
    with pytest.raises(DomainError):
        speakers.assign(mid, sid, view["version"], view["roster_revision"], foreign, "one:system:0")
    with pytest.raises(DomainError):
        speakers.view(other["meeting_id"], sid)
    person = view["participants"][0]["participant_id"]

    def save():
        try:
            speakers.assign(
                mid, sid, view["version"], view["roster_revision"], person, "one:system:0"
            )
            return "saved"
        except DomainError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == ["conflict", "saved"]


def test_archive_contains_raw_metadata_and_every_assignment_after_reset(model):
    store, speakers, mid, sid, _ = model
    first = add(model)
    confirm(model, "one:system:0", 0)
    confirm(model, "one:system:0", 1)
    confirm(model, "one:system:0", None)
    exported = Reports(store).export(mid)
    assert len(exported["speaker_assignments"]) == 3 and exported["schema_version"] == 2
    store.stop(sid)
    Discovery(store).reset(mid)
    with pytest.raises(DomainError):
        speakers.view(mid, sid)
    with sqlite3.connect(store.archive.path) as db:
        assert (
            json.loads(db.execute("SELECT payload FROM archive_events").fetchone()[0])
            == first.model_dump()
        )
        states = [
            json.loads(r[0])["speaker_assignments"]
            for r in db.execute("SELECT payload FROM archive_contexts")
        ]
        assert {a["version"] for state in states for a in state} == {1, 2, 3}


def test_archive_failure_rolls_back_confirmation(model):
    store, speakers, mid, sid, _ = model
    add(model)
    before = store.snapshot(sid)
    with sqlite3.connect(store.archive.path) as db:
        db.execute(
            "CREATE TRIGGER synthetic_failure BEFORE INSERT ON archive_contexts "
            "BEGIN SELECT RAISE(ABORT,'full disk'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        confirm(model, "one:system:0")
    assert store.snapshot(sid) == before
    assert not speakers.view(mid, sid)["history"]


def test_analysis_requires_exact_confirmed_person_evidence(model):
    store, speakers, mid, sid, _ = model
    event = add(model)
    view = confirm(model, "one:system:0", 0)
    context = ContextBuilder().build(
        store.snapshot(sid), Discovery(store).context(sid), empty_memory(), "Test"
    )
    claim = Claim(
        key="approval",
        section="pain_impact",
        text="The founder proposed slow approval.",
        basis="observed",
        source_ids=[event.segment_id],
        attributed_to=view["participants"][0]["participant_id"],
        speaker_evidence=[{"source_id": event.segment_id, "span_index": 0}],
    )
    output = Suggestion(question="", rationale="", source_ids=[], claims=[claim])
    validate_proposal(output, context)
    # A founder's hypothesis cannot be attributed to the customer who denied it.
    with pytest.raises(ValueError, match="speaker evidence"):
        validate_proposal(
            output.model_copy(
                update={
                    "claims": [
                        claim.model_copy(
                            update={"attributed_to": view["participants"][1]["participant_id"]}
                        )
                    ]
                }
            ),
            context,
        )
    with pytest.raises(ValueError):
        validate_proposal(
            output.model_copy(
                update={"claims": [claim.model_copy(update={"speaker_evidence": []})]}
            ),
            context,
        )
    neutral = Suggestion(
        question="What happened during that approval?",
        rationale="Neutral",
        source_ids=[event.segment_id],
    )
    validate_proposal(neutral, context)


def test_metadata_change_revisits_old_text_and_invalidates_generated_artifacts(model):
    store, _, mid, sid, _ = model
    event = add(model)
    before = store.snapshot(sid)
    context = ContextBuilder().build(before, Discovery(store).context(sid), empty_memory(), "Test")
    output = Suggestion(
        question="",
        rationale="",
        source_ids=[],
        claims=[
            Claim(
                key="old",
                section="pain_impact",
                text="Unidentified observation",
                basis="observed",
                source_ids=[event.segment_id],
            )
        ],
    )
    memory = reduce_memory(empty_memory(), before, context, output)
    confirm(model, "one:system:0")
    after = store.snapshot(sid)
    next_context = ContextBuilder().build(after, Discovery(store).context(sid), memory, "Test")
    assert next_context["new_source_ids"] == [event.segment_id]
    assert not next_context["memory"]["claims"]
    assert next_context["attribution_version"] > context["attribution_version"]
    assert after["segments"][0]["text"] == before["segments"][0]["text"]


def test_legacy_migration_preserves_source_roster_and_backup(model):
    store, _, mid, sid, people = model
    legacy_event = DeepgramNormalizer("legacy", "microphone", 0).event(dialogue())
    store.ingest(sid, TranscriptEvent(**legacy_event.model_dump(exclude={"speaker_metadata"})))
    store.stop(sid)
    original = store.snapshot(sid)
    with store.connection() as db:
        for table in (
            "speaker_assignments",
            "speaker_spans",
            "speaker_tracks",
            "participant_rosters",
            "participant_identities",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("DROP INDEX sessions_identity_meeting")
        db.execute("ALTER TABLE sessions DROP COLUMN attribution_version")
        legacy = [
            {k: v for k, v in p.items() if k != "participant_id"} for p in people["participants"]
        ]
        db.execute(
            "UPDATE meeting_participants SET payload=? WHERE meeting_id=?",
            (json.dumps(legacy), mid),
        )
        db.execute("DELETE FROM schema_migrations WHERE version=7")
    store.initialize()
    store.initialize()
    assert store.snapshot(sid)["segments"] == original["segments"]
    assert store.snapshot(sid)["session"]["attribution_version"] == 1
    assert store.snapshot(sid)["version"] == original["version"] + 1
    assert Reports(store).participants(mid) == people
    assert store.path.with_suffix(".before-speaker-attribution.sqlite3").exists()
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


async def test_inflight_analysis_rejected_after_attribution_edit(analysis_pipeline):  # noqa: F811
    pipeline = analysis_pipeline
    store = pipeline.service.storage
    s = session(store, "In-flight synthetic")
    sid, mid = s["id"], s["meeting_id"]
    model = (store, Speakers(store), mid, sid, Reports(store).participants(mid))
    add(model)
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(context):
        entered.set()
        await release.wait()
        return Suggestion(
            question="Old question", rationale="old", source_ids=context["new_source_ids"]
        ), {}

    pipeline.provider.analyze = held
    task = asyncio.create_task(pipeline.process_batch(sid, closing=True))
    await asyncio.wait_for(entered.wait(), 3)
    await pipeline.service.read(lambda: confirm(model, "one:system:0"))
    release.set()
    await task
    assert not Discovery(store).detail(mid)["questions"]
    assert not Discovery(store).memory(sid)["coverage"]
    await pipeline.stop(sid)


def test_api_identity_ownership_and_request_contract(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        store = app.state.service.storage
        s = session(store, "API attribution")
        mid, sid = s["meeting_id"], s["id"]
        store.ingest(sid, DeepgramNormalizer("a", "system", 0).event(dialogue()))
        path = f"/meetings/{mid}/sessions/{sid}/speakers"
        view = client.get(path).json()
        body = {
            "version": view["version"],
            "roster_revision": view["roster_revision"],
            "participant_id": view["participants"][1]["participant_id"],
            "track_id": "a:system:1",
        }
        assert client.put(path, json=body).status_code == 200
        assert client.put(path, json=body).status_code == 409
        assert client.put(path, json={**body, "version": -1}).status_code == 422
        assert client.get(f"/meetings/foreign/sessions/{sid}/speakers").status_code == 404


def test_saved_report_keeps_attribution_and_becomes_outdated(model):
    store, _, mid, sid, _ = model
    add(model)
    confirm(model, "one:system:0", 0)
    snapshot = store.snapshot(sid)
    context = ContextBuilder().build(
        snapshot, Discovery(store).context(sid), empty_memory(), "Test"
    )
    memory = reduce_memory(
        empty_memory(), snapshot, context, Suggestion(question="", rationale="", source_ids=[])
    )
    with store.connection() as db:
        db.execute("INSERT INTO analysis_state VALUES (?,?)", (sid, json.dumps(memory)))
    store.stop(sid)
    reports = Reports(store)
    reports.generate(sid, "mock")
    old = reports.list(mid)["reports"][0]
    saved = reports.get(mid, old["id"])
    assert saved["evidence"][0]["attributions"][0]["interview_role"] == "interviewer"
    confirm(model, "one:system:0", 1)
    assert reports.list(mid)["reports"][0]["outdated"]
    assert reports.get(mid, old["id"]) == saved
    assert not reports.live(mid)["state"]["coverage"]
