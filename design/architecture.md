# Explore — design decisions

Next work is sequenced in the [roadmap](../docs/roadmap.md): capture reliability, prepared
interviews/Test mode, then profiles and invitation-only teams. Capture diagnostics and prepared
interviews are implemented; profiles/invitations remain planned. See linked designs for acceptance checks.

[Speaker separation and confirmed attribution](speaker-attribution.md) is implemented locally.
Source labels, detected voices and confirmed people/roles remain distinct. SQLite migration 7,
provider observations, the resolver and confirmation UI are separate modules; real capture quality
and permission recovery still need a Firefox rehearsal.

## Structure
- [Durable transcript archive](transcript-retention.md): a separate append-only SQLite database
  survives working reset/permanent deletion. Transcript and archive writes commit atomically using rollback journals.
- Workspace → meetings → transcript sessions. A meeting retains identity and context when its test run is reset.
- SQLite repositories own transactions; API routes coordinate lifecycle; the analysis provider implements a small `Analyzer` interface. Future agent logic can reuse the same persisted sources.
- Briefs, notes and transcript revisions remain separate from derived questions/findings. Exact evidence links and immutable analysis input/output provide provenance.
- Optimistic revisions prevent silent overwrites from another tab. Reset stops work before transactional deletion; a fresh session ID rejects old producer traffic.

## Interface
- Implemented [manual full-transcript analysis](context-rebuild.md) is the MVP default for 45-minute meetings; Automatic incremental mode remains opt-in. Scheduling and reasoning strategies stay separate.
- [Shared dropdowns](dropdowns.md) standardize selection fields without changing API/data contracts.
- [Sidebar organization](sidebar.md) implements the approved 272 px rail, grouped navigation,
  workspace actions and compact tools; existing API and permission contracts are preserved.
- Immediate live source: [macOS microphone + system audio](macos-audio-capture.md), with a
  replaceable source/provider boundary feeding the existing transcript pipeline.
- Target live-call experience: [Zoom desktop + Explore](zoom-meetings.md). Regular Meetings RTMS
  eligibility must be verified before replacing the existing Video SDK proof.
- Light theme with conventional sidebar, meeting tabs, forms and confirmation dialogs. The app is **Explore**. See [UI decisions](ui.md).
- Interview: transcript, retained questions, status controls, replay and injection.
- Overview: source-linked workflows (blue), gaps (amber), automation hypotheses (purple). Labels accompany color.
- Brief and Notes: persistent meeting context. Asked/answered status is manual for now; questions link to the evidence behind the suggestion.
- Removed static sample workspaces, preview labels, decorative copy and the old single-session interface. Empty states now reflect actual data.
- Sequential 800 ms polling keeps the initial integration simple; existing WebSockets remain available. Selection stays in the browser; meeting data stays in SQLite.

## Deferred
Cross-meeting agents/context brain, embeddings, automatic answer detection, auth/remote access and audio integrations. Gemini passed a real synthetic integration check. Default repository configuration remains mock; the local ignored `.env` enables Gemini.

[Data model](../docs/data-model.md) · [Pipeline](../docs/pipeline.md)

## Analysis and reports
Explicit meeting end runs a full-transcript review independently of live-analysis success. Past
ended meetings can retry from Report; valid results create immutable report revisions. Shared
provider limits remain enforced. See [final review](meeting-reports.md#final-review--implemented-2026-09-16).

[Live analysis](live-analysis.md) now has replaceable batching, context, reasoning, validation and
formatting components with durable meeting memory. The [report design](meeting-reports.md) is
implemented through backend APIs for participant mappings, full transcript exports, shared generated
note sections, immutable final reports and evidence-backed Mermaid source. The browser now exposes participant editing, generated notes, finalization and report/transcript
downloads. Further real Gemini quality evaluation remains separate work.

[Implementation/API reference](../docs/analysis.md) · [Coding agent rules](../AGENTS.md)

## Follow-up after Gemini connection verification
[Developer diagnostics](observability.md) now provides local-owner authentication, bounded opt-in
model bodies, safe structured logs and timeout stages. Full account RBAC and tracing remain planned.
See the proposed [interview-ready release plan](interview-ready-release.md) for light UI, report downloads,
microphone testing, private hosting and Zoom ingestion. The light theme is implemented; the remaining release work is planned.

- Group overview gaps and automation hypotheses under their related workflows, with explicit
  relationships in the analysis data instead of relying on adjacent cards or color alone.

## Meeting organization and pacing
Meeting archiving is reversible organization, not deletion or capture control: stop the
meeting before archiving. The sidebar shows active meetings; a dedicated Archives view searches, filters, restores and deletes archived working records. Workspaces can also be archived. Question
frequency and discard controls are per meeting and preserve the evidence ledger. See
[live pacing](live-analysis.md#live-pacing-refinement--2026-09-12).

## Topic memory (opt-in)
[Topic memory](topic-memory.md) extends session-local analysis with resumable subjects and
evidence-backed associations using the existing provider workflow and SQLite. This is a
runtime option selected through the bottom-left Analysis mode control, with migration 4
for topic data and migration 5 for the app-wide preference.
The default remains `legacy` until real-provider evaluation. The browser now exposes thread
context and formatted report revisions; no agent framework was added. See [UI decisions](ui.md).

## Prepared session boundary (2026-09-12)
- New meetings are drafts (`session: null`) until explicit start. `Lifecycle` owns roster validation,
  mode and transcript-source claims in SQLite transactions. Start stores an immutable roster snapshot;
  editable participant records remain available for corrections and reports.
- Backend Test mode gates replay/injection/reset/Zoom proof. Session mode is immutable and real
  interviews reject test tools even when the global switch is on. One source family per session
  prevents capture and synthetic playback being combined accidentally; choose a new meeting to change source.
- Sidebar search filters titles in the selected workspace/archive view; no index/service is needed
  for the current local meeting list. Tags and full-text research remain separate future work.
- Findings link to workflows by `(topic_id, workflow_key)`, checked against the bounded supplied
  context or the same response. Unknown links fail validation; absent links stay visibly unassigned.

See [archives and question history](archives-and-question-history.md) for migrations 8–9, reversible organization and evidence-backed spoken-question extraction.

[Provider/model selection](model-selection.md) adds a persisted local choice, frozen per request,
and an OpenAI Responses adapter alongside Gemini. Existing transcripts and analysis validation are shared.
