import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
async function create(page: Page) {
  await page.goto('/');
  await page.getByRole('button', {name:'New workspace', exact:true}).click();
  await page.getByRole('dialog').getByLabel('Name').fill('Audio '+Date.now());
  await page.getByRole('button',{name:'Create',exact:true}).click();
  await page.getByRole('button',{name:'New meeting',exact:true}).first().click();
  await page.getByRole('dialog').getByLabel('Name').fill('Audio interview');
  await page.getByRole('button',{name:'Create',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Audio interview'})).toBeVisible();
}
test('audio capture requires explicit consent and can be stopped independently of the meeting', async ({page}) => {
  let current: Record<string,unknown> | null = null;
  let starts = 0;
  const state = () => ({supported:true,helper_ready:true,configured:true,max_seconds:120,capture:current});
  await page.route('**/api/audio-capture', route => route.fulfill({json:state()}));
  await page.route('**/api/sessions/*/audio-capture', route => {
    expect(route.request().postDataJSON()).toEqual({consent:true});
    const sid = route.request().url().split('/').at(-2);
    starts++;
    current = {id:'capture-1',sid,status:'capturing',error:'',elapsed_seconds:3,microphone_level:.2,system_level:.1,segments:0};
    return route.fulfill({json:state()});
  });
  await page.route('**/api/sessions/*/audio-capture/stop', route => {
    expect(route.request().postDataJSON()).toEqual({capture_id:'capture-1'});
    current = {...current,status:'stopped'};
    return route.fulfill({json:state()});
  });
  await create(page);
  await page.getByRole('button',{name:'Capture audio',exact:true}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button',{name:'Start capture',exact:true})).toBeDisabled();
  expect(starts).toBe(0);
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button',{name:'Start capture',exact:true}).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button',{name:'Stop capture',exact:true})).toBeVisible();
  await expect(page.getByRole('meter')).toHaveCount(2);
  await page.screenshot({path:'/tmp/explore-audio-capture.png',fullPage:true});
  await page.getByRole('button',{name:'Stop capture',exact:true}).click();
  await expect(page.getByText('Capture stopped. Accepted transcripts are saved.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Next turn',exact:true})).toBeEnabled();
});

test('missing capture setup leaves replay usable, with a responsive panel', async ({page}) => {
  await page.route('**/api/audio-capture',route=>route.fulfill({json:{supported:true,helper_ready:true,configured:false,max_seconds:120,capture:null}}));
  await create(page);
  await expect(page.getByRole('button',{name:'Capture audio',exact:true})).toBeDisabled();
  await expect(page.getByText('Add DEEPGRAM_API_KEY', {exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Next turn',exact:true})).toBeEnabled();
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('.ex-audio-capture')).toBeVisible();
  const box = await page.locator('.ex-audio-capture').boundingBox();
  expect(box!.width).toBeLessThanOrEqual(390);
});
