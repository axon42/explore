# Stage 1 — Explore

Connected browser UI with workspaces, meetings, replay/injection, persistent question history,
source-linked findings, versioned briefs and notes, and scoped test reset. Light theme.

Synthetic two-person interview tests the same ingestion boundary as external transcript producers.
Default analysis is simulated; Gemini can be enabled through backend configuration.
Questions use queued/asked/answered states controlled by the interviewer. Automatic status changes and cross-meeting context agents are future work.

Data is local SQLite with transactional migration, revision checks and immutable evidence history.
Reset retains meeting brief/notes and replaces its run ID. Workspace clear archives only its meetings. Dedicated Archives supports search/filter, restore and confirmed permanent working deletion; the protected transcript archive is retained. Workspaces can be archived and restored.

See [data model](../docs/data-model.md) and [design decisions](../design/architecture.md).

## Analysis and reporting backend
Modular batching and persistent structured memory support specific, evidence-backed follow-ups.
Question-progress matches are proposals; status remains human-controlled. Finalization drains
accepted final dialogue before generating a versioned report. API exports preserve full transcript
revisions; generated notes and reports share a structure beginning with participant roles. Supported
workflows export editable Mermaid diagrams. Repository default remains mock; the real Gemini synthetic integration check passed and local configuration can enable Gemini.

See [analysis APIs](../docs/analysis.md), [analysis design](../design/live-analysis.md) and
[report design](../design/meeting-reports.md). Report/participant/export controls and generated-note viewing are connected in the browser.
Structured human-note editing and further real-model evaluation remain separate work.

Optional [topic memory](../design/topic-memory.md) now supports session-local topic routing,
evidence associations, question readiness and report groupings. It is selectable from the bottom-left Analysis mode control and remains opt-in pending Gemini semantic evaluation. The browser displays evolving discussion
threads below the transcript and saved report revisions with grouped notes, question-status charts
and evidence-linked workflow diagrams. [Market scans](../design/market-scan.md) are future work.

Detected questions actually spoken are retained separately from suggestions, with exact transcript references and confirmed roles where available. They appear in the meeting and new reports; suggestion status stays manual. See [design](../design/archives-and-question-history.md).
