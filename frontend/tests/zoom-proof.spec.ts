import { expect, test } from "@playwright/test";

test("toolkit failure uses no join token; retry loads browser bundle before joining", async ({ page }) => {
  let joins = 0;
  let loads = 0;
  await page.route("**/api/integrations/zoom/proof", route => route.fulfill({json:{configured:true,enabled:true}}));
  await page.route("**/api/integrations/zoom/proof/join", route => {
    joins++;
    return route.fulfill({json:{videoSDKJWT:"synthetic",sessionName:"test",userName:"Test"}});
  });
  await page.route("https://source.zoom.us/**", route => {
    if (!route.request().url().endsWith('.umd.js')) return route.fulfill({body:""});
    loads++;
    if (loads === 1) return route.abort();
    return route.fulfill({contentType:"application/javascript",body:`window.UIToolkit={joinSession(){},onSessionJoined(){},onSessionClosed(){},onSessionDestroyed(){}};`});
  });
  await page.goto("/zoom-proof.html");
  await page.getByRole("button",{name:"Start Zoom preview"}).click();
  await expect(page.getByRole("status")).toContainText("No join token was issued");
  expect(joins).toBe(0);
  await page.getByRole("button",{name:"Start Zoom preview"}).click();
  await expect(page.getByRole("status")).toContainText("Complete the Zoom device preview");
  expect(joins).toBe(1);
});

test("Zoom proof stays disabled without explicit setup and loads no Zoom code", async ({ page }) => {
  const providerRequests: string[] = [];
  page.on("request", request => {
    if (request.url().includes("source.zoom.us")) providerRequests.push(request.url());
  });
  await page.route("**/api/integrations/zoom/proof", route => route.fulfill({
    json: { configured: false, enabled: false },
  }));
  await page.goto("/zoom-proof.html");
  await expect(page.getByRole("heading", { name: "Zoom connection test" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start Zoom preview" })).toBeDisabled();
  await expect(page.getByRole("status")).toContainText("Add ZOOM_VIDEO_SDK_KEY");
  expect(providerRequests).toEqual([]);
  await page.screenshot({ path: "/tmp/explore-zoom-proof.png", fullPage: true });
});
