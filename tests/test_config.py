"""Settings parsing tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nova.config import Settings


def test_settings_parses_basic_env(settings: Settings) -> None:
    assert settings.discord_bot_token == "test-token"
    assert settings.discord_owner_ids == [111, 222]
    assert settings.openclaw_agent_id == "test-agent"
    assert settings.openclaw_dm_policy == "allowlist"
    assert settings.openclaw_allow_from == ["42", "1337"]


def test_is_owner_predicate(settings: Settings) -> None:
    assert settings.is_owner(111) is True
    assert settings.is_owner(999) is False


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_allow_from_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    monkeypatch.setenv("OPENCLAW_ALLOW_FROM", "*")
    s = Settings()  # type: ignore[call-arg]
    assert s.openclaw_allow_from == ["*"]
