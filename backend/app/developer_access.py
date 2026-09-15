"""Local owner authentication for developer tools; replace with account RBAC before hosting."""

import hashlib
import hmac
import os
import secrets
import stat
import time
from pathlib import Path

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .models import DomainError

COOKIE = "explore_developer"


class Unlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=256)


class Recording(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class LocalAdmin:
    def __init__(self, directory: Path):
        self.path = directory / "developer-admin.key"
        self.digest = None
        self.sessions = {}
        self.attempts = []

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise RuntimeError(
                    "Developer admin key must be a private regular file (mode 600)."
                ) from None
        else:
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_urlsafe(32))
        key = self.path.read_text().strip()
        if len(key) < 32:
            raise RuntimeError("Developer admin key must contain at least 32 characters.")
        self.digest = hashlib.sha256(key.encode()).digest()
        return key

    def unlock(self, key):
        now = time.monotonic()
        self.attempts = [t for t in self.attempts if t > now - 60]
        if len(self.attempts) >= 5:
            raise DomainError(
                "admin_rate_limited", "Too many unlock attempts. Wait one minute.", 429
            )
        self.attempts.append(now)
        if not self.digest or not hmac.compare_digest(
            self.digest, hashlib.sha256(key.encode()).digest()
        ):
            raise DomainError("admin_required", "Admin key was not accepted.", 403)
        self.sessions = {k: v for k, v in self.sessions.items() if v > now}
        if len(self.sessions) >= 8:
            del self.sessions[next(iter(self.sessions))]
        token = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(token.encode()).digest()] = now + 3600
        return token

    def authorized(self, request):
        token = request.cookies.get(COOKIE, "")
        return self.sessions.get(hashlib.sha256(token.encode()).digest(), 0) > time.monotonic()

    def require(self, request):
        if not self.authorized(request):
            raise DomainError(
                "admin_required", "Unlock Developer tools with the local admin key.", 403
            )


def router(admin, diagnostics, service):
    api = APIRouter(prefix="/developer")

    @api.get("/access")
    async def access(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {
            "authorized": admin.authorized(request),
            "mode": "local_admin",
            "available": admin.digest is not None,
        }

    @api.post("/unlock")
    async def unlock(request: Request, body: Unlock, response: Response):
        # Browser mutations need an explicit origin in addition to the global allowlist.
        if not request.headers.get("origin"):
            raise DomainError("invalid_origin", "Open Developer tools from Explore.", 403)
        token = admin.unlock(body.key)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=3600)
        response.headers["Cache-Control"] = "no-store"
        return {"authorized": True}

    @api.post("/lock")
    async def lock(request: Request, response: Response):
        admin.require(request)
        if not request.headers.get("origin"):
            raise DomainError("invalid_origin", "Open Developer tools from Explore.", 403)
        token = request.cookies.get(COOKIE, "")
        admin.sessions.pop(hashlib.sha256(token.encode()).digest(), None)
        response.delete_cookie(COOKIE)
        diagnostics.recording(False)
        return {"authorized": False}

    @api.get("/status")
    async def status(request: Request):
        admin.require(request)
        return {"recording": diagnostics.recording(), "events": diagnostics.events.tail()}

    @api.put("/recording")
    async def recording(request: Request, body: Recording):
        admin.require(request)
        if not request.headers.get("origin"):
            raise DomainError("invalid_origin", "Open Developer tools from Explore.", 403)
        return diagnostics.recording(body.enabled)

    @api.get("/requests")
    async def requests(request: Request, session_id: str | None = None):
        admin.require(request)
        return await service.read(diagnostics.list, session_id)

    @api.get("/requests/{trace_id}")
    async def detail(request: Request, trace_id: str):
        admin.require(request)
        return await service.read(diagnostics.detail, trace_id)

    @api.delete("/history")
    async def clear(request: Request):
        admin.require(request)
        if not request.headers.get("origin"):
            raise DomainError("invalid_origin", "Open Developer tools from Explore.", 403)
        return await service.read(diagnostics.clear)

    return api
