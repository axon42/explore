# Reliable capture and prepared interviews

2026-09-12. Approved plan and implementation record.
See the [roadmap](../docs/roadmap.md). User confirmed interviewer + customer for real interviews,
solo testing only in Test mode.

## What the current failure tells us
An earlier read-only capture snapshot: backend healthy; helper and key configured;
capture stopped with no error code after ~51 seconds, 1,026 frames and zero finalized audio
segments. Its session contains nine replay turns, no microphone/system segments, and no saved
participant roster. No transcript bodies or credentials were read for this audit.

User follow-up: the meter moved and “Mic testing” appeared, then transcription stopped while
speaking continued. A saved session matching that supplied phrase contains two finalized
microphone segments ending at 3.46 seconds and four audio revisions. It remains live. This is
a different observation from the zero-audio/replay-only run above; do not conflate attempts.
It proves initial capture/recognition worked and makes a post-start stall the priority.

A later capture snapshot reports 119 seconds, 2,358 frames, two finalized audio segments and
no error code. This is consistent with the reported stall but is not correlated to the phrase
session by a retained capture-run ID. Levels reset to zero on stop, so the stopped meter values
do not establish whether speech reached the provider after the first result.

The native AudioMux emits a 100 ms frame for each channel even when its buffer is empty,
padding with zeroes. Frame counts therefore prove transport activity, not audible speech.
In the zero-result attempt the provider sockets opened, but no accepted audio transcript was stored. Existing diagnostics
cannot identify whether the input was silent, the wrong device was used, or the provider
returned no useful result. Do not claim a confirmed root cause or a fix yet.

## Confirmed gaps from code review
| Gap | Planned correction |
| --- | --- |
| `capturing` means sockets opened, not speech received | Expose separate source-ready, signal-present, provider-connected, last-result and stored-transcript states |
| Silence padding hides missing device callbacks | Native per-channel callback/real-sample counters; report padding separately; retain last/peak signal on stop |
| No stalled-transcription warning | Distinguish source starvation, expected silence and non-silent audio without results; bounded warnings and cancellation, no blind paid retries |
| Capture diagnostics disappear on restart | Persist compact capture-run lifecycle, timings, safe codes and counters; never audio/text/secrets |
| Provider startup errors become generic exceptions | Preserve safe stage/status/request-ID categories, including exception-group failures; redact messages |
| Replay and capture can share one live session | Explicit test/real session provenance and producer exclusivity |
| New/reset meetings immediately create live sessions | Draft preparation, explicit validated start, idempotent session creation |
| Participants are optional metadata | Enforce roster on the server before real start/capture, not just a disabled button |

Capture plan: first correlate the exact capture/session and add per-channel last-sample,
last-nonzero-frame, last-send, last-provider-result and last-ingestion timestamps. Reproduce a
first-utterance-then-stall scenario; then fix the
observed device/adapter fault. Validate native conversion for nonzero samples, both sources,
input-device changes, missing callbacks, silence, provider empty results, provider close/error,
stop/final drain, reset/restart, stale events and budget exhaustion. Tests use synthetic PCM and
mocked services. A real audio rehearsal is a separate explicit user action after the repair.

## Meeting lifecycle
**New meeting → Draft → Add participants/brief → Start interview → Live → End → Report.**

- Drafts save preparation but create no live transcript session and incur no provider calls.
  Preserve session `live/stopped` storage semantics; allow a draft meeting to have no session.
  Detail APIs must explicitly represent that absence; UI must not invent a session ID.
- Start verifies roster revision and meeting ownership in one transaction, creates one session,
  snapshots its roster and is idempotent for concurrent/double clicks. Capture still requires
  explicit consent. Adding participants never silently starts capture or an LLM call.
- Real mode requires two distinct named people: an interviewer and a customer. Job role is
  encouraged, not invented. Participants need no Explore login. A participant is a person;
  microphone/system audio are sources, not participant identities.
- Current mixed system audio cannot reliably identify individual remote speakers. Do not
  equate a roster with diarization; keep sources explicit until mapping is actually known.
- Starting does not lock out legitimate roster corrections; preserve revisions/snapshots and
  require the gate again before restarting capture if required roles were removed.
- Existing sessions and reports retain their history. Existing ended meetings remain readable;
  old incomplete live runs are stopped/recoverable, never silently deleted or relabeled.
  Reset keeps preparation/human notes and returns to Draft.
- End interview stays visible in normal mode, stops/drains capture, then finalizes analysis
  and report. Stop capture remains separate. Do not hide Stop inside the replay toolbar.

## Test mode
A bottom-left **Test mode** switch reveals Play/Pause, Next turn, replay speed, injected dialogue,
test reset and legacy Zoom diagnostics. Off by default. Always show a Test session label.

Use a separate persisted session mode (`real` or `test`); it cannot change while active.
Turning off the UI switch never silently ends a call or converts test evidence to real evidence.
A test session still permits one named participant for microphone diagnostics. Loading a
synthetic fixture explicitly supplies its synthetic roster; never populate real participants.

Backend authorization/capability checks cover playback, inject and legacy demo routes. Hiding
buttons is not access control. Keep a trusted provider-ingestion boundary separate from manual
injection. Deny replay while real capture is active, including direct API requests and races.
Existing Gemini/Deepgram limits apply in Test mode too; test mode is not free-provider mode.

## Acceptance
- Real start/capture denied for no roster, missing role, blank names, stale roster or wrong workspace.
- Concurrent starts create one run; stale events cannot target a reset run.
- Normal UI has no replay/injection controls but always has capture stop and interview end.
- Test switch, solo test, fixture roster, denied direct API access and mode/producer races covered.
- Diagnostics identify the failed stage without private content; expected silence is not an error.
- Firefox rehearsal verifies speech → saved transcript → threads/questions → report, plus stop.

Existing capture + pipeline regression tests: 22 passed with synthetic data and mocked providers.
The private-socket test required execution outside the filesystem sandbox. Passing these tests
does not reproduce or resolve the user’s live-device stall.

## Implemented slice
Draft creation, transactional/idempotent start, roster snapshots, solo Test mode, sidebar switch,
source isolation and an always-visible End interview action are implemented. Reset returns to Draft
and preserves participants, brief and human notes. Existing sessions retain `legacy` mode rather than
inventing identities or reclassifying prior interviews. The legacy `POST /sessions` route now returns
`meeting_preparation_required`; callers must use the prepared meeting API.

Capture diagnostics persist run identity, stage, per-channel input samples, sent frames, provider
results, accepted events and timing/peak counters. No audio or transcript bodies are in this audit.
Real sample counts distinguish silence from timer padding; microphone starvation or missing frames
stops after ten seconds once streaming starts. Device configuration changes stop with an actionable
error. Restart marks interrupted runs failed. System audio may legitimately provide no callbacks
while idle, so microphone starvation is the automatic stop criterion.

No paid reconnect/retry is automatic. The two-minute capture cap was removed at the user’s request; capture now defaults to manual stop. Continuous conversion
and synthetic source/provider tests pass through the same boundaries; live macOS/Firefox + remote
speech rehearsal is still required. These diagnostics do not establish the historical stall's cause.

The implemented start request checks participant revision. Brief edits do not block starting; the
latest brief remains independently revisioned and analysis snapshots it per batch. Test mode uses a
local, shared Boolean preference; it controls test tooling, not authentication or provider billing.
