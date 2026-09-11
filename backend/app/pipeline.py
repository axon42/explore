"""Replay and analysis orchestration, independent of HTTP and model transport."""

import asyncio
import copy
import json
import logging
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .analysis import PROMPT_VERSION, GeminiAnalyzer, MockAnalyzer
from .concurrency import blocking
from .discovery import Discovery
from .models import DomainError, TranscriptEvent

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/discovery-v1.json").read_text()
)


class PlaybackCommand(BaseModel):
    action: Literal["play", "pause", "next", "configure"]
    speed: float = Field(default=1, ge=0.25, le=10)
    objective: str = Field(default=FIXTURE["objective"], max_length=2000)


def finalized(snapshot):
    # A hard character budget protects costs even for large injected segments.
    result, remaining = [], 16000
    for segment in reversed(snapshot["segments"]):
        if not segment["is_final"]:
            continue
        item = {k: segment[k] for k in ("segment_id", "revision", "speaker_id", "text")}
        item["text"] = item["text"][:remaining]
        result.append(item)
        remaining -= len(item["text"])
        if remaining <= 0 or len(result) >= 30:
            break
    return list(reversed(result))


class Pipeline:
    def __init__(self, service, settings):
        self.service, self.settings = service, settings
        self.provider = (
            MockAnalyzer()
            if settings.analysis_provider == "mock"
            else GeminiAnalyzer(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
        )
        self.states, self.locks, self.wakes, self.workers, self.players = {}, {}, {}, {}, {}
        self.closed = False
        self.discovery = Discovery(service.storage)

    def lock(self, sid):
        return self.locks.setdefault(sid, asyncio.Lock())

    async def state(self, sid):
        if sid not in self.states:
            saved = await self.service.read(self.service.storage.experiment, sid)
            self.states[sid] = saved or {
                "fixture_id": FIXTURE["id"],
                "objective": FIXTURE["objective"],
                "cursor": 0,
                "total": len(FIXTURE["turns"]),
                "speed": 1,
                "playing": False,
                "analysis_status": "waiting",
                "result": None,
                "calls": 0,
                "runs": [],
                "error": "",
            }
            self.states[sid]["playing"] = False
            if self.states[sid]["analysis_status"] in ("queued", "analyzing"):
                self.states[sid]["analysis_status"] = "interrupted"
        return self.states[sid]

    async def save(self, sid):
        await self.service.read(self.service.storage.save_experiment, sid, self.states[sid])

    async def view(self, sid):
        async with self.lock(sid):
            state = copy.deepcopy(await self.state(sid))
            state.update(
                provider=self.settings.analysis_provider,
                model="simulated"
                if self.settings.analysis_provider == "mock"
                else self.settings.gemini_model,
                configured=self.settings.analysis_provider == "mock"
                or bool(self.settings.gemini_api_key.get_secret_value()),
            )
            return state

    def notify(self, sid):
        if self.closed:
            return
        if sid in self.states:
            self.states[sid].update(result=None, analysis_status="queued")
        self.wakes.setdefault(sid, asyncio.Event()).set()
        if sid not in self.workers or self.workers[sid].done():
            self.workers[sid] = asyncio.create_task(self.analyze(sid))
            self.workers[sid].add_done_callback(lambda task: self.worker_done(sid, task))

    def worker_done(self, sid, task):
        if not task.cancelled() and task.exception():
            logging.getLogger("meeting").error(
                json.dumps(
                    {
                        "event": "analysis_worker_failed",
                        "session_id": sid,
                        "error_type": type(task.exception()).__name__,
                    }
                )
            )
            if sid in self.states:
                self.states[sid].update(
                    analysis_status="error",
                    error="Analysis storage failed. The next turn will retry.",
                )

    async def command(self, sid, command):
        async with self.lock(sid):
            state = await self.state(sid)
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            if snapshot["session"]["status"] != "live":
                raise DomainError("session_stopped", "Create a new session to run another test")
            if command.action == "configure":
                if snapshot["segments"]:
                    raise DomainError(
                        "already_started", "Set the objective before delivering dialogue"
                    )
                state["objective"] = command.objective
            state["speed"] = command.speed
            if command.action == "pause":
                state["playing"] = False
            elif command.action == "next":
                state["playing"] = False
                await self.deliver(sid)
            elif command.action == "play":
                state["playing"] = state["cursor"] < state["total"]
                if sid not in self.players or self.players[sid].done():
                    self.players[sid] = asyncio.create_task(self.play(sid))
            await self.save(sid)
        return await self.view(sid)

    async def deliver(self, sid):
        state = self.states[sid]
        index = state["cursor"]
        if index >= state["total"]:
            return
        turn = FIXTURE["turns"][index]
        snapshot = await self.service.read(self.service.storage.snapshot, sid)
        start = max(
            sum(t["duration_ms"] for t in FIXTURE["turns"][:index]),
            max((s["end_ms"] for s in snapshot["segments"]), default=0),
        )
        await self.service.ingest(
            sid,
            TranscriptEvent(
                event_id=f"{FIXTURE['id']}-{index}",
                segment_id=f"turn-{index + 1}",
                revision=0,
                speaker_id=turn["speaker"],
                speaker_name="Alex · Cofounder"
                if turn["speaker"] == "cofounder"
                else "Sam · Customer",
                start_ms=start,
                end_ms=start + turn["duration_ms"],
                text=turn["text"],
                is_final=True,
            ),
        )
        state["cursor"] += 1
        if state["cursor"] == state["total"]:
            state["playing"] = False

    async def play(self, sid):
        try:
            while True:
                async with self.lock(sid):
                    state = self.states[sid]
                    if not state["playing"]:
                        return
                    index = state["cursor"]
                    await self.deliver(sid)
                    await self.save(sid)
                    delay = FIXTURE["turns"][index]["duration_ms"] / 1000 / state["speed"]
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self.lock(sid):
                self.states[sid].update(
                    playing=False, error="Replay failed. Try Next turn to retry delivery."
                )
                await self.save(sid)

    async def analyze(self, sid):
        wake = self.wakes[sid]
        while True:
            await wake.wait()
            wake.clear()
            started = time.monotonic()
            await asyncio.sleep(0.4)
            async with self.lock(sid):
                state = await self.state(sid)
                snapshot = await self.service.read(self.service.storage.snapshot, sid)
                if snapshot["session"]["status"] != "live":
                    continue
                segments = finalized(snapshot)
                if not segments:
                    continue
                wake.clear()  # This snapshot includes all events delivered during debounce.
                meeting_context = await self.service.read(self.discovery.context, sid)
                context = {
                    "objective": meeting_context["brief"].get("objective") or state["objective"],
                    "meeting": meeting_context,
                    "segments": segments,
                }
                if state["calls"] >= self.settings.analysis_max_calls:
                    state.update(
                        analysis_status="limited", error="Per-session analysis call limit reached."
                    )
                    await self.save(sid)
                    continue
                if (
                    self.settings.analysis_provider == "gemini"
                    and not self.settings.gemini_api_key.get_secret_value()
                ):
                    state.update(
                        analysis_status="unconfigured",
                        error="Set GEMINI_API_KEY on the server and restart.",
                    )
                    await self.save(sid)
                    continue
                state.update(analysis_status="analyzing", result=None, error="")
                state["calls"] += 1
                await self.save(sid)
            try:
                result, usage = await asyncio.wait_for(self.provider.analyze(context), 25)
                if result.question and (
                    not result.source_ids
                    or not set(result.source_ids) <= {s["segment_id"] for s in segments}
                ):
                    raise ValueError("Invalid evidence references")
                for finding in result.findings:
                    if not finding.source_ids or not set(finding.source_ids) <= {
                        s["segment_id"] for s in segments
                    }:
                        raise ValueError("Invalid finding evidence")
                error = ""
            except asyncio.CancelledError:
                raise
            except Exception:
                result, usage = None, {}
                error = (
                    "Analysis failed. Check server configuration or provider quota; "
                    "the next turn will try again."
                )
            async with self.lock(sid):
                async with self.service.lock:
                    current = await blocking(self.service.storage.snapshot, sid)
                    latest_context = await blocking(self.discovery.context, sid)
                    stale = (
                        current["session"]["status"] != "live"
                        or finalized(current) != segments
                        or latest_context["version"] != meeting_context["version"]
                    )
                    run = {
                        "input_version": snapshot["version"],
                        "source_revisions": {s["segment_id"]: s["revision"] for s in segments},
                        "prompt_version": PROMPT_VERSION,
                        "model": "simulated"
                        if self.settings.analysis_provider == "mock"
                        else self.settings.gemini_model,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "usage": usage,
                        "stale": stale,
                        "error": error,
                        "suggestion": result.model_dump() if result else None,
                    }
                    state["runs"].append(run)
                    state["runs"] = state["runs"][-100:]
                    state.update(
                        analysis_status="waiting" if stale else "error" if error else "ready",
                        result=None if stale else run,
                        error=error if not stale else "",
                    )
                    await blocking(
                        self.discovery.record_run,
                        sid,
                        context,
                        self.settings.analysis_provider,
                        run,
                    )
                    await blocking(self.service.storage.save_experiment, sid, state)

    async def stop(self, sid):
        tasks = [d.pop(sid) for d in (self.players, self.workers) if sid in d]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with self.lock(sid):
            state = await self.state(sid)
            state.update(playing=False, analysis_status="stopped")
            await self.save(sid)

    async def close(self):
        self.closed = True
        for sid in set(self.players) | set(self.workers):
            await self.stop(sid)
