"""Print the derived fitness metrics (max HR, zones, VO2 max, stream coverage) and the strongest evidence behind
the max-HR figure. Run on the Fly machine:
    fly ssh console --app whoop-lakshay -C "python3 /srv/scripts/fitness_report.py"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.analysis import fitness_summary, recompute  # noqa: E402
from app.config import load_settings  # noqa: E402


def main():
    settings = load_settings()
    con = db.connect(settings.db_path)
    try:
        recompute(con, settings)
        print(json.dumps(fitness_summary(con, settings), indent=2))
        print("\nTop sustained heart rates (held 30 s / 60 s / peak):")
        for r in con.execute("SELECT d, sport_type, hr_30s, hr_60s, peak_hr FROM activity_metrics WHERE hr_30s IS NOT NULL ORDER BY hr_30s DESC LIMIT 10"):
            print(f"  {r['d']}  {r['sport_type']:<16} {r['hr_30s']:.0f} / {r['hr_60s']:.0f} / {r['peak_hr']:.0f}")
        print("\nPer-run VO2 max estimates (latest 15):")
        for r in con.execute("SELECT d, vo2_est, vo2_n FROM activity_metrics WHERE vo2_est IS NOT NULL ORDER BY d DESC LIMIT 15"):
            print(f"  {r['d']}  {r['vo2_est']:.1f}  ({r['vo2_n']} windows)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
