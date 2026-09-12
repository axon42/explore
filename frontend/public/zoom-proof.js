import { loadZoom, boundedSdkCall } from './zoom-sdk.js';
const $ = id => document.getElementById(id);
const sessionId = new URLSearchParams(location.search).get('session');
const tabId = crypto.randomUUID();
const channel = new BroadcastChannel('explore-zoom-test');
const peers = new Map();
let generation, adapter, room, joined = false, disconnected = false, captureRequested = false;
let captureTimer, ending = false, polling = false, remoteEndTimer;
const messages = {
  zoom_stale: 'This test was disconnected in another tab. Reload before joining.',
  zoom_bound: 'Zoom is bound to another meeting. Use its active Zoom test link.',
  zoom_stopped: 'This Explore session has ended. Create a fresh meeting.',
  zoom_not_empty: 'This meeting already has transcript data. Create a fresh meeting for the Zoom test.',
  zoom_proof_limit: 'All four join tokens have been issued. End Zoom, then Disconnect test before retrying.',
  zoom_disabled: 'The Zoom test is disabled on the backend.',
  zoom_unconfigured: 'Zoom SDK credentials are missing on the backend.',
  invalid_origin: 'Open the test from the configured localhost Explore address.',
  not_found: 'This session no longer exists. Open the current meeting’s Zoom test link.',
};
const options = () => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation})});
async function request(path, init) {
  const response = await fetch('/api/integrations/zoom/proof' + path, {...init, signal:AbortSignal.timeout(10000)});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(Object.hasOwn(messages, body.code) ? `${messages[body.code]} [${body.code}]` : `Explore request failed (HTTP ${response.status}).`);
    error.safeForDisplay = true; throw error;
  }
  return body;
}
function safe(error, fallback) { return error?.safeForDisplay ? error.message : fallback; }
function client() { return adapter?.client(); }
function host() { return joined && client()?.getCurrentUserInfo?.()?.isHost === true; }
function announce() {
  channel.postMessage({kind:'state',tabId,generation,joined,host:host(),room});
}
function renderActivity() {
  for (const [id, peer] of peers) if (Date.now() - peer.seen > 7000) peers.delete(id);
  $('active-tabs').replaceChildren();
  for (const [id, peer] of peers) {
    if (!peer.joined) continue;
    const li = document.createElement('li');
    li.textContent = `${peer.host ? 'Host' : 'Participant'} · ${peer.room || id.slice(0,6)}`;
    if (peer.host) {
      const end = document.createElement('button');
      end.className = 'secondary'; end.textContent = 'End this session'; end.disabled = ending;
      end.onclick = () => requestRemoteEnd(peer.generation); li.append(end);
    }
    $('active-tabs').append(li);
  }
  $('end-session').disabled = ending || (!host() && ![...peers.values()].some(peer => peer.host && peer.joined && peer.generation === generation));
  if (joined) {
    const info = client()?.getCurrentUserInfo?.();
    $('role').textContent = info?.isHost ? 'Host · this tab' : 'Participant · this tab';
    $('participants').textContent = `${client()?.getAllUser?.()?.length ?? 1} participant(s) · ${info?.audio !== 'computer' ? 'Join computer audio in Zoom' : info.muted ? 'Microphone muted' : 'Microphone on'}`;
  }
}
channel.onmessage = event => {
  const msg = event.data;
  if (!msg || msg.tabId === tabId) return;
  if (msg.kind === 'state') {
    peers.set(msg.tabId, {joined:msg.joined === true,host:msg.host === true,generation:msg.generation,room:typeof msg.room === 'string' ? msg.room.slice(0,128) : '',seen:Date.now()}); renderActivity();
  } else if (msg.kind === 'end' && msg.generation === generation && host()) void endZoom();
  else if (msg.kind === 'ended') {
    clearTimeout(remoteEndTimer); ending = false;
    $('status').textContent = 'Zoom ended for everyone. Disconnect test to clear the binding before a new test.';
    renderActivity();
  }
};
function checkCapture() {
  $('capture').disabled = true;
  if (!sessionId) { $('capture-reason').textContent = 'Open this test from an Explore meeting to save transcripts.'; return; }
  if (disconnected || captureRequested) return;
  if (!joined) { $('capture-reason').textContent = 'Join the Zoom session before starting transcription.'; return; }
  try {
    const rtms = client()?.getRealTimeMediaStreamsClient?.();
    if (!rtms) { $('capture-reason').textContent = 'Zoom SDK did not expose RTMS controls. Capture is unavailable in this client.'; return; }
    if (client()?.getCurrentUserInfo?.()?.isHost === false) { $('capture-reason').textContent = 'This tab is a participant. Start transcription from the host tab.'; return; }
    if (rtms.isSupportRealTimeMediaStreams?.() === false) { $('capture-reason').textContent = 'RTMS is unavailable for this Zoom session. Check account RTMS enablement.'; return; }
    if (!rtms.canStartRealTimeMediaStreams()) { $('capture-reason').textContent = 'Zoom is not ready for RTMS. Checking automatically…'; return; }
    $('capture').disabled = false;
    $('capture-reason').textContent = 'Host ready. Unmute your microphone before speaking.';
  } catch { $('capture-reason').textContent = 'Zoom capability check failed. End this call and reconnect. [sdk_capability]'; }
}
function requestRemoteEnd(targetGeneration) {
  ending = true; renderActivity();
  channel.postMessage({kind:'end',generation:targetGeneration,tabId});
  $('status').textContent = 'Asking the host tab to end Zoom…';
  remoteEndTimer = setTimeout(() => {
    ending = false; renderActivity();
    $('status').textContent = 'Host did not confirm. End Zoom from its host tab; the call may still be running.';
  }, 10000);
}
async function endZoom() {
  if (ending) return;
  if (!host()) { requestRemoteEnd(generation); return; }
  ending = true; renderActivity();
  try {
    const result = await boundedSdkCall(client().leave(true));
    if (result && typeof result === 'object' && result.type) throw new Error('end_failed');
    joined = false; clearTimeout(captureTimer);
    await request('/capture/stop', options()).catch(() => {});
    $('connection').textContent = 'Ended'; $('role').textContent = 'Call ended';
    $('capture').disabled = true; $('stop-capture').hidden = true;
    $('status').textContent = 'Zoom ended for everyone. Disconnect test to clear the binding before a new test.';
    channel.postMessage({kind:'ended',generation,tabId}); announce();
  } catch { $('status').textContent = 'Zoom did not confirm it ended. Use End for everyone in the Zoom call and retry. [sdk_end_failed]'; }
  finally { ending = false; renderActivity(); }
}
$('end-session').onclick = () => void endZoom();
$('kill').onclick = async () => {
  $('kill').disabled = true;
  try {
    await request('/disconnect', options());
    disconnected = true; clearTimeout(captureTimer);
    $('start').disabled = true; $('capture').disabled = true; $('stop-capture').hidden = true;
    // Keep an active host connected so the explicit End control remains available.
    if (!joined) { $('session').hidden = true; $('session').src = 'about:blank'; $('placeholder').hidden = false; }
    $('status').textContent = 'Explore disconnected. End any active Zoom call, then reload to start a new test.';
    $('capture-reason').textContent = 'Old stream events cannot enter the next test. Saved transcript is retained.';
    $('connection').textContent = joined ? 'Call still connected' : 'Disconnected';
  } catch (error) { $('status').textContent = safe(error, 'Disconnection failed. Check backend connection.'); $('kill').disabled = false; }
};
async function endCapture() {
  clearTimeout(captureTimer);
  try {
    const result = await boundedSdkCall(client()?.getRealTimeMediaStreamsClient().stopRealTimeMediaStreams());
    if (result && typeof result === 'object' && result.type) throw new Error('stop_failed');
    await request('/capture/stop', options());
    $('capture-status').textContent = 'Transcription stopped';
  } catch { $('capture-status').textContent = 'Stop could not be confirmed. End Zoom for everyone. [capture_stop_failed]'; }
  $('stop-capture').hidden = true;
}
$('capture').onclick = async () => {
  $('capture').disabled = true; captureRequested = true;
  try {
    await request('/capture', options());
    const result = await boundedSdkCall(client().getRealTimeMediaStreamsClient().startRealTimeMediaStreams());
    if (result && typeof result === 'object' && result.type) throw new Error('start_failed');
    $('stop-capture').hidden = false;
    $('capture-status').textContent = 'Waiting for Zoom webhook and transcripts…';
    $('capture-reason').textContent = 'Speak with your microphone on. Capture stops after two minutes.';
    captureTimer = setTimeout(() => void endCapture(), 120000);
  } catch (error) {
    $('capture-status').textContent = safe(error, 'Capture could not start. Check RTMS eligibility and end the test call. [capture_start_failed]');
    await request('/capture/stop', options()).catch(() => {});
  }
};
$('stop-capture').onclick = () => void endCapture();
$('capture').hidden = !sessionId; $('capture-status').hidden = !sessionId;
try {
  const state = await request(''); generation = state.generation;
  $('kill').disabled = false;
  $('start').disabled = !state.configured || !state.enabled;
  $('status').textContent = !state.configured ? 'Add ZOOM_VIDEO_SDK_KEY and ZOOM_VIDEO_SDK_SECRET to .env, then restart.' : !state.enabled ? 'Enable ZOOM_PROOF_ENABLED on the backend to test.' : 'Ready. The first join is the host.';
  if (state.capture?.sid && state.capture.sid !== sessionId) {
    $('start').disabled = true;
    $('status').textContent = 'Another meeting is bound to Zoom. Open its test or disconnect the pending connection.';
    $('bound-session').href = '/zoom-proof.html?session=' + encodeURIComponent(state.capture.sid);
    $('bound-session').hidden = false;
  }
  checkCapture();
} catch { $('status').textContent = 'Backend unavailable. Start Explore and reload.'; }
setInterval(async () => {
  try { renderActivity(); announce(); } catch { /* An SDK teardown may briefly invalidate the client. */ }
  if (disconnected || polling || !generation) return;
  polling = true;
  try {
    const state = await request('');
    if (state.generation !== generation) {
      disconnected = true; $('capture').disabled = true; $('start').disabled = true;
      clearTimeout(captureTimer);
      if (!joined) { $('session').hidden = true; $('session').src = 'about:blank'; }
      $('status').textContent = 'This test was disconnected in another tab. End any active call, then reload.';
      return;
    }
    checkCapture();
    if (state.capture?.sid === sessionId) {
      const capture = state.capture;
      $('capture-status').textContent = `${capture.status} · ${capture.count} transcript packets${capture.error ? ' · ' + capture.error : ''}`;
    }
  } catch { $('capture-reason').textContent = 'Explore backend unavailable. End Zoom for everyone.'; }
  finally { polling = false; }
}, 2000);
$('join').addEventListener('submit', async event => {
  event.preventDefault(); $('start').disabled = true;
  $('status').textContent = 'Loading Zoom preview…';
  let stage = 'toolkit';
  try {
    adapter = await loadZoom($('session'));
    if (disconnected) return;
    stage = 'token';
    const config = await request('/join', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation,name:$('name').value,...(sessionId ? {session_id:sessionId} : {})})});
    if (disconnected) return;
    stage = 'preview'; room = config.sessionName;
    $('room').textContent = room; $('role').textContent = 'Device preview';
    $('session').hidden = false; $('placeholder').hidden = true;
    $('connection').textContent = 'Joining';
    $('status').textContent = 'Complete the Zoom device preview to join.';
    await adapter.join(config, () => {
      joined = true; $('connection').textContent = 'Connected';
      $('status').textContent = 'Connected. Start transcription when everyone is ready.';
      checkCapture(); renderActivity(); announce();
    }, () => {
      joined = false; clearTimeout(captureTimer);
      $('connection').textContent = 'Left call'; $('role').textContent = 'Not joined';
      $('capture').disabled = true; $('stop-capture').hidden = true;
      $('status').textContent = 'You left Zoom. Confirm the host ended the call for everyone.';
      renderActivity(); announce();
    });
  } catch (error) {
    if (disconnected) return;
    $('connection').textContent = 'Connection failed';
    $('status').textContent = stage === 'toolkit'
      ? 'Zoom toolkit could not load. Check access to source.zoom.us and retry. No join token was issued.'
      : stage === 'token' ? safe(error, 'Could not reach Explore to request a join token.')
      : 'Zoom did not finish joining. Complete the device preview, or disconnect this pending test and retry. [sdk_join_failed]';
    if (stage === 'toolkit') $('start').disabled = false;
  }
});
