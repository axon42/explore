import { useEffect, useState } from "react";
import { api } from "../types";
import { Select } from "./Select";

type Selection = {provider: string; model: string; revision: number; options: {provider: string; model: string; configured: boolean}[]};
export function ModelSettings() {
  const [record, setRecord] = useState<Selection>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  function accept(next: Selection) {
    setRecord(previous => previous && previous.revision > next.revision ? previous : next);
  }
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await api<Selection>("/settings/model", {signal: abort.signal});
        if (!abort.signal.aborted) accept(next);
      } catch {
        if (!abort.signal.aborted) setError("Model settings unavailable. Refresh to retry.");
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 3000);
    }
    void load();
    return () => {abort.abort(); clearTimeout(timer);};
  }, [retry]);
  return <div className="ex-model-settings">
    <label htmlFor="analysis-model">Analysis model</label>
    <Select id="analysis-model" value={record ? `${record.provider}:${record.model}` : ""} disabled={!record || busy} onValueChange={async value => {
      if (!record) return;
      const [provider, model] = value.split(":");
      setBusy(true); setError("");
      try {accept(await api<Selection>("/settings/model", {method:"PATCH", body:JSON.stringify({provider,model,revision:record.revision})}));}
      catch (e) {setError((e as Error).message); setRetry(n => n + 1);}
      finally {setBusy(false);}
    }}>
      {!record && <option value="">Loading…</option>}
      {record?.options.map(option => <option key={`${option.provider}:${option.model}`} value={`${option.provider}:${option.model}`} disabled={!option.configured}>
        {option.provider === "mock" ? "Simulated · test only" : option.model}{!option.configured ? " · API key needed" : ""}
      </option>)}
    </Select>
    <p>Applies to future requests in all meetings. Selecting a model makes no API call.</p>
    {record?.options.some(option => option.provider === "openai" && !option.configured) && <p>Add OPENAI_API_KEY to the server’s .env and restart to enable OpenAI.</p>}
    {error && <div><p role="alert">{error}</p><button onClick={() => {setError("");setRetry(n => n + 1);}}>Refresh models</button></div>}
  </div>;
}
