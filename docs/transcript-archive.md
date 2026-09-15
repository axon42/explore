# Retained transcripts

Explore now keeps accepted transcript revisions in a separate append-only SQLite archive.
**Reset test** and confirmed permanent meeting deletion remove working data but retain the transcript archive. **Clear meetings** now moves working meetings to Archives without deleting them.
No automatic cleanup or application delete path removes it, including during MVP testing.

With the default `DATA_DIR=./data`:
- Working data: `data/meetings.sqlite3`
- Retained evidence: `data-transcripts/transcripts.sqlite3`

For a custom data directory, the archive uses its sibling `<directory name>-transcripts`.
Do not delete that directory, its database, or SQLite journal files. Keep both databases on
a reliable local filesystem. The working DB now uses rollback journals instead of WAL to
commit both files atomically. Startup refuses a missing/replaced previously bound archive.

## Export for evaluation
From the repository root, list retained sessions (metadata only), then export the chosen IDs:

```sh
uv run --project backend python scripts/transcript_archive.py list
uv run --project backend python scripts/transcript_archive.py export \
  --workspace WORKSPACE_ID --session SESSION_ID --output /path/to/interview.json
```

JSON contains every accepted revision, including interim text and superseded corrections,
plus available participant/brief/source snapshots. It does not contain recorded audio, rejected
deliveries or analysis outputs. Never concatenate all revisions as if they were separate speech;
select the latest revision per segment for a current transcript. Outputs never overwrite files.

The CLI reads the archive independently: exports still work after a working meeting is cleared.
An explicit `--archive /path/to/transcripts.sqlite3` before the command selects another archive.
Existing in-app report/transcript downloads continue to use their selected working meeting.

## Backup
Create a consistent backup while the app is running, preferably to another device:

```sh
uv run --project backend python scripts/transcript_archive.py backup \
  --output /path/on/another/device/explore-transcripts-2026-09-14.sqlite3
```

There is no automatic off-device backup yet. A separate directory does not protect against disk
loss. Archive data is plaintext; keep exports/backups private. Previously deleted transcripts and
speech never received by Explore cannot be recovered. See [design](../design/transcript-retention.md).
