"""Tests for OpenClaw session keys and policy helpers."""

from __future__ import annotations

from types import SimpleNamespace

from nova.config import Settings
from nova.openclaw import SessionKey, dm_allowed, guild_message_requires_mention


def test_session_key_formats() -> None:
    dm = SessionKey(scope="dm", agent_id="main", target_id="main")
    guild = SessionKey(scope="guild-channel", agent_id="main", target_id=42)
    slash = SessionKey(scope="slash", agent_id="alpha", target_id=7)

    assert str(dm) == "agent:main:main"
    assert str(guild) == "agent:main:discord:channel:42"
    assert str(slash) == "agent:alpha:discord:slash:7"


def test_dm_allowed_respects_policy(settings: Settings) -> None:
    # allowlist policy with 42 and 1337 whitelisted
    assert dm_allowed(42, settings) is True
    assert dm_allowed(1337, settings) is True
    assert dm_allowed(999, settings) is False


def test_dm_allowed_wildcard_open(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    monkeypatch.setenv("OPENCLAW_DM_POLICY", "open")
    monkeypatch.setenv("OPENCLAW_ALLOW_FROM", "*")
    s = Settings()  # type: ignore[call-arg]
    assert dm_allowed(1, s) is True


def test_mention_required_in_guild() -> None:
    # Message in a guild without mentioning the bot → mention required
    message = SimpleNamespace(
        guild=object(),
        mentions=[],
        reference=None,
    )
    assert guild_message_requires_mention(message, bot_user_id=1) is True

    # Mentions the bot → no mention requirement
    mentioned = SimpleNamespace(
        guild=object(),
        mentions=[SimpleNamespace(id=1)],
        reference=None,
    )
    assert guild_message_requires_mention(mentioned, bot_user_id=1) is False


def test_mention_not_required_in_dms() -> None:
    dm_message = SimpleNamespace(guild=None, mentions=[], reference=None)
    assert guild_message_requires_mention(dm_message, bot_user_id=1) is False
