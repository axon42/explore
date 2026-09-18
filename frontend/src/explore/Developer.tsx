import { Select } from "./Select";
import { useEffect, useRef, useState } from "react";
import { Bug, Lock, RefreshCw } from "lucide-react";
import { api } from "../types";

type Trace = { id: string; session_id: string; meeting_title?: string; created_at: string; model: string; outcome: string; metadata: { elapsed_ms: number; code: string; segment_count: number; input_chars: number; http_status?: number; error_stage?: string; body_truncated?: boolean; [key: string]: unknown }; request_body?: string | null; response_body?: string | null };
type Status = { recording: { enabled: boolean; remaining_seconds: number; retention_hours: number; max_traces: number }; events: Record<string, unknown>[] };

function formatBody(body: string | null | undefined, empty: string) {
  if (!body) return empty;
  try { return JSON.stringify(JSON.parse(body), null, 2); }
  catch { return body; }
}

export function Developer() {
  const [authorized, setAuthorized] = useState(false);
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<Status>();
  const [rows, setRows] = useState<Trace[]>([]);
  const [trace, setTrace] = useState<Trace>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const abort = new AbortController(); api<{authorized: boolean}>("/developer/access", {signal: abort.signal}).then(a => { if (!abort.signal.aborted) setAuthorized(a.authorized); }).catch(() => { if (!abort.signal.aborted) setError("Developer tools are unavailable. The backend may need a restart."); }); return () => abort.abort(); }, []);
  useEffect(() => {
    if (!authorized) return;
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const access = await api<{authorized: boolean}>("/developer/access", {signal: abort.signal});
        if (!access.authorized) { setAuthorized(false); setTrace(undefined); setRows([]); setStatus(undefined); return; }
        const [s, list] = await Promise.all([api<Status>("/developer/status", {signal: abort.signal}), api<Trace[]>("/developer/requests", {signal: abort.signal})]);
        if (!abort.signal.aborted) { setStatus(s); setRows(list); }
      } catch (e) { if (!abort.signal.aborted) setError((e as Error).message); }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 2500);
    }
    void load(); return () => { abort.abort(); clearTimeout(timer); };
  }, [authorized, refresh]);
  const selectedOutcome = rows.find(r => r.id === selected)?.outcome;
  useEffect(() => {
    setTrace(undefined);
    if (!selected || !authorized) return;
    const abort = new AbortController();
    api<Trace>(`/developer/requests/${selected}`, {signal: abort.signal}).then(item => { if (!abort.signal.aborted) setTrace(item); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [selected, authorized, refresh, selectedOutcome]);
  async function unlock() {
    setBusy(true); setError("");
    try { await api("/developer/unlock", {method: "POST", body: JSON.stringify({key})}); setAuthorized(true); }
    catch (e) { setError((e as Error).message); }
    finally { setKey(""); setBusy(false); }
  }
  async function action(path: string, method: string, body?: object) {
    setBusy(true); setError("");
    try { await api(`/developer/${path}`, {method, body: body ? JSON.stringify(body) : undefined}); setRefresh(n => n + 1); dialog.current?.close(); if (path === "history") { setSelected(""); setTrace(undefined); } return true; }
    catch (e) { setError((e as Error).message); return false; }
    finally { setBusy(false); }
  }
  return <section className="ex-developer" aria-labelledby="developer-title">
    <header><h1 id="developer-title"><Bug size={25} /> Developer tools</h1><p>Local admin · Model requests and application diagnostics</p></header>
    {error && <p role="alert" className="ex-error">{error}</p>}
    {!authorized ? <form className="ex-developer-unlock" onSubmit={e => {e.preventDefault(); void unlock();}}><h2><Lock size={18} /> Unlock diagnostics</h2><p>Use the private admin key in your local data folder: <code>developer-admin.key</code>. This is separate from your Gemini key.</p><label>Admin key<input type="password" autoComplete="off" value={key} maxLength={256} onChange={e => setKey(e.target.value)} required disabled={busy} /></label><button className="ex-primary" disabled={busy || !key}>{busy ? "Unlocking…" : "Unlock"}</button></form> : <>
      <div className="ex-developer-toolbar"><button disabled={busy} onClick={() => { setError(""); setRefresh(n => n + 1); }}><RefreshCw size={14} />Refresh</button><button disabled={busy} onClick={() => void action("recording", "PUT", {enabled: !status?.recording.enabled})}>{status?.recording.enabled ? "Stop recording bodies" : "Record request / response bodies"}</button><button onClick={() => dialog.current?.showModal()} disabled={busy}>Clear diagnostic history</button><button disabled={busy} onClick={async () => { if (await action("lock", "POST")) {setAuthorized(false); setStatus(undefined); setRows([]); setTrace(undefined); setSelected("");} }}><Lock size={14} />Lock</button></div>
      <p className="ex-developer-notice">{status?.recording.enabled ? `Body recording on · ${Math.ceil(status.recording.remaining_seconds / 60)} minutes remaining.` : "Body recording off."} Bodies contain meeting content, with configured secrets redacted. Up to 100 requests are retained for 24 hours. Recording automatically stops after 15 minutes. Ordinary logs contain metadata only.</p>
      <div className="ex-archive-filters"><label>Search requests<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Meeting or request ID…" /></label><label>Request outcome<Select value={filter} onValueChange={value => setFilter(value)}><option value="">All outcomes</option>{["running", "ok", "error", "stale", "cancelled", "interrupted"].map(v => <option key={v} value={v}>{v}</option>)}</Select></label></div>
      <div className="ex-developer-grid"><section aria-label="Model requests" className="ex-developer-requests">{rows.filter(r => (!filter || r.outcome === filter) && `${r.meeting_title} ${r.id}`.toLowerCase().includes(search.toLowerCase().trim())).map(r => <button key={r.id} aria-pressed={selected === r.id} onClick={() => {setSelected(r.id); setError("");}}><strong>{r.meeting_title || "Meeting"}</strong><span>{r.outcome} · {(r.metadata.elapsed_ms/1000).toFixed(1)}s · {r.metadata.segment_count} segments</span><small>{new Date(r.created_at).toLocaleTimeString()} · {r.metadata.code || r.model}</small></button>)}{!rows.length && <p>No requests captured yet. New analysis attempts appear here.</p>}</section>
        <section aria-label="Selected model request" className="ex-developer-detail">{trace ? <><h2>Request details</h2><p className="ex-code-id">{trace.id}</p><pre tabIndex={0}>{JSON.stringify(trace.metadata, null, 2)}</pre>{trace.metadata.body_truncated && <p>Body preview truncated at the diagnostic size limit.</p>}<h3>Request body</h3><pre tabIndex={0}>{formatBody(trace.request_body, "Request body was not retained. Enable body recording before a future request to inspect its contents.")}</pre><h3>Response body</h3><pre tabIndex={0}>{formatBody(trace.response_body, "Response body was not retained. Check HTTP status and response bytes above to see whether a response arrived.")}</pre></> : <p>{selected ? "Loading request…" : "Select a request to inspect its timing, result and recorded bodies."}</p>}</section></div>
      <details className="ex-developer-events"><summary>Application logs · {status?.events.length || 0} recent events</summary><pre tabIndex={0}>{status?.events.map(e => JSON.stringify(e)).join("\n") || "No structured events yet."}</pre></details>
      <dialog ref={dialog} className="ex-dialog" aria-labelledby="diagnostic-clear-title" onCancel={e => {if (busy) e.preventDefault();}}><form onSubmit={e => {e.preventDefault(); void action("history", "DELETE");}}><header><h2 id="diagnostic-clear-title">Clear diagnostic history?</h2></header><p>Remove diagnostic requests and logs, and stop body recording. Meetings, reports and the protected transcript archive are preserved.</p><footer><button type="button" autoFocus disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button><button className="ex-danger" disabled={busy}>Clear diagnostics</button></footer></form></dialog>
    </>}
  </section>;
}
