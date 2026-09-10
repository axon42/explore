import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowDown,
  ArrowUpRight,
  AudioLines,
  Check,
  Circle,
  FileText,
  LoaderCircle,
  Plus,
  Radio,
  Square,
  WifiOff,
  X,
} from "lucide-react";
import { api, timestamp } from "./types";
import type { Session } from "./types";
import { useTranscript } from "./useTranscript";

function dateLabel(date: string) {
  return new Date(date).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState(location.hash.slice(1));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [demoEnabled, setDemoEnabled] = useState(false);
  const select = useCallback((id: string) => {
    setSelected(id);
    history.replaceState(null, "", `#${id}`);
  }, []);
  const updateSession = useCallback((session: Session) => {
    setSessions((current) => {
      const previous = current.find((item) => item.id === session.id);
      if (previous && previous.version >= session.version) return current;
      return [
        session,
        ...current.filter((item) => item.id !== session.id),
      ].sort((a, b) => b.created_at.localeCompare(a.created_at));
    });
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [items, health] = await Promise.all([
        api<Session[]>("/sessions"),
        api<{ demo_enabled: boolean }>("/health"),
      ]);
      setSessions(items);
      setDemoEnabled(health.demo_enabled);
      const hash = location.hash.slice(1);
      if (items.length)
        select(items.some((item) => item.id === hash) ? hash : items[0].id);
      else select("");
    } catch {
      setError(
        "Could not reach the local server. Check that it is running, then retry.",
      );
    } finally {
      setLoading(false);
    }
  }, [select]);
  useEffect(() => {
    void load();
  }, [load]);
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ title }),
      });
      updateSession(session);
      select(session.id);
      setCreating(false);
      setTitle("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Session history">
        <a
          className="brand"
          href="#"
          onClick={(event) => event.preventDefault()}
          aria-label="Still meeting transcripts"
        >
          <span className="brand-symbol">
            <AudioLines size={20} />
          </span>
          still<span className="brand-period">.</span>
        </a>
        <button className="new-session" onClick={() => setCreating(true)}>
          <Plus size={17} /> New session <span className="button-hint">＋</span>
        </button>
        {creating && (
          <form className="create-form" onSubmit={create}>
            <div className="form-heading">
              <label htmlFor="session-title">
                Session title <span>(optional)</span>
              </label>
              <button
                type="button"
                className="icon-button"
                aria-label="Cancel new session"
                onClick={() => setCreating(false)}
              >
                <X size={15} />
              </button>
            </div>
            <input
              id="session-title"
              autoFocus
              maxLength={120}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. Monday standup"
            />
            <button className="primary small" disabled={busy}>
              {busy ? "Creating…" : "Create session"}
              <ArrowUpRight size={15} />
            </button>
          </form>
        )}
        <div className="sidebar-label">
          SESSIONS <span>{sessions.length.toString().padStart(2, "0")}</span>
        </div>
        <nav className="session-list" aria-label="Previous sessions">
          {loading && <p className="sidebar-empty">Loading sessions…</p>}
          {!loading && sessions.length === 0 && (
            <p className="sidebar-empty">
              Your conversations will
              <br />
              appear here.
            </p>
          )}
          {sessions.map((session) => (
            <button
              key={session.id}
              className={`session-item ${selected === session.id ? "selected" : ""}`}
              aria-current={selected === session.id ? "page" : undefined}
              onClick={() => select(session.id)}
            >
              <FileText size={17} className="session-icon" />
              <span className="session-item-copy">
                <strong>{session.title}</strong>
                <span>
                  {dateLabel(session.created_at)}
                  <span className="separator">·</span>
                  {session.status === "live" ? "In progress" : "Stopped"}
                </span>
              </span>
              {session.status === "live" && <span className="live-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="local-icon">
            <Check size={14} />
          </span>
          <div>
            Stored on this device<small>Your transcripts stay local.</small>
          </div>
        </div>
      </aside>
      <main>
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => void load()}>Retry</button>
          </div>
        )}
        {selected ? (
          <SessionView
            key={selected}
            id={selected}
            onSession={updateSession}
            demoEnabled={demoEnabled}
          />
        ) : (
          <>
            <header className="workspace-header">
              <span className="eyebrow">YOUR WORKSPACE</span>
              <span className="local-label">
                <span className="live-dot" /> Local only
              </span>
            </header>
            <div className="welcome">
              <div className="empty-mark">
                <AudioLines size={32} strokeWidth={1.4} />
              </div>
              <span className="eyebrow">ROOM FOR THE CONVERSATION</span>
              <h1>
                A clear record.
                <br />
                One conversation at a time.
              </h1>
              <p>
                Create a session to bring your transcript into focus.
                <br />
                Try a short demo to see it unfold.
              </p>
              <button className="primary" onClick={() => setCreating(true)}>
                <Plus size={17} /> New session
              </button>
              <span className="empty-footnote">
                No recording. No accounts. Just the transcript.
              </span>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function SessionView({
  id,
  onSession,
  demoEnabled,
}: {
  id: string;
  onSession: (session: Session) => void;
  demoEnabled: boolean;
}) {
  const state = useTranscript(id, onSession);
  const [actionError, setActionError] = useState("");
  const [action, setAction] = useState("");
  const [demoStarted, setDemoStarted] = useState(false);
  const [away, setAway] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const { session, segments, connection } = state;
  useEffect(() => {
    if (nearBottom.current && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [segments]);
  async function perform(kind: "demo" | "stop") {
    setAction(kind);
    setActionError("");
    try {
      const result = await api<Session>(`/sessions/${id}/${kind}`, {
        method: "POST",
      });
      if (kind === "demo") setDemoStarted(true);
      else onSession(result);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setAction("");
    }
  }
  const connected = connection === "connected";
  const demoUsed =
    demoStarted ||
    segments.some((segment) => segment.event_id.startsWith("demo-"));
  const stopped = session?.status === "stopped";
  const duration = segments.length
    ? Math.max(...segments.map((segment) => segment.end_ms))
    : 0;
  const speakers = new Set(segments.map((segment) => segment.speaker_id));
  return (
    <div className="session-view">
      <header className="session-header">
        <div>
          <div className="session-kicker">
            <span className="eyebrow">SESSION</span>
            {session && (
              <span className={`status-tag ${stopped ? "stopped" : ""}`}>
                <span className={stopped ? "stopped-dot" : "live-dot"} />
                {stopped ? "Stopped" : "Live session"}
              </span>
            )}
          </div>
          <h1>{session?.title || "Loading session…"}</h1>
          <p className="session-date">
            {session &&
              new Date(session.created_at).toLocaleString(undefined, {
                month: "long",
                day: "numeric",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
          </p>
        </div>
        <div className="session-actions">
          <span
            className={`connection ${connected ? "" : "offline"}`}
            role="status"
          >
            {connected ? <Radio size={14} /> : <WifiOff size={14} />}
            {
              {
                connected: "Connected",
                connecting: "Connecting…",
                reconnecting: "Reconnecting…",
                disconnected: "Disconnected",
              }[connection]
            }
          </span>
          {!stopped && (
            <div className="controls">
              {demoEnabled && (
                <button
                  className="primary small"
                  disabled={!connected || !!action || demoUsed}
                  onClick={() => void perform("demo")}
                >
                  {action === "demo" ? (
                    <LoaderCircle className="spin" size={14} />
                  ) : (
                    <AudioLines size={15} />
                  )}
                  {demoUsed ? "Demo started" : "Start demo"}
                </button>
              )}
              <button
                className="secondary small"
                disabled={!connected || !!action || !session}
                onClick={() => void perform("stop")}
              >
                <Square size={12} />
                {action === "stop" ? "Stopping…" : "Stop session"}
              </button>
            </div>
          )}
        </div>
      </header>
      <div className="transcript-toolbar">
        <span>
          <FileText size={15} /> Transcript
        </span>
        <span>
          {speakers.size} {speakers.size === 1 ? "speaker" : "speakers"}
          <i />
          {timestamp(duration)}
        </span>
      </div>
      {(state.error || actionError) && (
        <div className="error-banner" role="alert">
          {actionError || state.error}
        </div>
      )}
      {!connected && session && (
        <div className="connection-banner">
          Showing saved transcript.{" "}
          {connection === "disconnected"
            ? "Connection lost; retrying automatically."
            : "Waiting for the live connection…"}
        </div>
      )}
      <div
        className="transcript-scroll"
        ref={scroll}
        onScroll={() => {
          if (!scroll.current) return;
          const element = scroll.current;
          nearBottom.current =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            100;
          setAway(!nearBottom.current);
        }}
      >
        {!session && (
          <div className="transcript-empty">
            <LoaderCircle className="spin" size={25} />
            <h2>Opening your session</h2>
            <p>Loading the saved transcript…</p>
          </div>
        )}
        {session && segments.length === 0 && (
          <div className="transcript-empty">
            <div className="empty-mark">
              <AudioLines size={30} strokeWidth={1.3} />
            </div>
            <h2>{stopped ? "A quiet session." : "Ready when you are."}</h2>
            <p>
              {stopped
                ? "This session ended without a transcript."
                : demoEnabled
                  ? "Start the demo and watch the conversation take shape."
                  : "Waiting for transcript events from your provider."}
            </p>
            {!stopped && demoEnabled && (
              <span className="demo-note">
                <Circle size={7} fill="currentColor" /> Two speakers. A short
                conversation. All local.
              </span>
            )}
          </div>
        )}
        {segments.length > 0 && (
          <div className="transcript-content">
            <div className="transcript-start">
              <span />
              {stopped ? "SESSION TRANSCRIPT" : "CONVERSATION STARTED"}
              <span />
            </div>
            {segments.map((segment, index) => (
              <article
                className={`segment ${segment.is_final ? "final" : "provisional"}`}
                key={segment.segment_id}
                data-testid="segment"
                data-final={segment.is_final}
              >
                <div
                  className={`speaker-avatar speaker-${[...speakers].indexOf(segment.speaker_id) % 2}`}
                >
                  {(segment.speaker_name || segment.speaker_id)
                    .slice(0, 1)
                    .toUpperCase()}
                </div>
                <div className="segment-body">
                  <div className="segment-meta">
                    <strong>
                      {segment.speaker_name || segment.speaker_id}
                    </strong>
                    <time>{timestamp(segment.start_ms)}</time>
                    {!segment.is_final && (
                      <span className="draft-label">Live draft</span>
                    )}
                  </div>
                  <p>
                    {segment.text}
                    {!segment.is_final && <span className="typing-cursor" />}
                  </p>
                </div>
                <span className="segment-number" aria-hidden="true">
                  {(index + 1).toString().padStart(2, "0")}
                </span>
              </article>
            ))}
            <div className="transcript-end">
              {stopped ? (
                <>
                  <Check size={13} /> Session ended · Saved on this device
                </>
              ) : (
                <>
                  <span className="live-dot" /> Listening for transcript events
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {away && (
        <button
          className="jump-button"
          onClick={() => {
            nearBottom.current = true;
            scroll.current?.scrollTo({
              top: scroll.current.scrollHeight,
              behavior: "smooth",
            });
            setAway(false);
          }}
        >
          <ArrowDown size={15} /> Jump to latest
        </button>
      )}
      <footer className="transcript-footer">
        <span>
          <span className={stopped ? "stopped-dot" : "live-dot"} />
          {stopped ? "Session complete" : "Live transcript"}
        </span>
        <span>
          {segments.length} {segments.length === 1 ? "segment" : "segments"}
          <span className="separator">·</span>Saved locally
        </span>
      </footer>
    </div>
  );
}
