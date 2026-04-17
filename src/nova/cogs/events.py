"""Guild scheduled events.

Thin wrapper over `Guild.create_scheduled_event` so agents and users
can create, list and cancel events via slash commands.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from nova.utils import embeds
from nova.utils.checks import guild_only

if TYPE_CHECKING:
    from nova.bot import NovaBot

log = logging.getLogger("nova.events")

#: Accepted input formats for the `when` argument on /event create.
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
)


class Events(commands.GroupCog, name="event"):
    """Create and manage Discord guild scheduled events."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="create", description="Create a new scheduled event.")
    @app_commands.describe(
        name="Event name",
        when="Start time (UTC). Format: YYYY-MM-DD HH:MM",
        duration_minutes="How long the event lasts.",
        location="Where it happens (text, voice channel mention, or a URL).",
        description="Optional description.",
    )
    @guild_only()
    @app_commands.default_permissions(manage_events=True)
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        when: str,
        duration_minutes: app_commands.Range[int, 15, 60 * 24 * 14],
        location: str,
        description: str | None = None,
    ) -> None:
        assert interaction.guild is not None
        start = _parse_datetime(when)
        if start is None:
            await interaction.response.send_message(
                embed=embeds.error(
                    "Invalid date",
                    "Use `YYYY-MM-DD HH:MM` (UTC), e.g. `2026-04-20 18:30`.",
                ),
                ephemeral=True,
            )
            return
        if start < datetime.now(tz=UTC) + timedelta(minutes=1):
            await interaction.response.send_message(
                "Start time must be in the future.", ephemeral=True
            )
            return

        end = start + timedelta(minutes=duration_minutes)
        await interaction.response.defer(ephemeral=True, thinking=True)

        # If `location` resolves to a voice / stage channel, prefer that.
        voice_channel = _resolve_voice(interaction.guild, location)

        try:
            if voice_channel is not None:
                event = await interaction.guild.create_scheduled_event(
                    name=name,
                    description=description or "",
                    start_time=start,
                    end_time=end,
                    channel=voice_channel,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    entity_type=(
                        discord.EntityType.voice
                        if isinstance(voice_channel, discord.VoiceChannel)
                        else discord.EntityType.stage_instance
                    ),
                    reason=f"/event create by {interaction.user}",
                )
            else:
                event = await interaction.guild.create_scheduled_event(
                    name=name,
                    description=description or "",
                    start_time=start,
                    end_time=end,
                    location=location,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    entity_type=discord.EntityType.external,
                    reason=f"/event create by {interaction.user}",
                )
        except discord.Forbidden:
            await interaction.followup.send(
                "I need the **Manage Events** permission here.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            log.warning("Event create failed: %s", exc)
            await interaction.followup.send(f"Discord rejected the event: `{exc}`", ephemeral=True)
            return

        await interaction.followup.send(
            embed=embeds.success(
                f"Event created — {event.name}",
                f"<t:{int(event.start_time.timestamp())}:F> · [jump]({event.url})",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="list", description="List upcoming scheduled events.")
    @guild_only()
    async def list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        upcoming = [
            e
            for e in interaction.guild.scheduled_events
            if e.status == discord.EventStatus.scheduled
        ]
        if not upcoming:
            await interaction.response.send_message(
                embed=embeds.info("No events", "There are no upcoming events in this server."),
                ephemeral=True,
            )
            return
        upcoming.sort(key=lambda e: e.start_time)
        lines = [
            f"• **{e.name}** — <t:{int(e.start_time.timestamp())}:R> · [jump]({e.url})"
            for e in upcoming[:15]
        ]
        await interaction.response.send_message(
            embed=embeds.info(f"Upcoming events ({len(upcoming)})", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(name="cancel", description="Cancel a scheduled event by ID.")
    @app_commands.describe(event_id="The event ID (shown by /event list).")
    @guild_only()
    @app_commands.default_permissions(manage_events=True)
    async def cancel(self, interaction: discord.Interaction, event_id: str) -> None:
        assert interaction.guild is not None
        try:
            event = await interaction.guild.fetch_scheduled_event(int(event_id))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Event not found.", ephemeral=True)
            return
        try:
            await event.cancel(reason=f"Cancelled by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need **Manage Events** to cancel this.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Cancelled", event.name), ephemeral=True
        )


def _parse_datetime(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _resolve_voice(guild: discord.Guild, hint: str) -> discord.VoiceChannel | discord.StageChannel | None:
    """Interpret `hint` as a channel mention / ID if possible."""
    hint = hint.strip()
    if hint.startswith("<#") and hint.endswith(">"):
        hint = hint[2:-1]
    if hint.isdigit():
        channel = guild.get_channel(int(hint))
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
    return None


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(Events(bot))
