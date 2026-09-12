import { useEffect, useState } from "react";
import { api } from "../types";
import type { Section } from "./analysisData";
import { RecordSections } from "./ReportDocument";
export { Reports } from "./Reports";
type Person = {
    speaker_id: string;
    name: string;
    interview_role: string;
    job_role: string;
};
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
    return <details className="ex-generated"><summary>AI notes</summary>{error && <p role="alert">{error}</p>}<RecordSections sections={sections}/></details>;
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
