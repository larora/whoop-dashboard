"""Shapes SQLite rows into the JSON the dashboard and MCP tools consume."""
from datetime import datetime, timedelta, timezone

from . import db


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


def build_days(con) -> list[dict]:
    """One row per WHOOP cycle, labelled with the day you wake up into."""
    rec = {r["cycle_id"]: r for r in con.execute("SELECT * FROM recovery")}
    sleeps = {}
    for s in con.execute("SELECT * FROM sleep WHERE nap=0"):
        cur = sleeps.get(s["cycle_id"])
        if cur is None or (s["in_bed_ms"] or 0) > (cur["in_bed_ms"] or 0):
            sleeps[s["cycle_id"]] = s
    days = {}
    for c in con.execute("SELECT * FROM cycles ORDER BY start"):
        start = local_dt(c["start"], c["tz"] or "+00:00")
        day = (start + timedelta(hours=12)).date().isoformat()
        r, s = rec.get(c["id"]), sleeps.get(c["id"])
        asleep = (s["in_bed_ms"] or 0) - (s["awake_ms"] or 0) if s and s["in_bed_ms"] is not None else None
        days[day] = {
            "d": day, "strain": r1(c["strain"]),
            "kcal": r1(c["kilojoule"] / 4.184, 0) if c["kilojoule"] else None,
            "rec": r1(r["recovery_score"], 0) if r else None, "hrv": r1(r["hrv"]) if r else None,
            "rhr": r1(r["rhr"], 0) if r else None, "spo2": r1(r["spo2"]) if r else None,
            "temp": r1(r["skin_temp"], 2) if r else None,
            "sleep": ms_h(asleep), "light": ms_h(s["light_ms"]) if s else None,
            "sws": ms_h(s["sws_ms"]) if s else None, "rem": ms_h(s["rem_ms"]) if s else None,
            "need": ms_h(s["need_ms"]) if s else None, "perf": r1(s["performance"], 0) if s else None,
            "eff": r1(s["efficiency"], 0) if s else None, "cons": r1(s["consistency"], 0) if s else None,
            "resp": r1(s["resp_rate"]) if s else None, "dist": s["disturbances"] if s else None,
            "bed": local_dt(s["start"], s["tz"] or "+00:00").strftime("%H:%M") if s and s["start"] else None,
        }
    return sorted(days.values(), key=lambda x: x["d"])


def build_workouts(con, limit=400) -> list[dict]:
    out = []
    for w in con.execute("SELECT * FROM workouts ORDER BY start DESC LIMIT ?", (limit,)):
        st, en = local_dt(w["start"], w["tz"] or "+00:00"), local_dt(w["end"], w["tz"] or "+00:00")
        out.append({
            "d": st.date().isoformat(), "t": st.strftime("%H:%M"),
            "sport": (w["sport_name"] or "activity").replace("_", " "),
            "min": round((en - st).total_seconds() / 60) if en else None, "strain": r1(w["strain"]),
            "avg_hr": w["avg_hr"], "max_hr": w["max_hr"],
            "km": r1(w["distance_m"] / 1000, 2) if w["distance_m"] else None,
            "zones": [round((w[f"zone{i}_ms"] or 0) / 60000) for i in range(6)],
        })
    return out


def build_payload(con) -> dict:
    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "days": build_days(con),
            "workouts": build_workouts(con), "last_sync": db.get_meta(con, "last_sync"),
            "whoop_connected": db.whoop_connected(con)}


def summarize(days: list[dict]) -> dict:
    """Averages over a list of day rows, used by the MCP summary tool."""
    def avg(key, nd=1):
        vals = [d[key] for d in days if d.get(key) is not None]
        return round(sum(vals) / len(vals), nd) if vals else None
    scored = [d for d in days if d.get("rec") is not None]
    return {
        "days": len(days), "from": days[0]["d"] if days else None, "to": days[-1]["d"] if days else None,
        "avg_recovery": avg("rec", 0), "avg_hrv_ms": avg("hrv"), "avg_rhr_bpm": avg("rhr"),
        "avg_sleep_h": avg("sleep"), "avg_sleep_need_h": avg("need"), "avg_strain": avg("strain"),
        "avg_sleep_performance_pct": avg("perf", 0),
        "green_days": sum(1 for d in scored if d["rec"] >= 67),
        "yellow_days": sum(1 for d in scored if 34 <= d["rec"] < 67),
        "red_days": sum(1 for d in scored if d["rec"] < 34),
    }
