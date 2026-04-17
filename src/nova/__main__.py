"""Entry point for `python -m nova`.

Loads settings from the environment (`.env` if present), wires up logging,
and starts the Discord bot under asyncio.run.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from nova.bot import NovaBot
from nova.config import Settings, load_settings
from nova.logging import configure_logging

log = logging.getLogger("nova")


async def _run(settings: Settings) -> None:
    bot = NovaBot(settings)

    # Graceful shutdown on SIGINT / SIGTERM. On Windows, loop.add_signal_handler
    # isn't supported — fall back to default KeyboardInterrupt handling there.
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))
        except NotImplementedError:
            # Windows ProactorEventLoop — handled by KeyboardInterrupt below.
            break

    async with bot:
        await bot.start(settings.discord_bot_token)


def main() -> int:
    """CLI entrypoint. Returns a Unix-style exit code."""
    settings = load_settings()
    configure_logging(settings)
    log.info("Starting Nova v%s (env=%s)", _version(), settings.environment)

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        log.info("Received keyboard interrupt, shutting down.")
        return 0
    except Exception:  # noqa: BLE001 — top-level crash log
        log.exception("Fatal error — the bot is exiting.")
        return 1
    return 0


def _version() -> str:
    from nova import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
