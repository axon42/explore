# Explore video interviews — design proposal

2026-09-11. Scope: plan and UI concept, not an implemented conferencing feature.
Extends the [release plan](interview-ready-release.md); analysis quality improvements remain Stage 2.

Implementation checkpoint: [local account proof and setup](../docs/zoom-setup.md) now provides
opt-in server-signed join tokens and a standalone Zoom Toolkit page. RTMS and two-device hosted
verification remain pending credentials/entitlement and authenticated hosting. The Toolkit npm
package requires React 18, so the proof uses its standalone hosted bundle rather than changing
Explore's React 19 application. The approved custom UI is not implemented yet.

Webhook checkpoint: a separate signed ingress app now validates Zoom challenges and persists
RTMS lifecycle notifications in a bounded, duplicate-safe inbox. It deliberately has no local
controller routes or outbound stream connections. Public HTTPS hosting and the RTMS worker
remain pending; a validated webhook alone does not establish live transcription.

## Product decision

Host an Explore interview using Zoom Video SDK. Guests join an Explore link; cofounders see the same call plus private interview assistance. Keep Zoom-specific code at the media and transcript boundaries so ordinary Zoom meetings can be added later through a separate adapter.

Assumptions for the first pilot: one concurrent interview, four participants, desktop cofounder experience, guest camera optional, host admits guests, all workspace cofounders share questions and notes. Customers cannot access the brief, analysis, internal notes, history or reports. These are proposed defaults; guest access must be enforced by the backend, not by hiding tabs.

## Technical proof before feature build

Verify the account can create a Video SDK session and receive RTMS transcripts, with two devices and stable speaker attribution. Confirm trial expiry, metering, overage behavior and the combined Video SDK/RTMS cost. Build Platform credits are required by [RTMS for Video SDK](https://developers.zoom.us/docs/rtms/video-sdk/), but the screenshot alone does not establish enabled features or remaining balance.

Use the official [web SDK](https://developers.zoom.us/docs/video-sdk/web/). Evaluate its UI Toolkit in the disposable proof; choose compact custom controls over the SDK if the toolkit cannot fit the interview layout. Do not implement video transport. Pin a verified supported SDK version after the proof. No production purchase or paid test is implied by this document.

## Screens and behavior

| Screen | Layout and primary action |
| --- | --- |
| Workspace | Meetings list with date, customer and Ready / Live / Report status. New meeting opens preparation. |
| Prepare | Title, objective, customer context, hypotheses, participant names and roles. Start interview and Copy guest link. Preserve the detailed brief. |
| Guest prejoin | Explore logo, meeting title, name, device preview/selectors, camera toggle and clear transcription/AI notice. Request to join; no workspace navigation. Permission requested only when testing devices/joining. |
| Host prejoin | Same device check plus guest admission and interviewer role mapping. Only an authorized host can start the provider session. |
| Live interview | Slim collapsible workspace sidebar; header with title, elapsed time and capture status. Four compact video tiles above transcript and question queue. Persistent mute, camera, devices, leave controls; End interview is host-only. |
| Overview | Workflow cards contain steps, associated gaps and automation hypotheses, each linked to evidence. Unassigned findings are separate. |
| Notes / Brief | Human notes and structured AI notes are clearly distinguished. Opening these tabs preserves call audio/video and local drafts. |
| Report | Generating / Ready / Failed state; participant roles first, summary and existing standard sections. Workflow diagrams, evidence links, Markdown/JSON download and Print / Save as PDF. |

Guest in-call screen contains video tiles, device controls and capture status only. Guests who leave see a simple meeting-ended/left screen. Internal report access is not shared automatically. Guest notice acknowledgement is stored with version/time; do not begin transcription before admitted participants acknowledge it. Admit later participants only after acknowledgement too.

Question queue retains suggested, asked and answered items. Show counts, not a misleading percentage of interview completeness. Example follow-up: “What happened between receiving that transaction request and starting it six hours later?” Clicking its evidence opens and highlights the exact transcript revision. Manual status remains authoritative. Incoming questions do not jump ahead of an item the interviewer is reading.

At widths below 1100 px collapse workspace navigation and show transcript/questions as sub-tabs; below 700 px use an active-speaker tile with a participant drawer. Keep call controls reachable and focused content stable. The initial cofounder release targets desktop; guest browser/device support must pass the SDK compatibility rehearsal before promising it.

## Visual system

See [live interview concept](mockups/video-interview.svg). Synthetic content and camera placeholders; this is a static design, not a working call.

- White content, #F6F7F9 navigation, #17191C primary text, visible neutral borders; 8 px spacing scale and modest 8–12 px radii.
- System font, 14–16 px body, restrained headings. Dark primary buttons; blue workflow, amber gap and purple hypothesis labels accompanied by words.
- Logo is an outlined circle with a centered solid dot, implemented once as SVG.
- Shared buttons, fields, dialogs, tabs, participant tiles, status indicators and evidence links. Reuse React/Vite/CSS/Lucide; no heavy application framework.
- Lazy-load Zoom on prejoin and Mermaid on report/overview. The earlier ≤100 kB gzip app-shell budget excludes those measured, separate chunks; show a useful loading state while media initializes.
- Complete keyboard/focus, accessible names, contrast, reduced-motion, empty/error and reconnect states. No auto-scroll while reading older evidence; expose Jump to live.

## Module boundaries

| Component | Owns |
| --- | --- |
| Conference adapter | Join/leave, devices, participant events and media rendering; no analysis or database access. |
| Meeting access service | Authenticated host/cofounder membership, expiring guest invites, admission and short-lived provider join credentials. |
| Provider session coordinator | One active provider session per transcript run, host lifecycle and stream ownership. |
| RTMS source adapter | Verified provider events, transcript normalization, timestamps, speaker mapping, deduplication and gap reporting. |
| Existing ingestion / analysis | Accepted transcript revisions, context batching, Gemini proposals, validation and shared persistent state. |
| Existing report pipeline | Drain accepted evidence, create immutable report, expose authorized exports. |

Browser media travels through Zoom; transcript events arrive server-side from RTMS. Cofounder updates come from Explore. Clients never submit arbitrary provider session names or select host privileges when obtaining tokens. SDK secrets, RTMS credentials and Gemini keys stay server-side. Prefer the documented Python integration where sufficient; assess any official SDK sidecar only during the proof, before changing hosting architecture.

## Data changes

Add versioned migrations; preserve existing meeting IDs, transcript runs, participant mappings and human notes.

- `conference_sessions`: internal ID, meeting/run foreign keys, provider, opaque unique provider session identity, lifecycle state and timestamps. Provider reconnect IDs map to this session, not a new meeting.
- `meeting_invites`: meeting scope, hashed random token, expiry, revocation and allowed guest capacity. Exchange URL token for a restricted session, remove it from the address bar and prevent referrer/log exposure. No permanent guest workspace membership.
- `conference_participants`: internal participant ID, conference scope, authenticated user or admitted guest identity, verified provider participant mappings, role and join/leave times. Display names alone never identify a person; reconnect mappings must be verified.
- Capture acknowledgements and ingestion interruptions tied to session/participant. Keep accepted transcript text in existing revision storage; do not duplicate it into conference tables.
- Persist budget usage/reservations independently of resettable test sessions. A call-count limit or free-credit display is not a monetary hard cap.

## Lifecycle and failure handling

Prepared → joining → live → ending → finalizing → complete. Media and analysis health are separate status values. A reconnect or individual Leave does not end the interview. Explicit host End closes admission, stops capture/media, drains trailing accepted source events with a bounded deadline, seals ingestion and finalizes once. Define/test that source-drain boundary before wiring the existing stop endpoint, which currently rejects events after stop.

Analysis failure preserves capture and human notes. RTMS interruption shows a visible gap and never silently publishes a complete report. Host disconnection gets a bounded reconnect grace period; use provider events and a server-side watchdog so orphaned sessions cannot stream indefinitely. End commands, webhooks and finalization must be idempotent. Backend restart reconciles provider sessions and reports interruption rather than assuming an in-memory worker survived.

Budget enforcement precedes paid usage: one active interview, maximum duration, server-side ledger, conservative reservations and stop-before-limit margin, with no automatic paid fallback. Reconcile with provider metering; provider rounding/delay means an application estimate alone cannot promise an exact invoice ceiling. Confirm provider-side controls before making that guarantee.

## Build sequence and acceptance

1. Account/SDK proof: two-device call, attributed transcripts, measured latency and observed credit consumption. Decide actual provider dependencies and resource requirements.
2. Light UI and guest/host flows against a fake conference adapter. Verify evidence selection, stable question history, notes, admission states and responsive layouts. Keep replay available for deterministic testing.
3. Auth, guest isolation, migrations and real Video SDK/RTMS adapter. Test invalid/revoked invites, token privilege escalation, duplicate/out-of-order events, reconnect identity and stop/drain races.
4. Report interface and exports with diagrams; test failure/retry and exact evidence coverage. Standard report schema stays in [meeting-reports.md](meeting-reports.md).
5. Private hosted rehearsal with four participants for 60 minutes; verify restart recovery, backup restore, browser/device compatibility and bounded spending before customers. Keep the one-instance architecture only if the SDK/RTMS proof fits it.

Open decisions: first interview date; whether browser Print / Save as PDF is sufficient or a direct PDF download is required. First pilot proposes no screen sharing, recording retention or automatic guest report delivery; add these only when needed.
