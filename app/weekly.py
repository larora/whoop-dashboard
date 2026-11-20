"""Weekly aggregates (Monday-start) for the dashboard charts, goal tracking and MCP tools."""
from datetime import date, timedelta


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _avg(vals, nd=1):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), nd) if vals else None


def _empty_week(monday: date, today: date) -> dict:
    return {"w": monday.isoformat(), "end": (monday + timedelta(days=6)).isoformat(),
            "current": week_start(today) == monday,
            "nights": 0, "kcal": 0, "strain": None,
            "sleep": None, "in_bed": None, "awake": None, "nap": None, "light": None, "sws": None, "rem": None,
            "hours": 0.0, "run_h": 0.0, "strength_h": 0.0, "other_h": 0.0,
            "runs": 0, "run_km": 0.0, "strength": 0, "sessions": 0, "longest_run_km": 0.0}


def build_weeks(days: list[dict], workouts: list[dict], today: date) -> list[dict]:
    """One row per ISO week covering all days/workouts up to today. Sleep fields are per-night averages
    (naps included); exercise hours exclude walking; counts/km come from categorised workouts."""
    if not days and not workouts:
        return []
    first = min([d["d"] for d in days] + [w["d"] for w in workouts])
    weeks: dict[str, dict] = {}
    monday = week_start(date.fromisoformat(first))
    while monday <= today:
        weeks[monday.isoformat()] = _empty_week(monday, today)
        monday += timedelta(days=7)

    by_week: dict[str, list] = {}
    for d in days:
        by_week.setdefault(week_start(date.fromisoformat(d["d"])).isoformat(), []).append(d)
    for key, rows in by_week.items():
        if key not in weeks:
            continue
        wk = weeks[key]
        wk["nights"] = sum(1 for r in rows if r.get("sleep") is not None)
        wk["kcal"] = round(sum(r["kcal"] or 0 for r in rows))
        wk["strain"] = _avg([r["strain"] for r in rows])
        for k in ("sleep", "in_bed", "awake", "nap", "light", "sws", "rem"):
            wk[k] = _avg([r.get(k) for r in rows], 2)

    for w in workouts:
        key = week_start(date.fromisoformat(w["d"])).isoformat()
        if key not in weeks:
            continue
        wk, h = weeks[key], (w["min"] or 0) / 60
        if w["cat"] == "walk":
            continue
        wk["hours"] = round(wk["hours"] + h, 2)
        wk["sessions"] += 1
        if w["cat"] == "run":
            wk["runs"] += 1
            wk["run_h"] = round(wk["run_h"] + h, 2)
            wk["run_km"] = round(wk["run_km"] + (w["km"] or 0), 2)
            wk["longest_run_km"] = max(wk["longest_run_km"], w["km"] or 0)
        elif w["cat"] == "strength":
            wk["strength"] += 1
            wk["strength_h"] = round(wk["strength_h"] + h, 2)
        else:
            wk["other_h"] = round(wk["other_h"] + h, 2)
    return list(weeks.values())


def goal_progress(weeks: list[dict], goals: dict) -> dict:
    """This week vs goals, with last week for comparison. Used by MCP and the insights panel."""
    cur = next((w for w in weeks if w["current"]), None)
    prev = weeks[-2] if cur and len(weeks) >= 2 else None
    if not cur:
        return {}
    return {
        "week_of": cur["w"], "runs": cur["runs"], "runs_goal": goals["runs"],
        "strength": cur["strength"], "strength_goal": goals["strength"],
        "run_km": cur["run_km"], "run_km_goal": goals["run_km"],
        "strength_hours": cur["strength_h"], "hours_exercised": cur["hours"],
        "last_week": {"runs": prev["runs"], "strength": prev["strength"], "run_km": prev["run_km"],
                      "hours_exercised": prev["hours"]} if prev else None,
    }
