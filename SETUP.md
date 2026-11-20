# Setup and operations guide

This is the hands-on setup, deploy and troubleshooting guide. For the project overview, see [README.md](README.md).

Self-hosted web app that syncs your WHOOP data every morning (and on demand), stores it in SQLite, and serves a password-protected dashboard plus an MCP endpoint so Claude can answer questions about your recovery, sleep, strain and workouts. Only external host contacted: `api.prod.whoop.com`.

```
app/
  main.py        FastAPI routes, auth wiring, scheduler, MCP mount
  auth.py        shared-password login, signed cookie, lockout
  whoop.py       WHOOP API client (OAuth, pagination, retry) + sync job
  db.py          SQLite schema and helpers
  payload.py     rows -> dashboard / MCP JSON
  mcp_server.py  MCP tools (get_summary, get_daily, get_workouts, get_sync_status, trigger_sync)
  templates/     login.html, dashboard.html
tests/           pytest suite with a mocked WHOOP API
legacy/          the original CLI script and template (not used by the app)
```

## 1. WHOOP developer app (one time)

1. https://developer-dashboard.whoop.com → create a Team → **Create App**.
2. Scopes: `offline read:recovery read:cycles read:sleep read:workout read:body_measurement`.
3. Redirect URLs (add both):
   - `http://localhost:8080/auth/whoop/callback`
   - `https://<app>.fly.dev/auth/whoop/callback` (fill in after step 3 below)
4. Note the Client ID and Client Secret. They only ever go into `.env` (local) or `fly secrets` (prod).

## 2. Local dev

```bash
uv venv .venv && uv pip install -r requirements-dev.txt     # or: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                                         # fill in values; SESSION_SECRET: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080, sign in with `DASHBOARD_PASSWORD`, click **Connect WHOOP**, approve. The first sync (last `INITIAL_DAYS` days) starts automatically. Data lands in `./data/whoop.db` (git-ignored).

Tests: `.venv/bin/python -m pytest -q`

**Preview without a WHOOP account:** `.venv/bin/python scripts/seed_demo.py` fills `./data/whoop.db` with 180 days of sample data. Delete the `data/` folder before connecting your real account.

## 3. Deploy to Fly.io

```bash
fly launch --no-deploy --copy-config --name <app> --region bom
fly volumes create whoop_data --size 1 --region bom
fly secrets set \
  WHOOP_CLIENT_ID=... \
  WHOOP_CLIENT_SECRET=... \
  WHOOP_REDIRECT_URI=https://<app>.fly.dev/auth/whoop/callback \
  DASHBOARD_PASSWORD=... \
  SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))') \
  MCP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
fly deploy
```

Then add `https://<app>.fly.dev/auth/whoop/callback` as a Redirect URL in the WHOOP developer dashboard, open the app, log in, Connect WHOOP.

Non-default env (`TZ`, `SYNC_HOUR`, `SYNC_MINUTE`, `INITIAL_DAYS`) lives in `fly.toml` `[env]`. `auto_stop_machines = false` keeps the scheduler alive; `/healthz` is the health check.

## 4. Connect Claude to the MCP endpoint

The MCP server is at `https://<app>.fly.dev/mcp` (streamable HTTP), protected by `MCP_TOKEN` as a bearer token. It's disabled when `MCP_TOKEN` is unset.

- **Claude.ai / desktop (custom connector):** URL `https://<app>.fly.dev/mcp`, auth header `Authorization: Bearer <MCP_TOKEN>`.
- **Claude Code:** `claude mcp add --transport http whoop https://<app>.fly.dev/mcp --header "Authorization: Bearer <MCP_TOKEN>"`

Tools: `get_summary(days)`, `get_daily(start, end | days)`, `get_workouts(days, sport)`, `get_sync_status()`, `trigger_sync()`.

## How sync works

- Daily cron at `SYNC_HOUR:SYNC_MINUTE` in `TZ`, plus a catch-up sync on startup if the last one is > 24 h old.
- First sync pulls `INITIAL_DAYS`; later syncs re-pull from `last_sync − 7 days` because WHOOP re-scores recent sleeps. Pagination via `nextToken`, 25 per page, backoff on 429/5xx.
- Access tokens are refreshed when expired; the rotated refresh token is always persisted. If refresh fails, the dashboard shows **Connect WHOOP** again.
- A lock ensures the scheduler and the **Sync now** button never run two syncs at once. One log line per sync with counts and duration.

## Troubleshooting

- **"Missing required environment variable(s)"** at startup → check `.env` / `fly secrets list`.
- **Redirect URL error on sign-in** → the URL in the WHOOP app must match `WHOOP_REDIRECT_URI` exactly.
- **Dashboard says "Connect WHOOP" again** → token refresh failed; reconnect. Check `fly logs` for the reason.
- **Reset everything** → `fly ssh console -C "rm /data/whoop.db"` then redeploy (or delete `./data` locally).

## Goals and activity categories

Optional env vars (defaults shown). Sport names are WHOOP's `sport_name` values; spaces and underscores both match.

```
GOAL_RUNS=4                 # run sessions per week
GOAL_STRENGTH=3             # strength sessions per week
GOAL_RUN_KM=20              # km per week
RUN_SPORTS=running,treadmill,trail running,track running
STRENGTH_SPORTS=weightlifting,strength trainer,strength workout,functional fitness,powerlifting,crossfit
WALK_SPORTS=walking,hiking  # excluded from "hours exercised"
```

VO2 max isn't available from the WHOOP API; enter it on the dashboard (the pencil on the VO2 max tile) whenever the app updates it.
