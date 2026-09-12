import { useEffect, useRef, useState } from "react";
import { ArrowDown, X } from "lucide-react";
import { timestamp } from "../types";
import type { Segment } from "../types";
import type { Evidence } from "./data";
import { briefLabels } from "./data";
import type { MeetingReport, RecordItem, SavedWorkflow, Section } from "./analysisData";
import { referencedEvidence, topicTone } from "./analysisData";

function Sources({ evidence, onEvidence }: { evidence: Evidence[]; onEvidence?: (e: Evidence) => void }) {
  if (!onEvidence || !evidence.length) return null;
  return <div className="ex-sources">{evidence.map(e => <button key={`${e.segment_id}-${e.revision}`} onClick={() => onEvidence(e)}>
    {timestamp(e.start_ms)}{e.superseded ? " · earlier revision" : ""} ↗
  </button>)}</div>;
}

function Items({ section, items, segments, onEvidence }: {
  section: string; items: RecordItem[]; segments: Segment[]; onEvidence?: (e: Evidence) => void;
}) {
  if (section === "people") return <div className="ex-report-people">{items.map((p, i) => <article key={i}>
    <span className="ex-record-label">{!p.interview_role || p.interview_role === "unknown" ? "Role not established" : p.interview_role}</span>
    <h3>{p.name || p.speaker_id || "Name not established"}</h3><p>{p.job_role || "Job role not established"}</p>
  </article>)}</div>;
  if (section === "purpose") return <dl className="ex-report-brief">{items.flatMap(item => Object.entries(item.brief || {}).filter(([, value]) => value).map(([key, value]) => <div key={key}>
    <dt>{briefLabels[key as keyof typeof briefLabels] || key}</dt><dd>{value}</dd>
  </div>))}</dl>;
  return <ul className="ex-report-items">{items.map((item, i) => <li key={i}>
    <div>{item.status && <span className={`ex-record-label ex-question-status ${item.status}`}>{item.status}</span>}
      {item.basis && <span className="ex-record-label">{item.basis === "inferred" ? "Hypothesis" : item.basis}</span>}
      {section === "evidence_notes" && <span className="ex-record-label">Human note</span>}
      <p>{item.text || item.body || "Not established"}</p></div>
    <Sources evidence={item.evidence || referencedEvidence(item.sources, segments)} onEvidence={onEvidence} />
  </li>)}</ul>;
}

export function RecordSections({ sections, segments = [], onEvidence, workflows = [], topics = [] }: {
  sections: Section[]; segments?: Segment[]; onEvidence?: (e: Evidence) => void;
  workflows?: SavedWorkflow[]; topics?: MeetingReport["topics"];
}) {
  return <div className="ex-record-sections">{sections.map(section => {
    const hasWorkflows = section.key === "workflows" && workflows.length > 0;
    const empty = (!section.items.length || (section.key === "purpose" && !section.items.some(item => Object.values(item.brief || {}).some(Boolean)))) && !hasWorkflows;
    const content = <>
      {section.key === "purpose" && <p className="ex-record-label">Pre-meeting brief</p>}
      {!!section.topic_groups?.length && !["people", "purpose", "evidence_notes"].includes(section.key)
        ? section.topic_groups.map(group => <div key={group.topic_id} className={`ex-report-group ${topicTone(group.topic_id)}`}>
          <h3>{group.title}</h3><Items section={section.key} items={group.items} segments={segments} onEvidence={onEvidence} />
        </div>)
        : <Items section={section.key} items={section.items} segments={segments} onEvidence={onEvidence} />}
      {hasWorkflows && workflows.map(w => <WorkflowDiagram key={`${w.topic_id || ""}:${w.key}`} workflow={w} topicTitle={topics?.find(t => t.id === w.topic_id)?.title} segments={segments} onEvidence={onEvidence} />)}
    </>;
    return empty ? <details className="ex-report-section ex-section-empty" data-section={section.key} id={`report-${section.key}`} key={section.key}>
      <summary>{section.title}<span>Not established</span></summary><p>No details were established in the accepted analysis.</p>
    </details> : <section className="ex-report-section" data-section={section.key} id={`report-${section.key}`} key={section.key}>
      <h2>{section.title}</h2>{content}
    </section>;
  })}</div>;
}

function WorkflowDiagram({ workflow, topicTitle, segments, onEvidence }: {
  workflow: SavedWorkflow; topicTitle?: string; segments: Segment[]; onEvidence?: (e: Evidence) => void;
}) {
  // The saved contract is a bounded ordered step list, not an arbitrary graph language.
  // Native text/HTML keeps both the visual and accessible version safe and lightweight.
  return <figure className={`ex-workflow-diagram ${topicTone(workflow.topic_id || "")}`}>
    <figcaption><h3>{workflow.title}</h3>{topicTitle && <span>{topicTitle}</span>}</figcaption>
    <ol>{workflow.steps.map((step, i) => {
      const transition = workflow.transitions[i - 1] || [];
      const refs = (ids: string[]) => Object.fromEntries(ids.map(id => [id, workflow.sources[id]]));
      return <li key={i}>
        {i > 0 && <div className={`ex-workflow-edge ${transition.length ? "supported" : "unknown"}`}>
          {transition.length ? <ArrowDown size={18} aria-hidden="true" /> : <span aria-hidden="true">⋯</span>}<span>{transition.length ? "Then" : "Order not established"}</span>
          <Sources evidence={referencedEvidence(refs(transition), segments)} onEvidence={onEvidence} />
        </div>}
        <div className="ex-workflow-step"><span aria-hidden="true">{i + 1}</span><div><p>{step.label}</p>
          <Sources evidence={referencedEvidence(refs(step.source_ids), segments)} onEvidence={onEvidence} /></div></div>
      </li>;
    })}</ol>
  </figure>;
}

function QuestionChart({ items }: { items: RecordItem[] }) {
  const counts = ["queued", "asked", "answered", "discarded"].map(status => ({ status, count: items.filter(item => item.status === status).length }));
  const total = counts.reduce((sum, item) => sum + item.count, 0);
  return <figure className="ex-question-chart"><figcaption>Question status <span>{total} saved</span></figcaption>
    {total > 0 && <div className="ex-status-bar" role="img" aria-label={counts.map(c => `${c.count} ${c.status}`).join(", ")}>
      {counts.filter(c => c.count).map(c => <span key={c.status} className={c.status} style={{ flex: c.count }} />)}
    </div>}
    <ul>{counts.map(c => <li key={c.status}><span className={`ex-chart-dot ${c.status}`} aria-hidden="true" /><strong>{c.count}</strong> {c.status}</li>)}</ul>
  </figure>;
}

export function ReportDocument({ report }: { report: MeetingReport }) {
  const [evidence, setEvidence] = useState<Evidence>();
  const evidencePanel = useRef<HTMLDivElement>(null);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  useEffect(() => { if (evidence) evidencePanel.current?.focus(); }, [evidence]);
  function revealEvidence(source: Evidence) {
    evidenceTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setEvidence(source);
  }
  function closeEvidence() {
    setEvidence(undefined);
    evidenceTrigger.current?.focus();
  }
  const topics = report.topics || [];
  const openingSections = new Set(["people", "purpose", "summary"]);
  return <article className="ex-report-document" aria-label="Saved meeting report">
    <header className="ex-report-cover"><span className="ex-record-label">{report.simulated ? "Simulated analysis" : "Meeting report"} · Revision {report.revision}</span>
      <h2>{report.meeting.title}</h2><p>{new Date(report.session.created_at).toLocaleDateString(undefined, { dateStyle: "long" })} · {timestamp(report.duration_ms)} transcript span</p>
    </header>
    <nav className="ex-report-contents" aria-label="Report sections">{report.sections.map(s => <a href={`#report-${s.key}`} key={s.key} onClick={e => {
      // Preserve the app's meeting hash when navigating within this saved document.
      e.preventDefault();
      const target = document.getElementById(`report-${s.key}`);
      if (target instanceof HTMLDetailsElement) target.open = true;
      if (target) { target.tabIndex = -1; target.focus({ preventScroll: true }); target.scrollIntoView({ block: "start" }); }
    }}>{s.title}</a>)}</nav>
    <RecordSections sections={report.sections.filter(s => openingSections.has(s.key))} segments={report.evidence} onEvidence={revealEvidence} />
    <div className="ex-report-readout"><QuestionChart items={report.sections.find(s => s.key === "questions")?.items || []} />
      <div className="ex-report-coverage"><strong>{report.coverage.processed_segments} / {report.coverage.final_segments}</strong><span>final transcript segments analyzed</span>
        {report.coverage.provisional_segments > 0 && <small>{report.coverage.provisional_segments} provisional segments remain</small>}
      </div></div>
    {!!topics.length && <section className="ex-report-topics"><h2>Discussion threads</h2><div>{topics.map(topic => <article key={topic.id} className={topicTone(topic.id)}>
      <span className="ex-record-label">{topic.provisional ? "Tentative" : topic.status === "active" ? "Last focus" : "Paused"}</span><h3>{topic.title}</h3>
      <p>{topic.needs_review ? "Summary needs review: evidence changed." : topic.summary || "Not established"}</p>
      <Sources evidence={referencedEvidence(topic.summary_sources, report.evidence)} onEvidence={revealEvidence} />
    </article>)}</div></section>}
    <RecordSections sections={report.sections.filter(s => !openingSections.has(s.key))} segments={report.evidence} workflows={report.workflows} topics={topics} onEvidence={revealEvidence} />
    <footer className="ex-report-provenance">Saved {new Date(report.generated_at).toLocaleString()} · {report.provider}<br />Based on received and accepted transcript only. Full transcript and editable workflow diagrams are available in the exports.</footer>
    {evidence && <div className="ex-report-evidence" role="region" aria-label="Report evidence" tabIndex={-1} ref={evidencePanel} onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); closeEvidence(); } }}>
      <header><strong>{evidence.speaker_name || evidence.speaker_id} · {timestamp(evidence.start_ms)} · Revision {evidence.revision}{evidence.superseded ? " · Earlier evidence" : ""}</strong>
        <button aria-label="Close report evidence" onClick={closeEvidence}><X size={16} /></button></header>
      <blockquote>{evidence.text}</blockquote><small>Evidence saved with this report</small>
    </div>}
  </article>;
}
