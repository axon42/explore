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

Open http://127.0.0.1:5173. Create a workspace and meeting, fill in the brief, then play or step through the interview. Data is saved in local SQLite.

Analysis defaults to **simulated** responses with no API calls. To enable Gemini, copy `.env.example`
to `.env`, set `ANALYSIS_PROVIDER=gemini` and `GEMINI_API_KEY`, then restart.
Gemini receives the delivered transcript and bounded meeting context. Automated tests use simulated analysis.

Use **Report** to end the interview and download Markdown/JSON reports or the full transcript.
**Reset test** clears transcript, analysis and reports while retaining the brief, participants and notes.
**Clear meetings** deletes meetings and their data in the selected workspace.

- [Data model and migration](docs/data-model.md)
- [Pipeline and provider setup](docs/pipeline.md)
- [Development](docs/development.md)
- [Design decisions](design/architecture.md)

The app runs locally in a browser. Remote sharing, audio integrations and cross-meeting agents are future work.
