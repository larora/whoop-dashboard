"""Environment-driven settings. Fails fast with a clear message when a required var is missing."""
import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI", "DASHBOARD_PASSWORD", "SESSION_SECRET"]


@dataclass(frozen=True)
class Settings:
    whoop_client_id: str
    whoop_client_secret: str
    whoop_redirect_uri: str
    dashboard_password: str
    session_secret: str
    data_dir: Path
    sync_hour: int
    sync_minute: int
    tz: str
    initial_days: int
    mcp_token: str | None  # MCP endpoint is disabled when unset
    goal_runs: int
    goal_strength: int
    goal_run_km: float
    run_sports: tuple[str, ...]
    strength_sports: tuple[str, ...]
    walk_sports: tuple[str, ...]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "whoop.db"

    @property
    def cookie_secure(self) -> bool:
        # Local dev uses http://localhost; everything else must be HTTPS.
        return self.whoop_redirect_uri.startswith("https://")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(v.strip().lower().replace("_", " ") for v in value.split(",") if v.strip())


def load_settings(env: dict | None = None) -> Settings:
    env = env if env is not None else os.environ
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}. See .env.example.")
    if len(env["SESSION_SECRET"]) < 32:
        raise SystemExit("SESSION_SECRET must be at least 32 characters (use: python3 -c 'import secrets; print(secrets.token_urlsafe(48))').")
    return Settings(
        whoop_client_id=env["WHOOP_CLIENT_ID"],
        whoop_client_secret=env["WHOOP_CLIENT_SECRET"],
        whoop_redirect_uri=env["WHOOP_REDIRECT_URI"],
        dashboard_password=env["DASHBOARD_PASSWORD"],
        session_secret=env["SESSION_SECRET"],
        data_dir=Path(env.get("DATA_DIR", "./data")).expanduser(),
        sync_hour=int(env.get("SYNC_HOUR", "9")),
        sync_minute=int(env.get("SYNC_MINUTE", "0")),
        tz=env.get("TZ", "Asia/Kolkata"),
        initial_days=int(env.get("INITIAL_DAYS", "365")),
        mcp_token=env.get("MCP_TOKEN") or None,
        goal_runs=int(env.get("GOAL_RUNS", "4")),
        goal_strength=int(env.get("GOAL_STRENGTH", "3")),
        goal_run_km=float(env.get("GOAL_RUN_KM", "20")),
        # WHOOP sport names as they appear in the API (underscores or spaces both match).
        run_sports=_csv(env.get("RUN_SPORTS", "running,treadmill,trail running,track running")),
        strength_sports=_csv(env.get("STRENGTH_SPORTS", "weightlifting,strength trainer,strength workout,functional fitness,powerlifting,crossfit")),
        walk_sports=_csv(env.get("WALK_SPORTS", "walking,hiking")),
    )
