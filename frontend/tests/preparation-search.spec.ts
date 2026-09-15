import { selectOption } from "./select";
import { test, expect } from "@playwright/test";

test("draft gate, real interview, hidden test tools and sidebar search", async ({page,request}) => {
  await request.put('/api/settings/test-mode',{data:{enabled:false}});
  const workspace = await (await request.post('/api/workspaces',{data:{name:'Prepared interviews'}})).json();
  const draft = await (await request.post(`/api/workspaces/${workspace.id}/meetings`,{data:{title:'Pharmacy discovery'}})).json();
  await request.post(`/api/workspaces/${workspace.id}/meetings`,{data:{title:'Supplier research'}});
  expect(draft.session).toBeNull();
  await page.goto('/');
  await selectOption(page.getByLabel('Workspace',{exact:true}), workspace.id);
  await page.getByRole('navigation',{name:'Meetings',exact:true}).getByRole('button',{name:'Pharmacy discovery'}).click();
  await expect(page.getByText('Draft',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Play',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Capture audio',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Start interview',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('named interviewer');
  const roster = [{speaker_id:'interviewer',name:'Alex',interview_role:'interviewer'}, {speaker_id:'customer',name:'Sam',interview_role:'customer'}];
  await request.put(`/api/meetings/${draft.meeting.id}/participants`,{data:{revision:0,participants:roster}});
  await page.reload();
  await page.getByRole('button',{name:'Start interview',exact:true}).click();
  await expect(page.getByRole('button',{name:'End interview',exact:true})).toBeVisible();
  await page.getByRole('switch',{name:'Test mode',exact:true}).click();
  await expect(page.getByRole('switch',{name:'Test mode',exact:true})).toHaveAttribute('aria-checked','true');
  await expect(page.getByRole('button',{name:'Play',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Reset test',exact:true})).toHaveCount(0);
  await page.getByRole('searchbox',{name:'Search meetings'}).fill('pharmacy');
  const nav = page.getByRole('navigation',{name:'Meetings',exact:true});
  await expect(nav.getByRole('button')).toHaveCount(1);
  await page.getByRole('searchbox',{name:'Search meetings'}).fill('missing');
  await expect(page.getByText('No matching meetings.')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Pharmacy discovery'})).toBeVisible();
  await page.getByRole('button',{name:'End interview',exact:true}).click();
  await expect(page.getByText('Stopped',{exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/prepared-meeting.png',fullPage:true});
});

test("public product tour search, evidence and mobile layout", async ({page}) => {
  let apiCalls = 0;
  page.on('request', r => { if (r.url().includes('/api/')) apiCalls++; });
  const errors:string[]=[]; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/website-preview/product.html');
  await page.getByLabel('Search meetings',{exact:true}).fill('missing');
  await expect(page.getByText('No matching meetings.')).toBeVisible();
  await page.getByLabel('Search meetings',{exact:true}).fill('weekly');
  await page.getByRole('navigation',{name:'Sample meetings'}).getByRole('button').click();
  await page.getByRole('button',{name:/See the supporting words/}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:/03.*Reflect/}).click();
  await expect(page.getByText('Workflow gap · Weekly reporting')).toBeVisible();
  await page.screenshot({path:'test-results/product-tour-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/product-tour-mobile.png',fullPage:true});
  expect(errors).toEqual([]); expect(apiCalls).toBe(0);
});

test("overview groups only explicit workflow relationships", async ({page,request}) => {
  const {startTest} = await import('./prepared');
  const workspace = await (await request.post('/api/workspaces',{data:{name:'Workflow review'}})).json();
  const draft = await (await request.post(`/api/workspaces/${workspace.id}/meetings`,{data:{title:'Inventory handoff'}})).json();
  const detail = await startTest(request,draft.meeting.id);
  const workflows = [{key:'approval',topic_id:'stock',title:'Stock approval'},{key:'approval',topic_id:'returns',title:'Supplier returns'}];
  const findings = [
    {id:'gap',kind:'gap',title:'Wait for sign-off',body:'The order waits for approval.',basis:'observed',topic_id:'stock',workflow_key:'approval',evidence:[]},
    {id:'possibility',kind:'opportunity',title:'Earlier return checks',body:'Explore this hypothesis in another interview.',basis:'inferred',topic_id:'returns',workflow_key:'approval',evidence:[]},
    {id:'unassigned',kind:'gap',title:'An unresolved detail',body:'Its relationship is not established.',basis:'observed',topic_id:'',workflow_key:'',evidence:[]}
  ];
  await page.route(`**/api/meetings/${draft.meeting.id}`, route => route.fulfill({json:{...detail,overview:'Two workflows with distinct approval steps.',workflows,findings}}));
  await page.goto('/');
  await selectOption(page.getByLabel('Workspace',{exact:true}), workspace.id);
  await page.getByRole('button',{name:'Overview',exact:true}).click();
  const stock = page.locator('.ex-workflow-group').filter({has:page.getByRole('heading',{name:'Stock approval',exact:true})});
  await expect(stock).toContainText('Wait for sign-off');
  await expect(stock).not.toContainText('Earlier return checks');
  await expect(page.locator('.ex-workflow-group').filter({has:page.getByRole('heading',{name:'Not linked to a workflow'})})).toContainText('An unresolved detail');
  await page.screenshot({path:'test-results/workflow-groups.png',fullPage:true});
});
