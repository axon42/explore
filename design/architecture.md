# Explore — design decisions

## Structure
- Workspace → meetings → transcript sessions. A meeting retains identity and context when its test run is reset.
- SQLite repositories own transactions; API routes coordinate lifecycle; the analysis provider implements a small `Analyzer` interface. Future agent logic can reuse the same persisted sources.
- Briefs, notes and transcript revisions remain separate from derived questions/findings. Exact evidence links and immutable analysis input/output provide provenance.
- Optimistic revisions prevent silent overwrites from another tab. Reset stops work before transactional deletion; a fresh session ID rejects old producer traffic.

## Interface
- Dark theme with conventional sidebar, meeting tabs, forms and confirmation dialogs. The app is **Explore**.
- Interview: transcript, retained questions, status controls, replay and injection.
- Overview: source-linked workflows (blue), gaps (amber), automation hypotheses (purple). Labels accompany color.
- Brief and Notes: persistent meeting context. Asked/answered status is manual for now; questions link to the evidence behind the suggestion.
- Removed static sample workspaces, preview labels, decorative copy and the old single-session interface. Empty states now reflect actual data.
- Sequential 800 ms polling keeps the initial integration simple; existing WebSockets remain available. Selection stays in the browser; meeting data stays in SQLite.

## Deferred
Cross-meeting agents/context brain, embeddings, automatic answer detection, auth/remote access and audio integrations. Gemini passed a real synthetic integration check. Default repository configuration remains mock; the local ignored `.env` enables Gemini.

[Data model](../docs/data-model.md) · [Pipeline](../docs/pipeline.md)

## Analysis and reports
[Live analysis](live-analysis.md) now has replaceable batching, context, reasoning, validation and
formatting components with durable meeting memory. The [report design](meeting-reports.md) is
implemented through backend APIs for participant mappings, full transcript exports, shared generated
note sections, immutable final reports and evidence-backed Mermaid source. Existing UI is preserved;
dedicated controls and real Gemini evaluation remain separate work.

[Implementation/API reference](../docs/analysis.md) · [Coding agent rules](../AGENTS.md)

## Follow-up after Gemini connection verification
- Group overview gaps and automation hypotheses under their related workflows, with explicit
  relationships in the analysis data instead of relying on adjacent cards or color alone.
- Revisit the theme toward the user's requested higher-contrast, lighter Gumloop-inspired appearance.
  No theme/layout work in the API integration step.
