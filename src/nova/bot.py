"""The NovaBot class.

Subclasses `commands.Bot`:
  * loads cogs in `setup_hook` (the modern discord.py v2 entry point for
    async startup work);
  * syncs slash commands to the configured dev guild in development, or
    globally in production;
  * honours OpenClaw policies for inbound messages;
  * exposes a shared `aiohttp.ClientSession` for cogs that need HTTP
    access (e.g. webhooks, yt-dlp).
"""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from nova.config import Settings
from nova.openclaw import dm_allowed, guild_message_requires_mention

log = logging.getLogger("nova.bot")

#: Cogs loaded at startup. Order doesn't matter; each is independent.
INITIAL_EXTENSIONS: Final[tuple[str, ...]] = (
    "nova.cogs.general",
    "nova.cogs.admin",
    "nova.cogs.events",
    "nova.cogs.pins",
    "nova.cogs.webhooks",
    "nova.cogs.music",
)


def _build_intents() -> discord.Intents:
    """Intents required by the cogs Nova ships with.

    Message Content and Guild Members are *privileged* — they must be
    enabled in the Discord Developer Portal in addition to being
    requested here.
    """
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guild_scheduled_events = True
    intents.voice_states = True
    return intents


class NovaBot(commands.Bot):
    """Nova — an OpenClaw-aware Discord bot."""

    http_session: aiohttp.ClientSession  # created in setup_hook

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=_build_intents(),
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=True,
            ),
            owner_ids=set(settings.discord_owner_ids) or None,
        )
        self.settings = settings

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def setup_hook(self) -> None:
        """Called once before the bot connects to the gateway."""
        # Shared aiohttp session for cogs that need HTTP (webhooks, etc.)
        self.http_session = aiohttp.ClientSession()

        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:
                log.exception("Failed to load extension %s", ext)

        # Sync slash commands. In development we sync to one guild for
        # instant availability; globally syncs take up to an hour.
        if self.settings.discord_dev_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_dev_guild_id)
            # Copy global commands to the guild so both sets stay in sync.
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to dev guild %s", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally", len(synced))

    async def close(self) -> None:
        """Clean shutdown — close HTTP session then let the parent disconnect."""
        session = getattr(self, "http_session", None)
        if session is not None and not session.closed:
            await session.close()
        await super().close()

    # ------------------------------------------------------------------
    # Discord events
    # ------------------------------------------------------------------
    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (id=%s) — serving %d guild(s)",
            self.user,
            self.user.id,
            len(self.guilds),
        )
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"/help · OpenClaw agent={self.settings.openclaw_agent_id}",
            ),
        )

    async def on_message(self, message: discord.Message) -> None:
        """Apply OpenClaw policy gates before dispatching to commands.

        The OpenClaw gateway enforces the same rules upstream, but when
        Nova is running standalone (e.g. in dev) we still want sensible
        defaults so random DMs and off-topic guild chatter don't wake
        the bot up.
        """
        if message.author.bot:
            return
        if self.user is None:
            return

        if message.guild is None:
            # DM policy gate
            if not dm_allowed(message.author.id, self.settings):
                log.debug("Ignoring DM from %s (policy=%s)",
                          message.author.id, self.settings.openclaw_dm_policy)
                return
        else:
            # Guild mention gate
            if guild_message_requires_mention(message, self.user.id):
                return

        await self.process_commands(message)

    async def on_command_error(
        self, ctx: commands.Context[commands.Bot], error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        log.exception("Command error in %s: %s", ctx.command, error)
        try:
            await ctx.reply(f"Something went wrong: `{error}`", mention_author=False)
        except discord.HTTPException:
            pass

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Global handler for slash-command errors.

        discord.py looks up this method on the CommandTree, but exposing
        it on the bot as well makes it easy for cogs to override per
        command. The tree-level hook is wired up in `_install_tree_error_hook`.
        """
        message = _format_app_command_error(error)
        log.warning("App command error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.exception("Failed to report app command error to user")


def _format_app_command_error(error: app_commands.AppCommandError) -> str:
    if isinstance(error, app_commands.CommandOnCooldown):
        return f"⏱️ You're on cooldown. Try again in {error.retry_after:.1f}s."
    if isinstance(error, app_commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        return f"🔒 You need the following permission(s): `{perms}`."
    if isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        return f"🤖 I'm missing the following permission(s): `{perms}`."
    if isinstance(error, app_commands.CheckFailure):
        return "🚫 You can't run this command here."
    return f"⚠️ Unexpected error: `{error.__class__.__name__}`"
