"""Shared pytest fixtures.

We isolate each test from stray `.env` files by forcing pydantic-settings
to read from explicit env vars set in `monkeypatch`.
"""

from __future__ import annotations

import pytest

from nova.config import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    reset_settings_cache()


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a minimal, valid environment before constructing Settings."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_OWNER_IDS", "111,222")
    monkeypatch.setenv("OPENCLAW_AGENT_ID", "test-agent")
    monkeypatch.setenv("OPENCLAW_DM_POLICY", "allowlist")
    monkeypatch.setenv("OPENCLAW_ALLOW_FROM", "42,1337")


@pytest.fixture
def settings(settings_env: None) -> Settings:  # noqa: ARG001 — fixture wiring
    return Settings()  # type: ignore[call-arg]
