import { expect, test } from "@playwright/test";

test("create, replay evolving transcript, stop, and reload persisted history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByRole("button", { name: "New session", exact: false })
    .first()
    .click();
  const title = `Product conversation ${Date.now()}`;
  await page.getByLabel("Session title").fill(title);
  await page.getByRole("button", { name: "Create session" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.locator('[data-final="false"]')).toBeVisible();
  await expect(page.getByText("Live draft", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "I grouped them by priority. There are four we should look at today.",
    ),
  ).toBeVisible({ timeout: 20000 });
  await expect(
    page.getByText(
      "That sounds good. Let's start with the onboarding request and go from there.",
    ),
  ).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("segment")).toHaveCount(3);
  await expect(page.locator('[data-final="false"]')).toHaveCount(0);
  await page.screenshot({
    path: "test-results/live-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Stop session" }).click();
  await expect(
    page.getByText("Session complete", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByTestId("segment")).toHaveCount(3);
  await expect(
    page.getByText("Session complete", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Start demo" })).toHaveCount(0);
  await page.screenshot({
    path: "test-results/stopped-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/stopped-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("disconnects and reconnects to a consistent saved snapshot", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    const Original = window.WebSocket;
    window.WebSocket = class extends Original {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        (window as unknown as { testSocket: WebSocket }).testSocket = this;
      }
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New session" }).first().click();
  await page.getByLabel("Session title").fill("Reconnect check");
  await page.getByRole("button", { name: "Create session" }).click();
  await expect(
    page.getByRole("heading", { name: "Reconnect check" }),
  ).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  const id = new URL(page.url()).hash.slice(1);
  await page.evaluate(() =>
    (window as unknown as { testSocket: WebSocket }).testSocket.close(),
  );
  await expect(page.getByText("Disconnected", { exact: true })).toBeVisible();
  // A change committed while disconnected must arrive in the next snapshot.
  await request.post(`/api/sessions/${id}/stop`);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Session complete", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reconnect check" }),
  ).toBeVisible();
});

test("keeps the reading position and offers jump to latest", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New session" }).first().click();
  await page.getByLabel("Session title").fill("Scroll check");
  await page.getByRole("button", { name: "Create session" }).click();
  await expect(
    page.getByRole("heading", { name: "Scroll check" }),
  ).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  async function produce(start: number, count: number) {
    await page.evaluate(
      async ({ start, count }) => {
        const socket = new WebSocket(
          `ws://${location.host}/api/sessions/${location.hash.slice(1)}/ingest`,
        );
        await new Promise<void>((resolve, reject) => {
          socket.onopen = () => resolve();
          socket.onerror = reject;
        });
        try {
          for (let index = start; index < start + count; index++) {
            const ack = new Promise<void>((resolve, reject) => {
              socket.onmessage = (event) =>
                JSON.parse(event.data).outcome === "accepted"
                  ? resolve()
                  : reject(new Error(event.data));
            });
            socket.send(
              JSON.stringify({
                event_id: `scroll-${index}`,
                segment_id: `scroll-${index}`,
                revision: 1,
                speaker_id: "Alex",
                speaker_name: "Alex",
                start_ms: index * 1000,
                end_ms: (index + 1) * 1000,
                text: `Discussion point ${index}. We will review this request in the next team meeting.`,
                is_final: true,
              }),
            );
            await ack;
          }
        } finally {
          socket.close();
        }
      },
      { start, count },
    );
  }
  await produce(0, 25);
  await expect(page.getByTestId("segment")).toHaveCount(25);
  const transcript = page.locator(".transcript-scroll");
  await expect
    .poll(() =>
      transcript.evaluate(
        (element) =>
          element.scrollHeight - element.scrollTop - element.clientHeight,
      ),
    )
    .toBeLessThan(100);
  await transcript.evaluate((element) => {
    element.scrollTop = 0;
  });
  await expect(
    page.getByRole("button", { name: "Jump to latest" }),
  ).toBeVisible();
  await produce(25, 1);
  await expect(page.getByTestId("segment")).toHaveCount(26);
  expect(await transcript.evaluate((element) => element.scrollTop)).toBe(0);
  await page.getByRole("button", { name: "Jump to latest" }).click();
  await expect
    .poll(() =>
      transcript.evaluate(
        (element) =>
          element.scrollHeight - element.scrollTop - element.clientHeight,
      ),
    )
    .toBeLessThan(100);
  await page.getByRole("button", { name: "Stop session" }).click();
  await expect(
    page.getByText("Session complete", { exact: true }),
  ).toBeVisible();
});
