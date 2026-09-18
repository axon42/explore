# Manual full-transcript analysis

2026-09-15 · Implemented locally. Typical meeting: 45 minutes; real-model quality/latency rehearsal pending.

## Scheduling
- New meetings default to **Manual**. Migration 11 preserves existing meetings as **Automatic**;
  reset retains the meeting's choice. Scheduling has its own optimistic revision, separate from
  Standard/Discussion threads and model selection.
- **Analyze now** makes one attempt over every accepted final segment's latest revision. Capture
  continues. Arrivals, timers, edits and mode selection never dispatch a Manual call. Explicit meeting
  end runs a separate full-transcript final review; see [reports](meeting-reports.md).
- **Automatic** retains incremental coalescing and finalization. Changing scheduling makes no call;
  the next notification can trigger Automatic. Changes are blocked during an in-flight attempt.
- The meeting control shows coverage, pending segments, status and remaining calls. Unchanged
  successfully reviewed input cannot be submitted again. Failures require explicit **Retry analysis**.
  There is no separate rebuild button, automatic retry, broker or multi-pass review.

## Frozen request
- Include all finalized text with stable IDs/revisions, confirmed attribution, the brief, all human
  notes and the complete question ledger. Topics include every current index/detail/history entry.
  Prior AI memory is comparison material, not evidence. Raw transcript revisions remain in the vault.
- Provider/model selection is frozen per call and included in the Manual fingerprint. A change
  permits explicit re-analysis; it never triggers a request. See [model selection](model-selection.md).
- The exact serialized provider envelope is capped at **1,000,000 UTF-8 bytes** before allowance
  reservation. Nothing is truncated. This is an application limit, not a tokenizer estimate.
- Full-output contract: at most 24 topic updates, 80 claims, 40 findings, 20 workflows, 80 question
  matches and 200 spoken questions; one optional suggested question. Gemini output budget is
  **16,384 tokens**. Incremental limits are unchanged. A required `complete` flag must be true;
  malformed/truncated/incomplete output fails without advancing coverage. This is not proof of
  semantic completeness; evaluate topic recall and grounding separately.
- Existing per-session allowance (configured default 100) and timeout remain. Provider errors and
  cancelled attempts consume their reserved allowance. No hidden smaller-batch retry in Manual mode.

## Persistence and races
- `manual_analysis_jobs` stores a UUID idempotency key, session ownership, input fingerprint, frozen
  input, status and safe error. Receipt and call reservation commit together before provider I/O.
  One running receipt per session; duplicate keys return the same receipt, never another call.
- Validated memory, source coverage, artifacts, analysis-run history and success ACK commit in the
  same repository transaction. Previous valid context remains visible during failures/in-flight work.
- Source corrections, attribution or human-context changes reject stale results. New appended speech
  may coexist with the frozen result; it stays pending. Manual suggestions remain available with a
  newer-speech notice; Automatic still suppresses suggestions while speech is pending.
  No automatic follow-up runs. Human notes and asked/discarded question history are preserved.
- Stop/reset cancels the worker; restart marks unfinished receipts interrupted. Neither resumes paid
  work. A fresh click is required. Reset changes session identity; archived scopes reject mutations.
- Report formatting makes no model calls in Manual mode. Incomplete coverage/context produces a clear
  error: analyze the stopped meeting explicitly, then generate its immutable report revision.

## Diagnostics and acceptance
Developer trace metadata identifies scheduling, scope, source watermark, usage, request bytes,
question publication/suppression reasons and accepted/rejected spoken-question counts.
Body recording remains admin opt-in with the existing 128 KiB redacted preview cap and visible
truncation flag; the frozen analysis input is persisted separately. Expanded debug tooling remains planned.

Synthetic tests cover defaults/migration, full input beyond incremental bounds, preserved notes and
history, duplicate/cross-session requests, errors, cancellation, correction/new-speech races, atomic
ACK rollback, budgets and report finalization. Browser checks cover scheduling, coverage and responsive
controls. A mocked provider verifies plumbing, not model comprehension.

Two clicks per five minutes means up to 18 clicks in 45 minutes; this is not a configured rate limit.
Compare manual and incremental modes on labeled 45-minute interviews before broader rollout.

## Output-limit correction — 2026-09-15
A real Manual response failed with an oversized array. Full-review schemas transmit actual
`minItems`/`maxItems` for primitive evidence lists. Large nested object collection bounds remain
in descriptions and strict local validation, avoiding costly repeated constrained-generation grammars.
A synthetic full-schema request returned 400 while a minimal request succeeded on the same key/model;
the same synthetic request with simplified bounds returned 200 in 4.5 seconds, completed and passed
local contract validation. This verifies request acceptance, not meeting-scale topic quality. Local validation still rejects
oversized responses without truncating evidence or advancing coverage. Diagnostics record only
schema-owned paths and numeric limits/counts; response content remains opt-in. See
[Gemini schema support](https://ai.google.dev/gemini-api/docs/structured-output#json_schema_support).

## Opportunity certainty correction — 2026-09-16
An observed-opportunity label caused an otherwise structured full review to fail. Opportunity
findings now always normalize to `inferred` after field validation, downgrading certainty without
changing their text or evidence. This applies to both providers; unknown fields, invalid enum values,
evidence and attribution remain strictly validated. No extra model call or automatic retry is added.

Latency optimization is [planned separately](analysis-latency.md). Full-transcript scope and
manual dispatch remain unchanged until a measured alternative is approved.
