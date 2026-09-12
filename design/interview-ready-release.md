# Interview-ready release — proposed plan

2026-09-11. Planning only; no UI changes or deployment yet. Analysis accuracy remains Stage 2 work.
Build on [analysis](live-analysis.md) and [reports](meeting-reports.md), keeping the existing evidence and reset contracts.

The [Video SDK and UI design](zoom-video-interviews.md) now details the proposed Explore-hosted call,
guest access, lifecycle, data changes and visual concept. Its account proof comes first; microphone
testing below remains an optional diagnostic rather than a required separate integration.

## 1. Light, fast interface

Use [Gumloop's public UI](https://www.gumloop.com/) as visual direction: white surfaces, pale neutral sidebar, dark text/buttons, fine borders and restrained accent colors. Preserve workspace → meetings, question history/status and transcript evidence highlighting. Remove repeated explanatory copy and decorative cards; retain useful status and error messages.

- Keep React/Vite, existing CSS/Tailwind and Lucide. Extract only shared primitives needed by current screens: buttons, fields, tabs, dialogs, status badges and evidence links. No new application or component framework.
- Use consistent spacing, typography, focus states and contrast. Complete loading, empty, disconnected, failure and saving states. Keep transcript scroll position stable while new text arrives.
- Interview prioritizes transcript and question queue. Overview groups each workflow with its gaps and automation hypotheses; unassociated findings remain explicitly unassigned. Brief remains the preparation screen; Notes preserves human contributions.
- Add a small SVG logo: outlined circle with a centered solid dot, shared by navigation and favicon.
- Establish measured budgets: initial app JavaScript ≤100 kB gzip, diagrams/export code loaded on demand, local interaction feedback within 100 ms in the rehearsal environment. Measure before optimizing; avoid full transcript rerenders and repeated full-history downloads as sessions grow.

Workflow grouping needs stable workflow references in validated analysis output and persistence, not matching nearby cards or titles. Add optional relationships with a migration; preserve older unassigned findings. Extraction accuracy improvements remain separate.

## 2. Meeting completion and downloads

Backend finalization, immutable reports, Markdown/JSON exports and evidence-backed diagram source already exist. Connect those APIs rather than create a second reporting pipeline.

Meeting end → stop source and flush accepted speech → drain analysis → generate report → show Ready/Failed status → download. Pending or failed analysis must never look complete. Allow retry without duplicate reports; full transcript export remains available if analysis fails.

Use the existing ten report sections, beginning with interviewer names/roles. Expose participant mapping before the meeting. Include human notes, question progress, workflow steps, gaps, hypotheses, uncertainty and exact evidence links. A summary is accompanied by the full transcript; JSON preserves accepted revision history.

Render validated workflows with lazy-loaded Mermaid in strict mode, with textual steps as fallback. Diagrams must appear in printable output, not raw Mermaid code. Keep unknown relationships visibly unknown. Human notes and generated notes retain separate provenance.

Download format is pending user preference. Markdown/JSON can ship using existing APIs. Recommend a printable report with browser Save as PDF first; a direct PDF download is a separate exporter if required. Avoid placing a PDF engine in the live interview bundle. Export saved report revisions without additional LLM calls.

## 3. Microphone test, then Zoom

```text
Replay ───────────────────────────────┐
Browser mic → backend → streaming STT ├→ normalized transcript events
Zoom RTMS transcript adapter ─────────┘    → evidence store → existing analysis → UI/report
```

Start with a microphone test using synthetic dialogue read aloud. Browser capture requires permission and HTTPS (localhost works for development); it captures the selected audio input, not a clean feed of remote Zoom participants. Loudspeaker pickup is not the real-interview ingestion strategy. See [browser capture](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

Propose Deepgram streaming behind a small STT adapter. Keep its key server-side, audio queues bounded and capture explicitly start/stop controlled. Normalize partial/final results, timestamps, stable IDs and corrections into the existing ingestion contract. Persist transcript evidence; do not retain raw audio by default. Mark transport gaps and recoverable disconnects; never invent missing speech. Only one authorized producer owns a session; other cofounders view its results.

Measure end-of-speech → final transcript → batching wait → model response → browser display across at least 20 scripted turns; report median and p95. The earlier 7.3-second model smoke check is one sample, not an end-to-end latency guarantee. Latency instrumentation is in scope; prompt/quality tuning stays in Stage 2.

There are two separate Zoom paths. For an ordinary Zoom Workplace meeting, RTMS requires Developer Pack credits; the current account checkout is routing that plan to Contact sales. That path is therefore a later integration track until Zoom enables it. See [RTMS for meetings](https://developers.zoom.us/docs/rtms/meetings/getting-started/).

The Build Platform trial shown in the account can be used for a different path: Explore creates its own meeting with the Zoom Video SDK, and RTMS can deliver live audio/transcripts from that Video SDK session using Build Platform credits. This is a custom Explore-hosted meeting powered by Zoom, not an adapter for an existing Zoom Workplace meeting. See [RTMS for Video SDK](https://developers.zoom.us/docs/rtms/video-sdk/) and [Video SDK credentials](https://developers.zoom.us/docs/video-sdk/get-credentials/). It is the recommended immediate technical test: three cofounders and the customer join an Explore session, while our transcript adapter and analysis pipeline stay unchanged.

For either path, verify app scopes, host/session ownership, webhook signatures, reconnection and end-of-stream behavior. Use Zoom's transcript directly initially; add Zoom audio → Deepgram only if measured transcript quality/latency justifies its extra cost and complexity. Confirm the Build Platform credit rate and remaining trial balance in the account before a 40–60 minute rehearsal; do not infer hours from the number 20.

## 4. Private hosting

Propose one always-on Render service serving the built frontend and FastAPI under one HTTPS origin, with SQLite on a persistent disk. Keep one application worker/instance: current coordination is in-process. This minimizes moving parts for three cofounders. PostgreSQL and shared job coordination become necessary before horizontal scaling.

Before access outside localhost:

- Add individual sign-in through an established OIDC integration, an explicit cofounder allowlist and workspace membership authorization for HTTP, streams and exports. Use secure sessions and CSRF protection; keep provider credentials server-side.
- Add health checks, redacted operational logs, bounded uploads/connections and visible transcription/analysis failures. Preserve exact origin checks.
- Use transactional migrations and SQLite-consistent off-host backups; test restore and restart recovery. Schedule deployments outside interviews because a disk-backed instance has deployment downtime.
- Rehearse a 60-minute session with three viewers, refresh/reconnect, provider failure and final export before real customers. Keep transcript capture usable when analysis fails.

[Render pricing](https://render.com/pricing) lists Starter compute at $7/month; disk, backup, bandwidth and any upgrades are additional. Reserve approximately $10–15/month for initial hosting, subject to checkout and rehearsal memory measurements. [Persistent disks](https://render.com/docs/disks) require a paid service and prevent multi-instance scaling. This is a pilot architecture, not a high-availability deployment.

## 5. Cost and customer data

Retain the earlier under-$50 budget as a planning constraint; Zoom cost is unresolved. [Deepgram](https://deepgram.com/pricing) currently lists promotional Nova-3 monolingual streaming at $0.0048/minute (about $0.29/hour), excluding add-ons, and advertises introductory credit. Recheck at activation.

Existing Gemini call limits are not a hard dollar cap. Before enabling any paid usage, implement a persistent shared budget ledger with conservative reservations, concurrency-safe enforcement and explicit manual reset; reset/test deletion must not erase spend history. Bound STT duration and concurrent producers too. Never silently fall back to a paid model.

Keep free Gemini testing synthetic. [Gemini's unpaid-service terms](https://ai.google.dev/gemini-api/terms) say not to submit sensitive, confidential or personal information and permit product-improvement use. Choose suitable provider data handling before real interviews; do not enable billing implicitly. Show participants when transcription/AI processing is active and establish consent and retention expectations.

## Delivery order and release checks

1. Light UI and report controls: responsive/keyboard review; preserve evidence links, statuses, notes and reset behavior; verify downloadable full evidence and printable diagrams.
2. Microphone adapter and latency measurement: synthetic audio, permission denial, disconnects, duplicates/corrections and stop/flush tests.
3. Private hosted rehearsal: authentication/isolation, backup restore, three viewers, 60-minute capture and report completion. Check Zoom feasibility early so it does not surprise the release schedule.
4. Zoom adapter and a cofounder rehearsal before customer interviews: remote speech and speaker mapping verified, no hidden gaps, acceptable measured latency and confirmed cost.

Open scheduling decisions: first interview date, separate-computer access needs, preferred report download format. No hosting purchase, billing change or deployment is authorized by this plan alone.
