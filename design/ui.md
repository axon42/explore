# Explore UI

The main application uses the approved Gumloop-inspired light direction: white content, a pale neutral workspace sidebar, dark primary actions and fine borders. A circle with a solid center dot identifies Explore, including its favicon.

- Keep workspace → meetings navigation and four meeting tabs. Transcript and retained questions sit side by side on desktop, with stacked panels on smaller screens.
- Blue evidence highlights connect suggestions to their source. Workflow, gap and opportunity labels accompany their colors; color alone does not imply a relationship.
- Display queued, asked and answered counts. These describe question status, not a percentage of interview completion.
- Use existing React components, CSS and icons without new dependencies, remote fonts or animation libraries. Preserve focus indicators, native forms, dialogs and reduced-motion behavior.
- Preserve brief, notes, replay, injection and scoped reset behavior. Video controls and workflow relationships require separate integration work. Brief now includes explicit participant mappings; Notes exposes generated sections; Report connects finalization and Markdown/JSON downloads.

Reference: [approved interview layout](mockups/video-interview.svg). The conferencing area remains deferred until its integration is ready.

## Local prototype completion

Reuse the existing report and participant APIs without changing storage contracts or model logic. Poll generated notes only while Notes is mounted, and report status only while Report is mounted. Keep human notes separate from derived sections. Explicit report generation ends ingestion; failed jobs can be retried and outdated immutable revisions remain downloadable. Export Markdown includes editable Mermaid source and textual workflow steps; an in-browser diagram renderer and PDF are deferred. Downloads check HTTP errors before creating a local file. Participant edits retain optimistic revision checks. Tests use synthetic data and mock analysis, never paid calls.
