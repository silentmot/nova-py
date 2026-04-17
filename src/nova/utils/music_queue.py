"""Per-guild music queue + player state.

The player keeps everything the music cog needs to render `/nowplaying`,
loop tracks, shuffle, seek, and auto-disconnect: the queue itself, a
small play history, timing state (so we can show a progress bar that
survives pause/resume/seek), and a few one-shot control flags that the
playback loop reads after each track finishes.

Deliberately in-memory only. Queues don't survive bot restarts — that's
the trade-off for not bringing in Redis/SQLite over one cog.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from random import shuffle as _shuffle
from typing import TYPE_CHECKING, Literal

import discord

if TYPE_CHECKING:
    from nova.bot import NovaBot

log = logging.getLogger("nova.music")

LoopMode = Literal["off", "track", "queue"]


@dataclass(slots=True)
class Track:
    """A single playable track as resolved by yt-dlp."""

    title: str
    url: str  # stream URL consumable by FFmpeg
    webpage_url: str  # user-facing URL
    duration: int | None  # seconds, may be None for live streams
    requested_by: int  # Discord user id


@dataclass(slots=True)
class GuildPlayer:
    """Per-guild playback state."""

    guild_id: int
    queue: deque[Track] = field(default_factory=deque)
    history: deque[Track] = field(default_factory=lambda: deque(maxlen=25))
    current: Track | None = None
    volume: float = 0.5
    loop_mode: LoopMode = "off"
    skip_votes: set[int] = field(default_factory=set)

    # Timing state (all values use time.monotonic()).
    _started: float | None = None   # when current ffmpeg source began
    _accumulated: float = 0.0       # seconds played before _started (survives pauses)
    seek_offset: float = 0.0        # seconds added via /seek

    # Control signals consumed by the playback loop after each track.
    _pending_seek: float = 0.0
    _seek_requested: bool = False
    _skip_requested: bool = False

    # Auto-disconnect debounce task.
    idle_task: asyncio.Task[None] | None = None

    # ---- queue mutations --------------------------------------------
    def enqueue(self, track: Track, *, max_queue: int) -> None:
        if len(self.queue) >= max_queue:
            raise ValueError(f"Queue is full (max {max_queue}).")
        self.queue.append(track)

    def enqueue_front(self, track: Track, *, max_queue: int) -> None:
        """Add to the front of the queue (`/music playnext`)."""
        if len(self.queue) >= max_queue:
            raise ValueError(f"Queue is full (max {max_queue}).")
        self.queue.appendleft(track)

    def pop_next(self) -> Track | None:
        try:
            return self.queue.popleft()
        except IndexError:
            return None

    def shuffle(self) -> None:
        buf = list(self.queue)
        _shuffle(buf)
        self.queue = deque(buf)

    def move(self, src: int, dst: int) -> Track:
        buf = list(self.queue)
        if not 0 <= src < len(buf):
            raise IndexError("source index out of range")
        dst = max(0, min(dst, len(buf) - 1))
        item = buf.pop(src)
        buf.insert(dst, item)
        self.queue = deque(buf)
        return item

    def remove(self, idx: int) -> Track:
        buf = list(self.queue)
        if not 0 <= idx < len(buf):
            raise IndexError("index out of range")
        item = buf.pop(idx)
        self.queue = deque(buf)
        return item

    def clear(self) -> None:
        self.queue.clear()
        self.current = None
        self.skip_votes.clear()
        self._started = None
        self._accumulated = 0.0
        self.seek_offset = 0.0
        self._pending_seek = 0.0
        self._seek_requested = False
        self._skip_requested = False

    # ---- timing ------------------------------------------------------
    def mark_play_start(self, *, seek_offset: float = 0.0) -> None:
        self._started = time.monotonic()
        self._accumulated = 0.0
        self.seek_offset = seek_offset
        self.skip_votes.clear()

    def mark_paused(self) -> None:
        if self._started is None:
            return
        self._accumulated += time.monotonic() - self._started
        self._started = None

    def mark_resumed(self) -> None:
        if self._started is None:
            self._started = time.monotonic()

    def position(self) -> float:
        """Elapsed seconds in the current track (pause- and seek-aware)."""
        base = self._accumulated + self.seek_offset
        if self._started is not None:
            base += time.monotonic() - self._started
        return max(0.0, base)

    # ---- control signals --------------------------------------------
    def request_seek(self, seconds: float) -> None:
        self._pending_seek = max(0.0, seconds)
        self._seek_requested = True

    def request_skip(self) -> None:
        self._skip_requested = True

    def consume_signals(self) -> tuple[bool, bool, float]:
        """Return (seek_requested, skip_requested, seek_offset) and reset them."""
        seek_req = self._seek_requested
        skip_req = self._skip_requested
        offset = self._pending_seek
        self._seek_requested = False
        self._skip_requested = False
        self._pending_seek = 0.0
        return seek_req, skip_req, offset


class MusicManager:
    """Registry of per-guild players."""

    def __init__(self, bot: NovaBot) -> None:
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def player_for(self, guild: discord.Guild) -> GuildPlayer:
        player = self._players.get(guild.id)
        if player is None:
            player = GuildPlayer(guild_id=guild.id)
            self._players[guild.id] = player
        return player

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    def drop(self, guild_id: int) -> None:
        player = self._players.pop(guild_id, None)
        if player and player.idle_task and not player.idle_task.done():
            player.idle_task.cancel()
        self._locks.pop(guild_id, None)
