import { selectOption } from "./select";
import { test, expect } from "@playwright/test";
import { startTest } from "./prepared";

test("confirm and correct speakers without changing text; accessible narrow layout", async ({ page, request }) => {
  const workspace = await (await request.post('/api/workspaces', { data: {name:'Speaker UI '+Date.now()} })).json();
  const meeting = await (await request.post(`/api/workspaces/${workspace.id}/meetings`, { data:{title:'Synthetic voices'} })).json();
  const mid = meeting.meeting.id;
  const detail = await startTest(request, mid);
  const sid = detail.session.id;
  const roster = await (await request.get(`/api/meetings/${mid}/participants`)).json();
  const person = roster.participants[1];
  let version = 0; let assigned: string | null = null; let passagePerson: string | null | undefined;
  const changes: Record<string,unknown>[] = [];
  const original = '😀 Slow approval. No, it works.';
  const text = Array.from(original);
  const split = Array.from('😀 Slow approval.').length;
  await page.route(`**/api/sessions/${sid}`, async route => {
    const snapshot = await (await route.fetch()).json();
    const spans = [[0,split],[split,text.length]].map(([start,end], index) => {
      const id = index === 0 ? (passagePerson !== undefined ? passagePerson : assigned) : null;
      const selected = roster.participants.find((p:{participant_id:string}) => p.participant_id === id);
      return {index,start,end,track_id:`voice-${index}`,name:selected?.name ?? `Remote speaker ${index+1}`,participant_id:id,
        interview_role:selected?.interview_role ?? 'unknown',status:selected?'confirmed':'unassigned',scope:'track',needs_review:false};
    });
    await route.fulfill({json:{...snapshot,segments:[{event_id:'synthetic',segment_id:'synthetic',revision:0,speaker_id:'system',speaker_name:'System audio',start_ms:0,end_ms:5000,text:original,is_final:true,attributions:spans}]}});
  });
  await page.route(`**/api/meetings/${mid}/sessions/${sid}/speakers`, async route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); changes.push(body);
      expect(body.version).toBe(version); expect(body.roster_revision).toBe(roster.revision);
      version++;
      if (body.track_id) assigned = body.participant_id; else passagePerson = body.participant_id;
    }
    await route.fulfill({json:{version,roster_revision:roster.revision,participants:roster.participants,history:[],tracks:[
      {id:'voice-0',channel:'system',label:0,capture_id:'connection',method:'diarized',participant_id:assigned,needs_review:false,excerpt:'😀 Slow approval.'},
      {id:'voice-1',channel:'system',label:1,capture_id:'connection',method:'diarized',participant_id:null,needs_review:false,excerpt:'No, it works.'},
    ]}});
  });
  await page.goto(`/#${mid}`);
  await selectOption(page.getByLabel("Workspace",{exact:true}), workspace.id);
  await expect(page.getByRole('heading',{name:'Synthetic voices'})).toBeVisible();
  const transcript = page.locator('.ex-transcript-list');
  await expect(transcript.locator('article')).toHaveCount(2);
  await expect(transcript).toContainText('😀 Slow approval.');
  await expect(transcript).toContainText('No, it works.');
  const speakers = page.getByRole('region',{name:'Speakers',exact:true});
  await speakers.locator('summary').first().click();
  await selectOption(speakers.getByLabel('Person for voice 1'), person.participant_id);
  await speakers.getByRole('button',{name:'Confirm speaker',exact:true}).click();
  await expect(transcript.locator('article').first()).toContainText(person.name);
  await expect(transcript.locator('.ex-speaker-role').first()).toHaveText('customer');
  await transcript.getByRole('button',{name:'Correct speaker'}).first().click();
  const dialog = page.getByRole('dialog',{name:'Correct this passage'});
  await expect(dialog).toContainText('😀 Slow approval.');
  await selectOption(dialog.getByLabel('Person for this passage'), roster.participants[0].participant_id);
  await dialog.getByRole('button',{name:'Confirm speaker',exact:true}).click();
  await expect(dialog).not.toBeVisible();
  await expect(transcript.locator('.ex-speaker-role').first()).toHaveText('interviewer');
  expect(changes[1]).toMatchObject({segment_id:'synthetic',segment_revision:0,span_index:0});
  await expect(transcript).toContainText('😀 Slow approval.');
  await page.setViewportSize({width:390,height:844});
  await transcript.getByRole('button',{name:'Correct speaker'}).first().click();
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.width).toBeLessThanOrEqual(390);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'/tmp/explore-speakers-ui.png',fullPage:true});
  await page.getByRole('button',{name:'Brief',exact:true}).click();
  await expect(page.getByLabel('Speaker ID',{exact:true})).toHaveCount(0);
  await expect(page.getByLabel('Name',{exact:true}).first()).toHaveValue(roster.participants[0].name);
});

test("microphone identity is an explicit selection and resets on reopening", async ({page,request}) => {
  const meeting = await (await request.post('/api/workspaces/default/meetings',{data:{title:'Mic setup'}})).json();
  const detail = await startTest(request,meeting.meeting.id);
  const sid = detail.session.id;
  const roster = await (await request.get(`/api/meetings/${meeting.meeting.id}/participants`)).json();
  let state: Record<string,unknown>|null = null;
  const view = () => ({configured:true,supported:true,helper_ready:true,max_seconds:0,capture:state});
  await page.route('**/api/audio-capture', route => route.fulfill({json:view()}));
  await page.route(`**/api/sessions/${sid}/audio-capture`, route => {
    expect(route.request().postDataJSON()).toEqual({consent:true,microphone_participant_id:roster.participants[0].participant_id,roster_revision:roster.revision});
    state = {id:'synthetic',sid,status:'capturing',error:'',elapsed_seconds:0,microphone_level:0,system_level:0,segments:0};
    return route.fulfill({json:view()});
  });
  await page.goto(`/#${meeting.meeting.id}`);
  await page.getByRole('button',{name:'Capture audio',exact:true}).click();
  const dialog = page.getByRole('dialog',{name:'Capture this conversation'});
  const choice = dialog.getByLabel('Who is using this microphone?');
  await expect(choice).toHaveAttribute("data-value", '');
  await selectOption(choice, roster.participants[0].participant_id);
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Capture audio',exact:true}).click();
  await expect(choice).toHaveAttribute("data-value", '');
  await selectOption(choice, roster.participants[0].participant_id);
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button',{name:'Start capture',exact:true}).click();
  await expect(page.getByRole('button',{name:'Stop capture',exact:true})).toBeVisible();
});
