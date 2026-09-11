# Stage 1 — Explore

Connected browser UI with workspaces, meetings, replay/injection, persistent question history,
source-linked findings, versioned briefs and notes, and scoped test reset. Dark theme.

Synthetic two-person interview tests the same ingestion boundary as external transcript producers.
Default analysis is simulated; Gemini can be enabled through backend configuration.
Questions use queued/asked/answered states controlled by the interviewer. Live semantic answer
detection and cross-meeting context agents are future work.

Data is local SQLite with transactional migration, revision checks and immutable evidence history.
Reset retains meeting brief/notes and replaces its run ID. Workspace clear affects only its meetings.

See [data model](../docs/data-model.md) and [design decisions](../design/architecture.md).
