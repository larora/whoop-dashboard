"""Shared fixtures: isolated settings + a mocked WHOOP API via httpx.MockTransport."""
import os
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["SKIP_STARTUP_SYNC"] = "1"

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD = "test-password-123"
MCP_TOKEN = "mcp-token-for-tests-0123456789"


@pytest.fixture
def settings(tmp_path):
    return load_settings({
        "WHOOP_CLIENT_ID": "cid", "WHOOP_CLIENT_SECRET": "csecret",
        "WHOOP_REDIRECT_URI": "http://localhost:8080/auth/whoop/callback",
        "DASHBOARD_PASSWORD": PASSWORD, "SESSION_SECRET": "x" * 48,
        "DATA_DIR": str(tmp_path / "data"), "INITIAL_DAYS": "30", "MCP_TOKEN": MCP_TOKEN,
    })


def _rec(table, i):
    """Minimal WHOOP v2 records; one per day, ids ascending."""
    day = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
    next_day = (date(2026, 1, 2) + timedelta(days=i)).isoformat()
    if table == "cycle":
        return {"id": i, "start": f"{day}T18:00:00.000Z", "end": None, "timezone_offset": "+05:30",
                "score_state": "SCORED", "score": {"strain": 10 + i % 5, "kilojoule": 8000, "average_heart_rate": 70, "max_heart_rate": 150}}
    if table == "recovery":
        return {"cycle_id": i, "sleep_id": f"s{i}", "score_state": "SCORED",
                "score": {"recovery_score": 50 + i, "resting_heart_rate": 55, "hrv_rmssd_milli": 60 + i, "spo2_percentage": 97, "skin_temp_celsius": 33.5}}
    if table == "sleep":
        return {"id": f"s{i}", "cycle_id": i, "start": f"{day}T18:30:00.000Z", "end": f"{next_day}T01:30:00.000Z",
                "timezone_offset": "+05:30", "nap": False, "score_state": "SCORED",
                "score": {"stage_summary": {"total_in_bed_time_milli": 25_200_000, "total_awake_time_milli": 1_800_000,
                                            "total_light_sleep_time_milli": 12_000_000, "total_slow_wave_sleep_time_milli": 6_000_000,
                                            "total_rem_sleep_time_milli": 5_400_000, "sleep_cycle_count": 4, "disturbance_count": 6},
                          "sleep_needed": {"baseline_milli": 27_000_000, "need_from_sleep_debt_milli": 1_000_000},
                          "respiratory_rate": 15.2, "sleep_performance_percentage": 90, "sleep_consistency_percentage": 70, "sleep_efficiency_percentage": 92}}
    return {"id": f"w{i}", "start": f"{day}T12:00:00.000Z", "end": f"{day}T13:00:00.000Z", "timezone_offset": "+05:30",
            "sport_name": "running", "sport_id": 0, "score_state": "SCORED",
            "score": {"strain": 12.5, "average_heart_rate": 140, "max_heart_rate": 175, "kilojoule": 2500, "distance_meter": 8000,
                      "zone_durations": {f"zone_{z}_milli": 600_000 for z in ["zero", "one", "two", "three", "four", "five"]}}}


class FakeWhoop:
    """Records every request; paginates each list endpoint over `pages` pages of 25."""

    def __init__(self, pages=2, access_expired=False, refresh_fails=False):
        self.pages, self.refresh_fails = pages, refresh_fails
        self.calls = []
        self.token_posts = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/oauth/oauth2/token":
            form = parse_qs(request.content.decode())
            self.token_posts.append(form)
            if form["grant_type"][0] == "refresh_token" and self.refresh_fails:
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": f"at-{len(self.token_posts)}", "refresh_token": f"rt-{len(self.token_posts)}",
                                             "expires_in": 3600, "scope": "offline read:recovery"})
        if request.headers.get("Authorization", "").split(" ")[-1] == "expired":
            return httpx.Response(401, json={"error": "unauthorized"})
        q = parse_qs(urlparse(str(request.url)).query)
        page = int(q.get("nextToken", ["0"])[0])
        table = {"/developer/v2/cycle": "cycle", "/developer/v2/recovery": "recovery",
                 "/developer/v2/activity/sleep": "sleep", "/developer/v2/activity/workout": "workout"}[path]
        records = [_rec(table, page * 25 + i) for i in range(25)]
        body = {"records": records}
        if page + 1 < self.pages:
            body["next_token"] = str(page + 1)
        return httpx.Response(200, json=body)

    @property
    def transport(self):
        return httpx.MockTransport(self.handler)


@pytest.fixture
def whoop():
    return FakeWhoop()


@pytest.fixture
def client(settings, whoop):
    app = create_app(settings, transport=whoop.transport)
    with TestClient(app) as c:
        yield c


def login(client, password=PASSWORD):
    return client.post("/login", data={"password": password}, follow_redirects=False)
