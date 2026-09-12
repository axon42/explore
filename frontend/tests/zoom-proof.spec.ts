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

test("bound Zoom test arms capture only after explicit host action", async ({ page }) => {
  let armed = 0;
  await page.route("**/api/integrations/zoom/proof", route => route.fulfill({ json: { configured: true, enabled: true, capture: { sid: "test", status: "ready", count: 0, error: "" } } }));
  await page.route("**/api/integrations/zoom/proof/join", route => {
    expect(route.request().postDataJSON().session_id).toBe("test");
    return route.fulfill({ json: { videoSDKJWT: "fake", sessionName: "test", userName: "Test" } });
  });
  await page.route("**/api/integrations/zoom/proof/capture", route => { armed++; return route.fulfill({ json: { status: "waiting" } }); });
  await page.route("**/api/integrations/zoom/proof/capture/stop", route => route.fulfill({ json: { status: "stopped" } }));
  await page.route("https://source.zoom.us/**", route => route.fulfill({ body: "", contentType: "text/javascript" }));
  await page.addInitScript(() => {
    let joined: () => void;
    Object.assign(window, { UIToolkit: {
      joinSession() { setTimeout(() => joined(), 0); },
      onSessionJoined(callback: () => void) { joined = callback; },
      onSessionClosed() {}, onSessionDestroyed() {},
      getClient() { return { getRealTimeMediaStreamsClient() { return {
        canStartRealTimeMediaStreams() { return true; },
        async startRealTimeMediaStreams() {}, async stopRealTimeMediaStreams() {},
      }; } }; },
    } });
  });
  await page.goto("/zoom-proof.html?session=test");
  await page.getByRole("button", { name: "Start Zoom preview" }).click();
  const capture = page.getByRole("button", { name: "Start transcription (2 minutes)" });
  await expect(capture).toBeEnabled();
  expect(armed).toBe(0);
  await capture.click();
  await expect(page.getByRole("button", { name: "Stop transcription", exact: true })).toBeVisible();
  expect(armed).toBe(1);
  await page.getByRole("button", { name: "Stop transcription", exact: true }).click();
  await expect(capture).toBeDisabled();
});

for (const code of ["zoom_bound", "zoom_proof_limit", "zoom_stopped", "unexpected"]) {
  test(`join rejection displays safe reason: ${code}`, async ({ page }) => {
    let joins = 0;
    await page.route("**/api/integrations/zoom/proof", route => route.fulfill({ json: { configured: true, enabled: true } }));
    await page.route("**/api/integrations/zoom/proof/join", route => {
      joins++;
      return route.fulfill({ status: 409, json: { code, message: "private-provider-content" } });
    });
    await page.addInitScript(() => Object.assign(window, { UIToolkit: { joinSession() {} } }));
    await page.route("https://source.zoom.us/**", route => route.fulfill({ body: "" }));
    await page.goto("/zoom-proof.html");
    await page.getByRole("button", { name: "Start Zoom preview" }).click();
    await expect(page.locator("#status")).toContainText(code === "unexpected" ? "HTTP 409" : `[${code}]`);
    await expect(page.locator("#status")).not.toContainText("private-provider-content");
    expect(joins).toBe(1);
    await expect(page.getByRole("button", { name: "Start Zoom preview" })).toBeDisabled();
  });
}

test("wrong meeting offers bound test before loading Zoom or requesting tokens", async ({ page }) => {
  const joins: string[] = [];
  await page.route("**/api/integrations/zoom/proof", route => route.fulfill({ json: {
    configured: true, enabled: true, capture: { sid: "correct-run", status: "ready", count: 0, error: "" },
  } }));
  page.on("request", request => {
    if (request.url().includes("source.zoom.us") || request.url().endsWith("/join")) joins.push(request.url());
  });
  await page.goto("/zoom-proof.html?session=wrong-run");
  await expect(page.getByRole("button", { name: "Start Zoom preview" })).toBeDisabled();
  await expect(page.getByRole("link", { name: "Open the active Zoom test" })).toHaveAttribute("href", "/zoom-proof.html?session=correct-run");
  expect(joins).toEqual([]);
  await page.getByRole("link", { name: "Open the active Zoom test" }).click();
  await expect(page.getByRole("button", { name: "Start Zoom preview" })).toBeEnabled();
});

test("participant receives a reason and kill switch releases the test", async ({ page }) => {
  let disconnected = false;
  await page.route("**/api/integrations/zoom/proof", route => route.fulfill({ json: { configured:true, enabled:true, generation:"test-generation", capture:{sid:"test",status:"ready",count:0,error:""} } }));
  await page.route("**/api/integrations/zoom/proof/join", route => route.fulfill({json:{videoSDKJWT:"fake",sessionName:"test",userName:"Test"}}));
  await page.route("**/api/integrations/zoom/proof/disconnect", route => { expect(route.request().postDataJSON().generation).toBe("test-generation"); disconnected = true; return route.fulfill({json:{status:"disconnected"}}); });
  await page.route("https://source.zoom.us/**", route => route.fulfill({body:""}));
  await page.addInitScript(() => {
    let joined: () => void;
    Object.assign(window,{UIToolkit:{
      joinSession(){setTimeout(() => joined(),0);}, onSessionJoined(cb: () => void){joined=cb;}, onSessionClosed(){},onSessionDestroyed(){},
      getClient(){return {getCurrentUserInfo(){return {isHost:false};},getRealTimeMediaStreamsClient(){return {canStartRealTimeMediaStreams(){return false;}};},async leave(){}};},
    }});
  });
  await page.goto("/zoom-proof.html?session=test");
  await page.getByRole("button",{name:"Start Zoom preview"}).click();
  await expect(page.locator("#capture-reason")).toContainText("This tab is a participant");
  await expect(page.locator("#capture")).toBeDisabled();
  await page.getByRole("button",{name:"Disconnect test"}).click();
  await expect(page.locator("#status")).toContainText("Explore disconnected");
  expect(disconnected).toBe(true);
});

test('SDK controller is initialized before subscriptions; host can end for everyone', async ({ page }) => {
  await page.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await page.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic',sessionName:'synthetic-room',userName:'Test'}}));
  await page.route('**/api/integrations/zoom/proof/capture/stop', route => route.fulfill({json:{status:'stopped'}}));
  await page.addInitScript(() => {
    let initialized = false;
    let onJoined: () => void;
    Object.assign(window, {UIToolkit:{
      joinSession() { initialized = true; setTimeout(() => onJoined(), 0); },
      onSessionJoined(cb: () => void) { if (!initialized) throw Error('Call joinSession first'); onJoined = cb; },
      onSessionClosed() { if (!initialized) throw Error('Call joinSession first'); },
      getClient() { return {getCurrentUserInfo(){return {isHost:true,audio:'computer',muted:false};},getAllUser(){return [{userId:1}];},async leave(end: boolean){if (!end) throw Error('Expected end for everyone');}};},
    }});
  });
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await expect(page.locator('#connection')).toHaveText('Connected');
  await expect(page.locator('#role')).toHaveText('Host · this tab');
  await expect(page.locator('#participants')).toContainText('Microphone on');
  await page.getByRole('button',{name:'End Zoom for everyone'}).click();
  await expect(page.locator('#status')).toContainText('Zoom ended for everyone');
});

test('SDK styles stay inside the call frame and narrow layout has no overflow', async ({page}) => {
  await page.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await page.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic',sessionName:'synthetic-room',userName:'Test'}}));
  await page.route('https://source.zoom.us/**', route => route.fulfill({contentType:route.request().url().endsWith('.css')?'text/css':'application/javascript',body:route.request().url().endsWith('.css')?'body{font-size:90px}button{padding:0!important}':'window.UIToolkit={joinSession(){},onSessionJoined(){},onSessionClosed(){}}'}));
  await page.setViewportSize({width:390,height:844});
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await expect(page.locator('#session')).toBeVisible();
  expect(await page.locator('body').evaluate(el => getComputedStyle(el).fontSize)).toBe('14px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'/tmp/explore-zoom-mobile.png',fullPage:true});
});

test('pinned real toolkit opens device preview without issuing a real token', async ({page}) => {
  test.skip(!process.env.ZOOM_TOOLKIT_FIXTURE, 'Optional smoke check against the downloaded public pinned bundle');
  const {readFile} = await import('node:fs/promises');
  const bundle = await readFile(process.env.ZOOM_TOOLKIT_FIXTURE!, 'utf8');
  const css = await readFile(process.env.ZOOM_TOOLKIT_FIXTURE!.replace(/\.js$/, '.css'), 'utf8');
  await page.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await page.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic-not-valid',sessionName:'synthetic-room',userName:'Test'}}));
  await page.route('https://source.zoom.us/**', route => route.fulfill({contentType:route.request().url().endsWith('.umd.js')?'application/javascript':'text/css',body:route.request().url().endsWith('.umd.js')?bundle:css}));
  // No authorized real token exists in this test and no Zoom session is joined.
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await expect(page.frameLocator('#session').locator('#zoom-root')).not.toBeEmpty();
  await expect(page.frameLocator('#session').getByRole('button', {name:'Join Session',exact:true})).toBeVisible();
  await expect(page.locator('#status')).toContainText('Complete the Zoom device preview');
  await page.screenshot({path:'/tmp/explore-zoom-real-sdk.png',fullPage:true});
});

test('another tab can see and end the host session', async ({context,page}) => {
  await context.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await context.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic',sessionName:'synthetic-room',userName:'Test'}}));
  await context.route('**/api/integrations/zoom/proof/capture/stop', route => route.fulfill({json:{status:'stopped'}}));
  await context.addInitScript(() => {
    let joined: () => void;
    Object.assign(window,{UIToolkit:{joinSession(){setTimeout(()=>joined(),0);},onSessionJoined(cb:()=>void){joined=cb;},onSessionClosed(){},getClient(){return {getCurrentUserInfo(){return {isHost:true};},async leave(){}};}}});
  });
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await expect(page.locator('#connection')).toHaveText('Connected');
  const observer = await context.newPage();
  await observer.goto('/zoom-proof.html');
  await expect(observer.locator('#active-tabs')).toContainText('synthetic-room');
  await observer.getByRole('button',{name:'End this session',exact:true}).click();
  await expect(page.locator('#connection')).toHaveText('Ended');
  await expect(observer.locator('#status')).toContainText('Zoom ended for everyone');
});

test('reset cancels a pending preview; late SDK completion cannot join a new test', async ({page}) => {
  await page.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await page.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic',sessionName:'synthetic-room',userName:'Test'}}));
  await page.route('**/api/integrations/zoom/proof/disconnect', route => route.fulfill({json:{generation:'new'}}));
  await page.addInitScript(() => Object.assign(window,{UIToolkit:{joinSession(){return new Promise(()=>{});},onSessionJoined(){},onSessionClosed(){}}}));
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await expect(page.locator('#session')).toBeVisible();
  await page.getByRole('button',{name:'Disconnect test'}).click();
  await expect(page.locator('#session')).toBeHidden();
  await expect(page.locator('#session')).toHaveAttribute('src','about:blank');
  await expect(page.locator('#start')).toBeDisabled();
  await expect(page.locator('#status')).toContainText('Explore disconnected');
});

test('failed host termination never reports that Zoom ended', async ({page}) => {
  await page.route('**/api/integrations/zoom/proof', route => route.fulfill({json:{configured:true,enabled:true,generation:'g'}}));
  await page.route('**/api/integrations/zoom/proof/join', route => route.fulfill({json:{videoSDKJWT:'synthetic',sessionName:'synthetic-room',userName:'Test'}}));
  await page.addInitScript(() => {
    let joined: () => void;
    Object.assign(window,{UIToolkit:{joinSession(){setTimeout(()=>joined(),0);},onSessionJoined(cb:()=>void){joined=cb;},onSessionClosed(){},getClient(){return {getCurrentUserInfo(){return {isHost:true};},async leave(){return {type:'INTERNAL_ERROR',reason:'private provider details'};}};}}});
  });
  await page.goto('/zoom-proof.html');
  await page.getByRole('button',{name:'Start Zoom preview'}).click();
  await page.getByRole('button',{name:'End Zoom for everyone'}).click();
  await expect(page.locator('#status')).toContainText('Zoom did not confirm it ended');
  await expect(page.locator('#status')).not.toContainText('private provider details');
  await expect(page.locator('#connection')).toHaveText('Connected');
  await expect(page.getByRole('button',{name:'End Zoom for everyone'})).toBeEnabled();
});
