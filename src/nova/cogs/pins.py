"""Message pinning commands.

Adds a `/pin` group and a "Pin this message" context-menu command for
quick access. Requires the bot to have `manage_messages` in the target
channel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from nova.utils import embeds
from nova.utils.checks import guild_only

if TYPE_CHECKING:
    from nova.bot import NovaBot


class Pins(commands.GroupCog, name="pin"):
    """Pin, unpin and list pinned messages."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        super().__init__()

        # Context-menu command: right-click -> Apps -> "Pin this message"
        self._ctx_pin = app_commands.ContextMenu(
            name="Pin this message",
            callback=self._ctx_pin_callback,
        )
        self.bot.tree.add_command(self._ctx_pin)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self._ctx_pin.name, type=self._ctx_pin.type)

    # ---- Group commands ---------------------------------------------
    @app_commands.command(name="add", description="Pin a message by its ID.")
    @app_commands.describe(message_id="Copy the message ID (enable Developer Mode).")
    @guild_only()
    @app_commands.default_permissions(manage_messages=True)
    async def add(self, interaction: discord.Interaction, message_id: str) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "This isn't a channel I can pin messages in.", ephemeral=True
            )
            return
        try:
            mid = int(message_id)
            message = await channel.fetch_message(mid)
            await message.pin(reason=f"Pinned by {interaction.user}")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(
                embed=embeds.error("Not found", "No message with that ID in this channel."),
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=embeds.error("Forbidden", "I don't have permission to pin here."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Pinned", message.jump_url), ephemeral=True
        )

    @app_commands.command(name="remove", description="Unpin a message by its ID.")
    @guild_only()
    @app_commands.default_permissions(manage_messages=True)
    async def remove(self, interaction: discord.Interaction, message_id: str) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Not a pinnable channel.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.unpin(reason=f"Unpinned by {interaction.user}")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Message not found.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to unpin here.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Unpinned", message.jump_url), ephemeral=True
        )

    @app_commands.command(name="list", description="List currently pinned messages in this channel.")
    @guild_only()
    async def list(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Not a channel.", ephemeral=True)
            return
        try:
            pins = await channel.pins()
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't read pins in this channel.", ephemeral=True
            )
            return
        if not pins:
            await interaction.response.send_message(
                embed=embeds.info("No pins", "This channel has no pinned messages."),
                ephemeral=True,
            )
            return
        description = "\n".join(
            f"• [{_truncate(msg.content or '(embed/attachment)', 60)}]({msg.jump_url})"
            f" — {msg.author.display_name}"
            for msg in pins[:20]
        )
        await interaction.response.send_message(
            embed=embeds.info(f"Pins ({len(pins)})", description), ephemeral=True
        )

    # ---- Context-menu callback --------------------------------------
    async def _ctx_pin_callback(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        try:
            await message.pin(reason=f"Pinned by {interaction.user} via context menu")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to pin in this channel.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"Couldn't pin: `{exc}`", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Pinned", message.jump_url), ephemeral=True
        )


def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(Pins(bot))
