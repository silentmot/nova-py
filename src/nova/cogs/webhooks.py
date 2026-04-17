"""Webhook management commands.

Webhook URLs contain a token, so we treat them as *secrets* and never
display or log them. `/webhook send` accepts the URL as an ephemeral
parameter and is intended for ad-hoc posting from an agent or operator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from nova.utils import embeds
from nova.utils.checks import guild_only

if TYPE_CHECKING:
    from nova.bot import NovaBot


class Webhooks(commands.GroupCog, name="webhook"):
    """Create, list, delete webhooks; send messages through an existing one."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="create", description="Create a webhook in a channel.")
    @app_commands.describe(
        channel="Channel to create the webhook in (defaults to current).",
        name="Display name for the webhook.",
    )
    @guild_only()
    @app_commands.default_permissions(manage_webhooks=True)
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Webhooks can only be created in text channels.", ephemeral=True
            )
            return
        try:
            hook = await target.create_webhook(name=name, reason=f"Created by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need **Manage Webhooks** in that channel.", ephemeral=True
            )
            return

        # Send the URL ephemerally; anything but the requester shouldn't see it.
        await interaction.response.send_message(
            embed=embeds.success(
                f"Webhook created: {hook.name}",
                f"Channel: {target.mention}\n"
                f"ID: `{hook.id}`\n"
                "**Webhook URL** (treat as a secret — do not share):\n"
                f"||{hook.url}||",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="list", description="List webhooks in this server.")
    @guild_only()
    @app_commands.default_permissions(manage_webhooks=True)
    async def list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        try:
            hooks = await interaction.guild.webhooks()
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need **Manage Webhooks** to list them.", ephemeral=True
            )
            return
        if not hooks:
            await interaction.response.send_message("No webhooks in this server.", ephemeral=True)
            return
        lines = [
            f"• **{h.name}** — <#{h.channel_id}> · id `{h.id}`"
            for h in hooks[:25]
        ]
        await interaction.response.send_message(
            embed=embeds.info(f"Webhooks ({len(hooks)})", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(name="delete", description="Delete a webhook by ID.")
    @app_commands.describe(webhook_id="The webhook's numeric ID (see /webhook list).")
    @guild_only()
    @app_commands.default_permissions(manage_webhooks=True)
    async def delete(self, interaction: discord.Interaction, webhook_id: str) -> None:
        assert interaction.guild is not None
        try:
            target_id = int(webhook_id)
        except ValueError:
            await interaction.response.send_message("Invalid ID.", ephemeral=True)
            return
        for hook in await interaction.guild.webhooks():
            if hook.id == target_id:
                await hook.delete(reason=f"Deleted by {interaction.user}")
                await interaction.response.send_message(
                    embed=embeds.success("Deleted", f"Webhook `{hook.name}` is gone."),
                    ephemeral=True,
                )
                return
        await interaction.response.send_message("Webhook not found.", ephemeral=True)

    @app_commands.command(name="send", description="Send a message via a webhook URL.")
    @app_commands.describe(
        url="The webhook URL (kept ephemeral, never logged).",
        content="Message content.",
        username="Override the webhook's display name.",
    )
    async def send(
        self,
        interaction: discord.Interaction,
        url: str,
        content: str,
        username: str | None = None,
    ) -> None:
        # Defer ephemerally so the URL leaves Discord's client quickly
        # and we don't sit on a visible "thinking…" response.
        await interaction.response.defer(ephemeral=True, thinking=True)
        session: aiohttp.ClientSession = self.bot.http_session
        try:
            hook = discord.Webhook.from_url(url, session=session, client=self.bot)
            await hook.send(content=content, username=username or discord.utils.MISSING)
        except (ValueError, discord.NotFound, discord.Forbidden) as exc:
            await interaction.followup.send(
                embed=embeds.error("Send failed", f"`{exc.__class__.__name__}`"),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=embeds.success("Sent", "Message delivered via webhook."),
            ephemeral=True,
        )


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(Webhooks(bot))
