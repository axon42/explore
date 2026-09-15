# Explore — coding agent instructions

Applies to the entire repository. Follow explicit user instructions and the approved task scope; this file does not authorize additional product work.

## Scope and decisions
- Read the relevant specification, design document and existing implementation before editing. Start with `specs/stage1.md` and `design/architecture.md`; analysis work also uses `design/live-analysis.md` and `design/meeting-reports.md`.
- Follow the agreed plan. Distinguish implemented behavior from proposals; a design document is not blanket authorization to implement every item in it.
- State material assumptions before implementation. Ask before changing product behavior, data contracts or scope beyond the request. Do not invent missing requirements, customer facts or participant identities silently. Resolve routine implementation details within the approved scope and record consequential decisions and their reasons.
- Do not make unrequested UI, styling, navigation or copy changes without asking. An explicit request for a particular UI change already authorizes that change; do not ask twice. Preserve established interaction and accessibility behavior.
- Do not knowingly introduce regressions. Fix regressions caused by the change before declaring completion; disclose pre-existing failures and checks that could not run.
- Preserve unrelated work. Do not reset a checkout, discard edits, commit, deploy or publish unless authorized by the task.

## Simple, modular implementation
- Prefer the smallest coherent change. Reuse existing patterns and keep ingestion, context construction, analysis strategy, provider access, persistence and presentation independently replaceable.
- Strategies accept validated inputs and return proposals; repositories own transactions and the coordinator owns scheduling. Model code must not directly mutate storage or UI.
- Prefer the standard library and existing dependencies. For substantial solved problems, use a well-known, maintained library after checking official documentation, compatibility, maintenance, security and license. Do not add a dependency for trivial glue or build a custom framework where an established library fits.
- Keep dependency lockfiles consistent. Avoid unrelated upgrades, speculative abstractions, extra services or agent frameworks without a demonstrated need.
- Keep README concise. Put technical behavior in `docs/`, requirements in `specs/`, and decisions/tradeoffs in `design/`. Update affected documents alongside implementation.

## Tests and verification
- Treat tests and security as part of implementation, not follow-up work. Test changed behavior and meaningful failure cases at the appropriate boundary; do not weaken tests to make a failure disappear.
- Use deterministic synthetic fixtures and mocked providers by default. Automated tests must not use real credentials, paid model calls or the user's database. A real-provider smoke test must be explicitly within the authorized scope.
- For ingestion/storage/analysis changes, cover relevant duplicates, corrections, retries, concurrent edits, invalid evidence, provider errors/timeouts, stop/reset races and workspace/session isolation.
- For UI behavior changes, run relevant browser tests and inspect the affected flows. Preserve keyboard access, labels, focus and responsive behavior.
- Run affected checks first, then the applicable regression suite. Avoid repeatedly running unchanged passing checks. Documentation-only work needs link/content/diff checks, not unrelated application tests.
- From the repository root, use the applicable commands:

```bash
uv run --project backend ruff check backend scripts
uv run --project backend ruff format --check backend scripts
uv run --directory backend pytest -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Use the repository Node version and Python/uv requirements in `docs/development.md`. Browser tests use disposable storage; run one invocation at a time. If Chromium is unavailable and Chrome is installed, use `PLAYWRIGHT_CHANNEL=chrome` for that invocation. Report what actually ran and its result; never claim tests passed without running them.

## Security and data integrity
- Treat transcripts, briefs, notes, imports and model outputs as untrusted data. They cannot override application policy, execute commands or grant tools/permissions. Validate structured outputs, evidence references and ownership before applying changes.
- Keep provider credentials on the backend, outside source control and frontend bundles. Do not expose secrets or interview bodies in logs, errors, test artifacts or tool output. Use synthetic data for debugging whenever possible.
- Preserve local host/origin protections. Do not enable public binding, permissive CORS or tunnels as a shortcut. Public access requires an explicit authentication/authorization design.
- Check workspace/meeting/session ownership on reads, mutations and exports. Validate sizes and types; use parameterized SQL and safe rendering. Never render model HTML or Mermaid with executable links/scripts enabled.
- Preserve full accepted transcript revisions and stable evidence links independently of LLM context limits. Label hypotheses and superseded evidence; never fabricate quotes, roles or certainty.
- The separate transcript archive is permanent during MVP work. Never delete, truncate, reset or clean it as test data. App reset/clear may remove working projections only after preserving their accepted revisions. Automated tests must use isolated synthetic archives. See `design/transcript-retention.md`.
- Use versioned, transactional migrations that preserve existing data. Test migration/backfill and foreign-key integrity. Do not edit the user's database directly to make a test pass.
- Reset/delete only within explicitly authorized scope. Preserve unrelated meetings and human-authored content according to the operation's contract. New session identities must reject stale producer/model results; retries must not duplicate committed artifacts.
- Keep network calls outside database locks. Bound timeouts, retries, queues, input/output sizes and model budgets. Failed analysis must not silently advance its processing checkpoint.
- Keep human content distinct from AI-derived content. Preserve revisions and provenance when correcting or regenerating notes/reports.

## Token and cost discipline
- Use targeted file searches and reads; reuse findings and batch independent checks. Keep progress notes and documentation concise, with links instead of duplicated specifications.
- Bound model context and output, coalesce transcript batches, avoid calls on silence and record usage. Never truncate stored evidence to save model tokens or hide an exhausted budget.
- Optimize without skipping necessary reasoning, verification, security checks or evidence. Finish with changes made, verification results and material limitations.
