import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  Folder,
  MessageSquare,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../types";
import type { Detail, Meeting, Workspace } from "./data";
import { MeetingView } from "./MeetingView";
import { Logo } from "./Logo";
import "./explore.css";
export default function Explore() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wid, setWid] = useState("");
  const [mid, setMid] = useState("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [modal, setModal] = useState<"workspace" | "meeting" | "clear">(
    "meeting",
  );
  const dialog = useRef<HTMLDialogElement>(null);
  const activeWorkspace = useRef(wid);
  useEffect(() => {
    activeWorkspace.current = wid;
  }, [wid]);
  const workspace = workspaces.find((w) => w.id === wid);
  const loadMeetings = useCallback(async () => {
    if (!wid) return;
    const items = await api<Meeting[]>(`/workspaces/${wid}/meetings`);
    if (activeWorkspace.current !== wid) return;
    setMeetings(items);
    setMid((current) =>
      items.some((m) => m.id === current) ? current : items[0]?.id || "",
    );
  }, [wid]);
  useEffect(() => {
    let active = true;
    api<Workspace[]>("/workspaces")
      .then((items) => {
        if (active) {
          setWorkspaces(items);
          setWid(
            items.find(
              (w) => w.id === localStorage.getItem("explore.workspace"),
            )?.id ||
              items[0]?.id ||
              "",
          );
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setMeetings([]);
    setMid("");
    if (wid)
      api<Meeting[]>(`/workspaces/${wid}/meetings`)
        .then((items) => {
          if (active) {
            setMeetings(items);
            setMid(
              items.find(
                (m) => m.id === localStorage.getItem("explore.meeting"),
              )?.id ||
                items[0]?.id ||
                "",
            );
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [wid]);
  function open(kind: typeof modal) {
    setModal(kind);
    setName("");
    setError("");
    dialog.current?.showModal();
  }
  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (modal === "workspace") {
        const item = await api<Workspace>("/workspaces", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        setWorkspaces((items) => [...items, item]);
        setWid(item.id);
        localStorage.setItem("explore.workspace", item.id);
      } else if (modal === "meeting") {
        const item = await api<Detail>(`/workspaces/${wid}/meetings`, {
          method: "POST",
          body: JSON.stringify({ title: name }),
        });
        const items = await api<Meeting[]>(`/workspaces/${wid}/meetings`);
        setMeetings(items);
        setMid(item.meeting.id);
        localStorage.setItem("explore.meeting", item.meeting.id);
      } else {
        await api(`/workspaces/${wid}/meetings`, { method: "DELETE" });
        setMeetings([]);
        setMid("");
      }
      dialog.current?.close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="explore">
      <aside className="ex-sidebar">
        <a className="ex-brand" href="/">
          <Logo />
          Explore
        </a>
        <label className="ex-label" htmlFor="workspace">
          Workspace
        </label>
        <div className="ex-workspace-select">
          <select
            id="workspace"
            value={wid}
            onChange={(e) => {
              localStorage.setItem("explore.workspace", e.target.value);
              setWid(e.target.value);
            }}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <button aria-label="New workspace" onClick={() => open("workspace")}>
            <Plus size={17} />
          </button>
        </div>
        <div className="ex-nav-heading">
          <span>
            <Folder size={14} />
            Meetings
          </span>
          <button
            aria-label="New meeting"
            disabled={!wid}
            onClick={() => open("meeting")}
          >
            <Plus size={16} />
          </button>
        </div>
        <nav aria-label="Meetings">
          {meetings.map((m) => (
            <button
              key={m.id}
              className={mid === m.id ? "selected" : ""}
              aria-current={mid === m.id ? "page" : undefined}
              onClick={() => {
                localStorage.setItem("explore.meeting", m.id);
                setMid(m.id);
              }}
            >
              <MessageSquare size={15} />
              <span>{m.title}</span>
            </button>
          ))}
        </nav>
        <div className="ex-sidebar-bottom">
          <span>Local workspace</span>
          <button
            disabled={!wid || !meetings.length}
            onClick={() => open("clear")}
          >
            <Trash2 size={13} />
            Clear meetings
          </button>
        </div>
      </aside>
      <main className="ex-main">
        {error && !dialog.current?.open && (
          <div className="ex-error" role="alert">
            {error}
            <button onClick={() => location.reload()}>Reload</button>
          </div>
        )}
        {mid ? (
          <MeetingView
            key={mid}
            id={mid}
            workspace={workspace?.name || ""}
            onChanged={loadMeetings}
          />
        ) : (
          <div className="ex-empty">
            <Folder size={32} />
            <h1>{workspace?.name || "Explore"}</h1>
            <p>Create a meeting to start your research.</p>
            <button
              className="ex-primary"
              disabled={!wid}
              onClick={() => open("meeting")}
            >
              <Plus size={15} />
              New meeting
            </button>
          </div>
        )}
      </main>
      <dialog
        className="ex-dialog"
        ref={dialog}
        onCancel={(e) => {
          if (busy) e.preventDefault();
        }}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <header>
            <h2>
              {modal === "workspace"
                ? "New workspace"
                : modal === "meeting"
                  ? "New meeting"
                  : "Clear workspace meetings?"}
            </h2>
            <button
              type="button"
              aria-label="Close dialog"
              disabled={busy}
              onClick={() => dialog.current?.close()}
            >
              <X size={19} />
            </button>
          </header>
          {modal === "clear" ? (
            <p>
              Delete all meetings, transcripts, questions, briefs and notes in{" "}
              <strong>{workspace?.name}</strong>. Other workspaces are kept.
              This cannot be undone.
            </p>
          ) : (
            <label>
              Name
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                required
              />
            </label>
          )}
          {error && (
            <p className="ex-error" role="alert">
              {error}
            </p>
          )}
          <footer>
            <button
              type="button"
              disabled={busy}
              onClick={() => dialog.current?.close()}
            >
              Cancel
            </button>
            <button
              className={modal === "clear" ? "ex-danger" : "ex-primary"}
              disabled={busy || (modal !== "clear" && !name.trim())}
            >
              {busy
                ? "Saving…"
                : modal === "clear"
                  ? "Delete meetings"
                  : "Create"}
            </button>
          </footer>
        </form>
      </dialog>
    </div>
  );
}
