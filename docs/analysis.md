# Analysis and reports

The backend implements the [analysis design](../design/live-analysis.md) and
[report design](../design/meeting-reports.md) using the mock provider by default. Existing
Interview/Overview screens consume the resulting questions and accumulated overview. Participant
editing is available in Brief; Notes exposes structured AI notes; Report provides finalization,
job status, immutable revision downloads and full transcript exports. Local interactive API documentation is at `/docs` on
the backend (normally `http://127.0.0.1:8000/docs`).

## Manual analysis (default for new meetings)

Capture stores transcript continuously. **Analyze now** makes one full-finalized-transcript attempt;
failures require explicit retry. All human notes and question history are included. Existing meetings
retain Automatic scheduling. Switching modes does not dispatch a request.

`PATCH /sessions/{sid}/analysis-scheduling` accepts `{mode: "manual" | "automatic", revision}`.
`POST /sessions/{sid}/analyze` accepts a UUID `request_id` and returns a persistent receipt (202).
Reuse the ID after ambiguous network failure; use a new ID for an explicit failed-attempt retry.
`GET /sessions/{sid}/experiment` includes `scheduling`: mode/revision, last receipt, changed-input flag,
coverage, pending segments and remaining calls. Archived/current-session ownership checks apply.

Manual input is capped at 1 MB serialized UTF-8; no truncation. Output uses a full-review contract
and 16,384-token cap. Attempts count against the existing allowance and timeout. See
[full design](../design/context-rebuild.md) for schema bounds, validation and persistence semantics.

## Automatic processing

1. Save each accepted transcript revision. Interim text is displayed but not analyzed.
2. Replay/injection collection waits for one second without another notification, up to five
   seconds. Native audio uses four seconds / 25 seconds and a 35-word context threshold;
   finalization bypasses the threshold. A maximum-window flush updates memory without a question.
   One worker handles each session; notifications coalesce while it runs.
3. `ContextBuilder` selects up to 60 unprocessed final segments / 24,000 characters, plus up to
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
job. Both scheduling modes run one full-transcript final review, including accumulated AI memory,
before report assembly. Past ended meetings use **Run final review** in Report. An unchanged successful
final review is reused; failures require an explicit retry. Failed, timed-out, invalid or incomplete
live analysis does not prevent this new review: all saved final segments and the last accepted
analysis are included. Provider availability, credentials and separate live/manual and final-review call limits still apply. Replay **pause** does not end a
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
new frontend library is needed: the report reader renders validated step lists as native HTML and CSS, without executing Mermaid or model HTML.

## Limits and validation

`ANALYSIS_MAX_CALLS` limits live/manual analysis (default 100); `FINAL_REVIEW_MAX_CALLS`
separately limits final review (default 2, configurable 0–10). Failed/cancelled
attempts count; exhausting it can leave a report explicitly failed. Set a suitable per-session limit
before longer experiments. There is no automatic provider fallback, paid smoke test, semantic quality
claim, cost estimate, cross-meeting retrieval, automatic status change or new public-access capability.
See [pipeline configuration](pipeline.md#gemini) for connecting Gemini later.

Regression coverage includes untruncated batching, source correction, compatible in-flight updates,
manual status precedence, invalid references, transaction rollback, job idempotence, participant
revisions, full exports, report retries, reset races, restart persistence and workspace ownership.

Gemini response failures distinguish token-limit truncation, blocked/empty responses, malformed
JSON and local contract violations. Safe messages exclude response text and arbitrary field names.
Wire-schema descriptions carry local size limits; the compact-output prompt requests only changed
memory entries. Strict local validation and the 4,096-token output ceiling remain unchanged, with
no automatic retries. After deploying an adapter change, restart the backend. A live session retries
unprocessed evidence when another turn arrives; a stopped session retries via Generate report.
Refreshing the UI only reloads state and does not retry analysis.

## Topic memory (opt-in)
Choose **Discussion threads** in **Analysis mode** at the bottom left. Choose **Standard**
to return to legacy analysis. The setting applies across the local app, persists in SQLite and
takes effect on subsequent batches without a restart. Use a fresh synthetic meeting for
evaluation; switching does not delete topics or original evidence. Provider selection remains independent:
`ANALYSIS_PROVIDER=mock` makes no external calls; `gemini` uses the existing server-side key.
Switching strategy never automatically rebuilds historical meetings.

Topic mode adds routing, readiness, scoped artifact keys and exact-intent dedupe to the same
provider call. The checkpoint includes `topic_state`; `GET /meetings/{mid}/analysis` returns
`topics` and notes with `topic_groups`. The Interview tab polls this endpoint every 2.5 seconds while mounted and displays a session-filtered thread panel beneath the transcript. Active focus follows updates unless the viewer selects a thread; source links require exact current revisions.
Reports containing topics use version 2, preserve section order, and include active and paused
subjects. Full transcript exports still retain every accepted revision.

The context index is capped at 40 topics, details at three, added exact evidence at 8K characters,
and the shared serialized context at 64K characters (with metadata reserve). Derived memory and
older notes may be omitted with counts; new segments are never truncated. Context that still
exceeds the cap fails before a provider call. Index-only resumes wait for a later eligible batch
with hydrated detail before questions can be published. Topics with more than 30 associated
questions suppress new questions until a future history-retrieval policy is implemented.

Opening fragments wait for 35 words; processed sessions accept short corrections. All sources
use four-second quiet / 25-second maximum batching in topic mode; maximum flushes update memory
only. Model readiness and cooldown checks govern publication. Automatic also suppresses questions
on pending speech; Manual retains the explicit snapshot suggestion with a newer-speech notice.

Run the offline comparison from `backend`: `.venv/bin/python -m app.topic_eval`.
It uses temporary storage, no keys, and no provider network calls. See the
[evaluation baseline](topic-memory-evaluation.md) and [design](../design/topic-memory.md).
A separately budgeted, synthetic Gemini evaluation remains necessary before interview rollout.


## Analysis-mode setting
`GET /settings/analysis` returns `{strategy, revision}`. `PATCH /settings/analysis` accepts
`strategy: legacy | topics` and the current integer revision; stale writes return 409.
The sidebar polls every three seconds, rejects older GET responses and displays save failures.
This is an app-wide preference, independent of workspace/meeting selection, provider keys,
call caps and data reset. Local host/origin protections apply to both endpoints.

Each analysis invocation captures its mode and preference revision before calling the provider,
then validates and commits under that same contract. An in-flight batch finishes normally;
changing the mode neither starts another call nor rebuilds history. A collection window already
waiting may finish under its previous timing policy; the next invocation uses the saved mode.
`ANALYSIS_STRATEGY` is only an initial fallback before the first UI save. Once saved, the database
choice takes precedence across server restarts. Analysis inputs record both mode and revision.


Validation errors carry a safe diagnostic code, also saved as `validation_code` on the run.
Examples include `topic_focus_changed`, `topic_routing_evidence`, and `question_intent_missing`.
The transcript checkpoint never advances on rejection. First-topic `continue` is canonicalized
only for an accepted new focus in an empty topic index; evidence validation remains strict.
Failed analysis leaves coverage pending. In **Manual**, click **Retry analysis** explicitly;
new dialogue and report generation never trigger a model call. In **Automatic**, new dialogue
can retry pending analysis and **Report → Generate report** drains remaining analysis for a
stopped meeting within the call cap.

## Provider selection
`GET /settings/model` returns the selected provider/model/revision and configured model options.
`PATCH /settings/model` accepts `{provider, model, revision}`; conflicts return 409 and unknown or
unconfigured choices return 422. Selection makes no provider call. Running requests keep their
original model; Manual can explicitly review unchanged text after a selection change.
See [provider design](../design/model-selection.md).

To compare models, open **Analysis mode → Analysis model** at the bottom left, choose a
configured model, then click **Analyze now** in a Manual meeting. The selection applies to
future requests across all meetings. Switching alone is free; analysis uses the selected API.
See [Manual review](../design/context-rebuild.md) for the latest opportunity-certainty correction.

Opportunity certainty is normalized consistently for finding cards and structured claims: both
remain inferred hypotheses. Evidence and confirmed-attribution checks still run; malformed or
unsupported proposals are not accepted. This applies to both providers and final/live review.

Workflow connection counts that do not match adjacent step pairs are normalized to unknown order
for every connection, after validating all supplied step/connection evidence. Supported steps remain;
no positional alignment is guessed. Unknown references still reject the whole proposal.

## Manual follow-up behavior — 2026-09-17
Manual live review explicitly asks for one useful grounded follow-up and a full discussion/workflow
review. Its provider instructions are separate from final review's no-live-question instructions.
A developing topic can support a manual follow-up when routing, source evidence and question intent
are valid; uncertain routing/readiness, repeated intents, disabled questions and cooldown still block.
Automatic analysis retains the ready-only pacing gate. No question is fabricated when the model
returns none; diagnostics preserve model_empty instead of mislabeling it as topic_not_ready.
Thread focus changes do not delete other topics. Manual input includes all topic summaries and
accumulated workflows; updates omit unchanged artifacts and preserve them. The UI detail pane follows
the active topic unless pinned; earlier threads remain available in the thread picker.
Synthetic regressions cover consecutive reviews and retained topic/workflow identity. Real-provider
question quality remains an evaluation task; no extra model request or hidden retry is introduced.

Manual full-transcript questions may cite any validated supplied segment, including passages absent
from the topic summary's small citation set. Automatic batches retain topic-context overlap checks.
Routing, topic history, intent deduplication, cooldown and source ownership checks still apply.
Diagnostics distinguish readiness, missing history, citation-scope and duplicate-intent suppression.
