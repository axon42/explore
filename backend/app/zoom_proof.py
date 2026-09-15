"""Local-only, explicit opt-in Video SDK account proof, separate from meeting data."""

import asyncio
import secrets
import time
from uuid import uuid4

import jwt
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .lifecycle import Lifecycle
from .models import DomainError


class JoinProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60, pattern=r"\S")
    session_id: str | None = Field(default=None, max_length=200)
    generation: str | None = Field(default=None, max_length=100)


class Disconnect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: str = Field(min_length=1, max_length=100)


def router(settings: Settings, capture=None) -> APIRouter:
    routes = APIRouter(prefix="/integrations/zoom/proof")
    # One random room per backend lifetime; never accepts client-supplied room/privileges.
    room = "explore-proof-" + uuid4().hex
    passcode = secrets.token_hex(5)
    issued = 0
    generation = str(uuid4())
    mutation = asyncio.Lock()

    @routes.get("")
    async def readiness(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {
            "configured": bool(settings.zoom_video_sdk_key.get_secret_value())
            and bool(settings.zoom_video_sdk_secret.get_secret_value()),
            "enabled": settings.zoom_proof_enabled,
            "scope": "local-video-proof",
            "transcript_connected": False,
            "capture": capture.view() if capture else None,
            "generation": generation,
            "remaining_tokens": 4 - issued,
        }

    @routes.post("/capture")
    async def start_capture(body: Disconnect, request: Request):
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required", 403)
        if not settings.zoom_proof_enabled or not capture:
            raise DomainError("zoom_disabled", "Zoom test is disabled", 409)
        async with mutation:
            if body.generation != generation:
                raise DomainError("zoom_stale", "This test was disconnected. Reload.")
            await capture.service.read(
                Lifecycle(capture.service.storage).test_access,
                capture.binding["sid"] if capture.binding else None,
            )
            await capture.arm()
        return capture.view()

    @routes.post("/capture/stop")
    async def stop_capture(body: Disconnect, request: Request):
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required", 403)
        async with mutation:
            if body.generation != generation:
                raise DomainError("zoom_stale", "This test was disconnected. Reload.")
            if capture:
                await capture.close()
        return {"status": "stopped"}

    async def issue(body: JoinProof, request: Request, response: Response):
        nonlocal issued
        if body.generation is not None and body.generation != generation:
            raise DomainError("zoom_stale", "This test was disconnected. Reload before joining.")
        # Host checks are also applied globally. Require explicit browser origin here.
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required", 403)
        if not settings.zoom_proof_enabled:
            raise DomainError("zoom_disabled", "Enable ZOOM_PROOF_ENABLED for this test", 409)
        if capture:
            await capture.service.read(
                Lifecycle(capture.service.storage).test_access, body.session_id
            )
            if body.session_id:
                await capture.service.read(
                    Lifecycle(capture.service.storage).claim, body.session_id, "zoom"
                )
        key = settings.zoom_video_sdk_key.get_secret_value()
        secret = settings.zoom_video_sdk_secret.get_secret_value()
        if not key or not secret:
            raise DomainError("zoom_unconfigured", "Add Zoom Video SDK credentials first", 409)
        if issued >= 4:
            raise DomainError("zoom_proof_limit", "Four test join tokens already issued", 429)
        now = int(time.time())
        claims = {}
        if body.session_id:
            if not capture:
                raise DomainError("zoom_unavailable", "Capture is unavailable")
            if issued and not capture.binding:
                raise DomainError(
                    "zoom_bound", "Restart before binding an existing video-only test"
                )
            claims["session_key"] = await capture.bind(body.session_id)
        elif capture and capture.binding:
            raise DomainError("zoom_bound", "Open the Zoom link from the bound meeting")
        # Binding awaits storage: concurrent joins must recheck the issuance limit.
        if issued >= 4:
            raise DomainError("zoom_proof_limit", "Four test join tokens already issued", 429)
        token = jwt.encode(
            {
                "app_key": key,
                "tpc": room,
                "role_type": 1 if issued == 0 else 0,
                "version": 1,
                "iat": now,
                "exp": now + 1800,
                "user_key": str(uuid4()),
                **claims,
            },
            secret,
            algorithm="HS256",
        )
        issued += 1
        response.headers["Cache-Control"] = "no-store"
        return {
            "videoSDKJWT": token,
            "sessionName": room,
            "sessionPasscode": passcode,
            "userName": body.name.strip(),
        }

    @routes.post("/join")
    async def join(body: JoinProof, request: Request, response: Response):
        async with mutation:
            return await issue(body, request, response)

    @routes.post("/disconnect")
    async def disconnect(body: Disconnect, request: Request):
        nonlocal room, passcode, issued, generation
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required", 403)
        async with mutation:
            if body.generation != generation:
                raise DomainError("zoom_stale", "This test was already disconnected. Reload.")
            if capture:
                await capture.release()
            room = "explore-proof-" + uuid4().hex
            passcode = secrets.token_hex(5)
            issued = 0
            generation = str(uuid4())
            return {"status": "disconnected", "generation": generation, "zoom_call_ended": False}

    return routes
