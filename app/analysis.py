"""Derived fitness metrics from raw heart-rate / pace streams (Strava) and daily resting HR (WHOOP).

Everything here is computed from data we own, with methods that are explicit and replaceable:
  - Max HR: the highest heart rate *held for 30 s* in any activity (a single peak is often a strap artifact).
  - Zones: heart-rate reserve (Karvonen) — Z1..Z5 start at 50/60/70/80/90 % of (max − resting), Z0 below.
  - VO2 max: from steady running windows. Oxygen cost of the pace (ACSM running equation) divided by the
    fraction of heart-rate reserve being used (%HRR ≈ %VO2 reserve), median over windows and recent runs.
    Cross-checked with Daniels' VDOT from the fastest recent 5k / 10k best effort.
  - TRIMP (Banister): training load per activity from the HR stream.
"""
import json
import math
import statistics
from bisect import bisect_left
from collections import deque
from datetime import datetime, timedelta, timezone

from . import db
from .config import Settings

ZONE_FRACTIONS = (0.5, 0.6, 0.7, 0.8, 0.9)  # lower bound of Z1..Z5 as a fraction of heart-rate reserve
VO2_WINDOW_S, VO2_STEP_S, VO2_SKIP_S = 180, 60, 300  # 3-min windows every minute, skipping the first 5 min (HR lag)
VO2_MIN_V, VO2_HRR_LO, VO2_HRR_HI = 1.8, 0.55, 0.95  # m/s floor (≈9:15/km); usable %HRR band
RECENT_DAYS = 90  # window for the headline VO2 max and the max-HR search weight


# ------------------------------------------------------------ primitives ---
def sustained_max(hr: list, t: list, window_s: int) -> float | None:
    """Highest value v such that HR >= v for a continuous window_s seconds (sliding-window minimum)."""
    best, dq, i = None, deque(), 0
    for j in range(len(hr)):
        if hr[j] is None:
            dq.clear(); i = j + 1; continue
        while dq and hr[dq[-1]] >= hr[j]:
            dq.pop()
        dq.append(j)
        while t[j] - t[i] > window_s:  # shrink from the left to keep the window ≈ window_s
            i += 1
            if dq and dq[0] < i:
                dq.popleft()
        if t[j] - t[i] >= window_s - 1 and dq:
            best = max(best or 0, hr[dq[0]])
    return best


def zone_bounds(max_hr: float, rhr: float) -> list[int]:
    return [round(rhr + f * (max_hr - rhr)) for f in ZONE_FRACTIONS]


def zone_seconds(hr: list, t: list, bounds: list[int]) -> list[int]:
    out = [0] * 6
    for k in range(1, len(hr)):
        h = hr[k]
        if h is None:
            continue
        dt = min(t[k] - t[k - 1], 30)  # cap gaps (auto-pause) so they don't count as zone time
        z = sum(1 for b in bounds if h >= b)
        out[z] += dt
    return out


def trimp(hr: list, t: list, max_hr: float, rhr: float) -> float:
    """Banister TRIMP; male exponent (1.92), the only difference for female is 1.67 — about 10 % lower."""
    res = max_hr - rhr
    if res <= 0:
        return 0.0
    tot = 0.0
    for k in range(1, len(hr)):
        if hr[k] is None:
            continue
        frac = min(max((hr[k] - rhr) / res, 0), 1)
        tot += min(t[k] - t[k - 1], 30) / 60 * frac * 0.64 * math.exp(1.92 * frac)
    return round(tot, 1)


def vo2_windows(stream: dict) -> list[list]:
    """Steady running windows as [velocity m/min, mean HR, grade %]. Pace steadiness (each minute within ±15 %
    of the window mean) is required so that HR reflects the pace in the same window (HR lags pace by ~1 min)."""
    t, hr, dist, alt = stream.get("time"), stream.get("heartrate"), stream.get("distance"), stream.get("altitude")
    if not t or not hr or not dist or t[-1] < VO2_SKIP_S + VO2_WINDOW_S:
        return []
    out, start = [], VO2_SKIP_S
    while start + VO2_WINDOW_S <= t[-1]:
        i, j = bisect_left(t, start), bisect_left(t, start + VO2_WINDOW_S)
        start += VO2_STEP_S
        if j >= len(t) or t[j] - t[i] > VO2_WINDOW_S * 1.2:  # a pause inside the window
            continue
        dt, dd = t[j] - t[i], dist[j] - dist[i]
        v = dd / dt if dt > 0 else 0
        if v < VO2_MIN_V:
            continue
        thirds = []
        for q in range(3):
            a, b = bisect_left(t, t[i] + dt * q / 3), bisect_left(t, t[i] + dt * (q + 1) / 3)
            thirds.append((dist[b] - dist[a]) / max(t[b] - t[a], 1))
        hrs = [h for h in hr[i:j + 1] if h is not None]
        if min(thirds) / v < 0.85 or max(thirds) / v > 1.15 or len(hrs) < (j - i) * 0.8:
            continue
        grade = (alt[j] - alt[i]) / dd * 100 if alt and dd > 0 else 0.0
        out.append([round(v * 60, 1), round(statistics.fmean(hrs), 1), round(grade, 2)])
    return out


def vo2_from_windows(windows: list[list], max_hr: float, rhr: float) -> tuple[float | None, int]:
    """Median VO2 max estimate over usable windows, and how many windows were used."""
    res = max_hr - rhr
    ests = []
    for v, h, g in windows:
        frac = (h - rhr) / res if res > 0 else 0
        if not (VO2_HRR_LO <= frac <= VO2_HRR_HI) or abs(g) > 6:
            continue
        vo2 = 3.5 + 0.2 * v + 0.9 * v * max(g, 0) / 100  # ACSM running equation (ml/kg/min); downhill not credited
        ests.append((vo2 - 3.5) / frac + 3.5)
    return (round(statistics.median(ests), 1), len(ests)) if len(ests) >= 3 else (None, len(ests))


def vdot(distance_m: float, seconds: float) -> float | None:
    """Daniels & Gilbert VDOT from a race-like effort."""
    if not distance_m or not seconds or seconds < 60:
        return None
    t = seconds / 60
    v = distance_m / t
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    pct = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)
    return round(vo2 / pct, 1)


# ------------------------------------------------------------- pipeline ---
def load_stream(con, activity_id: int) -> dict | None:
    r = con.execute("SELECT * FROM strava_streams WHERE activity_id=?", (activity_id,)).fetchone()
    if not r:
        return None
    return {k: json.loads(r[k]) if r[k] else None for k in ("time", "heartrate", "distance", "velocity", "altitude", "cadence", "grade")}


def resting_hr(con, settings: Settings) -> float | None:
    if settings.resting_hr:
        return float(settings.resting_hr)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    row = con.execute("SELECT AVG(rhr) FROM recovery WHERE rhr IS NOT NULL AND created_at >= ?", (since,)).fetchone()
    if row and row[0]:
        return round(row[0], 1)
    row = con.execute("SELECT AVG(rhr) FROM recovery WHERE rhr IS NOT NULL").fetchone()
    return round(row[0], 1) if row and row[0] else None


def max_hr_info(con, settings: Settings) -> dict:
    """Max HR with provenance: setting override, else best 30-s sustained HR from streams, else WHOOP peaks."""
    if settings.max_hr:
        return {"value": settings.max_hr, "source": "setting"}
    r = con.execute("SELECT hr_30s, hr_60s, peak_hr, d, activity_id FROM activity_metrics WHERE hr_30s IS NOT NULL ORDER BY hr_30s DESC LIMIT 1").fetchone()
    if r:
        return {"value": round(r["hr_30s"]), "source": "stream", "held_60s": r["hr_60s"], "peak": r["peak_hr"], "d": r["d"], "activity_id": r["activity_id"]}
    peaks = [x[0] for x in con.execute("SELECT max_hr FROM workouts WHERE max_hr IS NOT NULL ORDER BY max_hr DESC")]
    if peaks:
        return {"value": round(peaks[max(0, int(len(peaks) * 0.05) - 1)]), "source": "whoop_peaks_p95", "peak": peaks[0]}
    return {"value": None, "source": "none"}


def recompute(con, settings: Settings, force: bool = False) -> int:
    """Stage 1: stream-derived facts per activity (peak, sustained HR, VO2 windows) for activities without them.
    Stage 2: parameter-dependent metrics (zones, VO2 max, TRIMP) whenever max HR / resting HR changed."""
    now = datetime.now(timezone.utc).isoformat()
    todo = con.execute("""SELECT a.id, a.whoop_workout_id, a.start_local, a.start, a.sport_type, a.elapsed_s FROM strava_activities a
                          JOIN strava_streams s ON s.activity_id = a.id
                          LEFT JOIN activity_metrics m ON m.activity_id = a.id WHERE m.activity_id IS NULL""" + ("" if not force else " OR 1=1")).fetchall()
    from .strava import RUN_TYPES
    for a in todo:
        st = load_stream(con, a["id"])
        t, hr = st.get("time") or [], st.get("heartrate") or []
        if not t or not hr or len(t) != len(hr):
            peak = h30 = h60 = None; windows = []
        else:
            peak, h30, h60 = max(h for h in hr if h is not None), sustained_max(hr, t, 30), sustained_max(hr, t, 60)
            windows = vo2_windows(st) if a["sport_type"] in RUN_TYPES else []
        con.execute("""INSERT OR REPLACE INTO activity_metrics (activity_id, whoop_workout_id, d, sport_type, duration_s, peak_hr, hr_30s, hr_60s, vo2_windows, computed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (a["id"], a["whoop_workout_id"], (a["start_local"] or a["start"] or "")[:10], a["sport_type"], t[-1] if t else a["elapsed_s"],
                     peak, h30, h60, json.dumps(windows), now))
    con.commit()
    mx, rhr = max_hr_info(con, settings)["value"], resting_hr(con, settings)
    if not mx or not rhr:
        return len(todo)
    params = f"{mx}|{rhr}|{','.join(map(str, ZONE_FRACTIONS))}"
    bounds = zone_bounds(mx, rhr)
    stale = con.execute("SELECT activity_id, vo2_windows FROM activity_metrics WHERE params IS NOT ? OR params IS NULL", (params,)).fetchall()
    for m in stale:
        st = load_stream(con, m["activity_id"])
        t, hr = (st or {}).get("time") or [], (st or {}).get("heartrate") or []
        ok = t and hr and len(t) == len(hr)
        zs = zone_seconds(hr, t, bounds) if ok else None
        tr = trimp(hr, t, mx, rhr) if ok else None
        est, n = vo2_from_windows(json.loads(m["vo2_windows"] or "[]"), mx, rhr)
        con.execute("UPDATE activity_metrics SET zone_s=?, trimp=?, vo2_est=?, vo2_n=?, params=?, computed_at=? WHERE activity_id=?",
                    (json.dumps(zs) if zs else None, tr, est, n, params, now, m["activity_id"]))
    con.commit()
    return len(todo)


# -------------------------------------------------------------- outputs ---
def metrics_by_activity(con) -> dict[int, dict]:
    out = {}
    for m in con.execute("SELECT * FROM activity_metrics"):
        out[m["activity_id"]] = {"peak_hr": m["peak_hr"], "hr_30s": m["hr_30s"], "trimp": m["trimp"], "vo2_est": m["vo2_est"],
                                 "zones": [round(s / 60) for s in json.loads(m["zone_s"])] if m["zone_s"] else None, "whoop_workout_id": m["whoop_workout_id"]}
    return out


def fitness_summary(con, settings: Settings) -> dict:
    """Max HR, resting HR, zone boundaries and VO2 max estimates, each with provenance."""
    mx, rhr = max_hr_info(con, settings), resting_hr(con, settings)
    out = {"max_hr": mx, "resting_hr": rhr, "zones": None, "vo2max": None}
    if mx["value"] and rhr:
        out["zones"] = {"model": "heart-rate reserve", "fractions": list(ZONE_FRACTIONS), "bounds": zone_bounds(mx["value"], rhr)}
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).date().isoformat()
    runs = [dict(r) for r in con.execute("SELECT d, vo2_est, vo2_n, activity_id FROM activity_metrics WHERE vo2_est IS NOT NULL ORDER BY d")]
    recent = [r for r in runs if r["d"] >= since] or runs[-8:]
    if recent:
        vals = [r["vo2_est"] for r in recent[-8:]]
        out["vo2max"] = {"estimate": round(statistics.median(vals), 1), "runs_used": len(vals), "from": recent[-8:][0]["d"], "to": recent[-1]["d"],
                         "per_run": [{"d": r["d"], "v": r["vo2_est"], "windows": r["vo2_n"], "activity_id": r["activity_id"]} for r in runs[-40:]],
                         "method": "ACSM pace cost ÷ %HRR, median of 3-min steady windows, median of last 8 runs"}
    q = """SELECT e.name, e.distance_m, e.elapsed_s, a.start_local FROM strava_best_efforts e JOIN strava_activities a ON a.id=e.activity_id
           WHERE e.name IN ('5k', '10k') AND substr(a.start_local, 1, 10) >= ? ORDER BY e.elapsed_s / e.distance_m LIMIT 1"""
    best = con.execute(q, (since,)).fetchone() or con.execute(q, ("0000",)).fetchone()  # recent, else all-time
    if best:
        out.setdefault("vo2max", {})["vdot"] = {"value": vdot(best["distance_m"], best["elapsed_s"]), "from": best["name"], "time_s": best["elapsed_s"], "d": (best["start_local"] or "")[:10]}
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    out["trimp_7d"] = round(con.execute("SELECT COALESCE(SUM(trimp), 0) FROM activity_metrics WHERE d >= ?", (week_ago,)).fetchone()[0])
    out["streams"] = {"with_streams": con.execute("SELECT COUNT(*) FROM strava_streams").fetchone()[0],
                      "pending": con.execute("SELECT COUNT(*) FROM strava_activities WHERE streams_fetched=0").fetchone()[0]}
    return out


def downsampled_stream(con, activity_id: int, step_s: int = 10) -> dict | None:
    """Stream thinned to one point per step_s seconds, for the MCP tool."""
    st = load_stream(con, activity_id)
    if not st or not st.get("time"):
        return None
    t = st["time"]; keep = []; nxt = 0
    for k, tk in enumerate(t):
        if tk >= nxt:
            keep.append(k); nxt = tk + step_s
    return {k: [v[i] for i in keep] if v else None for k, v in st.items()}
