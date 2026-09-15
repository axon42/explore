# Topic memory within a meeting

Status: implemented as the **Discussion threads** mode, selectable at the bottom left,
2026-09-12. Standard (`legacy`) remains the initial default pending real-provider evaluation. The browser now shows live threads and saved topic-aware reports. Extends [live analysis](live-analysis.md) and [meeting reports](meeting-reports.md).

## Decision and purpose
Use persistent topic threads inside a meeting's current session. One bounded analysis call
proposes topic routing, evidence-backed memory updates and zero or one question. Keep the
existing coordinator, provider adapter, validators and SQLite repository. No agent framework,
agent per topic, vector database or graph database is needed for this phase.

A topic is a recurring subject, such as operational reporting. A transcript paragraph is a
display grouping; an analysis batch is a scheduling unit. Neither defines a topic boundary.
A topic can reference nonconsecutive passages, and one passage can support multiple topics.
Topic relevance does not establish workflow order, dependency or causality.

The legacy strategy has recent dialogue, accumulated claims/workflows, source revisions,
question cooldown and discard history. The topic strategy adds persistent identity, routing,
readiness and evidence retrieval. Timing heuristics alone cannot establish a completed thought.

## Mental model

| Layer | Contents | Purpose |
| --- | --- | --- |
| Recent conversation | New final text plus bounded recent exact dialogue | Resolve pronouns, interruptions and unfinished explanations |
| Topic memory | Known facts, workflow references, open gaps, question history and citations | Resume a subject without starting over |
| Meeting context | Brief, participants, human notes and compact topic index | Keep the interview objective and broader discussion in view |

Example, with synthetic dialogue:

| Passage | Proposed update | Question behavior |
| --- | --- | --- |
| “Our weekly report takes six hours. Let me explain…” | Open operational reporting; explanation still developing | Wait |
| “Before we pull the numbers, access needs approval.” | Link evidence to reporting and access approvals; propose a dependency only if supported | Do not assume a full topic switch |
| “Separately, recruiting has been difficult.” | Switch focus to recruiting; retain reporting memory | Defer reporting follow-ups |
| “Back to the report: five of those hours are waiting for access.” | Resume reporting; attach the clarification and supporting evidence | Consider a specific remaining gap after the speaker finishes |
| “No, that delay happened only once.” | Record a correction; remove any unsupported recurring-delay inference | Reconsider questions based on the old premise |

The topic remains operational reporting even when its title is refined. A return creates new
evidence links to the existing identity, not a duplicate topic.

## Topic routing and state
The model proposes `continue`, `switch`, `resume`, or `uncertain`, citing the passages that
support its interpretation. Existing IDs must come from the supplied topic index; the
repository assigns IDs to new-topic proposals. Topic titles are labels, not identifiers.

Keep a primary focus topic plus optional related topics. Topics are active or paused;
paused means the conversation moved elsewhere, not that every question was answered.
End-of-meeting status comes from session lifecycle, not an LLM claim that a topic is complete.

- Explicit transitions can support a switch immediately. A passing mention alone should not
  replace the focus; uncertain assignments remain provisional and cannot drive a question.
- Preserve enough recent dialogue across a switch to resolve “that” and “the earlier issue.”
- Allow unassigned evidence when there is no clear subject. Never invent a topic to satisfy a schema.
- Topic assignments are revisable derived data. Similar wording is not enough to merge topics;
  ambiguity can remain unresolved. Automatic merges and user merge/split controls are deferred.
- A gap, workflow and automation hypothesis retain their own identities. Topic membership
  groups them; explicit evidence-backed links establish any claimed relationship between them.

## Storage and contracts
Migration 4 creates topic and association tables transactionally. See the
[implemented data model](../docs/data-model.md#topic-memory-migration-4).

| Record | Minimum contents |
| --- | --- |
| Topic | Session-scoped ID, label, bounded summary, active/paused state, revision, creating/updating analysis run |
| Topic evidence | Topic ID, exact session/segment/revision reference, provisional/accepted assignment |
| Topic association | Topic ID plus existing claim/workflow/question identity; same-session validation |
| Analysis checkpoint extension | Schema version, focus ID, unresolved routing, existing coverage and state version |
| Analysis proposal extension | Routing decision, bounded topic updates, associations, question topic/intent and readiness reason |

Store topic rows and evidence links in SQLite. Extend existing structured memory rather than
copying entire claim/workflow bodies into every topic. Scope claim keys to their topic where
needed so identical labels cannot overwrite facts about different processes. Reuse immutable
analysis runs for change provenance; do not add a second general event system.

All associations must resolve within the current session. Composite foreign keys protect
relational evidence links; validate JSON references at the application boundary. Commit
routing, memory, evidence, question and coverage changes together. Invalid proposals roll back;
failed calls do not advance coverage. Topic IDs and accepted job identity make retries idempotent.

Human notes, brief and question status remain human-owned. Topic summaries cannot overwrite them.
Existing meetings start with no topic assignments; do not silently spend tokens reprocessing
history. A later explicit rebuild may derive topics from stored evidence. Reset removes topic
run data; archive preserves it. Old-session results cannot populate a new run.

## Context construction and cost
Keep one provider call per eligible batch; topic classification is part of that call, not
another model or an autonomous loop. Provider-independent context selection receives a snapshot
and returns a bounded envelope; the model only proposes updates, and the repository owns writes.

Include the brief, recent/new dialogue, focus-topic detail, relevant question intents and a
compact topic index. Start with the focus and at most two related topic details. Bound index
and detail sizes inside the existing total input/output budgets, rather than adding an
unbounded new allowance. Tune allocations against replay fixtures before choosing production defaults.

For an older topic, use known IDs, recency and SQLite text matching to select candidates.
If routing identifies a topic whose detail was omitted, persist the routing proposal, load its
summary and relevant exact evidence for the next eligible batch, and withhold questions until
that context is available. Do not trigger an unbounded immediate retrieval/model loop. Record
omitted-topic counts so truncation is explicit; storage and transcript exports remain complete.

Topic summaries are retrieval aids, not independent evidence. Any new factual premise must
cite supplied transcript revisions. Keep unresolved contradictions and short negations visible;
never repeatedly summarize away their meaning. Reconcile dependencies when evidence is corrected.

## Question readiness and timing
Separate memory updates from permission to interrupt. The model proposes readiness as
`developing`, `ready`, or `uncertain`, with a short reason and evidence. This is an assessment,
not proof; the application also enforces freshness, scope, cooldown and budget rules.

Publish only when the topic is sufficiently understood, the explanation appears complete,
there is a concrete unresolved gap, the question relates to the current focus, and no newer
speech invalidates its premise. Preserve the existing conservative suppression while newer
final text is pending or speech remains provisional. Maximum-window flushes update memory only.

Associate a question with its topic and a normalized intent, such as “impact of access delay.”
Check supplied asked/answered/discarded intents before proposing another wording. Exact matching
is enforced in code; semantic equivalence requires model evaluation and is not guaranteed by an
intent string. Missing relevant question history makes readiness uncertain.

Switching topics does not reset cooldown, discard history or manually set statuses. Old queued
questions remain available but are not newly promoted for an unrelated topic. No hidden queue
of model questions is auto-published later: reconsider against fresh context before publication.

Revisit the current 35-word opening threshold during this work: use it to avoid greeting-only
calls, not to block a short correction to an established topic. Interim speech may inform
activity/quiet detection but is not accepted factual evidence. Topic logic must be source-neutral;
replay should reproduce native-audio fragment timing through the same policy for evaluation.

## Notes, overview and final report
Derive views from accepted topic associations. Preserve the established notes/report section
order and add topic groupings within it; a topic is not automatically a workflow. A gap with no
supported workflow link stays unassigned, and an automation opportunity remains a hypothesis.

Finalization drains every accepted final segment, including short residual text, then assembles
a report covering active and paused topics. Label unresolved topics, contradictions and missing
evidence. It must not summarize only the last focus topic. Preserve full transcript exports and
immutable report revisions. Topic-aware output requires a versioned contract, not silent changes
to old reports. The approved thread panel and report reader preserve existing interview controls and
evidence interactions; see [UI decisions](ui.md#live-context-and-report-reader).

## Delivery and validation
1. **Fixtures and baseline:** scripted topic switches, returns, incomplete explanations and
   short corrections. Record current question quality, latency and token use at fixed checkpoints.
2. **Storage and contracts:** topic/evidence migration, reducer, deterministic fake proposals,
   restart/retry tests. Keep topic strategy selectable so the existing strategy remains usable.
3. **Context and reasoning:** bounded routing, context hydration, readiness and intent checks
   through the existing Gemini adapter. Default tests use mocks; separately authorize and budget
   a small synthetic real-provider evaluation before enabling the strategy for interviews.
4. **Outputs:** topic-aware notes/report contracts and complete finalization coverage, followed
   by a separately reviewed UI grouping proposal. No automatic paid rebuild of prior meetings.

| Test case | Required outcome |
| --- | --- |
| Reporting → recruiting → reporting | Same reporting ID resumes; recruiting facts stay separate |
| Rapid switching, cross-topic passage, vague pronouns | Provisional/unassigned allowed; no unsupported question |
| Fragmented explanation, long pause, brief interruption | No suggestion while the fixture marks the explanation unfinished |
| Short denial or correction | Evidence retained; dependent premises reconsidered without waiting for 35 new words |
| Asked, answered or discarded intent on return | No rephrased duplicate in curated evaluation cases |
| Old topic omitted from context | Hydrate it within budget before asking; never invent missing detail |
| Revisions, concurrent human edits, reset and retry | Correct ownership, no stale writes, atomic checkpoint and no duplicate artifacts |
| Long meeting, provider failure, exhausted budget | Bounded calls/context, explicit failure, complete saved transcript |
| Stop, restart, archive and export | All topics/evidence preserved as specified; final report covers the full run |

Deterministic integrity tests must all pass. For semantic quality, annotate expected topic
identity, allowed question windows and supporting evidence on held-out synthetic interviews.
Compare premature-question and duplicate rates, topic-resume accuracy, grounding, and question
usefulness against the baseline. Measure waiting time, provider time and display latency separately,
plus calls/tokens per minute. Set numeric quality/latency acceptance thresholds from the baseline
before rollout; passing mocked tests alone does not establish Gemini quality.

## Deferred complexity
Cross-meeting topic identity, embeddings, graph queries, agent-led research, automatic topic
merging and a visual topic editor remain outside this phase. Consider them only when evaluation
shows a concrete retrieval or workflow limitation. Session-local topic memory should remain
replaceable without changing transcript ingestion or provider transport.


## Implementation choices and remaining evaluation
- `topics.py` owns contracts, validation, context bounds and readiness; `topic_storage.py`
  owns SQL projections within the existing analysis transaction. Topic focus lives in the
  checkpoint; active/paused status is derived to avoid inconsistent duplicate state.
- New topic IDs are deterministically assigned from job identity and proposal-local keys
  before reducing memory, then inserted by the repository. Existing IDs and evidence are
  validated; retries cannot create additional topics for an already accepted job.
- The index selects at most 40 topics using focus, title-word matches and recency. Detail
  loads for at most three topics; up to 8K characters of exact topic evidence share the
  64K-character context ceiling. Character budgets are conservative size limits, not token
  estimates. Output remains 4,096 tokens and existing call/deadline limits apply.
- Topic summaries with corrected source dependencies are withheld and marked for review.
  Stored evidence history and topic identity remain intact. Claims/workflows are keyed by
  `(topic_id, key)`; legacy entries remain unassigned. Question intent matching is exact after
  normalization; semantic equivalence and routing correctness still depend on model quality.
- Opening fragments wait for 35 words. Once any evidence has been processed, short corrections
  bypass that opening threshold. Topic mode uses the same four/25-second scheduling policy for
  replay, injection and native audio. Finalization always drains remaining accepted text.
- Notes expose additive `topic_groups`; reports with topics use schema/strategy version 2 and
  group Markdown items within the existing sections. The browser renders live threads below the transcript and grouped saved report sections.
- The offline fixture and `python -m app.topic_eval` are implemented. They validate plumbing
  with a deliberately limited simulated router, not a learned classifier. See the
  [baseline](../docs/topic-memory-evaluation.md). Held-out Gemini grounding, semantic duplicate
  rates and real latency/token measurements remain rollout gates, not completed checks.


## First-topic compatibility repair
A synthetic Gemini request reproduced the first-topic failure: a declared, accepted new topic
used `continue` while no focus existed. The validator rejected the whole batch. Prompt v7
explicitly asks for `switch`, and the initial response schema excludes `continue`/`resume`
when the topic index is empty. A pure normalizer also canonicalizes that specific empty-index,
empty-focus `continue` to `switch` when its focus names an accepted `new:` update. It does not
invent IDs, evidence or summaries; all evidence/ownership/readiness checks still run. Existing
focus changes via `continue` continue to fail validation.

Verification: one synthetic request reproduced the error; one post-fix request saved a topic
and claim (one call each, 1,989 and 1,947 total tokens respectively). No private interview was
sent. This verifies first-topic integration, not semantic readiness/question-quality accuracy.

## Missing routing fields repair — 2026-09-12
`topic_routing_incomplete` means a non-uncertain action lacks its focus ID or routing citations.
A synthetic provider response reproduced the rejection despite an accepted focus update already
citing its evidence. The previous wire schema allowed routing fields to be omitted, and the
shared no-question instruction did not distinguish top-level from nested `source_ids`.

Prompt v8 separates question evidence from topic evidence. The Gemini schema requires explicit
topic fields; an `anyOf` branch requires at least one routing citation for continue/switch/resume
while permitting an evidence-free uncertain result. These are documented
[Gemini JSON Schema features](https://github.com/googleapis/googleapis/blob/master/google/ai/generativelanguage/v1beta/generative_service.proto).
Local validation remains authoritative; no extra model calls or automatic retries were added.

The pure routing normalizer handles two redundant omissions before validation: `continue` may
repeat a known current focus, and missing routing citations may reuse the one accepted update
whose ID exactly matches the declared focus. Never infer a switch/resume target, use question
citations, union unrelated updates, overwrite invalid supplied references or reuse old evidence.
All original evidence, ownership, provisional-state and readiness checks still run atomically.
Unrecoverable output remains an error with coverage unchanged; explicit retry processes the saved
transcript. Tests cover successful questions, memory-only batches, ambiguous/foreign references,
retry and idempotency. The reported error class is reproduced; the user's discarded raw provider
response is unavailable, and live Gemini quality still requires a separate check.

Verification: 138 backend tests and five analysis/context/report browser tests passed with
mocked providers and disposable storage; Ruff checks passed. Restarted the local server at
5173 after confirming no live sessions/capture; startup reported zero interrupted sessions.
No real Gemini calls or transcript reprocessing were triggered by this repair.

Attribution changes (migration 7) invalidate the current topic readiness and derived memory.
Persisted topic summaries compare their owning run's attribution version with the session before
being displayed or reused. The bounded catalog resolves retrieved source spans under current human
assignments; old topic/run provenance remains available for review.


## Planned reliability follow-up — 2026-09-15
See [interview reliability and analysis quality](analysis-reliability.md) for capture/utterance
assembly, scoped diagnostics, durable analysis jobs and multi-topic evaluation. These are proposals;
the existing implementation and limits remain unchanged.
