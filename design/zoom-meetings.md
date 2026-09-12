# Zoom desktop + Explore

Approved direction: conduct calls in the normal Zoom app; keep Explore open beside it for
transcripts, questions, context, notes and reports. This replaces the Video SDK conferencing plan.
Status: design; regular Zoom Meetings ingestion is not implemented.

## Connection

Zoom Meetings RTMS → signed webhook → owned meeting-instance binding → transcript adapter →
existing ingestion, analysis and report pipeline. Reuse transport components only after validating
the Meetings contracts; Video SDK session keys and credentials are not interchangeable.

Explore owns workspace/meeting selection and capture status. Zoom owns devices, video, admission
and call lifecycle. Customers join an ordinary Zoom invite and do not need an Explore account.
Remove the Video SDK test link from the main workflow when the replacement is ready; retain the
isolated proof as development history. No new conferencing UI or guest-hosting system is needed.

## Prerequisites to verify first

- An active Zoom Developer Pack subscription with sufficient credits. Existing Universal Credit
  Video SDK trial balance does not establish Meetings RTMS eligibility.
- A user-managed General App, authorized by the host, with transcript-only scope
  `meeting:read:meeting_transcript` and `meeting.rtms_started` / `meeting.rtms_stopped` events.
- Choose explicit capture initiation after confirming account eligibility: a small Zoom in-meeting
  control surface or the supported REST flow. Do not assume a pasted meeting URL grants capture
  access. REST initiation has participant/invitation prerequisites that must be tested.

## Implementation boundaries

1. OAuth callback with state validation, protected backend token storage and least-privilege scopes.
   Public ingress exposes only necessary callback/webhook routes, not local controller APIs.
2. Bind the authorized host/account and actual Zoom meeting instance UUID to one Explore run.
   Meeting numbers can recur; never route by title, display name or meeting number alone.
3. Validate Meetings event envelopes and credentials separately from Video SDK. One stream owner,
   bounded queues/timeouts, deduplication, explicit interruption status and no silent reconnect loops.
4. Preserve exact transcript evidence and speaker IDs. Map participant names/roles with human
   confirmation; retain replay for deterministic testing.
5. Stop capture before sealing ingestion and finalizing. Test late events, duplicate/out-of-order
   notifications, reset races, account isolation, restart recovery and provider failures.

UI: Connect Zoom, select/link meeting, Start/Stop capture, and separate capture/analysis health.
Keep the existing evidence-linked question queue, Brief, Notes and Report flows.

The user will monitor spending manually during short tests. An app timer is not a provider invoice
cap. No paid subscription purchase or live capture is initiated by this design update.

## Sources checked

- [Meetings RTMS prerequisites](https://developers.zoom.us/docs/rtms/meetings/getting-started/)
- [General App, scopes, events and initiation requirements](https://developers.zoom.us/docs/rtms/meetings/add-features/)
