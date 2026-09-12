import { useEffect, useRef, useState } from "react";
import { Mic, Square, Radio } from "lucide-react";
import { api } from "../types";

type Capture = {
  id: string; sid: string; status: string; error: string; elapsed_seconds: number;
  microphone_level: number; system_level: number; segments: number;
};
type State = { supported: boolean; configured: boolean; helper_ready: boolean; max_seconds: number; capture: Capture | null };
const activeStates = new Set(["starting", "capturing", "stopping"]);

export function AudioCapture({ sid, stopped }: { sid: string; stopped: boolean }) {
  const [state, setState] = useState<State>();
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const startButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await api<State>("/audio-capture", { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) });
        if (!disposed) { setState(next); setConnectionError(""); }
      } catch {
        if (!disposed) setConnectionError("Capture status unavailable. Use the Explore Capture menu on your Mac to stop audio.");
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 1000);
      }
    }
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [sid]);
  const capture = state?.capture;
  const mine = capture?.sid === sid;
  const active = !!capture && activeStates.has(capture.status);
  const canStart = !stopped && !active && state?.supported && state.configured && state.helper_ready;
  function close() { dialog.current?.close(); setConsent(false); startButton.current?.focus(); }
  async function command(stop: boolean) {
    setBusy(true); setError("");
    try {
      const next = await api<State>(`/sessions/${sid}/audio-capture${stop ? "/stop" : ""}`, {
        method: "POST", body: JSON.stringify(stop ? { capture_id: capture?.id } : { consent: true }),
      });
      setState(next); close();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const setup = !state ? "Checking capture…" : !state.supported ? "Mac audio capture requires macOS. Replay remains available."
    : !state.helper_ready ? "Build the Explore Capture helper to enable Mac audio."
    : !state.configured ? "Add DEEPGRAM_API_KEY to .env and restart to enable transcription." : "";
  return <section className="ex-audio-capture" data-active={active && mine} aria-label="Mac audio capture">
    <div className="ex-audio-heading"><div><span className="ex-icon"><Radio size={15} /></span><strong>Mac audio</strong>
      <span>{active && mine ? capture.status === "starting" ? "Waiting for permissions / connection" : capture.status : "Microphone + system audio"}</span></div>
      {active && mine ? <button disabled={busy} onClick={() => void command(true)}><Square size={13} />Stop capture</button>
        : <button className="ex-primary" ref={startButton} disabled={!canStart || busy} onClick={() => { setConsent(false); setError(""); dialog.current?.showModal(); }}><Mic size={14} />Capture audio</button>}
    </div>
    {active && mine && <div className="ex-audio-meters">
      <label>Microphone <meter min={0} max={1} value={capture.microphone_level} /></label>
      <label>System audio <meter min={0} max={1} value={capture.system_level} /></label>
      <span>{Math.floor(capture.elapsed_seconds / 60)}:{String(capture.elapsed_seconds % 60).padStart(2, "0")} / {Math.floor((state?.max_seconds ?? 120) / 60)} min · {capture.segments} finalized segments</span>
    </div>}
    {(setup || (active && !mine)) && <p>{active && !mine ? "Another meeting is capturing audio. Stop that capture before starting here." : setup}</p>}
    {mine && !active && capture?.status === "stopped" && <p>Capture stopped. Accepted transcripts are saved.</p>}
    {((error && !dialog.current?.open) || connectionError || (mine && capture?.error)) && <p role="alert">{(!dialog.current?.open && error) || connectionError || capture?.error}</p>}
    <dialog ref={dialog} className="ex-dialog ex-audio-dialog" aria-labelledby="audio-consent-title" onCancel={e => { e.preventDefault(); if (!busy) close(); }}>
      <header><span className="ex-icon"><Mic size={18} /></span><h2 id="audio-consent-title">Capture this conversation</h2></header>
      <p className="ex-capture-detail">Explore will send your microphone and all system audio to Deepgram for transcription, then use your configured analysis provider. Screen video and audio files are not saved by Explore.</p>
      <p>Use headphones to avoid duplicate speech. Remote voices share the “System audio” label. Close other apps playing private audio.</p>
      <p>Stops automatically after {Math.floor((state?.max_seconds ?? 120) / 60)} minutes. Provider usage is billed separately from Gemini.</p>
      <label><input type="checkbox" disabled={busy} checked={consent} onChange={e => setConsent(e.target.checked)} /><span>Everyone has agreed to transcription and AI processing.</span></label>
      {error && <p className="ex-capture-error" role="alert">{error}</p>}
      <footer><button disabled={busy} onClick={close}>Cancel</button><button className="ex-primary" disabled={busy || !consent || !canStart || !!connectionError} onClick={() => void command(false)}>{busy ? "Starting…" : "Start capture"}</button></footer>
    </dialog>
  </section>;
}
