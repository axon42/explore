# Explore roadmap

Updated 2026-09-15. Sequenced work, not a delivery-date commitment. New items below are
tracked below with implementation status. Market research stays later; a reliable interview comes first.

| Order | Work | Exit criterion |
| --- | --- | --- |
| Now · P0 | Transcript quality and readability | Mac capture is confirmed working; improve transcription/utterance grouping and speaker attribution, and move correction controls outside transcript prose |
| Next · P1 | Meeting preparation and Test mode | Real start requires named interviewer + customer; replay/injection appear only in explicit Test mode; ending an interview is always available |
| P2 | Live analysis quality and durable processing | Evaluate capture/utterance boundaries, topic switches, evidence and duplicates; durable jobs with commit acknowledgement, bounded retries and visible coverage/budgets |
| P2a · implemented, rehearsal pending | Speaker separation and confirmed person/role mapping | Separate remote voices; interviewer confirms identities; unknown and founder speech cannot become confirmed customer evidence; corrections preserve transcript/report history |
| P3 | Profiles, personal/team spaces, invitations | One login; private personal space; team admin/member access; invitation acceptance and isolation tests pass |
| P4 | Private hosted pilot | Authenticated HTTPS, backups/restore, safe capture pairing, durable jobs and per-account budgets; verified 40–60 minute rehearsal before customer use |
| P5 | Public website | Approve artistic landing + product direction; connect only implemented CTAs and accurate availability claims |
| Later · P5a | Post-meeting AI review | Review the full saved transcript in bounded passes; propose evidence-backed corrections to generated notes/reports as a new revision; preserve source text and human content |
| Later · P6 | Post-meeting market research | Reviewed research brief, explicit budget, dated citations, competitor table and saved revisions; manual trigger only |
| Later | Browser/Zoom integrations and cross-meeting research | Reuse ingestion/evidence contracts; pursue after the core interview experience is reliable |

Website design can proceed alongside P0; a polished mock does not make the product ready to launch.
Typical meetings are 45 minutes. Mac capture is confirmed working by the user on 2026-09-15 and runs until manually stopped. Transcription accuracy and downstream analysis remain separate quality work.

## Current baseline
Transcript preservation is now a prerequisite for today's meeting: a separate append-only archive,
atomic writes/backfill and offline export/backup are implemented. Reset/permanent working deletion retain evidence; Clear meetings now archives without deleting.
See [retention design](../design/transcript-retention.md). Speaker separation and human confirmation are implemented locally; real accuracy remains unverified.

Implemented: local browser UI, workspaces/meetings, replay/injection, Mac capture adapter,
Deepgram/Gemini adapters, topic memory, question pacing and discard, saved transcript evidence,
briefs/notes, report reader/exports, meeting archive, blue + sage UI.

Not implemented: authentication, user profiles, team membership, invitations, persistent
transcription spend ceiling, market research. Draft/start and Test mode are implemented.
Mac capture is user-confirmed working. Current investigation concerns transcript quality, speaker attribution and downstream analysis.

## Decisions confirmed
- Real interviews require at least one named interviewer and one named customer.
- Solo microphone testing belongs in Test mode.
- Team access begins with admin invitations only.
- Keep the local Firefox origin at `http://127.0.0.1:5173`.
- Keep market research separate from meeting evidence and live-analysis spend.

## Plans and acceptance checks
- [Capture audit, preparation and Test mode](../design/interview-readiness.md)
- [Speaker separation and confirmed attribution](../design/speaker-attribution.md) — implemented locally; rehearsal/evaluation pending
- [Profiles and team access](../design/accounts-and-workspaces.md)
- [Website concept](../design/product-website.md)
- [Live analysis](../design/live-analysis.md) · [Topic memory](../design/topic-memory.md)
- [Market scan](../design/market-scan.md) · [Observability](../design/observability.md)

Each slice preserves stored transcripts, human notes, report revisions and existing cost safeguards.
P0 now targets the reported transcript quality/readability issues; P2 needs durable processing and a real-provider quality benchmark.

## This implementation
- P0: durable capture counters, microphone starvation detection and device-change errors;
  continuous PCM self-test. The user confirms Mac capture is working; transcription accuracy remains to be evaluated.
- P1: new meetings are drafts; named participants and an explicit start are required.
  Test mode controls replay/injection/reset, with immutable session mode and source isolation.
- P2: explicit workflow associations and grouped findings; synthetic readiness/evidence
  regression cases. Real-provider quality comparison remains open; tests do not measure Gemini comprehension.
- Sidebar title search and the expanded public product tour are included.
- **Meeting tags — planned:** workspace-scoped labels, add/remove on a meeting and sidebar
  filtering. Decide team editing permissions alongside membership; no tags implemented yet.

Next: improve transcript quality, analysis reliability and speaker separation,
then P3/P4 for the cofounder pilot. The invitation flow
is create account → admin invite → verified acceptance → shared team workspace and meetings.
Keep Gemini for now. ChatGPT Pro does not include API credits; any OpenAI adapter or market
scan needs separately configured API billing and its own enforced budget.

### P2a implementation — 2026-09-14
New capture setup selects a microphone participant or shared/unknown. Remote/shared streams use
Deepgram diarization; the Speakers panel confirms identities and supports passage corrections.
Participant IDs, revisioned rosters, source spans and attribution audit rows are isolated by session
and meeting. Corrections invalidate stale AI context and report status while preserving source text,
human question status and permanent transcript history. Internal speaker IDs are hidden from the roster.

Next release gate: resolve the reported transcript/analysis issues and evaluate three-person speaker attribution on the existing Firefox origin.
Then profiles/team invitations (P3), followed by hosted pairing, backups and budgets (P4).
No account or hosting work is included in this local attribution slice.

### Organization and question review — implemented locally
- Clear meetings archives the current workspace's meetings; Archives provides name search,
  workspace/type filters, restore and confirmed permanent working-record deletion.
- Workspace archive/restore preserves its meetings and individual archive choices.
- Spoken questions are detected separately from suggestions, with exact revision-bound evidence,
  confirmed roles where available, correction history and report/JSON export inclusion.
- Next: benchmark detection against manually labeled interviews, including omitted questions,
  fragment boundaries and attribution. Historical backfill and strategy scoring are not implemented.
See [design and limitations](../design/archives-and-question-history.md).

### Developer diagnostics — implemented locally
- Locked Developer view: timing, request IDs, timeout stages, validation outcomes, token usage,
  optional request/response bodies and safe rotating application logs.
- Timeout retries use smaller subsequent batches without advancing failed checkpoints or bypassing caps.
- Access uses a private local owner key for this MVP. User profiles, account-admin roles and invitations
  are still P3; replace the local gate before hosting. Full tracing/support export remains later work.
- Real-provider latency/quality evaluation remains required; old errors have no retroactive bodies.
See [Developer tools](developer-tools.md).


### Meeting reliability follow-up — planned, 2026-09-15
The reported real meeting exposed fragmentation, intrusive speaker-correction controls, limited topic
coverage and exhausted analysis attempts. These are not declared fixed by the planning work.
See [reliability design](../design/analysis-reliability.md).

1. **P0/P2 diagnostics:** Workspace → meeting → session → job → attempts; inspect exact redacted
   provider requests/responses when admin recording was enabled. Separate global operational logs.
   Show captured/analyzed coverage and budget exhaustion before tuning topic prompts.
2. **P0 transcription/display:** Preserve end-of-speech metadata, evaluate utterance assembly and diarization,
   and evaluate recognition. Correction actions now use a separate passage picker; precise correction remains available.
3. **P2 processing:** Durable SQLite job queue, transactional ACK, leases, idempotent commits,
   bounded retries/backoff, coalesced pending work, visible backlog and independent analysis cadence.
   Do not silently increase the current call limit or introduce unlimited retries.
4. **P2 quality:** Labeled multi-topic replay and speaker/word accuracy evaluation; evidence-based
   model/prompt comparisons. Distinguish missing analysis coverage from incorrect routing.
5. **P2 manual analysis — implemented locally:** New meetings use **Analyze now**: one full-transcript
   attempt per click, durable receipts, visible coverage and unchanged call/timeout safeguards.
   Existing meetings retain Automatic until changed. No hidden live calls/retries in Manual mode; explicit meeting end runs final review.
   Full-request input/output bounds are explicit; real-model quality and latency rehearsal remains open.
   See [design](../design/context-rebuild.md).
6. **Test-mode dashboard:** Always-visible Deepgram and Gemini health/usage metrics for the selected
   meeting; exact model bodies remain admin-only. Measured/estimated/unknown values are distinct.
7. **Post-meeting review — implemented locally:** One full-transcript review on explicit end or
   from Report for past meetings, followed by an immutable report revision. Preserves original
   transcript and human content. Review diffs and independent multi-pass verification remain later.
   See [design](../design/meeting-reports.md).

Prioritize these reliability gates before inviting the cofounder to a hosted pilot. Profiles,
invitations, meeting tags, public website and market research remain on the roadmap.

### Provider comparison — 2026-09-15
Local model selection and OpenAI Responses integration are implemented; Gemini stays selected.
Two synthetic Gemini quality checks passed, including fragmented speech. Real OpenAI verification
and meeting-scale quality evaluation remain pending. No automatic fallback or market research added.

## Next: manual analysis latency and lifecycle — planned 2026-09-16
[Latency plan](../design/analysis-latency.md): measure phases, shorten output while retaining full
transcript input, evaluate reasoning settings, then improve progress feedback. Separate meeting
completion from capture/server lifecycle before the next real interview. No implementation yet.
