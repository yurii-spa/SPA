"""
Tests for the paper-trading return-distribution module (SPA-V383).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_risk_metrics.py / test_equity_curve.py).

Run::
    python spa_core/tests/test_return_distribution.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.return_distribution import (
    DEFAULT_BINS,
    DEFAULT_CONFIDENCE_LEVELS,
    compute_return_distribution,
    generate_return_distribution_report,
    _percentile,
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
    subsequent values are realised returns. Mirrors test_risk_metrics._curve.
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


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    d = compute_return_distribution([])
    assert d["count"] == 0, d
    assert d["mean_pct"] is None, d
    assert d["histogram"] == [], d
    assert d["var"] == {"95": None, "99": None}, d
    assert d["confidence_levels"] == list(DEFAULT_CONFIDENCE_LEVELS), d
    assert d["bins"] == DEFAULT_BINS, d


def test_single_seed_day_no_returns():
    d = compute_return_distribution(_curve([0.0]))
    assert d["count"] == 0, d
    assert d["percentiles"]["p50"] is None, d


def test_counts_and_central_tendency():
    # seed + returns: +1, -0.5, +0.5, -0.25, 0.0 → 5 return days
    d = compute_return_distribution(_curve([0.0, 1.0, -0.5, 0.5, -0.25, 0.0]))
    assert d["count"] == 5, d
    assert d["positive_days"] == 2, d
    assert d["negative_days"] == 2, d
    assert d["zero_days"] == 1, d
    # mean of [1, -0.5, 0.5, -0.25, 0] = 0.15
    assert approx(d["mean_pct"], 0.15, tol=1e-4), d["mean_pct"]
    assert approx(d["median_pct"], 0.0, tol=1e-9), d["median_pct"]


def test_min_max():
    d = compute_return_distribution(_curve([0.0, 2.0, -3.0, 1.0]))
    assert approx(d["min_pct"], -3.0), d
    assert approx(d["max_pct"], 2.0), d


def test_percentile_helper_linear_interpolation():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert approx(_percentile(vals, 0), 0.0)
    assert approx(_percentile(vals, 100), 4.0)
    assert approx(_percentile(vals, 50), 2.0)
    assert approx(_percentile(vals, 25), 1.0)


def test_percentiles_present_and_ordered():
    d = compute_return_distribution(_curve([0.0, 1.0, -0.5, 0.5, -0.25, 0.3, -0.1]))
    p = d["percentiles"]
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"], p


def test_histogram_buckets_sum_to_count():
    rets = [0.0, 1.0, -0.5, 0.5, -0.25, 0.3, -0.1, 0.8, -0.9, 0.2]
    d = compute_return_distribution(_curve(rets), bins=5)
    assert len(d["histogram"]) == 5, d["histogram"]
    total = sum(b["count"] for b in d["histogram"])
    assert total == d["count"], (total, d["count"])
    # buckets are contiguous and ascending
    for a, b in zip(d["histogram"], d["histogram"][1:]):
        assert approx(a["upper"], b["lower"], tol=1e-6), (a, b)


def test_histogram_identical_values_single_bucket():
    # All realised returns identical → degenerate single bucket holding all.
    d = compute_return_distribution(_curve([0.0, 0.3, 0.3, 0.3]), bins=10)
    assert len(d["histogram"]) == 1, d["histogram"]
    assert d["histogram"][0]["count"] == 3, d["histogram"]


def test_var_cvar_are_losses_non_positive():
    rets = [0.0, 0.5, -0.3, 0.4, -1.2, 0.2, -0.6, 0.1]
    d = compute_return_distribution(_curve(rets), confidence_levels=[95, 99])
    for c in ("95", "99"):
        assert d["var"][c] is not None and d["var"][c] <= 0.0, (c, d["var"])
        assert d["cvar"][c] is not None and d["cvar"][c] <= 0.0, (c, d["cvar"])
    # CVaR (mean of the tail) must be at least as bad as VaR (the quantile).
    assert d["cvar"]["95"] <= d["var"]["95"] + 1e-9, (d["cvar"], d["var"])


def test_all_positive_var_clamped_to_zero():
    # No losing days → VaR/CVaR are "no loss" → clamped to 0.0, never positive.
    d = compute_return_distribution(_curve([0.0, 0.5, 0.3, 0.7, 0.2]))
    assert d["var"]["95"] == 0.0, d["var"]
    assert d["cvar"]["95"] == 0.0, d["cvar"]


def test_custom_confidence_levels():
    d = compute_return_distribution(
        _curve([0.0, 0.5, -0.3, 0.4, -1.0]), confidence_levels=[90, 95, 99])
    assert d["confidence_levels"] == [90, 95, 99], d
    assert set(d["var"].keys()) == {"90", "95", "99"}, d["var"]


def test_skew_kurtosis_zero_spread_none():
    # Constant non-zero return → zero spread → skew/kurtosis undefined.
    d = compute_return_distribution(_curve([0.0, 0.3, 0.3, 0.3]))
    assert d["stdev_pct"] == 0.0, d
    assert d["skewness"] is None, d
    assert d["excess_kurtosis"] is None, d


def test_skew_sign_for_right_tail():
    # One big positive outlier → positive skew.
    d = compute_return_distribution(_curve([0.0, -0.1, -0.1, -0.1, 5.0]))
    assert d["skewness"] is not None and d["skewness"] > 0, d["skewness"]


def test_report_no_write_smoke():
    # Run against the real history file, compute-only (output_path=None).
    rep = generate_return_distribution_report(output_path=None)
    assert "distribution" in rep and "generated_at" in rep, rep
    dist = rep["distribution"]
    assert isinstance(dist["count"], int), rep
    # All present numeric scalar fields must be finite & JSON-serializable.
    for k, v in dist.items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)
    for c, v in dist["var"].items():
        assert v is None or math.isfinite(v), (c, v)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_return_distribution (SPA-V383)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_seed_day_no_returns)
    run("counts + central tendency", test_counts_and_central_tendency)
    run("min / max", test_min_max)
    run("percentile helper interpolation", test_percentile_helper_linear_interpolation)
    run("percentiles present + ordered", test_percentiles_present_and_ordered)
    run("histogram buckets sum to count", test_histogram_buckets_sum_to_count)
    run("histogram identical values → 1 bucket", test_histogram_identical_values_single_bucket)
    run("VaR/CVaR are losses (<=0)", test_var_cvar_are_losses_non_positive)
    run("all-positive → VaR clamped to 0", test_all_positive_var_clamped_to_zero)
    run("custom confidence levels", test_custom_confidence_levels)
    run("zero spread → skew/kurtosis None", test_skew_kurtosis_zero_spread_none)
    run("positive skew for right tail", test_skew_sign_for_right_tail)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
