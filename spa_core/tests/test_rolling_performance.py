"""
Tests for the paper-trading rolling-window performance module (SPA-V381).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_risk_metrics.py / test_equity_curve.py).

Run::
    python spa_core/tests/test_rolling_performance.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics_lab.rolling_performance import (
    DEFAULT_WINDOWS,
    compute_rolling_performance,
    compute_rolling_series,
    compute_window_metrics,
    generate_rolling_performance_report,
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


def _curve(returns):
    """Build a minimal daily curve from a list of daily_return_pct values.

    Element 0 is the seed day (daily_return_pct forced to 0.0). The synthetic
    close path / all-time drawdown is filled so bars look like real curve bars.
    """
    bars = []
    equity = 100.0
    peak = 100.0
    for i, r in enumerate(returns):
        dr = 0.0 if i == 0 else r
        equity *= (1.0 + dr / 100.0)
        peak = max(peak, equity)
        dd = (equity / peak - 1.0) * 100.0
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(equity, 4),
            "close_equity": round(equity, 4),
            "high_equity": round(equity, 4),
            "low_equity": round(equity, 4),
            "snapshots": 1,
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": 0.0,
            "drawdown_pct": round(dd, 6),
        })
    return bars


def approx(a, b, tol=1e-4):
    return abs(a - b) <= tol


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_window_metrics([], 7)
    assert m["window"] == 7, m
    assert m["days_in_window"] == 0, m
    assert m["window_return_pct"] == 0.0, m
    assert m["best_day"] is None and m["worst_day"] is None, m
    assert compute_rolling_series([], 7) == [], "empty series expected"


def test_seed_only_no_realised_days():
    # Only the seed day → no realised returns.
    m = compute_window_metrics(_curve([0.0]), 7)
    assert m["days_in_window"] == 0, m
    assert compute_rolling_series(_curve([0.0]), 7) == [], "no realised days"


def test_nonpositive_window():
    m = compute_window_metrics(_curve([0.0, 1.0, 2.0]), 0)
    assert m["days_in_window"] == 0, m
    assert compute_rolling_series(_curve([0.0, 1.0, 2.0]), -3) == [], "neg window"


def test_window_caps_at_history_length():
    # 3 realised days, ask for window 7 → uses all 3.
    m = compute_window_metrics(_curve([0.0, 1.0, -0.5, 0.5]), 7)
    assert m["days_in_window"] == 3, m
    assert m["first_date"] == "2026-05-16", m  # first *realised* day
    assert m["last_date"] == "2026-05-18", m


def test_window_takes_trailing_slice():
    # 5 realised days (+1,-0.5,+0.5,-0.25,+2.0); window 2 → last two days only.
    m = compute_window_metrics(_curve([0.0, 1.0, -0.5, 0.5, -0.25, 2.0]), 2)
    assert m["days_in_window"] == 2, m
    assert m["positive_days"] == 1 and m["negative_days"] == 1, m
    assert m["best_day"]["daily_return_pct"] == 2.0, m["best_day"]
    assert m["worst_day"]["daily_return_pct"] == -0.25, m["worst_day"]


def test_window_return_compounds():
    # Two +10% days → compounded 21%, not 20%.
    m = compute_window_metrics(_curve([0.0, 10.0, 10.0]), 7)
    assert approx(m["window_return_pct"], 21.0), m["window_return_pct"]


def test_window_counts_and_mean():
    m = compute_window_metrics(_curve([0.0, 1.0, -0.5, 0.5, -0.25]), 7)
    assert m["days_in_window"] == 4, m
    assert m["positive_days"] == 2 and m["negative_days"] == 2, m
    assert approx(m["mean_daily_return_pct"], (1.0 - 0.5 + 0.5 - 0.25) / 4), m


def test_window_drawdown_within_window():
    # Recovered all-time, but inside the trailing window there is a dip.
    # realised: +1, -2, +0.5 ; window 3 covers the -2 day → window dd < 0.
    m = compute_window_metrics(_curve([0.0, 1.0, -2.0, 0.5]), 3)
    assert m["window_max_drawdown_pct"] < 0, m
    # A flat/rising-only window has zero drawdown.
    m2 = compute_window_metrics(_curve([0.0, 0.5, 0.3, 0.7]), 3)
    assert m2["window_max_drawdown_pct"] == 0.0, m2


def test_zero_volatility_window():
    # Constant return → zero stdev.
    m = compute_window_metrics(_curve([0.0, 0.3, 0.3, 0.3]), 7)
    assert approx(m["window_volatility_pct"], 0.0), m


def test_rolling_series_length_and_growth():
    curve = _curve([0.0, 1.0, -0.5, 0.5, -0.25, 2.0])  # 5 realised days
    series = compute_rolling_series(curve, 3)
    assert len(series) == 5, len(series)
    # days_in_window ramps 1,2,3,3,3 as the trailing window fills.
    assert [p["days_in_window"] for p in series] == [1, 2, 3, 3, 3], series
    # Last point's window return matches the window-2... no: window 3 last slice.
    last = compute_window_metrics(curve, 3)
    assert approx(series[-1]["window_return_pct"], last["window_return_pct"]), (
        series[-1], last)


def test_compute_rolling_performance_dedup_sorts():
    curve = _curve([0.0, 1.0, -0.5, 0.5])
    out = compute_rolling_performance(curve, [30, 7, 7, -1, 0])
    assert out["windows"] == [7, 30], out["windows"]
    assert set(out["by_window"].keys()) == {"7", "30"}, out["by_window"].keys()
    for w in out["by_window"].values():
        assert "summary" in w and "series" in w, w


def test_report_no_write_smoke():
    rep = generate_rolling_performance_report(output_path=None)
    assert "by_window" in rep and "generated_at" in rep, rep
    assert rep["windows"] == sorted(set(DEFAULT_WINDOWS)), rep["windows"]
    # Every numeric field present must be JSON-serializable & finite.
    for w in rep["by_window"].values():
        for k, v in w["summary"].items():
            if isinstance(v, float):
                assert math.isfinite(v), (k, v)
        for point in w["series"]:
            for k, v in point.items():
                if isinstance(v, float):
                    assert math.isfinite(v), (k, v)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_rolling_performance (SPA-V381)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("seed only → no realised days", test_seed_only_no_realised_days)
    run("non-positive window", test_nonpositive_window)
    run("window caps at history length", test_window_caps_at_history_length)
    run("window takes trailing slice", test_window_takes_trailing_slice)
    run("window return compounds", test_window_return_compounds)
    run("window counts + mean", test_window_counts_and_mean)
    run("window drawdown within window", test_window_drawdown_within_window)
    run("zero volatility window", test_zero_volatility_window)
    run("rolling series length + growth", test_rolling_series_length_and_growth)
    run("rolling performance dedup/sorts", test_compute_rolling_performance_dedup_sorts)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
