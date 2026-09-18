# Meeting records and final reports — design

2026-09-11. Backend APIs now implement transcript exports, shared generated-note/report sections,
human participant mappings, immutable final reports and Mermaid source generation. See
[implementation reference](../docs/analysis.md). Existing human-note bodies and UI are preserved.

## Durable evidence
Retain the entire transcript received and accepted by Explore, including provisional text, final text and accepted corrections, with speaker IDs, timestamps and exact revision references. Duplicate/rejected deliveries are not additional spoken content. A bounded LLM context never bounds storage retention. Unreceived speech cannot be recovered; any known ingestion gaps must be disclosed.

Current storage retains accepted segment revisions; older legacy revisions discarded before migration cannot be reconstructed. As of 2026-09-14, [the independent transcript archive](transcript-retention.md) also retains accepted revisions through test reset/permanent working deletion. Clear meetings now archives and preserves working records. Ordinary stop or report generation never deletes evidence.

Provide two transcript exports: readable Markdown with speaker/time labels, and versioned JSON containing current segments, accepted revision history, participant mappings and stable evidence IDs. Include meeting/session identity and export/source versions so external processing can trace quotations. Clearly distinguish provisional, current and superseded text. Exports are user-initiated and scoped to the selected meeting; no external upload is implied.

## Shared structure
Use one versioned section schema for meeting notes and final reports. Keep the same ordering across meetings, using “Not established” for missing information. Live AI notes fill it incrementally; a final report completes it through the closing transcript checkpoint. Human notes may remain free-form within those sections and retain their authorship/revision history. Do not rewrite or reclassify existing notes without a deliberate migration and reviewable mapping.

1. **People and meeting:** interviewer name(s), interview role and job role first; customer/other participants and roles, workspace, title, date and duration. Store stable participant-to-speaker mappings. The implemented [speaker attribution layer](speaker-attribution.md) requires human confirmation of person/role mappings; self-introductions are supporting text, not automatic confirmation. Do not infer a job role from speaking style. Allow unknown speakers until identified. Reports retain their attribution version and become outdated when relevant mappings change.
2. **Purpose:** interview objective, customer/vertical context and hypotheses from the brief, labeled as pre-meeting input.
3. **Discussion summary:** concise account of what was learned, without promoting hypotheses to findings.
4. **Workflows:** trigger, actor, steps, tools, handoffs, decisions and outcome; include supported frequency/timing and diagrams where useful.
5. **Pain and impact:** concrete incidents, frequency, effort, delays, cost and consequences, distinguishing stated facts from estimates.
6. **Current alternatives:** tools, workarounds, spending and previous attempts to solve the issue.
7. **Opportunities and uncertainty:** automation hypotheses, supporting/contradicting evidence, unknowns and further validation needed. Interest is not purchase commitment.
8. **Question progress:** retained questions, asked/answered status, answer evidence, dismissed/covered items and unresolved topics. Status respects the chosen human-confirmation policy.
9. **Questions asked in conversation:** detected verbatim questions, exact source evidence, confirmed speaker/role where available and earlier-revision labels.
10. **Next steps:** explicit commitments with owner/date when stated; AI-recommended follow-ups labeled separately. No invented owners or dates.
11. **Evidence and human notes:** source-linked details/quotes, original human contributions and transcript export references. Include coverage, report revision and generation provenance.

The report begins with participant details and a concise summary, followed by the structured detail. “All details” means preserving substantive evidence and access to the complete transcript, not claiming that a prose summary reproduces every utterance.

## Report lifecycle
- Separate replay pause, transcript-source closure and meeting finalization. A pause does not create a final report. On meeting end, close ingestion and capture its final accepted cursor, review the full transcript, then schedule report generation once.
- The stop path cancels live analysis, then schedules a separate finalization worker to review all finals plus accumulated AI memory before reporting. Reset/clear cancel work without starting finalization.
- Build from structured state plus source passages. Check coverage across the entire accepted transcript; if some dialogue was never analyzed, include it in the single full-input review before synthesis. Never generate a “complete” report solely from the last context window.
- Record pending/generating/complete/failed state and covered cursor. Retries are idempotent. On provider failure or incomplete coverage, preserve data and show that completion failed or is partial, rather than publishing a misleading final report.
- Save immutable report revisions with schema, source/context versions, model/prompt identity, usage and evidence references. Later corrections or human-context changes mark the report outdated; regeneration creates a new revision while preserving the old one. Keep human edits separate from generated revisions.
- Reset invalidates in-flight report jobs using the session identity, just as it does live analysis. No stale result may repopulate deleted data.

## Workflow diagrams
Store workflow structure separately from rendered Mermaid: nodes for actors/actions/decisions and edges for sequence/handoffs, each with supporting evidence or an explicit unknown/inferred marker. Derive Mermaid from this validated structure so rendering can change independently of analysis. Prefer deterministic IDs and escaped labels over arbitrary model-authored diagram code.

Only draw connections supported by the interview, or visibly label them as uncertain. Do not imply timing, order or causal relationships that were not established. Include a textual step list and evidence references alongside each diagram so exports remain useful without a renderer. If there is insufficient detail, report the gap rather than invent a flowchart.

Mermaid remains the editable diagram export format. The browser renders the current bounded, linear step contract directly as semantic HTML with CSS connectors. It never evaluates saved Mermaid or model HTML. Unsupported order uses a dashed connector and an explicit label. This avoids a general graph dependency for a small ordered-list view; reconsider a maintained graph renderer if branching/layout needs expand. Markdown and JSON are implemented export formats; PDF is deferred.

## Modular boundaries and checks
Reuse the analysis coordinator, model adapter and validator. A report strategy receives a read-only evidence snapshot and returns a structured report proposal; an exporter renders saved records without a model call. The diagram renderer consumes validated workflow data. These boundaries allow provider, reasoning and output formats to change independently.

Test complete transcript/revision export, speaker-role mapping and unknowns, consistent section structure, evidence ownership, unsupported-claim rejection, long-meeting coverage, diagram escaping/unknown edges, stop/drain ordering, retries, corrections, reset races and preservation of human notes. Use synthetic fixtures; no paid calls in ordinary tests.

Implementation follows the [live analysis plan](live-analysis.md): establish structured state first, then participant metadata/shared sections, export and report finalization. UI changes require their own approved scope. The question-answer confirmation policy remains unresolved; manual status remains the current behavior.

## Current limits
Reports are formatted from accepted evidence without a separate model call. Mock extraction is a
limited simulation; its explicit fixture pattern exercises workflow diagrams without claiming
general workflow understanding. Unknown roles remain unknown. All transcript evidence is included.
Browser controls now support participant mappings, generated-note viewing, finalization and exports.
Structured editing of human notes, post-stop transcript corrections and human edits to generated reports are not implemented. Existing human notes are included verbatim in their section.

## Topic-aware synthesis (opt-in)
See [topic memory](topic-memory.md#notes-overview-and-final-report). Keep the existing section
order, group accepted findings within sections by topic, and cover paused as well as active
topics. Topic membership alone must not imply workflow sequence or causality. Reports containing topics use schema/strategy version 2. Existing immutable reports remain
unchanged. Live notes expose additive topic groups; the browser renders these groups in notes and the saved report reader.

## Attribution snapshots — 2026-09-14
Current transcript JSON uses schema 2 and includes raw accepted revisions, resolved speaker spans,
assignment history and roster revisions. Markdown retains raw text and adds person/role/span labels.
Saved reports include their attribution version and history; their evidence viewer uses the same
resolved spans as live dialogue. Correcting a person/role never rewrites an older saved report.
Regeneration requires the full transcript to be reconciled under the new attribution version.

## Spoken questions in reports — 2026-09-14
New reports (`evidence-report-v3`) add **Questions asked in conversation**, separate from suggestion
progress. Entries contain detected verbatim wording, exact revision evidence, confirmed speaker/role
where available and superseded flags. Markdown and JSON retain these references; the in-app reader
uses the existing safe text/evidence components. Existing saved reports are not rewritten. See
[extraction and archive contract](archives-and-question-history.md).


## Deferred review extensions
Independent multi-pass verification, resumable chunked reviews and a visual review diff remain
planned. The single full-transcript final review below is implemented. Market research is separate
and cannot become meeting evidence. Review cannot recover missing speech without new evidence.

New report provider labels come from successful analysis provenance, including `mixed` when
providers differ. Existing report revisions remain immutable. See [model selection](model-selection.md).

## Final review — implemented 2026-09-16
- Explicit meeting end runs one full-transcript call in either scheduling mode. Stopping capture
  alone does not end the meeting. Report → **Run final review** handles past ended meetings.
- Reuse the manual input builder, topic catalog, provider selection, strict evidence validation,
  durable receipt and atomic artifact commit. Include prior claims/workflows, human context and
  question history. Prior AI output is comparison material, not evidence.
- Correct supported artifacts through existing stable keys and topic identities; preserve human
  notes, confirmed identities and transcript revisions. No new live question is queued after end.
- Same input/model/context and unchanged accepted analysis reuse the last successful final review.
  Empty meetings make no provider call. No hidden retry; separate final-review allowance and existing input/output limits apply.
- Migration 13 preserves old report payloads and permits new revisions for changed analysis with
  unchanged transcript/context. New payloads carry analysis_version; previous reports remain readable.
- Failed, timed-out, invalid or incomplete live analyses do not gate final review. It includes all
  saved final segments and the last valid accumulated state, including previously uncovered speech.
  A prior failed live attempt does not count as a completed final review.
- An ongoing provider outage, missing credentials or exhausted final-review call limit can still block
  final review. Exhausted call allowance reports an explicit blocked reason and sends no request.
  FINAL_REVIEW_MAX_CALLS defaults to two attempts per session, separate from live/manual usage. Retry explicitly after resolving the cause.
- Errors/stale results publish no replacement report. Review diffs and independent multi-pass
  verification remain future work; this feature cannot recover speech that was never captured.

Opportunity findings and structured claims are always normalized to inferred hypotheses before
evidence validation. An overstated certainty label alone does not discard an otherwise valid review;
unknown evidence or invalid attribution still rejects the proposal.

Workflow connection counts that do not match adjacent step pairs are normalized to unknown order
for every connection, after validating all supplied step/connection evidence. Supported steps remain;
no positional alignment is guessed. Unknown references still reject the whole proposal.
