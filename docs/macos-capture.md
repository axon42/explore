# Mac audio capture setup

Explore stays at **http://127.0.0.1:5173** in Firefox. Call participants use Zoom, Meet or any
other app. This captures your microphone and your Mac's mixed system audio.

1. On macOS 13+ with Xcode Command Line Tools, run `python3 scripts/build_macos_capture.py`.
   This builds `native/macos/build/Explore Capture.app` and runs a synthetic conversion check.
2. Add `DEEPGRAM_API_KEY=...` to the existing local `.env`. Never use a `VITE_` variable.
3. Restart Explore. Create a meeting, save named participants, then **Start interview → Capture audio**.
   Solo microphone tests require **Test mode** and one named participant.
4. Select **Who is using this microphone?** or keep **Shared microphone / not sure**.
   Confirm participant consent and select **Start capture**. Allow microphone and screen-recording
   access when prompted. System audio uses ScreenCaptureKit; Explore does not save screen video.
   If denied, enable **Explore Capture** under macOS System Settings →
   Privacy & Security → Microphone / Screen Recording, then retry. Rebuilding can require reapproval.
5. Use headphones. Speak, then play meeting audio; the two meters should respond separately.
   Open **Speakers** to assign detected voices to named participants and review their roles.
   Unknown voices stay unassigned. **Correct speaker** changes only that final passage; whole-voice
   confirmation applies across the voice track. Each new capture requires a fresh microphone choice.
6. **Stop capture** ends transcription while keeping the meeting open. The Explore Capture menu-bar
   item can also stop it. Stopping/resetting the meeting stops capture before finalizing/deleting its run.

Default `AUDIO_CAPTURE_MAX_SECONDS=0`: no automatic duration cutoff. Use **Stop capture** or
**End interview** to finish. An optional test cutoff can be set to 30–600 seconds. Only one capture can run at once. Two Deepgram streams incur usage independently. The duration setting is not a dollar cap;
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

### Screen Recording is enabled but capture still fails
If the latest capture still reports `screen_permission`, stop capture before changing permissions.
A development build's saved macOS permission entry may be stale even when its toggle is enabled.

1. In System Settings → Privacy & Security → Screen Recording, select **Explore Capture** and
   remove that entry with **−**. Leave other applications' permissions unchanged.
2. Click **+**, then **⌘⇧G** in the file picker and open this repository's `native/macos/build/`
   folder. Select **Explore Capture.app** and add it again.
3. Enable it and accept **Quit & Reopen** if offered. Return to Explore and start capture again;
   each attempt launches a fresh helper process. Firefox's own permission is not the helper's grant.

The 2026-09-14 diagnostic showed microphone authorization succeeding while macOS denied screen
capture for the exact bundled helper, before any audio frames or provider calls. The helper signature
verified and no helper remained running. A stale grant is a hypothesis, not a confirmed root cause;
re-adding the app and retesting is required. Do not reset all macOS permissions or rebuild the helper
just to retry, since changing a development signature can itself require new permission approval.

## Diagnosing a stalled transcript
Expand **Capture diagnostics** under Mac audio. Input samples show actual converted microphone
samples; sent frames alone can include silence padding. Provider results and accepted-event counters
show whether the failure is before transcription or before storage. Last input/result times and the
run ID remain available after Stop and backend restart. No interview body is logged.

After a microphone device change, select the intended input and restart capture. A ten-second loss
of microphone samples or helper frames stops the run explicitly. Ordinary silence still has samples
and does not trigger this check. Provider silence while audio arrives is visible in counters; it does
not trigger an automatic paid retry. Manual-stop mode removes the former two-minute cutoff; failure detection and bounded connection/drain timeouts remain.
