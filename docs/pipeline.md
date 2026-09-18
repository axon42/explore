# Interview test pipeline

`JSON fixture / manual text / external WebSocket → Service.ingest → SQLite → transcript subscribers`

`accepted final event → coalescing analysis worker → Analyzer → validated result → SQLite → browser`

The current workspace data model and CRUD/reset contract are documented in [data-model.md](data-model.md).

## Components
- `backend/fixtures/discovery-v1.json`: reviewed synthetic interview, stable IDs and logical timings. Change its ID when changing its content. Only delivered turns enter model context. Separate checkpoints are never included.
- `Pipeline`: replay cursor, play/pause/next/speed, objective, analysis lifecycle. Replay timestamps advance past previously injected dialogue. Internal replay and browser injection call the same ingestion service as the external WebSocket; this avoids a loopback network dependency.
- `Analyzer` protocol: replace provider without changing replay, persistence or UI. Mock is deliberately simplistic and explicitly labeled. Gemini uses backend-only HTTP, structured JSON and source validation.
- Context and scheduling: persisted structured memory, bounded unprocessed/recent dialogue, a one-second idle/five-second maximum collection policy, and one active analysis call. Compatible new speech no longer invalidates committed state; corrected sources and changed human context do. See [analysis and reports](analysis.md) for exact limits and contracts.
- Persistence: experiments store replay state/call counts; relational analysis runs and revisioned evidence retain provenance. Migration 2 adds state checkpoints, participants and report records without replacing source data.
- Stop closes ingestion and schedules report finalization; test reset cancels work and removes its documented working-data scope. Clear meetings archives without deletion and requires sessions to be ended. Pause only pauses playback.
- UI: the connected workspace polls transcript and meeting state every 800 ms. Multiple tabs share the backend state. Provider timing does not measure browser rendering or STT.

## Browser endpoints
- `GET /fixtures`: scenario metadata, without future dialogue.
- `GET /sessions/{id}/experiment`: replay state and exportable run records.
- Test tools require enabled Test mode and a test/legacy session. Real interviews reject these endpoints.
- `POST /sessions/{id}/playback`: `{ "action": "play|pause|next|configure", "speed": 1, "objective": "..." }`. Objective changes are allowed before dialogue starts. Speeds 0.25–10; timing changes apply at the next scheduled interval. Next pauses automatic playback.
- `POST /sessions/{id}/inject`: the existing complete TranscriptEvent schema. Retry ambiguous failures with the same event ID. The built-in form sends a new finalized segment.
- Existing ingestion WebSocket and transcript endpoints remain compatible. The legacy `/demo` smoke test remains available through the API, but the UI uses the interview fixture.

The browser controls are local controller endpoints guarded by Host/Origin checks. `INGESTION_TOKEN` protects external producers, not these local controls. No remote authentication or public hosting is supplied. Do not expose this development server publicly.

## Gemini
Set `ANALYSIS_PROVIDER=gemini`, `GEMINI_API_KEY` and optionally `GEMINI_MODEL` in root `.env`. Restart the backend. Keep keys out of `VITE_` variables. No automatic fallback to mock: missing credentials and provider failures appear in the panel. Calls have a configurable 45-second overall deadline (`ANALYSIS_TIMEOUT_SECONDS`, maximum 60), 4,096 output-token cap and no automatic retries. `ANALYSIS_MAX_CALLS` defaults to 100 per session (failed attempts count). Final review separately permits `FINAL_REVIEW_MAX_CALLS=2` attempts per session (0 disables it, maximum 10). Failed/cancelled reservations count; unchanged successful reviews do not. These cap requests, not dollar spend.

The adapter uses Google's [GenerateContent structured output API](https://ai.google.dev/gemini-api/docs/generate-content/structured-output). Provider schema, HTTP errors and cancellation are tested without credentials. The real synthetic integration check has also passed. Token usage is exported when provided. Dollar cost estimation is intentionally deferred until the account's model/tier is selected.

## Evaluate
Run at 1× to assess timing; 5×/10× and Next are for debugging. Review the separate fixture checkpoints for grounded, non-leading questions, lack of repetition and adjustment to contradictory evidence. Mock mode validates transport and orchestration only. Synthetic interviews do not establish real-world question quality.

Next additions: explicit helpful/not-helpful ratings, multiple scenarios (including no pain), aggregate latency percentiles, then one real provider smoke test. Audio and meeting integrations should arrive after question quality is useful.

## Explicit connection check

After adding `GEMINI_API_KEY` to the ignored root `.env`, run:

```bash
uv run --directory backend python -m app.gemini_smoke
```

This explicitly makes **one Gemini call** with four synthetic fixture turns in a temporary database.
It validates structured output, evidence, persisted coverage and report creation, then removes its
test data. It does not read existing meetings or change the running server's provider. Output contains
status/counts/latency/token usage, never credentials or transcript bodies. Missing credentials make
no request; HTTP/auth/quota errors use fixed safe messages and are not automatically retried.

After the real check passes, set `ANALYSIS_PROVIDER=gemini` and restart the dev launcher without an
`ANALYSIS_PROVIDER=mock` or empty `GEMINI_API_KEY` environment override. Environment variables take
precedence over `.env`. Confirm the experiment endpoint shows `provider=gemini` and `configured=true`
before replaying a new synthetic interview in the browser. The real-key check passed on 2026-09-11: four segments processed, an evidence-linked question generated and a final report saved, in 7.28 seconds (936 input / 521 output tokens). This is one integration measurement, not a latency or quality guarantee.


The provider schema inlines types and omits size constraints that remain enforced by Pydantic after
receipt. Evidence fields, including workflow transitions, are constrained to supplied segment IDs;
transitions never contain step labels. This fixes a mismatch found in the real model response.
The key remains backend-only. No billing settings were changed; keep the AI Studio project on Free
Tier without linked billing for the user's current zero-spend testing plan. No model fallback or
automatic retry is enabled.

Speaker-aware context uses the shared resolver and session attribution version. Exact speaker spans
are optional for legacy events; unknown channels never imply a customer. Human confirmations can
trigger reanalysis with no new text, subject to existing limits. See [speaker design](../design/speaker-attribution.md).
