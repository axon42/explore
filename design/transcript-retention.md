# Durable transcript archive

2026-09-14 · Implemented; protection from MVP resets is required by the user.

## Contract
Every accepted transcript revision—interim, final and correction—is retained verbatim as
structured text, with its original event/segment/session IDs and speaker/timing fields.
The archive is independent of analysis windows, questions, reports and working-data cleanup.
Duplicate or rejected deliveries are not additional accepted speech. Audio is not retained;
speech never delivered to Explore and history deleted before this change cannot be recovered.

## Isolation and durability
- Working database: `DATA_DIR/meetings.sqlite3`. Archive: sibling directory
  `<DATA_DIR name>-transcripts/transcripts.sqlite3` (normally `data-transcripts/`). This is a
  separate SQLite file and directory, not a physical disk partition or a second service.
- Accepted text is inserted into both databases in one SQLite ATTACH transaction, before
  acknowledgement or analysis notification. Both use rollback journals and FULL synchronous
  writes. WAL is deliberately removed: SQLite does not guarantee crash-atomic multi-file
  commits with WAL. Existing single-process ordering remains appropriate for the local app.
  [SQLite transaction guarantee](https://www.sqlite.org/lang_attach.html).
- Archive tables have no foreign keys to working tables. Their own constraints and UPDATE/DELETE
  rejection triggers protect the append-only contract. There is no archive deletion API, TTL,
  reset command or LLM write path. This is not tamper-proof storage against filesystem access.
- Startup backs up an existing working DB before migration, then idempotently copies all retained
  revisions. A bound archive identity prevents silently starting over with a missing/replaced vault.
  Archive failures fail the operation; capture must not acknowledge an unprotected transcript.
- Reset/permanent meeting deletion recheck and preserve accepted revisions in the same transaction before deleting
  working projections. Session IDs remain unchanged in retained evidence; stale input cannot
  enter a replacement session. Real and synthetic session modes remain separate metadata.

## Records and evaluation
Archive schema version 1 stores sessions with meeting/workspace ownership, accepted revision
payloads with SHA-256 integrity digests, and deduplicated context snapshots (roster, brief, source
and session metadata). Context is sampled at ingestion, stop, startup and before working deletion;
roster and attribution edits also append context snapshots immediately (context schema 2).
Other human edits are not completely audited here. Old source labels remain labels, not confirmed people.

The working transcript is the current projection; the accepted revision archive is the durable
evaluation source. Later analysis can select finals/current revisions without modifying the archive.
Offline export requires workspace and session IDs and remains usable after working-data deletion.
The protected transcript vault is exported through the offline utility. The separate UI Archives page restores archived working meetings; it does not browse or erase this vault.

## Backup and verification
Use the read-only [archive utility](../docs/transcript-archive.md) to export or create a consistent
SQLite backup. Files remain local plaintext with owner-only archive permissions. A separate directory
protects against app cleanup, not device failure; keep an independent backup on another device.

Synthetic tests cover corrections/deduplication, rollback/retry, process interruption before commit,
missing archive, append-only triggers, concurrent duplicates, backfill/restart, reset/clear survival,
offline scoped export and backup. No real credentials or interview bodies are used in tests/logs.
Physical power-loss behavior relies on SQLite and the filesystem; it is not simulated by process exit.
