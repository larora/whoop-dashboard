# Setting up your own WHOOP dashboard

This guide takes you from zero to a running dashboard connected to **your** WHOOP account. It assumes you're comfortable with a terminal but nothing more. For what the project is, see [README.md](README.md).

**Time needed:** about 15 minutes to run it on your laptop, 30–45 minutes to host it somewhere permanent.

---

## Step 1: Create a WHOOP developer app (everyone does this once)

The app talks to WHOOP through their official API, which requires your own free developer app. This is how WHOOP knows the dashboard is allowed to read your data, and it means your data never goes through anyone else's servers.

1. Go to https://developer-dashboard.whoop.com and sign in with your normal WHOOP login.
2. Create a **Team** (any name), then click **Create App**.
3. Fill in:
   - **Name:** anything, e.g. "My dashboard"
   - **Scopes:** tick all of `offline`, `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`, `read:body_measurement`
   - **Redirect URLs:** add `http://localhost:8080/auth/whoop/callback` now. When you host it later, you'll come back and add a second one for your real address.
4. Save, then copy the **Client ID** and **Client Secret**. Treat the secret like a password.

## Step 2: Run it on your laptop first

This proves everything works before you deal with hosting.

```bash
git clone https://github.com/<your-github-username>/whoop-dashboard.git
cd whoop-dashboard
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Open `.env` in any text editor and fill in:

| Variable | What to put |
|---|---|
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | from Step 1 |
| `WHOOP_REDIRECT_URI` | leave as `http://localhost:8080/auth/whoop/callback` |
| `DASHBOARD_PASSWORD` | a password of your choice for the login page |
| `SESSION_SECRET` | a long random string. Generate one with: `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` |

Everything else can stay at its default. Then start it:

```bash
set -a && source .env && set +a && .venv/bin/uvicorn app.main:app --port 8080
```

Open http://localhost:8080, sign in with your dashboard password, click **Connect WHOOP**, approve on WHOOP's page. The first sync pulls the last year and takes a minute or two.

> **No WHOOP yet, or just want to see it?** Run `.venv/bin/python scripts/seed_demo.py` before starting the server. The dashboard fills with 180 days of realistic sample data. Delete the `data/` folder before connecting a real account.

## Step 3: Pick where to host it

The app is one process that needs three things: to stay running (it syncs on a schedule), a folder that persists (the SQLite database), and HTTPS (WHOOP requires it for anything other than localhost). Any option below gives you all three.

| Option | Good for | Cost | Effort |
|---|---|---|---|
| **A. Your own server + Docker** | a VPS, home server, Raspberry Pi | whatever the server costs | medium |
| **B. Your own server, no Docker** | same, if you prefer systemd | same | medium |
| **C. Fly.io** | no server to manage, deploy in 5 commands | ~$2–3/month | low |
| **D. Other PaaS** (Railway, Render, …) | same idea as Fly | varies | low |
| **E. Just your laptop** | trying it out | free | none, but it only syncs while the laptop is on |

Whichever you choose, the app-level config is the same `.env` variables as Step 2, with two changes: `WHOOP_REDIRECT_URI` becomes `https://<your address>/auth/whoop/callback`, and you add that same URL to your WHOOP app's Redirect URLs.

### Option A: Your own server with Docker

On the server:

```bash
git clone https://github.com/<your-github-username>/whoop-dashboard.git && cd whoop-dashboard
cp .env.example .env     # fill in as in Step 2, but set DATA_DIR=/data and the https redirect URI
sudo mkdir -p /var/lib/whoop
docker build -t whoop-dashboard .
docker run -d --name whoop --restart unless-stopped --env-file .env \
  -v /var/lib/whoop:/data -p 127.0.0.1:8080:8080 whoop-dashboard
```

The app now listens on port 8080, only on the server itself. Put HTTPS in front with Caddy (it fetches certificates automatically):

```bash
sudo apt install caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain first
sudo systemctl reload caddy
```

Point your domain's DNS at the server, open `https://your-domain`, sign in, Connect WHOOP.

**Updating later:** `git pull && docker build -t whoop-dashboard . && docker rm -f whoop` then the same `docker run` line. Your data is in `/var/lib/whoop`, untouched.

### Option B: Your own server with systemd (no Docker)

```bash
sudo useradd --system --home /opt/whoop --create-home whoop
sudo -u whoop git clone https://github.com/<your-github-username>/whoop-dashboard.git /opt/whoop/app
cd /opt/whoop/app
sudo -u whoop python3 -m venv .venv && sudo -u whoop .venv/bin/pip install -r requirements.txt
sudo -u whoop cp .env.example .env     # fill in; set DATA_DIR=/opt/whoop/data
sudo chmod 600 .env
sudo cp deploy/whoop-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now whoop-dashboard
```

Then the same Caddy step as Option A. Logs: `journalctl -u whoop-dashboard -f`. Updating: `git pull`, reinstall requirements if they changed, `sudo systemctl restart whoop-dashboard`.

### Option C: Fly.io

Install the Fly CLI (https://fly.io/docs/flyctl/install/) and sign up, then from the repo folder:

```bash
fly launch --no-deploy --copy-config --name <pick-a-name> --region <nearest, e.g. bom, lhr, iad>
fly volumes create whoop_data --size 1 --region <same region>
fly secrets set \
  WHOOP_CLIENT_ID=... \
  WHOOP_CLIENT_SECRET=... \
  WHOOP_REDIRECT_URI=https://<pick-a-name>.fly.dev/auth/whoop/callback \
  DASHBOARD_PASSWORD=... \
  SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
fly deploy
```

Add `https://<pick-a-name>.fly.dev/auth/whoop/callback` to your WHOOP app, open the URL, sign in, Connect WHOOP. `fly.toml` already keeps one machine always on (the scheduler needs it) and mounts the volume at `/data`. Timezone and sync time live in its `[env]` block.

### Option D: Railway, Render and similar

They all build the `Dockerfile` directly. You need to: set the same environment variables as secrets, attach a persistent disk and set `DATA_DIR` to its mount path, and make sure the service isn't put to sleep when idle (the daily sync runs inside the app). Health check path: `/healthz`.

## Step 4: Optional extras

**Let Claude read your data (MCP).** Set `MCP_TOKEN` to a long random string and restart. The MCP server is then at `https://<your address>/mcp`. In Claude, add it as a custom connector with header `Authorization: Bearer <that token>`; in Claude Code: `claude mcp add --transport http whoop https://<your address>/mcp --header "Authorization: Bearer <that token>"`. Leave `MCP_TOKEN` empty and the endpoint doesn't exist.

**Training goals and categories.** Defaults shown; override in `.env`:

```
GOAL_RUNS=4                 # run sessions per week
GOAL_STRENGTH=3             # strength sessions per week
GOAL_RUN_KM=20              # km per week
RUN_SPORTS=running,treadmill,trail running,track running
STRENGTH_SPORTS=weightlifting,strength trainer,strength workout,functional fitness,powerlifting,crossfit
WALK_SPORTS=walking,hiking  # excluded from "hours exercised"
TZ=Asia/Kolkata             # your timezone; sync runs at SYNC_HOUR:SYNC_MINUTE in it
SYNC_HOUR=9
SYNC_MINUTE=0
```

Sport names are whatever WHOOP calls the activity when you log it. Check the "Recent workouts" table to see the exact names in your data.

**VO2 max.** WHOOP's API doesn't expose it. Click the pencil on the VO2 max tile and type the number from the app whenever it changes; the history is kept.

## How it works, briefly

- Every morning at `SYNC_HOUR`, and whenever you press **Sync now**, the app pulls recovery, sleep, cycles and workouts from WHOOP into a SQLite file in `DATA_DIR`. On startup it also syncs if the last one is more than 24 hours old.
- The first sync pulls `INITIAL_DAYS` (default 365). Later syncs re-pull the last 7 days because WHOOP re-scores recent sleeps.
- Tokens are refreshed automatically. If that ever fails (e.g. you revoked access), the dashboard shows **Connect WHOOP** again.
- The only external host the app contacts is `api.prod.whoop.com`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing required environment variable(s)` on start | a value in `.env` is empty, or `.env` wasn't loaded (Docker: `--env-file`; systemd: `EnvironmentFile`) |
| WHOOP shows a redirect URL error on sign-in | the URL in the WHOOP app must match `WHOOP_REDIRECT_URI` character for character, including `https` and the path |
| Browser says the cookie is rejected / login loops | you're on plain `http` with a non-localhost address. Put HTTPS in front |
| Dashboard shows **Connect WHOOP** again after working | token refresh failed; just reconnect. Logs say why |
| Data disappeared after a redeploy | `DATA_DIR` pointed inside the container or app folder. Use a volume or a path outside the checkout |
| Strength sessions show 0 | your sport name differs; look at "Recent workouts" and add it to `STRENGTH_SPORTS` |
| Start over | stop the app, delete the database file in `DATA_DIR`, start again |

## Running the tests

```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```

Tests use a mocked WHOOP API; they never contact the real one.
