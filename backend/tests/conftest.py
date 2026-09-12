"""Tests never inherit real provider credentials from a developer's environment."""

import pytest


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("ANALYSIS_STRATEGY", "legacy")
    monkeypatch.setenv("GEMINI_API_KEY", "")
