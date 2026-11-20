# WHOOP Dashboard + MCP

A self-hosted web app that pulls my WHOOP wearable data every morning, stores it, and shows it on a password-protected dashboard. It also exposes the same data to Claude through an MCP server, so I can ask questions like "how did my sleep compare to last month?" in plain language.

Built as a side project to learn three things end to end: working with a real OAuth API, deploying a small always-on service, and building an MCP server that an AI assistant can use.

> **Screenshot:** _(add `docs/dashboard.png` here; the sample-data mode means no real health data needs to appear)_

## What it does

- **Daily sync.** At 9:00 every morning the app pulls recovery, sleep, strain and workouts from the WHOOP API into a local SQLite database. A **Sync now** button does the same on demand.
- **Dashboard.** Recovery, HRV and resting heart rate trends, sleep stages against sleep need, daily strain, how strain affects next-day recovery, recovery by weekday, sleep quality, and a workouts table. Range selector from 30 days to all time. Plus a short list of auto-generated observations from the data ("7-day HRV is 8% below your 30-day baseline").
- **Ask Claude about it.** An MCP endpoint with five tools: summary over N days, per-day rows, workouts, sync status, and trigger a sync. Connect it to Claude (desktop, web or Claude Code) and the data becomes something you can converse with.
- **Private by design.** Single-password login, signed session cookie, lockout after repeated failures. The MCP endpoint uses its own bearer token. The only external host the app ever contacts is `api.prod.whoop.com`. Nothing is sent anywhere else.

## How it's built

```
Browser ──login──▶ FastAPI app ──▶ SQLite (one file on a persistent volume)
                      │  ▲
Claude ──MCP/HTTP─────┘  │  scheduler (APScheduler, daily cron)
                         │
                   WHOOP API (OAuth 2.0, paginated REST)
```

| Piece | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, uvicorn | Small, typed, async-ready; one process does web + scheduler + MCP |
| Storage | SQLite on a Fly.io volume | Single user, a few MB a year; zero ops |
| Frontend | One HTML file, vanilla JS, inline SVG charts | No build step; the whole UI is readable in one sitting |
| Scheduling | APScheduler in-process | No separate worker or cron host to keep alive |
| MCP | Official `mcp` Python SDK, streamable HTTP | Mounts into the same FastAPI app; bearer-token gated |
| Hosting | Fly.io, single shared-CPU machine | Always-on for the scheduler; ~$2–3/month |

About 1,100 lines of Python and HTML in total, including tests. No JavaScript framework, no ORM, no message queue.

### Things worth noting in the code

- **Token rotation.** WHOOP rotates the refresh token on every refresh. The client always persists the newest one, and if a refresh fails it flips the app to a "Reconnect WHOOP" state instead of silently failing every morning.
- **Overlapping sync window.** WHOOP re-scores recent sleeps after the fact, so each sync re-pulls the last 7 days rather than only new records. Upserts make this idempotent.
- **Single-flight sync.** A lock ensures the cron job and the Sync now button can never run two syncs at once.
- **Tests without the real API.** The WHOOP API is mocked with `httpx.MockTransport`, so the suite covers pagination, token refresh, lockout, cookie tampering and MCP auth in half a second, offline.
- **Sample-data mode.** `scripts/seed_demo.py` fills the database with 180 days of plausible data so the dashboard can be previewed, demoed or screenshotted without any real health data.

## Run it yourself

If you have a WHOOP, you can run this for your own data. It takes about 15 minutes; nothing about it is specific to me.

1. Create a (free) WHOOP developer app at https://developer-dashboard.whoop.com to get a Client ID and Secret.
2. Clone this repo, copy `.env.example` to `.env`, fill in the values.
3. `uv pip install -r requirements.txt` (or plain `pip`), then `uvicorn app.main:app --port 8080`.
4. Open http://localhost:8080, sign in, click **Connect WHOOP**.

To keep it running in the cloud, [SETUP.md](SETUP.md) has the exact Fly.io commands, how to point Claude at the MCP endpoint, and troubleshooting. Deploying takes another 10 minutes.

If you don't have a WHOOP, `python scripts/seed_demo.py` gives you a dashboard full of sample data to click around in.

## Project layout

```
app/
  main.py        routes, login, OAuth callback, scheduler startup, MCP mount
  auth.py        password check, signed cookie, lockout
  whoop.py       WHOOP API client and the sync job
  db.py          SQLite schema and helpers
  payload.py     turns rows into the JSON the dashboard and MCP tools use
  mcp_server.py  the five MCP tools and the bearer-token gate
  templates/     dashboard.html, login.html
scripts/seed_demo.py   sample data generator
tests/                 15 tests, mocked WHOOP API
Dockerfile, fly.toml   deployment
SETUP.md               setup, deploy and operations guide
```

## What I'd do next

- Body measurements and skin temperature trends (the scope is already requested, the charts aren't built).
- Weekly email or Slack digest generated from the same summary the MCP tool returns.
- Multi-user support, if anyone other than me wanted to use one deployment.

## Privacy note

This app handles personal health data. It's designed for one person running their own instance: your data stays in your database, on your server, behind your password. Please don't point a shared deployment at other people's WHOOP accounts without thinking through consent and access.

---

Built with Python 3.12, FastAPI, SQLite and the MCP Python SDK. Developed with help from Claude Code.
