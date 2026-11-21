"""WHOOP API client: OAuth exchange/refresh, paginated fetch with retry, and the sync job."""
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from . import db
from .config import Settings

log = logging.getLogger("whoop")

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer/v2"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:body_measurement"
PAGE_LIMIT = 25
REPULL_DAYS = 7  # WHOOP re-scores recent sleeps/cycles, so later syncs overlap by this much


class WhoopError(Exception):
    pass


class NotConnected(WhoopError):
    """Raised when there is no usable token; the dashboard should show 'Connect WHOOP'."""


# ---------------------------------------------------------------- mappers ---
def _g(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def map_cycle(r):
    s = r.get("score") or {}
    return {"id": r["id"], "start": r.get("start"), "end": r.get("end"), "tz": r.get("timezone_offset"),
            "score_state": r.get("score_state"), "strain": s.get("strain"), "kilojoule": s.get("kilojoule"),
            "avg_hr": s.get("average_heart_rate"), "max_hr": s.get("max_heart_rate"),
            "updated_at": r.get("updated_at"), "raw": json.dumps(r)}


def map_recovery(r):
    s = r.get("score") or {}
    return {"cycle_id": r["cycle_id"], "sleep_id": r.get("sleep_id"), "created_at": r.get("created_at"),
            "score_state": r.get("score_state"), "recovery_score": s.get("recovery_score"),
            "rhr": s.get("resting_heart_rate"), "hrv": s.get("hrv_rmssd_milli"),
            "spo2": s.get("spo2_percentage"), "skin_temp": s.get("skin_temp_celsius"),
            "calibrating": int(bool(s.get("user_calibrating"))), "updated_at": r.get("updated_at"),
            "raw": json.dumps(r)}


def map_sleep(r):
    st = _g(r, "score", "stage_summary") or {}
    nd = _g(r, "score", "sleep_needed") or {}
    s = r.get("score") or {}
    return {"id": r["id"], "cycle_id": r.get("cycle_id"), "start": r.get("start"), "end": r.get("end"),
            "tz": r.get("timezone_offset"), "nap": int(bool(r.get("nap"))), "score_state": r.get("score_state"),
            "in_bed_ms": st.get("total_in_bed_time_milli"), "awake_ms": st.get("total_awake_time_milli"),
            "light_ms": st.get("total_light_sleep_time_milli"), "sws_ms": st.get("total_slow_wave_sleep_time_milli"),
            "rem_ms": st.get("total_rem_sleep_time_milli"), "sleep_cycles": st.get("sleep_cycle_count"),
            "disturbances": st.get("disturbance_count"),
            "need_ms": sum(v for v in nd.values() if isinstance(v, (int, float))) if nd else None,
            "resp_rate": s.get("respiratory_rate"), "performance": s.get("sleep_performance_percentage"),
            "consistency": s.get("sleep_consistency_percentage"), "efficiency": s.get("sleep_efficiency_percentage"),
            "updated_at": r.get("updated_at"), "raw": json.dumps(r)}


def map_workout(r):
    s = r.get("score") or {}
    z = s.get("zone_durations") or {}
    zones = {f"zone{i}_ms": z.get(f"zone_{n}_milli") for i, n in enumerate(["zero", "one", "two", "three", "four", "five"])}
    return {"id": r["id"], "start": r.get("start"), "end": r.get("end"), "tz": r.get("timezone_offset"),
            "sport_name": r.get("sport_name"), "sport_id": r.get("sport_id"), "score_state": r.get("score_state"),
            "strain": s.get("strain"), "avg_hr": s.get("average_heart_rate"), "max_hr": s.get("max_heart_rate"),
            "kilojoule": s.get("kilojoule"), "distance_m": s.get("distance_meter"), **zones,
            "updated_at": r.get("updated_at"), "raw": json.dumps(r)}


# table -> (api path, primary key, mapper)
ENDPOINTS = {
    "cycles": ("/cycle", "id", map_cycle),
    "recovery": ("/recovery", "cycle_id", map_recovery),
    "sleep": ("/activity/sleep", "id", map_sleep),
    "workouts": ("/activity/workout", "id", map_workout),
}


# ----------------------------------------------------------------- client ---
class WhoopClient:
    """Thin httpx wrapper. `transport` is injectable so tests can mock the API."""

    def __init__(self, settings: Settings, con, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.con = con
        self.http = httpx.Client(timeout=30, transport=transport,
                                 headers={"User-Agent": "whoop-personal-dashboard/1.0", "Accept": "application/json"})

    # OAuth ---------------------------------------------------------------
    def auth_url(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(16)  # WHOOP requires >= 8 chars
        params = {"response_type": "code", "client_id": self.settings.whoop_client_id,
                  "redirect_uri": self.settings.whoop_redirect_uri, "scope": SCOPES, "state": state}
        return f"{AUTH_URL}?{urlencode(params)}", state

    def exchange_code(self, code: str):
        tok = self._request("POST", TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "client_id": self.settings.whoop_client_id,
            "client_secret": self.settings.whoop_client_secret, "redirect_uri": self.settings.whoop_redirect_uri})
        if "refresh_token" not in tok:
            log.warning("No refresh token returned - check the 'offline' scope is enabled for the WHOOP app")
        db.save_tokens(self.con, tok)

    def access_token(self) -> str:
        tok = db.get_tokens(self.con)
        if not tok:
            raise NotConnected("WHOOP is not connected")
        if time.time() < tok["expires_at"]:
            return tok["access_token"]
        if not tok.get("refresh_token"):
            db.clear_tokens(self.con)
            raise NotConnected("Access token expired and no refresh token stored")
        try:
            new = self._request("POST", TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "scope": "offline",
                "client_id": self.settings.whoop_client_id, "client_secret": self.settings.whoop_client_secret})
        except WhoopError as e:
            db.clear_tokens(self.con)
            raise NotConnected(f"Token refresh failed: {e}") from None
        db.save_tokens(self.con, new, previous=tok)
        return new["access_token"]

    # HTTP ----------------------------------------------------------------
    def _request(self, method, url, *, data=None, params=None, headers=None) -> dict:
        """Retry with backoff on 429/5xx and transient network errors."""
        for attempt in range(6):
            try:
                r = self.http.request(method, url, data=data, params=params, headers=headers)
            except httpx.TransportError as e:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise WhoopError(f"Network error: {e}") from None
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            if r.status_code == 401 and url != TOKEN_URL:
                db.clear_tokens(self.con)
                raise NotConnected("WHOOP rejected the access token (401)")
            if r.status_code >= 400:
                raise WhoopError(f"{method} {url.split('?')[0]} -> HTTP {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else {}
        raise WhoopError("Gave up after repeated rate-limit/server errors")

    def fetch_all(self, path: str, start_iso: str) -> list[dict]:
        params = {"limit": PAGE_LIMIT, "start": start_iso}
        records = []
        while True:
            resp = self._request("GET", f"{API}{path}", params=params,
                                 headers={"Authorization": f"Bearer {self.access_token()}"})
            records.extend(resp.get("records") or [])
            nxt = resp.get("next_token") or resp.get("nextToken")
            if not nxt:
                return records
            params["nextToken"] = nxt

    def close(self):
        self.http.close()


# ------------------------------------------------------------------- sync ---
class SyncRunner:
    """Owns the single-flight lock so the scheduler and the 'Sync now' button never overlap."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, strava_transport=None):
        self.settings = settings
        self.transport = transport
        self.strava_transport = strava_transport
        self._lock = threading.Lock()
        self.running = False
        self.last_error: str | None = None
        self.strava_retry_at: float | None = None  # when to fetch the next batch of Strava details

    def start_background(self) -> bool:
        """Kick off a sync thread; returns False if one is already running."""
        if self.running:
            return False
        threading.Thread(target=self.run, daemon=True, name="whoop-sync").start()
        return True

    def run_pending_strava(self):
        """Scheduler tick (every few minutes): continue fetching Strava details once the rate-limit window passed."""
        if self.strava_retry_at and time.time() >= self.strava_retry_at and not self.running:
            self.run(strava_details_only=True)

    def run(self, strava_details_only: bool = False) -> dict | None:
        if not self._lock.acquire(blocking=False):
            return None
        self.running = True
        started = time.time()
        con = db.connect(self.settings.db_path)
        counts, errors = {}, []
        try:
            if db.whoop_connected(con) and not strava_details_only:
                client = WhoopClient(self.settings, con, self.transport)
                try:
                    start_iso = self._window_start(con)
                    log.info("sync start from %s", start_iso)
                    for table, (path, pk, mapper) in ENDPOINTS.items():
                        recs = client.fetch_all(path, start_iso)
                        counts[table] = db.upsert(con, table, pk, [mapper(r) for r in recs])
                    db.set_meta(con, "last_sync", datetime.now(timezone.utc).isoformat())
                except WhoopError as e:
                    errors.append(f"WHOOP: {e}")
                finally:
                    client.close()
            if self.settings.strava_enabled and db.provider_connected(con, "strava"):
                from .strava import StravaError, sync_strava  # local import keeps whoop.py importable without strava
                try:
                    counts.update(sync_strava(con, self.settings, self.strava_transport, details_only=strava_details_only))
                    # More details to fetch? Come back after Strava's 15-minute window (sooner if we weren't limited).
                    self.strava_retry_at = (time.time() + (16 * 60 if counts.get("strava_rate_limited") else 60)) if counts.get("strava_pending") else None
                except StravaError as e:
                    errors.append(f"Strava: {e}")
            self.last_error = "; ".join(errors) or None
            if errors:
                log.error("sync finished with errors after %.1fs: %s", time.time() - started, self.last_error)
            else:
                log.info("sync done in %.1fs: %s", time.time() - started, counts)
            return None if errors and not counts else counts
        finally:
            con.close()
            self.running = False
            self._lock.release()

    def _window_start(self, con) -> str:
        last = db.get_meta(con, "last_sync")
        if last:
            start = datetime.fromisoformat(last) - timedelta(days=REPULL_DAYS)
        else:
            start = datetime.now(timezone.utc) - timedelta(days=self.settings.initial_days)
        return start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
