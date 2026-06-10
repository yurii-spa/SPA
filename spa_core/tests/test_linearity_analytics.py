"""
Tests for the paper-trading equity-curve linearity / K-ratio module (SPA-V402).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_advanced_ratios.py).

Run::
    python spa_core/tests/test_linearity_analytics.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.linearity_analytics import (
    ANNUALIZATION_DAYS,
    _linearity_grade,
    _ols_fit,
    _trend_direction,
    compute_linearity,
    generate_linearity_report,
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


def _curve_from_equity(equities):
    """Build a minimal daily curve from a list of close_equity values."""
    bars = []
    for i, e in enumerate(equities):
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(e, 4),
            "close_equity": round(e, 4),
            "high_equity": round(e, 4),
            "low_equity": round(e, 4),
            "snapshots": 1,
            "daily_return_pct": 0.0,
            "cumulative_return_pct": 0.0,
            "drawdown_pct": 0.0,
        })
    return bars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


_SCHEMA_KEYS = {
    "num_points", "log_slope_per_day", "intercept_log", "r_squared",
    "slope_std_err", "t_stat_slope", "k_ratio", "rmse_log",
    "max_abs_residual_log", "annualized_log_drift_pct", "linearity_grade",
    "trend_direction", "annualization_days", "execution_mode",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_linearity([])
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_points"] == 0, m
    assert m["r_squared"] is None, m
    assert m["k_ratio"] is None, m
    assert m["annualization_days"] == ANNUALIZATION_DAYS, m
    assert m["execution_mode"] == "read_only_simulation", m


def test_single_point_undefined():
    m = compute_linearity(_curve_from_equity([100.0]))
    assert m["num_points"] == 1, m
    assert m["log_slope_per_day"] is None, m
    assert m["r_squared"] is None, m


def test_schema_keys_on_real_shape():
    m = compute_linearity(_curve_from_equity([100.0, 101.0, 100.5, 102.0]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()


def test_ols_perfect_line_log():
    # equity grows by exactly factor k each day → log-equity is a perfect line.
    eq = [100.0 * (1.01 ** i) for i in range(6)]
    m = compute_linearity(_curve_from_equity(eq))
    assert approx(m["r_squared"], 1.0, tol=1e-9), m
    # slope of ln(equity) per day == ln(1.01)
    assert approx(m["log_slope_per_day"], math.log(1.01), tol=1e-6), m
    assert m["linearity_grade"] == "A", m
    assert m["trend_direction"] == "up", m
    # residuals essentially zero (helper rounds equity to 4dp → ~1e-8 floor)
    assert m["rmse_log"] is not None and m["rmse_log"] < 1e-6, m


def test_ols_helper_known_line():
    # y = 2x + 1 exactly → slope 2, intercept 1, r2 1.
    xs = [0.0, 1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 3.0, 5.0, 7.0, 9.0]
    fit = _ols_fit(xs, ys)
    assert approx(fit["slope"], 2.0), fit
    assert approx(fit["intercept"], 1.0), fit
    assert approx(fit["r_squared"], 1.0), fit
    assert fit["rmse"] is not None and fit["rmse"] < 1e-9, fit


def test_downtrend_negative_slope():
    eq = [100.0 * (0.99 ** i) for i in range(6)]
    m = compute_linearity(_curve_from_equity(eq))
    assert m["log_slope_per_day"] < 0, m
    assert m["trend_direction"] == "down", m
    assert m["annualized_log_drift_pct"] < 0, m


def test_flat_curve_trend_flat():
    m = compute_linearity(_curve_from_equity([100.0, 100.0, 100.0, 100.0]))
    assert approx(m["log_slope_per_day"], 0.0, tol=1e-9), m
    assert m["trend_direction"] == "flat", m
    # perfectly flat → r_squared defined as 1.0 (fit explains the zero variance)
    assert m["r_squared"] == 1.0, m
    assert approx(m["annualized_log_drift_pct"], 0.0, tol=1e-6), m


def test_noisy_curve_lower_r2_than_clean():
    clean = [100.0 * (1.01 ** i) for i in range(8)]
    noisy = [v * (1.0 + (0.03 if i % 2 else -0.03)) for i, v in enumerate(clean)]
    r2_clean = compute_linearity(_curve_from_equity(clean))["r_squared"]
    r2_noisy = compute_linearity(_curve_from_equity(noisy))["r_squared"]
    assert r2_clean >= r2_noisy, (r2_clean, r2_noisy)
    assert 0.0 <= r2_noisy <= 1.0, r2_noisy


def test_r_squared_in_unit_interval():
    m = compute_linearity(_curve_from_equity([100.0, 103.0, 99.0, 105.0, 98.0, 110.0]))
    assert 0.0 <= m["r_squared"] <= 1.0, m


def test_k_ratio_present_and_finite_with_enough_points():
    eq = [100.0, 101.2, 100.8, 102.5, 103.1, 104.0, 103.7, 105.2]
    m = compute_linearity(_curve_from_equity(eq))
    assert m["k_ratio"] is not None, m
    assert math.isfinite(m["k_ratio"]), m
    # k_ratio == t_stat / sqrt(n)
    assert approx(m["k_ratio"], m["t_stat_slope"] / math.sqrt(m["num_points"]), tol=1e-5), m


def test_two_points_no_std_err():
    # n == 2 → fit defined but slope std-err (needs n-2 dof) undefined.
    m = compute_linearity(_curve_from_equity([100.0, 101.0]))
    assert m["num_points"] == 2, m
    assert m["log_slope_per_day"] is not None, m
    assert m["slope_std_err"] is None, m
    assert m["t_stat_slope"] is None, m
    assert m["k_ratio"] is None, m


def test_non_positive_equity_guarded():
    m = compute_linearity(_curve_from_equity([100.0, 0.0, 101.0, 102.0]))
    # contains a non-positive equity → logs unsafe → stable schema, no slope
    assert m["log_slope_per_day"] is None, m
    assert m["r_squared"] is None, m
    assert m["num_points"] == 4, m


def test_k_ratio_sign_follows_slope():
    up = compute_linearity(_curve_from_equity([100.0 * (1.005 ** i) for i in range(8)]))
    down = compute_linearity(_curve_from_equity([100.0 * (0.995 ** i) for i in range(8)]))
    if up["k_ratio"] is not None:
        assert up["k_ratio"] > 0, up
    if down["k_ratio"] is not None:
        assert down["k_ratio"] < 0, down


def test_annualized_drift_consistent_with_slope():
    eq = [100.0 * (1.002 ** i) for i in range(8)]
    m = compute_linearity(_curve_from_equity(eq))
    expected = (math.exp(m["log_slope_per_day"] * ANNUALIZATION_DAYS) - 1.0) * 100.0
    assert approx(m["annualized_log_drift_pct"], round(expected, 4), tol=1e-3), m


def test_grade_helper_thresholds():
    assert _linearity_grade(0.99) == "A"
    assert _linearity_grade(0.85) == "B"
    assert _linearity_grade(0.60) == "C"
    assert _linearity_grade(0.10) == "D"
    assert _linearity_grade(None) is None


def test_trend_helper():
    assert _trend_direction(0.01) == "up"
    assert _trend_direction(-0.01) == "down"
    assert _trend_direction(0.0) == "flat"
    assert _trend_direction(None) is None


def test_max_abs_residual_geq_zero():
    m = compute_linearity(_curve_from_equity([100.0, 102.0, 99.0, 103.0, 101.0]))
    assert m["max_abs_residual_log"] is not None and m["max_abs_residual_log"] >= 0, m
    assert m["rmse_log"] is not None and m["rmse_log"] >= 0, m
    # max abs residual >= rmse for any residual vector
    assert m["max_abs_residual_log"] + 1e-12 >= m["rmse_log"], m


def test_all_finite_outputs():
    m = compute_linearity(_curve_from_equity([100.0, 101.5, 100.2, 102.8, 101.1, 103.6, 102.0]))
    for k, v in m.items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)


def test_report_no_write_smoke_real_data():
    report = generate_linearity_report(output_path=None)
    assert "generated_at" in report and "metrics" in report, report
    assert set(report["metrics"].keys()) == _SCHEMA_KEYS, report["metrics"].keys()


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "linearity_analytics.json"
        generate_linearity_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir() if p.name.startswith(".linearity_analytics_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_linearity_analytics (SPA-V402)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single point → undefined", test_single_point_undefined)
    run("schema keys on real shape", test_schema_keys_on_real_shape)
    run("perfect log-line → r2=1, slope=ln k", test_ols_perfect_line_log)
    run("ols helper on known line", test_ols_helper_known_line)
    run("downtrend → negative slope", test_downtrend_negative_slope)
    run("flat curve → trend flat", test_flat_curve_trend_flat)
    run("noisy curve lower r2 than clean", test_noisy_curve_lower_r2_than_clean)
    run("r_squared in [0,1]", test_r_squared_in_unit_interval)
    run("k_ratio present + finite (enough pts)", test_k_ratio_present_and_finite_with_enough_points)
    run("two points → no std err", test_two_points_no_std_err)
    run("non-positive equity guarded", test_non_positive_equity_guarded)
    run("k_ratio sign follows slope", test_k_ratio_sign_follows_slope)
    run("annualized drift consistent with slope", test_annualized_drift_consistent_with_slope)
    run("grade helper thresholds", test_grade_helper_thresholds)
    run("trend helper", test_trend_helper)
    run("max abs residual >= rmse >= 0", test_max_abs_residual_geq_zero)
    run("all outputs finite", test_all_finite_outputs)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
