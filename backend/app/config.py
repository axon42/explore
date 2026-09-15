from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    ingestion_token: SecretStr = SecretStr("")
    demo_enabled: bool = True
    analysis_strategy: Literal["legacy", "topics"] = "legacy"
    analysis_provider: Literal["mock", "gemini"] = "mock"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.1-flash-lite", pattern=r"^[a-zA-Z0-9.-]+$")
    analysis_max_calls: int = Field(default=100, ge=1, le=1000)
    analysis_timeout_seconds: int = Field(default=45, ge=5, le=60)
    backend_port: int = Field(default=8000, ge=1024, le=65535)
    frontend_port: int = Field(default=5173, ge=1024, le=65535)
    subscriber_queue_size: int = Field(default=128, ge=1)
    zoom_video_sdk_key: SecretStr = SecretStr("")
    zoom_video_sdk_secret: SecretStr = SecretStr("")
    deepgram_api_key: SecretStr = SecretStr("")
    # Zero means manual stop; a positive value is an optional local test cutoff.
    audio_capture_max_seconds: int = Field(default=0, ge=0, le=600)
    zoom_proof_enabled: bool = False
    zoom_webhook_secret_token: SecretStr = SecretStr("")

    @field_validator("audio_capture_max_seconds")
    @classmethod
    def capture_cutoff(cls, value: int) -> int:
        if 0 < value < 30:
            raise ValueError("Capture cutoff must be 0 (manual stop) or 30–600 seconds")
        return value

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value

    @property
    def transcript_archive_path(self) -> Path:
        # Sibling of disposable working data, including isolated per-test data directories.
        directory = self.data_dir.resolve()
        return directory.parent / f"{directory.name}-transcripts" / "transcripts.sqlite3"

    @property
    def origins(self) -> set[str]:
        return {
            f"http://{host}:{port}"
            for host in ("127.0.0.1", "localhost")
            for port in (self.frontend_port, self.backend_port)
        }
