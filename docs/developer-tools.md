# Developer tools (local MVP)

Open **Developer** near the bottom of Explore's sidebar. It requires a separate local admin key,
not your Gemini key. Test mode does not grant access. Team admin/member accounts remain planned.

After starting the updated backend, run this in your own terminal from the repository:

```sh
uv run --project backend python scripts/developer_access.py
# Or with the already installed environment:
backend/.venv/bin/python scripts/developer_access.py
```

Paste that key into **Admin key → Unlock**. Keep it private; do not paste keys into chats. The session
lasts one hour. **Lock** revokes it and stops body recording; restart revokes all admin sessions.
The key file is created in `DATA_DIR` with private permissions.

## Investigate a failure
1. Unlock Developer and enable **Record request / response bodies** before reproducing the issue.
   This retains interview content locally and turns off automatically after 15 minutes.
2. Continue the interview or use **Retry analysis**. Recording itself makes no model calls and
   does not change provider limits.
3. Search the meeting title/request ID and select an attempt. Inspect timing, stage, token counts,
   request and response. Filter by outcome to find errors.
4. **Application logs** shows structured events. Analysis completion events carry the matching
   model request ID. Logs exclude bodies, keys and unfiltered third-party exception text.
5. Turn recording off or Lock. **Clear diagnostic history** removes diagnostics without touching
   meetings, reports or the protected transcript archive.

| Code | Interpretation |
| --- | --- |
| `provider_timeout_connect` | Connection establishment timed out; inspect network/provider availability |
| `provider_timeout_read` | Waiting for Gemini timed out; this does not prove it never processed the request |
| `provider_timeout_write` / `pool` | Sending data or acquiring a connection timed out |
| `provider_deadline` | Gemini returned HTTP 504 |
| `analysis_deadline` | Explore's total analysis deadline elapsed |
| `provider_http_429` | Provider quota/rate limit; a smaller batch may not resolve it |
| `provider_invalid_json` / `provider_invalid_fields` | Response did not satisfy the structured contract |
| Evidence/topic validation code | The response arrived but references were unsafe to apply |
| `stale` / `cancelled` / `interrupted` | Newer edits, stop/reset or restart prevented normal application |

Timeouts reduce the next batch's new-text budget without advancing its transcript checkpoint.
Retries remain subject to the same call/budget limits. Timeouts may have no response or usage,
even when the provider performed some work.

History contains new attempts only: at most 100 for 24 hours. Bodies are capped and may be truncated;
full original transcripts remain in the separate archive. Bodies are not retroactive, anonymized or
encrypted on disk. Normal logs retain bounded metadata. If Developer says unavailable after frontend
refresh, the backend may need restarting; end active capture first.

See [design](../design/observability.md) for retention and the future hosted authentication boundary.
