# Zoom Video SDK account proof

Implemented: a local opt-in join-token endpoint and standalone official Zoom Toolkit page at
`http://127.0.0.1:5173/zoom-proof.html`. This tests account/video connectivity only. It does not
capture transcripts, invoke Gemini, provide guest authentication or implement the approved live UI.

## Your setup

1. In the Zoom web portal, open **Advanced → Zoom CPaaS → Manage** beside Universal Credit,
   then **Build App**. Alternatively use Marketplace **Develop → Build Video SDK**.
2. Under **SDK credentials**, copy **SDK Key** and **SDK Secret** into the repository's ignored
   `.env` as `ZOOM_VIDEO_SDK_KEY` and `ZOOM_VIDEO_SDK_SECRET`. These are different from the
   API Key/Secret. Do not paste secrets into chat or prefix them with `VITE_`.
3. Check trial expiry, remaining credits and automatic overage behavior in Zoom before calling.
   When ready to consume trial credits, set `ZOOM_PROOF_ENABLED=true` and restart Explore
   using the existing development launcher. Keep it false otherwise.
4. Open the proof page. Start with two local tabs using synthetic names and headphones/muted
   audio to avoid feedback. First join is host, subsequent joins are participants. The backend
   issues at most four tokens per process, all for one random room. It does not accept a room
   name or role from the browser. Use the host's **End** control after a 1–2 minute test.
5. Confirm the session ended in Zoom and inspect actual credit consumption. Token expiry,
   closing tabs, the four-token limit and disabling the endpoint do not terminate an active call
   or enforce a dollar cap. Do not restart repeatedly to bypass the test limit.

For RTMS, open **Add feature → Event Subscriptions** and look for **RTMS Started** and
**RTMS Stopped** (`session.rtms_started`, `session.rtms_stopped`). Report whether these are
available. Zoom documents RTMS enablement as a prerequisite; Build Platform credits alone do
not prove it is enabled. If unavailable, request Video SDK RTMS enablement through Zoom
Developer Support. Do not buy Developer Pack solely on the assumption that it fixes this.

An event notification URL will be provided when the signed webhook receiver is implemented
and hosted. Do not enter localhost or expose the entire development app through a tunnel.
A two-device call requires the planned authenticated HTTPS deployment; the initial proof is
deliberately local, with two tabs as a first account check.

## Implementation notes

`backend/app/zoom_proof.py` signs HS256 tokens with PyJWT using Zoom's minimum 30-minute
JWT validity. This controls admission, not meeting duration. Local Host/Origin protection remains
in effect, POST additionally requires an explicit local browser origin, responses are no-store,
and secret values are not returned. The proof room is ephemeral and separate from meeting data.

The official Toolkit 2.5.0-1 npm package declares React 18 peer dependencies; Explore is React 19.
The separate HTML page loads Zoom's pinned hosted UMD/CSS only after a user action. The ESM
bundle failed in Chrome with an automatic-publicPath error; the browser-script bundle loads
successfully. Load failures occur before token issuance and show a distinct retryable error. No toolkit
dependency is added to the application bundle. These external assets are a proof dependency;
the final adapter's packaging is decided after the account test. Recording and extra features are
disabled in the proof controls; account-level auto-recording must also be checked in Zoom.

The user verified that the video proof works and RTMS events are available in the app.
Remaining: public HTTPS receiver deployment, one-owner transcript adapter, source draining,
authenticated hosting/guest flow, budget enforcement and the approved UI.

## Signed webhook receiver

`app.zoom_webhook:app` is a separate FastAPI application exposing only
`POST /webhooks/zoom`. It never exposes Explore's local controls or join-token endpoint.
Configure `ZOOM_WEBHOOK_SECRET_TOKEN` with the app's Add feature Secret Token.

Local receiver command, from `backend/`:

```bash
uv run uvicorn app.zoom_webhook:app --host 127.0.0.1 --port 8002 --no-access-log
```

The receiver verifies HMAC SHA-256 over the original request bytes and requires a timestamp
within five minutes. It caps bodies at 32 KiB and returns safe error codes without echoing data.
Signed `endpoint.url_validation` requests receive Zoom's challenge response. RTMS start/stop
events are stored transactionally in `DATA_DIR/zoom-webhooks.sqlite3`, with duplicate suppression
across restarts. The 1,000-event capacity fails with 503 when full instead of silently discarding
events. This inbox is separate from the meeting database and has no outbound network behavior.

This is ingress only: receiving a start event does not yet establish an RTMS WebSocket or start
Gemini analysis. A future worker must validate provider account/session ownership and permitted
Zoom endpoints before using stored URLs, handle stop-before-start/reconnects and reject stale
streams. Saved notifications are not a replayable archive of audio that was never received.

For deployment, use an isolated service with persistent disk, HTTPS termination, ingress rate/body
limits and no request-body logging. Expose only `/webhooks/zoom`; do not publish the local app.
The final URL will be `https://<assigned-host>/webhooks/zoom` after hosting is selected/configured.
Then enter it in Zoom, click Validate and Save. No public URL has been provisioned yet.

## Sources

- [Get Video SDK credentials](https://developers.zoom.us/docs/video-sdk/get-credentials/)
- [Join token contract](https://developers.zoom.us/docs/video-sdk/auth/)
- [Official UI Toolkit](https://developers.zoom.us/docs/video-sdk/web/ui-toolkit/)
- [RTMS account prerequisites and events](https://developers.zoom.us/docs/rtms/video-sdk/add-features/)

## RTMS transport checkpoint

`app.zoom_rtms` now provides a transcript-only WebSocket transport with signed signaling/media
handshakes, keep-alive replies, bounded socket queues/timeouts and cancellation cleanup. It uses
existing `websockets` and rejects endpoints outside RTMS-prefixed Zoom hosts. Packet normalization
preserves distinct utterances and deduplicates identical stream/speaker/timestamp/text packets;
Zoom provides utterance start times, so duration is not inferred. It does not infer corrections.

This transport is not yet activated by the application. A session-ownership coordinator, durable
capture lifecycle/budget controls and host UI wiring are still required before live use. Tests use
synthetic sockets and no credits. Billing remains unresolved: Build Platform billing documentation
describes plan management but does not document a disable-overage switch. Do not assume that a
trial or application timer guarantees a zero invoice.


## Local live transcript test (connected pilot)

The user authorized a manually monitored trial test. Enable `ZOOM_PROOF_ENABLED=true` only for
this run. In Explore, create a fresh meeting, then use **Zoom test**. The same link may be opened
in a second local tab. First join is host; subsequent joins are participants (four tokens maximum).
After joining, the host explicitly presses **Start transcription (2 minutes)**. Speak synthetic
interview dialogue and watch the selected Explore meeting for transcript and analysis updates.
Use **Stop transcription**, then Zoom **End for everyone**. Explore's Report tab can finalize the
received transcript after capture stops. The timer is not a billing cap and does not end video.

`ZoomCapture` now binds the server-generated JWT `session_key` to exactly one fresh local run.
It polls the signed inbox, connects once to matching RTMS events, rejects stop-before-start streams,
and delivers through `Service.ingest`. Failed streams do not reconnect automatically. Stopping or
resetting the Explore run cancels capture. Only this ephemeral local pilot is implemented: restart
loses its binding and cannot recover missed speech. Captured evidence persists in normal transcript
storage. Keep a note of any capture interruption; reports cover received speech only.

The existing isolated receiver remains on localhost:8002 and its existing Cloudflare tunnel is
reused; the main app is not exposed. The Toolkit's documented debug-mode client access enables
host RTMS controls in the separate local test page. Never share browser debug logs containing
provider session details. Real account handshake, SDK RTMS availability and latency still require
the user's live test; synthetic transport/coordinator/browser tests do not prove those capabilities.


## Disconnect and capture diagnostics

**Disconnect test** cancels and awaits the local capture worker, releases its binding, rotates
room/passcode/session identity and restores four join slots for the next explicitly started test.
It does not delete meeting data. Generation checks reject stale disconnect/start/stop requests;
join and disconnect are serialized. Old Zoom JWTs cannot be revoked locally, but refer to the old
room and cannot route transcripts into the new binding. From the connected host browser the UI
also requests Zoom end-for-everyone; without that host connection it cannot guarantee the old
Zoom call or its billing has stopped. End the old call before starting another.

Capture availability is checked repeatedly after joining, with visible reasons for participant
role, missing SDK RTMS controls, unsupported sessions and not-ready state. Event handlers are
registered before join so synchronous/early join notifications cannot be missed. Account/browser
RTMS support still needs live verification. Firefox remains the user's testing browser on 5173.

### Updated test controls
Use Firefox at `http://127.0.0.1:5173` and open a meeting's Zoom test link.
1. Clear an old pending connection with **Disconnect test**, then reload the same link.
2. **Start Zoom preview**, allow microphone access, and join in the Zoom panel.
3. Check **Host · this tab** and microphone status, then **Start transcription (2 minutes)**.
4. **End Zoom for everyone** ends the host call. Connected host tabs also expose **End this session**
   to other test tabs in the same browser. Wait for confirmation before resetting.

Disconnect clears local ingestion and cancels pending preview; it does not terminate a remote call.
Keep the host tab open until ending. Session activity cannot discover calls in another browser or
closed tabs. Do not interpret an empty list as proof that Zoom billing has stopped.

Test shell assets: `zoom-proof.html`, `zoom-proof.css`, `zoom-proof.js`; isolated SDK adapter:
`zoom-sdk.js` + `zoom-frame.html`. No frontend framework or dependency added.
