"""MCP server exposing the synced WHOOP data to Claude. Mounted at /mcp, protected by a bearer token."""
import hmac
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from . import db, payload
from .weekly import goal_progress
from .config import Settings


def _authorized(scope, token: str) -> bool:
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    auth = headers.get(b"authorization", b"").decode()
    return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)


class BearerAuth:
    """Minimal ASGI wrapper: 401 unless the Authorization header carries the MCP token.
    Also rewrites the path to "/" because the FastMCP app routes only its root and we attach it at /mcp."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if not _authorized(scope, self.token):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
            scope = {**scope, "path": "/", "raw_path": b"/"}
        await self.app(scope, receive, send)


class TokenInPath:
    """Accepts the MCP token as the last path segment (/mcp/<token>) for clients that can't send a
    custom Authorization header, e.g. the Claude.ai custom-connector form. Rewrites it into a Bearer
    header and hands off to BearerAuth, so the same constant-time check applies."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = scope.get("path_params", {}).get("token", "")
            headers = [(k, v) for k, v in scope.get("headers", []) if k != b"authorization"]
            headers.append((b"authorization", f"Bearer {supplied}".encode()))
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


def build_mcp(settings: Settings, runner) -> FastMCP:
    # Host-header (DNS-rebinding) checks are off: the endpoint is bearer-protected and served over HTTPS on Fly,
    # and the Fly hostname isn't known until deploy time.
    mcp = FastMCP("whoop", stateless_http=True, streamable_http_path="/", json_response=True,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
                  instructions="Personal WHOOP data: recovery, HRV, resting HR, sleep, strain and workouts, "
                               "one row per day. Dates are ISO (YYYY-MM-DD). Not medical advice.")

    def days_window(days: int) -> list[dict]:
        con = db.connect(settings.db_path)
        try:
            rows = payload.build_days(con)
        finally:
            con.close()
        return rows[-days:] if days > 0 else rows

    def full_payload() -> dict:
        con = db.connect(settings.db_path)
        try:
            return payload.build_payload(con, settings)
        finally:
            con.close()

    @mcp.tool()
    def get_summary(days: int = 30) -> dict:
        """Averages (recovery, HRV, RHR, sleep incl. naps, in-bed, strain, kcal) and green/yellow/red day counts
        over the last N days, the most recent day's numbers, and this week's progress against training goals."""
        rows = days_window(days)
        summary = payload.summarize(rows)
        summary["latest"] = rows[-1] if rows else None
        p = full_payload()
        summary["this_week"] = goal_progress(p["weeks"], p["goals"])
        summary["vo2max"] = p["vo2max"][-1] if p["vo2max"] else None
        return summary

    @mcp.tool()
    def get_weekly(weeks: int = 8) -> list[dict]:
        """Per-week rows (Monday start): kcal, avg strain, avg sleep/in-bed/awake/nap hours per night,
        hours exercised by category, run count/km/longest run, strength sessions. Last N weeks."""
        return full_payload()["weeks"][-weeks:]

    @mcp.tool()
    def get_daily(start: str | None = None, end: str | None = None, days: int = 30) -> list[dict]:
        """Per-day rows (recovery %, HRV ms, RHR bpm, sleep h, sleep stages, strain, kcal, bedtime).
        Pass start/end ISO dates for an explicit range, otherwise the last `days` days."""
        if start or end:
            start = start or "0000-01-01"
            end = end or date.today().isoformat()
            return [d for d in days_window(0) if start <= d["d"] <= end]
        return days_window(days)

    @mcp.tool()
    def get_workouts(days: int = 30, sport: str | None = None) -> list[dict]:
        """Workouts in the last N days: sport, category (run/strength/walk/other), duration (min), strain,
        avg/max HR, kcal, km, pace (min/km), HR-zone minutes [0-5]. `sport` filters by name or category."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        con = db.connect(settings.db_path)
        try:
            rows = [w for w in payload.build_workouts(con, settings) if w["d"] >= cutoff]
        finally:
            con.close()
        if sport:
            rows = [w for w in rows if sport.lower() in w["sport"].lower() or sport.lower() == w["cat"]]
        return rows

    @mcp.tool()
    def get_run_detail(date_iso: str) -> list[dict]:
        """Runs on a given date (YYYY-MM-DD) with Strava detail when available: per-km splits (pace, HR,
        elevation change), total elevation gain, cadence and best efforts within that run."""
        return [w for w in full_payload()["workouts"] if w["d"] == date_iso and w["cat"] == "run"]

    @mcp.tool()
    def get_personal_bests() -> list[dict]:
        """Fastest 1k / 1 mile / 5k / 10k / half-marathon etc. from Strava best efforts, with the date of each."""
        return full_payload()["prs"]

    @mcp.tool()
    def set_vo2max(value: float, date_iso: str | None = None) -> dict:
        """Record a VO2 max reading from the WHOOP app (the API doesn't expose it). Defaults to today."""
        d = date_iso or payload.today_local(settings).isoformat()
        con = db.connect(settings.db_path)
        try:
            db.set_metric(con, "vo2max", d, value)
            return {"vo2max": db.get_metric_history(con, "vo2max")}
        finally:
            con.close()

    @mcp.tool()
    def get_sync_status() -> dict:
        """When data was last pulled from WHOOP, whether a sync is running, and row counts per table."""
        con = db.connect(settings.db_path)
        try:
            return {"last_sync": db.get_meta(con, "last_sync"), "whoop_connected": db.whoop_connected(con),
                    "strava_connected": db.provider_connected(con, "strava"), "strava_last_sync": db.get_meta(con, "strava_last_sync"),
                    "sync_running": runner.running, "last_error": runner.last_error, "rows": db.table_counts(con)}
        finally:
            con.close()

    @mcp.tool()
    def trigger_sync() -> dict:
        """Start a background sync from the WHOOP API now. Returns immediately; poll get_sync_status."""
        return {"started": runner.start_background()}

    original = mcp.streamable_http_app
    mcp.streamable_http_app = lambda: BearerAuth(original(), settings.mcp_token)  # type: ignore[method-assign]
    return mcp
