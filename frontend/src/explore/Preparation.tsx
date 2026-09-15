import { useState } from "react";
import { api } from "../types";
import type { Detail } from "./data";
import { BriefEditor } from "./Editors";
import { Participants } from "./Records";

export function Preparation({ detail, testMode, reload }: { detail: Detail; testMode: boolean; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mid = detail.meeting.id;
  const [peopleVersion, setPeopleVersion] = useState(0);
  async function samplePeople() {
    setBusy(true); setError("");
    try {
      const roster = await api<{ revision:number; participants: unknown[] }>(`/meetings/${mid}/participants`);
      if (roster.participants.length) throw new Error("Remove the existing participants before loading sample people.");
      await api(`/meetings/${mid}/participants`, { method:"PUT", body:JSON.stringify({ revision:roster.revision, participants:[{speaker_id:"cofounder",name:"Alex Test",interview_role:"interviewer",job_role:"Cofounder"},{speaker_id:"customer",name:"Sam Test",interview_role:"customer",job_role:"Operations lead"}] }) });
      setPeopleVersion(v => v + 1);
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function start() {
    setBusy(true); setError("");
    try {
      const roster = await api<{ revision: number }>(`/meetings/${mid}/participants`);
      await api(`/meetings/${mid}/start`, { method: "POST", body: JSON.stringify({ revision: roster.revision, mode: testMode ? "test" : "real" }) });
      reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="ex-content ex-preparation">
    <header className="ex-meeting-header"><div><span className="ex-status">Draft</span><h1>{detail.meeting.title}</h1><p>Save your participants and brief before starting.</p></div>
      <button className="ex-primary" disabled={busy || !!detail.meeting.archived} onClick={() => void start()}>{busy ? "Starting…" : testMode ? "Start test meeting" : "Start interview"}</button></header>
    {error && <p role="alert" className="ex-error">{error}</p>}
    <p>{testMode ? "Test mode · One named participant is enough for a solo test. Replay uses synthetic cofounder/customer speakers." : "A real interview requires a named interviewer and a named customer."}</p>
    {testMode && <button disabled={busy} onClick={() => void samplePeople()}>Use sample participants</button>}
    <Participants key={peopleVersion} mid={mid} />
    <BriefEditor detail={detail} onSaved={reload} />
  </div>;
}
