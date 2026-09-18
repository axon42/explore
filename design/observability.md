# Developer diagnostics

2026-09-14 · Implemented for the local MVP. Full team authentication remains planned.

## Access and content policy
Developer tools require a separate local owner key. The backend gates every trace, log and recording
endpoint; Test mode is not an admin permission. Startup creates `DATA_DIR/developer-admin.key` with
mode 600. Unlock uses constant-time digest comparison, at most five attempts per minute, and an opaque
HttpOnly/SameSite=Strict cookie expiring in one hour. Only cookie hashes stay in memory; restart revokes
them. Browser mutations require an allowed Origin. Developer responses are `no-store`; existing
loopback host/origin checks remain. An unavailable/insecure key fails closed for developer access.

This authenticates the local machine owner, not a team administrator. Before hosting, replace
`LocalAdmin` with managed sign-in and membership checks, scope queries by account, use HTTPS cookies
and disable local-key bootstrap. No public binding is authorized by this work.

Ordinary logs exclude transcript bodies, headers, keys, arbitrary exception messages and raw model
output. The user's explicit request to inspect model exchanges permits **opt-in admin diagnostic
records** containing request/response bodies. Recording defaults off, expires after 15 minutes,
stops on Lock and is not restored on restart. Configured keys and bearer tokens are redacted;
this is not anonymization of interview content. Automated tests use synthetic data only.

## Recorded data and boundaries
- Each actual analysis attempt has a random request ID, separate from the stable job ID used for
  deduplication. The existing analysis run stores that ID and a safe failure code.
- Metadata includes model, session/job, input size/count, elapsed time, configured deadline,
  HTTP status, timeout stage, finish reason, validation categories and returned token usage.
  Outcomes distinguish running, successful, rejected, stale, cancelled and interrupted attempts.
- The Gemini adapter observes its exact JSON payload and HTTP response before parsing, excluding
  headers. Simulated analysis records context/proposal instead. A running trace may show context
  until the attempt completes. A timeout may have no response body or known usage.
- A context-local observer keeps provider code independent of persistence. The coordinator owns
  lifecycle; storage uses the existing serialized boundary. Diagnostic write failures cannot fail
  a successful analysis commit. Cleared generations or deleted sessions reject late completions.
- The event tail includes lifecycle, HTTP failure IDs and analysis completion/rejection metadata.
  It does not include every SDK/Uvicorn log. HTTP IDs and model IDs are distinct; session/job IDs
  connect model traces to analysis events. Full distributed tracing and support export are deferred.

## Retention and UI
Migration 10 adds `developer_traces` to the working database, cascading with its session. Retain at
most 100 attempts for 24 hours; prune on reads/writes, startup and once per minute while running.
Each body is capped at 131,072 characters with a truncation indicator. This is plain local SQLite
text behind admin API access, not encrypted storage. Removal is logical deletion, not forensic erasure.

Allowlisted events use a 500-entry memory ring (200 displayed), a private 512 KB rotating file and
two backups. Clear diagnostic history stops recording and clears only these records/files. Meetings,
reports, budgets and the permanent transcript archive are unaffected. Working-storage backups may
include opt-in diagnostics; the permanent archive contains no diagnostic traces.

The existing UI tokens style a searchable request list, outcome filter and plaintext body viewer.
React escapes model text; no model HTML or Markdown runs. Lock/expiry remove cached bodies from the
view. Clear uses the existing keyboard-accessible confirmation dialog.

## Timeout handling and verification
Distinguish connect/read/write/pool timeouts, HTTP 504 and the coordinator's total deadline. After
a timeout, halve subsequent new-text and fragment budgets, up to an eightfold reduction for that
session. Preserve whole source segments, pending coverage, meeting context and existing call caps.
This mitigates input-related delays; it does not establish their cause. No extra automatic provider
retry, model switch or thinking change is added. See [analysis design](live-analysis.md).

Tests cover auth/origin/expiry, redaction, retention, migration, safe log rotation, clear/cancel races,
timeout stages and checkpoint safety, plus browser unlock, inspection, filtering, unsafe text and
responsive behavior. Older failures cannot be retrospectively reconstructed.

[Usage](../docs/developer-tools.md) · [Accounts](accounts-and-workspaces.md)


## Planned workspace/meeting diagnostics — 2026-09-15
Not implemented. See [reliability plan](analysis-reliability.md). Preserve the existing local admin
boundary until real membership authorization exists; Test mode never grants body/log access.

Navigation: Workspace → meeting (including archived) → session/run → job → attempts. Use scoped
backend filters and indexes, not client-side filtering of a global trace dump. Workspace/meeting IDs
are validated through ownership joins. Unknown/unscoped server events live in a separate Global
operations view, never attributed to the currently selected meeting by guesswork.

Meeting summary: captured/analyzed-through timestamps, pending final revisions, live capture status,
analysis state, remaining allowance and errors. Attempt list filters: provider, exact model, outcome,
error stage, time range and job. Auto-scope Developer when opened from a meeting; preserve explicit
selection and display breadcrumbs. Paginate and bound responses.

Attempt detail tabs:
- **Input:** exact serialized provider payload, system instructions, context sections, source ranges,
  model parameters, prompt/schema version and body completeness. Mark simulated context separately.
- **Response:** raw escaped response, finish reason, provider ID and usage; separate parsed proposal,
  validation/rejection explanation and committed changes. A timeout means response unavailable,
  not an empty successful response. Never reconstruct missing historical payloads as exact requests.
- **Timeline:** queued, leased, sent, received, validated, committed/ACK or retry/blocked; session,
  job and unique attempt IDs correlate logs. No headers, API secrets or executable model content.
- **Coverage/routing:** which revisions were supplied/accepted, current topic index, routing action,
  why a suggestion was withheld, and what remains pending. Link exact evidence privately.

Retain existing opt-in body recording, expiry, redaction and admin lock. Do not automatically record
full requests because Test mode is on. Plan metadata retention per meeting with a global storage
ceiling and fair per-meeting bounds; show the retained date range and explicit expiry/truncation.
A busy session must not silently erase the only available diagnostic trail of another meeting.
Bodies retain a separately bounded shorter policy; final duration/byte defaults require a decision.
Diagnostic deletion remains separate from protected transcript retention. General application logs
remain metadata-only; any future support export needs preview/redaction and explicit user action.

### Test-mode provider strip — planned
Always visible in the selected meeting while Test mode is enabled, including idle, stopped, error
and unconfigured states. Compact summaries expand into details; admin request bodies stay in
Developer. Show meeting/session attribution and last-updated/stale state; modest bounded polling.

| Provider/stage | Metrics |
| --- | --- |
| Deepgram | Exact model; microphone/system connection health and separate audio seconds sent; latest result age; interim/final counts; gaps/reconnects; local ingest lag; available confidence and unmapped voice counts |
| Gemini | Exact model; queued/in-flight/blocked jobs; oldest backlog age; captured versus analyzed watermark; attempt/success/error/retry counts; last and p50/p95 latency with sample count; returned input/output tokens; remaining call/budget allowance |
| Cost | Provider-reported usage where returned; otherwise explicitly labeled estimates from audio seconds/tokens and versioned rates; unknown timeout usage and provider-credit balance shown as unavailable unless actually queried |

Audio seconds summed across separate streams are not meeting duration; transmitted seconds are not
proof of billed seconds. Confidence is not an accuracy score. End-to-end latency needs synchronized
or comparable clocks; label local stage measurements precisely. Recent stored counters are not a
live provider dashboard. This strip adds no automatic model requests or account-balance polling.

Acceptance: switching workspaces/meetings cannot show another scope's counters or bodies; empty,
archived, reconnecting, stale, capped, timed-out and provider-unconfigured states are covered; Test
mode visibility does not weaken backend permissions; raw metrics contain no transcript content.

## Analysis-mode diagnostics
[Manual analysis](context-rebuild.md) traces now include scheduling, scope and source watermark.
Existing usage/timing and admin-only redacted payload previews remain; their 128 KiB body cap still
applies. Complete per-workspace drilldown, applied-change summaries and Test-mode metrics are planned.

Contract failures now include safe schema-field paths and count/length bounds, without rejected values
or unknown object keys. `provider_output_limit` distinguishes oversized arrays/strings from invalid
structure. Older traces containing only `too_long` cannot identify the field retroactively.

Analysis traces also record `question_decision` and accepted/rejected spoken-question counts, without
quote bodies. HTTP 503 is reported as temporary provider unavailability; it is not a credential or
schema diagnosis. Manual failures preserve coverage and require explicit retry.

Missing body previews mean contents were not retained, not that an empty request was sent.
Use request/response byte counts and HTTP status to distinguish transport from recording.
The Developer panel now explains this without speculating about a timeout after a 200 response.
