# Archives and spoken-question history

Implemented locally · 2026-09-14. Scope: reversible organization and retrospective question review.

## Organization
- **Workspace actions → Archive all meetings** (formerly Clear meetings) archives every active meeting in the selected workspace in one transaction.
  It works in normal mode. An active interview blocks the whole operation; no partial archive or
  implicit capture stop. Individual archive follows the same stopped-session rule.
- **Archive workspace** hides the workspace and its meetings from the main screen. It preserves
  each meeting's individual archive flag. Restoring the workspace restores the previous organization;
  individually archived meetings remain archived. Restore a workspace before restoring its meetings.
- **Archives** is a separate sidebar view. Search names, filter meetings by workspace and session
  type, inspect a meeting, restore, or permanently delete. Archived workspaces have their own view.
- Permanent meeting deletion is a red action with a confirmation dialog. The backend requires
  archived status, matching workspace, current meeting revision and explicit confirmation. It
  rejects live sessions and pending report generation. Test mode is unrelated to organization.
- Deletion removes working records, including human notes, suggestions and reports. It retains the
  [protected transcript archive](transcript-retention.md). Copy and confirmation distinguish these
  two stores. There is no permanent workspace deletion or public transcript-vault deletion endpoint.

Migration 8 adds `workspaces.archived` and an optimistic `revision`, defaulting existing spaces to
active. Meeting creation/start reject archived workspaces. Archiving does not rewrite transcript
identities. The deprecated bulk DELETE route now aliases reversible archiving, preventing older UI
clients from accidentally purging meetings. Physical deletion is per-meeting only through the new API.

## Questions actually spoken
A separate ledger records questions the model detects in delivered, finalized speech. It includes
manual questions and questions read from suggestions; it does not claim to know their origin.
Suggestion queued/asked/answered/discarded statuses remain human-controlled. We do not automatically
mark a suggestion asked from a lexical match.

The existing bounded analysis request adds `spoken_questions` (up to 16, 1500 characters each), with
verbatim text and up to six source IDs. Detection runs regardless of suggestion frequency/readiness;
it shares analysis batching, provider budgets and failure handling. No separate model calls, agent,
embedding index or question-classification service is added. The mock uses question punctuation for
plumbing tests only; Gemini is prompted to recognize spoken requests such as “walk me through…”.

Before persistence the app locates one exact occurrence in consecutive finalized source segments,
allowing whitespace variation only. Source offsets are Unicode character offsets. Skipped turns,
foreign sources, paraphrases, ambiguous repeated occurrences and large gaps are rejected. Invalid
optional quotes are omitted with a content-free diagnostic count; otherwise valid analysis survives.
Whole-provider/schema failures retain the existing retry/checkpoint policy.

Migration 9 adds `spoken_questions` and `spoken_question_evidence`. Each observation belongs to a
session and accepted analysis run; composite foreign keys bind exact segment revisions and ranges.
The ID hashes session + ordered revision/ranges. Overlapping batches and retries deduplicate the
same occurrence; the same wording spoken later is a separate observation. Failed/stale runs cannot
commit observations. Corrections retain old observations marked superseded, hidden by default but
available through “Include earlier revisions”.

Names/roles come from confirmed speaker spans intersecting the quote, never model guesses or source
channel names. Unconfirmed/multiple speakers remain unknown. A human mapping correction changes the
current view's attribution without rewriting the quote; saved reports retain their attribution
snapshot and existing outdated indicator. Transcript JSON exports and new reports include the ledger.
Existing saved reports remain readable and are not silently regenerated.

The UI calls these **detected** questions and links source passages. This is not an exhaustive,
verified account of every question: semantic detection, missing audio, batch boundaries and exact
matching can miss items. Retroactive extraction of already-processed historical meetings, manual
question annotation and strategy-scoring/evaluation dashboards remain follow-up work.

## Verification boundaries
Synthetic tests exercise isolation, live-session blocking, optimistic races, restore semantics,
confirmation, rollback on archive failure, migration/idempotence, corrections, retry deduplication,
role confirmation, provider staleness, disabled suggestions, exports and keyboard/browser workflows.
Provider semantic accuracy and a real multi-person capture remain separate release checks.
