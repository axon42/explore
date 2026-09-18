import { prepareInUI } from "./prepared";
import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
async function create(page: Page) {
  await page.goto("/");
  await page.getByRole("button", {name: "Workspace actions", exact: true}).click();
  await page
    .getByRole("button", { name: "New workspace", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("Name")
    .fill("Agencies " + Date.now());
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page
    .getByRole("button", { name: "New meeting", exact: true })
    .first()
    .click();
  await page.getByRole("dialog").getByLabel("Name").fill("Agency discovery");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Agency discovery" }),
  ).toBeVisible();
  await prepareInUI(page);
  await expect(
    page.getByRole("button", { name: "Next turn", exact: true }),
  ).toBeEnabled();
}
test("workspace, brief, transcript, questions, evidence, notes and persistence", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await create(page);
  await expect(page.locator("html")).toHaveCSS("color-scheme", "light");
  await expect(page.locator(".ex-brand svg circle")).toHaveCount(2);
  await page.getByRole("button", { name: "Brief", exact: true }).click();
  await page
    .getByLabel("Objective", { exact: true })
    .fill("Understand reporting workflow and existing spend.");
  await page
    .getByLabel("Customer", { exact: true })
    .fill("Sam, agency operations");
  await page.getByRole("button", { name: "Save brief", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await page.getByRole("button", { name: "Interview", exact: true }).click();
  await page.getByText("Inject dialogue", { exact: true }).click();
  await page
    .getByLabel("Transcript text", { exact: true })
    .fill("Last Friday I used a spreadsheet to check reports for two hours.");
  await page.getByRole("button", { name: "Inject", exact: true }).click();
  const question = page.getByRole("button", {
    name: "You mentioned “Last Friday I used a spreadsheet to check reports for two hours.”. What was the impact?",
    exact: true,
  });
  await expect(question).toBeVisible();
  await question.click();
  await expect(page.locator(".ex-evidence")).toContainText("Last Friday");
  await page.getByRole("button", { name: "Mark asked", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Mark answered", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mark answered", exact: true })
    .click();
  await expect(page.locator(".ex-progress")).toContainText("1 / 1");
  await page.screenshot({
    path: "test-results/explore-interview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Spreadsheet reporting" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/explore-overview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await page
    .getByLabel("Meeting note", { exact: true })
    .fill("Ask who approves the final report.");
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await expect(page.locator(".ex-notes article")).toContainText(
    "Ask who approves",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Agency discovery" }),
  ).toBeVisible();
  await expect(page.locator(".ex-progress")).toContainText("1 / 1");
  await page.getByRole("button", { name: "Notes", exact: false }).click();
  await expect(page.locator(".ex-notes article")).toContainText(
    "Ask who approves",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Interview", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/explore-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
test("reset during replay starts clean and preserves brief and notes", async ({
  page,
}) => {
  await create(page);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(
    page.locator(".ex-transcript-list article").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reset test", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("separate transcript archive");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Reset test", exact: true })
    .click();
  await expect(page.locator(".ex-transcript-list article")).toHaveCount(0);
  await expect(page.getByText("Draft", {exact:true})).toBeVisible();
  await page.getByRole("button", { name: "Start test meeting", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Play", exact: true }),
  ).toBeEnabled();
  await page.reload();
  await expect(page.locator(".ex-transcript-list article")).toHaveCount(0);
  await page.getByRole("button", { name: "Next turn", exact: true }).click();
  await expect(page.locator(".ex-transcript-list article")).toHaveCount(1);
});
test("two viewers see the same questions and updated status", async ({
  page,
  context,
}) => {
  await create(page);
  const other = await context.newPage();
  await other.goto("/");
  await expect(
    other.getByRole("heading", { name: "Agency discovery" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next turn", exact: true }).click();
  await expect(page.locator(".ex-transcript-list article")).toHaveCount(1);
  await page.getByRole("button", { name: "Next turn", exact: true }).click();
  await expect(other.locator(".ex-question")).toHaveCount(1);
  await page.getByRole("button", { name: "Mark asked", exact: true }).click();
  await expect(
    other.getByRole("button", { name: "Mark answered", exact: true }),
  ).toBeVisible();
  await other.close();
});

test("local interview completes with participants, AI notes and downloadable report", async ({ page }) => {
  await create(page);
  await page.getByRole("button", { name: "Brief", exact: true }).click();
  await page.getByLabel("Job role", { exact: true }).first().fill("Founder");
  await page.getByRole("button", { name: "Save participants", exact: true }).click();
  await expect(page.getByText("Participants saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Interview", exact: true }).click();
  await page.getByText("Inject dialogue", { exact: true }).click();
  await page.getByLabel("Transcript text", { exact: true }).fill("Last Friday I used a spreadsheet to check reports for two hours.");
  await page.getByRole("button", { name: "Inject", exact: true }).click();
  await expect(page.locator(".ex-question")).toHaveCount(1);
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await page.getByText("AI notes", { exact: true }).click();
  await expect(page.locator(".ex-generated")).toContainText("Alex Test");
  await page.getByRole("button", { name: "Report", exact: true }).click();
  await page.getByRole("button", { name: "End interview and run final review", exact: true }).click();
  await expect(page.getByText("Report ready", { exact: true })).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download JSON", exact: true }).click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream!) chunks.push(chunk);
  const report = JSON.parse(Buffer.concat(chunks).toString());
  expect(report.sections[0].items[0].name).toBe("Alex Test");
  expect(report.coverage.final_segments).toBe(1);
  expect(report.coverage.processed_segments).toBe(1);
  expect(report.evidence[0].text).toContain("Last Friday");
  await page.screenshot({ path: "test-results/explore-report.png", fullPage: true });
  await page.getByRole("button", { name: "Brief", exact: true }).click();
  await page.locator(".ex-participants").getByLabel("Name", { exact: true }).first().fill("Alex Updated");
  await page.getByRole("button", { name: "Save participants", exact: true }).click();
  await expect(page.getByText("Participants saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Report", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Report 1 · Outdated" })).toBeVisible();
  await page.route("**/api/meetings/*/reports/*?format=json", route => route.fulfill({ status: 503 }));
  await page.getByRole("button", { name: "Download JSON", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Download failed");
  await page.unroute("**/api/meetings/*/reports/*?format=json");
  const transcriptEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export transcript JSON", exact: true }).click();
  expect((await transcriptEvent).suggestedFilename()).toBe("explore-transcript.json");
});
