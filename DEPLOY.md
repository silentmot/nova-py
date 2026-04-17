# Deploying Nova to GCE (e2-micro, free tier)

This runbook deploys Nova to a single Google Compute Engine VM running
the existing Docker image. No code changes. Total cost: **$0** if you
keep the VM in `us-central1`, `us-west1`, or `us-east1` (Google's
[Always Free](https://cloud.google.com/free/docs/free-cloud-features#compute)
tier).

Works on bash / Git Bash / WSL / macOS. On Windows cmd, replace `$VAR`
with `%VAR%` in set-variable lines.

---

## Prerequisites

- `gcloud` CLI installed and `gcloud auth login` done
- A GCP project with billing enabled (free tier still needs billing on file)
- The code pushed to a Git remote (GitHub, GitLab, whatever) so the VM
  can `git clone` it. See [Git setup](#git-setup) if you haven't done this yet.
- Your rotated Discord bot token at hand

## Variables used below

```bash
PROJECT=your-gcp-project-id           # gcloud config get-value project
REGION=us-central1                     # stay in the free-tier regions
ZONE=us-central1-a
VM_NAME=nova-bot
REPO_URL=https://github.com/you/nova-py.git  # your fork/repo URL
```

---

## 1. Git setup

If you haven't already:

```bash
cd /path/to/nova-py
git init
git add -A
git status    # sanity-check: .env must NOT appear here
git commit -m "initial scaffold"

# Create a repo on GitHub (via web UI, or 'gh repo create nova-py --private --source=. --remote=origin')
git branch -M main
git remote add origin git@github.com:you/nova-py.git
git push -u origin main
```

Double-check `.env` is ignored:

```bash
git ls-files | grep -E '^\.env$'   # must print nothing
```

---

## 2. Create the VM

```bash
gcloud compute instances create $VM_NAME \
    --project=$PROJECT \
    --zone=$ZONE \
    --machine-type=e2-micro \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard \
    --tags=nova \
    --metadata=enable-oslogin=TRUE
```

**Note:** Free-tier limits are **1 e2-micro in us-central1/us-west1/us-east1**
and **30 GB standard persistent disk**. Anything more spills over into paid.

No firewall rules needed. Nova is outbound-only (connects to Discord);
nothing on the internet needs to reach it.

---

## 3. Install Docker on the VM

```bash
gcloud compute ssh $VM_NAME --zone=$ZONE --command='
  set -euo pipefail
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl git gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
  sudo usermod -aG docker $USER
'
```

Log out of SSH if you were in — the `docker` group membership applies
on next login.

---

## 4. Clone the repo on the VM

```bash
gcloud compute ssh $VM_NAME --zone=$ZONE --command="
  set -euo pipefail
  if [ ! -d ~/nova ]; then
    git clone $REPO_URL ~/nova
  else
    cd ~/nova && git pull --ff-only
  fi
"
```

---

## 5. Store `.env` in Secret Manager (once)

Keep secrets out of the VM filesystem and git. This only needs to be
done once, from your laptop:

```bash
# Put the complete production .env into a file on your laptop (never commit it).
# Then upload as a Secret Manager secret:
gcloud secrets create nova \
    --project=$PROJECT \
    --replication-policy=automatic \
    --data-file=./prod.env

# Later, to update the token or any other value:
gcloud secrets versions add nova --project=$PROJECT --data-file=./prod.env
```

Grant the VM's default service account read access to the secret
(one-time IAM binding):

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding nova \
    --project=$PROJECT \
    --member=serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
```

And make sure the VM was created (or updated) with the `cloud-platform`
scope so the metadata-server token can call Secret Manager:

```bash
# Only needed if the VM was created with default scopes.
gcloud compute instances stop $VM_NAME --zone=$ZONE
gcloud compute instances set-service-account $VM_NAME --zone=$ZONE \
    --service-account=${PROJECT_NUMBER}-compute@developer.gserviceaccount.com \
    --scopes=cloud-platform
gcloud compute instances start $VM_NAME --zone=$ZONE
```

Minimum prod `.env` contents (paste this into your local `prod.env`
before running `gcloud secrets create nova ...`):

```env
DISCORD_BOT_TOKEN=<your rotated token>
DISCORD_OWNER_IDS=250332983964336128

# Leave unset — production syncs slash commands globally.
# DISCORD_DEV_GUILD_ID=

ENVIRONMENT=production
LOG_LEVEL=INFO

OPENCLAW_AGENT_ID=main
OPENCLAW_DM_POLICY=pairing
OPENCLAW_GROUP_POLICY=allowlist
OPENCLAW_HISTORY_LIMIT=20
OPENCLAW_REPLY_MODE=batched
OPENCLAW_STREAMING=off

FFMPEG_PATH=ffmpeg
MUSIC_MAX_QUEUE=100
```

### Pulling the secret onto the VM

Use the helper [`deploy/fetch-secret.sh`](deploy/fetch-secret.sh) — it
uses the GCE metadata server to authenticate, so no credentials ever
touch the VM's disk beyond the resulting `.env`:

```bash
gcloud compute ssh $VM_NAME --zone=$ZONE
# on the VM:
cd ~/nova
bash deploy/fetch-secret.sh
```

The script writes `~/nova/.env` with mode 600 and prints the list of
keys (not values) it retrieved so you can eyeball it.

---

## 6. Start the bot

Still on the VM:

```bash
cd ~/nova
docker compose up -d --build
docker compose logs -f nova
```

You should see:

```
INFO  Starting Nova v0.1.0 (env=production)
INFO  Loaded extension: nova.cogs.general
...
INFO  Synced N command(s) globally
INFO  Logged in as Nova#1759 — serving N guild(s)
```

Detach from logs with `Ctrl+C`. The container keeps running (compose's
`restart: unless-stopped`).

**Remember:** global slash-command syncs can take up to an hour to
propagate to Discord clients the first time. After that, they're fast.

---

## 7. Day-2 operations

### Update the bot after a `git push`

From the VM (one command, uses the helper in [`deploy/update.sh`](deploy/update.sh)):

```bash
bash ~/nova/deploy/update.sh
```

*(First time only: `chmod +x ~/nova/deploy/update.sh` if you prefer the
shorter `~/nova/deploy/update.sh` form. Windows git can lose the
executable bit, hence `bash …` above.)*

Or, manually:

```bash
cd ~/nova
git pull --ff-only
docker compose build
docker compose up -d
```

### Tail logs

```bash
docker compose logs -f nova --tail=200
```

### Restart

```bash
cd ~/nova && docker compose restart
```

### Stop

```bash
cd ~/nova && docker compose down
```

### Shell inside the container

```bash
docker compose exec nova bash
```

### Tear down the VM

```bash
gcloud compute instances delete $VM_NAME --zone=$ZONE
```

---

## When to graduate off this setup

- **You want `git push` → auto-redeploy.** → Switch to **Cloud Run** with
  a Cloud Build trigger. Be aware: Cloud Run with `--min-instances=1 --no-cpu-throttling`
  ≈ $15–25/mo, i.e. paid.
- **You need more than 1 GB RAM** (e.g. Lavalink later). → Upgrade to
  `e2-small` (~$13/mo) or add swap on the e2-micro.
- **You want secrets out of the `.env` file.** → Use GCP Secret Manager
  and mount at container start via `docker run --env-file <(gcloud secrets versions access latest --secret=...)`. Overkill for a single-user bot; do it if the
  VM hosts multiple services.
