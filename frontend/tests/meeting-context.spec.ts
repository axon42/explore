import { selectOption } from "./select";
import { startTest, type StartedDetail } from "./prepared";
import { test, expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import type { Detail } from "../src/explore/data";
import type { LiveAnalysis, MeetingReport, Topic } from "../src/explore/analysisData";
import type { Segment } from "../src/types";

async function create(page: Page, request: APIRequestContext) {
  const workspace = await (await request.post("/api/workspaces", { data: { name: "Thread view test" } })).json();
  const draft: Detail = await (await request.post(`/api/workspaces/${workspace.id}/meetings`, { data: { title: "Operations discovery" } })).json();
  const detail = await startTest(request, draft.meeting.id);
  await page.goto("/");
  await selectOption(page.getByLabel("Workspace", { exact: true }), workspace.id);
  await expect(page.getByRole("heading", { name: "Operations discovery", exact: true })).toBeVisible();
  return detail;
}

function segment(id: string, text: string, start = 0): Segment {
  return { event_id: id, segment_id: id, revision: 1, speaker_id: "customer", speaker_name: "Sam Test", start_ms: start, end_ms: start + 5000, text, is_final: true };
}
function topic(sid: string, id: string, title: string, source: Segment): Topic {
  return { id, session_id: sid, title, summary: source.text, summary_sources: { [source.segment_id]: 1 }, revision: 1, status: "active", provisional: false, needs_review: false, evidence: [{ segment_id: source.segment_id, revision: 1, superseded: false, assignment: "accepted" }] };
}

test("live threads evolve, resume identities, preserve inspection and link exact evidence", async ({ page, request }) => {
  const detail = await create(page, request);
  const mid = detail.meeting.id, sid = detail.session.id;
  const reporting = segment("report-pass", "Our weekly operational report waits six hours for access approval.");
  const recruiting = segment("hiring-pass", "Separately, interview scheduling keeps the recruiting team waiting.", 12000);
  for (const s of [reporting, recruiting]) await request.post(`/api/sessions/${sid}/inject`, { data: s });
  const a = topic(sid, "topic-reporting", "Operational reporting", reporting);
  const b = topic(sid, "topic-recruiting", "Recruiting", recruiting);
  let view: LiveAnalysis = { topics: [], state: {}, simulated: true, notes: [] };
  await page.route(`**/api/meetings/${mid}/analysis`, route => route.fulfill({ json: view }));
  await page.route(`**/api/sessions/${sid}/experiment`, async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...(await response.json()), strategy: "topics" } });
  });
  await expect(page.getByText("Listening for a complete thought.", { exact: false })).toBeVisible();
  view = { ...view, topics: [a], state: { topic_state: { focus_id: a.id, readiness: "developing", action: "continue" } } };
  const panel = page.getByRole("region", { name: "Discussion threads", exact: true });
  await expect(panel.getByText("Thought still developing")).toBeVisible();
  const firstColor = await panel.getByRole("button", { name: /Operational reporting/ }).getAttribute("class");
  await panel.getByRole("button", { name: "View thread evidence at 00:00" }).click();
  await expect(page.locator("#source-report-pass")).toHaveClass("highlight");
  await expect(page.locator(".ex-evidence")).toContainText(reporting.text);
  view = { ...view, topics: [{ ...a, status: "paused" }, b], state: { topic_state: { focus_id: b.id, readiness: "ready", action: "switch" } } };
  await expect(panel.locator(".ex-thread-detail h3")).toHaveText("Recruiting");
  await panel.getByRole("button", { name: /Operational reporting/ }).click();
  await expect(panel.locator(".ex-thread-detail h3")).toHaveText("Operational reporting");
  view = { ...view, topics: [{ ...a, status: "paused" }, { ...b, revision: 2, summary: "Recruiting schedules are reviewed every Friday." }] };
  await expect(panel.locator(".ex-thread-detail h3")).toHaveText("Operational reporting");
  await panel.getByRole("button", { name: "Follow active thread" }).click();
  await expect(panel.getByText("Recruiting schedules are reviewed every Friday.")).toBeVisible();
  view = { ...view, topics: [{ ...a, revision: 2 }, { ...b, status: "paused" }], state: { topic_state: { focus_id: a.id, readiness: "developing", action: "resume" } } };
  await expect(panel.locator(".ex-thread-detail h3")).toHaveText("Operational reporting");
  await expect(panel.getByRole("button", { name: /Operational reporting/ })).toHaveAttribute("class", firstColor!);
  await expect(panel.locator(".ex-thread-picker button")).toHaveCount(2);
  await page.screenshot({ path: "test-results/discussion-threads.png", fullPage: true });
  view = { ...view, topics: [{ ...a, summary: "", needs_review: true, summary_sources: { [reporting.segment_id]: 0 } }, { ...b, status: "paused" }] };
  await expect(panel.getByText("Evidence changed. This summary needs review.")).toBeVisible();
  await expect(panel.getByRole("button", { name: /View thread evidence/ })).toHaveCount(0);
  // Never show another session's topics after reset or a stale cross-session response.
  view = { ...view, topics: [{ ...a, session_id: "old-session" }] };
  await expect(panel.locator(".ex-thread-picker button")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

function report(detail: StartedDetail): MeetingReport {
  const source = segment("workflow-pass", 'We export the report, check it, and ask finance for approval. <img src=x onerror="window.unsafe=true">');
  const thread = topic(detail.session.id, "topic-reporting", "Operational reporting", source);
  const claim = { text: "Access approval delays the weekly report.", basis: "observed", sources: { [source.segment_id]: 1 } };
  return {
    schema_version: 2, revision: 2, meeting: detail.meeting, session: detail.session,
    generated_at: "2026-09-12T18:00:00Z", duration_ms: 3600000, simulated: true, provider: "mock", topics: [thread],
    sections: [
      { key: "people", title: "People and meeting", items: [{ name: "Alex Test", interview_role: "interviewer", job_role: "Co-founder" }, { name: "Sam Test", interview_role: "customer", job_role: "Operations lead" }] },
      { key: "purpose", title: "Purpose", items: [{ brief: { objective: "Understand reporting bottlenecks", vertical: "Agencies" } }] },
      { key: "summary", title: "Discussion summary", items: [claim], topic_groups: [{ topic_id: thread.id, title: thread.title, items: [claim] }] },
      { key: "workflows", title: "Workflows", items: [] },
      { key: "pain_impact", title: "Pain and impact", items: [claim] },
      { key: "alternatives", title: "Current alternatives", items: [] },
      { key: "opportunities", title: "Opportunities and uncertainty", items: [{ ...claim, text: "Approval reminders could reduce waiting; validate this.", basis: "inferred" }] },
      { key: "questions", title: "Question progress", items: ["queued", "asked", "answered", "discarded"].map(status => ({ text: `A ${status} follow-up`, status })) },
      { key: "next_steps", title: "Next steps", items: [] },
      { key: "evidence_notes", title: "Evidence and human notes", items: [{ body: "Follow up on the approval policy." }] },
    ],
    workflows: [{ key: "weekly", title: "Weekly report", topic_id: thread.id, steps: ["Export report", "Check figures", 'Finance review <script>window.unsafe=true</script>'].map(label => ({ label, source_ids: [source.segment_id] })), transitions: [[source.segment_id], []], sources: { [source.segment_id]: 1 } }],
    evidence: [source], coverage: { final_segments: 1, processed_segments: 1, provisional_segments: 0 },
  };
}

test("saved report renders safe diagrams, grouped notes, evidence, revisions and mobile layout", async ({ page, request }) => {
  const detail = await create(page, request);
  const mid = detail.meeting.id;
  const saved = report(detail);
  await page.route(`**/api/meetings/${mid}/reports`, route => route.fulfill({ json: { job: { status: "complete", error: "" }, reports: [{ id: "new", revision: 2, outdated: false }, { id: "old", revision: 1, outdated: true }] } }));
  await page.route(`**/api/meetings/${mid}/reports/new`, route => route.fulfill({ json: saved }));
  // Existing version-one reports omit topic fields; they remain readable.
  await page.route(`**/api/meetings/${mid}/reports/old`, route => route.fulfill({ json: { ...saved, schema_version: 1, revision: 1, topics: undefined, sections: saved.sections.map(s => ({ ...s, topic_groups: undefined })) } }));
  await page.getByRole("button", { name: "Report", exact: true }).click();
  const doc = page.getByRole("article", { name: "Saved meeting report" });
  await expect(doc.getByRole("heading", { name: "Alex Test" })).toBeVisible();
  await expect(doc.getByText("Co-founder", { exact: true })).toBeVisible();
  await expect(doc.getByText("Hypothesis", { exact: true })).toBeVisible();
  await expect(doc.getByRole("img", { name: "1 queued, 1 asked, 1 answered, 1 discarded" })).toBeVisible();
  await expect(doc.locator(".ex-workflow-step")).toHaveCount(3);
  await expect(doc.getByText("Order not established", { exact: true })).toBeVisible();
  await expect(doc.locator("script, img, iframe")).toHaveCount(0);
  await expect(doc.locator(".ex-workflow-step").last()).toContainText("<script>");
  await page.screenshot({ path: "test-results/meeting-report-reader.png", fullPage: true });
  const source = doc.locator(".ex-workflow-step").first().getByRole("button", { name: "00:00 ↗" });
  await source.click();
  await expect(page.getByRole("region", { name: "Report evidence" })).toContainText(saved.evidence[0].text);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("region", { name: "Report evidence" })).toHaveCount(0);
  await expect(source).toBeFocused();
  const url = page.url();
  await doc.getByRole("link", { name: "Current alternatives" }).click();
  expect(page.url()).toBe(url);
  await expect(doc.locator("#report-alternatives")).toHaveAttribute("open", "");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/meeting-report-mobile.png", fullPage: true });
  await selectOption(page.getByLabel("Report revision"), "old");
  await expect(doc.getByText("Simulated analysis · Revision 1")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Report 1 · Outdated" })).toBeVisible();
  await expect(doc.locator(".ex-report-topics")).toHaveCount(0);
});

test("report loading fails visibly and retries; unmounted revisions cannot overwrite selection", async ({ page, request }) => {
  const detail = await create(page, request);
  const mid = detail.meeting.id;
  const saved = report(detail);
  await page.route(`**/api/meetings/${mid}/reports`, route => route.fulfill({ json: { job: { status: "complete", error: "" }, reports: [{ id: "new", revision: 2, outdated: false }, { id: "old", revision: 1, outdated: true }] } }));
  let fail = true;
  await page.route(`**/api/meetings/${mid}/reports/new`, route => fail ? route.fulfill({ status: 503 }) : route.fulfill({ json: saved }));
  await page.getByRole("button", { name: "Report", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Could not open this report");
  fail = false;
  await page.getByRole("button", { name: "Retry report" }).click();
  await expect(page.getByText("Simulated analysis · Revision 2")).toBeVisible();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested = false;
  await page.route(`**/api/meetings/${mid}/reports/old`, async route => { requested = true; await gate; await route.fulfill({ json: { ...saved, revision: 1 } }).catch(() => {}); });
  await selectOption(page.getByLabel("Report revision"), "old");
  await expect.poll(() => requested).toBe(true);
  await selectOption(page.getByLabel("Report revision"), "new");
  await expect(page.getByText("Simulated analysis · Revision 2")).toBeVisible();
  release();
  await expect(page.getByText("Simulated analysis · Revision 1")).toHaveCount(0);
});
