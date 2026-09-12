# Mac audio capture setup

Explore stays at **http://127.0.0.1:5173** in Firefox. Call participants use Zoom, Meet or any
other app. This captures your microphone and your Mac's mixed system audio.

1. On macOS 13+ with Xcode Command Line Tools, run `python3 scripts/build_macos_capture.py`.
   This builds `native/macos/build/Explore Capture.app` and runs a synthetic conversion check.
2. Add `DEEPGRAM_API_KEY=...` to the existing local `.env`. Never use a `VITE_` variable.
3. Restart Explore. Create/open a live meeting → Interview → **Capture audio**.
4. Confirm participant consent and select **Start capture**. Allow microphone and screen-recording
   access when prompted. System audio uses ScreenCaptureKit; Explore does not save screen video.
   If denied, enable **Explore Capture** under macOS System Settings →
   Privacy & Security → Microphone / Screen Recording, then retry. Rebuilding can require reapproval.
5. Use headphones. Speak, then play meeting audio; the two meters should respond separately.
   Transcript labels are **Microphone** and **System audio**, not guessed participant identities.
6. **Stop capture** ends transcription while keeping the meeting open. The Explore Capture menu-bar
   item can also stop it. Stopping/resetting the meeting stops capture before finalizing/deleting its run.

Default `AUDIO_CAPTURE_MAX_SECONDS=120`; allowed range 30–600 seconds. Only one capture can run at
once. Two Deepgram streams incur usage independently. This is a duration limit, not a dollar cap;
provider costs and retention are governed by the Deepgram account. The existing Gemini budget is separate.
No raw audio is retained by Explore. Accepted transcript revisions remain exportable.

| API | Behavior |
| --- | --- |
| `GET /audio-capture` | Safe configuration, active capture identity, health, levels and time limit |
| `POST /sessions/{sid}/audio-capture` | `{ "consent": true }`, live session + local Origin required |
| `POST /sessions/{sid}/audio-capture/stop` | `{ "capture_id": "..." }`, rejects stale/wrong-session requests |

Failures show safe codes/messages; missing permissions/key never silently switch to demo data.
After backend failure, the helper stops when its private socket closes. No tunnel is needed for capture.

[Design and replacement boundaries](../design/macos-audio-capture.md).

Verification: Deepgram authenticated and returned a valid final transcript from five seconds of
synthetic speech through the production adapter (2026-09-12). No microphone or system audio was
used in that check; live native capture remains a separate manual acceptance test.

Firefox permission is separate from native capture. Explore Capture is launched through macOS
Launch Services so it can request its own permissions. If its entry is missing, retry Capture audio
with the updated backend; do not grant microphone access to unrelated apps.
