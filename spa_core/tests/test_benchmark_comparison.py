"""
Tests for the paper-trading benchmark-comparison module (SPA-V394).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_return_distribution.py /
test_risk_metrics.py).

Run::
    python spa_core/tests/test_benchmark_comparison.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.benchmark_comparison import (
    compute_benchmark_comparison,
    generate_benchmark_comparison_report,
    _flat_daily_return_pct,
    _compound_pct,
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

    The first element is the seed day (daily_return_pct forced to 0.0); all
    subsequent values are realised returns. Mirrors test_return_distribution._curve.
    """
    bars = []
    equity = 100.0
    for i, r in enumerate(returns):
        dr = 0.0 if i == 0 else r
        equity *= (1.0 + dr / 100.0)
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(equity, 4),
            "close_equity": round(equity, 4),
            "high_equity": round(equity, 4),
            "low_equity": round(equity, 4),
            "snapshots": 1,
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": 0.0,
            "drawdown_pct": 0.0,
        })
    return bars


# ─── Schema / degenerate inputs ────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    c = compute_benchmark_comparison([])
    assert c["count"] == 0, c
    # Every metric key present; numeric metrics None on empty input.
    for k in ("portfolio_total_return_pct", "tracking_error_pct",
              "information_ratio", "beta", "correlation",
              "up_capture", "down_capture", "best_active_day"):
        assert c[k] is None, (k, c[k])
    assert c["benchmark_kind"] == "flat_risk_free", c


def test_single_seed_day_no_returns():
    c = compute_benchmark_comparison(_curve([0.0]))
    assert c["count"] == 0, c  # only seed day → no realised returns


def test_benchmark_kind_flag():
    flat = compute_benchmark_comparison(_curve([0.0, 0.1, 0.2]))
    assert flat["benchmark_kind"] == "flat_risk_free", flat
    expl = compute_benchmark_comparison(_curve([0.0, 0.1, 0.2]),
                                        benchmark_returns=[0.05, 0.05])
    assert expl["benchmark_kind"] == "explicit", expl


# ─── Flat-benchmark helpers / math ─────────────────────────────────────────────

def test_flat_daily_return_roundtrip():
    # Compounding the per-day flat return over a year recovers the annual rate.
    daily = _flat_daily_return_pct(4.0, 365)
    annual = ((1.0 + daily / 100.0) ** 365 - 1.0) * 100.0
    assert math.isclose(annual, 4.0, rel_tol=1e-9), (daily, annual)


def test_flat_zero_rate_is_zero():
    assert _flat_daily_return_pct(0.0, 365) == 0.0


def test_compound_pct_known_value():
    # +10% then +10% compounds to +21%.
    assert math.isclose(_compound_pct([10.0, 10.0]), 21.0, rel_tol=1e-9)


# ─── Excess return / tracking error / information ratio ────────────────────────

def test_excess_return_equals_portfolio_minus_benchmark():
    c = compute_benchmark_comparison(_curve([0.0, 0.5, 0.5, 0.5]),
                                     benchmark_annual_pct=0.0)
    # Zero benchmark → excess total == portfolio total.
    assert math.isclose(c["excess_total_return_pct"],
                        c["portfolio_total_return_pct"], rel_tol=1e-9), c
    assert math.isclose(c["benchmark_total_return_pct"], 0.0, abs_tol=1e-9), c


def test_tracking_error_zero_when_matching_benchmark():
    # Portfolio returns exactly equal to the flat benchmark each day → zero
    # active risk → tracking error 0 and information ratio undefined.
    daily = _flat_daily_return_pct(4.0, 365)
    c = compute_benchmark_comparison(_curve([0.0, daily, daily, daily]),
                                     benchmark_annual_pct=4.0)
    assert math.isclose(c["tracking_error_pct"], 0.0, abs_tol=1e-9), c
    assert c["information_ratio"] is None, c


def test_information_ratio_sign_follows_active_return():
    # Portfolio consistently beats a flat benchmark → positive active return,
    # positive (finite) information ratio with some active-risk variation.
    c = compute_benchmark_comparison(_curve([0.0, 1.0, 0.5, 1.5, 0.8]),
                                     benchmark_annual_pct=4.0)
    assert c["mean_active_return_pct"] > 0, c
    assert c["information_ratio"] is not None and c["information_ratio"] > 0, c
    assert c["tracking_error_pct"] > 0, c


def test_information_ratio_annualized_scales():
    c = compute_benchmark_comparison(_curve([0.0, 1.0, -0.5, 0.8, -0.2]),
                                     benchmark_annual_pct=4.0,
                                     periods_per_year=365)
    if c["information_ratio"] is not None:
        # information_ratio is rounded for display; the annualised value is
        # derived from the unrounded ratio, so allow a small absolute slack.
        expected = c["information_ratio"] * math.sqrt(365)
        assert math.isclose(c["information_ratio_annualized"], expected, abs_tol=0.01), c


# ─── Beta / correlation (flat vs varying benchmark) ────────────────────────────

def test_flat_benchmark_beta_correlation_none():
    # A flat benchmark has zero variance → beta / correlation / capture undefined.
    c = compute_benchmark_comparison(_curve([0.0, 1.0, -0.5, 0.3]),
                                     benchmark_annual_pct=4.0)
    assert c["beta"] is None, c
    assert c["correlation"] is None, c
    assert c["up_capture"] is None and c["down_capture"] is None, c


def test_varying_benchmark_perfect_correlation():
    # Portfolio == benchmark exactly → beta 1, correlation 1.
    port = [0.0, 1.0, -0.5, 0.8, -0.2]      # incl. seed
    bench = [1.0, -0.5, 0.8, -0.2]          # realised days only
    c = compute_benchmark_comparison(_curve(port), benchmark_returns=bench)
    assert math.isclose(c["beta"], 1.0, rel_tol=1e-9), c
    assert math.isclose(c["correlation"], 1.0, rel_tol=1e-9), c
    assert math.isclose(c["tracking_error_pct"], 0.0, abs_tol=1e-9), c


def test_varying_benchmark_beta_two():
    # Portfolio = 2x benchmark each day → beta 2, correlation 1.
    bench = [1.0, -0.5, 0.8, -0.2]
    port = [0.0] + [2.0 * b for b in bench]
    c = compute_benchmark_comparison(_curve(port), benchmark_returns=bench)
    assert math.isclose(c["beta"], 2.0, rel_tol=1e-9), c
    assert math.isclose(c["correlation"], 1.0, rel_tol=1e-9), c


def test_correlation_in_range():
    bench = [1.0, -2.0, 0.5, 1.5, -1.0]
    port = [0.0, -0.5, 1.0, 0.2, -1.5, 2.0][:1 + len(bench)]
    c = compute_benchmark_comparison(_curve(port), benchmark_returns=bench)
    if c["correlation"] is not None:
        assert -1.0 <= c["correlation"] <= 1.0, c


def test_capture_ratios_with_varying_benchmark():
    # Portfolio captures exactly the benchmark on every day → both capture
    # ratios == 1.0.
    bench = [2.0, -1.0, 1.5, -0.5]
    port = [0.0] + list(bench)
    c = compute_benchmark_comparison(_curve(port), benchmark_returns=bench)
    assert c["up_capture"] is not None and math.isclose(c["up_capture"], 1.0, rel_tol=1e-9), c
    assert c["down_capture"] is not None and math.isclose(c["down_capture"], 1.0, rel_tol=1e-9), c


# ─── Day counts / alignment ────────────────────────────────────────────────────

def test_days_outperformed_counts():
    # Flat benchmark ~ tiny positive daily; portfolio: +,+,- vs benchmark.
    c = compute_benchmark_comparison(_curve([0.0, 1.0, 2.0, -3.0]),
                                     benchmark_annual_pct=4.0)
    assert c["days_outperformed"] + c["days_underperformed"] + c["days_matched"] == c["count"], c
    assert c["days_outperformed"] == 2 and c["days_underperformed"] == 1, c


def test_explicit_benchmark_alignment_truncates():
    # 4 realised portfolio days, 2 benchmark days → aligned to 2.
    c = compute_benchmark_comparison(_curve([0.0, 1.0, 1.0, 1.0, 1.0]),
                                     benchmark_returns=[0.5, 0.5])
    assert c["count"] == 2, c


def test_best_worst_active_day_present():
    c = compute_benchmark_comparison(_curve([0.0, 2.0, -1.0, 0.5]),
                                     benchmark_annual_pct=4.0)
    assert c["best_active_day"]["active_return_pct"] >= c["worst_active_day"]["active_return_pct"], c
    assert c["best_active_day"]["date"] is not None, c


# ─── Real-data smoke ───────────────────────────────────────────────────────────

def test_report_no_write_smoke():
    rep = generate_benchmark_comparison_report(output_path=None)
    assert "comparison" in rep and "generated_at" in rep, rep
    comp = rep["comparison"]
    assert isinstance(comp["count"], int), rep
    # All present float scalars must be finite & JSON-serialisable.
    for k, v in comp.items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)


def main():
    print("test_benchmark_comparison (SPA-V394)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_seed_day_no_returns)
    run("benchmark kind flag", test_benchmark_kind_flag)
    run("flat daily-return annual roundtrip", test_flat_daily_return_roundtrip)
    run("flat zero rate → 0", test_flat_zero_rate_is_zero)
    run("compound_pct known value", test_compound_pct_known_value)
    run("excess == portfolio − benchmark", test_excess_return_equals_portfolio_minus_benchmark)
    run("tracking error 0 when matching benchmark", test_tracking_error_zero_when_matching_benchmark)
    run("information ratio sign follows active return", test_information_ratio_sign_follows_active_return)
    run("information ratio annualised scales", test_information_ratio_annualized_scales)
    run("flat benchmark → beta/corr/capture None", test_flat_benchmark_beta_correlation_none)
    run("varying benchmark perfect correlation", test_varying_benchmark_perfect_correlation)
    run("varying benchmark beta = 2", test_varying_benchmark_beta_two)
    run("correlation in [-1, 1]", test_correlation_in_range)
    run("capture ratios with varying benchmark", test_capture_ratios_with_varying_benchmark)
    run("days outperformed counts", test_days_outperformed_counts)
    run("explicit benchmark alignment truncates", test_explicit_benchmark_alignment_truncates)
    run("best/worst active day present", test_best_worst_active_day_present)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
