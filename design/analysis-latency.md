# Manual analysis latency plan

2026-09-16 · Proposed only; no model calls or runtime changes for this plan.

## Baseline
Latest three successful Luna full reviews took 19.7s, 19.5s and 25.7s. Inputs were
7,656–13,305 tokens; billed outputs 2,599–3,480 tokens. Small sample, not a benchmark.
Current request uses low reasoning, the full finalized transcript and one structured response
covering questions, threads, findings, claims, workflows and spoken questions. Nothing appears
until complete validation/commit. Existing elapsed time does not isolate provider versus local work.

## Implementation order
1. **Measure:** record context-build, provider round trip, parse/validation, commit and UI receipt
   durations. Record cached input and reasoning tokens where supplied, without transcript bodies.
   Compare median/tail latency only on repeated comparable fixtures; do not infer phases from total.
2. **Shorten output, preserve full input:** concise summaries/rationales, changed artifacts only,
   no duplicate facts across fields unless the contract needs them. Keep all evidence and necessary
   threads. Remove conflicting incremental instructions from the full-review prompt. Maintain
   stable instructions/schema before variable content to help caching; caching is not guaranteed.
   Do not merely lower the output cap: truncated JSON fails and wastes the whole request.
3. **Controlled model settings comparison:** compare existing low effort with none where supported
   (Luna supports both), one variable at a time. Keep current default until quality checks pass.
   Do not assume a cheaper model is faster. Paid benchmarks require separately approved call/cost caps.
4. **Honest progress:** show elapsed time, Preparing / Waiting for model / Validating / Saved using
   actual events, not fabricated percentages. Streaming can improve feedback, but incomplete JSON
   must never become saved evidence or final questions. Defer streaming unless it adds useful UX.
5. **Only if insufficient:** propose a separate compact “Suggest a question” action and retain full
   “Review meeting” for threads/notes. This is a product/contract change requiring agreement; do not
   silently replace full review with recent-only context or add a second automatic model call.

## Acceptance
- First target: reduce median full-review duration by 30% on matched synthetic fixtures, with no
  reduction in labeled topic/question recall, grounding or schema success. Aspirational, not SLA.
- Fixtures: a 45-minute meeting, A→B→A topic return, fragmented speech, unknown voices, corrections,
  answered/discarded questions and genuinely no useful follow-up. Score cost and p95 after enough runs.
- Deterministic tests preserve idempotency, invalid-evidence rejection, stop/reset races, concurrent
  edits, workspace isolation and atomic commit. Stored transcripts remain untouched.
- No extra services, agent framework, hidden retries or automatic model fallback. Queues improve
  recovery/backpressure, not provider generation speed. Global spend enforcement remains separate.

## Related correctness blocker
Backend restart currently stops live sessions. Plan a separate meeting lifecycle from capture and
producer connections; capture stop and server restart must not imply explicit interview completion.
Reconnect must reject stale capture producers/results and require explicit audio restart. No database
reopening or lifecycle changes are performed as part of this latency plan.

References: [manual review](context-rebuild.md), [model selection](model-selection.md),
[OpenAI latency guidance](https://developers.openai.com/api/docs/guides/latency-optimization),
[Luna reasoning settings](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
