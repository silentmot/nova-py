"""Embed builders for consistent visual styling across cogs."""

from __future__ import annotations

from datetime import datetime, timezone

import discord


def success(title: str, description: str | None = None) -> discord.Embed:
    return _embed(title, description, color=discord.Color.green())


def info(title: str, description: str | None = None) -> discord.Embed:
    return _embed(title, description, color=discord.Color.blurple())


def warning(title: str, description: str | None = None) -> discord.Embed:
    return _embed(title, description, color=discord.Color.gold())


def error(title: str, description: str | None = None) -> discord.Embed:
    return _embed(title, description, color=discord.Color.red())


def _embed(title: str, description: str | None, *, color: discord.Color) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(tz=timezone.utc),
    )
