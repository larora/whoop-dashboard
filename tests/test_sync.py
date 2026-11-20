import time

from app import db
from app.whoop import SyncRunner


def seed_tokens(settings, expires_in=3600):
    con = db.connect(settings.db_path)
    db.save_tokens(con, {"access_token": "at-0", "refresh_token": "rt-0", "expires_in": expires_in})
    con.close()


def test_sync_paginates_and_writes_rows(settings, whoop):
    seed_tokens(settings)
    counts = SyncRunner(settings, whoop.transport).run()
    assert counts == {"cycles": 50, "recovery": 50, "sleep": 50, "workouts": 50}
    con = db.connect(settings.db_path)
    assert db.table_counts(con)["cycles"] == 50
    assert db.get_meta(con, "last_sync") is not None
    con.close()
    # 2 pages x 4 endpoints, no token calls since the access token was valid
    assert len([c for c in whoop.calls if "/developer/" in c.url.path]) == 8
    assert whoop.token_posts == []


def test_second_sync_uses_overlap_window(settings, whoop):
    seed_tokens(settings)
    runner = SyncRunner(settings, whoop.transport)
    runner.run()
    first_start = [c for c in whoop.calls if "/developer/" in c.url.path][0].url.params["start"]
    runner.run()
    second_start = [c for c in whoop.calls if "/developer/" in c.url.path][8].url.params["start"]
    assert second_start > first_start  # only the last ~7 days are re-pulled


def test_expired_token_is_refreshed_and_rotated(settings, whoop):
    seed_tokens(settings, expires_in=0)  # expires_at is already in the past
    SyncRunner(settings, whoop.transport).run()
    assert len(whoop.token_posts) == 1 and whoop.token_posts[0]["grant_type"] == ["refresh_token"]
    con = db.connect(settings.db_path)
    tok = db.get_tokens(con)
    assert tok["refresh_token"] == "rt-1" and tok["access_token"] == "at-1"
    assert tok["expires_at"] > time.time()
    con.close()


def test_failed_refresh_marks_disconnected(settings):
    from conftest import FakeWhoop
    whoop = FakeWhoop(refresh_fails=True)
    seed_tokens(settings, expires_in=0)
    runner = SyncRunner(settings, whoop.transport)
    assert runner.run() is None
    assert "refresh failed" in runner.last_error.lower()
    con = db.connect(settings.db_path)
    assert db.whoop_connected(con) is False
    con.close()


def test_sync_lock_prevents_overlap(settings, whoop):
    seed_tokens(settings)
    runner = SyncRunner(settings, whoop.transport)
    runner._lock.acquire()
    assert runner.run() is None  # could not get the lock
    runner._lock.release()


def test_api_data_shape_after_sync(client, settings, whoop):
    from conftest import login
    seed_tokens(settings)
    login(client)
    r = client.post("/sync")
    assert r.status_code == 202
    for _ in range(50):  # background thread; wait for it to finish
        data = client.get("/api/data").json()
        if not data["sync_running"] and data["days"]:
            break
        time.sleep(0.05)
    assert data["whoop_connected"] is True and data["last_sync"]
    assert len(data["days"]) == 50
    day = data["days"][0]
    assert day["rec"] == 50 and day["sleep"] == 6.5 and day["strain"] == 10.0
    assert data["workouts"][0]["sport"] == "running" and data["workouts"][0]["min"] == 60
