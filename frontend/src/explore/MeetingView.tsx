import { AnalysisControls } from "./AnalysisControls";
import { Select } from "./Select";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  MessageSquare,
  Pause,
  Play,
  RotateCcw,
  Send,
  SkipForward,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import { api, timestamp } from "../types";
import type { Evidence, Question } from "./data";
import { Preparation } from "./Preparation";
import { useMeeting } from "./useMeeting";
import { SpokenQuestions } from "./SpokenQuestions";
import { groupTranscript } from "./transcript";
import { AudioCapture } from "./AudioCapture";
import { Speakers } from "./Speakers";
import type { Passage } from "./Speakers";
import { BriefEditor, Notes } from "./Editors";
import { GeneratedNotes, Participants, Reports } from "./Records";
import { DiscussionThreads } from "./DiscussionThreads";
export function MeetingView({
  id,
  workspace,
  onChanged,
  testMode,
}: {
  testMode: boolean;
  id: string;
  workspace: string;
  onChanged: () => Promise<void>;
}) {
  const [refresh, setRefresh] = useState(0);
  const { bundle, error } = useMeeting(id, refresh);
  const [tab, setTab] = useState("Interview");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [text, setText] = useState("");
  const [speaker, setSpeaker] = useState("customer");
  const [focus, setFocus] = useState<Evidence>();
  const [speakerPassage, setSpeakerPassage] = useState<Passage>();
  const resetDialog = useRef<HTMLDialogElement>(null);
  const injectionId = useRef<string | undefined>(undefined);
  const transcriptScroll = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [away, setAway] = useState(false);
  useEffect(() => {
    if (nearBottom.current && transcriptScroll.current)
      transcriptScroll.current.scrollTop =
        transcriptScroll.current.scrollHeight;
  }, [bundle?.segments]);
  function reload() {
    setRefresh((n) => n + 1);
    void onChanged().catch((e) => setActionError(e.message));
  }
  async function action(path: string, body?: unknown, method = "POST") {
    setBusy(true);
    setActionError("");
    try {
      await api(path, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      reload();
      return true;
    } catch (e) {
      setActionError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  function evidence(source: Evidence) {
    nearBottom.current = false;
    setFocus(source);
    setTab("Interview");
    requestAnimationFrame(() =>
      document
        .getElementById("source-" + source.segment_id)
        ?.scrollIntoView({ block: "center", behavior: "smooth" }),
    );
  }
  if (!bundle)
    return (
      <div className="ex-empty">
        <p>{error || "Loading meeting…"}</p>
        <button onClick={reload}>Retry</button>
      </div>
    );
  const { detail, segments, experiment } = bundle;
  if (!detail.session || !experiment) return <Preparation detail={detail} testMode={testMode} reload={reload} />;
  const testTools = testMode && detail.session.mode !== "real";
  const sid = detail.session.id;
  const stopped = detail.session.status === "stopped";
  const activeQuestions = detail.questions.filter((q) => q.status !== "discarded");
  const answered = detail.questions.filter(
    (q) => q.status === "answered",
  ).length;
  const asked = detail.questions.filter((q) => q.status === "asked").length;
  const shown = detail.questions
    .filter((q) => filter === "all" ? q.status !== "discarded" : q.status === filter)
    .sort(
      (a, b) =>
        ({ queued: 0, asked: 1, answered: 2, discarded: 3 })[a.status] -
        { queued: 0, asked: 1, answered: 2, discarded: 3 }[b.status],
    );
  async function update(q: Question) {
    await action(
      `/meetings/${id}/questions/${q.id}`,
      {
        revision: q.revision,
        status:
          q.status === "queued"
            ? "asked"
            : q.status === "asked"
              ? "answered"
              : "queued",
      },
      "PATCH",
    );
  }
  async function inject() {
    const start = Math.max(0, ...segments.map((s) => s.end_ms));
    injectionId.current ??= crypto.randomUUID();
    const eventId = injectionId.current;
    if (
      await action(`/sessions/${sid}/inject`, {
        event_id: eventId,
        segment_id: eventId,
        revision: 0,
        speaker_id: speaker,
        speaker_name: speaker === "customer" ? "Customer" : "Cofounder",
        start_ms: start,
        end_ms: start + 4000,
        text: text.trim(),
        is_final: true,
      })
    ) {
      setText("");
      injectionId.current = undefined;
    }
  }
  return (
    <>
      <div className="ex-breadcrumb">
        {workspace}
        <ChevronRight size={13} />
        Meetings
      </div>
      <header className="ex-meeting-header">
        <div>
          <h1>{detail.meeting.title}</h1>
          <p className="ex-meeting-meta">
            <span className="ex-status" data-state={stopped ? "stopped" : "live"}>{stopped ? "Stopped" : "In progress"}</span>
            {detail.brief.customer || "Customer discovery"}
          </p>
        </div>
        <div className="ex-header-actions">
          {testTools && !stopped && <a href={`/zoom-proof.html?session=${encodeURIComponent(sid)}`} target="_blank" rel="noopener noreferrer">Zoom test ↗</a>}
          <span className="ex-mode">
            {experiment.provider === "mock" ? "Simulated analysis" : experiment.model}
          </span>
          <button disabled={busy || (!stopped && !detail.meeting.archived)} title={!stopped ? "Stop the meeting before archiving" : undefined} onClick={() => void action(`/meetings/${id}/preferences`, {revision: detail.meeting.context_version, archived: !detail.meeting.archived}, "PATCH")}>
            {detail.meeting.archived ? "Restore meeting" : "Archive meeting"}
          </button>
          {!stopped && <button disabled={busy} onClick={() => void action(`/sessions/${sid}/stop`)}>End interview</button>}
          {detail.session.mode === "test" && <span className="ex-mode">Test meeting</span>}
          {testTools && <button disabled={!!detail.meeting.archived} onClick={() => resetDialog.current?.showModal()}>
            <RotateCcw size={14} />
            Reset test
          </button>}
        </div>
      </header>
      <nav className="ex-tabs" aria-label="Meeting views">
        {["Interview", "Overview", "Brief", "Notes", "Report"].map((name) => (
          <button
            key={name}
            aria-current={name === tab ? "page" : undefined}
            onClick={() => setTab(name)}
          >
            {name}
            {name === "Notes" && detail.notes.length > 0 && (
              <span>{detail.notes.length}</span>
            )}
          </button>
        ))}
      </nav>
      {(error || actionError || experiment.error) && (
        <div className="ex-error" role="alert">
          {actionError || error || experiment.error}
          <button onClick={reload}>Refresh</button>
        </div>
      )}
      <div className="ex-content">
        <AnalysisControls key={sid} sid={sid} experiment={experiment} archived={!!detail.meeting.archived} reload={reload} />
        {tab === "Interview" && (
          <>
            <AudioCapture key={sid} mid={id} sid={sid} stopped={stopped} />
            <Speakers key={`speakers-${sid}`} mid={id} sid={sid} passage={speakerPassage} onClose={() => setSpeakerPassage(undefined)} />
            <div className="ex-interview-grid">
              <div className="ex-conversation">
              <section className="ex-transcript">
                <div className="ex-panel-title">
                  <h2>
                    <span className="ex-icon"><MessageSquare size={16} /></span>
                    Transcript
                  </h2>
                  <span>
                    {segments.length}{" "}
                    {segments.length === 1 ? "segment" : "segments"}
                  </span>
                </div>
                {focus && (
                  <div className="ex-evidence">
                    <header>
                      <strong>
                        {focus.superseded
                          ? "Earlier transcript revision"
                          : "Evidence"}{" "}
                        · {timestamp(focus.start_ms)}
                      </strong>
                      <button
                        aria-label="Close evidence"
                        onClick={() => setFocus(undefined)}
                      >
                        <X size={14} />
                      </button>
                    </header>
                    <p>{focus.text}</p>
                  </div>
                )}
                <div
                  className="ex-transcript-list"
                  ref={transcriptScroll}
                  onScroll={() => {
                    const el = transcriptScroll.current;
                    if (el) {
                      nearBottom.current =
                        el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                      setAway(!nearBottom.current);
                    }
                  }}
                >
                  {groupTranscript(segments).map((group) => (
                    <article key={`${group[0].segment_id}-${group[0].span_index ?? "legacy"}`}>
                      <header>
                        <span className={"ex-avatar " + (group[0].speaker_id === "customer" ? "customer" : "")}>{(group[0].speaker_name || group[0].speaker_id)[0]}</span>
                        <strong>{group[0].speaker_name || group[0].speaker_id}</strong>
                        {group[0].attribution_status && <small className="ex-speaker-role">{group[0].attribution_status === "confirmed" ? group[0].interview_role : "Unassigned"}</small>}
                        <time>{timestamp(group[0].start_ms)}</time>
                      </header>
                      <p>{group.map((segment) => <span key={`${segment.segment_id}-${segment.span_index ?? "legacy"}`} id={segment.anchor === false ? undefined : "source-" + segment.segment_id} className={focus?.segment_id === segment.segment_id ? "highlight" : undefined}>
                        {segment.text}{!segment.is_final && <small> Draft</small>}{" "}
                      </span>)}</p>
                      {group.some(segment => segment.is_final && segment.span_index !== undefined) && <details className="ex-speaker-corrections">
                        <summary>Correct speaker</summary>
                        <p>Choose the exact passage to assign to a person.</p>
                        <ol>{group.filter(segment => segment.is_final && segment.span_index !== undefined).map((segment, index) => <li key={`${segment.segment_id}-${segment.span_index}`}>
                          <button aria-label={`Correct speaker for passage ${index + 1}`} onClick={() => setSpeakerPassage({ segment_id: segment.segment_id, segment_revision: segment.revision, span_index: segment.span_index!, text: segment.text })}>
                            <small>Passage {index + 1} · {timestamp(segment.start_ms)}</small><span>{segment.text}</span>
                          </button>
                        </li>)}</ol>
                      </details>}
                    </article>
                  ))}
                  {!segments.length && (
                    <div className="ex-empty small">
                      <FileText size={25} />
                      <p>Start audio capture to see the conversation here.</p>
                    </div>
                  )}
                </div>
                {away && (
                  <button
                    className="ex-latest"
                    onClick={() => {
                      nearBottom.current = true;
                      transcriptScroll.current?.scrollTo({
                        top: transcriptScroll.current.scrollHeight,
                        behavior: "smooth",
                      });
                      setAway(false);
                    }}
                  >
                    Latest transcript ↓
                  </button>
                )}
                {testTools && <><div className="ex-playback">
                  <button
                    className="ex-primary"
                    disabled={
                      busy || stopped || experiment.cursor === experiment.total
                    }
                    onClick={() =>
                      void action(`/sessions/${sid}/playback`, {
                        action: experiment.playing ? "pause" : "play",
                        speed: experiment.speed,
                      })
                    }
                  >
                    {experiment.playing ? (
                      <Pause size={14} />
                    ) : (
                      <Play size={14} />
                    )}{" "}
                    {experiment.playing ? "Pause" : "Play"}
                  </button>
                  <button
                    aria-label="Next turn"
                    disabled={
                      busy || stopped || experiment.cursor === experiment.total
                    }
                    onClick={() =>
                      void action(`/sessions/${sid}/playback`, {
                        action: "next",
                        speed: experiment.speed,
                      })
                    }
                  >
                    <SkipForward size={15} />
                  </button>
                  <Select
                    aria-label="Playback speed"
                    disabled={busy || stopped}
                    value={experiment.speed}
                    onValueChange={(value) =>
                      void action(`/sessions/${sid}/playback`, {
                        action: experiment.playing ? "play" : "pause",
                        speed: Number(value),
                      })
                    }
                  >
                    {[0.5, 1, 2, 5, 10].map((n) => (
                      <option key={n} value={n}>
                        {n}×
                      </option>
                    ))}
                  </Select>
                  <span>
                    {experiment.cursor}/{experiment.total} turns
                  </span>
                  {!stopped && (
                    <button
                      className="ex-stop"
                      disabled={busy}
                      onClick={() => void action(`/sessions/${sid}/stop`)}
                    >
                      Stop
                    </button>
                  )}
                </div>
                <details className="ex-inject">
                  <summary>Inject dialogue</summary>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void inject();
                    }}
                  >
                    <Select
                      aria-label="Speaker"
                      value={speaker}
                      disabled={busy || stopped}
                      onValueChange={(value) => {
                        setSpeaker(value);
                        injectionId.current = undefined;
                      }}
                    >
                      <option value="customer">Customer</option>
                      <option value="cofounder">Cofounder</option>
                    </Select>
                    <textarea
                      aria-label="Transcript text"
                      rows={3}
                      value={text}
                      maxLength={20000}
                      disabled={busy || stopped}
                      onChange={(e) => {
                        setText(e.target.value);
                        injectionId.current = undefined;
                      }}
                      placeholder="What did they say?"
                      required
                    />
                    <button disabled={busy || stopped || !text.trim()}>
                      <Send size={13} />
                      Inject
                    </button>
                  </form>
                </details></>}
              </section>
              <DiscussionThreads key={sid} mid={id} sid={sid} stopped={stopped} strategy={experiment.strategy} analyzing={experiment.analysis_status === "analyzing"} segments={segments} onEvidence={evidence} />
              <SpokenQuestions items={detail.spoken_questions || []} onEvidence={evidence} />
              </div>
              <section className="ex-questions">
                <div className="ex-panel-title">
                  <h2>
                    <span className="ex-icon ex-icon-ai"><Sparkles size={16} /></span>
                    Questions
                  </h2>
                  <span>
                    {experiment.analysis_status === "analyzing"
                      ? "Analyzing…"
                      : `${detail.questions.length} collected`}
                  </span>
                </div>
                {experiment.scheduling?.mode === "manual" && (experiment.scheduling.pending_segments > 0 || segments.some((segment) => !segment.is_final)) && activeQuestions.length > 0 && (
                  <p className="ex-muted" role="status">New speech has not been analyzed. It may already answer a suggested question.</p>
                )}
                <div className="ex-progress">
                  <div>
                    <strong>
                      {answered} / {activeQuestions.length}
                    </strong>{" "}
                    answered<span>{asked} asked</span>
                    <span>{activeQuestions.length - answered - asked} queued</span>
                  </div>
                  <label>Question frequency <Select aria-label="Question frequency" disabled={busy} value={detail.meeting.question_interval} onValueChange={(value) => void action(`/meetings/${id}/preferences`, {revision: detail.meeting.context_version, question_interval: Number(value)}, "PATCH")}>
                    <option value={30}>At most every 30 seconds</option>
                    <option value={60}>At most every minute</option>
                    <option value={120}>At most every 2 minutes</option>
                    <option value={0}>Off · notes only</option>
                  </Select></label>
                </div>
                <div className="ex-filters">
                  {["all", "queued", "asked", "answered", "discarded"].map((name) => (
                    <button
                      key={name}
                      aria-pressed={filter === name}
                      onClick={() => setFilter(name)}
                    >
                      {name}
                      <span>
                        {name === "all"
                          ? activeQuestions.length
                          : detail.questions.filter((q) => q.status === name)
                              .length}
                      </span>
                    </button>
                  ))}
                </div>
                {shown.map((q) => (
                  <article className={"ex-question " + q.status} key={q.id}>
                    <header>
                      <span className={`ex-question-status ${q.status}`}>{q.status}</span>
                      {q.evidence.some((e) => e.superseded) && (
                        <span>Evidence revised</span>
                      )}
                    </header>
                    <button
                      className="ex-question-title"
                      onClick={() => q.evidence[0] && evidence(q.evidence[0])}
                    >
                      {q.text}
                    </button>
                    {q.needs_review && <p className="ex-speaker-review">Speaker details changed · review this question</p>}
                    <p>{q.rationale}</p>
                    <footer>
                      <div className="ex-sources">
                        {q.evidence.map((e, i) => (
                          <button key={i} onClick={() => evidence(e)}>
                            {timestamp(e.start_ms)} ↗
                          </button>
                        ))}
                      </div>
                      {q.status !== "discarded" && <button className="ex-quiet" disabled={busy} onClick={() => void action(`/meetings/${id}/questions/${q.id}`, {revision: q.revision, status: "discarded"}, "PATCH")}>Discard</button>}
                      <button className="ex-suggestion-action" disabled={busy} onClick={() => void update(q)}>
                        {q.status === "queued"
                          ? "Mark asked"
                          : q.status === "asked"
                            ? "Mark answered"
                            : q.status === "discarded" ? "Restore" : "Reopen"}
                        <Check size={12} />
                      </button>
                    </footer>
                  </article>
                ))}
                {!shown.length && (
                  <div className="ex-empty small">
                    <p>
                      {detail.questions.length
                        ? "No questions in this view."
                        : "Questions collect here as the interview unfolds."}
                    </p>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
        {tab === "Overview" && (
          <section className="ex-overview">
            <div className="ex-summary">
              <h2><span className="ex-icon"><MessageSquare size={16} /></span>Discussion so far</h2>
              <p>
                {detail.overview ||
                  "No analysis yet. Capture speech, then use the analysis controls above."}
              </p>
              {detail.overview_input_version !== null && (
                <small>
                  {detail.overview_input_version !== detail.session.version ||
                  detail.overview_context_version !==
                    detail.meeting.context_version
                    ? "Earlier analysis · newer context available"
                    : "Based on the current conversation"}
                </small>
              )}
            </div>
            {[...(detail.workflows || []).map(w => ({ ...w, findings: detail.findings.filter(f => f.workflow_key === w.key && f.topic_id === w.topic_id) })),
              { key: "", topic_id: "", title: "Not linked to a workflow", findings: detail.findings.filter(f => !f.workflow_key || !(detail.workflows || []).some(w => w.key === f.workflow_key && w.topic_id === f.topic_id)) }
            ].filter(group => group.findings.length).map(group => <section className="ex-workflow-group" key={JSON.stringify([group.topic_id,group.key])}>
            <h2>{group.title}</h2><div className="ex-findings">
              {group.findings.map((f) => (
                <article className={f.kind} key={f.id}>
                  <span className="ex-category">
                    {f.kind === "gap" ? <CircleHelp size={13} /> : f.kind === "opportunity" ? <Sparkles size={13} /> : <Workflow size={13} />}
                    {f.kind === "opportunity"
                      ? "Automation possibility"
                      : f.kind}
                  </span>
                  <h3>{f.title}</h3>
                  <p>{f.body}</p>
                  <footer>
                    <span>
                      {f.kind === "opportunity"
                        ? "Unvalidated hypothesis"
                        : f.basis}
                      {f.evidence.some((e) => e.superseded)
                        ? " · evidence revised"
                        : ""}
                    </span>
                    <div className="ex-sources">
                      {f.evidence.map((e, i) => (
                        <button key={i} onClick={() => evidence(e)}>
                          {timestamp(e.start_ms)} ↗
                        </button>
                      ))}
                    </div>
                  </footer>
                </article>
              ))}
            </div></section>)}
          </section>
        )}
        {tab === "Brief" && <><BriefEditor detail={detail} onSaved={reload} /><Participants key={id} mid={id} /></>}
        {tab === "Notes" && (
          <><Notes mid={id} notes={detail.notes} onSaved={reload} /><GeneratedNotes key={sid} mid={id} /></>
        )}
        {tab === "Report" && <Reports key={sid} mid={id} sid={sid} stopped={stopped} onChanged={reload} />}
      </div>
      <dialog
        ref={resetDialog}
        className="ex-dialog"
        aria-labelledby="reset-dialog-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
        }}
      >
        <header>
          <h2 id="reset-dialog-title">Reset this test?</h2>
          <button
            aria-label="Close reset dialog"
            disabled={busy}
            onClick={() => resetDialog.current?.close()}
          >
            <X size={18} />
          </button>
        </header>
        <p>
          Clear this meeting’s working transcript, questions, analysis and reports. Keep its
          brief, notes and separate transcript archive. The meeting returns to Draft; old transcript
          streams cannot write to it.
        </p>
        {actionError && (
          <p className="ex-error" role="alert">
            {actionError}
          </p>
        )}
        <footer>
          <button disabled={busy} onClick={() => resetDialog.current?.close()}>
            Cancel
          </button>
          <button
            className="ex-danger"
            disabled={busy}
            onClick={async () => {
              if (await action(`/meetings/${id}/reset`, { session_id: sid })) {
                setFocus(undefined);
                setFilter("all");
                setText("");
                injectionId.current = undefined;
                resetDialog.current?.close();
              }
            }}
          >
            Reset test
            <ArrowRight size={14} />
          </button>
        </footer>
      </dialog>
    </>
  );
}
