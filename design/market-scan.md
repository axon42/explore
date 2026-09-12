# Post-meeting market scan

Status: future proposal, not implemented. Keep separate from live interview analysis and
the saved [meeting report](meeting-reports.md). A report is evidence about the interview;
market research introduces external claims with different sources and dates.

## Proposed experience
After the report is ready, an explicit **Start market scan** action opens a short research
brief: target customer, observed pain, possible solution category and open questions.
The user reviews the direction before research starts. No automatic scan or background spend.

The result should include:

- Concise research direction grounded in the interview, with evidence links.
- A competitor/alternative table: customer segment, workflow covered, pricing when verified,
  strengths, gaps, evidence URL and checked date. Include manual workarounds where relevant.
- Separate observations, hypotheses, missing information and recommended validation interviews.

## Small modular boundary
A research strategy consumes a saved report revision plus the reviewed brief and returns a
structured result. A separate coordinator owns cancellation, deadlines, retries and budgets;
provider adapters own search/model access; the repository owns versioned results and citations.
The viewer formats saved results without rerunning research. Begin with one bounded workflow;
add multiple agents only if evaluations demonstrate a benefit.

Link results to their meeting/session and report revision. Later report edits mark a scan
outdated; research must never rewrite transcript evidence or human notes. A future workspace
view can compare scans without changing the live ingestion contract.

Before implementation, decide the research provider, explicit per-scan cost ceiling, data
sharing policy and evaluation criteria. Treat web pages and retrieved text as untrusted;
validate citations, distinguish unavailable pricing from zero, and expose partial/failed runs.
Tests must use synthetic interviews and mocked search results.
