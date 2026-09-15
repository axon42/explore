"""Reversible organization and explicitly confirmed working-record deletion."""

from .discovery import Discovery, require
from .models import DomainError
from .storage import now


class Archives:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def idle(db, wid):
        if db.execute(
            "SELECT 1 FROM sessions s JOIN meetings m ON m.id=s.meeting_id "
            "WHERE m.workspace_id=? AND s.status='live' LIMIT 1",
            (wid,),
        ).fetchone():
            raise DomainError(
                "meeting_live", "End active meetings before archiving this workspace."
            )

    def clear(self, wid):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(db, "workspaces", wid)
            self.idle(db, wid)
            count = db.execute(
                "UPDATE meetings SET archived=1, context_version=context_version+1, "
                "updated_at=? WHERE workspace_id=? AND archived=0",
                (now(), wid),
            ).rowcount
            return {"status": "archived", "count": count}

    def workspace(self, wid, revision, archived):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            item = require(db, "workspaces", wid)
            if item["revision"] != revision:
                raise DomainError("conflict", "Workspace changed. Refresh and retry.")
            if archived:
                self.idle(db, wid)
            db.execute(
                "UPDATE workspaces SET archived=?, revision=revision+1 WHERE id=?",
                (int(archived), wid),
            )
            return require(db, "workspaces", wid)

    def list(self):
        with self.storage.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT m.*, w.name AS workspace_name, w.archived AS workspace_archived, "
                    "COALESCE((SELECT s.mode FROM sessions s WHERE s.meeting_id=m.id "
                    "ORDER BY s.created_at DESC,s.id DESC LIMIT 1),'draft') AS mode "
                    "FROM meetings m JOIN workspaces w ON w.id=m.workspace_id "
                    "WHERE m.archived=1 OR w.archived=1 ORDER BY m.updated_at DESC,m.id"
                )
            ]

    def delete(self, wid, mid, revision, confirmed):
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            meeting = require(db, "meetings", mid)
            workspace = require(db, "workspaces", wid)
            if meeting["workspace_id"] != wid:
                raise DomainError("not_found", "Meeting not found in this workspace.", 404)
            if not confirmed or not (meeting["archived"] or workspace["archived"]):
                raise DomainError(
                    "archive_required", "Archive the meeting and confirm deletion first."
                )
            if meeting["context_version"] != revision:
                raise DomainError(
                    "conflict", "Meeting changed. Refresh and review before deleting."
                )
            if db.execute(
                "SELECT 1 FROM sessions WHERE meeting_id=? AND status='live'", (mid,)
            ).fetchone():
                raise DomainError("meeting_live", "End the meeting before deleting it.")
            if db.execute(
                "SELECT 1 FROM report_jobs j JOIN sessions s ON s.id=j.session_id "
                "WHERE s.meeting_id=? AND j.status IN ('pending','generating')",
                (mid,),
            ).fetchone():
                raise DomainError(
                    "report_pending", "Wait for the report to finish before deleting."
                )
            # Preservation and deletion share the attached-database transaction.
            Discovery(self.storage)._delete_meeting(db, mid)
            return {"status": "deleted", "transcript_archive_retained": True}
