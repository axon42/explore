"""Workspace/meeting API; the ingestion transport remains independent."""

import asyncio
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .archives import Archives
from .discovery import Discovery
from .lifecycle import Lifecycle
from .models import DomainError
from .reports import Reports, report_markdown, transcript_markdown
from .speakers import Speakers


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Name(StrictBody):
    name: str = Field(min_length=1, max_length=120)


class NewMeeting(StrictBody):
    title: str = Field(default="Untitled interview", min_length=1, max_length=120)


class StartMeeting(StrictBody):
    revision: int = Field(ge=0)
    mode: Literal["real", "test"] = "real"


class TestMode(StrictBody):
    enabled: bool = Field(strict=True)


class Brief(StrictBody):
    title: str = Field(min_length=1, max_length=120)
    customer: str = Field(default="", max_length=1000)
    vertical: str = Field(default="", max_length=500)
    objective: str = Field(default="", max_length=2000)
    background: str = Field(default="", max_length=3000)
    hypotheses: str = Field(default="", max_length=2000)
    guidance: str = Field(default="", max_length=2000)


class BriefUpdate(StrictBody):
    revision: int = Field(ge=0)
    brief: Brief


class Note(StrictBody):
    body: str = Field(min_length=1, max_length=4000)
    revision: int = Field(default=0, ge=0)


class ResetRun(StrictBody):
    session_id: str = Field(min_length=1, max_length=200)


class QuestionUpdate(StrictBody):
    revision: int = Field(ge=0)
    status: Literal["queued", "asked", "answered", "discarded"]


class Preferences(StrictBody):
    revision: int = Field(ge=0)
    question_interval: Literal[0, 30, 60, 120] | None = None
    archived: bool | None = None


class ArchiveWorkspace(StrictBody):
    revision: int = Field(ge=0, strict=True)
    archived: bool = Field(strict=True)


class DeleteMeeting(StrictBody):
    revision: int = Field(ge=0, strict=True)
    confirmed: bool = Field(strict=True)


class AnalysisPreferencesUpdate(StrictBody):
    strategy: Literal["legacy", "topics"]
    revision: int = Field(ge=0, strict=True)


class Participant(StrictBody):
    participant_id: str | None = Field(default=None, min_length=1, max_length=200)
    speaker_id: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)
    interview_role: Literal["interviewer", "customer", "observer", "unknown"] = "unknown"
    job_role: str = Field(default="", max_length=200)


class ParticipantsUpdate(StrictBody):
    revision: int = Field(ge=0)
    participants: list[Participant] = Field(max_length=30)

    @model_validator(mode="after")
    def unique_speakers(self):
        if len({p.speaker_id for p in self.participants}) != len(self.participants):
            raise ValueError("Duplicate speaker IDs")
        return self


class SpeakerAssignment(StrictBody):
    version: int = Field(ge=0, strict=True)
    roster_revision: int = Field(ge=0, strict=True)
    participant_id: str | None = Field(default=None, min_length=1, max_length=200)
    track_id: str | None = Field(default=None, min_length=1, max_length=200)
    segment_id: str | None = Field(default=None, min_length=1, max_length=200)
    segment_revision: int | None = Field(default=None, ge=0, strict=True)
    span_index: int | None = Field(default=None, ge=0, strict=True)


def router(service, pipeline, stop_session):
    api = APIRouter()
    repo = Discovery(service.storage)
    reports = Reports(service.storage)
    speakers = Speakers(service.storage)
    mutation = asyncio.Lock()
    lifecycle = Lifecycle(service.storage)

    @api.get("/meetings/{mid}/sessions/{sid}/speakers")
    async def speaker_view(mid: str, sid: str):
        return await service.read(speakers.view, mid, sid)

    @api.put("/meetings/{mid}/sessions/{sid}/speakers")
    async def speaker_assign(mid: str, sid: str, body: SpeakerAssignment):
        async with mutation:
            result = await service.read(lambda: speakers.assign(mid, sid, **body.model_dump()))
            await service.refresh(sid)
            await changed(mid)
            return result

    @api.get("/settings/test-mode")
    async def test_mode():
        return await service.read(lifecycle.test_mode)

    @api.put("/settings/test-mode")
    async def set_test_mode(body: TestMode):
        return await service.read(lifecycle.test_mode, body.enabled)

    @api.post("/meetings/{mid}/start")
    async def start_meeting(mid: str, body: StartMeeting):
        async with mutation:
            await service.read(lifecycle.start, mid, body.revision, body.mode)
            return await service.read(repo.detail, mid)

    @api.get("/settings/analysis")
    async def analysis_preferences():
        return await service.read(pipeline.preferences.get)

    @api.patch("/settings/analysis")
    async def update_analysis_preferences(body: AnalysisPreferencesUpdate):
        return await service.read(pipeline.preferences.update, body.strategy, body.revision)

    @api.get("/workspaces")
    async def workspaces():
        return await service.read(repo.workspaces)

    @api.post("/workspaces", status_code=201)
    async def create_workspace(body: Name):
        return await service.read(repo.create_workspace, body.name)

    @api.get("/workspaces/{wid}/meetings")
    async def meetings(wid: str):
        return await service.read(repo.meetings, wid)

    @api.post("/workspaces/{wid}/meetings", status_code=201)
    async def create_meeting(wid: str, body: NewMeeting):
        async with mutation:
            session = await service.read(repo.create, wid, body.title)
            return await service.read(repo.detail, session["meeting_id"])

    @api.get("/meetings/{mid}")
    async def meeting(mid: str):
        return await service.read(repo.detail, mid)

    @api.patch("/meetings/{mid}/preferences")
    async def preferences(mid: str, body: Preferences):
        async with mutation:
            return await service.read(
                repo.preferences, mid, body.revision, body.question_interval, body.archived
            )

    async def changed(mid):
        detail = await service.read(repo.detail, mid)
        if detail["session"] and detail["session"]["status"] == "live":
            pipeline.notify(detail["session"]["id"])
        return detail

    @api.put("/meetings/{mid}/brief")
    async def brief(mid: str, body: BriefUpdate):
        async with mutation:
            await service.read(repo.save_brief, mid, body.revision, body.brief.model_dump())
            return await changed(mid)

    @api.post("/meetings/{mid}/notes", status_code=201)
    async def add_note(mid: str, body: Note):
        async with mutation:
            note = await service.read(repo.note, mid, body.body)
            await changed(mid)
            return note

    @api.put("/meetings/{mid}/notes/{nid}")
    async def edit_note(mid: str, nid: str, body: Note):
        async with mutation:
            note = await service.read(repo.note, mid, body.body, nid, body.revision)
            await changed(mid)
            return note

    @api.patch("/meetings/{mid}/questions/{qid}")
    async def question(mid: str, qid: str, body: QuestionUpdate):
        async with mutation:
            result = await service.read(repo.question_status, mid, qid, body.revision, body.status)
            await changed(mid)
            return result

    async def stop_meeting(mid):
        detail = await service.read(repo.detail, mid)
        if not detail["session"]:
            return
        sid = detail["session"]["id"]
        await stop_session(sid, False)
        pipeline.states.pop(sid, None)
        pipeline.wakes.pop(sid, None)

    @api.post("/meetings/{mid}/reset")
    async def reset(mid: str, body: ResetRun):
        async with mutation:
            detail = await service.read(repo.detail, mid)
            if not detail["session"] or detail["session"]["id"] != body.session_id:
                raise DomainError("conflict", "This test was already reset. Refresh the meeting.")
            await service.read(lifecycle.test_access, body.session_id)
            await stop_meeting(mid)
            return await service.read(repo.reset, mid)

    archives = Archives(service.storage)

    @api.get("/archives/meetings")
    async def archived_meetings():
        return await service.read(archives.list)

    @api.patch("/workspaces/{wid}/archive")
    async def archive_workspace(wid: str, body: ArchiveWorkspace):
        async with mutation:
            return await service.read(archives.workspace, wid, body.revision, body.archived)

    @api.post("/workspaces/{wid}/meetings/archive")
    @api.delete("/workspaces/{wid}/meetings", deprecated=True)
    async def clear(wid: str):
        async with mutation:
            return await service.read(archives.clear, wid)

    @api.delete("/workspaces/{wid}/meetings/{mid}")
    async def delete_meeting(wid: str, mid: str, body: DeleteMeeting):
        async with mutation:
            return await service.read(archives.delete, wid, mid, body.revision, body.confirmed)

    @api.get("/meetings/{mid}/analysis")
    async def analysis(mid: str):
        return await service.read(reports.live, mid)

    @api.get("/meetings/{mid}/participants")
    async def participants(mid: str):
        return await service.read(reports.participants, mid)

    @api.put("/meetings/{mid}/participants")
    async def update_participants(mid: str, body: ParticipantsUpdate):
        async with mutation:
            result = await service.read(
                reports.participants,
                mid,
                body.revision,
                [p.model_dump() for p in body.participants],
            )
            await changed(mid)
            return result

    @api.get("/meetings/{mid}/transcript/export")
    async def export_transcript(mid: str, format: Literal["json", "markdown"] = "json"):
        source = await service.read(reports.export, mid)
        if format == "json":
            return source
        return Response(
            transcript_markdown(source),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="transcript.md"'},
        )

    @api.post("/meetings/{mid}/finalize", status_code=202)
    async def finalize(mid: str, body: ResetRun):
        async with mutation:
            detail = await service.read(repo.detail, mid)
            if not detail["session"] or detail["session"]["id"] != body.session_id:
                raise DomainError("conflict", "Session changed. Refresh before finalizing.")
            await stop_session(body.session_id)
            return await service.read(reports.list, mid)

    @api.get("/meetings/{mid}/reports")
    async def report_list(mid: str):
        return await service.read(reports.list, mid)

    @api.get("/meetings/{mid}/reports/{rid}")
    async def report(mid: str, rid: str, format: Literal["json", "markdown"] = "json"):
        saved = await service.read(reports.get, mid, rid)
        if format == "json":
            return saved
        return Response(
            report_markdown(saved),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="report.md"'},
        )

    return api
