"""General utility commands — ping, info, help summary."""

from __future__ import annotations

import platform
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from nova import __version__
from nova.openclaw import session_key_for_interaction
from nova.utils import embeds

if TYPE_CHECKING:
    from nova.bot import NovaBot


class General(commands.Cog):
    """Diagnostic and informational commands."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        t0 = time.perf_counter()
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)
        rtt_ms = (time.perf_counter() - t0) * 1000
        gw_ms = self.bot.latency * 1000
        await interaction.edit_original_response(
            content=f"🏓 **Pong!** gateway: `{gw_ms:.0f} ms`, rtt: `{rtt_ms:.0f} ms`"
        )

    @app_commands.command(name="info", description="Show bot version and runtime info.")
    async def info(self, interaction: discord.Interaction) -> None:
        session = session_key_for_interaction(interaction, self.bot.settings)
        embed = embeds.info(
            title=f"Nova v{__version__}",
            description="An OpenClaw Discord channel bot.",
        )
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(
            name="OpenClaw agent",
            value=f"`{self.bot.settings.openclaw_agent_id}`",
            inline=True,
        )
        embed.add_field(name="Session key", value=f"`{session}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Overview of Nova's slash commands.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = embeds.info(
            title="Nova — Commands",
            description=(
                "Nova exposes the following slash-command groups. "
                "Type `/` to browse them in Discord's command picker."
            ),
        )
        embed.add_field(
            name="🎵 /play & /search",
            value=(
                "`/play <url>` — queue a track\n"
                "`/search <query>` — pick from top-5 results"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎛️ /music",
            value=(
                "`nowplaying` · `queue` · `history`\n"
                "`pause` · `resume` · `skip` · `voteskip` · `stop`\n"
                "`loop <off|track|queue>` · `seek <time>` · `volume <%>`\n"
                "`playnext` · `shuffle` · `clear` · `remove <n>` · `move <a> <b>`"
            ),
            inline=False,
        )
        embed.add_field(
            name="📅 /event",
            value="`create`, `list`, `cancel`",
            inline=False,
        )
        embed.add_field(
            name="📌 /pin",
            value="`add`, `remove`, `list`",
            inline=False,
        )
        embed.add_field(
            name="🪝 /webhook",
            value="`create`, `send`, `list`, `delete`",
            inline=False,
        )
        embed.add_field(
            name="🛠️ /admin (owner-only)",
            value="`sync`, `reload`, `shutdown`",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(General(bot))
