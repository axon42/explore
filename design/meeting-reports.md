# Meeting records and final reports — design

2026-09-11. Backend APIs now implement transcript exports, shared generated-note/report sections,
human participant mappings, immutable final reports and Mermaid source generation. See
[implementation reference](../docs/analysis.md). Existing human-note bodies and UI are preserved.

## Durable evidence
Retain the entire transcript received and accepted by Explore, including provisional text, final text and accepted corrections, with speaker IDs, timestamps and exact revision references. Duplicate/rejected deliveries are not additional spoken content. A bounded LLM context never bounds storage retention. Unreceived speech cannot be recovered; any known ingestion gaps must be disclosed.

Current storage already retains accepted segment revisions; older legacy revisions discarded before migration cannot be reconstructed. Explicit test reset/delete remains destructive within its documented scope, rather than silently becoming an archive operation. Communicate this when implementing export/report controls; ordinary stop or report generation never deletes evidence.

Provide two transcript exports: readable Markdown with speaker/time labels, and versioned JSON containing current segments, accepted revision history, participant mappings and stable evidence IDs. Include meeting/session identity and export/source versions so external processing can trace quotations. Clearly distinguish provisional, current and superseded text. Exports are user-initiated and scoped to the selected meeting; no external upload is implied.

## Shared structure
Use one versioned section schema for meeting notes and final reports. Keep the same ordering across meetings, using “Not established” for missing information. Live AI notes fill it incrementally; a final report completes it through the closing transcript checkpoint. Human notes may remain free-form within those sections and retain their authorship/revision history. Do not rewrite or reclassify existing notes without a deliberate migration and reviewable mapping.

1. **People and meeting:** interviewer name(s), interview role and job role first; customer/other participants and roles, workspace, title, date and duration. Store stable participant-to-speaker mappings. User-supplied identities or explicit self-introductions are sources; do not infer a job role from speaking style. Allow unknown speakers until identified.
2. **Purpose:** interview objective, customer/vertical context and hypotheses from the brief, labeled as pre-meeting input.
3. **Discussion summary:** concise account of what was learned, without promoting hypotheses to findings.
4. **Workflows:** trigger, actor, steps, tools, handoffs, decisions and outcome; include supported frequency/timing and diagrams where useful.
5. **Pain and impact:** concrete incidents, frequency, effort, delays, cost and consequences, distinguishing stated facts from estimates.
6. **Current alternatives:** tools, workarounds, spending and previous attempts to solve the issue.
7. **Opportunities and uncertainty:** automation hypotheses, supporting/contradicting evidence, unknowns and further validation needed. Interest is not purchase commitment.
8. **Question progress:** retained questions, asked/answered status, answer evidence, dismissed/covered items and unresolved topics. Status respects the chosen human-confirmation policy.
9. **Next steps:** explicit commitments with owner/date when stated; AI-recommended follow-ups labeled separately. No invented owners or dates.
10. **Evidence and human notes:** source-linked details/quotes, original human contributions and transcript export references. Include coverage, report revision and generation provenance.

The report begins with participant details and a concise summary, followed by the structured detail. “All details” means preserving substantive evidence and access to the complete transcript, not claiming that a prose summary reproduces every utterance.

## Report lifecycle
- Separate replay pause, transcript-source closure and meeting finalization. A pause does not create a final report. On meeting end, close ingestion and capture its final accepted cursor, drain analysis through it, then schedule report generation once.
- The stop path cancels live analysis, then schedules a separate finalization worker to drain unprocessed finals before reporting. Reset/clear cancel work without starting finalization.
- Build from structured state plus source passages. Check coverage across the entire accepted transcript; if some dialogue was never analyzed, process it in bounded batches before synthesis. Never generate a “complete” report solely from the last context window.
- Record pending/generating/complete/failed state and covered cursor. Retries are idempotent. On provider failure or incomplete coverage, preserve data and show that completion failed or is partial, rather than publishing a misleading final report.
- Save immutable report revisions with schema, source/context versions, model/prompt identity, usage and evidence references. Later corrections or human-context changes mark the report outdated; regeneration creates a new revision while preserving the old one. Keep human edits separate from generated revisions.
- Reset invalidates in-flight report jobs using the session identity, just as it does live analysis. No stale result may repopulate deleted data.

## Workflow diagrams
Store workflow structure separately from rendered Mermaid: nodes for actors/actions/decisions and edges for sequence/handoffs, each with supporting evidence or an explicit unknown/inferred marker. Derive Mermaid from this validated structure so rendering can change independently of analysis. Prefer deterministic IDs and escaped labels over arbitrary model-authored diagram code.

Only draw connections supported by the interview, or visibly label them as uncertain. Do not imply timing, order or causal relationships that were not established. Include a textual step list and evidence references alongside each diagram so exports remain useful without a renderer. If there is insufficient detail, report the gap rather than invent a flowchart.

Mermaid is the editable diagram export format. No UI renderer is installed. When adding one, verify a maintained compatible renderer and use strict settings that disallow arbitrary HTML/click actions. Diagram size is bounded. Markdown and JSON are implemented export formats; PDF is deferred.

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
