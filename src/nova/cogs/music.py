"""Voice / music cog — Tier 1 feature set.

Top-level:
    /play <url-or-query>         queue a track, start playback
    /search <query>              pick from top-5 YouTube results

Group /music <subcommand>:
    pause | resume | skip        playback controls
    stop                         clear queue, leave voice
    queue                        show upcoming
    nowplaying                   current track + progress bar
    loop <off|track|queue>       loop modes
    seek <time>                  jump inside the current track
    volume <percent>             playback volume (applies next track)
    shuffle | clear              queue-wide actions
    remove <n> | move <a> <b>    single-entry ops
    playnext <query>             bump to front of queue
    voteskip                     majority-vote skip
    history                      last 25 played
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from nova.utils import embeds
from nova.utils.checks import guild_only
from nova.utils.music_queue import GuildPlayer, LoopMode, MusicManager, Track

if TYPE_CHECKING:
    from nova.bot import NovaBot

log = logging.getLogger("nova.music")

_YTDL_OPTS: dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
    "source_address": "0.0.0.0",
}

_YTDL_SEARCH_OPTS: dict[str, Any] = {
    **_YTDL_OPTS,
    # extract_flat=True avoids a full resolve for each candidate; we
    # re-resolve only the one the user picks.
    "extract_flat": True,
}

_FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

_IDLE_DISCONNECT_SECONDS = 180  # leave voice if queue stays empty this long
_EMPTY_CHANNEL_SECONDS = 30     # leave voice if non-bot humans leave


def _ffmpeg_options(volume: float) -> str:
    """Ffmpeg output options — volume is applied inside ffmpeg to keep
    Python off the audio hot path (the real fix for drift)."""
    return f"-vn -filter:a volume={max(volume, 0.0):.3f}"


# =====================================================================
# Search UI
# =====================================================================
class _SearchSelect(discord.ui.Select["_SearchView"]):
    def __init__(self, tracks: list[Track], cog: Music, requester_id: int) -> None:
        options = [
            discord.SelectOption(
                label=_truncate(t.title, 100) or f"Result {i + 1}",
                value=str(i),
                description=_truncate(
                    f"{_fmt_duration(t.duration)} · {t.webpage_url}", 100
                ),
            )
            for i, t in enumerate(tracks)
        ]
        super().__init__(placeholder="Pick a result…", min_values=1, max_values=1, options=options)
        self.tracks = tracks
        self.cog = cog
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran /search can pick.", ephemeral=True
            )
            return
        track = self.tracks[int(self.values[0])]
        await interaction.response.defer(thinking=True)
        # Re-resolve with the full extractor to get a proper stream URL.
        resolved = await self.cog._resolve(track.webpage_url, requester_id=self.requester_id)
        if resolved is None:
            await interaction.followup.send(
                embed=embeds.error("Resolve failed", f"Couldn't fetch `{track.title}`.")
            )
            return
        await self.cog._enqueue_and_play(interaction, resolved)
        # Disable the select after use.
        if self.view is not None:
            for child in self.view.children:
                child.disabled = True  # type: ignore[attr-defined]
            await interaction.edit_original_response(view=self.view)


class _SearchView(discord.ui.View):
    def __init__(self, tracks: list[Track], cog: Music, requester_id: int) -> None:
        super().__init__(timeout=60)
        self.add_item(_SearchSelect(tracks, cog, requester_id))


# =====================================================================
# Music cog
# =====================================================================
class Music(commands.Cog):
    """Slash commands for voice playback."""

    music_group = app_commands.Group(
        name="music",
        description="Voice playback controls.",
    )

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        self.manager = MusicManager(bot)

    # ------------------------------------------------------------------
    # Top-level /play
    # ------------------------------------------------------------------
    @app_commands.command(
        name="play",
        description="Play a track — paste a YouTube URL, any audio URL, or a search query.",
    )
    @app_commands.describe(url="YouTube URL, audio URL, or search terms.")
    @guild_only()
    async def play(self, interaction: discord.Interaction, url: str) -> None:
        await self._do_play(interaction, url, front=False)

    # ------------------------------------------------------------------
    # Top-level /search
    # ------------------------------------------------------------------
    @app_commands.command(
        name="search",
        description="Search YouTube and pick a result to play.",
    )
    @app_commands.describe(query="What to search for.")
    @guild_only()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        results = await self._search(query, limit=5, requester_id=interaction.user.id)
        if not results:
            await interaction.followup.send(
                embed=embeds.error("No results", f"Nothing found for `{query}`.")
            )
            return
        lines = [
            f"`{i + 1}.` [{t.title}]({t.webpage_url}) — {_fmt_duration(t.duration)}"
            for i, t in enumerate(results)
        ]
        embed = embeds.info(f"Results for “{query}”", "\n".join(lines))
        view = _SearchView(results, self, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)

    # ------------------------------------------------------------------
    # /music <subcommand>
    # ------------------------------------------------------------------
    @music_group.command(name="pause", description="Pause playback.")
    @guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        if vc and vc.is_playing():
            vc.pause()
            self.manager.player_for(interaction.guild).mark_paused()
            await interaction.response.send_message("⏸️ Paused.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @music_group.command(name="resume", description="Resume playback.")
    @guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        if vc and vc.is_paused():
            vc.resume()
            self.manager.player_for(interaction.guild).mark_resumed()
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing to resume.", ephemeral=True)

    @music_group.command(name="skip", description="Skip the current track.")
    @guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        if vc and (vc.is_playing() or vc.is_paused()):
            player = self.manager.player_for(interaction.guild)
            player.request_skip()
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @music_group.command(
        name="stop",
        description="Stop playback, clear the queue, and leave voice.",
    )
    @guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        player = self.manager.player_for(interaction.guild)
        player.clear()
        if vc is not None:
            await vc.disconnect(force=False)
        self.manager.drop(interaction.guild.id)
        await interaction.response.send_message("⏹️ Stopped and disconnected.", ephemeral=True)

    @music_group.command(name="queue", description="Show the current queue.")
    @guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        if player.current is None and not player.queue:
            await interaction.response.send_message(
                embed=embeds.info("Queue is empty", "Try `/play <url-or-query>`."),
                ephemeral=True,
            )
            return
        lines: list[str] = []
        if player.current is not None:
            lines.append(
                f"**Now:** [{player.current.title}]({player.current.webpage_url}) "
                f"— {_fmt_duration(player.current.duration)}"
            )
        for i, track in enumerate(list(player.queue)[:15], start=1):
            lines.append(
                f"`{i}.` [{track.title}]({track.webpage_url}) "
                f"— {_fmt_duration(track.duration)}"
            )
        extra = len(player.queue) - 15
        if extra > 0:
            lines.append(f"…and **{extra}** more")
        footer = f"loop: `{player.loop_mode}` · volume: `{int(player.volume * 100)}%`"
        await interaction.response.send_message(
            embed=embeds.info("Queue", "\n".join(lines) + f"\n\n{footer}"),
            ephemeral=True,
        )

    @music_group.command(
        name="nowplaying",
        description="Show the current track with a progress bar.",
    )
    @guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        if player.current is None:
            await interaction.response.send_message(
                embed=embeds.info("Nothing playing", "Queue is idle."),
                ephemeral=True,
            )
            return
        track = player.current
        pos = player.position()
        dur = track.duration or 0
        bar = _progress_bar(pos, dur)
        vc = self._voice(interaction)
        state = "⏸️ paused" if (vc and vc.is_paused()) else "▶️ playing"
        requester = interaction.guild.get_member(track.requested_by)
        req_name = requester.display_name if requester else f"<@{track.requested_by}>"
        embed = embeds.info(
            title=track.title,
            description=(
                f"{state}\n`{bar}` {_fmt_duration(pos)} / {_fmt_duration(dur)}\n"
                f"[source]({track.webpage_url}) · requested by {req_name}"
            ),
        )
        embed.add_field(name="Loop", value=f"`{player.loop_mode}`", inline=True)
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        embed.add_field(name="In queue", value=str(len(player.queue)), inline=True)
        await interaction.response.send_message(embed=embed)

    @music_group.command(name="loop", description="Set loop mode.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="off — play once then advance", value="off"),
            app_commands.Choice(name="track — repeat current track", value="track"),
            app_commands.Choice(name="queue — cycle the whole queue", value="queue"),
        ]
    )
    @guild_only()
    async def loop(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
    ) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        player.loop_mode = mode.value  # type: ignore[assignment]
        await interaction.response.send_message(
            f"🔁 Loop mode: `{player.loop_mode}`", ephemeral=True
        )

    @music_group.command(
        name="seek",
        description="Jump to a position in the current track. Format: 90 or 1:30.",
    )
    @app_commands.describe(position="Seconds (90) or MM:SS (1:30) or HH:MM:SS (1:02:30).")
    @guild_only()
    async def seek(self, interaction: discord.Interaction, position: str) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        player = self.manager.player_for(interaction.guild)
        if vc is None or player.current is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        try:
            target = _parse_time(position)
        except ValueError:
            await interaction.response.send_message(
                "Couldn't read that time. Use `90`, `1:30`, or `1:02:30`.", ephemeral=True
            )
            return
        if player.current.duration and target >= player.current.duration:
            await interaction.response.send_message(
                "Seek past end — skipping instead.", ephemeral=True
            )
            player.request_skip()
            vc.stop()
            return
        player.request_seek(target)
        vc.stop()  # triggers the after-callback; loop sees the seek flag
        await interaction.response.send_message(
            f"⏩ Seeking to `{_fmt_duration(target)}`.", ephemeral=True
        )

    @music_group.command(name="volume", description="Set playback volume (0–200).")
    @app_commands.describe(percent="Takes effect on the next track.")
    @guild_only()
    async def volume(
        self,
        interaction: discord.Interaction,
        percent: app_commands.Range[int, 0, 200],
    ) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        player.volume = percent / 100
        await interaction.response.send_message(
            f"🔊 Volume: {percent}% — applies to the next track. "
            "Use `/music skip` to apply immediately.",
            ephemeral=True,
        )

    @music_group.command(name="shuffle", description="Shuffle the queue.")
    @guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        if not player.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(
            f"🔀 Shuffled {len(player.queue)} track(s).", ephemeral=True
        )

    @music_group.command(name="clear", description="Remove every upcoming track (keeps current).")
    @guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        removed = len(player.queue)
        player.queue.clear()
        await interaction.response.send_message(f"🗑️ Cleared {removed} track(s).", ephemeral=True)

    @music_group.command(name="remove", description="Remove a track from the queue by position.")
    @app_commands.describe(position="1-based index shown in /music queue.")
    @guild_only()
    async def remove(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1, 10000],
    ) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        try:
            track = player.remove(position - 1)
        except IndexError:
            await interaction.response.send_message("No track at that position.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embeds.success("Removed", f"[{track.title}]({track.webpage_url})"),
            ephemeral=True,
        )

    @music_group.command(name="move", description="Move a queued track to a new position.")
    @app_commands.describe(
        source="Current 1-based position.",
        destination="New 1-based position.",
    )
    @guild_only()
    async def move(
        self,
        interaction: discord.Interaction,
        source: app_commands.Range[int, 1, 10000],
        destination: app_commands.Range[int, 1, 10000],
    ) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        try:
            track = player.move(source - 1, destination - 1)
        except IndexError:
            await interaction.response.send_message("Invalid position.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"↕️ Moved [{track.title}]({track.webpage_url}) to `#{destination}`.",
            ephemeral=True,
        )

    @music_group.command(
        name="playnext",
        description="Queue a track at the front of the line.",
    )
    @app_commands.describe(url="YouTube URL or search query.")
    @guild_only()
    async def playnext(self, interaction: discord.Interaction, url: str) -> None:
        await self._do_play(interaction, url, front=True)

    @music_group.command(name="voteskip", description="Vote to skip the current track.")
    @guild_only()
    async def voteskip(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        vc = self._voice(interaction)
        if vc is None or not vc.is_connected():
            await interaction.response.send_message("Not in a voice channel.", ephemeral=True)
            return
        player = self.manager.player_for(interaction.guild)
        if player.current is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        # Only non-bot members in the bot's voice channel count.
        listeners = [m for m in vc.channel.members if not m.bot]
        if interaction.user not in listeners:
            await interaction.response.send_message(
                "Join the voice channel to vote.", ephemeral=True
            )
            return
        player.skip_votes.add(interaction.user.id)
        needed = max(1, (len(listeners) // 2) + 1)  # simple majority
        if len(player.skip_votes) >= needed:
            player.request_skip()
            vc.stop()
            await interaction.response.send_message(
                f"⏭️ Skipped ({len(player.skip_votes)}/{needed}).",
            )
        else:
            await interaction.response.send_message(
                f"🗳️ Voted to skip ({len(player.skip_votes)}/{needed}).",
            )

    @music_group.command(name="history", description="Show recently played tracks.")
    @guild_only()
    async def history(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.manager.player_for(interaction.guild)
        if not player.history:
            await interaction.response.send_message(
                embed=embeds.info("No history yet", "Play something first."),
                ephemeral=True,
            )
            return
        lines = [
            f"`{i + 1}.` [{t.title}]({t.webpage_url}) — {_fmt_duration(t.duration)}"
            for i, t in enumerate(list(player.history)[:15])
        ]
        await interaction.response.send_message(
            embed=embeds.info(f"Recently played ({len(player.history)})", "\n".join(lines)),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # Auto-disconnect listener
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or self.bot.user is None:
            return
        guild = member.guild
        vc = guild.voice_client
        if not isinstance(vc, discord.VoiceClient) or not vc.is_connected():
            return
        # Did this change affect the bot's channel?
        channel = vc.channel
        if channel not in (before.channel, after.channel):
            return
        non_bot = [m for m in channel.members if not m.bot]
        if non_bot:
            return
        # Nobody left but the bot — wait briefly, then leave.
        await asyncio.sleep(_EMPTY_CHANNEL_SECONDS)
        if vc.is_connected() and not [m for m in channel.members if not m.bot]:
            log.info("Leaving empty voice channel in guild %s", guild.id)
            player = self.manager.player_for(guild)
            player.clear()
            await vc.disconnect(force=False)
            self.manager.drop(guild.id)

    # ------------------------------------------------------------------
    # Shared play implementation
    # ------------------------------------------------------------------
    async def _do_play(
        self,
        interaction: discord.Interaction,
        query: str,
        *,
        front: bool,
    ) -> None:
        assert interaction.guild is not None
        member = interaction.user
        if (
            not isinstance(member, discord.Member)
            or member.voice is None
            or member.voice.channel is None
        ):
            await interaction.response.send_message(
                "Join a voice channel first.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        track = await self._resolve(query, requester_id=member.id)
        if track is None:
            await interaction.followup.send(
                embed=embeds.error("Nothing found", f"No match for `{query}`.")
            )
            return
        await self._enqueue_and_play(interaction, track, front=front)

    async def _enqueue_and_play(
        self,
        interaction: discord.Interaction,
        track: Track,
        *,
        front: bool = False,
    ) -> None:
        assert interaction.guild is not None
        member = interaction.user
        assert isinstance(member, discord.Member)
        assert member.voice is not None and member.voice.channel is not None

        vc = interaction.guild.voice_client
        if vc is None:
            vc = await member.voice.channel.connect(self_deaf=True)
        elif isinstance(vc, discord.VoiceClient) and vc.channel != member.voice.channel:
            await vc.move_to(member.voice.channel)
        assert isinstance(vc, discord.VoiceClient)

        player = self.manager.player_for(interaction.guild)
        try:
            if front:
                player.enqueue_front(track, max_queue=self.bot.settings.music_max_queue)
            else:
                player.enqueue(track, max_queue=self.bot.settings.music_max_queue)
        except ValueError as exc:
            await interaction.followup.send(str(exc))
            return

        if not vc.is_playing() and not vc.is_paused():
            asyncio.create_task(self._playback_loop(interaction.guild, vc, player))
            await interaction.followup.send(
                embed=embeds.success(
                    "Now playing",
                    f"[{track.title}]({track.webpage_url}) — {_fmt_duration(track.duration)}",
                )
            )
        else:
            where = "next" if front else f"#{len(player.queue)}"
            await interaction.followup.send(
                embed=embeds.info(
                    f"Queued ({where})",
                    f"[{track.title}]({track.webpage_url}) — {_fmt_duration(track.duration)}",
                )
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        if interaction.guild is None:
            return None
        vc = interaction.guild.voice_client
        return vc if isinstance(vc, discord.VoiceClient) else None

    async def _resolve(self, query: str, *, requester_id: int) -> Track | None:
        loop = asyncio.get_running_loop()

        def extract() -> dict[str, Any] | None:
            with yt_dlp.YoutubeDL(_YTDL_OPTS) as ydl:
                info = ydl.extract_info(query, download=False)
                if info is None:
                    return None
                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        return None
                    info = entries[0]
                return info

        info = await loop.run_in_executor(None, extract)
        if info is None:
            return None
        stream_url = info.get("url")
        if stream_url is None:
            return None
        return Track(
            title=info.get("title", "Unknown title"),
            url=stream_url,
            webpage_url=info.get("webpage_url", query),
            duration=info.get("duration"),
            requested_by=requester_id,
        )

    async def _search(self, query: str, *, limit: int, requester_id: int) -> list[Track]:
        """Return up to `limit` search candidates (with webpage URLs only).

        Stream URLs are resolved lazily when the user picks a result, so
        we don't burn 5× the extractor work up front.
        """
        loop = asyncio.get_running_loop()
        search_opts = {**_YTDL_SEARCH_OPTS}

        def extract() -> list[dict[str, Any]]:
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                if not info or "entries" not in info:
                    return []
                return [e for e in info["entries"] if e]

        entries = await loop.run_in_executor(None, extract)
        return [
            Track(
                title=e.get("title", "Unknown"),
                url=e.get("url", ""),  # not a real stream URL in flat mode
                webpage_url=e.get("webpage_url") or e.get("url") or "",
                duration=e.get("duration"),
                requested_by=requester_id,
            )
            for e in entries
        ]

    async def _playback_loop(
        self,
        guild: discord.Guild,
        vc: discord.VoiceClient,
        player: GuildPlayer,
    ) -> None:
        """Drain the queue, honouring loop mode, seek, and skip signals."""
        lock = self.manager.lock_for(guild.id)
        if lock.locked():
            # Another loop is already running for this guild.
            return
        async with lock:
            while True:
                # Pick or reuse current track.
                if player.current is None:
                    nxt = player.pop_next()
                    if nxt is None:
                        break
                    player.current = nxt

                # Check voice connection health (reconnect if dropped).
                if not vc.is_connected():
                    channel = _last_channel(vc)
                    if channel is None:
                        log.warning("Voice dropped and no channel to rejoin; aborting.")
                        break
                    try:
                        vc = await channel.connect(self_deaf=True, reconnect=True)
                    except (asyncio.TimeoutError, discord.ClientException) as exc:
                        log.warning("Voice reconnect failed: %s", exc)
                        break

                # Consume seek/skip control flags set before this iteration.
                _, _, seek_offset = player.consume_signals()

                before = _FFMPEG_BEFORE
                if seek_offset > 0:
                    before = f"{before} -ss {seek_offset:.3f}"

                source = discord.FFmpegOpusAudio(
                    player.current.url,
                    executable=self.bot.settings.ffmpeg_path,
                    before_options=before,
                    options=_ffmpeg_options(player.volume),
                )

                finished = asyncio.Event()

                def _after(err: BaseException | None) -> None:
                    if err is not None:
                        log.warning("FFmpeg playback error: %s", err)
                    self.bot.loop.call_soon_threadsafe(finished.set)

                player.mark_play_start(seek_offset=seek_offset)
                vc.play(source, after=_after)
                await finished.wait()

                # Signals set *during* playback decide what happens next.
                seek_req, skip_req, next_seek = player.consume_signals()
                if seek_req:
                    # Replay the same track at the new position.
                    player._pending_seek = next_seek
                    continue
                if skip_req:
                    player.history.appendleft(player.current)
                    player.current = None
                    continue

                # Natural end. Record history, then apply loop mode.
                finished_track = player.current
                player.history.appendleft(finished_track)
                if player.loop_mode == "track":
                    # Keep player.current as-is for a straight replay.
                    continue
                if player.loop_mode == "queue":
                    player.queue.append(finished_track)
                player.current = None

        # Queue drained — schedule a delayed disconnect so quick re-queues
        # don't kick the bot out of voice between tracks.
        await self._schedule_idle_disconnect(guild, vc, player)

    async def _schedule_idle_disconnect(
        self,
        guild: discord.Guild,
        vc: discord.VoiceClient,
        player: GuildPlayer,
    ) -> None:
        async def _disconnect_after_idle() -> None:
            try:
                await asyncio.sleep(_IDLE_DISCONNECT_SECONDS)
            except asyncio.CancelledError:
                return
            if vc.is_connected() and not vc.is_playing() and not player.queue:
                log.info("Idle disconnect from guild %s", guild.id)
                await vc.disconnect(force=False)
                self.manager.drop(guild.id)

        if player.idle_task and not player.idle_task.done():
            player.idle_task.cancel()
        player.idle_task = asyncio.create_task(_disconnect_after_idle())


# =====================================================================
# Helpers
# =====================================================================
_TIME_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


def _parse_time(raw: str) -> float:
    """Parse `90`, `1:30`, or `1:02:30` into seconds."""
    raw = raw.strip()
    m = _TIME_RE.match(raw)
    if not m:
        raise ValueError(raw)
    a, b, c = m.groups()
    parts = [p for p in (a, b, c) if p is not None]
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _fmt_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "??:??"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _progress_bar(pos: float, dur: float, *, width: int = 20) -> str:
    if dur <= 0:
        return "▱" * width
    ratio = max(0.0, min(1.0, pos / dur))
    filled = int(ratio * width)
    return "▰" * filled + "▱" * (width - filled)


def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _last_channel(
    vc: discord.VoiceClient,
) -> discord.VoiceChannel | discord.StageChannel | None:
    channel = getattr(vc, "channel", None)
    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return channel
    return None


async def setup(bot: NovaBot) -> None:
    await bot.add_cog(Music(bot))
