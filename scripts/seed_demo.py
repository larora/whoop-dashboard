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
SPORTS = ["running", "weightlifting", "cycling", "functional_fitness", "yoga"]


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
        if rng.random() < .5:
            w_start = start + timedelta(hours=18, minutes=30)
            mins = rng.randint(30, 80)
            workouts.append({"id": f"demo-w{i + 1}", "start": iso(w_start), "end": iso(w_start + timedelta(minutes=mins)), "timezone_offset": "+05:30",
                             "sport_name": rng.choice(SPORTS), "sport_id": 0, "score_state": "SCORED",
                             "score": {"strain": round(6 + rng.random() * 8, 1), "average_heart_rate": 128, "max_heart_rate": 168, "kilojoule": 2500,
                                       "distance_meter": 5200 if rng.random() < .5 else None,
                                       "zone_durations": {f"zone_{z}_milli": m * 60_000 for z, m in zip(["zero", "one", "two", "three", "four", "five"], [5, 10, 15, 15, 8, 2])}}})
    db.upsert(con, "cycles", "id", [map_cycle(r) for r in cycles])
    db.upsert(con, "recovery", "cycle_id", [map_recovery(r) for r in recs])
    db.upsert(con, "sleep", "id", [map_sleep(r) for r in sleeps])
    db.upsert(con, "workouts", "id", [map_workout(r) for r in workouts])
    db.save_tokens(con, {"access_token": "demo", "refresh_token": None, "expires_in": 0})
    db.set_meta(con, "last_sync", datetime.now(timezone.utc).isoformat())
    db.set_meta(con, "demo", "1")
    print(json.dumps(db.table_counts(con)), "-> demo data written. Start the server and open http://localhost:8080")
    con.close()


if __name__ == "__main__":
    main()
