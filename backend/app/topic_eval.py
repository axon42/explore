"""Offline synthetic baseline: python -m app.topic_eval. No keys or paid providers."""

import asyncio
import json
import statistics
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from .broadcast import Broadcaster
from .config import Settings
from .models import TranscriptEvent
from .pipeline import Pipeline
from .service import Service
from .storage import Storage

FIXTURE = Path(__file__).parents[1] / "fixtures/topic-switching-v1.json"


async def evaluate(strategy, turns):
    with tempfile.TemporaryDirectory(prefix="explore-topic-eval-") as directory:
        settings = Settings(
            _env_file=None,
            data_dir=Path(directory),
            analysis_provider="mock",
            analysis_strategy=strategy,
            gemini_api_key="",
            deepgram_api_key="",
        )
        storage = Storage(settings.data_dir / "eval.sqlite3")
        storage.initialize()
        pipeline = Pipeline(Service(storage, Broadcaster(128)), settings)
        session = storage.create("Synthetic topic baseline")
        sid, mid = session["id"], session["meeting_id"]
        pipeline.wakes[sid] = asyncio.Event()
        premature = 0
        focus = []
        try:
            for index, turn in enumerate(turns):
                # Advance only repository wall time to test intent/readiness independently
                # of cooldown. No changes to real storage or real clocks.
                clock = (
                    datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=index * 61)
                ).isoformat()
                with patch("app.discovery.now", return_value=clock):
                    await pipeline.service.ingest(
                        sid,
                        TranscriptEvent(
                            event_id=f"fixture-{index}",
                            segment_id=f"fixture-{index}",
                            revision=0,
                            speaker_id="customer",
                            speaker_name="Synthetic customer",
                            text=turn["text"],
                            start_ms=index * 61000,
                            end_ms=index * 61000 + 4000,
                            is_final=True,
                        ),
                    )
                    await pipeline.process_batch(sid)
                    run = pipeline.states[sid]["runs"][-1]
                    premature += (
                        bool(run["suggestion"]["question"]) and not turn["question_allowed"]
                    )
                    focus.append(
                        pipeline.discovery.memory(sid).get("topic_state", {}).get("focus_id")
                    )
            runs = pipeline.states[sid]["runs"]
            return {
                "strategy": strategy,
                "simulated_calls": len(runs),
                "questions": len(pipeline.discovery.detail(mid)["questions"]),
                "questions_outside_allowed_checkpoints": premature,
                "reporting_resumed": bool(focus[0] and focus[0] == focus[4] == focus[5]),
                "pipeline_p50_ms_without_collection_wait": statistics.median(
                    r["latency_ms"] for r in runs
                ),
                "real_provider_calls": 0,
                "provider_tokens": None,
            }
        finally:
            await pipeline.close()


async def main():
    fixture = json.loads(FIXTURE.read_text())
    results = [await evaluate(strategy, fixture["turns"]) for strategy in ("legacy", "topics")]
    print(
        json.dumps(
            {"fixture": fixture["id"], "scope": fixture["scope"], "results": results}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
