"""Logging setup.

Uses `rich` for readable console output in development and falls back to
plain stderr logging in production for predictable container log lines.
"""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

from nova.config import Settings

_CONFIGURED = False


def configure_logging(settings: Settings) -> None:
    """Configure the root and `nova.*` loggers.

    Idempotent — safe to call multiple times (tests, reload scenarios).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = _parse_level(settings.log_level)

    handler: logging.Handler
    if settings.is_development:
        handler = RichHandler(
            console=Console(stderr=True),
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            show_path=False,
            show_time=True,
            markup=False,
        )
        fmt = "%(message)s"
    else:
        handler = logging.StreamHandler(stream=sys.stderr)
        fmt = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"

    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    # Silence noisy third-party loggers at WARNING; keep our own at `level`.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    logging.getLogger("nova").setLevel(level)
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)

    _CONFIGURED = True


def _parse_level(value: str) -> int:
    """Accept both names and numeric levels."""
    if value.isdigit():
        return int(value)
    level = logging.getLevelName(value.upper())
    if isinstance(level, int):
        return level
    return logging.INFO
