from datetime import date

from app.weekly import build_weeks, goal_progress, week_start


def day(d, **kw):
    base = {"d": d, "strain": 10, "kcal": 2000, "sleep": 7, "in_bed": 7.5, "awake": 0.5, "nap": None, "light": 3.5, "sws": 1.5, "rem": 2}
    return {**base, **kw}


def wo(d, cat, mins=60, km=None):
    return {"d": d, "cat": cat, "min": mins, "km": km}


def test_week_start_is_monday():
    assert week_start(date(2026, 11, 20)) == date(2026, 11, 16)  # Friday -> Monday
    assert week_start(date(2026, 11, 16)) == date(2026, 11, 16)


def test_build_weeks_aggregates_and_excludes_walks():
    days = [day("2026-11-10"), day("2026-11-11", sleep=6, nap=0.5), day("2026-11-17")]
    workouts = [wo("2026-11-10", "run", 30, 5.0), wo("2026-11-12", "run", 60, 10.0), wo("2026-11-11", "strength", 45),
                wo("2026-11-13", "walk", 40), wo("2026-11-17", "other", 30)]
    weeks = build_weeks(days, workouts, today=date(2026, 11, 20))
    assert [w["w"] for w in weeks] == ["2026-11-09", "2026-11-16"]
    w1, w2 = weeks
    assert w1["runs"] == 2 and w1["run_km"] == 15.0 and w1["longest_run_km"] == 10.0
    assert w1["strength"] == 1 and w1["strength_h"] == 0.75 and w1["hours"] == 2.25  # walk excluded
    assert w1["kcal"] == 4000 and w1["sleep"] == 6.5 and w1["nap"] == 0.5 and w1["nights"] == 2
    assert w2["current"] is True and w2["other_h"] == 0.5 and w2["runs"] == 0


def test_goal_progress_compares_with_last_week():
    weeks = build_weeks([day("2026-11-10"), day("2026-11-17")],
                        [wo("2026-11-10", "run", 30, 5.0), wo("2026-11-17", "run", 30, 6.0), wo("2026-11-18", "strength", 40)],
                        today=date(2026, 11, 20))
    g = goal_progress(weeks, {"runs": 4, "strength": 3, "run_km": 20})
    assert g["runs"] == 1 and g["runs_goal"] == 4 and g["run_km"] == 6.0 and g["strength"] == 1
    assert g["last_week"]["runs"] == 1 and g["last_week"]["run_km"] == 5.0
