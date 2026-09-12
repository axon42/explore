"""Local-only, explicit opt-in Video SDK account proof, separate from meeting data."""

import secrets
import time
from uuid import uuid4

import jwt
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .models import DomainError


class JoinProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60, pattern=r"\S")


def router(settings: Settings) -> APIRouter:
    routes = APIRouter(prefix="/integrations/zoom/proof")
    # One random room per backend lifetime; never accepts client-supplied room/privileges.
    room = "explore-proof-" + uuid4().hex
    passcode = secrets.token_hex(5)
    issued = 0

    @routes.get("")
    async def readiness(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {
            "configured": bool(settings.zoom_video_sdk_key.get_secret_value())
            and bool(settings.zoom_video_sdk_secret.get_secret_value()),
            "enabled": settings.zoom_proof_enabled,
            "scope": "local-video-proof",
            "transcript_connected": False,
        }

    @routes.post("/join")
    async def join(body: JoinProof, request: Request, response: Response):
        nonlocal issued
        # Host checks are also applied globally. Require explicit browser origin here.
        if request.headers.get("origin") not in settings.origins:
            raise DomainError("invalid_origin", "A local browser origin is required", 403)
        if not settings.zoom_proof_enabled:
            raise DomainError("zoom_disabled", "Enable ZOOM_PROOF_ENABLED for this test", 409)
        key = settings.zoom_video_sdk_key.get_secret_value()
        secret = settings.zoom_video_sdk_secret.get_secret_value()
        if not key or not secret:
            raise DomainError("zoom_unconfigured", "Add Zoom Video SDK credentials first", 409)
        if issued >= 4:
            raise DomainError("zoom_proof_limit", "Four test join tokens already issued", 429)
        now = int(time.time())
        token = jwt.encode(
            {
                "app_key": key,
                "tpc": room,
                "role_type": 1 if issued == 0 else 0,
                "version": 1,
                "iat": now,
                "exp": now + 1800,
                "user_key": str(uuid4()),
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

    return routes
