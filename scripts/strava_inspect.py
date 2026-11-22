"""Print the field names Strava returns for your latest weight-training activity (no values), to check
whether exercise/set data is present anywhere in the API response.

On the Fly machine:   fly ssh console --app whoop-lakshay -C "python3 /srv/scripts/strava_inspect.py"
Locally (if Strava is connected locally):   set -a && source .env && set +a && .venv/bin/python scripts/strava_inspect.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.strava import API, StravaClient  # noqa: E402

WORDS = ("exerc", "set", "rep", "weight", "lift", "muscle", "volume")


def describe(name, value, depth=0):
    pad = "  " * depth
    if isinstance(value, dict):
        print(f"{pad}{name}: dict keys = {sorted(value.keys())}")
        for k, v in value.items():
            if isinstance(v, (dict, list)) and depth < 2:
                describe(k, v, depth + 1)
    elif isinstance(value, list):
        inner = sorted(value[0].keys()) if value and isinstance(value[0], dict) else type(value[0]).__name__ if value else "empty"
        print(f"{pad}{name}: list[{len(value)}] item keys = {inner}")


def main():
    settings = load_settings()
    con = db.connect(settings.db_path)
    row = con.execute("SELECT id, name FROM strava_activities WHERE sport_type='WeightTraining' ORDER BY start DESC LIMIT 1").fetchone()
    if not row:
        sys.exit("No WeightTraining activity synced yet.")
    client = StravaClient(settings, con)
    try:
        d = client._request("GET", f"{API}/activities/{row['id']}", auth=True)
        print(f"Activity {row['id']} ({row['name']})")
        print("top-level keys:", sorted(d.keys()))
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                describe(k, v, 1)
        words = {w for w in json.dumps(d).replace('"', " ").replace(":", " ").split() if any(x in w.lower() for x in WORDS)}
        print("tokens mentioning exercise/set/rep/weight/muscle:", sorted(words)[:30] or "none")
        print("description:", repr(d.get("description"))[:100])
        for extra in ("laps", "zones", "streams?keys=heartrate&key_by_type=true"):
            try:
                r = client._request("GET", f"{API}/activities/{row['id']}/{extra}", auth=True)
                describe("/" + extra.split("?")[0], r)
            except Exception as e:  # noqa: BLE001
                print(f"/{extra.split('?')[0]}: {str(e)[:90]}")
    finally:
        client.close()
        con.close()


if __name__ == "__main__":
    main()
