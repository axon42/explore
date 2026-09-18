import {test, expect} from '@playwright/test';
import {selectOption} from './select';
import {startTest} from './prepared';

test('model selection persists across tabs without dispatching analysis and disables missing keys', async ({page,context,request}) => {
  let selected = {provider:'gemini',model:'gemini-3.1-flash-lite',revision:0};
  const options = [
    {provider:'gemini',model:'gemini-3.1-flash-lite',configured:true},
    {provider:'openai',model:'gpt-5.6-terra',configured:true},
    {provider:'openai',model:'gpt-5.6-sol',configured:false},
  ];
  await context.route('**/api/settings/model',async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON();
      expect(body.revision).toBe(selected.revision);
      selected = {...body,revision:selected.revision+1};
    }
    await route.fulfill({json:{...selected,options}});
  });
  const draft = await (await request.post('/api/workspaces/default/meetings',{data:{title:'Model comparison'}})).json();
  const detail = await startTest(request,draft.meeting.id,false);
  await page.goto('/');
  await page.getByRole('button',{name:'Analysis settings',exact:true}).click();
  const model = page.getByRole('combobox',{name:'Analysis model',exact:true});
  await expect(model).toHaveAttribute('data-value','gemini:gemini-3.1-flash-lite');
  await model.click();
  await expect(page.getByRole('option',{name:'gpt-5.6-sol · API key needed',exact:true})).toHaveAttribute('aria-disabled','true');
  await page.keyboard.press('Escape');
  await selectOption(model,'openai:gpt-5.6-terra');
  await expect(model).toHaveAttribute('data-value','openai:gpt-5.6-terra');
  expect((await (await request.get(`/api/sessions/${detail.session.id}/experiment`)).json()).calls).toBe(0);
  const other = await context.newPage();
  await other.goto('/');
  await other.getByRole('button',{name:'Analysis settings',exact:true}).click();
  await expect(other.getByRole('combobox',{name:'Analysis model',exact:true})).toHaveAttribute('data-value','openai:gpt-5.6-terra');
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Analysis settings',exact:true}).click();
  await expect(model).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'/tmp/explore-model-selector-mobile.png',fullPage:false});
  await other.screenshot({path:'/tmp/explore-model-selector-desktop.png',fullPage:false});
  await other.close();
});

test('empty successful review explains the outcome without rendering model HTML', async ({page,request}) => {
  const title = `Empty review explanation ${Date.now()}`;
  const draft = await (await request.post('/api/workspaces/default/meetings',{data:{title}})).json();
  await startTest(request,draft.meeting.id,false);
  await page.route('**/api/sessions/*/experiment',async route => {
    const response=await route.fetch();
    await route.fulfill({json:{...(await response.json()),analysis_status:'ready',result:{model:'synthetic',latency_ms:5,review:{empty:true,reason:'<img src=x onerror="window.__bad=true"> Not enough detail.'}}}});
  });
  await page.goto('/');
  await page.getByRole('button',{name:title,exact:true}).click();
  await expect(page.getByText('Review completed with no new updates.',{exact:true})).toBeVisible();
  const controls = page.getByRole('region',{name:'Meeting analysis'});
  await expect(controls).toContainText('Not enough detail.');
  await expect(controls.locator('img')).toHaveCount(0);
  expect(await page.evaluate(() => '__bad' in window)).toBe(false);
});
