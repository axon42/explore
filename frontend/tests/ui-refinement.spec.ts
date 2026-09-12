import { test, expect } from "@playwright/test";
import type { Locator } from "@playwright/test";

async function centered(dialog: Locator, width: number, height: number) {
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThan(3);
  expect(Math.abs(box.y + box.height / 2 - height / 2)).toBeLessThan(3);
  expect(box.x).toBeGreaterThanOrEqual(12);
  expect(box.y).toBeGreaterThanOrEqual(12);
  expect(box.height).toBeLessThanOrEqual(height - 24);
}

test("capture, creation and reset dialogs stay centered with accessible controls", async ({ page, request }) => {
  await page.route("**/api/audio-capture", route => route.fulfill({ json: { supported: true, configured: true, helper_ready: true, max_seconds: 120, capture: null } }));
  await page.route("**/api/sessions/*/audio-capture", route => route.fulfill({ status: 503, json: { message: "Synthetic capture unavailable. Retry after checking permissions." } }));
  const workspace = await (await request.post("/api/workspaces", { data: { name: "Dialog audit" } })).json();
  await request.post(`/api/workspaces/${workspace.id}/meetings`, { data: { title: "Dialog audit meeting" } });
  await page.goto("/");
  await page.getByLabel("Workspace", { exact: true }).selectOption(workspace.id);
  const open = page.getByRole("button", { name: "Capture audio", exact: true });
  await open.click();
  const capture = page.getByRole("dialog", { name: "Capture this conversation" });
  await centered(capture, 1440, 1000);
  const checkbox = capture.getByRole("checkbox");
  const box = (await checkbox.boundingBox())!;
  const label = (await capture.locator("label > span").boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(20);
  expect(label.x - box.x - box.width).toBeLessThan(16);
  await expect(capture.getByRole("button", { name: "Start capture" })).toBeDisabled();
  await checkbox.check();
  await expect(capture.getByRole("button", { name: "Start capture" })).toHaveCSS("background-color", "rgb(49, 91, 211)");
  await page.screenshot({ path: "test-results/capture-dialog-fixed.png", fullPage: true });
  await capture.getByRole("button", { name: "Start capture" }).click();
  await expect(capture.getByRole("alert")).toContainText("Synthetic capture unavailable");
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  await open.click();
  await expect(capture.getByRole("checkbox")).not.toBeChecked();
  await page.setViewportSize({ width: 390, height: 650 });
  await centered(capture, 390, 650);
  expect(await capture.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: "test-results/capture-dialog-mobile.png", fullPage: true });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "New workspace", exact: true }).click();
  await centered(page.getByRole("dialog", { name: "New workspace" }), 390, 650);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Reset test", exact: true }).click();
  await centered(page.getByRole("dialog", { name: "Reset this test?" }), 390, 650);
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("color proposal is isolated, responsive and previews all meeting surfaces", async ({ page }) => {
  const calls: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/")) calls.push(request.url()); });
  await page.goto("/ui-preview.html");
  await expect(page.getByRole("heading", { name: "Reporting discovery" })).toBeVisible();
  await page.screenshot({ path: "test-results/color-preview-interview.png", fullPage: true });
  await page.getByRole("button", { name: "Capture audio" }).click();
  await centered(page.getByRole("dialog", { name: "Capture this conversation" }), 1440, 1000);
  await page.screenshot({ path: "test-results/color-preview-dialog.png", fullPage: true });
  await page.keyboard.press("Escape");
  for (const name of ["Overview", "Brief", "Notes", "Report"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("button", { name, exact: true })).toHaveAttribute("aria-current", "page");
    await page.screenshot({ path: `test-results/color-preview-${name.toLowerCase()}.png`, fullPage: true });
  }
  await page.getByLabel("Color direction").selectOption("indigo");
  await page.getByRole("button", { name: "Interview", exact: true }).click();
  await page.screenshot({ path: "test-results/color-preview-alternative.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Capture audio" }).click();
  await centered(page.getByRole("dialog", { name: "Capture this conversation" }), 390, 844);
  expect(calls).toEqual([]);
});

test("shared theme keeps meeting controls readable across views, zoom and narrow screens", async ({ page, request }) => {
  const workspace = await (await request.post("/api/workspaces", { data: { name: "Reporting research" } })).json();
  await request.post(`/api/workspaces/${workspace.id}/meetings`, { data: { title: "Operations and reporting discovery" } });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByLabel("Workspace", { exact: true }).selectOption(workspace.id);
  await expect(page.getByRole("heading", { name: "Operations and reporting discovery" })).toBeVisible();
  await expect(page.locator(".ex-questions").getByLabel("Question frequency")).toBeVisible();

  // Check actual rendered text/background pairs, including disabled controls and semantic badges.
  const contrast = await page.locator(".ex-primary, .ex-mode, .ex-status, .ex-archive-toggle").evaluateAll(elements => elements.map(el => {
    const style = getComputedStyle(el);
    const luminance = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(n => {
        const v = n / 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
      });
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    };
    let background = style.backgroundColor;
    for (let parent = el.parentElement; background === "rgba(0, 0, 0, 0)" && parent; parent = parent.parentElement) background = getComputedStyle(parent).backgroundColor;
    const values = [luminance(style.color), luminance(background)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
  }));
  expect(contrast.length).toBeGreaterThan(3);
  contrast.forEach(ratio => expect(ratio).toBeGreaterThanOrEqual(4.5));

  for (const width of [1440, 768, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ["Interview", "Overview", "Brief", "Notes", "Report"]) {
      await page.getByRole("navigation", { name: "Meeting views" }).getByRole("button", { name: view, exact: true }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (width === 1440 && ["Brief", "Notes"].includes(view)) await page.screenshot({ path: `test-results/theme-${view.toLowerCase()}.png`, fullPage: true });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Interview", exact: true }).click();
  await page.locator("body").evaluate(el => { el.style.zoom = "2"; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Reset test", exact: true }).click();
  const reset = page.getByRole("dialog", { name: "Reset this test?" });
  await expect(reset).toBeVisible();
  await reset.getByRole("button", { name: "Close reset dialog" }).focus();
  await page.keyboard.press("Tab");
  await expect(reset.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(reset.getByRole("button", { name: "Cancel" })).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Reset test", exact: true })).toBeFocused();
});
