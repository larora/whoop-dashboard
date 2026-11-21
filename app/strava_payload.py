"""Strava rows -> JSON merged into the workouts list and a personal-bests summary."""
from . import db

EFFORT_ORDER = ["1k", "1 mile", "5k", "10k", "15k", "20k", "Half-Marathon", "Marathon"]


def _pace(sec: float | None, meters: float | None) -> float | None:
    return round(sec / 60 / (meters / 1000), 2) if sec and meters and meters >= 200 else None


def pace_str(min_per_km: float | None) -> str | None:
    if not min_per_km:
        return None
    m, s = divmod(round(min_per_km * 60), 60)
    return f"{m}:{s:02d}"


def time_str(sec: float | None) -> str | None:
    if sec is None:
        return None
    sec = round(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def strava_by_workout(con) -> dict[str, dict]:
    """Map WHOOP workout id -> Strava enrichment (elevation, cadence, splits, best efforts)."""
    splits, efforts = {}, {}
    for r in con.execute("SELECT * FROM strava_splits ORDER BY activity_id, split"):
        p = _pace(r["moving_s"], r["distance_m"])
        splits.setdefault(r["activity_id"], []).append({
            "km": r["split"], "dist_m": round(r["distance_m"] or 0), "min": round((r["moving_s"] or 0) / 60, 2),
            "pace": p, "pace_str": pace_str(p), "hr": round(r["avg_hr"]) if r["avg_hr"] else None,
            "elev": round(r["elev_diff_m"]) if r["elev_diff_m"] is not None else None})
    for r in con.execute("SELECT * FROM strava_best_efforts"):
        efforts.setdefault(r["activity_id"], []).append({
            "name": r["name"], "sec": r["elapsed_s"], "time": time_str(r["elapsed_s"]),
            "pace_str": pace_str(_pace(r["elapsed_s"], r["distance_m"])), "pr_rank": r["pr_rank"]})
    out = {}
    for a in con.execute("SELECT * FROM strava_activities WHERE whoop_workout_id IS NOT NULL"):
        eff = sorted(efforts.get(a["id"], []), key=lambda e: EFFORT_ORDER.index(e["name"]) if e["name"] in EFFORT_ORDER else 99)
        out[a["whoop_workout_id"]] = {
            "id": a["id"], "name": a["name"], "elev_m": round(a["elev_gain_m"]) if a["elev_gain_m"] is not None else None,
            "cadence": round(a["avg_cadence"] * 2) if a["avg_cadence"] else None,  # Strava stores one-leg cadence
            "moving_min": round((a["moving_s"] or 0) / 60), "splits": splits.get(a["id"], []), "efforts": eff,
        }
    return out


def personal_bests(con) -> list[dict]:
    """Fastest time per standard distance across all stored best efforts, with the run's date."""
    rows = con.execute("""SELECT e.name, e.distance_m, e.elapsed_s, a.start_local, a.id AS activity_id
                          FROM strava_best_efforts e JOIN strava_activities a ON a.id = e.activity_id""").fetchall()
    best: dict[str, dict] = {}
    for r in rows:
        if r["name"] not in EFFORT_ORDER or r["elapsed_s"] is None:
            continue
        cur = best.get(r["name"])
        if cur is None or r["elapsed_s"] < cur["sec"]:
            best[r["name"]] = {"name": r["name"], "sec": r["elapsed_s"], "time": time_str(r["elapsed_s"]),
                               "pace_str": pace_str(_pace(r["elapsed_s"], r["distance_m"])),
                               "d": (r["start_local"] or "")[:10] or None, "activity_id": r["activity_id"]}
    return [best[n] for n in EFFORT_ORDER if n in best]


def unmatched_runs(con, limit=20) -> list[dict]:
    """Strava runs with no WHOOP counterpart (e.g. logged on a watch), so they're still visible."""
    return [{"id": a["id"], "d": (a["start_local"] or "")[:10], "name": a["name"], "km": round((a["distance_m"] or 0) / 1000, 2),
             "min": round((a["moving_s"] or 0) / 60), "elev_m": round(a["elev_gain_m"] or 0)}
            for a in con.execute("SELECT * FROM strava_activities WHERE whoop_workout_id IS NULL AND sport_type IN ('Run','TrailRun','VirtualRun') ORDER BY start DESC LIMIT ?", (limit,))]


def strava_status(con, settings) -> dict:
    return {"strava_enabled": settings.strava_enabled, "strava_connected": db.provider_connected(con, "strava"),
            "strava_last_sync": db.get_meta(con, "strava_last_sync")}
