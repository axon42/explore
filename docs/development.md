# Development reference — local meeting transcripts

Browser React workspace backed by FastAPI and SQLite. The [pipeline guide](pipeline.md) describes the interview lab, replay controls and optional Gemini analysis. This reference covers the underlying transcript API and development workflow.

## Setup and run

User testing preference: **Firefox**, using **http://127.0.0.1:5173** consistently.
Keep this port and hostname stable across restarts; browser permissions and storage are origin-specific.
Disposable automated test servers may use separate ports; do not redirect the user's testing workflow.

Prerequisites: **Node.js 22.12+** (Node 22 is selected by `.nvmrc`), **Python 3.12+**, and **uv**. Use npm for frontend dependencies. Install uv using [its official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

From this repository:

```bash
nvm use                    # if you use nvm; otherwise activate Node 22.12+
cp .env.example .env       # once; preserve an existing .env
npm --prefix frontend ci
uv sync --project backend --locked
bash scripts/dev.sh
```

After initial setup, **`uv run --project backend python scripts/dev.py`** starts both servers on Windows, macOS or Linux (`bash scripts/dev.sh` also works on POSIX systems). Open **http://127.0.0.1:5173**. Choose **New meeting → save participants and brief → Start interview**. For synthetic playback, enable **Test mode** in the bottom left, choose **Use sample participants → Start test meeting → Play**. **End interview** stops capture and generates the report. Ctrl-C stops both processes cleanly. Vite supports frontend hot reload; restart the command after backend/configuration changes.

This is a **localhost development app**. Both servers bind to `127.0.0.1`; do not expose them publicly or use tunnels. Use exactly one backend process/worker. No Docker or external services are needed.

Optional Mac capture: [setup](macos-capture.md) and [design](../design/macos-audio-capture.md).

## Configuration

Copy `.env.example` to `.env`; explicit environment variables override it. Relative `DATA_DIR` paths resolve from the repository root.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `./data` | Working `meetings.sqlite3`; durable transcript archive uses sibling `<directory name>-transcripts` |
| `BACKEND_PORT` | `8000` | FastAPI and internal demo producer port |
| `FRONTEND_PORT` | `5173` | Vite and allowed browser origin port |
| `DEMO_ENABLED` | `true` | Enables the development-only demo endpoint/button; set `false` to disable |
| `INGESTION_TOKEN` | empty | Optional shared token required on ingestion sockets |
| `SUBSCRIBER_QUEUE_SIZE` | `128` | Maximum queued messages per UI subscriber |

The data directory, environment files, dependencies, and generated artifacts are ignored by Git. If configuring a data directory outside `data/`, keep that directory outside the checkout or add it to `.gitignore`. SQLite content is local plaintext, not encrypted.

## API and a future provider adapter

FastAPI listens at `http://127.0.0.1:8000`. Vite forwards `/api/*` and `/api/*` WebSocket upgrades to FastAPI, stripping `/api`. No permissive CORS is configured. HTTP browser requests and WebSockets validate local origins and hosts; headless ingestion clients may omit Origin.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Health and demo capability |
| `POST /sessions` | Retired (409); create a draft meeting and use its prepared start endpoint |
| `GET /sessions` | Sessions, newest first |
| `GET /sessions/{id}` | Consistent snapshot: session, current segments, version |
| `POST /sessions/{id}/stop` | Idempotently stop the session; reject subsequent ingestion |
| `POST /sessions/{id}/demo` | Development-only replay; rejects concurrent/already-used demos |
| `WS /sessions/{id}/ingest` | Provider-neutral input and acknowledgements |
| `WS /sessions/{id}/events` | Initial snapshot, then segment/status updates |

Create a session, then have a future adapter connect to `ws://127.0.0.1:8000/sessions/{id}/ingest`. If configured, send `Authorization: Bearer <INGESTION_TOKEN>` as a **header**, never a query parameter. Keep tokens out of frontend code and `VITE_` variables. Adapter scripts may omit the Origin header; browser event subscribers must send an allowed local Origin.

Send one JSON text frame per event:

```json
{
  "event_id": "evt-123",
  "segment_id": "seg-42",
  "revision": 1,
  "speaker_id": "speaker-1",
  "speaker_name": "Alex",
  "start_ms": 12000,
  "end_ms": 15800,
  "text": "We review these requests every morning.",
  "is_final": true
}
```

`event_id` identifies a delivery and must be stable when retried. `segment_id` identifies an utterance. Increment `revision` for every change to that utterance. Speaker name may be omitted or null; all other fields are required. Timestamps are nonnegative integer milliseconds relative to session start; end must be at least start. Revision is a nonnegative integer. Numeric fields cannot exceed JavaScript’s safe integer limit (9,007,199,254,740,991). Fields are strictly typed; unknown fields are rejected. Text is limited to 20,000 characters and frames to 64 KiB (oversized transport frames may close with code 1009).

Read the acknowledgement before considering a delivery complete:

```json
{"type":"ack","event_id":"evt-123","outcome":"accepted","version":1}
```

Accepted events are acknowledged **after the transaction commits**. Repeated event IDs return `outcome: "ignored", reason: "duplicate"`. Older/equal revisions return `stale_revision`; a provisional update to a finalized segment returns `finalized_segment`. These ignored deliveries do not advance the session version. Newer final corrections replace the segment. Seen IDs are retained, including ignored revisions, so use a new event ID for a corrected delivery.

Invalid payloads return `{"type":"error","code":"invalid_event","message":"Invalid transcript event","details":[...]}` without closing ingestion. Other codes include `invalid_frame`, `session_stopped`, `not_found`, and retryable `storage_error`. Errors omit transcript inputs. Reconnect and retry unacknowledged deliveries using the same event IDs after a transport failure.

The UI socket sends:

- `snapshot`: `{type, version, session, segments}`
- `segment`: `{type, version, segment}`
- `status`: `{type, version, session}`
- `demo_error`: a development replay failure message

Version increases for each committed segment change or status change. Snapshots and subscription registration share the same process lock as commit/broadcast; updates cannot be lost between snapshot and subscription. A bounded queue isolates each viewer. Overflow disconnects that viewer with code **1013** to force a fresh snapshot. The UI reconnects at 1, 2, 4, 8, then at most 15-second intervals; the delay resets after a snapshot. It merges segments by ID and revision and ignores older versions. HTTP snapshots keep saved history readable when WebSockets are unavailable.

## CLI replay

The button and CLI both call `backend/app/replay.py`, which sends events through the public ingestion WebSocket. The roughly 13-second replay includes Alex and Sam, pauses, interim/final text, a final correction, an exact duplicate, and a stale revision. A demo runs once per session; create another session to replay it afresh. Replay completion leaves the session live until you stop it.

With `.env` copied in setup:

```bash
# Create a session and copy the returned id:
curl -s http://127.0.0.1:8000/sessions \
  -H 'Content-Type: application/json' -d '{"title":"Replay example"}'

bash scripts/replay.sh SESSION_ID
# Optional faster replay or different backend port:
bash scripts/replay.sh SESSION_ID --speed 2 --base-url ws://127.0.0.1:8000
```

The CLI loads `.env` through uv; the shared token is read from the environment. Demo tasks are cancelled on stop/shutdown. Structured JSON application logs include lifecycle, connection, and error codes, without transcript bodies or credentials. Uvicorn also emits its normal server/connection logs.

## Verification

```bash
uv run --project backend ruff check backend scripts
uv run --project backend ruff format --check backend scripts
uv run --project backend pytest backend/tests -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build

# One-time browser install, then end-to-end tests:
cd frontend
npx playwright install chromium
npm run test:browser
```

If the bundled browser does not support your OS but Google Chrome is installed:

```bash
cd frontend
PLAYWRIGHT_CHANNEL=chrome npm run test:browser
```

Browser tests start their own servers on ports **5174/8001** and persist disposable history under `data/browser-tests/`. They cover evolving transcript text, final corrections/deduplication, stop and reload, responsive layout, reconnection with a change during disconnection, and scroll position/Jump to latest. Screenshots and failure traces are saved in `frontend/test-results/`. Run one browser test invocation at a time.

Backend tests cover persistence, crash recovery, concurrent duplicates, revisions, invalid payloads, stopped sessions, snapshot ordering, reconnection, bounded queues, origin/token validation, replay-task cancellation, and storage failure retries.

Browser tests use one worker because Test mode and analysis preferences are backend-wide.
Transcript archive tests use only disposable synthetic databases outside the user's archive.

## Structure and constraints

```text
frontend/src/       React interface, WebSocket state, Tailwind/CSS
frontend/tests/     Playwright browser tests
backend/app/
  main.py          API handlers, WebSocket lifecycle, development replay task
  models.py        Provider-neutral Pydantic validation
  storage.py       SQLite transactions and uniqueness constraints
  service.py       Off-loop database execution and ordered snapshot/commit boundary
  broadcast.py     Bounded subscriber queues
  replay.py        Shared deterministic WebSocket producer
  config.py        Local environment configuration
backend/tests/     Focused API/storage/concurrency tests
scripts/           Combined launcher and CLI replay wrapper
```

`backend/uv.lock` and `frontend/package-lock.json` pin dependency resolution. TypeScript uses the current stable 6.0 line supported by the ESLint TypeScript integration; incompatible TypeScript 7 is deliberately excluded.

The one-process ordering lock serializes database operations in worker threads. This favors simple, consistent local behavior over throughput. History and deduplication records are retained indefinitely, snapshots contain the entire session, and the transcript is not virtualized. This step does not implement multi-user access, production deployment, a real provider, audio capture, or automatic transcription. Live sessions are marked stopped during graceful shutdown and any interrupted live sessions are stopped on the next startup; finalized and provisional transcript history is retained.

## Troubleshooting

- **Node/uv not found:** activate Node 22 (`nvm use`) and install uv, then open a fresh terminal. The launcher checks prerequisites.
- **Port already in use:** stop the earlier launcher or change both port variables in `.env`; restart the launcher. Vite uses a strict port rather than silently moving.
- **Disconnected UI:** verify `curl http://127.0.0.1:8000/health`, use the configured localhost frontend URL, and check backend logs. Reconnection is automatic. A 403/policy close generally indicates an unexpected Origin/Host.
- **Producer rejected:** verify the Authorization header matches `INGESTION_TOKEN`; create a fresh session if the previous one stopped.
- **History looks missing:** check `DATA_DIR`. The default is repository-relative even when launched from another directory.
- **Database errors:** check free disk space and write permissions; stop all other backend processes using this database. Retry unacknowledged events with the same event ID.
- **Reset local demo history:** use the app's Test mode reset. Never delete the separate transcript archive as MVP cleanup. See [retention and backup](transcript-archive.md).

## Prepared meetings and test tools
`POST /workspaces/{wid}/meetings` creates a draft with a nullable `session`.
Save the roster using `PUT /meetings/{mid}/participants` with its revision, then
`POST /meetings/{mid}/start` with `{revision, mode: "real" | "test"}`. Real mode requires named
interviewer and customer; test mode requires at least one named person and the Test mode preference.
The start response is meeting detail; identical concurrent starts return the same session.

`GET/PUT /settings/test-mode` reads/sets `{enabled: boolean}`. This local shared preference is not
authentication. Test mode does not bypass budgets or convert existing real sessions. Public legacy
`POST /sessions` is retired with HTTP 409. Replay, injected dialogue, reset and legacy Zoom proof
are backend-gated. Source family remains fixed for a session, so start a new meeting to change it.

## Optional OpenAI analysis
Set `OPENAI_API_KEY` in the server `.env` and restart. `OPENAI_MODEL` defaults to `gpt-5.6-terra`.
Choose the model in bottom-left **Analysis settings → Analysis model**. Gemini remains selected
until changed; `ANALYSIS_PROVIDER` is only the initial choice when no persisted selection exists.
OpenAI API billing is separate from the application. No calls occur just by selecting a model.
