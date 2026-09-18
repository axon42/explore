import { useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { api, timestamp } from "../types";
import { Select } from "./Select";
import type { Experiment } from "./data";
import "./analysis-controls.css";

export function AnalysisControls({ sid, experiment, archived, reload }: {
  sid: string; experiment: Experiment; archived: boolean; reload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef<string | null>(null);
  const state = experiment.scheduling;
  if (!state) return null;
  const running = experiment.analysis_status === "analyzing" || state.job?.status === "running";
  const failed = ["failed", "stale", "interrupted"].includes(state.job?.status ?? "");
  async function analyze() {
    if (busy) return;
    setBusy(true); setError("");
    if (requestId.current === state?.job?.id && state.job.status !== "running") requestId.current = null;
    requestId.current ??= crypto.randomUUID();
    try {
      await api(`/sessions/${sid}/analyze`, { method: "POST", body: JSON.stringify({ request_id: requestId.current }) });
      requestId.current = null;
      reload();
    } catch (e) {
      // Keep the id after ambiguous network failure: a repeated click cannot double charge.
      setError((e as Error).message);
    } finally { setBusy(false); }
  }
  async function schedule(mode: string) {
    if (!state) return;
    setBusy(true); setError("");
    try {
      await api(`/sessions/${sid}/analysis-scheduling`, { method: "PATCH", body: JSON.stringify({ mode, revision: state.revision }) });
      requestId.current = null; reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="ex-analysis-controls" aria-label="Meeting analysis">
    <div className="ex-analysis-choice">
      <label htmlFor={`schedule-${sid}`}>Analysis scheduling</label>
      <Select id={`schedule-${sid}`} value={state.mode} disabled={busy || running || archived} onValueChange={(v) => void schedule(v)}>
        <option value="manual">Manual</option><option value="automatic">Automatic</option>
      </Select>
    </div>
    <div className="ex-analysis-coverage" aria-live="polite">
      <strong>{running ? "Analyzing saved transcript…" : state.mode === "manual" ? "Analyze when you’re ready" : "Analysis follows the conversation"}</strong>
      <span>{state.final_segments - state.pending_segments}/{state.final_segments} segments analyzed · Through {timestamp(state.analyzed_through_ms)} · {state.pending_segments} pending · {state.remaining_calls} calls left</span>
      <small>{state.mode === "manual" ? "Full saved transcript per click. Capture continues; no automatic retries." : "New speech triggers incremental analysis. Switching modes alone makes no call."}</small>
    </div>
    {state.mode === "manual" && <button className="ex-primary" disabled={busy || running || archived || !state.changed || state.remaining_calls === 0} onClick={() => void analyze()}>
      <Sparkles size={16} />{running ? "Analyzing…" : failed ? "Retry analysis" : "Analyze now"}
    </button>}
    {!running && experiment.analysis_status === "ready" && experiment.result?.review?.empty && <div role="status">
      <strong>Review completed with no new updates.</strong>
      <p>{experiment.result.review.reason || "The model returned no questions, discussion threads or notes for this review."}</p>
      <small>Reviewed by {experiment.result.model}. Continue capturing more detail, or select another model to compare.</small>
    </div>}
    {error && <p className="ex-error" role="alert">{error}</p>}
  </section>;
}
