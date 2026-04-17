#!/usr/bin/env bash
# Update Nova on a GCE VM.
#
# Run this ON THE VM (not your laptop). It:
#   1. Pulls the latest main branch
#   2. Rebuilds the Docker image if anything changed
#   3. Restarts the container if the image is new
#   4. Tails the last 50 log lines so you can confirm it came back up
#
# Idempotent: running it twice in a row is a no-op.

set -euo pipefail

# Resolve the repo root regardless of where this was invoked from.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_DIR="$(dirname -- "$SCRIPT_DIR")"
cd "$REPO_DIR"

echo ">> pulling latest from origin"
git fetch --quiet origin
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse '@{u}')

if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo ">> already up to date ($LOCAL)"
else
    git pull --ff-only
    echo ">> pulled $(git rev-parse --short HEAD)"
fi

echo ">> refreshing .env from Secret Manager"
bash "$SCRIPT_DIR/fetch-secret.sh"

echo ">> building image (cache will make this fast if nothing changed)"
docker compose build --pull

echo ">> (re)starting container"
docker compose up -d

echo ">> recent logs"
docker compose logs --tail=50 nova
