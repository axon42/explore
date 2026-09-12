// The official toolkit owns only this same-origin iframe, including its global CSS.
const base = 'https://source.zoom.us/uitoolkit/2.5.0-1/';
export async function boundedSdkCall(operation, milliseconds = 20000) {
  let timer;
  try {
    return await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('sdk_timeout')), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
export async function loadZoom(frame) {
  await boundedSdkCall(new Promise((resolve, reject) => {
    frame.onload = resolve;
    frame.onerror = () => reject(new Error('toolkit_load'));
    frame.src = '/zoom-frame.html';
  }));
  const doc = frame.contentDocument;
  // Device preview is taller than the in-call grid; keep its Join control reachable.
  frame.style.height = '850px';
  const win = frame.contentWindow;
  if (!win.UIToolkit) {
    const css = doc.createElement('link');
    css.rel = 'stylesheet'; css.href = base + 'videosdk-ui-toolkit.css';
    doc.head.append(css);
    await boundedSdkCall(new Promise((resolve, reject) => {
      const script = doc.createElement('script');
      script.src = base + 'videosdk-ui-toolkit.min.umd.js';
      script.onload = resolve;
      script.onerror = () => reject(new Error('toolkit_load'));
      doc.head.append(script);
    }));
  }
  const toolkit = win.UIToolkit;
  if (typeof toolkit?.joinSession !== 'function') throw new Error('toolkit_load');
  return {
    client: () => toolkit.getClient?.(),
    join(config, onJoined, onClosed) {
      // 2.5.0-1 requires joinSession to initialize the controller BEFORE subscribing.
      // Do not await it here: the promise settles only after the device preview is joined.
      const pending = toolkit.joinSession(doc.querySelector('#zoom-root'), {
        ...config, debug: true, leaveOnPageUnload: true,
        featuresOptions: {
          preview:{enable:true},video:{enable:true},audio:{enable:true},users:{enable:true},
          settings:{enable:true},leave:{enable:true},recording:{enable:false},phone:{enable:false},
          share:{enable:false},chat:{enable:false},caption:{enable:false},invite:{enable:false},
        },
      });
      // Attach rejection handling even if registration itself fails.
      const settled = Promise.resolve(pending);
      settled.catch(() => {});
      toolkit.onSessionJoined(() => { frame.style.height = '620px'; onJoined(); });
      toolkit.onSessionClosed(onClosed);
      return settled;
    },
  };
}
