# Explore

Customer-discovery interviews, organized by workspace. Replay a test interview or inject text,
collect follow-up questions, inspect evidence, and download meeting reports.

## Run

Install Node.js 22.12+ and uv (Python 3.12+), then:

```sh
uv sync --project backend --locked
npm ci --prefix frontend
uv run --project backend python scripts/dev.py
```

Open http://127.0.0.1:5173. Create a meeting, save participants and a brief, then **Start interview**.
For replay, enable **Test mode** in the bottom left, add sample participants and start a test meeting.

Analysis defaults to **simulated** responses with no API calls. To enable Gemini, copy `.env.example`
to `.env`, set `ANALYSIS_PROVIDER=gemini` and `GEMINI_API_KEY`, then restart.
Gemini receives the delivered transcript and bounded meeting context. Automated tests use simulated analysis.

Ending a meeting runs a full-transcript final review, even if live analysis failed. For past ended
meetings, use **Report → Run final review**. Download versioned Markdown/JSON reports or the full
transcript there. Provider and budget limits still apply; failures preserve the last valid report.
**Reset test** returns a test meeting to Draft, clearing transcript, analysis and reports while keeping participants, brief and notes.
**Workspace actions → Archive all meetings** moves meetings to **Archives**, where you can search, restore or permanently delete working records. Workspaces can also be archived.

Reset and permanent deletion preserve the separate [transcript archive](docs/transcript-archive.md) for later evaluation.

## Documentation

Specifications describe requirements; design documents record decisions and proposals; `docs/`
contains operating and implementation references. Each document identifies its implementation status.

### Product and delivery
- [Roadmap](docs/roadmap.md) · [Stage 1 requirements](specs/stage1.md) · [Architecture](design/architecture.md)
- [Interview readiness](design/interview-readiness.md) · [Release plan](design/interview-ready-release.md)
- [Accounts and workspaces](design/accounts-and-workspaces.md) · [Archives and question history](design/archives-and-question-history.md)
- [Market research plan](design/market-scan.md)

### Analysis, evidence and reports
- [Analysis APIs and behavior](docs/analysis.md) · [Pipeline and provider setup](docs/pipeline.md)
- [Live analysis](design/live-analysis.md) · [Manual full-transcript review](design/context-rebuild.md)
- [Final review and meeting reports](design/meeting-reports.md) · [Topic memory](design/topic-memory.md)
- [Model selection](design/model-selection.md) · [Reliability plan](design/analysis-reliability.md) · [Latency plan](design/analysis-latency.md)
- [Speaker attribution](design/speaker-attribution.md) · [Topic evaluation](docs/topic-memory-evaluation.md) · [Synthetic interview checkpoints](backend/fixtures/discovery-v1.checkpoints.md)

### Data and development
- [Data model and migrations](docs/data-model.md) · [Transcript retention design](design/transcript-retention.md) · [Transcript archive operations](docs/transcript-archive.md)
- [Development and tests](docs/development.md) · [Developer tools](docs/developer-tools.md) · [Observability design](design/observability.md)
- [Coding agent instructions](AGENTS.md)

### Audio and meeting integrations
- [macOS capture setup](docs/macos-capture.md) · [macOS capture design](design/macos-audio-capture.md)
- [Zoom setup](docs/zoom-setup.md) · [Zoom desktop integration](design/zoom-meetings.md) · [Video SDK design](design/zoom-video-interviews.md) · [Video interview mockup](design/mockups/video-interview.svg)

### Interface and website
- [UI foundations](design/ui.md) · [UI refinement](design/ui-refinement.md) · [UI preview](design/ui-preview.md)
- [Sidebar](design/sidebar.md) · [Dropdowns](design/dropdowns.md) · [Product website](design/product-website.md)

The app runs locally in a browser, with optional macOS audio capture. Hosted team sharing and market research are planned.
