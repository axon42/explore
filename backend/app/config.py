from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    ingestion_token: SecretStr = SecretStr("")
    demo_enabled: bool = True
    backend_port: int = Field(default=8000, ge=1024, le=65535)
    frontend_port: int = Field(default=5173, ge=1024, le=65535)
    subscriber_queue_size: int = Field(default=128, ge=1)

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value

    @property
    def origins(self) -> set[str]:
        return {
            f"http://{host}:{port}"
            for host in ("127.0.0.1", "localhost")
            for port in (self.frontend_port, self.backend_port)
        }
