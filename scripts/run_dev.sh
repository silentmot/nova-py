#!/usr/bin/env bash
# Convenience wrapper for local development.
# Activates .venv if present, loads .env, and starts the bot.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec python -m nova "$@"
