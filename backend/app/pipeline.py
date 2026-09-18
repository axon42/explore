"""Replay and analysis orchestration, independent of HTTP and model transport."""

import asyncio
import copy
import json
import logging
import time
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, Field

from .analysis import PROMPT_VERSION, ProviderError
from .analysis_errors import validation_failure
from .analysis_preferences import AnalysisPreferences
from .analysis_state import (
    AnalysisStrategy,
    ContextBuilder,
    TriggerPolicy,
    reconcile,
    reduce_memory,
    validate_proposal,
)
from .concurrency import blocking
from .diagnostics import ACTIVE_TRACE, Diagnostics
from .discovery import Discovery
from .manual_analysis import ManualAnalysis, fingerprint, full_context
from .model_selection import ModelSelection
from .models import DomainError, TranscriptEvent
from .overview import OverviewStrategy
from .spoken_questions import accepted as accepted_spoken
from .topics import (
    add_topic_context,
    advance_topic_state,
    normalize_topic_routing,
    question_ready,
    resolve_topics,
    validate_topics,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/discovery-v1.json").read_text()
)


class PlaybackCommand(BaseModel):
    action: Literal["play", "pause", "next", "configure"]
    speed: float = Field(default=1, ge=0.25, le=10)
    objective: str = Field(default=FIXTURE["objective"], max_length=2000)


class Pipeline:
    def __init__(self, service, settings):
        self.service, self.settings = service, settings
        self.models = ModelSelection(service.storage, settings)
        self.provider = self.models.analyzer(self.models.initial)
        self.states, self.locks, self.wakes, self.workers, self.players = {}, {}, {}, {}, {}
        self.trigger = TriggerPolicy()
        self.context_builder = ContextBuilder()
        self.diagnostics = Diagnostics(service.storage, settings)
        self.strategy = AnalysisStrategy()
        self.overview_strategy = OverviewStrategy()
        self.report_workers = {}
        self.manual_workers = {}
        self.manual = ManualAnalysis(service.storage)
        self.closed = False
        self.discovery = Discovery(service.storage)
        self.preferences = AnalysisPreferences(service.storage, settings.analysis_strategy)

    async def analysis_preferences(self):
        preferences = await self.service.read(self.preferences.get)
        return {**preferences, "model_selection": await self.service.read(self.models.get)}

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
            preferences = await self.analysis_preferences()
            state.update(
                strategy=preferences["strategy"],
                provider=preferences["model_selection"]["provider"],
                model=preferences["model_selection"]["model"],
                configured=self.models.configured(preferences["model_selection"]["provider"]),
            )
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            context = await self.service.read(self.discovery.context, sid)
            memory = reconcile(await self.service.read(self.discovery.memory, sid), snapshot)
            finals = [s for s in snapshot["segments"] if s["is_final"]]
            pending = [
                s for s in finals if memory["coverage"].get(s["segment_id"]) != s["revision"]
            ]
            through = 0
            for segment in finals:
                if memory["coverage"].get(segment["segment_id"]) != segment["revision"]:
                    break
                through = max(through, segment["end_ms"])
            state["scheduling"] = {
                **await self.service.read(self.manual.settings, sid),
                "job": await self.service.read(self.manual.receipt, sid),
                "pending_segments": len(pending),
                "final_segments": len(finals),
                "analyzed_through_ms": through,
                "remaining_calls": max(0, self.settings.analysis_max_calls - state["calls"]),
                "changed": bool(finals)
                and memory.get("manual_fingerprint") != fingerprint(snapshot, context, preferences),
            }
            return state

    async def set_schedule(self, sid, mode, revision):
        async with self.lock(sid):
            state = await self.state(sid)
            if state["analysis_status"] == "analyzing":
                raise DomainError(
                    "analysis_running", "Wait for the current analysis before changing scheduling."
                )
            result = await self.service.read(self.manual.update, sid, mode, revision)
            self.wakes.setdefault(sid, asyncio.Event()).clear()
            state.update(analysis_status="waiting", error="")
            await self.save(sid)
            return result

    async def submit_manual(self, sid, request_id, *, final_review=False):
        async with self.lock(sid):
            schedule = await self.service.read(self.manual.settings, sid, True)
            previous = await self.service.read(self.manual.receipt, sid, request_id)
            if previous:
                return previous
            state = await self.state(sid)
            if schedule["mode"] != "manual" and not final_review:
                raise DomainError(
                    "manual_required", "Select Manual scheduling before analyzing now."
                )
            if state["analysis_status"] == "analyzing":
                raise DomainError(
                    "analysis_running", "Analysis is already running for this meeting."
                )
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            meeting = await self.service.read(self.discovery.context, sid, True)
            memory = reconcile(await self.service.read(self.discovery.memory, sid), snapshot)
            preferences = await self.analysis_preferences()
            digest = fingerprint(snapshot, meeting, preferences)
            if final_review and snapshot["session"]["status"] != "stopped":
                raise DomainError("conflict", "End the meeting before its final review.")
            reviewed = (
                (
                    memory.get("final_review_fingerprint") == digest
                    and memory.get("final_review_version") == memory["version"]
                )
                if final_review
                else digest == memory.get("manual_fingerprint")
            )
            if reviewed:
                raise DomainError(
                    "analysis_unchanged", "All current input has already been analyzed."
                )
            context = full_context(snapshot, meeting, memory, state["objective"])
            if not context["segments"]:
                raise DomainError("no_transcript", "Capture finalized speech before analyzing.")
            if preferences["strategy"] == "topics":
                context["strategy"] = "topics-v1"
                context["topics"] = await self.service.read(
                    self.manual.catalog, sid, context, memory
                )
            context.update(
                session_id=sid,
                meeting_id=snapshot["session"]["meeting_id"],
                model_selection=preferences["model_selection"],
                analysis_mode=preferences["strategy"],
                analysis_settings_revision=preferences["revision"],
                schedule_revision=schedule["revision"],
                job_id=request_id,
                input_fingerprint=digest,
                review_kind="final" if final_review else "live",
                question_allowed=snapshot["session"]["status"] == "live"
                and await self.service.read(self.discovery.question_allowed, sid),
            )
            from .analysis import request_payload
            from .openai_analysis import request_payload as openai_payload

            try:
                selection = preferences["model_selection"]
                if selection["provider"] == "openai":
                    openai_payload(context, selection["model"])
                else:
                    request_payload(context)
            except ProviderError as exc:
                raise DomainError(exc.code, str(exc), 422) from None
            if final_review:
                attempts = await self.service.read(self.manual.final_attempts, sid)
                if attempts >= self.settings.final_review_max_calls:
                    raise DomainError(
                        "final_review_limit",
                        "Final-review call limit is exhausted. No model request was sent. "
                        "Increase FINAL_REVIEW_MAX_CALLS before retrying.",
                    )
            elif state["calls"] >= self.settings.analysis_max_calls:
                raise DomainError("analysis_limit", "Per-session analysis call limit reached.")
            if not self.models.configured(selection["provider"]):
                raise DomainError(
                    "analysis_unconfigured",
                    "Configure the selected provider API key on the server and restart.",
                )
            reserved = {
                **state,
                "calls": state["calls"] + (0 if final_review else 1),
                "analysis_status": "analyzing",
                "error": "",
            }
            await self.service.read(self.manual.begin, sid, context, reserved)
            state.update(reserved)
            prepared = (snapshot, meeting, memory, context, preferences)
            self.manual_workers[sid] = asyncio.create_task(self.run_manual(sid, prepared))
            self.manual_workers[sid].add_done_callback(lambda task: self.worker_done(sid, task))
            return await self.service.read(self.manual.receipt, sid, request_id)

    async def run_manual(self, sid, prepared):
        try:
            await self.process_batch(sid, prepared=prepared)
        finally:
            await self.service.read(self.manual.interrupt, sid, prepared[3]["job_id"])
            async with self.lock(sid):
                state = await self.state(sid)
                if state["analysis_status"] == "analyzing":
                    state.update(
                        analysis_status="interrupted",
                        error="Analysis interrupted. Retry explicitly.",
                    )
                    await self.save(sid)

    def notify(self, sid):
        if self.closed:
            return
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
                    error="Analysis storage failed. Retry analysis explicitly.",
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
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            schedule = await self.service.read(self.manual.settings, sid)
            if schedule["mode"] == "manual":
                wake.clear()
                continue
            preferences = await self.analysis_preferences()
            audio = preferences["strategy"] == "topics" or any(
                s["segment_id"].startswith("audio-") for s in snapshot["segments"]
            )
            settled = await (
                TriggerPolicy(idle_seconds=4, max_wait_seconds=25) if audio else self.trigger
            ).collect(wake)
            await self.process_batch(
                sid, allow_questions=settled, schedule_revision=schedule["revision"]
            )

    async def process_batch(
        self, sid, closing=False, allow_questions=True, prepared=None, schedule_revision=None
    ):
        started = time.monotonic()
        async with self.lock(sid):
            state = await self.state(sid)
            manual = prepared is not None
            schedule = await self.service.read(self.manual.settings, sid)
            if manual:
                snapshot, meeting_context, memory, context, preferences = prepared
                closing = snapshot["session"]["status"] != "live"
                topic_mode = preferences["strategy"] == "topics"
            else:
                if (
                    schedule["mode"] != "automatic"
                    or (schedule_revision is not None and schedule["revision"] != schedule_revision)
                    or state["analysis_status"] == "analyzing"
                ):
                    return False
                snapshot = await self.service.read(self.service.storage.snapshot, sid)
                if snapshot["session"]["status"] != "live" and not closing:
                    return False
                meeting_context = await self.service.read(self.discovery.context, sid)
                memory = reconcile(await self.service.read(self.discovery.memory, sid), snapshot)
                context = self.context_builder.build(
                    snapshot,
                    meeting_context,
                    memory,
                    state["objective"],
                    state.get("batch_reduction", 0),
                )
                if context is None or not context["segments"]:
                    return False
                # Freeze the choice for this invocation, including validation and commit after I/O.
                preferences = await self.analysis_preferences()
                topic_mode = preferences["strategy"] == "topics"
                if not closing and (
                    topic_mode
                    or any(s["segment_id"].startswith("audio-") for s in context["segments"])
                ):
                    # Keep fragments pending until there is enough speech for useful reasoning.
                    if (not topic_mode or not memory["coverage"]) and sum(
                        len(s["text"].split()) for s in context["segments"]
                    ) < 35:
                        state.update(analysis_status="listening", error="")
                        await self.save(sid)
                        return False
                context["question_allowed"] = (
                    allow_questions
                    and not closing
                    and await self.service.read(self.discovery.question_allowed, sid)
                )
                if topic_mode:
                    catalog = await self.service.read(
                        self.discovery.topic_catalog, sid, context, memory
                    )
                    try:
                        context = add_topic_context(context, memory, catalog)
                    except ValueError:
                        state.update(
                            analysis_status="limited",
                            error=(
                                "Topic context exceeds its budget. "
                                "Reduce the brief or included notes before retrying."
                            ),
                        )
                        await self.save(sid)
                        return False
                context["session_id"] = sid
                context["meeting_id"] = snapshot["session"]["meeting_id"]
                context["model_selection"] = preferences["model_selection"]
                context["analysis_mode"] = preferences["strategy"]
                context["analysis_settings_revision"] = preferences["revision"]
                context["scheduling_mode"] = "automatic"
                context["schedule_revision"] = schedule["revision"]
                context["job_id"] = str(uuid5(NAMESPACE_URL, json.dumps(context, sort_keys=True)))
                if state["calls"] >= self.settings.analysis_max_calls:
                    state.update(
                        analysis_status="limited", error="Per-session analysis call limit reached."
                    )
                    await self.save(sid)
                    return False
                if not self.models.configured(preferences["model_selection"]["provider"]):
                    state.update(
                        analysis_status="unconfigured",
                        error="Configure the selected provider API key on the server and restart.",
                    )
                    await self.save(sid)
                    return False
                state.update(analysis_status="analyzing", result=None, error="")
                state["calls"] += 1
                await self.save(sid)
        selection = context["model_selection"]
        provider_name, model_name = selection["provider"], selection["model"]
        analyzer = (
            self.provider
            if all(selection[key] == self.models.initial[key] for key in ("provider", "model"))
            else self.models.analyzer(selection)
        )
        validation_code = ""
        provider_code = ""
        usage = {}
        trace = await self.service.read(
            self.diagnostics.begin,
            sid,
            context,
            model_name,
            self.settings.analysis_timeout_seconds,
        )
        trace_token = ACTIVE_TRACE.set(trace)
        try:
            result, usage = await asyncio.wait_for(
                self.strategy.analyze(analyzer, context),
                self.settings.analysis_timeout_seconds,
            )
            if trace.capture and provider_name == "mock":
                trace.response = result.model_dump()
            if manual and not getattr(result, "complete", False):
                raise ProviderError(
                    "The model could not complete the full review within its output "
                    "limits. Previous analysis is unchanged; retry explicitly.",
                    "full_output_incomplete",
                )
            trace.metadata["workflow_order_normalizations"] = sum(
                len(w.transitions) != len(w.steps) - 1 for w in result.workflows
            )
            validate_proposal(result, context)
            trace.metadata["question_decision"] = "proposed" if result.question else "model_empty"
            result, rejected_spoken = accepted_spoken(result, context)
            trace.metadata["spoken_questions_rejected"] = rejected_spoken
            trace.metadata["spoken_questions_accepted"] = len(result.spoken_questions)
            if rejected_spoken:
                logging.getLogger("meeting").warning(
                    json.dumps(
                        {"event": "spoken_question_quotes_rejected", "count": rejected_spoken}
                    )
                )
            if topic_mode:
                result = normalize_topic_routing(result, context)
                validate_topics(result, context)
                ready = question_ready(result, context)
                result = resolve_topics(result, context)
                if not ready:
                    trace.metadata["question_decision"] = "topic_not_ready"
                    result = result.model_copy(update={"question": "", "source_ids": []})
            error = ""
        except asyncio.CancelledError:
            await self.service.read(self.diagnostics.save, trace, "cancelled", "cancelled")
            raise
        except ProviderError as exc:
            result, usage = None, {}
            error = str(exc)
            provider_code = exc.code
        except TimeoutError:
            result, usage = None, {}
            provider_code = "analysis_deadline"
            trace.metadata["error_stage"] = "analysis_deadline"
            error = (
                f"Analysis exceeded the {self.settings.analysis_timeout_seconds}-second deadline."
            )
        except ValueError as exc:
            result = None
            validation_code, error = validation_failure(exc)
            logging.getLogger("meeting").warning(
                json.dumps(
                    {
                        "event": "analysis_rejected",
                        "session_id": sid,
                        "job_id": context["job_id"],
                        "code": validation_code,
                    }
                )
            )
        except Exception as exc:
            result, usage = None, {}
            provider_code = "analysis_unexpected"
            trace.metadata["error_type"] = type(exc).__name__
            error = "Analysis failed. Check configuration or quota; retry or deliver another turn."
        finally:
            ACTIVE_TRACE.reset(trace_token)
        if not usage:
            usage = trace.metadata.get("usage", {})
        async with self.lock(sid):
            async with self.service.lock:
                if provider_code.startswith("provider_timeout_") or provider_code in {
                    "provider_deadline",
                    "analysis_deadline",
                }:
                    state["batch_reduction"] = min(3, state.get("batch_reduction", 0) + 1)
                current = await blocking(self.service.storage.snapshot, sid)
                latest_context = await blocking(self.discovery.context, sid)
                latest_schedule = await blocking(self.manual.settings, sid)
                revisions = {s["segment_id"]: s["revision"] for s in current["segments"]}
                stale = (
                    latest_schedule["revision"] != context["schedule_revision"]
                    or (current["session"]["status"] != "live" and not closing)
                    or current["session"].get("attribution_version", 0)
                    != context.get("attribution_version", 0)
                    or any(
                        revisions.get(s["segment_id"]) != s["revision"] for s in context["segments"]
                    )
                    or latest_context["version"] != meeting_context["version"]
                )
                updated = None
                if not stale and not error:
                    updated = reduce_memory(memory, current, context, result)
                    if manual:
                        updated["manual_fingerprint"] = context["input_fingerprint"]
                        if context.get("review_kind") == "final":
                            updated["final_review_fingerprint"] = context["input_fingerprint"]
                            updated["final_review_version"] = updated["version"]
                    if topic_mode:
                        updated = advance_topic_state(updated, context, result)
                    updated["overview"] = self.overview_strategy.build(updated, result.summary)
                    pending = any(
                        s["is_final"] and updated["coverage"].get(s["segment_id"]) != s["revision"]
                        for s in current["segments"]
                    )
                    speaking = any(not s["is_final"] for s in current["segments"])
                    allowed = await blocking(self.discovery.question_allowed, sid)
                    if result.question:
                        reason = (
                            "meeting_ended"
                            if closing
                            else "questions_disabled_or_cooldown"
                            if not allowed or not allow_questions or not context["question_allowed"]
                            else "new_speech"
                            if (pending or speaking) and not manual
                            else "accepted"
                        )
                        trace.metadata["question_decision"] = reason
                        if reason != "accepted":
                            result = result.model_copy(update={"question": "", "source_ids": []})
                    # Manual questions belong to the explicit frozen review. New speech
                    # stays pending and is visible in the UI; it must not starve every review.
                    if pending and not closing and not manual:
                        self.wakes[sid].set()
                elif stale and not closing and not manual:
                    self.wakes[sid].set()
                run = {
                    "scheduling_mode": context["scheduling_mode"],
                    "input_version": snapshot["version"],
                    "source_revisions": {
                        s["segment_id"]: s["revision"] for s in context["segments"]
                    },
                    "prompt_version": (
                        "discovery-final-v1"
                        if context.get("review_kind") == "final"
                        else "discovery-full-v4"
                        if manual
                        else PROMPT_VERSION
                    ),
                    "review_kind": context.get("review_kind", "live"),
                    "model": model_name,
                    "provider": provider_name,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "usage": usage,
                    "stale": stale,
                    "error": error,
                    "validation_code": validation_code,
                    "provider_code": provider_code,
                    "request_id": trace.id,
                    "suggestion": result.model_dump() if result else None,
                    "review": {
                        "empty": not any(
                            [
                                result.question,
                                result.findings,
                                result.claims,
                                result.workflows,
                                result.matches,
                                result.spoken_questions,
                                getattr(getattr(result, "topic", None), "updates", []),
                            ]
                        ),
                        "reason": getattr(getattr(result, "topic", None), "reason", "")
                        or result.rationale,
                    }
                    if result and not error and not stale
                    else None,
                }
                state["runs"].append(run)
                state["runs"] = state["runs"][-100:]
                state.update(
                    analysis_status="stale"
                    if stale and manual
                    else "waiting"
                    if stale
                    else "error"
                    if error
                    else "ready",
                    result=None if stale else run,
                    error=error
                    if not stale
                    else "Input changed. Analyze again to update context."
                    if manual
                    else "",
                )
                await blocking(
                    self.discovery.record_run,
                    sid,
                    context,
                    provider_name,
                    run,
                    updated,
                )
                await blocking(self.service.storage.save_experiment, sid, state)
                await blocking(
                    self.diagnostics.save,
                    trace,
                    "stale" if stale else "error" if error else "ok",
                    provider_code or validation_code,
                    usage,
                )
                logging.getLogger("meeting").info(
                    json.dumps(
                        {
                            "event": "analysis_completed",
                            "request_id": trace.id,
                            "session_id": sid,
                            "job_id": context["job_id"],
                            "outcome": "stale" if stale else "error" if error else "ok",
                            "code": provider_code or validation_code,
                            "elapsed_ms": run["latency_ms"],
                        }
                    )
                )
                return updated is not None

    async def request_report(self, sid):
        from .reports import Reports

        repo = Reports(self.service.storage)
        async with self.lock(sid):
            if sid in self.report_workers and not self.report_workers[sid].done():
                return
            await self.service.read(repo.job, sid, "pending", "")
            self.report_workers[sid] = asyncio.create_task(self.finalize(sid))
            self.report_workers[sid].add_done_callback(lambda task: self.worker_done(sid, task))

    async def finalize(self, sid):
        from .reports import Reports

        repo = Reports(self.service.storage)
        try:
            await self.service.read(repo.job, sid, "generating", "")
            snapshot = await self.service.read(self.service.storage.snapshot, sid)
            if any(s["is_final"] for s in snapshot["segments"]):
                job_id = str(uuid4())
                try:
                    await self.submit_manual(sid, job_id, final_review=True)
                except DomainError as exc:
                    if exc.code != "analysis_unchanged":
                        raise
                else:
                    await self.manual_workers[sid]
                    receipt = await self.service.read(self.manual.receipt, sid, job_id)
                    if receipt["status"] != "succeeded":
                        raise DomainError("final_review_failed", "Final review did not complete.")
            await self.service.read(repo.generate, sid, self.settings.analysis_provider)
        except asyncio.CancelledError:
            raise
        except DomainError as exc:
            message = (
                "Final review blocked: the per-session analysis call limit is exhausted. "
                "No model request was sent. Increase the configured limit before retrying."
                if exc.code == "analysis_limit"
                else str(exc)
            )
            await self.service.read(
                repo.job,
                sid,
                "failed",
                f"{message} Transcript and earlier reports are preserved.",
            )
        except Exception:
            await self.service.read(
                repo.job,
                sid,
                "failed",
                "Final review incomplete. Transcript and earlier reports are preserved. "
                "Check analysis diagnostics, then retry final review.",
            )

    async def stop(self, sid):
        tasks = [
            d.pop(sid)
            for d in (self.players, self.workers, self.report_workers, self.manual_workers)
            if sid in d
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with self.lock(sid):
            state = await self.state(sid)
            state.update(playing=False, analysis_status="stopped")
            await self.save(sid)

    async def close(self):
        self.closed = True
        for sid in (
            set(self.players)
            | set(self.workers)
            | set(self.report_workers)
            | set(self.manual_workers)
        ):
            await self.stop(sid)
