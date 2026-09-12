import { useState } from "react";
import { api } from "../types";
import { briefLabels, emptyBrief } from "./data";
import type { Brief, Detail, Note } from "./data";
export function BriefEditor({
  detail,
  onSaved,
}: {
  detail: Detail;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Brief>({
    ...emptyBrief,
    ...detail.brief,
    title: detail.meeting.title,
  });
  const [revision, setRevision] = useState(detail.brief_revision);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<Detail>(`/meetings/${detail.meeting.id}/brief`, {
        method: "PUT",
        body: JSON.stringify({ revision, brief: draft }),
      });
      setRevision(result.brief_revision);
      setMessage("Saved");
      onSaved();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="ex-brief"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {(Object.keys(briefLabels) as Array<keyof Brief>).map((key) => (
        <label key={key}>
          {briefLabels[key]}
          {["title", "customer", "vertical"].includes(key) ? (
            <input
              disabled={busy}
              value={draft[key]}
              maxLength={key === "title" ? 120 : 500}
              required={key === "title"}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
            />
          ) : (
            <textarea
              disabled={busy}
              rows={3}
              maxLength={key === "background" ? 3000 : 2000}
              value={draft[key]}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
            />
          )}
        </label>
      ))}
      <footer>
        <span role="status">{message}</span>
        <button className="ex-primary" disabled={busy}>
          {busy ? "Saving…" : "Save brief"}
        </button>
      </footer>
    </form>
  );
}
export function Notes({
  mid,
  notes,
  onSaved,
}: {
  mid: string;
  notes: Note[];
  onSaved: () => void;
}) {
  const [body, setBody] = useState("");
  const [editing, setEditing] = useState<Note>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(`/meetings/${mid}/notes${editing ? "/" + editing.id : ""}`, {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify({ body, revision: editing?.revision || 0 }),
      });
      setBody("");
      setEditing(undefined);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="ex-notes">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <label>
          {editing ? "Edit note" : "Meeting note"}
          <textarea
            disabled={busy}
            rows={4}
            maxLength={4000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Observations, context, or follow-ups…"
            required
          />
        </label>
        <footer>
          {editing && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setEditing(undefined);
                setBody("");
              }}
            >
              Cancel
            </button>
          )}
          <button className="ex-primary" disabled={busy || !body.trim()}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add note"}
          </button>
        </footer>
        {error && (
          <p className="ex-error" role="alert">
            {error}
          </p>
        )}
      </form>
      {notes.map((note) => (
        <article key={note.id}>
          <p>{note.body}</p>
          <footer>
            <time>{new Date(note.updated_at).toLocaleString()}</time>
            <button
              onClick={() => {
                setEditing(note);
                setBody(note.body);
              }}
            >
              Edit
            </button>
          </footer>
        </article>
      ))}
    </section>
  );
}
