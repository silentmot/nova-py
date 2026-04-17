"""OpenClaw channel helpers.

These utilities implement the conventions documented at
https://docs.openclaw.ai/channels/discord. They don't run a gateway
themselves (OpenClaw's gateway owns the Discord websocket); instead
they expose the same session-keying, policy and identifier helpers so
the bot's slash commands can cooperate with an OpenClaw agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import discord

from nova.config import Settings

SessionScope = Literal["dm", "guild-channel", "slash"]


@dataclass(frozen=True, slots=True)
class SessionKey:
    """A stable identifier for an OpenClaw conversation.

    Format matches the OpenClaw docs:

        DM:            agent:<agentId>:main              (shared main session)
        Guild channel: agent:<agentId>:discord:channel:<channelId>
        Slash command: agent:<agentId>:discord:slash:<userId>
    """

    scope: SessionScope
    agent_id: str
    target_id: int | str

    def __str__(self) -> str:
        if self.scope == "dm":
            # OpenClaw docs explicitly call out the DM key as
            # "agent:main:main" — a shared session rather than per-user.
            return f"agent:{self.agent_id}:main"
        if self.scope == "guild-channel":
            return f"agent:{self.agent_id}:discord:channel:{self.target_id}"
        if self.scope == "slash":
            return f"agent:{self.agent_id}:discord:slash:{self.target_id}"
        raise ValueError(f"Unknown session scope: {self.scope!r}")


def session_key_for_interaction(
    interaction: discord.Interaction, settings: Settings
) -> SessionKey:
    """Build the session key OpenClaw would use for this interaction."""
    agent = settings.openclaw_agent_id
    if interaction.guild is None:
        # DMs share a single main session per OpenClaw docs.
        return SessionKey(scope="dm", agent_id=agent, target_id="main")
    # Slash commands always get a per-user isolated session.
    return SessionKey(scope="slash", agent_id=agent, target_id=interaction.user.id)


def session_key_for_message(message: discord.Message, settings: Settings) -> SessionKey:
    """Build the session key OpenClaw would use for this incoming message."""
    agent = settings.openclaw_agent_id
    if message.guild is None:
        return SessionKey(scope="dm", agent_id=agent, target_id="main")
    return SessionKey(
        scope="guild-channel",
        agent_id=agent,
        target_id=message.channel.id,
    )


# ---------------------------------------------------------------------
# Access policy helpers
# ---------------------------------------------------------------------
def dm_allowed(user_id: int, settings: Settings) -> bool:
    """Apply the configured DM policy for an inbound DM."""
    policy = settings.openclaw_dm_policy
    if policy == "disabled":
        return False
    if policy == "open":
        # Operators must explicitly set allowFrom=["*"] in OpenClaw; we
        # mirror that here by looking for the wildcard sentinel.
        return "*" in settings.openclaw_allow_from
    if policy == "allowlist":
        return str(user_id) in settings.openclaw_allow_from
    # "pairing": DMs from unknown users are allowed but downstream code
    # is expected to send a pairing prompt on first contact.
    return True


def guild_message_requires_mention(message: discord.Message, bot_user_id: int) -> bool:
    """Return True if the message lacks a required bot mention in a guild.

    Mirrors the default OpenClaw `mentionRequired: true` policy: guild
    messages that don't @mention the bot shouldn't trigger agent runs.
    Direct replies to the bot are treated as implicit mentions.
    """
    if message.guild is None:
        return False  # DMs never require a mention
    if any(user.id == bot_user_id for user in message.mentions):
        return False
    ref = message.reference
    if ref is not None and ref.resolved is not None:
        resolved = ref.resolved
        author = getattr(resolved, "author", None)
        if author is not None and author.id == bot_user_id:
            return False
    return True


__all__ = [
    "SessionKey",
    "SessionScope",
    "dm_allowed",
    "guild_message_requires_mention",
    "session_key_for_interaction",
    "session_key_for_message",
]
