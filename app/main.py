"""FastAPI app: dashboard, auth, WHOOP OAuth, sync trigger, scheduler and MCP mount."""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, payload
from .auth import Sessions, client_ip
from .config import Settings, load_settings
from .mcp_server import build_mcp
from .whoop import SyncRunner, WhoopClient, WhoopError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class MetricIn(BaseModel):
    value: float = Field(gt=0, lt=200)
    date: str | None = None  # ISO date; defaults to today


def create_app(settings: Settings | None = None, transport=None) -> FastAPI:
    """App factory so tests can pass their own settings and a mocked WHOOP transport."""
    settings = settings or load_settings()
    sessions = Sessions(settings)
    runner = SyncRunner(settings, transport=transport)
    mcp = build_mcp(settings, runner) if settings.mcp_token else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.connect(settings.db_path).close()  # create schema up front
        scheduler = start_scheduler(settings, runner)
        if mcp:
            async with mcp.session_manager.run():
                yield
        else:
            yield
        scheduler.shutdown(wait=False)

    app = FastAPI(title="WHOOP dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")  # JS only, no data
    app.state.settings, app.state.sessions, app.state.runner = settings, sessions, runner
    require_login = Depends(sessions.require)

    def connection():
        return db.connect(settings.db_path)

    # ---------------------------------------------------------------- auth --
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if sessions.is_authed(request):
            return RedirectResponse("/", status_code=303)
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, password: str = Form("")):
        ip = client_ip(request)
        if sessions.locked_out(ip):
            return TEMPLATES.TemplateResponse(request, "login.html",
                                              {"error": "Too many attempts. Try again in a minute."}, status_code=429)
        if not sessions.check_password(ip, password):
            return TEMPLATES.TemplateResponse(request, "login.html", {"error": "Wrong password."}, status_code=401)
        resp = RedirectResponse("/", status_code=303)
        sessions.write(resp, {"auth": True})
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        sessions.clear(resp)
        return resp

    # ----------------------------------------------------------- dashboard --
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        if not sessions.is_authed(request):
            return RedirectResponse("/login", status_code=303)
        con = connection()
        try:
            connected = db.whoop_connected(con)
        finally:
            con.close()
        return TEMPLATES.TemplateResponse(request, "dashboard.html", {"whoop_connected": connected})

    @app.get("/api/data", dependencies=[require_login])
    def api_data():
        con = connection()
        try:
            data = payload.build_payload(con, settings)
        finally:
            con.close()
        data["sync_running"] = runner.running
        data["sync_error"] = runner.last_error
        return JSONResponse(data)

    @app.post("/api/metrics/vo2max", dependencies=[require_login])
    def set_vo2max(body: MetricIn):
        d = body.date or payload.today_local(settings).isoformat()
        try:
            datetime.fromisoformat(d)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
        con = connection()
        try:
            db.set_metric(con, "vo2max", d, body.value)
            history = db.get_metric_history(con, "vo2max")
        finally:
            con.close()
        return {"vo2max": history}

    @app.post("/sync", dependencies=[require_login], status_code=202)
    def sync_now():
        started = runner.start_background()
        return {"started": started, "sync_running": True}

    # --------------------------------------------------------- WHOOP OAuth --
    @app.get("/auth/whoop", dependencies=[require_login])
    def auth_whoop(request: Request):
        con = connection()
        try:
            url, state = WhoopClient(settings, con, transport).auth_url()
        finally:
            con.close()
        resp = RedirectResponse(url, status_code=303)
        sessions.write(resp, {**sessions.read(request), "oauth_state": state})
        return resp

    @app.get("/auth/whoop/callback", dependencies=[require_login])
    def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        session = sessions.read(request)
        expected = session.pop("oauth_state", None)
        if error or not code or not expected or state != expected:
            log.warning("OAuth callback rejected: error=%s state_ok=%s", error, state == expected)
            return HTMLResponse("<p>WHOOP sign-in failed (state mismatch or denied). <a href='/'>Back</a></p>", status_code=400)
        con = connection()
        try:
            WhoopClient(settings, con, transport).exchange_code(code)
        except WhoopError as e:
            return HTMLResponse(f"<p>Token exchange failed: {e}. <a href='/'>Back</a></p>", status_code=502)
        finally:
            con.close()
        runner.start_background()
        resp = RedirectResponse("/", status_code=303)
        sessions.write(resp, session)
        return resp

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    if mcp:
        # add_route (not mount) so /mcp is served directly without a 307 to /mcp/
        app.add_route("/mcp", mcp.streamable_http_app(), methods=["GET", "POST", "DELETE"])
    return app


def start_scheduler(settings: Settings, runner: SyncRunner) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.tz)
    scheduler.add_job(runner.run, CronTrigger(hour=settings.sync_hour, minute=settings.sync_minute, timezone=settings.tz),
                      id="daily-sync", coalesce=True, max_instances=1)
    scheduler.start()
    log.info("scheduled daily sync at %02d:%02d %s", settings.sync_hour, settings.sync_minute, settings.tz)
    # Catch up if the last sync is stale (e.g. the machine was down at sync time).
    con = db.connect(settings.db_path)
    try:
        last, connected = db.get_meta(con, "last_sync"), db.whoop_connected(con)
    finally:
        con.close()
    stale = not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(hours=24)
    if connected and stale and os.environ.get("SKIP_STARTUP_SYNC") != "1":
        runner.start_background()
    return scheduler


def __getattr__(name):
    # `uvicorn app.main:app` builds the app lazily; importing this module in tests stays side-effect free.
    if name == "app":
        return create_app()
    raise AttributeError(name)
