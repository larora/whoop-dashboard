"""SQLite helpers. Tables: cycles, recovery, sleep, workouts, meta, oauth_tokens."""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS manual_metrics (
    metric TEXT NOT NULL, d TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (metric, d));
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL, refresh_token TEXT, expires_at REAL NOT NULL, scope TEXT);
CREATE TABLE IF NOT EXISTS provider_tokens (
    provider TEXT PRIMARY KEY, access_token TEXT NOT NULL, refresh_token TEXT, expires_at REAL NOT NULL, scope TEXT);
CREATE TABLE IF NOT EXISTS strava_activities (
    id INTEGER PRIMARY KEY, start TEXT, start_local TEXT, name TEXT, sport_type TEXT,
    distance_m REAL, moving_s INTEGER, elapsed_s INTEGER, elev_gain_m REAL, avg_hr REAL, max_hr REAL,
    avg_cadence REAL, avg_speed REAL, whoop_workout_id TEXT, detail_fetched INTEGER DEFAULT 0, updated_at TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS strava_splits (
    activity_id INTEGER, split INTEGER, distance_m REAL, elapsed_s INTEGER, moving_s INTEGER,
    elev_diff_m REAL, avg_speed REAL, avg_hr REAL, PRIMARY KEY (activity_id, split));
CREATE TABLE IF NOT EXISTS strava_best_efforts (
    activity_id INTEGER, name TEXT, distance_m REAL, elapsed_s INTEGER, start_date TEXT, pr_rank INTEGER,
    PRIMARY KEY (activity_id, name));
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY, start TEXT, "end" TEXT, tz TEXT, score_state TEXT,
    strain REAL, kilojoule REAL, avg_hr REAL, max_hr REAL, updated_at TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS recovery (
    cycle_id INTEGER PRIMARY KEY, sleep_id TEXT, created_at TEXT, score_state TEXT,
    recovery_score REAL, rhr REAL, hrv REAL, spo2 REAL, skin_temp REAL, calibrating INTEGER,
    updated_at TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS sleep (
    id TEXT PRIMARY KEY, cycle_id INTEGER, start TEXT, "end" TEXT, tz TEXT, nap INTEGER, score_state TEXT,
    in_bed_ms INTEGER, awake_ms INTEGER, light_ms INTEGER, sws_ms INTEGER, rem_ms INTEGER,
    sleep_cycles INTEGER, disturbances INTEGER, need_ms INTEGER, resp_rate REAL, performance REAL,
    consistency REAL, efficiency REAL, updated_at TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY, start TEXT, "end" TEXT, tz TEXT, sport_name TEXT, sport_id INTEGER, score_state TEXT,
    strain REAL, avg_hr REAL, max_hr REAL, kilojoule REAL, distance_m REAL,
    zone0_ms INTEGER, zone1_ms INTEGER, zone2_ms INTEGER, zone3_ms INTEGER, zone4_ms INTEGER, zone5_ms INTEGER,
    updated_at TEXT, raw TEXT);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


# ------------------------------------------------------------------- meta ---
def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    con.commit()


# ----------------------------------------------------------------- tokens ---
def get_tokens(con) -> dict | None:
    row = con.execute("SELECT * FROM oauth_tokens WHERE id=1").fetchone()
    return dict(row) if row else None


def save_tokens(con, tok: dict, previous: dict | None = None):
    """Persist a token response. WHOOP rotates refresh tokens, so always store the newest one."""
    refresh = tok.get("refresh_token") or (previous or {}).get("refresh_token")
    expires_at = time.time() + int(tok.get("expires_in", 3600)) - 120  # 2-min safety margin
    con.execute(
        "INSERT OR REPLACE INTO oauth_tokens (id, access_token, refresh_token, expires_at, scope) VALUES (1, ?, ?, ?, ?)",
        (tok["access_token"], refresh, expires_at, tok.get("scope")),
    )
    set_meta(con, "whoop_connected", "1")


def clear_tokens(con):
    con.execute("DELETE FROM oauth_tokens")
    set_meta(con, "whoop_connected", "0")


def whoop_connected(con) -> bool:
    return get_meta(con, "whoop_connected") == "1" and get_tokens(con) is not None


# ----------------------------------------------------------------- upsert ---
def upsert(con, table: str, pk: str, rows: list[dict]) -> int:
    """INSERT OR REPLACE rows; adds any columns the API introduced since the schema was written."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    for c in cols:
        if c not in existing:
            con.execute(f'ALTER TABLE {table} ADD COLUMN "{c}"')
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(
        f"INSERT OR REPLACE INTO {table} ({quoted}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    con.commit()
    return len(rows)


def table_counts(con) -> dict:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("cycles", "recovery", "sleep", "workouts", "strava_activities", "strava_splits")}


# --------------------------------------------------------- manual metrics ---
def set_metric(con, metric: str, d: str, value: float):
    """Values the WHOOP API doesn't expose (e.g. VO2 max) that the user types in from the app."""
    con.execute("INSERT OR REPLACE INTO manual_metrics (metric, d, value) VALUES (?, ?, ?)", (metric, d, value))
    con.commit()


def get_metric_history(con, metric: str) -> list[dict]:
    return [{"d": r["d"], "v": r["value"]} for r in
            con.execute("SELECT d, value FROM manual_metrics WHERE metric=? ORDER BY d", (metric,))]


# -------------------------------------------------------- provider tokens ---
def get_provider_tokens(con, provider: str) -> dict | None:
    row = con.execute("SELECT * FROM provider_tokens WHERE provider=?", (provider,)).fetchone()
    return dict(row) if row else None


def save_provider_tokens(con, provider: str, tok: dict, previous: dict | None = None):
    refresh = tok.get("refresh_token") or (previous or {}).get("refresh_token")
    expires_at = tok.get("expires_at") or (time.time() + int(tok.get("expires_in", 3600)) - 120)
    con.execute("INSERT OR REPLACE INTO provider_tokens (provider, access_token, refresh_token, expires_at, scope) VALUES (?, ?, ?, ?, ?)",
                (provider, tok["access_token"], refresh, float(expires_at), tok.get("scope")))
    set_meta(con, f"{provider}_connected", "1")


def clear_provider_tokens(con, provider: str):
    con.execute("DELETE FROM provider_tokens WHERE provider=?", (provider,))
    set_meta(con, f"{provider}_connected", "0")


def provider_connected(con, provider: str) -> bool:
    return get_meta(con, f"{provider}_connected") == "1" and get_provider_tokens(con, provider) is not None
