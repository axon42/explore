# macOS audio capture

Status: implemented local prototype. Deepgram streaming passed a five-second synthetic speech
smoke test on 2026-09-12. Real macOS permissions and dual-source capture still require verification.

## Decision
Keep Explore's interface and analysis in the browser/backend. A small macOS 13+ helper captures
microphone (AVAudioEngine) and system audio (ScreenCaptureKit). No Zoom entitlement, injected
meeting bot, audio driver, new public port, or conferencing UI is required. This supersedes Zoom
RTMS as the immediate test source; Zoom integration remains available independently.

## Boundaries
- `native/macos`: Apple-framework helper, ad-hoc signed .app with a menu-bar Stop action.
- `audio/source.py`: source protocol and helper adapter. Launch Services gives the helper its own app identity for permissions. A private Unix socket
  carries versioned JSON with 100 ms / 16 kHz / mono PCM16 frames. Socket EOF stops the helper.
- `audio/deepgram.py`: fixed Deepgram streaming endpoint, two independent mono streams.
  Converts interim/final responses to existing transcript events; no storage or analysis access.
- `audio/capture.py`: lifecycle, one active capture globally, optional test cutoff, final-result drain,
  ownership checks and calls to `Service.ingest`. Source and provider factories are replaceable.
- `AudioCapture.tsx`: status/control panel in Interview, using existing visual primitives.

A future browser/meeting integration implements a new AudioSource adapter, or emits the existing
TranscriptEvent directly. It need not change storage, evidence, analysis, notes or reports.
No native dependency is imported by the analysis layer; non-Mac hosts can still run replay.

## Evidence and identities
Microphone and mixed system audio are labeled by source, not inferred people or roles. Remote
speaker separation and confirmed participant mapping are [implemented separately](speaker-attribution.md). Headphones reduce duplicate remote speech
picked up by the microphone; there is no custom echo-cancellation algorithm. Interim revisions
and finals use stable capture/source/start identities. Accepted evidence is stored by the existing
repository. Capture resumes with a new identity and an offset after the last saved segment;
these timestamps describe the recorded timeline, not a wall-clock timeline across pauses.

## Lifecycle and security
Permission audit (2026-09-14): the current test Mac runs macOS 13.5. ScreenCaptureKit uses
Screen Recording authorization even though this helper registers only an audio output.
Removing the permission check does not provide permission-free system audio. Apple's
[Core Audio tap alternative](https://developer.apple.com/documentation/coreaudio/capturing-system-audio-with-core-audio-taps)
requires macOS 14.2+ and a different source implementation. Microphone-only capture could avoid
Screen Recording permission, but would not directly capture remote voices through headphones.
The user's capture preference is pending; no permission or source behavior changed in this audit.

Start requires an explicit consent checkbox and allowed local Origin. The helper receives no
provider keys; Deepgram's key stays backend-only. No screen output is registered and no audio
files are written. All system audio is included: users must close unrelated audio sources.
Accepted transcript content remains subject to configured analysis-provider processing.
Provider retention is governed separately by the user's Deepgram account/policy.

A single capture has two billable STT streams. Capture defaults to manual stop (`AUDIO_CAPTURE_MAX_SECONDS=0`),
as requested on 2026-09-12; an optional local test cutoff remains available at 30–600 seconds.
There is no automatic restart/reconnect or repeated paid retry. Duration settings are not a cumulative USD cap. Gemini's existing budget remains separate. Helper/provider failures stop capture and
surface fixed diagnostic codes, without audio/text/key logging. Stop/reset/shutdown close the
helper and streams; explicit stop allows a bounded final-result drain before report finalization.
Audio buffering is bounded; overflow fails visibly. Backend death closes the private socket to stop native capture.
Navigating away does not stop capture; use its original meeting panel or the macOS menu item.

## Verification and release boundary
Tests use synthetic PCM and provider doubles, never real credentials/devices. The native build
runs a conversion self-test without permission prompts. Browser tests cover consent, meters,
stop, setup failure and retained replay. Real system/microphone permission attribution, channel
quality and Deepgram latency still require a manual macOS smoke test. Ad-hoc signing is local
only; notarized distribution, Intel validation, native device selection, real diarization quality validation and a
persistent cumulative transcription budget are separate release work.

Permission-flow repair: launch the .app through `/usr/bin/open -n -W`, not its executable as a
backend child. The original child process could inherit the IDE/terminal responsibility chain
and fail to request its own microphone permission. IPC uses a random 0700 temporary directory
and a 0600 Unix socket; no TCP port, disk audio file, or provider key is introduced. Native socket
EOF exits the app even during permission setup. A transport-only Launch Services probe verifies
connection and termination without accessing devices; the user must still grant OS permissions.

Speaker separation (2026-09-14): Deepgram streams request `diarize_model=v1` for system audio
and shared/unknown microphones. An explicitly selected single-person microphone skips diarization.
Original channel IDs remain unchanged; versioned exact-text spans carry provider voice observations.
Each new capture has a fresh namespace and microphone choice. The backend persists the initial
human assertion in the same transaction as source claiming, before starting audio.
The native binary and its permission identity are unchanged by this implementation.


## Planned reliability follow-up — 2026-09-15
See [interview reliability and analysis quality](analysis-reliability.md) for capture/utterance
assembly, scoped diagnostics, durable analysis jobs and multi-topic evaluation. These are proposals;
the existing implementation and limits remain unchanged.
