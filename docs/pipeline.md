# Interview test pipeline

`JSON fixture / manual text / external WebSocket → Service.ingest → SQLite → transcript subscribers`

`accepted final event → coalescing analysis worker → Analyzer → validated result → SQLite → browser`

The current workspace data model and CRUD/reset contract are documented in [data-model.md](data-model.md).

## Components
- `backend/fixtures/discovery-v1.json`: reviewed synthetic interview, stable IDs and logical timings. Change its ID when changing its content. Only delivered turns enter model context. Separate checkpoints are never included.
- `Pipeline`: replay cursor, play/pause/next/speed, objective, analysis lifecycle. Replay timestamps advance past previously injected dialogue. Internal replay and browser injection call the same ingestion service as the external WebSocket; this avoids a loopback network dependency.
- `Analyzer` protocol: replace provider without changing replay, persistence or UI. Mock is deliberately simplistic and explicitly labeled. Gemini uses backend-only HTTP, structured JSON and source validation.
- Context: objective plus at most 30 finalized segments and 16,000 transcript characters, plus the validated brief, latest 10 notes (up to 4,000 characters each), and 30 previous question records. Old context is dropped; no long-meeting memory yet. Corrections replace previous text. Model input never includes unreplayed fixture lines or evaluation checkpoints.
- Scheduling: 400 ms collection window, one in-flight call per session and one coalesced pending batch. Duplicate/stale events and provisional updates do not schedule calls. Results are discarded if finalized context changed while the request was running. Stop cancels work.
- Persistence: additive `experiments` table stores cursor, objective and latest 100 run records, including prompt/model version, source IDs, input version, provider token usage and measured latency. No destructive migration. Restart stops live sessions; create a new session for a fresh replay.
- UI: transcript uses existing ordered WebSocket snapshots; experiment state uses sequential 800 ms polling. Multiple tabs see the same backend generation. Polling can add up to 800 ms to display latency; recorded latency covers debounce + provider + validation, not display or STT.

## Browser endpoints
- `GET /fixtures`: scenario metadata, without future dialogue.
- `GET /sessions/{id}/experiment`: replay state and exportable run records.
- `POST /sessions/{id}/playback`: `{ "action": "play|pause|next|configure", "speed": 1, "objective": "..." }`. Objective changes are allowed before dialogue starts. Speeds 0.25–10; timing changes apply at the next scheduled interval. Next pauses automatic playback.
- `POST /sessions/{id}/inject`: the existing complete TranscriptEvent schema. Retry ambiguous failures with the same event ID. The built-in form sends a new finalized segment.
- Existing ingestion WebSocket and transcript endpoints remain compatible. The legacy `/demo` smoke test remains available through the API, but the UI uses the interview fixture.

The browser controls are local controller endpoints guarded by Host/Origin checks. `INGESTION_TOKEN` protects external producers, not these local controls. No remote authentication or public hosting is supplied. Do not expose this development server publicly.

## Gemini
Set `ANALYSIS_PROVIDER=gemini`, `GEMINI_API_KEY` and optionally `GEMINI_MODEL` in root `.env`. Restart the backend. Keep keys out of `VITE_` variables. No automatic fallback to mock: missing credentials and provider failures appear in the panel. Calls have a 25-second overall deadline, 4,096 output-token cap and no automatic retries. `ANALYSIS_MAX_CALLS` defaults to 100 per session (failed attempts count). This caps requests, not spend across sessions.

The adapter uses Google's [GenerateContent structured output API](https://ai.google.dev/gemini-api/docs/generate-content/structured-output). Provider schema, HTTP errors and cancellation are tested without credentials; a real account smoke test is still required. Token usage is exported when provided. Dollar cost estimation is intentionally deferred until the account's model/tier is selected.

## Evaluate
Run at 1× to assess timing; 5×/10× and Next are for debugging. Review the separate fixture checkpoints for grounded, non-leading questions, lack of repetition and adjustment to contradictory evidence. Mock mode validates transport and orchestration only. Synthetic interviews do not establish real-world question quality.

Next additions: explicit helpful/not-helpful ratings, multiple scenarios (including no pain), aggregate latency percentiles, then one real provider smoke test. Audio and meeting integrations should arrive after question quality is useful.
