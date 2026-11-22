"""Unit tests for the derived-metrics math: sustained max HR, HRR zones, VO2 max from steady windows, VDOT."""
from app.analysis import sustained_max, trimp, vdot, vo2_from_windows, vo2_windows, zone_bounds, zone_seconds


def test_sustained_max_ignores_short_spikes():
    t = list(range(300)); hr = [140] * 300
    for k in range(100, 110): hr[k] = 190   # 10-s spike
    for k in range(200, 245): hr[k] = 170   # 45-s plateau
    assert sustained_max(hr, t, 30) == 170 and sustained_max(hr, t, 60) == 140
    assert sustained_max(hr, t, 5) == 190


def test_zone_bounds_and_seconds():
    b = zone_bounds(200, 60)  # reserve 140 → 130/144/158/172/186
    assert b == [130, 144, 158, 172, 186]
    t = list(range(0, 600)); hr = [120] * 100 + [150] * 200 + [175] * 200 + [190] * 100
    z = zone_seconds(hr, t, b)
    assert z == [99, 0, 200, 0, 200, 100] and sum(z) == 599
    assert trimp(hr, t, 200, 60) > 0


def test_vo2_from_windows_is_consistent_with_known_physiology():
    # 12 km/h (200 m/min) at 80 % HRR: VO2 = 3.5 + 40 = 43.5 → (43.5-3.5)/0.8 + 3.5 = 53.5
    windows = [[200.0, 60 + 0.8 * 140, 0.0]] * 3
    est, n = vo2_from_windows(windows, 200, 60)
    assert n == 3 and est == 53.5
    assert vo2_from_windows(windows[:2], 200, 60) == (None, 2)  # too few windows
    assert vo2_from_windows([[200.0, 70, 0.0]] * 3, 200, 60) == (None, 0)  # HR too low to be a steady effort


def test_vo2_windows_require_steady_pace():
    n = 1500; t = list(range(n))
    steady = {"time": t, "heartrate": [150] * n, "distance": [k * 3.0 for k in t], "altitude": [10.0] * n}
    w = vo2_windows(steady)
    assert w and all(abs(x[0] - 180) < 0.5 and x[1] == 150 for x in w)
    # alternate sprint/walk minutes: no window is steady
    dist, d = [], 0.0
    for k in t:
        d += 5.0 if (k // 60) % 2 == 0 else 0.8; dist.append(d)
    assert vo2_windows({**steady, "distance": dist}) == []


def test_vdot():
    assert vdot(5000, 25 * 60) == 38.3   # 25:00 5k ≈ VDOT 38
    assert 44 < vdot(10000, 45 * 60) < 46  # 45:00 10k ≈ VDOT 45
    assert vdot(5000, 10) is None
