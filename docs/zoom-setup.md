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
