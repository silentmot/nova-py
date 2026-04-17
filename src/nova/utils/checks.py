"""Custom app_commands checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

import discord
from discord import app_commands

if TYPE_CHECKING:
    from nova.bot import NovaBot

_F = TypeVar("_F", bound=Callable[..., Any])


def is_owner() -> Callable[[_F], _F]:
    """Allow only bot owners (as configured in `DISCORD_OWNER_IDS`)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        bot = cast("NovaBot", interaction.client)
        if bot.settings.is_owner(interaction.user.id):
            return True
        # Fall back to Discord's application owner(s) if ids aren't set.
        app = await bot.application_info()
        if app.team:
            return interaction.user.id in {m.id for m in app.team.members}
        return bool(interaction.user.id == app.owner.id)

    return app_commands.check(predicate)


def guild_only() -> Callable[[_F], _F]:
    """Reject DMs with a friendly message."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.CheckFailure("This command can only be used in a server.")
        return True

    return app_commands.check(predicate)
