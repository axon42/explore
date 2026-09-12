import { useEffect, useState } from "react";
import { Layers3 } from "lucide-react";
import { api, timestamp } from "../types";
import type { Segment } from "../types";
import type { Evidence } from "./data";
import type { LiveAnalysis } from "./analysisData";
import { referencedEvidence, topicTone } from "./analysisData";

export function DiscussionThreads({ mid, sid, stopped, strategy, analyzing, segments, onEvidence }: {
  mid: string; sid: string; stopped: boolean; strategy?: string; analyzing: boolean;
  segments: Segment[]; onEvidence: (evidence: Evidence) => void;
}) {
  const [snapshot, setSnapshot] = useState<LiveAnalysis>();
  const [pinned, setPinned] = useState<string>();
  const [error, setError] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await api<LiveAnalysis>(`/meetings/${mid}/analysis`, { signal: abort.signal });
        if (!abort.signal.aborted) { setSnapshot(next); setError(false); }
      } catch {
        if (!abort.signal.aborted) setError(true);
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 2500);
    }
    void load();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [mid, sid]);
  const topics = (snapshot?.topics || []).filter(t => t.session_id === sid);
  const focus = topics.find(t => t.status === "active");
  const selected = topics.find(t => t.id === pinned) || focus || topics[0];
  const readiness = snapshot?.state.topic_state?.readiness;
  const uncertain = snapshot?.state.topic_state?.action === "uncertain";
  return <section className="ex-threads" aria-labelledby="discussion-title">
    <div className="ex-panel-title"><h2 id="discussion-title"><span className="ex-icon"><Layers3 size={16} /></span>Discussion threads</h2>
      <span>{stopped ? "Meeting ended" : strategy !== "topics" ? "Saved context" : analyzing ? "Updating…" : "Live context"}</span></div>
    {error && <p className="ex-record-notice" role="alert">Context could not refresh. {snapshot ? "Showing the last update. " : ""}Retrying…</p>}
    {!topics.length && <p className="ex-thread-empty">{!snapshot ? "Loading context…" : strategy !== "topics" ? "Choose Discussion threads in Analysis mode to see live context." : "Listening for a complete thought. Threads appear as the discussion develops."}</p>}
    {!!topics.length && <>
      <div className="ex-thread-picker" aria-label="Discussion threads">
        {topics.map(t => <button key={t.id} className={topicTone(t.id)} aria-pressed={selected?.id === t.id} onClick={() => setPinned(t.id)}>
          <span className="ex-thread-dot" aria-hidden="true" /><span>{t.title}</span>
          <small>{t.provisional ? "Tentative" : t.status === "active" ? stopped || strategy !== "topics" ? "Last focus" : "Active" : "Paused"}</small>
        </button>)}
      </div>
      {pinned && <button className="ex-follow-context" onClick={() => setPinned(undefined)}>{stopped ? "Show last focus" : "Follow active thread"}</button>}
      {selected && <article className={`ex-thread-detail ${topicTone(selected.id)}`}>
        <header><h3>{selected.title}</h3><span>{snapshot?.simulated ? "Simulated · " : ""}Update {selected.revision}</span></header>
        <p>{selected.needs_review ? "Evidence changed. This summary needs review." : selected.summary || "Context is still developing."}</p>
        {!stopped && strategy === "topics" && selected.id === focus?.id && <small>{uncertain ? "Topic transition uncertain" : readiness === "developing" ? "Thought still developing" : readiness === "ready" ? "Ready to consider a follow-up" : "Listening for more context"}</small>}
        <div className="ex-sources">{referencedEvidence(selected.summary_sources, segments).map(e => <button key={e.segment_id} onClick={() => onEvidence(e)} aria-label={`View thread evidence at ${timestamp(e.start_ms)}`}>{timestamp(e.start_ms)} ↗</button>)}</div>
      </article>}
    </>}
  </section>;
}
