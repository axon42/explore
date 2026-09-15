import { selectOption } from "./select";
import { startTest } from "./prepared";
import { test, expect } from "@playwright/test";

test("bottom-left analysis setting saves, follows other tabs and preserves interview controls", async ({ page, context, request }) => {
  let setting = { strategy: "legacy", revision: 0 };
  const writes: unknown[] = [];
  await context.route("**/api/settings/analysis", async route => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      writes.push(body);
      expect(body.revision).toBe(setting.revision);
      setting = { strategy: body.strategy, revision: setting.revision + 1 };
    }
    await route.fulfill({ json: setting });
  });
  await context.route("**/api/sessions/*/experiment", async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...(await response.json()), strategy: setting.strategy } });
  });
  const workspace = await (await request.post("/api/workspaces", { data: { name: "Settings demo" } })).json();
  const draft = await (await request.post(`/api/workspaces/${workspace.id}/meetings`, { data: { title: "Settings interview" } })).json();
  await startTest(request, draft.meeting.id);
  await page.goto("/");
  await selectOption(page.getByLabel("Workspace", { exact: true }), workspace.id);
  await page.getByRole("button", {name:"Analysis settings",exact:true}).click();
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "legacy");
  const other = await context.newPage();
  await other.goto("/");
  await other.getByRole("button", {name:"Analysis settings",exact:true}).click();
  await selectOption(page.getByLabel("Analysis mode"), "topics");
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "topics");
  await expect(other.getByLabel("Analysis mode")).toHaveAttribute("data-value", "topics");
  expect(writes).toEqual([{ strategy: "topics", revision: 0 }]);
  await expect(page.getByText("Listening for a complete thought.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next turn", exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole("button", {name:"Analysis settings",exact:true}).click();
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "topics");
  await expect(page.getByRole("heading", { name: "Settings interview" })).toBeVisible();
  const box = await page.getByRole("region", { name: "Analysis settings" }).boundingBox();
  expect(box!.x).toBeLessThan(220);
  expect(box!.y).toBeGreaterThan(500);
  await page.screenshot({ path: "test-results/analysis-settings.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", {name:"Analysis settings",exact:true}).click();
  await expect(page.getByLabel("Analysis mode")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/analysis-settings-mobile.png", fullPage: true });
  await other.close();
});

test("stale reads cannot undo a saved mode and conflicts are visible", async ({ page }) => {
  let setting = { strategy: "legacy", revision: 0 };
  let pauseRead = false;
  let entered = false;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/settings/analysis", async route => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      if (body.revision !== setting.revision) {
        await route.fulfill({ status: 409, json: { message: "Analysis mode changed in another tab. Review the setting and retry." } });
        return;
      }
      setting = { strategy: body.strategy, revision: setting.revision + 1 };
      await route.fulfill({ json: setting });
      return;
    }
    const snapshot = { ...setting };
    if (pauseRead) { pauseRead = false; entered = true; await gate; }
    await route.fulfill({ json: snapshot });
  });
  await page.goto("/");
  await page.getByRole("button", {name:"Analysis settings",exact:true}).click();
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "legacy");
  pauseRead = true;
  await expect.poll(() => entered).toBe(true);
  await selectOption(page.getByLabel("Analysis mode"), "topics");
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "topics");
  release();
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "topics");
  setting = { strategy: "legacy", revision: 2 };
  await selectOption(page.getByLabel("Analysis mode"), "legacy");
  await expect(page.getByRole("alert")).toContainText("changed in another tab");
  await expect(page.getByLabel("Analysis mode")).toHaveAttribute("data-value", "legacy");
  await page.getByRole("button", { name: "Refresh setting" }).click();
  await expect(page.getByRole("region", { name: "Analysis settings" }).getByRole("alert")).toHaveCount(0);
});
