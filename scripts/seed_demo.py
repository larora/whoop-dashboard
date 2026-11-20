"""Fill the local database with 180 days of made-up WHOOP data so the dashboard can be previewed
before connecting a real account. Usage:  .venv/bin/python scripts/seed_demo.py   (reads DATA_DIR, default ./data)

Marks the DB as 'connected' with a dummy token so the dashboard renders charts. Clicking Connect WHOOP
later overwrites the dummy token; a real sync then replaces the demo rows (ids 1..180) over time.
To start clean instead, delete the data/ folder.
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.whoop import map_cycle, map_recovery, map_sleep, map_workout  # noqa: E402

rng = random.Random(7)


def main():
    con = db.connect(Path(os.environ.get("DATA_DIR", "./data")) / "whoop.db")
    today = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)
    cycles, recs, sleeps, workouts = [], [], [], []
    hrv = 58.0
    for i in range(180):
        start = today - timedelta(days=180 - i)
        iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
        strain = round(6 + rng.random() * 12, 1)
        hrv = max(32, min(90, hrv + (60 - hrv) * 0.15 + rng.gauss(0, 3) + (-3 if strain > 14 else 0.5)))
        sleep_h = 5.8 + rng.random() * 2.8
        rec = int(max(4, min(99, hrv * 0.9 + (sleep_h - 7) * 9 + rng.gauss(0, 10))))
        cycles.append({"id": i + 1, "start": iso(start), "end": iso(start + timedelta(days=1)), "timezone_offset": "+05:30",
                       "score_state": "SCORED", "score": {"strain": strain, "kilojoule": (1900 + strain * 70) * 4.184,
                                                         "average_heart_rate": 72, "max_heart_rate": 150 + int(strain * 2)}})
        recs.append({"cycle_id": i + 1, "sleep_id": f"demo-s{i + 1}", "score_state": "SCORED",
                     "score": {"recovery_score": rec, "resting_heart_rate": round(64 - hrv / 10 + rng.gauss(0, 1)),
                               "hrv_rmssd_milli": round(hrv, 1), "spo2_percentage": 96 + rng.random() * 2, "skin_temp_celsius": 33.5}})
        asleep_ms = int(sleep_h * 3_600_000)
        sleeps.append({"id": f"demo-s{i + 1}", "cycle_id": i + 1, "start": iso(start + timedelta(minutes=rng.randint(0, 59))),  # bedtime ≈ 23:30–00:30 IST
                       "end": iso(start + timedelta(hours=12)), "timezone_offset": "+05:30", "nap": False, "score_state": "SCORED",
                       "score": {"stage_summary": {"total_in_bed_time_milli": asleep_ms + 1_500_000, "total_awake_time_milli": 1_500_000,
                                                   "total_light_sleep_time_milli": int(asleep_ms * .5), "total_slow_wave_sleep_time_milli": int(asleep_ms * .23),
                                                   "total_rem_sleep_time_milli": int(asleep_ms * .27), "sleep_cycle_count": 4, "disturbance_count": rng.randint(4, 14)},
                                 "sleep_needed": {"baseline_milli": 27_360_000, "need_from_sleep_debt_milli": rng.randint(0, 2_000_000)},
                                 "respiratory_rate": 15.4, "sleep_performance_percentage": min(100, round(sleep_h / 8 * 100)),
                                 "sleep_consistency_percentage": rng.randint(60, 90), "sleep_efficiency_percentage": rng.randint(86, 95)}})
        if rng.random() < .25:  # afternoon nap on some days
            nap_start = start + timedelta(hours=20, minutes=rng.randint(0, 90))
            nap_ms = rng.randint(20, 45) * 60_000
            sleeps.append({"id": f"demo-n{i + 1}", "cycle_id": i + 1, "start": iso(nap_start), "end": iso(nap_start + timedelta(milliseconds=nap_ms + 300_000)),
                           "timezone_offset": "+05:30", "nap": True, "score_state": "SCORED",
                           "score": {"stage_summary": {"total_in_bed_time_milli": nap_ms + 300_000, "total_awake_time_milli": 300_000,
                                                       "total_light_sleep_time_milli": int(nap_ms * .7), "total_slow_wave_sleep_time_milli": int(nap_ms * .2),
                                                       "total_rem_sleep_time_milli": int(nap_ms * .1), "sleep_cycle_count": 0, "disturbance_count": 1}}})
        # Training pattern: ~3 runs + ~2 strength sessions a week, plus walks and the odd ride.
        dow = (start + timedelta(hours=12)).weekday()
        plan = {0: "running", 1: "weightlifting", 2: "running", 3: "weightlifting", 5: "running", 6: "cycling"}.get(dow)
        zones = lambda mins, fr: {f"zone_{z}_milli": int(mins * f * 60_000) for z, f in zip(["zero", "one", "two", "three", "four", "five"], fr)}  # noqa: E731
        if plan and rng.random() < .85:
            w_start = start + timedelta(hours=12, minutes=30 + rng.randint(0, 60))
            if plan == "running":
                km = round(rng.choice([4, 5, 6, 7, 8, 10]) + rng.random(), 2) if dow != 5 else round(10 + i / 25 + rng.random() * 2, 2)
                pace = 6.4 - i / 180 * 0.8 + rng.gauss(0, 0.15)  # slowly getting faster over the 180 days
                mins = km * pace
                score = {"strain": round(min(20, 8 + km * 0.6), 1), "average_heart_rate": 150 + rng.randint(-6, 6), "max_heart_rate": 176 + rng.randint(-4, 6),
                         "kilojoule": km * 65 * 4.184, "distance_meter": km * 1000, "zone_durations": zones(mins, [.02, .08, .25, .4, .2, .05])}
            elif plan == "weightlifting":
                mins = rng.randint(45, 75)
                score = {"strain": round(7 + rng.random() * 4, 1), "average_heart_rate": 118 + rng.randint(-6, 6), "max_heart_rate": 158 + rng.randint(-5, 8),
                         "kilojoule": mins * 7 * 4.184, "distance_meter": None, "zone_durations": zones(mins, [.1, .3, .35, .2, .05, 0])}
            else:
                mins = rng.randint(40, 90)
                score = {"strain": round(8 + rng.random() * 5, 1), "average_heart_rate": 135, "max_heart_rate": 165, "kilojoule": mins * 9 * 4.184,
                         "distance_meter": mins * 400, "zone_durations": zones(mins, [.05, .15, .35, .3, .12, .03])}
            workouts.append({"id": f"demo-w{i + 1}", "start": iso(w_start), "end": iso(w_start + timedelta(minutes=mins)), "timezone_offset": "+05:30",
                             "sport_name": plan, "sport_id": 0, "score_state": "SCORED", "score": score})
        if rng.random() < .4:  # walks: excluded from "hours exercised"
            w_start, mins = start + timedelta(hours=3), rng.randint(20, 50)
            workouts.append({"id": f"demo-walk{i + 1}", "start": iso(w_start), "end": iso(w_start + timedelta(minutes=mins)), "timezone_offset": "+05:30",
                             "sport_name": "walking", "sport_id": 0, "score_state": "SCORED",
                             "score": {"strain": 4.0, "average_heart_rate": 95, "max_heart_rate": 115, "kilojoule": mins * 4 * 4.184, "distance_meter": mins * 90,
                                       "zone_durations": zones(mins, [.5, .5, 0, 0, 0, 0])}})
    db.upsert(con, "cycles", "id", [map_cycle(r) for r in cycles])
    db.upsert(con, "recovery", "cycle_id", [map_recovery(r) for r in recs])
    db.upsert(con, "sleep", "id", [map_sleep(r) for r in sleeps])
    db.upsert(con, "workouts", "id", [map_workout(r) for r in workouts])
    db.save_tokens(con, {"access_token": "demo", "refresh_token": None, "expires_in": 0})
    db.set_meta(con, "last_sync", datetime.now(timezone.utc).isoformat())
    db.set_meta(con, "demo", "1")
    for d, v in ((60, 44.1), (30, 45.0), (3, 46.2)):  # a few manual VO2 max entries
        db.set_metric(con, "vo2max", (today - timedelta(days=d)).date().isoformat(), v)
    print(json.dumps(db.table_counts(con)), "-> demo data written. Start the server and open http://localhost:8080")
    con.close()


if __name__ == "__main__":
    main()
