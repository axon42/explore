# Debugging and error logging — follow-up

Requested by the user after generic Gemini and Zoom failures obscured their causes. Planned work:

- Correlation IDs across browser actions, API requests, provider calls and capture jobs.
- Structured events with operation, safe error code, duration, outcome and relevant internal IDs.
- Separate device permission, token issuance, SDK join, webhook, RTMS handshake, ingestion,
  analysis and report failures. Preserve the originating stage through the UI.
- A local diagnostic view and redacted support export: configuration presence (never values),
  versions, connection state, retry counts, last success/error and queue/capture health.
- Rotating logs with bounded retention. Never log keys, JWTs, OAuth tokens, passcodes, signed
  stream URLs, transcript bodies, raw model responses or unfiltered SDK exceptions.
- Tests for redaction, error-code propagation, request correlation and failure recovery.

Current small fix: the Zoom proof maps known backend rejection codes to fixed actionable messages.
Unknown responses show HTTP status only. It does not automatically retry token issuance.


Implemented narrow analysis diagnostic (2026-09-12): validation failures now store an
allowlisted `validation_code` in the analysis run and emit `analysis_rejected` with session/job
IDs and that code. The UI receives a fixed explanation and code; arbitrary exception text,
model output, transcript text and keys are excluded. Provider usage survives semantic rejection.
Older generic failures cannot be retrospectively classified because their reason was discarded.
