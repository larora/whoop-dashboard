"""MCP server exposing the synced WHOOP data to Claude. Mounted at /mcp, protected by a bearer token."""
import hmac
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from . import db, payload
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

    @mcp.tool()
    def get_summary(days: int = 30) -> dict:
        """Averages and green/yellow/red day counts over the last N days, plus the most recent day's numbers."""
        rows = days_window(days)
        summary = payload.summarize(rows)
        summary["latest"] = rows[-1] if rows else None
        return summary

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
        """Workouts in the last N days: sport, duration (min), strain, avg/max HR, km, HR-zone minutes [0-5]."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        con = db.connect(settings.db_path)
        try:
            rows = [w for w in payload.build_workouts(con) if w["d"] >= cutoff]
        finally:
            con.close()
        if sport:
            rows = [w for w in rows if sport.lower() in w["sport"].lower()]
        return rows

    @mcp.tool()
    def get_sync_status() -> dict:
        """When data was last pulled from WHOOP, whether a sync is running, and row counts per table."""
        con = db.connect(settings.db_path)
        try:
            return {"last_sync": db.get_meta(con, "last_sync"), "whoop_connected": db.whoop_connected(con),
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
