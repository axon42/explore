# Stage 1 — Explore

Connected browser UI with workspaces, meetings, replay/injection, persistent question history,
source-linked findings, versioned briefs and notes, and scoped test reset. Dark theme.

Synthetic two-person interview tests the same ingestion boundary as external transcript producers.
Default analysis is simulated; Gemini can be enabled through backend configuration.
Questions use queued/asked/answered states controlled by the interviewer. Automatic status changes and cross-meeting context agents are future work.

Data is local SQLite with transactional migration, revision checks and immutable evidence history.
Reset retains meeting brief/notes and replaces its run ID. Workspace clear affects only its meetings.

See [data model](../docs/data-model.md) and [design decisions](../design/architecture.md).

## Analysis and reporting backend
Modular batching and persistent structured memory support specific, evidence-backed follow-ups.
Question-progress matches are proposals; status remains human-controlled. Finalization drains
accepted final dialogue before generating a versioned report. API exports preserve full transcript
revisions; generated notes and reports share a structure beginning with participant roles. Supported
workflows export editable Mermaid diagrams. Repository default remains mock; the real Gemini synthetic integration check passed and local configuration can enable Gemini.

See [analysis APIs](../docs/analysis.md), [analysis design](../design/live-analysis.md) and
[report design](../design/meeting-reports.md). Dedicated report/participant/export UI controls,
structured human-note editing and real-model evaluation remain separate work.
