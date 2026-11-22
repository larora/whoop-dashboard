"""Strava API client: OAuth, activity list, per-run splits and best efforts, matched to WHOOP workouts.

WHOOP pushes workouts to Strava, so every Strava run also exists as a WHOOP workout. We keep Strava for
what WHOOP lacks (splits, elevation, cadence, best efforts) and link each activity to the WHOOP workout
that started within a few minutes of it.
"""
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from . import db
from .config import Settings
from .exercises import parse_description

log = logging.getLogger("strava")

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
SCOPE = "activity:read_all"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
STRENGTH_TYPES = {"WeightTraining", "Workout", "Crossfit", "HighIntensityIntervalTraining"}
DETAIL_TYPES = RUN_TYPES | STRENGTH_TYPES  # activities worth a detail call (splits / exercise description)
MATCH_WINDOW_S = 300  # WHOOP and Strava start times for the same run are usually within a minute
# Strava allows 100 requests per 15 min (200 once an app is approved) and 1000/day. Stay under the lower
# limit per pass; whatever is left is fetched on the next pass (every 15 min while anything is pending).
DETAIL_BUDGET = 80
STREAM_KEYS = "time,heartrate,distance,velocity_smooth,altitude,cadence,grade_smooth"


class StravaError(Exception):
    pass


class StravaNotConnected(StravaError):
    pass


class StravaRateLimited(StravaError):
    """429 from Strava: stop this pass, keep what was stored, try again later."""


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class StravaClient:
    def __init__(self, settings: Settings, con, transport: httpx.BaseTransport | None = None):
        self.settings, self.con = settings, con
        self.http = httpx.Client(timeout=30, transport=transport, headers={"User-Agent": "whoop-personal-dashboard/1.0"})

    # OAuth ---------------------------------------------------------------
    def auth_url(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        params = {"client_id": self.settings.strava_client_id, "response_type": "code", "approval_prompt": "auto",
                  "redirect_uri": self.settings.strava_redirect_uri, "scope": SCOPE, "state": state}
        return f"{AUTH_URL}?{urlencode(params)}", state

    def exchange_code(self, code: str):
        tok = self._request("POST", TOKEN_URL, data={"client_id": self.settings.strava_client_id,
                                                      "client_secret": self.settings.strava_client_secret,
                                                      "code": code, "grant_type": "authorization_code"})
        db.save_provider_tokens(self.con, "strava", tok)

    def access_token(self) -> str:
        tok = db.get_provider_tokens(self.con, "strava")
        if not tok:
            raise StravaNotConnected("Strava is not connected")
        if time.time() < tok["expires_at"] - 60:
            return tok["access_token"]
        try:
            new = self._request("POST", TOKEN_URL, data={"client_id": self.settings.strava_client_id,
                                                          "client_secret": self.settings.strava_client_secret,
                                                          "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        except StravaError as e:
            db.clear_provider_tokens(self.con, "strava")
            raise StravaNotConnected(f"Strava token refresh failed: {e}") from None
        db.save_provider_tokens(self.con, "strava", new, previous=tok)
        return new["access_token"]

    # HTTP ----------------------------------------------------------------
    def _request(self, method, url, *, data=None, params=None, auth=False):
        for attempt in range(5):
            headers = {"Authorization": f"Bearer {self.access_token()}"} if auth else {}
            try:
                r = self.http.request(method, url, data=data, params=params, headers=headers)
            except httpx.TransportError as e:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise StravaError(f"Network error: {e}") from None
            if r.status_code == 429:
                raise StravaRateLimited("Strava rate limit reached (15-minute window)")
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401 and auth:
                db.clear_provider_tokens(self.con, "strava")
                raise StravaNotConnected("Strava rejected the access token (401)")
            if r.status_code >= 400:
                raise StravaError(f"{method} {url.split('?')[0]} -> HTTP {r.status_code}: {r.text[:200]}")
            return r.json() if r.content else {}
        raise StravaError("Gave up after repeated rate-limit/server errors")

    def list_activities(self, after: datetime) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._request("GET", f"{API}/athlete/activities", auth=True,
                                  params={"after": int(after.timestamp()), "per_page": 100, "page": page})
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def activity_detail(self, activity_id: int) -> dict:
        return self._request("GET", f"{API}/activities/{activity_id}", auth=True, params={"include_all_efforts": "false"})

    def activity_streams(self, activity_id: int) -> dict | None:
        """Second-by-second streams keyed by type, or None when Strava has none for this activity (404)."""
        try:
            return self._request("GET", f"{API}/activities/{activity_id}/streams", auth=True,
                                 params={"keys": STREAM_KEYS, "key_by_type": "true"})
        except StravaError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def close(self):
        self.http.close()


# ------------------------------------------------------------------- sync ---
def match_whoop_workout(con, start_iso: str) -> str | None:
    """Return the WHOOP workout id whose start is closest to `start_iso` within MATCH_WINDOW_S, else None."""
    st = _parse(start_iso)
    lo, hi = (st - timedelta(seconds=MATCH_WINDOW_S)).isoformat(), (st + timedelta(seconds=MATCH_WINDOW_S)).isoformat()
    best, best_dt = None, None
    for w in con.execute("SELECT id, start FROM workouts WHERE start BETWEEN ? AND ?", (lo.replace("+00:00", ""), hi.replace("+00:00", "Z"))):
        dt = abs((_parse(w["start"]) - st).total_seconds())
        if best_dt is None or dt < best_dt:
            best, best_dt = w["id"], dt
    return best


def _store_activity(con, a: dict):
    con.execute(
        """INSERT INTO strava_activities (id, start, start_local, name, sport_type, distance_m, moving_s, elapsed_s, elev_gain_m,
           avg_hr, max_hr, avg_cadence, avg_speed, whoop_workout_id, updated_at, raw)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, distance_m=excluded.distance_m, moving_s=excluded.moving_s,
           elapsed_s=excluded.elapsed_s, elev_gain_m=excluded.elev_gain_m, avg_hr=excluded.avg_hr, max_hr=excluded.max_hr,
           avg_cadence=excluded.avg_cadence, avg_speed=excluded.avg_speed, whoop_workout_id=excluded.whoop_workout_id,
           updated_at=excluded.updated_at, raw=excluded.raw""",
        (a["id"], a.get("start_date"), a.get("start_date_local"), a.get("name"), a.get("sport_type") or a.get("type"),
         a.get("distance"), a.get("moving_time"), a.get("elapsed_time"), a.get("total_elevation_gain"),
         a.get("average_heartrate"), a.get("max_heartrate"), a.get("average_cadence"), a.get("average_speed"),
         match_whoop_workout(con, a["start_date"]) if a.get("start_date") else None,
         datetime.now(timezone.utc).isoformat(), json.dumps({k: v for k, v in a.items() if k not in ("map", "segment_efforts", "laps")})))


def _store_detail(con, d: dict):
    aid = d["id"]
    # WHOOP's Strength Trainer writes the exercise list into the description; keep the text and a parsed copy.
    con.execute("UPDATE strava_activities SET description=? WHERE id=?", (d.get("description"), aid))
    exercises, _notes = parse_description(d.get("description"))
    con.execute("DELETE FROM strava_exercises WHERE activity_id=?", (aid,))
    con.executemany("INSERT INTO strava_exercises VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(aid, i, e["exercise"], e["sets"], e["reps"], e["reps_list"], e["weight_kg"], e["seconds"], e["volume_kg"], e["raw"])
                     for i, e in enumerate(exercises)])
    con.execute("DELETE FROM strava_splits WHERE activity_id=?", (aid,))
    con.executemany("INSERT INTO strava_splits VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(aid, s.get("split"), s.get("distance"), s.get("elapsed_time"), s.get("moving_time"),
                      s.get("elevation_difference"), s.get("average_speed"), s.get("average_heartrate"))
                     for s in d.get("splits_metric") or []])
    con.execute("DELETE FROM strava_best_efforts WHERE activity_id=?", (aid,))
    con.executemany("INSERT INTO strava_best_efforts VALUES (?, ?, ?, ?, ?, ?)",
                    [(aid, e.get("name"), e.get("distance"), e.get("elapsed_time"), e.get("start_date"), e.get("pr_rank"))
                     for e in d.get("best_efforts") or []])
    con.execute("UPDATE strava_activities SET detail_fetched=1 WHERE id=?", (aid,))


def _store_streams(con, aid: int, streams: dict | None):
    if not streams:
        con.execute("UPDATE strava_activities SET streams_fetched=-1 WHERE id=?", (aid,))
        return
    col = {"time": "time", "heartrate": "heartrate", "distance": "distance", "velocity_smooth": "velocity",
           "altitude": "altitude", "cadence": "cadence", "grade_smooth": "grade"}
    vals = {c: json.dumps(streams[k]["data"]) if k in streams else None for k, c in col.items()}
    n = len(streams["time"]["data"]) if "time" in streams else max((len(v["data"]) for v in streams.values()), default=0)
    con.execute("""INSERT OR REPLACE INTO strava_streams (activity_id, n, time, heartrate, distance, velocity, altitude, cadence, grade, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aid, n, vals["time"], vals["heartrate"], vals["distance"], vals["velocity"], vals["altitude"], vals["cadence"], vals["grade"],
                 datetime.now(timezone.utc).isoformat()))
    con.execute("UPDATE strava_activities SET streams_fetched=1 WHERE id=?", (aid,))


def pending_details(con) -> int:
    """Activities still owed an API call: detail (runs/strength) or streams (every activity)."""
    marks = ", ".join("?" for _ in DETAIL_TYPES)
    return con.execute(f"SELECT COUNT(*) FROM strava_activities WHERE (detail_fetched=0 AND sport_type IN ({marks})) OR streams_fetched=0",
                       tuple(DETAIL_TYPES)).fetchone()[0]


def sync_strava(con, settings: Settings, transport=None, details_only: bool = False) -> dict:
    """Pull activities since the last Strava sync (minus 7 days), then details for up to DETAIL_BUDGET
    runs/strength sessions that lack them. A 429 ends the pass early without being an error; the caller
    re-runs with details_only=True after the rate-limit window."""
    client = StravaClient(settings, con, transport)
    fetched, listed, limited = 0, 0, False
    try:
        if not details_only:
            last = db.get_meta(con, "strava_last_sync")
            after = (datetime.fromisoformat(last) - timedelta(days=7)) if last else datetime.now(timezone.utc) - timedelta(days=settings.initial_days)
            acts = client.list_activities(after)
            for a in acts:
                _store_activity(con, a)
            con.commit()
            listed = len(acts)
            db.set_meta(con, "strava_last_sync", datetime.now(timezone.utc).isoformat())
        marks = ", ".join("?" for _ in DETAIL_TYPES)
        rows = con.execute(f"SELECT id FROM strava_activities WHERE detail_fetched=0 AND sport_type IN ({marks}) ORDER BY start DESC LIMIT ?",
                           (*DETAIL_TYPES, DETAIL_BUDGET)).fetchall()
        for row in rows:
            try:
                _store_detail(con, client.activity_detail(row["id"]))
            except StravaRateLimited:
                limited = True
                break
            con.commit()
            fetched += 1
        # Streams (full HR / pace / altitude series) for every activity, newest first, with what's left of the budget.
        streams = 0
        if not limited:
            for row in con.execute("SELECT id FROM strava_activities WHERE streams_fetched=0 ORDER BY start DESC LIMIT ?",
                                   (max(0, DETAIL_BUDGET - fetched),)).fetchall():
                try:
                    _store_streams(con, row["id"], client.activity_streams(row["id"]))
                except StravaRateLimited:
                    limited = True
                    break
                con.commit()
                streams += 1
        if streams:
            from .analysis import recompute  # derived metrics (max HR, zones, VO2 max) from the new streams
            recompute(con, settings)
        left = pending_details(con)
        log.info("strava sync: %d listed, %d details, %d streams fetched, %d pending%s", listed, fetched, streams, left, ", rate limited" if limited else "")
        return {"strava_activities": listed, "strava_details": fetched, "strava_streams": streams, "strava_pending": left, "strava_rate_limited": limited}
    finally:
        client.close()
