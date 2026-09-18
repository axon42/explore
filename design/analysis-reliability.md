# Interview reliability and analysis quality

2026-09-15 · Broader reliability plan. Manual analysis receipts are implemented; the queue, metrics
and transcript-quality work below remains planned. Typical meetings: 45 minutes. Mac capture works.

## Findings
- “Correct speaker” was an inline UI action, not stored transcript text. It now lives in a separate
  collapsed passage picker with exact speaker correction and evidence anchors preserved.
- Deepgram currently uses Nova-3, interim results, punctuation and 300 ms endpointing. The adapter
  uses `is_final` but does not retain `speech_final` as a boundary signal. Final fragments are not
  completed thoughts. [Provider distinction](https://developers.deepgram.com/docs/understand-endpointing-interim-results).
- One broad thread could reflect missing analysis coverage, routing quality, rejected output or
  persistence/display issues. Compare captured/analyzed watermarks and requests before diagnosing.
  The screenshots' minute-24 citations versus minute-49 transcript are a clue, not proof of stoppage.
- Existing processing uses in-memory workers/wakeups with persisted attempts/coverage, not durable
  leased jobs. The 100-attempt session default includes failures; question frequency is separate.

## Order
1. [Scoped diagnostics and Test-mode metrics](observability.md): expose coverage, limits and errors.
2. Improve utterance assembly/attribution and remove correction buttons from transcript prose.
3. [Manual full-transcript analysis](context-rebuild.md) is implemented for new meetings, with
   durable receipts and explicit retries. Automatic incremental mode remains; its durable queue below is planned.
4. Evaluate topic quality before changing prompts/models. Automatic post-meeting review stays later.

## Transcript quality
Preserve immutable transcript revisions, derived readable utterances and confirmed attribution as
separate layers. Use boundary signals, word timing and speaker changes with bounded waiting;
benchmark endpointing rather than assuming a larger delay fixes recognition. Retain exact span IDs.
Never join different voices just to remove breaks, or infer customer identity from remote audio.
Scope diarized labels to connection/capture epochs so reconnects cannot inherit another identity.

Measure microphone/system gaps, overlap/echo, unknown voices and confidence separately. Confidence
is not accuracy. Audio is not retained today; missing words cannot be recovered reliably from text
alone. Any future audio evaluation recording needs its own consent/access/retention decision.

## Durable jobs and ACK
Start with SQLite plus a worker behind a replaceable repository interface; no broker or agent
framework yet. ACK means **validated results committed**, not HTTP acceptance. Provider execution
is at least once; application commits must be idempotent. Timeouts can still incur provider charges.

| Record | Required data |
| --- | --- |
| Job | Workspace/meeting/session generation; stable ID; frozen input/source revisions; context/attribution/prompt/model versions; state, due time, lease/token, attempt ceiling |
| Attempt | Unique request ID, job/provider IDs, timing, outcome, usage or unknown-usage flag, budget reservation |
| Pending work | Per-session desired watermark, distinct from committed coverage; coalesces incoming text |

- Persist pending work with ingestion or reconstruct from durable coverage on startup. Never drop
  accepted text when notifications overflow. One active job per session; bounded global concurrency.
- Provider I/O stays outside database transactions. Lease fencing rejects expired workers. Commit
  validated artifacts, coverage and ACK atomically; crashes/retries cannot duplicate questions.
- Retry frozen input; changed batching/context creates a replacement job. Corrections and reset
  invalidate stale jobs. Stop drains bounded pending work; archived sessions never restart silently.
- Blocked jobs preserve evidence and unadvanced coverage. Show backlog age and analyzed-through
  time; suppress premature questions while catching up. Recovery is explicit and budgeted.
- Automatic mode only: proposed retry ceiling of three attempts, backoff/jitter and retry hints.
  Manual mode has no background retry; every retry is another explicit, budgeted attempt.
  Retry transient network/5xx/throttling failures; stop on credentials, hard quotas/budgets and bad
  requests. Schema/semantic failures need inspection or a separately budgeted repair strategy.
  [Gemini guidance](https://ai.google.dev/gemini-api/docs/troubleshooting).
- Reserve persistent capacity before sending; all attempts count and unknown usage is conservative.
  Set analysis cadence independently of question frequency. Capacity must cover live calls, retries
  and final draining. Numeric budgets/cadence remain undecided; current limits are not raised.

## Topic quality
Keep the full topic catalog plus bounded focused/related detail and source passages. Classify
continue/switch/resume/new/uncertain within the existing single call; do not broaden one topic to
absorb unrelated subjects or create permanent threads for every noun. Ambiguous assignments stay
provisional. Preserve contradictions, topic-scoped question history and evidence when resuming.

Inspect input → proposal → validation → storage → UI. Compare incremental, full-history and manual
rebuild on identical labeled interviews before choosing a model/context strategy. No automatic
expensive fallback, separate agent per topic or “SOTA” quality assumption.

## Acceptance
- 45-minute standard and 60-minute stress replays: all accepted revisions accounted for; no silent
  stalls, duplicate commits or unsupported evidence. Mac capture itself is not the current blocker.
- Queue tests: crash before send/after response/after commit, lease expiry, duplicate delivery,
  correction/reset/stop/archive, deadlines, quota/budget exhaustion and workspace/session isolation.
- Transcript/UI tests: corrections, out-of-order finals, reconnects, overlapping speakers, Unicode,
  grouping/copy/export fidelity and accessible narrow layouts. No source-text rewriting.
- Quality fixtures: labeled A → B → A switches, incidental mentions, short denials and role ambiguity;
  measure missed/excess threads, switch delay, evidence correctness and question usefulness.
- Diagnostics: scoping, admin gates, redaction, missing/truncated bodies and unknown usage.

Use synthetic mocked fixtures for regression. Real-provider/audio evaluation is separately authorized,
budgeted and labeled; counters and valid JSON alone do not establish semantic quality.
