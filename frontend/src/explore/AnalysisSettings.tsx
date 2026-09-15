import { Select } from "./Select";
import { useEffect, useState } from "react";
import { Settings2 } from "lucide-react";
import { SidebarPopover } from "./SidebarPopover";
import { api } from "../types";

type Preferences = { strategy: "legacy" | "topics"; revision: number };

export function AnalysisSettings() {
  const [record, setRecord] = useState<Preferences>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);
  function accept(next: Preferences) {
    // A GET started before a save must not replace the saved choice when it arrives late.
    setRecord(previous => previous && previous.revision > next.revision ? previous : next);
  }
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await api<Preferences>("/settings/analysis", { signal: abort.signal });
        if (!abort.signal.aborted) { accept(next); setOffline(false); }
      } catch {
        if (!abort.signal.aborted) setOffline(true);
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 3000);
    }
    void load();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [retry]);
  return <section className="ex-analysis-settings" aria-label="Analysis settings">
    <SidebarPopover label="Analysis settings" side trigger={<><Settings2 size={17} aria-hidden="true" />Analysis mode<span className="ex-analysis-badge">{offline ? "Offline" : error ? "Review" : busy ? "Saving…" : record?.strategy === "topics" ? "Threads" : record ? "Standard" : "Loading…"}</span></>}>
    {() => <><label htmlFor="analysis-mode">Analysis mode</label>
    <Select id="analysis-mode" value={record?.strategy || ""} disabled={!record || busy || offline} onValueChange={async value => {
      if (!record) return;
      const strategy = value as Preferences["strategy"];
      setBusy(true); setError("");
      try { accept(await api<Preferences>("/settings/analysis", { method: "PATCH", body: JSON.stringify({ strategy, revision: record.revision }) })); }
      catch (e) { setError((e as Error).message); setRetry(n => n + 1); }
      finally { setBusy(false); }
    }}>
      {!record && <option value="">Loading…</option>}
      <option value="legacy">Standard</option>
      <option value="topics">Discussion threads</option>
    </Select>
    <p>{busy ? "Saving…" : "All meetings · applies to new batches"}</p>
    {(offline || error) && <div><p role="alert">{offline ? "Analysis settings unavailable." : error}</p>
      <button onClick={() => { setError(""); setRetry(n => n + 1); }}>Refresh setting</button></div>}
    </>}
    </SidebarPopover>
  </section>;
}
