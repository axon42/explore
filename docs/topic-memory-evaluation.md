# Topic-memory evaluation

2026-09-12. Offline deterministic simulation only; these results do not measure Gemini quality.

Run from `backend`: `.venv/bin/python -m app.topic_eval`. The runner forces the mock provider,
uses temporary SQLite storage and ignores `.env`. Fixture: `fixtures/topic-switching-v1.json`.
Repository time advances by 61 seconds per turn to isolate readiness/intent from cooldown;
collection waiting is bypassed. No audio, user database or paid calls are used.

| Metric | Legacy simulation | Topic simulation |
| --- | --- | --- |
| Simulated calls | 6 | 6 |
| Questions | 6 | 2 |
| Questions outside allowed fixture checkpoints | 4 | 0 |
| Reporting resumed under the same topic identity | No topic identity | Yes |
| Observed pipeline p50 excluding collection wait | 264 ms | 267 ms |

The mock deliberately recognizes a few fixture labels and quotes transcript passages. Its delay
is artificial; timings are neither end-to-end latency nor predictions for a real provider.
Token usage is unavailable in this simulation. The comparison verifies integration and gates,
not general semantic accuracy or a guarantee that an interview will produce two questions.

Automated coverage additionally exercises hydration, source corrections, independent claim keys,
discarded intents, atomic/idempotent persistence, invalid routing, ownership, reset cancellation,
budget exhaustion, bounded context, migration and mocked Gemini schema round trips.

Before rollout, add held-out synthetic conversations with implicit topic switches, interruptions,
ambiguous pronouns, long pauses, corrections, no meaningful pain and mixed workflows. Annotate
expected topic identity, allowed question windows and exact supporting evidence. Run a separately
authorized bounded Gemini evaluation and set acceptance thresholds for premature/duplicate
questions, grounding, resume accuracy and latency from that baseline. Report waiting/provider/UI
latency separately, plus calls and provider tokens per minute; compare under the same cost cap.
