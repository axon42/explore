"""Metadata-only health checks: distinguish missing input from ordinary silence."""

from .source import AudioError


def check_health(diagnostics, elapsed, streaming_seconds):
    if streaming_seconds < 10:
        return
    mic = diagnostics["microphone"]
    if elapsed - (mic["last_frame_seconds"] or 0) > 10:
        raise AudioError("audio_transport_stalled")
    if mic["input_observable"] and elapsed - (mic["last_input_seconds"] or 0) > 10:
        raise AudioError("audio_input_stalled")
