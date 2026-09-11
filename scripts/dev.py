"""Launch and supervise both localhost processes; Ctrl-C cleans up both groups."""

import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings

settings = Settings()
env = {
    **os.environ,
    "BACKEND_PORT": str(settings.backend_port),
    "FRONTEND_PORT": str(settings.frontend_port),
}
children: list[subprocess.Popen] = []
stopping = False


def stop(signum, frame):
    global stopping
    stopping = True


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
try:
    children.append(
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(settings.backend_port),
                "--workers",
                "1",
                "--ws-max-size",
                "65536",
                "--no-access-log",
            ],
            cwd=ROOT / "backend",
            env=env,
            start_new_session=os.name != "nt",
        )
    )
    children.append(
        subprocess.Popen(
            [shutil.which("npm") or "npm", "run", "dev"],
            cwd=ROOT / "frontend",
            env=env,
            start_new_session=os.name != "nt",
        )
    )
    while not stopping and all(child.poll() is None for child in children):
        time.sleep(0.2)
finally:
    for child in children:
        if child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], check=False)
            else:
                os.killpg(child.pid, signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                child.kill()
            else:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
if not stopping and any(child.returncode for child in children):
    sys.exit(1)
