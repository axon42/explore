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

Use **Report** to end the interview and download Markdown/JSON reports or the full transcript.
**Reset test** returns a test meeting to Draft, clearing transcript, analysis and reports while keeping participants, brief and notes.
**Workspace actions → Archive all meetings** moves meetings to **Archives**, where you can search, restore or permanently delete working records. Workspaces can also be archived.

Reset and permanent deletion preserve the separate [transcript archive](docs/transcript-archive.md) for later evaluation.

- [Roadmap](docs/roadmap.md)
- [Data model and migration](docs/data-model.md)
- [Pipeline and provider setup](docs/pipeline.md)
- [Development](docs/development.md)
- [Developer tools and model debugging](docs/developer-tools.md)
- [Design decisions](design/architecture.md)

The app runs locally in a browser, with optional macOS audio capture. Hosted team sharing and market research are planned.
