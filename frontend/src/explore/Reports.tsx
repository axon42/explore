import { Select } from "./Select";
import { useEffect, useState } from "react";
import { api } from "../types";
import type { MeetingReport } from "./analysisData";
import { ReportDocument } from "./ReportDocument";

type ReportList = {
  job: { status: string; error: string };
  reports: { id: string; revision: number; outdated: boolean }[];
};

function SavedReport({ mid, sid, rid }: { mid: string; sid: string; rid: string }) {
  const [report, setReport] = useState<MeetingReport>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void api<MeetingReport>(`/meetings/${mid}/reports/${rid}`, { signal: abort.signal }).then(next => {
      if (next.meeting.id !== mid || next.session.id !== sid || ![1, 2].includes(next.schema_version))
        throw new Error("This report cannot be displayed by this version of Explore. Download JSON to inspect it.");
      if (!abort.signal.aborted) { setReport(next); setError(""); }
    }).catch(() => { if (!abort.signal.aborted) setError("Could not open this report. Retry or download the saved copy."); });
    return () => abort.abort();
  }, [mid, sid, rid, attempt]);
  if (error) return <div className="ex-record-notice"><p role="alert">{error}</p><button onClick={() => { setError(""); setAttempt(n => n + 1); }}>Retry report</button></div>;
  return report ? <ReportDocument report={report} /> : <p>Opening report…</p>;
}

export function Reports({ mid, sid, stopped, onChanged }: {
  mid: string; sid: string; stopped: boolean; onChanged: () => void;
}) {
  const [list, setList] = useState<ReportList>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await api<ReportList>(`/meetings/${mid}/reports`, { signal: abort.signal });
        if (!abort.signal.aborted) { setList(next); setLoadError(false); }
      } catch {
        if (!abort.signal.aborted) setLoadError(true);
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 1500);
    }
    void load();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [mid, sid]);
  async function download(path: string, filename: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/meetings/${mid}/${path}`);
      if (!response.ok) throw new Error("Download failed. Please retry.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const generating = list?.job.status === "pending" || list?.job.status === "generating";
  const selectedReport = list?.reports.find(r => r.id === selected) || list?.reports[0];
  return <section className="ex-reports">
    <div className="ex-report-toolbar"><div><h2>Meeting report</h2>
      <p role="status">{generating ? "Generating report…" : list?.job.status === "complete" ? "Report ready" : list?.job.status === "failed" ? "Report failed" : "End the interview to generate its report."}</p></div>
      <button className="ex-primary" disabled={busy || generating || !list} onClick={async () => {
        setBusy(true); setError("");
        try { setList(await api(`/meetings/${mid}/finalize`, { method: "POST", body: JSON.stringify({ session_id: sid }) })); setSelected(""); onChanged(); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
      }}>{stopped ? "Generate report" : "End interview and generate report"}</button>
    </div>
    {(error || list?.job.error || loadError) && <p className="ex-record-notice" role="alert">{error || list?.job.error || "Report status could not refresh. Retrying…"}</p>}
    {selectedReport && <>
      <div className="ex-report-toolbar ex-report-version"><h3>Report {selectedReport.revision}{selectedReport.outdated ? " · Outdated" : ""}</h3>
        {list && list.reports.length > 1 && <label>Revision <Select aria-label="Report revision" value={selectedReport.id} onValueChange={value => setSelected(value)}>
          {list.reports.map(r => <option value={r.id} key={r.id}>Report {r.revision}{r.outdated ? " · Outdated" : ""}</option>)}
        </Select></label>}
        <div className="ex-record-actions">{["markdown", "json"].map(format => <button key={format} disabled={busy} onClick={() => void download(`reports/${selectedReport.id}?format=${format}`, `explore-report-${selectedReport.revision}.${format === "markdown" ? "md" : "json"}`)}>Download {format === "markdown" ? "Markdown" : "JSON"}</button>)}</div>
      </div>
      {selectedReport.outdated && <p className="ex-record-notice">This saved revision predates changes to the meeting. Generate a new report to include them.</p>}
      <SavedReport key={selectedReport.id} mid={mid} sid={sid} rid={selectedReport.id} />
    </>}
    <details className="ex-transcript-export" open><summary>Full transcript</summary><div className="ex-record-actions">{["markdown", "json"].map(format => <button key={format} disabled={busy} onClick={() => void download(`transcript/export?format=${format}`, `explore-transcript.${format === "markdown" ? "md" : "json"}`)}>Export transcript {format === "markdown" ? "Markdown" : "JSON"}</button>)}</div></details>
  </section>;
}
