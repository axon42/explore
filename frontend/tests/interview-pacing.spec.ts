import { test, expect } from '@playwright/test';
import { groupTranscript } from '../src/explore/transcript';
import type { Segment } from '../src/types';

test('groups nearby speech without losing source identities', () => {
  const segment = (id: string, start: number, speaker = 'customer') => ({segment_id: id, speaker_id: speaker, start_ms: start, end_ms: start + 1000, text: id, is_final: true}) as Segment;
  const groups = groupTranscript([segment('a', 0), segment('b', 3000), segment('c', 7000, 'host'), segment('d', 20000, 'host')]);
  expect(groups.map(g => g.map(s => s.segment_id))).toEqual([['a', 'b'], ['c'], ['d']]);
});

test('frequency, discard restore, grouping and archive controls persist', async ({page, request}) => {
  const workspace = await (await request.post('/api/workspaces', {data:{name:'Pacing test'}})).json();
  const detail = await (await request.post(`/api/workspaces/${workspace.id}/meetings`, {data:{title:'Pacing interview'}})).json();
  await page.goto('/');
  await page.getByLabel('Workspace', {exact:true}).selectOption(workspace.id);
  await expect(page.getByRole('heading',{name:'Pacing interview'})).toBeVisible();
  await page.getByLabel('Question frequency').selectOption('120');
  await expect.poll(async () => (await (await request.get(`/api/meetings/${detail.meeting.id}`)).json()).meeting.question_interval).toBe(120);
  for (const [i,text] of ['We use a spreadsheet to prepare reports.', 'The checks take two hours each Friday.'].entries()) {
    await request.post(`/api/sessions/${detail.session.id}/inject`, {data:{event_id:`event-${i}`,segment_id:`part-${i}`,revision:1,speaker_id:'customer',speaker_name:'Customer',start_ms:i*2000,end_ms:i*2000+1000,text,is_final:true}});
  }
  await expect(page.locator('.ex-transcript-list article')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'Discard',exact:true})).toBeVisible();
  await page.locator('.ex-question-title').click();
  await expect(page.locator('.ex-transcript-list span.highlight')).toHaveCount(1);
  await page.getByRole('button',{name:'Discard',exact:true}).click();
  await expect(page.locator('.ex-question')).toHaveCount(0);
  await page.getByRole('button',{name:/discarded/}).click();
  await expect(page.getByRole('button',{name:'Restore',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Restore',exact:true}).click();
  await page.getByRole('button',{name:/queued/}).click();
  await expect(page.getByRole('button',{name:'Mark asked',exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/pacing-interview.png',fullPage:true});
  await expect(page.getByRole('button',{name:'Archive meeting',exact:true})).toBeDisabled();
  await request.post(`/api/sessions/${detail.session.id}/stop`);
  await expect(page.getByRole('button',{name:'Archive meeting',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Archive meeting',exact:true}).click();
  await expect(page.getByRole('button',{name:'Restore meeting',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation',{name:'Meetings',exact:true}).getByText('Pacing interview')).toHaveCount(0);
  await page.getByRole('button',{name:'Show archived meetings',exact:true}).click();
  await expect(page.getByRole('navigation',{name:'Meetings',exact:true}).getByText('Pacing interview')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Question frequency')).toHaveValue('120');
  await page.getByRole('button',{name:'Restore meeting',exact:true}).click();
  await expect(page.getByRole('navigation',{name:'Meetings',exact:true}).getByText('Pacing interview')).toBeVisible();
});
