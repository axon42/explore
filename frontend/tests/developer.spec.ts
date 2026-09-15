import { selectOption } from "./select";
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { startTest } from './prepared';

test('admin diagnostics captures a synthetic model exchange and locks access', async ({page, request}) => {
  // This is only the disposable test server's key, never the user's data directory.
  const directory = process.env.EXPLORE_TEST_DATA_DIR || resolve(import.meta.dirname, '../../data/browser-tests');
  const key = readFileSync(resolve(directory, 'developer-admin.key'), 'utf8');
  const draft = await (await request.post('/api/workspaces/default/meetings', {data: {title: 'Diagnostic interview'}})).json();
  const detail = await startTest(request, draft.meeting.id);
  await page.goto('/');
  await page.getByRole('button', {name: 'Developer', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Unlock diagnostics'})).toBeVisible();
  expect((await request.get('/api/developer/requests')).status()).toBe(403);
  await page.getByLabel('Admin key', {exact: true}).fill(key);
  await page.getByRole('button', {name: 'Unlock', exact: true}).click();
  await page.getByRole('button', {name: 'Record request / response bodies', exact: true}).click();
  await expect(page.getByText(/Body recording on/)).toBeVisible();
  const text = 'What happened during the last approval? <img src=x onerror="window.__injected=true">';
  await request.post(`/api/sessions/${detail.session.id}/inject`, {data: {
    event_id: 'diag-event', segment_id: 'diag-segment', revision: 1, text,
    is_final: true, speaker_id: 'cofounder', start_ms: 0, end_ms: 5000,
  }});
  const requests = page.getByRole('region', {name: 'Model requests', exact: true});
  const row = requests.getByRole('button').filter({hasText: 'Diagnostic interview'}).first();
  await expect(row).toContainText('ok', {timeout: 15000});
  await row.click();
  const selected = page.getByRole('region', {name: 'Selected model request'});
  await expect(selected.locator('pre').nth(1)).toContainText('analysis_context');
  await expect(selected.locator('pre').nth(1)).toContainText('window.__injected');
  await expect(selected.locator('pre').nth(2)).toContainText('spoken_questions');
  expect(await page.evaluate(() => '__injected' in window)).toBe(false);
  await expect(selected.locator('img')).toHaveCount(0);
  await selectOption(page.getByLabel('Request outcome'), 'error');
  await expect(requests.getByRole('button')).toHaveCount(0);
  await selectOption(page.getByLabel('Request outcome'), '');
  await page.getByLabel('Search requests').fill('unmatched synthetic title');
  await expect(requests.getByRole('button')).toHaveCount(0);
  await page.getByLabel('Search requests').fill('Diagnostic interview');
  await expect(row).toBeVisible();
  await page.screenshot({path: '/tmp/explore-developer-desktop.png', fullPage: true});
  await page.setViewportSize({width: 760, height: 900});
  await page.screenshot({path: '/tmp/explore-developer-narrow.png', fullPage: true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole('button', {name: 'Clear diagnostic history', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Cancel', exact: true})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(row).toBeVisible();
  await page.getByRole('button', {name: 'Clear diagnostic history', exact: true}).click();
  await page.getByRole('button', {name: 'Clear diagnostics', exact: true}).click();
  await expect(requests.getByRole('button')).toHaveCount(0);
  expect((await request.get(`/api/sessions/${detail.session.id}`)).ok()).toBeTruthy();
  await page.getByRole('button', {name: 'Lock', exact: true}).click();
  await expect(page.getByLabel('Admin key', {exact: true})).toBeVisible();
  expect((await page.request.get('/api/developer/requests')).status()).toBe(403);
  await request.post(`/api/sessions/${detail.session.id}/stop`);
});

test('expired admin session removes already displayed diagnostics', async ({page}) => {
  let authorized = true;
  await page.route('**/api/developer/access', route => route.fulfill({json: {authorized}}));
  await page.route('**/api/developer/status', route => route.fulfill({json: {
    recording: {enabled: false, remaining_seconds: 0, retention_hours: 24, max_traces: 100}, events: [],
  }}));
  const item = {id: 'synthetic-request', meeting_title: 'Private synthetic meeting', model: 'mock', created_at: new Date().toISOString(), outcome: 'ok', metadata: {elapsed_ms: 5, segment_count: 1}};
  await page.route('**/api/developer/requests', route => route.fulfill({json: [item]}));
  await page.route('**/api/developer/requests/synthetic-request', route => route.fulfill({json: {...item, request_body: 'Sensitive synthetic dialogue'}}));
  await page.goto('/');
  await page.getByRole('button', {name: 'Developer', exact: true}).click();
  await page.getByRole('button', {name: /Private synthetic meeting/}).click();
  await expect(page.getByText('Sensitive synthetic dialogue', {exact: true})).toBeVisible();
  authorized = false;
  await expect(page.getByRole('heading', {name: 'Unlock diagnostics'})).toBeVisible();
  await expect(page.getByText('Sensitive synthetic dialogue', {exact: true})).toHaveCount(0);
});
