#!/usr/bin/env bash
# Pull the Nova bot configuration from GCP Secret Manager and write it
# to ../.env with 0600 perms.
#
# Designed to run ON the GCE VM. Uses the instance metadata server for
# auth — no gcloud install required, no credentials on disk.
#
# The VM's default service account must have the role
# `roles/secretmanager.secretAccessor` on the secret.

set -euo pipefail

PROJECT="${GCP_PROJECT:-nova-bot-mot}"
SECRET="${GCP_SECRET:-nova}"
VERSION="${GCP_SECRET_VERSION:-latest}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
OUT_FILE="${OUT_FILE:-$SCRIPT_DIR/../.env}"

META_URL="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
SM_URL="https://secretmanager.googleapis.com/v1/projects/${PROJECT}/secrets/${SECRET}/versions/${VERSION}:access"

echo ">> fetching access token from metadata server"
TOKEN=$(curl -sSf -H "Metadata-Flavor: Google" "$META_URL" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo ">> fetching secret: projects/${PROJECT}/secrets/${SECRET}/versions/${VERSION}"
TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

curl -sSf -H "Authorization: Bearer $TOKEN" "$SM_URL" \
    | python3 -c '
import sys, json, base64
payload = json.load(sys.stdin)["payload"]["data"]
sys.stdout.write(base64.b64decode(payload).decode("utf-8"))
' > "$TMP_FILE"

# Atomic move so a failed fetch never leaves a truncated .env behind.
mv "$TMP_FILE" "$OUT_FILE"
trap - EXIT
chmod 600 "$OUT_FILE"

# Report what we got without leaking values.
KEYS=$(grep -oE '^[A-Z_][A-Z0-9_]*' "$OUT_FILE" | sort | uniq | tr '\n' ' ')
echo ">> wrote $OUT_FILE ($(wc -l < "$OUT_FILE") lines)"
echo ">> keys: $KEYS"
