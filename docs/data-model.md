# Explore data model

SQLite, one backend process, foreign keys enabled on every connection. Repository operations run off the event loop under the service ordering lock. UUIDs identify records; UTC timestamps record changes. Human-editable resources use integer revisions and reject stale writes with HTTP 409.

## Ownership

```mermaid
erDiagram
  workspaces ||--o{ meetings : contains
  meetings ||--o{ sessions : runs
  meetings ||--o{ meeting_briefs : versions
  meetings ||--o{ notes : contains
  notes ||--o{ note_revisions : versions
  sessions ||--o{ segment_revisions : evidence
  sessions ||--o{ analysis_runs : analyzes
  analysis_runs ||--o{ questions : proposes
  analysis_runs ||--o{ findings : produces
  questions ||--o{ question_evidence : cites
  findings ||--o{ finding_evidence : cites
```

- **Workspace:** a research initiative or customer segment. Meetings belong to exactly one workspace.
- **Meeting:** stable identity, title and context version. Context version changes when brief, notes or question statuses change.
- **Session:** a transcript/replay run within a meeting. A reset replaces its ID, so old producers cannot write into the fresh run. The current implementation maintains one run per meeting; reset is destructive rather than an archive operation.
- **Brief:** versioned JSON with validated fields for customer, vertical, objective, background, hypotheses and guidance. JSON allows the context envelope to evolve without coupling provider code to every field.
- **Notes:** independently addressable text records with edit revisions and timestamps. Older text is retained in `note_revisions`. Notes survive a test reset.
- **Transcript:** `segments` holds current text; `segment_revisions` retains each accepted revision. Deduplication uses `seen_events`. A speaker ID is scoped to a session, not assumed to be a global person.
- **Analysis runs:** immutable request context, input transcript/context versions, provider/model/prompt identity, output, token usage, timing, stale/error indicators. The existing experiments JSON stores replay/runtime state; it is not the source of truth for questions or notes.
- **Questions:** retained, deduplicated by normalized text within a session; queued/asked/answered with optimistic revisions and status history. Status is explicitly set by a human in this iteration; no automatic answer detection is claimed.
- **Findings:** workflow/gap/opportunity with observed/inferred basis. Each successful analysis supplies a new overview; prior runs and findings remain queryable. Automation possibilities must be inferred hypotheses.
- **Evidence:** relational links to exact `(session_id, segment_id, revision)` records. Foreign keys prevent references to another run. Corrected evidence remains inspectable and is marked superseded. Question evidence currently records the basis for asking; a manual answered status does not assert a separately verified answer span.

## Consistency and reset

No provider call holds the database lock. A completed call is discarded if one of its supplied source revisions or the human meeting context changed. Compatible newly appended dialogue remains pending while accepted state commits. Invalid evidence IDs are rejected. The analysis result and its question/finding/evidence records commit together.

Meeting reset requires the expected session ID. It stops ingestion on that run, cancels and awaits replay/analysis work, then transactionally deletes run data and creates a fresh session. A repeated reset using the old ID returns 409. Workspace clearing coordinates the same shutdown and removes only that workspace's meetings, briefs, notes and run data. The workspace remains. Database work is awaited even when its calling coroutine is cancelled, so locks cannot release before a worker thread finishes writing.

## Migration

`schema_migrations` records forward-only schema versions. Migration 1 adds the discovery entities, assigns existing sessions to **My workspace**, preserves transcript IDs/text and saved objectives, and backfills the available transcript revision. Revisions discarded by older code cannot be reconstructed. Existing legacy experiment JSON is retained; historical suggestions in that JSON are not promoted to new question rows.

Before migrating a legacy database, `Storage.initialize` makes a consistent SQLite backup at `meetings.before-discovery.sqlite3`. Schema changes and backfill are transactional and idempotent. Startup marks interrupted live sessions stopped. The automatic migration backup is not updated by reset/delete actions.

## API

- `GET/POST /workspaces`; `GET/POST /workspaces/{id}/meetings`
- `GET /meetings/{id}` returns current run, brief, questions, overview, findings and notes.
- `PUT /meetings/{id}/brief` accepts `{revision, brief}`.
- `POST /meetings/{id}/notes`; `PUT /meetings/{id}/notes/{noteId}` accepts `{body, revision}`.
- `PATCH /meetings/{id}/questions/{questionId}` accepts `{revision, status}`.
- `POST /meetings/{id}/reset` accepts `{session_id}`.
- `DELETE /workspaces/{id}/meetings` clears that workspace's meetings.
- Existing `/sessions/{id}` replay, injection and WebSocket endpoints remain available.

The browser polls meeting state every 800 ms, cancelling obsolete loads. Selection IDs alone are remembered in localStorage; content lives in SQLite. This adds up to one polling interval plus request time to display latency. The WebSocket contract remains available for faster future UI transport.

## Analysis/report migration 2

- `analysis_state`: current structured claims, question-match proposals, workflows, processed revision coverage and overview, keyed by session. Updated atomically with accepted analysis runs; immutable run input/output retains prior state/proposal provenance.
- `meeting_participants`: human participant/speaker mappings with optimistic revision checks. Roles remain unknown unless supplied. Context version advances when edited; existing reports preserve their earlier participant snapshot.
- `report_jobs`: durable finalization status/error, keyed by session. Interrupted jobs become failed on startup.
- `reports`: immutable structured reports, unique by session/source/context version and numbered within the session. Includes exact evidence, note snapshots and generation provenance.

Session-owned additions cascade on run deletion; participant mappings survive reset and cascade only
with meeting deletion. Migration is transactional and idempotent; upgrading a version-1 database first saves a consistent
`meetings.before-analysis.sqlite3` backup. Existing historical runs are not
silently converted to new structured memory: finalization processes retained current finals as needed.
See [analysis and report APIs](analysis.md) for coverage, exports and finalization semantics.

## Future context brain

Build retrieval over meeting briefs, note revisions and transcript evidence. Store derived claims with their run provenance and exact citations; do not overwrite original observations with agent summaries. Cross-meeting retrieval, embeddings, authors/permissions, automatic answer-span detection, pagination and retention policies are not implemented here. This remains a single-host MVP, not a multi-tenant hosted service.

## Meeting controls (migration 3)
`meetings.archived` is a checked boolean, and `question_interval` is one of 0/30/60/120
seconds (default 60). `PATCH /meetings/{id}/preferences` requires the current
`context_version` as `revision`; updates increment it and invalidate stale analysis.
Archiving requires a stopped session, preserves all content and is reversible. Restore a
meeting before resetting its test. Workspace clear retains its explicit all-meetings scope.

`questions.discarded` preserves the previous stored status while the API projects
`status=discarded` in question lists, context and exports. Discard/restore use the existing
revision-checked question endpoint and append status events. Original evidence remains intact.
The migration adds columns transactionally, backfills defaults, and preserves existing keys.

## Topic memory (migration 4)
- `topics`: session-owned stable IDs, title/summary with exact summary source revisions,
  optimistic projection revision and latest owning analysis run. Active/paused status derives
  from `analysis_state.topic_state.focus_id`; old runs preserve proposal provenance.
- `topic_evidence`: many-to-many topic/source revision links, with accepted/provisional assignment.
- `topic_artifacts`: current claim/workflow key associations, rebuilt with accepted memory.
  JSON artifact references are validated in application code; topic ownership has composite FKs.
- `question_topics`: question/topic/session link and normalized intent, unique within that
  session/topic. Discard/restore preserves it, preventing exact-intent reissues.

Migration 4 leaves existing sessions/topics unassigned and makes no provider calls. Run reset
removes topic rows before dependent transcript/run records; archive retains them. Foreign keys
and transaction rollback protect cross-session evidence and atomic state/run/topic writes.
Current summaries whose sources were corrected are withheld until refreshed; old versions remain
in analysis runs. The [topic design](../design/topic-memory.md#storage-and-contracts) records the
boundaries and limitations. Existing human content and transcript revision retention are unchanged.


## Analysis preference (migration 5)
`analysis_preferences` contains at most one local-app row: `id=1`, checked `strategy`
(`legacy` or `topics`) and a positive optimistic `revision`. It deliberately has no session or
workspace foreign key: the bottom-left control affects new batches throughout this local app.
Creation/update is transactional; concurrent stale writes fail instead of overwriting. Before
the first save, the server's initial mode is returned with revision 0. After a save, database
state takes precedence. Meeting reset/archive and workspace clear preserve the preference.
The migration changes no existing interview records and triggers no provider work.
