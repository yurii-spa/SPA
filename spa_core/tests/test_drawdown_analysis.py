"""
Tests for the paper-trading drawdown-episode analysis module (SPA-V382).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_rolling_performance.py /
test_risk_metrics.py / test_equity_curve.py).

Run::
    python spa_core/tests/test_drawdown_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.drawdown_analysis import (
    compute_drawdown_summary,
    find_drawdown_episodes,
    generate_drawdown_report,
)


# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0


def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except AssertionError as exc:
        FAIL += 1
        print(f"  ✗ {name}: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors as fails
        FAIL += 1
        print(f"  ✗ {name}: UNEXPECTED {type(exc).__name__}: {exc}")


def _curve(closes):
    """Build a minimal daily curve from a list of close_equity values.

    Each element becomes one bar dated sequentially from 2026-05-15. Only the
    fields the drawdown module reads (date, close_equity) need be accurate.
    """
    bars = []
    for i, c in enumerate(closes):
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(float(c), 4),
            "close_equity": round(float(c), 4),
            "high_equity": round(float(c), 4),
            "low_equity": round(float(c), 4),
            "snapshots": 1,
            "daily_return_pct": 0.0,
            "cumulative_return_pct": 0.0,
            "drawdown_pct": 0.0,
        })
    return bars


def approx(a, b, tol=1e-4):
    return abs(a - b) <= tol


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_no_episodes():
    assert find_drawdown_episodes([]) == [], "empty curve → no episodes"
    s = compute_drawdown_summary([], [])
    assert s["num_episodes"] == 0, s
    assert s["currently_in_drawdown"] is False, s
    assert s["max_drawdown_pct"] == 0.0, s
    assert s["total_days"] is None, s


def test_monotonic_rise_no_drawdown():
    curve = _curve([100, 101, 102, 103])
    eps = find_drawdown_episodes(curve)
    assert eps == [], f"strictly rising curve should have no drawdown: {eps}"
    s = compute_drawdown_summary(curve, eps)
    assert s["num_episodes"] == 0 and s["time_underwater_pct"] == 0.0, s


def test_single_recovered_episode():
    # peak 100 (day0), trough 90 (day2), recover to 100 (day4).
    curve = _curve([100, 95, 90, 95, 100])
    eps = find_drawdown_episodes(curve)
    assert len(eps) == 1, eps
    e = eps[0]
    assert e["peak_date"] == "2026-05-15", e
    assert e["trough_date"] == "2026-05-17", e
    assert e["recovery_date"] == "2026-05-19", e
    assert e["recovered"] is True, e
    assert approx(e["max_drawdown_pct"], -10.0), e["max_drawdown_pct"]
    assert e["drawdown_days"] == 2, e   # day0 -> day2
    assert e["recovery_days"] == 2, e   # day2 -> day4
    assert e["total_days"] == 4, e      # day0 -> day4


def test_ongoing_episode_not_recovered():
    # Falls and never reclaims the 100 peak before history ends.
    curve = _curve([100, 96, 92, 94])
    eps = find_drawdown_episodes(curve)
    assert len(eps) == 1, eps
    e = eps[0]
    assert e["recovered"] is False, e
    assert e["recovery_date"] is None, e
    assert e["recovery_days"] is None, e
    assert e["trough_date"] == "2026-05-17", e   # deepest = 92
    assert approx(e["max_drawdown_pct"], -8.0), e["max_drawdown_pct"]
    # total_days runs peak -> last observed date (day3), not a recovery.
    assert e["total_days"] == 3, e
    s = compute_drawdown_summary(curve, eps)
    assert s["currently_in_drawdown"] is True, s
    assert approx(s["current_drawdown_pct"], -8.0), s
    assert s["ongoing_episodes"] == 1 and s["recovered_episodes"] == 0, s


def test_two_distinct_episodes_and_new_peak():
    # ep1: 100->90->recover@105 (new high); ep2 from 105->100 (ongoing).
    curve = _curve([100, 90, 105, 100])
    eps = find_drawdown_episodes(curve)
    assert len(eps) == 2, eps
    a, b = eps
    assert a["peak_equity"] == 100 and a["recovered"] is True, a
    assert a["recovery_date"] == "2026-05-17", a
    assert b["peak_equity"] == 105 and b["recovered"] is False, b
    assert approx(b["max_drawdown_pct"], (100 / 105 - 1) * 100), b
    s = compute_drawdown_summary(curve, eps)
    assert s["num_episodes"] == 2, s
    assert s["recovered_episodes"] == 1 and s["ongoing_episodes"] == 1, s
    # worst episode is ep1 (-10%) vs ep2 (~-4.76%).
    assert approx(s["max_drawdown_pct"], -10.0), s
    assert s["max_drawdown_episode"]["peak_equity"] == 100, s


def test_min_depth_filter():
    # A 1% dip then recovery, plus a deeper 10% dip. min_depth filters the 1%.
    curve = _curve([100, 99, 100, 90, 100])
    all_eps = find_drawdown_episodes(curve, min_depth_pct=0.0)
    assert len(all_eps) == 2, all_eps
    filtered = find_drawdown_episodes(curve, min_depth_pct=5.0)
    assert len(filtered) == 1, filtered
    assert approx(filtered[0]["max_drawdown_pct"], -10.0), filtered[0]


def test_summary_avg_and_longest():
    # ep1 -10% (recover), ep2 -20% ongoing → avg -15%; longest_recovery only ep1.
    curve = _curve([100, 90, 100, 80])
    eps = find_drawdown_episodes(curve)
    s = compute_drawdown_summary(curve, eps)
    assert approx(s["avg_drawdown_pct"], -15.0), s
    assert s["longest_recovery_days"] is not None, s
    assert s["max_drawdown_pct"] == -20.0, s


def test_drawdown_then_lower_low_single_episode():
    # One episode whose trough deepens over several days before recovery.
    curve = _curve([100, 95, 92, 88, 95, 101])
    eps = find_drawdown_episodes(curve)
    assert len(eps) == 1, eps
    e = eps[0]
    assert e["trough_date"] == "2026-05-18", e        # 88 is the deepest
    assert approx(e["max_drawdown_pct"], -12.0), e
    assert e["recovered"] is True, e


def test_time_underwater_bounded():
    curve = _curve([100, 90, 100, 80, 120])
    eps = find_drawdown_episodes(curve)
    s = compute_drawdown_summary(curve, eps)
    assert 0.0 <= s["time_underwater_pct"] <= 100.0, s


def test_nonnumeric_close_skipped():
    # A bar with a bool / missing close must not raise and must be skipped.
    curve = _curve([100, 90, 100])
    curve.insert(2, {"date": "2026-05-99", "close_equity": True})  # bool rejected
    eps = find_drawdown_episodes(curve)
    assert len(eps) == 1, eps
    assert eps[0]["recovered"] is True, eps


def test_report_no_write_smoke():
    # Real pnl_history.json → compute-only, schema present, never raises.
    report = generate_drawdown_report(output_path=None)
    assert set(report) >= {"generated_at", "source", "summary", "episodes"}, report
    s = report["summary"]
    for k in ("num_episodes", "max_drawdown_pct", "currently_in_drawdown",
              "time_underwater_pct"):
        assert k in s, (k, s)
    assert isinstance(report["episodes"], list), report
    assert 0.0 <= s["time_underwater_pct"] <= 100.0, s


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_drawdown_analysis (SPA-V382)")
    run("empty curve → no episodes", test_empty_curve_no_episodes)
    run("monotonic rise → no drawdown", test_monotonic_rise_no_drawdown)
    run("single recovered episode", test_single_recovered_episode)
    run("ongoing episode not recovered", test_ongoing_episode_not_recovered)
    run("two distinct episodes + new peak", test_two_distinct_episodes_and_new_peak)
    run("min-depth filter", test_min_depth_filter)
    run("summary avg + longest", test_summary_avg_and_longest)
    run("deepening trough = single episode", test_drawdown_then_lower_low_single_episode)
    run("time underwater bounded", test_time_underwater_bounded)
    run("non-numeric close skipped", test_nonnumeric_close_skipped)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
