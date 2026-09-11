from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=200)
    segment_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=0, le=9007199254740991)
    speaker_id: str = Field(min_length=1, max_length=200)
    speaker_name: str | None = Field(default=None, max_length=200)
    start_ms: int = Field(ge=0, le=9007199254740991)
    end_ms: int = Field(ge=0, le=9007199254740991)
    text: str = Field(min_length=1, max_length=20000)
    is_final: bool

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return self


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=120)


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
