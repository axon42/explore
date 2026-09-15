# Explore UI

The main application uses the approved Gumloop-inspired light direction: white content, a pale neutral workspace sidebar, dark primary actions and fine borders. A circle with a solid center dot identifies Explore, including its favicon.

- Keep workspace → meetings navigation and the existing meeting tabs. Transcript and retained questions sit side by side on desktop, with stacked panels on smaller screens.
- Blue evidence highlights connect suggestions to their source. Workflow, gap and opportunity labels accompany their colors; color alone does not imply a relationship.
- Display queued, asked and answered counts. These describe question status, not a percentage of interview completion.
- Use existing React components, CSS and icons; avoid remote fonts and animation libraries. Shared dropdowns use the focused Radix Select primitive for cross-browser menus and keyboard behavior; see [dropdown decisions](dropdowns.md). Preserve focus indicators, form submission, dialogs and reduced-motion behavior.
- Preserve brief, notes, replay, injection and scoped reset behavior. Video controls and workflow relationships require separate integration work. Brief now includes explicit participant mappings; Notes exposes generated sections; Report connects finalization and Markdown/JSON downloads.

Reference: [approved interview layout](mockups/video-interview.svg). The conferencing area remains deferred until its integration is ready.

## Local prototype completion

Reuse the existing report and participant APIs without changing storage contracts or model logic. Poll generated notes only while Notes is mounted, and report status only while Report is mounted. Keep human notes separate from derived sections. Explicit report generation ends ingestion; failed jobs can be retried and outdated immutable revisions remain downloadable. Export Markdown includes editable Mermaid source and textual workflow steps; PDF is deferred. Downloads check HTTP errors before creating a local file. Participant edits retain optimistic revision checks. Tests use synthetic data and mock analysis, never paid calls.


## Live context and report reader

Implemented 2026-09-12, within the requested UI scope.

- A compact panel below the transcript shows stable thread colors plus active/paused/tentative
  labels. Selection follows focus until a viewer chooses a thread; Follow active thread resumes
  tracking. Update numbers and developing/uncertain state communicate analysis progress without
  suggesting that a paused topic is complete. Superseded summaries are withheld.
- Thread polling runs sequentially while Interview is mounted. It uses saved analysis data,
  costs no extra model calls, filters by session and shows refresh failures. Legacy strategy
  and new meetings get honest empty states; previous meetings are not silently reprocessed.
- Report opens the latest immutable revision automatically. Revision selection, retry, outdated
  notices and existing downloads stay available. Participants/roles lead the report; structured
  sections, topic groupings, a question-status chart and a coverage count follow. The chart
  represents saved question statuses, not interview completion or market potential.
- Native HTML workflow cards show source-backed steps and supported transitions. Unknown order
  is dashed and labeled, without an arrow implying sequence. Mermaid remains an export format;
  no general graph engine, HTML parser, chart library or extra provider call is required.
- Report evidence opens an accessible in-page panel using the saved revision's exact text.
  Escape/close restores focus. Contents navigation preserves the meeting URL. Mobile layouts
  stack naturally; empty sections collapse while retaining the common report structure.

Future: [post-meeting market scan](market-scan.md), independently triggered and budgeted.


## Analysis mode
The bottom-left **Analysis mode** row shows the current choice and opens the shared dropdown for
**Standard** and **Discussion threads**. See the approved [sidebar layout](sidebar.md).
The choice is app-wide and saved on the backend, rather than browser-local, so all viewers use
the same mode. It survives restart and meeting reset. Provider credentials and budgets stay
server-controlled. Save errors and conflicts are visible; older polls cannot undo a save.
In-flight analysis keeps its original contract and later batches pick up the selected mode.
On mobile the control stays in the sidebar's stacked settings area. This changes no meeting
navigation and starts no provider call or historical reprocessing by itself.


## Consistency repair and color review
The [refinement plan](ui-refinement.md) inventories existing controls. The capture popup uses the shared centered,
height-bounded dialog. Checkbox inputs are excluded from full-width text-input rules, errors
remain visible inside capture consent, dialogs have accessible names, and pending form inputs
are disabled to avoid losing edits. The isolated `/ui-preview.html` demonstrates both palettes.

## Approved color rollout — 2026-09-12
The blue + sage [UI refinement](ui-refinement.md) is now applied to the connected app. Shared
CSS tokens keep actions/workflows blue, live observations sage, AI suggestions violet and
gaps amber. Labels and evidence remain authoritative. Question frequency is next to questions;
forms, dialogs, notes and reports share the same visual treatment. No data contract, provider
logic or dependency changed. The static mock remains a reference, not the app entry point.
