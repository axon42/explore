import { Select } from "./Select";
import { Archive, Code2, FlaskConical, Folder, LockKeyhole, MessageSquare, MoreHorizontal, Plus, Search } from "lucide-react";
import type { Meeting, Workspace } from "./data";
import { Logo } from "./Logo";
import { AnalysisSettings } from "./AnalysisSettings";
import { SidebarPopover } from "./SidebarPopover";

type Props = {
  workspaces: Workspace[]; wid: string; meetings: Meeting[]; mid: string;
  page: "meetings" | "archives" | "developer"; search: string; testMode: boolean; modeBusy: boolean;
  onWorkspace: (id: string) => void; onMeeting: (id: string) => void;
  onPage: (page: Props["page"]) => void; onSearch: (text: string) => void;
  onOpen: (kind: "workspace" | "meeting" | "clear" | "archive-workspace") => void;
  onTestMode: () => void;
};

function WorkspaceControl({ workspaces, wid, meetings, onWorkspace, onOpen }: Props) {
  const workspace = workspaces.find(w => w.id === wid);
  const initials = workspace?.name.trim().split(/\s+/).slice(0, 2).map(word => Array.from(word)[0]).join("").toUpperCase() || "–";
  return <div className="ex-workspace-card">
    <span className="ex-workspace-initial" aria-hidden="true">{initials}</span>
    <label className="ex-workspace-picker"><span>Workspace</span>
      <Select aria-label="Workspace" value={wid} title={workspace?.name || "No active workspace"} onValueChange={value => onWorkspace(value)}>
        {!wid && <option value="">No active workspace</option>}
        {workspaces.filter(w => !w.archived).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
      </Select>
    </label>
    <SidebarPopover label="Workspace actions" className="ex-workspace-actions" trigger={<MoreHorizontal size={17} aria-hidden="true" />}>
      {close => <><h2>Workspace actions</h2>
        <button onClick={() => { close(); onOpen("workspace"); }}><Plus size={16} />New workspace</button><hr />
        <button disabled={!wid || !meetings.length} onClick={() => { close(); onOpen("clear"); }}><Archive size={16} />Archive all meetings</button>
        <button disabled={!wid} onClick={() => { close(); onOpen("archive-workspace"); }}><Folder size={16} />Archive workspace</button>
        <p>Archived items remain available in Archives. Permanent deletion lives there.</p>
      </>}
    </SidebarPopover>
  </div>;
}

function MeetingNavigation({ meetings, mid, page, search, onSearch, onMeeting, onPage }: Props) {
  const visible = meetings.filter(m => !m.archived);
  const filtered = visible.filter(m => m.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <>
    <nav className="ex-library-nav" aria-label="Workspace navigation">
      <button aria-current={page === "meetings" ? "page" : undefined} onClick={() => onPage("meetings")}><Folder size={18} />Meetings<span className="ex-nav-count">{visible.length}</span></button>
      <button aria-current={page === "archives" ? "page" : undefined} onClick={() => onPage("archives")}><Archive size={18} />Archives</button>
    </nav>
    <label className="ex-sidebar-search"><Search size={16} aria-hidden="true" /><input aria-label="Search meetings" type="search" placeholder="Search meetings…" value={search} onChange={e => onSearch(e.target.value)} /></label>
    <h2 className="ex-sidebar-heading">Recent meetings</h2>
    <nav className="ex-meeting-nav" aria-label="Meetings">
      {filtered.map(m => {
        const date = m.created_at ? new Date(m.created_at) : null;
        const validDate = date && !Number.isNaN(date.valueOf());
        return <button key={m.id} title={m.title} aria-label={m.title} aria-current={page === "meetings" && mid === m.id ? "page" : undefined} onClick={() => onMeeting(m.id)}>
          <MessageSquare size={16} aria-hidden="true" /><span><strong>{m.title}</strong>{validDate && <time dateTime={m.created_at} title={`Created ${date.toLocaleString()}`}>{date.toLocaleDateString(undefined, {month: "short", day: "numeric"})}</time>}</span>
        </button>;
      })}
      {!filtered.length && <p className="ex-search-empty">{search ? "No matching meetings." : "Your meetings will appear here."}</p>}
    </nav>
  </>;
}

export function Sidebar(props: Props) {
  return <aside className="ex-sidebar" aria-label="Explore sidebar">
    <a className="ex-brand" href="/"><Logo />Explore</a>
    <WorkspaceControl {...props} />
    <button className="ex-sidebar-new" disabled={!props.wid} onClick={() => props.onOpen("meeting")}><Plus size={17} />New meeting</button>
    <MeetingNavigation {...props} />
    <section className="ex-sidebar-bottom" aria-label="App tools"><h2 className="ex-sidebar-heading">Tools</h2>
      <AnalysisSettings />
      <button className="ex-test-switch" role="switch" aria-label="Test mode" aria-checked={props.testMode} disabled={props.modeBusy} onClick={props.onTestMode}><FlaskConical size={17} />Test mode<span className="ex-switch-track" aria-hidden="true" /></button>
      <button aria-label="Developer" aria-current={props.page === "developer" ? "page" : undefined} onClick={() => props.onPage("developer")}><Code2 size={17} />Developer<span className="ex-admin-label" title="Admin access required"><LockKeyhole size={12} />Admin</span></button>
    </section>
  </aside>;
}
