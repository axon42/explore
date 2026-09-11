# Analysis and reports

The backend implements the [analysis design](../design/live-analysis.md) and
[report design](../design/meeting-reports.md) using the mock provider by default. Existing
Interview/Overview screens consume the resulting questions and accumulated overview. Participant
editing, structured AI notes, exports and final reports are available through the API; dedicated
UI controls are not added in this change. Local interactive API documentation is at `/docs` on
the backend (normally `http://127.0.0.1:8000/docs`).

## Processing

1. Save each accepted transcript revision. Interim text is displayed but not analyzed.
2. `TriggerPolicy` waits for one second without another notification, up to five seconds per
   collection window. One worker handles each session; notifications coalesce while it runs.
3. `ContextBuilder` selects up to 12 unprocessed final segments / 24,000 characters, plus up to
   4,000 characters of previously processed dialogue (at most ten segments). A single unprocessed
   segment is never truncated. Corrections invalidate dependent memory before context construction.
4. Send brief, latest ten human notes, latest thirty questions, participant mappings and up to forty
   entries each of claims/matches/workflows, alongside new/recent dialogue. These are bounded model
   inputs; complete source and derived history stay in SQLite.
5. `AnalysisStrategy` delegates to the existing `Analyzer` provider. Structured proposals contain
   specific follow-ups, claims, possible question-status matches and workflow steps/transitions.
6. Validate source and question ownership; reduce accepted state and commit it with the analysis
   run and artifacts. Stable job IDs prevent reapplying an accepted job. Failed attempts remain
   auditable and do not advance coverage. New speech can coexist with a completed batch; defer its
   question if unprocessed speech remains. Corrections to supplied evidence or human-context changes
   invalidate the result and schedule fresh context.
7. `OverviewStrategy` cheaply formats accepted claims after each successful batch. It makes no
   extra provider call. `GET /meetings/{mid}/analysis` returns current reconciled memory and the same
   section structure used in reports. Human notes and question statuses are never automatically changed.

`analysis_state.coverage` maps segment IDs to accepted processed revisions. `cursor` is a session
version watermark advanced only when every current final segment is covered; it is not a count of
processed segments. The last model input version and source revisions are separately recorded in
`analysis_runs`. Old revisions and run history remain available after a correction.

The mock quotes customer statements and uses a small explicit fixture pattern for workflow diagrams.
It demonstrates delivery, storage and rendering contracts, not semantic reasoning quality. Gemini
uses the same output schema and is not contacted in mock mode. Evidence-ID validation cannot prove
that a model's interpretation of a passage is correct; evaluate grounding with real model outputs
before relying on automatic analysis.

## Finalization and revisions

Stopping a session closes ingestion, cancels the live/replay worker, then starts a background report
job that drains unprocessed finals through the same batch strategy. Replay **pause** does not end a
meeting. Reset/clear use cancellation without starting report generation. Report jobs use
pending/generating/complete/failed states; failures are explicit and retries are user-initiated.

Reports require full final-segment coverage and the current human-context version. Report formatting
is deterministic over accepted structured evidence, with no additional model call. It includes all
current transcript evidence, human notes and question history; provisional text is retained and
counted separately. Unknown roles/fields are not invented. A report covers received transcript only.

A report is immutable and unique for its session/source/context versions. Regeneration after a brief,
note, participant or question-status change creates a new revision. Reports list an `outdated` flag.
The ingestion API does not reopen stopped sessions; post-stop transcript editing is not added here.
Interrupted report jobs become failed at startup and can be retried. Reset removes reports/run data,
retains the meeting brief, human notes and participant mappings, and creates a new session ID.

## API

Use `/api` before these paths through Vite. Direct backend requests omit `/api`.

| Method / path | Contract |
| --- | --- |
| `GET /meetings/{mid}/analysis` | Reconciled state and ten structured AI-note sections |
| `GET /meetings/{mid}/participants` | `{revision, participants}` |
| `PUT /meetings/{mid}/participants` | Replace mappings with `{revision, participants}`; stale revisions return 409 |
| `GET /meetings/{mid}/transcript/export?format=json` | Full current transcript, accepted revision history, context and participant mappings |
| `GET /meetings/{mid}/transcript/export?format=markdown` | Readable transcript plus accepted revision history |
| `POST /meetings/{mid}/finalize` | `{session_id}`; closes ingestion and starts/retries report job; returns 202 |
| `GET /meetings/{mid}/reports` | Job state and report revisions/outdated indicators |
| `GET /meetings/{mid}/reports/{rid}?format=json` | Immutable structured report owned by this meeting |
| `GET /meetings/{mid}/reports/{rid}?format=markdown` | Readable report with evidence anchors and editable Mermaid |
| `POST /sessions/{sid}/stop` | Existing endpoint; now also schedules finalization |

Participant shape: `{speaker_id, name, interview_role, job_role}`. `interview_role` is interviewer,
customer, observer or unknown. Speaker IDs must be unique within a mapping (up to 30 participants).
These are explicit human mappings, not inferred identities. Absent mappings use transcript speaker
labels and unknown roles. Existing human-note records retain their original bodies and revisions.

Exports escape untrusted Markdown/HTML. Workflow data has bounded, evidence-linked nodes/transitions;
Mermaid is generated with fixed node IDs and encoded labels. Unknown ordering uses a labeled dashed
edge. Markdown includes textual steps for readers without Mermaid support. No diagram renderer or
new frontend library has been installed; a future UI renderer must use strict security settings.

## Limits and validation

The existing `ANALYSIS_MAX_CALLS` limit is shared by live analysis and finalization. Failed/cancelled
attempts count; exhausting it can leave a report explicitly failed. Set a suitable per-session limit
before longer experiments. There is no automatic provider fallback, paid smoke test, semantic quality
claim, cost estimate, cross-meeting retrieval, automatic status change or new public-access capability.
See [pipeline configuration](pipeline.md#gemini) for connecting Gemini later.

Regression coverage includes untruncated batching, source correction, compatible in-flight updates,
manual status precedence, invalid references, transaction rollback, job idempotence, participant
revisions, full exports, report retries, reset races, restart persistence and workspace ownership.
