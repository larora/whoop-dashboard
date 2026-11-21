"""Strava sync against a mocked API: OAuth exchange, activity list, run detail, matching to WHOOP workouts."""
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.main import create_app
from app.strava import sync_strava
from app.whoop import SyncRunner
from conftest import MCP_TOKEN, PASSWORD, FakeWhoop, login
from test_sync import seed_tokens

RUN_START = "2026-01-10T12:00:30Z"  # WHOOP seed has a running workout at 2026-01-10T12:00:00Z (i=9)


class FakeStrava:
    def __init__(self):
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            return httpx.Response(200, json={"access_token": f"sat-{form['grant_type'][0]}", "refresh_token": "srt-1",
                                             "expires_at": 4_000_000_000, "scope": "activity:read_all"})
        if path == "/api/v3/athlete/activities":
            if request.url.params.get("page") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {"id": 501, "name": "Morning Run", "sport_type": "Run", "start_date": RUN_START, "start_date_local": "2026-01-10T17:30:30Z",
                 "distance": 8000.0, "moving_time": 2400, "elapsed_time": 2460, "total_elevation_gain": 42.0,
                 "average_heartrate": 152.0, "max_heartrate": 176.0, "average_cadence": 84.0, "average_speed": 3.33},
                {"id": 502, "name": "Lunch Ride", "sport_type": "Ride", "start_date": "2026-01-11T07:00:00Z", "start_date_local": "2026-01-11T12:30:00Z",
                 "distance": 20000.0, "moving_time": 3000, "elapsed_time": 3100, "total_elevation_gain": 100.0},
                {"id": 503, "name": "Watch run", "sport_type": "Run", "start_date": "2025-12-01T05:00:00Z", "start_date_local": "2025-12-01T10:30:00Z",
                 "distance": 5000.0, "moving_time": 1500, "elapsed_time": 1500, "total_elevation_gain": 10.0},
            ])
        if path.startswith("/api/v3/activities/"):
            aid = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={
                "id": aid, "splits_metric": [{"split": i + 1, "distance": 1000.0, "elapsed_time": 300 + i * 2, "moving_time": 298 + i * 2,
                                              "elevation_difference": 3.0 - i, "average_speed": 3.35, "average_heartrate": 148 + i} for i in range(8)],
                "best_efforts": [{"name": "1k", "distance": 1000, "elapsed_time": 290, "start_date": RUN_START, "pr_rank": 1},
                                 {"name": "5k", "distance": 5000, "elapsed_time": 1500, "start_date": RUN_START, "pr_rank": None}]})
        return httpx.Response(404)

    @property
    def transport(self):
        return httpx.MockTransport(self.handler)


@pytest.fixture
def strava_settings(tmp_path):
    return load_settings({
        "WHOOP_CLIENT_ID": "cid", "WHOOP_CLIENT_SECRET": "csecret", "WHOOP_REDIRECT_URI": "http://localhost:8080/auth/whoop/callback",
        "DASHBOARD_PASSWORD": PASSWORD, "SESSION_SECRET": "x" * 48, "DATA_DIR": str(tmp_path / "data"), "INITIAL_DAYS": "30",
        "MCP_TOKEN": MCP_TOKEN, "STRAVA_CLIENT_ID": "sid", "STRAVA_CLIENT_SECRET": "ssecret",
    })


def connect_strava(settings):
    con = db.connect(settings.db_path)
    db.save_provider_tokens(con, "strava", {"access_token": "sat", "refresh_token": "srt", "expires_at": 4_000_000_000})
    con.close()


def test_redirect_uri_defaults_to_same_host(strava_settings):
    assert strava_settings.strava_enabled
    assert strava_settings.strava_redirect_uri == "http://localhost:8080/auth/strava/callback"


def test_sync_stores_activities_and_matches_whoop(strava_settings):
    whoop, strava = FakeWhoop(), FakeStrava()
    seed_tokens(strava_settings)
    connect_strava(strava_settings)
    counts = SyncRunner(strava_settings, whoop.transport, strava_transport=strava.transport).run()
    assert counts["strava_activities"] == 3 and counts["strava_details"] == 2  # two runs, the ride gets no detail
    con = db.connect(strava_settings.db_path)
    matched = con.execute("SELECT whoop_workout_id FROM strava_activities WHERE id=501").fetchone()[0]
    assert matched == "w9"  # 30 s after the WHOOP workout start
    assert con.execute("SELECT whoop_workout_id FROM strava_activities WHERE id=503").fetchone()[0] is None
    assert con.execute("SELECT COUNT(*) FROM strava_splits WHERE activity_id=501").fetchone()[0] == 8
    assert db.get_meta(con, "strava_last_sync")
    con.close()


def test_payload_and_mcp_expose_splits_and_prs(strava_settings):
    whoop, strava = FakeWhoop(), FakeStrava()
    seed_tokens(strava_settings)
    connect_strava(strava_settings)
    app = create_app(strava_settings, transport=whoop.transport, strava_transport=strava.transport)
    with TestClient(app) as client:
        SyncRunner(strava_settings, whoop.transport, strava_transport=strava.transport).run()
        login(client)
        data = client.get("/api/data").json()
        assert data["strava_enabled"] and data["strava_connected"]
        run = next(w for w in data["workouts"] if w["strava"])
        assert run["d"] == "2026-01-10" and run["strava"]["elev_m"] == 42 and run["strava"]["cadence"] == 168
        assert len(run["strava"]["splits"]) == 8 and run["strava"]["splits"][0]["pace_str"] == "4:58"
        assert [p["name"] for p in data["prs"]] == ["1k", "5k"] and data["prs"][0]["time"] == "4:50"
        assert data["unmatched_runs"][0]["id"] == 503
        h = {"Authorization": f"Bearer {MCP_TOKEN}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        r = client.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": "get_personal_bests", "arguments": {}}})
        assert "5k" in r.text


def test_strava_oauth_routes(strava_settings):
    strava = FakeStrava()
    app = create_app(strava_settings, transport=FakeWhoop().transport, strava_transport=strava.transport)
    with TestClient(app) as client:
        login(client)
        r = client.get("/auth/strava", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("https://www.strava.com/oauth/authorize?")
        assert "scope=activity%3Aread_all" in r.headers["location"]
        r = client.get("/auth/strava/callback?code=abc&state=wrong&scope=activity:read_all", follow_redirects=False)
        assert r.status_code == 400  # state mismatch
        assert client.get("/api/data").json()["strava_connected"] is False


def test_strava_disabled_without_credentials(client):
    login(client)
    assert client.get("/auth/strava", follow_redirects=False).status_code == 404
    assert client.get("/api/data").json()["strava_enabled"] is False
