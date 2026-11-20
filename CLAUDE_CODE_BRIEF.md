# Brief for Claude Code: WHOOP web dashboard

Build a small, self-hosted web app that syncs my WHOOP data every morning (and on demand), stores it, and shows a password-protected dashboard. Deploy target is Fly.io; code lives in a private repo on my **personal** GitHub.

This is a personal project with my own health data. Keep it simple, dependency-light, and never put secrets or data in the repo.

## Starting point

Two files already exist in this folder — reuse them, don't start from scratch:

- `whoop_sync.py` — working WHOOP API client: OAuth token refresh, paginated fetch of cycles / recovery / sleep / workouts (`/developer/v2/...`), SQLite upsert, and a `build_payload()` that shapes data for the dashboard. It currently stores secrets in macOS Keychain and bakes data into a static HTML file; both must change (see below).
- `dashboard_template.html` — complete dashboard UI (vanilla JS + inline SVG charts, light/dark). It currently reads a `DATA` constant injected at build time; change it to fetch `/api/data` instead. Keep the visuals.

## What to build

```
whoop-dashboard/
├── app/
│   ├── main.py          # FastAPI app: routes, auth, scheduler startup
│   ├── whoop.py         # API client + sync (from whoop_sync.py, minus keyring/CLI/HTML)
│   ├── db.py            # SQLite helpers; tables: cycles, recovery, sleep, workouts, meta, oauth_tokens
│   └── templates/
│       ├── login.html
│       └── dashboard.html   # from dashboard_template.html
├── Dockerfile
├── fly.toml
├── requirements.txt     # fastapi, uvicorn, httpx, jinja2, itsdangerous, apscheduler
├── .gitignore           # *.db, .env, __pycache__, .venv
├── .env.example
└── README.md            # setup + deploy steps for me
```

### Routes

| Route | Purpose |
|---|---|
| `GET /login`, `POST /login` | Single shared password (from `DASHBOARD_PASSWORD`). Signed session cookie (itsdangerous), HttpOnly, Secure, 30-day expiry. Constant-time compare. Simple rate limit (e.g. 5 failures → 1-min lockout). |
| `POST /logout` | Clear cookie. |
| `GET /` | Dashboard (login required). If WHOOP isn't connected yet, show a "Connect WHOOP" button instead of charts. |
| `GET /api/data` | JSON from `build_payload()` (login required). Add `last_sync`, `sync_running`, `whoop_connected`. |
| `POST /sync` | "Sync now" — kick off a sync in the background, return 202; dashboard polls `/api/data` until `sync_running` is false. Ignore if already running. |
| `GET /auth/whoop` | Redirect to WHOOP OAuth (`https://api.prod.whoop.com/oauth/oauth2/auth`) with scopes `offline read:recovery read:cycles read:sleep read:workout read:body_measurement`, random `state` (≥8 chars) stored in the session. |
| `GET /auth/whoop/callback` | Verify state, exchange code at `https://api.prod.whoop.com/oauth/oauth2/token`, store access + refresh token + expiry in `oauth_tokens` table, run a first sync, redirect to `/`. |
| `GET /healthz` | 200 for Fly health checks. No auth. |

### Sync behaviour

- Scheduler: APScheduler `BackgroundScheduler` started on app startup, cron from `SYNC_HOUR` / `SYNC_MINUTE` (default 09:00) in `TZ` (default `Asia/Kolkata`). Also run a sync on startup if `last_sync` is older than 24 h.
- First sync pulls `INITIAL_DAYS` (default 365). Later syncs re-pull from `last_sync − 7 days` (WHOOP re-scores recent sleeps). Pagination via `nextToken`, `limit=25`. Retry/backoff on 429 and 5xx.
- Refresh the access token when expired; WHOOP rotates the refresh token — always persist the new one. If refresh fails, mark `whoop_connected=false` so the dashboard shows "Reconnect WHOOP".
- Single-process app; use a lock so the scheduled job and the manual button never run two syncs at once.
- Log one line per sync: start time, records per table, duration, errors.

### Config (env vars only, never in code or repo)

```
WHOOP_CLIENT_ID=
WHOOP_CLIENT_SECRET=
WHOOP_REDIRECT_URI=https://<app>.fly.dev/auth/whoop/callback
DASHBOARD_PASSWORD=
SESSION_SECRET=            # long random string
DATA_DIR=/data             # Fly volume mount; SQLite file lives here
SYNC_HOUR=9
SYNC_MINUTE=0
TZ=Asia/Kolkata
INITIAL_DAYS=365
```

Fail fast at startup with a clear message if a required var is missing.

### Deployment (Fly.io)

- `Dockerfile`: `python:3.12-slim`, non-root user, `uvicorn app.main:app --host 0.0.0.0 --port 8080`.
- `fly.toml`: internal port 8080, `[[mounts]] source="whoop_data" destination="/data"`, `auto_stop_machines = false` (scheduler must stay alive), `min_machines_running = 1`, HTTP health check on `/healthz`, force HTTPS.
- README must give me the exact commands: `fly launch --no-deploy`, `fly volumes create whoop_data --size 1`, `fly secrets set ...`, `fly deploy`, then what to set as the Redirect URL in the WHOOP developer dashboard (https://developer-dashboard.whoop.com).

### Dashboard changes (`dashboard_template.html` → `dashboard.html`)

- Replace the injected `DATA` constant with `fetch('/api/data')`; show a loading state; on 401 redirect to `/login`.
- Header: "Last synced X min ago", a **Sync now** button (disabled + spinner while `sync_running`), **Logout**.
- Remove the built-in `demoData()` sample generator (or keep it behind `?demo=1` only).
- Keep everything else (KPI tiles, recovery/HRV/sleep/strain charts, insights, workouts table).

### Local dev

- `cp .env.example .env`, fill in values, `uvicorn app.main:app --reload --port 8080`, with `WHOOP_REDIRECT_URI=http://localhost:8080/auth/whoop/callback` registered as a second redirect URL in the WHOOP app.
- Add a small `tests/` folder: auth (wrong password rejected, cookie works), `/api/data` requires login, sync against a mocked WHOOP API (httpx MockTransport) writes rows and handles pagination + token refresh.

## Rules

- **Never** commit `.env`, `*.db`, tokens or the client secret. Add them to `.gitignore` before the first commit and check `git status` before committing.
- Personal GitHub account, private repo. Do not use any work account or work tooling.
- Only external host the app talks to is `api.prod.whoop.com`.
- Prefer the standard library and the listed packages; don't add a frontend build step or a JS framework.
- When done: run the tests, show me the final tree, the `git` commands to create the private repo and push, and the Fly commands in order.
