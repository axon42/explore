import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  Folder,
  X,
} from "lucide-react";
import { api } from "../types";
import type { Detail, Meeting, Workspace } from "./data";
import { Developer } from "./Developer";
import { Archives } from "./Archives";
import { MeetingView } from "./MeetingView";
import { Sidebar } from "./Sidebar";
import "./theme.css";
import "./explore.css";
import "./records.css";
import "./sidebar.css";
import "./select.css";
export default function Explore() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wid, setWid] = useState("");
  const [mid, setMid] = useState("");
  const [search, setSearch] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try { const mode = await api<{ enabled: boolean }>("/settings/test-mode", { signal: abort.signal }); if (!abort.signal.aborted) setTestMode(mode.enabled); }
      catch { /* Mutations remain gated on the backend if status is unavailable. */ }
      if (!abort.signal.aborted) timer = setTimeout(() => void load(), 1500);
    }
    void load(); return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  const [page, setPage] = useState<"meetings" | "archives" | "developer">("meetings");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [modal, setModal] = useState<"workspace" | "meeting" | "clear" | "archive-workspace">(
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
    const visible = items.filter(m => !m.archived);
    setMeetings(visible);
    setMid((current) =>
      visible.some((m) => m.id === current) ? current : visible[0]?.id || "",
    );
  }, [wid]);
  const loadWorkspaces = useCallback(async () => {
    const items = await api<Workspace[]>("/workspaces");
    setWorkspaces(items);
    setWid(current => items.find(w => !w.archived && w.id === current)?.id || items.find(w => !w.archived)?.id || "");
  }, []);
  useEffect(() => {
    let active = true;
    api<Workspace[]>("/workspaces").then(items => {
      if (!active) return;
      setWorkspaces(items);
      setWid(items.find(w => !w.archived && w.id === localStorage.getItem("explore.workspace"))?.id || items.find(w => !w.archived)?.id || "");
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setMeetings([]);
    setMid("");
    if (wid)
      api<Meeting[]>(`/workspaces/${wid}/meetings`)
        .then((rows) => {
          const items = rows.filter(m => !m.archived);
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
    requestAnimationFrame(() => {
      dialog.current?.showModal();
      const target = kind === "clear" || kind === "archive-workspace" ? "footer button" : "input";
      dialog.current?.querySelector<HTMLElement>(target)?.focus();
    });
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
        setMeetings(items.filter(m => !m.archived));
        setMid(item.meeting.id);
        localStorage.setItem("explore.meeting", item.meeting.id);
      } else if (modal === "archive-workspace") {
        await api(`/workspaces/${wid}/archive`, { method: "PATCH", body: JSON.stringify({ revision: workspace?.revision, archived: true }) });
        await loadWorkspaces();
      } else {
        await api(`/workspaces/${wid}/meetings/archive`, { method: "POST" });
        setMeetings([]);
        setMid("");
      }
      setPage("meetings");
      dialog.current?.close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="explore">
      <Sidebar workspaces={workspaces} wid={wid} meetings={meetings} mid={mid} page={page}
        search={search} testMode={testMode} modeBusy={modeBusy} onSearch={setSearch} onPage={setPage} onOpen={open}
        onWorkspace={id => { localStorage.setItem("explore.workspace", id); setPage("meetings"); setSearch(""); setWid(id); }}
        onMeeting={id => { localStorage.setItem("explore.meeting", id); setMid(id); setPage("meetings"); }}
        onTestMode={async () => {
          setModeBusy(true);
          try { const mode = await api<{ enabled: boolean }>("/settings/test-mode", { method: "PUT", body: JSON.stringify({ enabled: !testMode }) }); setTestMode(mode.enabled); }
          catch (e) { setError((e as Error).message); }
          finally { setModeBusy(false); }
        }} />
      <main className="ex-main">
        {error && !dialog.current?.open && (
          <div className="ex-error" role="alert">
            {error}
            <button onClick={() => location.reload()}>Reload</button>
          </div>
        )}
        {page === "developer" ? <Developer /> : page === "archives" ? <Archives workspaces={workspaces} testMode={testMode} onChanged={async () => { await loadWorkspaces(); await loadMeetings(); }} /> : mid ? (
          <MeetingView
            key={mid}
            id={mid}
            workspace={workspace?.name || ""}
            onChanged={loadMeetings}
            testMode={testMode}
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
        aria-labelledby="workspace-dialog-title"
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
            <h2 id="workspace-dialog-title">
              {modal === "workspace"
                ? "New workspace"
                : modal === "meeting"
                  ? "New meeting"
                  : modal === "clear" ? "Archive all meetings?" : "Archive workspace?"}
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
          {modal === "clear" || modal === "archive-workspace" ? (
            <p>{modal === "clear" ? "Move all meetings in" : "Move"} <strong>{workspace?.name}</strong> {modal === "clear" ? "to Archives?" : "and its meetings to Archives?"} You can restore them at any time. End active meetings first.</p>
          ) : (
            <label>
              Name
              <input
                autoFocus
                disabled={busy}
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
              className="ex-primary"
              disabled={busy || ((modal === "workspace" || modal === "meeting") && !name.trim())}
            >
              {busy
                ? "Saving…"
                : modal === "clear"
                  ? "Archive meetings"
                  : modal === "archive-workspace" ? "Archive workspace" : "Create"}
            </button>
          </footer>
        </form>
      </dialog>
    </div>
  );
}
