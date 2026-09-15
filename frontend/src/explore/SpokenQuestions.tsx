import { Select } from "./Select";
import { useState } from "react";
import { timestamp } from "../types";
import type { Evidence, SpokenQuestion } from "./data";

export function SpokenQuestions({ items, onEvidence }: { items: SpokenQuestion[]; onEvidence: (e: Evidence) => void }) {
  const [role, setRole] = useState("");
  const [history, setHistory] = useState(false);
  const active = items.filter(q => !q.superseded);
  const shown = items.filter(q => (history || !q.superseded) && (!role || q.interview_role === role));
  return <details className="ex-spoken-questions">
    <summary>Asked in conversation <span>{active.length} detected</span></summary>
    <p>Questions heard in the transcript. Detection may miss or misclassify a question; the source is always available.</p>
    <div className="ex-spoken-filters"><label>Speaker role<Select value={role} onValueChange={value => setRole(value)}><option value="">All speakers</option><option value="interviewer">Interviewers</option><option value="customer">Customers</option><option value="observer">Observers</option><option value="unknown">Unconfirmed</option></Select></label><label><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)} />Include earlier revisions</label></div>
    <ol>{shown.map(q => <li key={q.id}><span>{timestamp(q.start_ms)} · {q.speaker_name} · {q.interview_role}{q.superseded && " · Earlier revision"}</span><p>{q.text}</p><div className="ex-sources">{q.evidence.map(e => <button key={`${e.segment_id}:${e.revision}`} onClick={() => onEvidence(e)}>View source {timestamp(e.start_ms)} ↗</button>)}</div></li>)}</ol>
    {!shown.length && <p>No detected questions in this view.</p>}
  </details>;
}
