"""Owner-only administrative commands.

`/admin sync`      — resync the slash-command tree
`/admin reload`    — hot-reload a cog by its short name
`/admin shutdown`  — cleanly stop the bot
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from nova.utils import embeds
from nova.utils.checks import is_owner

if TYPE_CHECKING:
    from nova.bot import NovaBot

log = logging.getLogger("nova.admin")


async def _extension_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Suggest currently-loaded cog short names for `/admin reload`."""
    bot = cast("NovaBot", interaction.client)
    names = sorted(
        ext.removeprefix("nova.cogs.")
        for ext in bot.extensions
        if ext.startswith("nova.cogs.")
    )
    matches = [n for n in names if current.lower() in n.lower()]
    return [app_commands.Choice(name=n, value=n) for n in matches[:25]]


class Admin(commands.GroupCog, name="admin"):
    """Owner tooling. All commands below are gated by `is_owner()`."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="sync", description="Resync slash commands with Discord.")
    @app_commands.describe(scope="Where to sync: 'guild' (this server) or 'global'.")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="guild", value="guild"),
            app_commands.Choice(name="global", value="global"),
        ]
    )
    @is_owner()
    async def sync(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if scope.value == "guild":
            if interaction.guild is None:
                await interaction.followup.send(
                    "Run this in a server, or pick `global`.", ephemeral=True
                )
                return
            synced = await self.bot.tree.sync(guild=interaction.guild)
            where = f"guild `{interaction.guild.name}`"
        else:
            synced = await self.bot.tree.sync()
            where = "globally"
        await interaction.followup.send(
            embed=embeds.success(
                "Synced",
                f"Registered **{len(synced)}** command(s) {where}.",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="reload", description="Reload a cog by module name.")
    @app_commands.describe(extension="The cog module, e.g. 'music' or 'nova.cogs.music'.")
    @app_commands.autocomplete(extension=_extension_autocomplete)
    @is_owner()
    async def reload(self, interaction: discord.Interaction, extension: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        module = extension if extension.startswith("nova.") else f"nova.cogs.{extension}"
        try:
            await self.bot.reload_extension(module)
        except commands.ExtensionNotLoaded:
            await self.bot.load_extension(module)
        except Exception as exc:  # noqa: BLE001 — report any load error to operator
            log.exception("Reload failed")
            await interaction.followup.send(
                embed=embeds.error("Reload failed", f"`{exc.__class__.__name__}`: {exc}"),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=embeds.success("Reloaded", f"`{module}`"), ephemeral=True
        )

    @app_commands.command(name="shutdown", description="Stop the bot.")
    @is_owner()
    async def shutdown(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("👋 Shutting down.", ephemeral=True)
        log.warning("Shutdown requested by %s (%s)", interaction.user, interaction.user.id)
        await self.bot.close()


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(Admin(bot))
