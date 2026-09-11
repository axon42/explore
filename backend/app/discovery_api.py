"""Workspace/meeting API; the ingestion transport remains independent."""

import asyncio
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .discovery import Discovery
from .models import DomainError
from .reports import Reports, report_markdown, transcript_markdown


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Name(StrictBody):
    name: str = Field(min_length=1, max_length=120)


class NewMeeting(StrictBody):
    title: str = Field(default="Untitled interview", min_length=1, max_length=120)


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
    status: Literal["queued", "asked", "answered"]


class Participant(StrictBody):
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


def router(service, pipeline, stop_session):
    api = APIRouter()
    repo = Discovery(service.storage)
    reports = Reports(service.storage)
    mutation = asyncio.Lock()

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

    async def changed(mid):
        detail = await service.read(repo.detail, mid)
        if detail["session"]["status"] == "live":
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
        sid = detail["session"]["id"]
        await stop_session(sid, False)
        pipeline.states.pop(sid, None)
        pipeline.wakes.pop(sid, None)

    @api.post("/meetings/{mid}/reset")
    async def reset(mid: str, body: ResetRun):
        async with mutation:
            detail = await service.read(repo.detail, mid)
            if detail["session"]["id"] != body.session_id:
                raise DomainError("conflict", "This test was already reset. Refresh the meeting.")
            await stop_meeting(mid)
            return await service.read(repo.reset, mid)

    @api.delete("/workspaces/{wid}/meetings")
    async def clear(wid: str):
        async with mutation:
            for item in await service.read(repo.meetings, wid):
                await stop_meeting(item["id"])
            return await service.read(repo.clear_workspace, wid)

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
            if detail["session"]["id"] != body.session_id:
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
