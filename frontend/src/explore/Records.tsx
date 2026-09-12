import { useEffect, useState } from "react";
import { api } from "../types";
type Section = {
    key: string;
    title: string;
    items: Record<string, unknown>[];
};
type ReportList = {
    job: {
        status: string;
        error: string;
    };
    reports: {
        id: string;
        revision: number;
        outdated: boolean;
    }[];
};
type Person = {
    speaker_id: string;
    name: string;
    interview_role: string;
    job_role: string;
};
function Sections({ sections }: {
    sections: Section[];
}) {
    return <div className="ex-record-sections">{sections.map(section => <section className="ex-summary" key={section.key}>
    <h2>{section.title}</h2>
    {!section.items.length && <p>Not established</p>}
    {section.items.map((item, index) => <p key={index}>{section.key === "people" ? `${item.name || item.speaker_id} · ${item.interview_role} · ${item.job_role || "Job role not established"}` :
                    section.key === "purpose" ? Object.entries(item.brief as Record<string, string>).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join("\n") :
                        `${item.status ? `[${item.status}] ` : ""}${item.text || item.body || "Not established"}${item.basis ? ` (${item.basis})` : ""}`}</p>)}
  </section>)}</div>;
}
export function GeneratedNotes({ mid }: {
    mid: string;
}) {
    const [sections, setSections] = useState<Section[]>([]);
    const [error, setError] = useState("");
    useEffect(() => {
        const abort = new AbortController();
        let timer: ReturnType<typeof setTimeout>;
        async function load() {
            try {
                const result = await api<{
                    notes: Section[];
                }>(`/meetings/${mid}/analysis`, { signal: abort.signal });
                if (!abort.signal.aborted) {
                    setSections(result.notes);
                    setError("");
                }
            }
            catch {
                if (!abort.signal.aborted)
                    setError("Could not load generated notes.");
            }
            if (!abort.signal.aborted)
                timer = setTimeout(() => void load(), 2500);
        }
        void load();
        return () => { abort.abort(); clearTimeout(timer); };
    }, [mid]);
    return <details className="ex-generated"><summary>AI notes</summary>{error && <p role="alert">{error}</p>}<Sections sections={sections}/></details>;
}
export function Participants({ mid }: {
    mid: string;
}) {
    const [record, setRecord] = useState<{
        revision: number;
        participants: Person[];
    }>();
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        const abort = new AbortController();
        void api<{
            revision: number;
            participants: Person[];
        }>(`/meetings/${mid}/participants`, { signal: abort.signal }).then(setRecord).catch(() => { if (!abort.signal.aborted)
            setMessage("Could not load participants. Reopen Brief to retry."); });
        return () => abort.abort();
    }, [mid]);
    function edit(index: number, field: keyof Person, value: string) {
        if (record)
            setRecord({ ...record, participants: record.participants.map((p, i) => i === index ? { ...p, [field]: value } : p) });
        setMessage("");
    }
    return <section className="ex-participants"><h2>Participants</h2><p>For replay and injected dialogue, use speaker IDs cofounder and customer. Enter actual names and roles for the report.</p>{record && <form onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setMessage("");
                try {
                    setRecord(await api(`/meetings/${mid}/participants`, { method: "PUT", body: JSON.stringify(record) }));
                    setMessage("Participants saved");
                }
                catch (e) {
                    setMessage((e as Error).message);
                }
                finally {
                    setBusy(false);
                }
            }}>
    {record.participants.map((person, index) => <fieldset disabled={busy} key={index}><legend>Person {index + 1}</legend>
      {(["speaker_id", "name", "job_role"] as const).map(field => <label key={field}>{field === "speaker_id" ? "Speaker ID" : field === "name" ? "Name" : "Job role"}<input required={field === "speaker_id"} maxLength={200} value={person[field]} onChange={e => edit(index, field, e.target.value)}/></label>)}
      <label>Interview role<select aria-label="Interview role" value={person.interview_role} onChange={e => edit(index, "interview_role", e.target.value)}>{["unknown", "interviewer", "customer", "observer"].map(role => <option key={role}>{role}</option>)}</select></label>
      <button type="button" onClick={() => setRecord({ ...record, participants: record.participants.filter((_, i) => i !== index) })}>Remove person {index + 1}</button>
    </fieldset>)}
    <div className="ex-record-actions"><button type="button" disabled={busy || record.participants.length >= 30} onClick={() => setRecord({ ...record, participants: [...record.participants, { speaker_id: "", name: "", job_role: "", interview_role: "unknown" }] })}>Add participant</button><button disabled={busy} className="ex-primary">Save participants</button></div>
  </form>}{message && <p role="status">{message}</p>}</section>;
}
export function Reports({ mid, sid, stopped, onChanged }: {
    mid: string;
    sid: string;
    stopped: boolean;
    onChanged: () => void;
}) {
    const [list, setList] = useState<ReportList>();
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        const abort = new AbortController();
        let timer: ReturnType<typeof setTimeout>;
        async function load() {
            try {
                const next = await api<ReportList>(`/meetings/${mid}/reports`, { signal: abort.signal });
                if (!abort.signal.aborted)
                    setList(next);
            }
            catch {
                if (!abort.signal.aborted)
                    setError("Could not load reports.");
            }
            if (!abort.signal.aborted)
                timer = setTimeout(() => void load(), 1500);
        }
        void load();
        return () => { abort.abort(); clearTimeout(timer); };
    }, [mid, sid]);
    async function download(path: string, filename: string) {
        setBusy(true);
        setError("");
        try {
            const response = await fetch(`/api/meetings/${mid}/${path}`);
            if (!response.ok)
                throw new Error("Download failed. Please retry.");
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
        catch (e) {
            setError((e as Error).message);
        }
        finally {
            setBusy(false);
        }
    }
    const generating = list?.job.status === "pending" || list?.job.status === "generating";
    return <section className="ex-reports"><h2>Meeting report</h2><p>Includes received transcript evidence, participant roles, notes, question history and supported workflow diagrams in Markdown.</p>
    <p role="status">{generating ? "Generating report…" : list?.job.status === "complete" ? "Report ready" : list?.job.status === "failed" ? "Report failed" : "End the interview to generate its report."}</p>
    {(error || list?.job.error) && <p role="alert">{error || list?.job.error}</p>}
    <button className="ex-primary" disabled={busy || generating || !list} onClick={async () => {
            setBusy(true);
            setError("");
            try {
                setList(await api(`/meetings/${mid}/finalize`, { method: "POST", body: JSON.stringify({ session_id: sid }) }));
                onChanged();
            }
            catch (e) {
                setError((e as Error).message);
            }
            finally {
                setBusy(false);
            }
        }}>{stopped ? "Generate report" : "End interview and generate report"}</button>
    {list?.reports.map(report => <article className="ex-summary" key={report.id}><h3>Report {report.revision}{report.outdated ? " · Outdated" : ""}</h3><div className="ex-record-actions">{["markdown", "json"].map(format => <button key={format} disabled={busy} onClick={() => void download(`reports/${report.id}?format=${format}`, `explore-report-${report.revision}.${format === "markdown" ? "md" : "json"}`)}>Download {format === "markdown" ? "Markdown" : "JSON"}</button>)}</div></article>)}
    <h2>Full transcript</h2><div className="ex-record-actions">{["markdown", "json"].map(format => <button key={format} disabled={busy} onClick={() => void download(`transcript/export?format=${format}`, `explore-transcript.${format === "markdown" ? "md" : "json"}`)}>Export transcript {format === "markdown" ? "Markdown" : "JSON"}</button>)}</div>
  </section>;
}
