"""Explicit, one-call Gemini integration check using disposable synthetic data.

Run from the repository root: uv run --directory backend python -m app.gemini_smoke
No real meeting content is read; no key, transcript or provider response body is printed.
"""

import asyncio
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from .broadcast import Broadcaster
from .config import Settings
from .models import TranscriptEvent
from .pipeline import FIXTURE, Pipeline
from .reports import Reports
from .service import Service
from .storage import Storage


async def check(settings):
    if not settings.gemini_api_key.get_secret_value().strip():
        return {"status": "unconfigured", "message": "Add GEMINI_API_KEY to the root .env file."}
    with TemporaryDirectory(prefix="explore-gemini-check-") as directory:
        settings = settings.model_copy(
            update={
                "data_dir": Path(directory),
                "analysis_provider": "gemini",
                "analysis_max_calls": 1,
            }
        )
        storage = Storage(settings.data_dir / "test.sqlite3")
        storage.initialize()
        service = Service(storage, Broadcaster(16))
        # No notification hook: exactly one explicit batch, never a background paid retry.
        pipeline = Pipeline(service, settings)
        session = await service.read(storage.create, "Synthetic Gemini integration check")
        sid = session["id"]
        try:
            position = 0
            for i, turn in enumerate(FIXTURE["turns"][:4]):
                await service.ingest(
                    sid,
                    TranscriptEvent(
                        event_id=f"smoke-{i}",
                        segment_id=f"turn-{i + 1}",
                        revision=0,
                        speaker_id=turn["speaker"],
                        start_ms=position,
                        end_ms=position + turn["duration_ms"],
                        text=turn["text"],
                        is_final=True,
                    ),
                )
                position += turn["duration_ms"]
            started = time.monotonic()
            accepted = await pipeline.process_batch(sid)
            state = await pipeline.view(sid)
            if not accepted:
                return {
                    "status": state["analysis_status"],
                    "message": state["error"],
                    "calls": state["calls"],
                }
            memory = await service.read(pipeline.discovery.memory, sid)
            if len(memory["coverage"]) != 4:
                raise ValueError("Incomplete source coverage")
            await service.stop(sid)
            reports = Reports(storage)
            await service.read(reports.job, sid, "generating", "")
            await service.read(reports.generate, sid, "gemini")
            saved = await service.read(reports.list, session["meeting_id"])
            if saved["job"]["status"] != "complete" or len(saved["reports"]) != 1:
                raise ValueError("Report persistence failed")
            result = state["runs"][-1]
            return {
                "status": "passed",
                "model": settings.gemini_model,
                "calls": state["calls"],
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "usage": result["usage"],
                "processed_segments": len(memory["coverage"]),
                "claims": len(memory["claims"]),
                "question_generated": bool(result["suggestion"]["question"]),
                "report_created": True,
            }
        finally:
            await pipeline.close()


def main():
    try:
        result = asyncio.run(check(Settings()))
    except Exception:
        # SDK/HTTP/validation exceptions may include credentials or model response bodies.
        result = {
            "status": "error",
            "message": "Integration check failed; no private details logged.",
        }
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
