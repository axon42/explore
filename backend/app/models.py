from typing import Literal, Self

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


class SpeakerSpan(BaseModel):
    """An observation over exact characters, never a rewritten transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)
    start: int = Field(ge=0, le=20000)
    end: int = Field(gt=0, le=20000)
    label: int | None = Field(default=None, ge=0, le=999)


class SpeakerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    capture_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    channel: Literal["microphone", "system"]
    method: Literal["single_person_source", "diarized"]
    spans: list[SpeakerSpan] = Field(max_length=2000)


class AttributedTranscriptEvent(TranscriptEvent):
    speaker_metadata: SpeakerMetadata

    @model_validator(mode="after")
    def exact_spans(self) -> Self:
        previous = 0
        for span in self.speaker_metadata.spans:
            if span.start != previous or span.end <= span.start or span.end > len(self.text):
                raise ValueError("Speaker spans must partition the original text")
            previous = span.end
        if previous != len(self.text):
            raise ValueError("Speaker spans must cover the original text")
        if self.speaker_metadata.channel != self.speaker_id:
            raise ValueError("Speaker channel mismatch")
        if self.speaker_metadata.method == "single_person_source" and (
            self.speaker_id != "microphone"
            or any(s.label != 0 for s in self.speaker_metadata.spans)
        ):
            raise ValueError("Single-person sources require the microphone track")
        return self


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
