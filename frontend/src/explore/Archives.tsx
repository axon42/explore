import { Select } from "./Select";
import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArrowLeft, Trash2 } from "lucide-react";
import { api } from "../types";
import type { Meeting, Workspace } from "./data";
import { MeetingView } from "./MeetingView";

type ArchivedMeeting = Meeting & { workspace_name: string; workspace_archived: number; mode: string };
export function Archives({ workspaces, onChanged, testMode }: { workspaces: Workspace[]; onChanged: () => Promise<void>; testMode: boolean }) {
  const [items, setItems] = useState<ArchivedMeeting[]>([]);
  const [search, setSearch] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [mode, setMode] = useState("");
  const [tab, setTab] = useState<"meetings" | "workspaces">("meetings");
  const [opened, setOpened] = useState<ArchivedMeeting | null>(null);
  const [deleting, setDeleting] = useState<ArchivedMeeting | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const load = useCallback(async () => setItems(await api<ArchivedMeeting[]>("/archives/meetings")), []);
  useEffect(() => { let active = true; api<ArchivedMeeting[]>("/archives/meetings").then(rows => { if (active) setItems(rows); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  async function mutate(path: string, method: string, body: object) {
    setBusy(true); setError("");
    try { await api(path, { method, body: JSON.stringify(body) }); dialog.current?.close(); setDeleting(null); await load(); await onChanged(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const needle = search.trim().toLocaleLowerCase();
  const filtered = items.filter(m => m.title.toLocaleLowerCase().includes(needle) && (!workspace || m.workspace_id === workspace) && (!mode || m.mode === mode));
  if (opened) return <><button className="ex-archives-back" onClick={() => setOpened(null)}><ArrowLeft size={16} />Back to archives</button><MeetingView key={opened.id} id={opened.id} workspace={opened.workspace_name} testMode={testMode} onChanged={async () => { setOpened(null); await load(); await onChanged(); }} /></>;
  return <section className="ex-archives" aria-labelledby="archives-title">
    <header><div><h1 id="archives-title"><Archive size={25} /> Archives</h1><p>Restore meetings and workspaces, or delete archived meeting records.</p></div></header>
    <div className="ex-tabs" aria-label="Archive category">
      <button aria-pressed={tab === "meetings"} onClick={() => setTab("meetings")}>Meetings</button>
      <button aria-pressed={tab === "workspaces"} onClick={() => setTab("workspaces")}>Workspaces</button>
    </div>
    <div className="ex-archive-filters">
      <label>Search archives<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={tab === "meetings" ? "Meeting name…" : "Workspace name…"} /></label>
      {tab === "meetings" && <><label>Workspace filter<Select value={workspace} onValueChange={value => setWorkspace(value)}><option value="">All workspaces</option>{workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></label><label>Meeting type<Select value={mode} onValueChange={value => setMode(value)}><option value="">All types</option><option value="real">Interviews</option><option value="test">Tests</option><option value="draft">Drafts</option><option value="legacy">Earlier sessions</option></Select></label></>}
    </div>
    {error && !deleting && <p role="alert" className="ex-error">{error}</p>}
    {tab === "meetings" ? <div className="ex-archive-list">{filtered.map(m => <article key={m.id}>
      <div><button className="ex-archive-title" onClick={() => setOpened(m)}>{m.title}</button><p>{m.workspace_name} · {m.mode === "real" ? "Interview" : m.mode}{!!m.workspace_archived && " · Workspace archived"}</p></div>
      <div className="ex-archive-actions"><button disabled={busy || !!m.workspace_archived} title={m.workspace_archived ? "Restore the workspace first" : undefined} onClick={() => void mutate(`/meetings/${m.id}/preferences`, "PATCH", { revision: m.context_version, archived: false })}>Restore meeting</button><button className="ex-danger" disabled={busy} onClick={() => { setDeleting(m); setError(""); dialog.current?.showModal(); }}><Trash2 size={15} />Delete permanently</button></div>
    </article>)}{!filtered.length && <p className="ex-muted">No archived meetings match.</p>}</div> : <div className="ex-archive-list">{workspaces.filter(w => w.archived && w.name.toLocaleLowerCase().includes(needle)).map(w => <article key={w.id}><div><h2>{w.name}</h2><p>Restoring keeps individually archived meetings in Archives.</p></div><button disabled={busy} onClick={() => void mutate(`/workspaces/${w.id}/archive`, "PATCH", { revision: w.revision, archived: false })}>Restore workspace</button></article>)}{!workspaces.some(w => w.archived && w.name.toLocaleLowerCase().includes(needle)) && <p className="ex-muted">No archived workspaces match.</p>}</div>}
    <dialog className="ex-dialog" ref={dialog} aria-labelledby="archive-delete-title" onCancel={e => { if (busy) e.preventDefault(); else setDeleting(null); }}>
      <form onSubmit={e => { e.preventDefault(); if (deleting) void mutate(`/workspaces/${deleting.workspace_id}/meetings/${deleting.id}`, "DELETE", { revision: deleting.context_version, confirmed: true }); }}>
        <header><h2 id="archive-delete-title">Permanently delete meeting?</h2></header>
        <p><strong>{deleting?.title}</strong> and its working notes, questions and reports will be deleted. This cannot be undone.</p><p>The protected transcript archive is retained for later evaluation.</p>
        {error && <p className="ex-error" role="alert">{error}</p>}
        <footer><button type="button" autoFocus disabled={busy} onClick={() => { dialog.current?.close(); setDeleting(null); }}>Cancel</button><button className="ex-danger" disabled={busy}>{busy ? "Deleting…" : "Delete meeting"}</button></footer>
      </form>
    </dialog>
  </section>;
}
