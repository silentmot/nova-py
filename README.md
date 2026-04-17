# Nova — OpenClaw Discord Channel

Nova is a Python Discord bot built with [discord.py](https://discordpy.readthedocs.io/) v2
that also functions as an [OpenClaw Discord Channel](https://docs.openclaw.ai/channels/discord).
It exposes AI-friendly slash commands for music playback, scheduled events, message pinning,
webhook management, and general utility — all wired up so an OpenClaw agent can drive them
through Discord's native gateway.

## Features

- **Slash-command first** — all user-facing actions use application commands (`/music`, `/event`, `/pin`, `/webhook`, ...).
- **Music playback** — `/music play|pause|resume|skip|queue|stop`, powered by `ffmpeg` + `yt-dlp`.
- **Scheduled events** — `/event create|list|cancel` wrapping Discord's guild scheduled events API.
- **Pins** — `/pin add|remove|list` for quick message pinning without needing manage-messages UI.
- **Webhooks** — `/webhook create|send|list|delete` for programmatic channel posting.
- **Admin tools** — owner-only `/admin sync|reload|shutdown` for live ops.
- **OpenClaw integration** — honors DM / guild / mention policies, exposes session keys that match
  the OpenClaw channel spec (`agent:<agentId>:discord:channel:<channelId>`, etc.).

## Project layout

```
nova-py/
├── src/nova/              # Bot package
│   ├── __main__.py        # `python -m nova`
│   ├── bot.py             # NovaBot (commands.Bot subclass + setup_hook)
│   ├── config.py          # Pydantic settings from .env
│   ├── logging.py         # Rich + stdlib logging
│   ├── openclaw.py        # OpenClaw session/policy helpers
│   ├── cogs/              # Feature modules (slash commands)
│   └── utils/             # Shared helpers (embeds, checks, music queue)
├── openclaw/channel.yaml  # OpenClaw channel manifest
├── config/                # Example config + logging yaml
├── tests/                 # Pytest suite
├── Dockerfile             # Multi-stage build with ffmpeg
├── docker-compose.yml
├── pyproject.toml         # Package metadata + ruff/black/mypy/pytest config
├── requirements.txt       # Runtime deps
└── requirements-dev.txt   # + lint/test tooling
```

## Prerequisites

- Python **3.11+**
- `ffmpeg` on `$PATH` (for music playback)
- A Discord bot application with the **Message Content** and **Server Members** privileged intents enabled

## Quick start

```bash
# 1. Create virtualenv and install dev deps
make install-dev

# 2. Copy env template and fill in your token
cp .env.example .env
# edit .env — set DISCORD_BOT_TOKEN, DISCORD_DEV_GUILD_ID (optional)

# 3. Run the bot
make run
```

Or without Make:

```bash
python -m venv .venv
. .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e ".[dev]"
python -m nova
```

## Docker

```bash
docker build -t nova-bot .
docker run --rm -it --env-file .env nova-bot
```

Or with Compose:

```bash
docker compose up --build
```

## Invite URL

Replace `<CLIENT_ID>` with your application's client ID. The `applications.commands` scope is
required for slash commands to show up in Discord.

```
https://discord.com/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot+applications.commands&permissions=277083450960
```

## Development

| Task                 | Command            |
| -------------------- | ------------------ |
| Install dev tools    | `make install-dev` |
| Run the bot          | `make run`         |
| Run tests            | `make test`        |
| Lint                 | `make lint`        |
| Format (ruff+black)  | `make format`      |
| Type check           | `make typecheck`   |
| All of the above     | `make check`       |

### Adding a cog

1. Create `src/nova/cogs/my_cog.py` with a `commands.Cog` subclass and an
   `async def setup(bot): await bot.add_cog(MyCog(bot))` function.
2. Add its module path to `INITIAL_EXTENSIONS` in
   [`src/nova/bot.py`](src/nova/bot.py).
3. Use `/admin reload my_cog` in Discord to hot-reload without restarting.

## OpenClaw channel configuration

The [`openclaw/channel.yaml`](openclaw/channel.yaml) file describes how the OpenClaw gateway
should register Nova as a Discord channel. It defines the bot's token env var, DM / guild
policies, reply mode, streaming behavior, and tool gates as per the
[OpenClaw docs](https://docs.openclaw.ai/channels/discord). Reference it from your OpenClaw
gateway config via `channels.discord` include or directly copy values across.

## License

MIT — see [LICENSE](LICENSE).
