# Analysis provider and model selection

2026-09-16 · Implemented locally. Gemini and OpenAI use separate server keys; the saved UI selection controls future calls.

- The bottom-left Analysis settings selects a provider/model for future requests across this local
  application, independently of analysis strategy and per-meeting scheduling. No automatic fallback.
- Migration 12 adds singleton `model_selection(provider, model, revision)`. An absent row uses
  environment defaults, preserving existing deployments. Updates use optimistic concurrency;
  unknown combinations and missing keys are rejected before any analysis allowance is reserved.
- Each request freezes provider/model/revision in its persisted input. Switching during I/O does
  not relabel or reroute that request. The model selection is part of the Manual fingerprint, so
  switching enables an explicit review of unchanged finalized text. Selecting alone makes no call.
- Gemini and OpenAI adapters return the same validated proposals. Evidence, attribution, stale-input
  checks, atomic commits, allowance limits and explicit Manual retry behavior remain shared.
- OpenAI uses Responses with `store=false`, low reasoning effort and strict JSON schema. All schema
  object fields are explicit; local validation remains authoritative. No provider tools are enabled.
  Timeout, refusal, incomplete and invalid responses cannot advance coverage. Error bodies are private.
- Keys remain in server environment settings, never model-selection storage or browser responses.
  Diagnostics record actual provider/model and normalized token usage; body recording remains opt-in.
- Run history retains provider provenance. New reports derive their provider label from successful
  runs, using `mixed` for multiple providers. Existing immutable reports are unchanged.
- Comparisons are sequential reviews of the same meeting with accumulated state, not a blinded
  benchmark. A controlled quality evaluation must use independent synthetic starting states.

## Gemini empty-output investigation
The prompt now explicitly permits neutral extraction from unidentified voices and treats empty
first-review question history as normal. It still prohibits invented identities and unsupported
claims. Full reviews explicitly request all output fields; empty arrays remain valid. An empty
successful review displays its reason instead of appearing silent.

Two approved real Gemini checks passed through validation/persistence with synthetic unidentified
speech: complete turns and fragmented turns each produced two threads, two spoken questions and one
suggested question. This does not establish real-meeting quality or eliminate intermittent 503s.
OpenAI transport is tested with mocked HTTP responses; real OpenAI verification is still pending.

References: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[manual analysis](context-rebuild.md), [observability](observability.md).

The [opportunity certainty correction](context-rebuild.md#opportunity-certainty-correction--2026-09-16)
is shared by both providers. Synthetic mocked-HTTP integration tests verify that a mislabeled
opportunity does not block two valid threads and a suggested question, while invalid evidence
still rejects the whole proposal. No real OpenAI request has been made during this verification.

## OpenAI schema correction — 2026-09-16
Schema conversion previously removed property names such as `title` along with JSON Schema
metadata, causing valid provider responses to fail local validation. Conversion now preserves
all names in `properties` and `$defs`; only schema-node metadata is stripped. Regression tests
compare every contract property across both strategies and scheduling scopes. No missing titles
are fabricated, validation remains strict, and rejected reviews remain pending for explicit retry.
