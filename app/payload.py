"""Shapes SQLite rows into the JSON the dashboard and MCP tools consume."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db
from .config import Settings
from .strava_payload import personal_bests, strava_by_workout, strava_only_workouts, strava_status
from .weekly import build_weeks


def local_dt(iso, tz):
    """Parse a WHOOP UTC timestamp and shift it to the record's timezone offset (e.g. '+05:30')."""
    if not iso:
        return None
    base = iso.replace("Z", "").split(".")[0].split("+")[0]
    dt = datetime.strptime(base[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    try:
        sign = -1 if tz.startswith("-") else 1
        hh, mm = tz.lstrip("+-").split(":")
        return dt.astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    except Exception:
        return dt


def r1(x, nd=1):
    return None if x is None else round(float(x), nd)


def ms_h(x):
    return None if x is None else round(x / 3_600_000, 2)


def today_local(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.tz)).date()


# ------------------------------------------------------------------- days ---
def _sleep_totals(rows) -> dict:
    """Sum stage/awake/in-bed time across one cycle's main sleep and naps."""
    tot = {k: 0 for k in ("in_bed_ms", "awake_ms", "light_ms", "sws_ms", "rem_ms")}
    nap_asleep = 0
    any_data = False
    for s in rows:
        if s["in_bed_ms"] is None:
            continue
        any_data = True
        for k in tot:
            tot[k] += s[k] or 0
        if s["nap"]:
            nap_asleep += (s["in_bed_ms"] or 0) - (s["awake_ms"] or 0)
    if not any_data:
        return {}
    return {"in_bed": ms_h(tot["in_bed_ms"]), "awake": ms_h(tot["awake_ms"]),
            "sleep": ms_h(tot["in_bed_ms"] - tot["awake_ms"]), "nap": ms_h(nap_asleep),
            "light": ms_h(tot["light_ms"]), "sws": ms_h(tot["sws_ms"]), "rem": ms_h(tot["rem_ms"])}


def build_days(con) -> list[dict]:
    """One row per WHOOP cycle, labelled with the day you wake up into. Sleep totals include naps."""
    rec = {r["cycle_id"]: r for r in con.execute("SELECT * FROM recovery")}
    by_cycle: dict[int, list] = {}
    for s in con.execute("SELECT * FROM sleep ORDER BY start"):
        by_cycle.setdefault(s["cycle_id"], []).append(s)
    days = {}
    for c in con.execute("SELECT * FROM cycles ORDER BY start"):
        start = local_dt(c["start"], c["tz"] or "+00:00")
        day = (start + timedelta(hours=12)).date().isoformat()
        r = rec.get(c["id"])
        sleeps = by_cycle.get(c["id"], [])
        main = max((s for s in sleeps if not s["nap"]), key=lambda s: s["in_bed_ms"] or 0, default=None)
        row = {
            "d": day, "strain": r1(c["strain"]),
            "kcal": r1(c["kilojoule"] / 4.184, 0) if c["kilojoule"] else None,
            "rec": r1(r["recovery_score"], 0) if r else None, "hrv": r1(r["hrv"]) if r else None,
            "rhr": r1(r["rhr"], 0) if r else None, "spo2": r1(r["spo2"]) if r else None,
            "temp": r1(r["skin_temp"], 2) if r else None,
            "sleep": None, "in_bed": None, "awake": None, "nap": None, "light": None, "sws": None, "rem": None,
            "need": ms_h(main["need_ms"]) if main else None, "perf": r1(main["performance"], 0) if main else None,
            "eff": r1(main["efficiency"], 0) if main else None, "cons": r1(main["consistency"], 0) if main else None,
            "resp": r1(main["resp_rate"]) if main else None, "dist": main["disturbances"] if main else None,
            "bed": local_dt(main["start"], main["tz"] or "+00:00").strftime("%H:%M") if main and main["start"] else None,
            "wake": local_dt(main["end"], main["tz"] or "+00:00").strftime("%H:%M") if main and main["end"] else None,
        }
        row.update(_sleep_totals(sleeps))
        days[day] = row
    return sorted(days.values(), key=lambda x: x["d"])


# --------------------------------------------------------------- workouts ---
def categorize(sport: str, settings: Settings) -> str:
    """Match WHOOP sport names to run/strength/walk. A configured name also matches variants that
    start with it, so "weightlifting" covers WHOOP's "weightlifting_msk" (Strength Trainer)."""
    s = (sport or "").lower().replace("_", " ")
    for cat, names in (("run", settings.run_sports), ("strength", settings.strength_sports), ("walk", settings.walk_sports)):
        if any(s == n or s.startswith(n + " ") for n in names):
            return cat
    return "other"


def pace_str(min_per_km: float | None) -> str | None:
    if not min_per_km:
        return None
    m, sec = divmod(round(min_per_km * 60), 60)
    return f"{m}:{sec:02d}"


def build_workouts(con, settings: Settings, limit=600) -> list[dict]:
    out, strava = [], strava_by_workout(con)
    for w in con.execute("SELECT * FROM workouts ORDER BY start DESC LIMIT ?", (limit,)):
        st, en = local_dt(w["start"], w["tz"] or "+00:00"), local_dt(w["end"], w["tz"] or "+00:00")
        mins = round((en - st).total_seconds() / 60) if en else None
        km = r1(w["distance_m"] / 1000, 2) if w["distance_m"] else None
        cat = categorize(w["sport_name"], settings)
        pace = round(mins / km, 2) if cat == "run" and km and mins and km >= 0.5 else None  # min/km, runs only
        out.append({
            "d": st.date().isoformat(), "t": st.strftime("%H:%M"),
            "sport": (w["sport_name"] or "activity").replace("_", " "), "cat": cat,
            "min": mins, "strain": r1(w["strain"]), "avg_hr": w["avg_hr"], "max_hr": w["max_hr"],
            "kcal": r1(w["kilojoule"] / 4.184, 0) if w["kilojoule"] else None,
            "km": km, "pace": pace, "pace_str": pace_str(pace),
            "zones": [round((w[f"zone{i}_ms"] or 0) / 60000) for i in range(6)],
            "sources": ["WHOOP"] + (["Strava"] if w["id"] in strava else []),
            "strava": strava.get(w["id"]),  # splits, elevation, cadence, exercises when matched
            "start": w["start"],
        })
    # Activities only Strava knows about (e.g. logged on a watch) become rows too, so weekly totals include them.
    out.extend(strava_only_workouts(con, settings))
    out.sort(key=lambda x: x["start"] or "", reverse=True)
    return out


# ---------------------------------------------------------------- payload ---
def build_payload(con, settings: Settings) -> dict:
    days, workouts = build_days(con), build_workouts(con, settings)
    today = today_local(settings)
    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(),
            "days": days, "workouts": workouts, "weeks": build_weeks(days, workouts, today),
            "vo2max": db.get_metric_history(con, "vo2max"),
            "prs": personal_bests(con), **strava_status(con, settings),
            "goals": {"runs": settings.goal_runs, "strength": settings.goal_strength, "run_km": settings.goal_run_km},
            "max_hr": max_heart_rate(con, settings),
            "last_sync": db.get_meta(con, "last_sync"), "whoop_connected": db.whoop_connected(con)}


def max_heart_rate(con, settings: Settings) -> int | None:
    """MAX_HR from settings, else the highest heart rate WHOOP has recorded in any workout (WHOOP's zones are % of max HR)."""
    if settings.max_hr:
        return settings.max_hr
    row = con.execute("SELECT MAX(max_hr) FROM workouts").fetchone()
    return int(row[0]) if row and row[0] else None


def summarize(days: list[dict]) -> dict:
    """Averages over a list of day rows, used by the MCP summary tool."""
    def avg(key, nd=1):
        vals = [d[key] for d in days if d.get(key) is not None]
        return round(sum(vals) / len(vals), nd) if vals else None
    scored = [d for d in days if d.get("rec") is not None]
    return {
        "days": len(days), "from": days[0]["d"] if days else None, "to": days[-1]["d"] if days else None,
        "avg_recovery": avg("rec", 0), "avg_hrv_ms": avg("hrv"), "avg_rhr_bpm": avg("rhr"),
        "avg_sleep_h": avg("sleep"), "avg_in_bed_h": avg("in_bed"), "avg_nap_h": avg("nap"),
        "avg_sleep_need_h": avg("need"), "avg_strain": avg("strain"), "avg_kcal": avg("kcal", 0),
        "green_days": sum(1 for d in scored if d["rec"] >= 67),
        "yellow_days": sum(1 for d in scored if 34 <= d["rec"] < 67),
        "red_days": sum(1 for d in scored if d["rec"] < 34),
    }
