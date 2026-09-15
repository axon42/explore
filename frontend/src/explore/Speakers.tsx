import { Select } from "./Select";
import { useEffect, useRef, useState } from "react";
import { api } from "../types";

export type Person = { participant_id: string; speaker_id: string; name: string; interview_role: string; job_role: string };
export type Passage = { segment_id: string; segment_revision: number; span_index: number; text: string };
type Target = { track_id: string } | Omit<Passage, "text">;
type Assignment = Target & { participant_id: string | null; version: number; roster_revision: number };
type Track = { id: string; channel: string; label: number; capture_id: string; method: string; participant_id: string | null; needs_review: boolean; excerpt: string };
type State = { version: number; roster_revision: number; participants: Person[]; tracks: Track[]; history: Assignment[] };

function AssignmentForm({ state, target, current, onSave, label }: {
  state: State; target: Target; current: string | null; onSave: (value: Assignment) => Promise<void>; label: string;
}) {
  const [draft, setDraft] = useState<{ person: string; version: number; roster: number }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const value = draft?.person ?? current ?? "";
  return <form className="ex-speaker-form" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      await onSave({ ...target, participant_id: value || null, version: draft?.version ?? state.version, roster_revision: draft?.roster ?? state.roster_revision });
      setDraft(undefined);
    } catch (e) { setError((e as Error).message); setDraft(undefined); }
    finally { setBusy(false); }
  }}>
    <label>{label}<Select disabled={busy} value={value} onValueChange={value => setDraft({ person: value, version: state.version, roster: state.roster_revision })}>
      <option value="">Unassigned</option>
      {state.participants.map(p => <option key={p.participant_id} value={p.participant_id}>{p.name} · {p.interview_role}{p.job_role ? ` · ${p.job_role}` : ""}</option>)}
    </Select></label>
    <button disabled={busy} type="submit">{busy ? "Saving…" : value ? "Confirm speaker" : "Clear assignment"}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}

export function Speakers({ mid, sid, passage, onClose }: { mid: string; sid: string; passage?: Passage; onClose: () => void }) {
  const [state, setState] = useState<State>();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const path = `/meetings/${mid}/sessions/${sid}/speakers`;
  useEffect(() => {
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try { const next = await api<State>(path, { signal: abort.signal }); if (!abort.signal.aborted) { setState(next); setError(""); } }
      catch { if (!abort.signal.aborted) setError("Could not load speakers. Retrying…"); }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 2000);
    }
    void load(); return () => { abort.abort(); clearTimeout(timer); };
  }, [path]);
  useEffect(() => { if (passage) dialog.current?.showModal(); else dialog.current?.close(); }, [passage]);
  async function save(value: Assignment) {
    const next = await api<State>(path, { method: "PUT", body: JSON.stringify(value) });
    setState(next); setMessage("Speaker updated. Analysis will review the attribution change.");
  }
  return <section className="ex-speakers" aria-label="Speakers">
    <details>
      <summary>Speakers <span>{state?.tracks.length ?? 0} voices · {state?.tracks.filter(t => !t.participant_id || t.needs_review).length ?? 0} unconfirmed</span></summary>
      <p>Confirm who each voice belongs to. An unidentified voice has no customer or interviewer role.</p>
      {error && <p role="alert">{error}</p>}
      {state?.tracks.map((track, index) => <div className="ex-speaker-track" key={track.id}>
        <strong>{track.channel === "microphone" ? "Microphone" : "Remote"} {track.method === "single_person_source" ? "· single person" : `speaker ${track.label + 1}`} <small>· connection {[...new Set(state.tracks.map(t => t.capture_id))].indexOf(track.capture_id) + 1}</small></strong>
        <p>{track.excerpt || "Waiting for speech…"}</p>
        {track.needs_review && <p className="ex-speaker-review">Participant details changed. Confirm again.</p>}
        <AssignmentForm state={state} target={{ track_id: track.id }} current={track.participant_id} onSave={save} label={`Person for voice ${index + 1}`} />
      </div>)}
      {!state?.tracks.length && <p>Voices appear after captured speech is finalized.</p>}
      {!!state?.history.length && <details><summary>Assignment history</summary><ol className="ex-speaker-history">{state.history.slice().reverse().map(h => <li key={h.version}>Revision {h.version} · {"track_id" in h && h.track_id ? "Whole voice" : "One passage"} · {state.participants.find(p => p.participant_id === h.participant_id)?.name ?? (h.participant_id ? "Removed participant" : "Unassigned")}</li>)}</ol><p>To undo an assignment, select the earlier person and confirm. Every change is retained.</p></details>}
      {message && <p role="status">{message}</p>}
    </details>
    <dialog ref={dialog} className="ex-dialog ex-speaker-dialog" aria-labelledby="passage-speaker-title" onCancel={onClose}>
      <h2 id="passage-speaker-title">Correct this passage</h2>
      <p>This changes only the selected passage and transcript revision.</p>
      {passage && <blockquote>{passage.text}</blockquote>}
      {passage && state && <AssignmentForm key={`${passage.segment_id}-${passage.segment_revision}-${passage.span_index}`} state={state} target={{ segment_id: passage.segment_id, segment_revision: passage.segment_revision, span_index: passage.span_index }} current={null} label="Person for this passage" onSave={async value => { await save(value); onClose(); }} />}
      <footer><button onClick={onClose}>Close</button></footer>
    </dialog>
  </section>;
}
