"""
Tests for the paper-trading Monte Carlo projection module (SPA-V395).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_return_distribution.py /
test_benchmark_comparison.py).

Run::
    python spa_core/tests/test_monte_carlo_projection.py
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics_lab.monte_carlo_projection import (
    DEFAULT_CONFIDENCE_LEVELS,
    compute_monte_carlo_projection,
    generate_monte_carlo_report,
    _percentile,
    _band_day_indices,
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
    equity = 10000.0
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
    p = compute_monte_carlo_projection([], num_simulations=100, horizon_days=10)
    assert p["inputs"]["num_historical_returns"] == 0, p
    # Default fallback start equity when there is no curve.
    assert p["inputs"]["start_equity"] == 10000.0, p
    assert "terminal_equity" in p and "terminal_return_pct" in p, p
    assert p["probability_of_profit"] is None, p
    assert p["probability_of_loss"] is None, p
    assert p["equity_percentile_bands"] == [], p


def test_single_seed_day_no_returns():
    p = compute_monte_carlo_projection(_curve([0.0]), num_simulations=100)
    assert p["inputs"]["num_historical_returns"] == 0, p
    # Terminal equity falls back to start equity at every percentile.
    se = p["inputs"]["start_equity"]
    assert p["terminal_equity"]["p50"] == se, p
    assert p["probability_of_profit"] is None, p


def test_determinism_same_seed():
    curve = _curve([0.0, 1.0, -0.5, 0.8, -0.3, 0.4])
    a = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=20, seed=7)
    b = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=20, seed=7)
    assert a == b, "same seed must produce identical result"


def test_determinism_different_seed():
    curve = _curve([0.0, 1.0, -0.5, 0.8, -0.3, 0.4])
    a = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=20, seed=1)
    b = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=20, seed=2)
    assert a["terminal_equity"]["p50"] != b["terminal_equity"]["p50"], (a, b)


def test_default_start_equity_from_last_close():
    curve = _curve([0.0, 1.0, 2.0])
    expected = curve[-1]["close_equity"]
    p = compute_monte_carlo_projection(curve, num_simulations=200, seed=3)
    assert approx(p["inputs"]["start_equity"], round(expected, 2), tol=0.01), p["inputs"]


def test_explicit_start_equity_respected():
    curve = _curve([0.0, 1.0, -0.5])
    p = compute_monte_carlo_projection(curve, num_simulations=200, start_equity=50000.0, seed=3)
    assert p["inputs"]["start_equity"] == 50000.0, p["inputs"]


def test_positive_history_median_reasonable():
    # All positive realised returns → median terminal equity should be > start
    # and not absurdly large for a 30-day horizon of small returns.
    curve = _curve([0.0, 0.5, 0.4, 0.6, 0.3, 0.5])
    p = compute_monte_carlo_projection(curve, num_simulations=2000, horizon_days=30, seed=11)
    start = p["inputs"]["start_equity"]
    p50 = p["terminal_equity"]["p50"]
    assert p50 > start, (p50, start)
    # ~0.5%/day for 30 days ~ +16%, well under +100%.
    assert p50 < start * 2.0, (p50, start)


def test_all_zero_returns_terminal_equals_start():
    curve = _curve([0.0, 0.0, 0.0, 0.0, 0.0])
    p = compute_monte_carlo_projection(curve, num_simulations=300, horizon_days=15, seed=5)
    se = p["inputs"]["start_equity"]
    for key in ("p5", "p25", "p50", "p75", "p95", "mean", "min", "max"):
        assert approx(p["terminal_equity"][key], se, tol=1e-6), (key, p["terminal_equity"])
    assert p["probability_of_profit"] == 0.0, p
    assert p["probability_of_loss"] == 0.0, p


def test_all_positive_prob_profit_one():
    curve = _curve([0.0, 0.5, 0.3, 0.7, 0.2])
    p = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=10, seed=9)
    assert p["probability_of_profit"] == 1.0, p
    assert p["probability_of_loss"] == 0.0, p


def test_all_negative_prob_loss_one():
    curve = _curve([0.0, -0.5, -0.3, -0.7, -0.2])
    p = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=10, seed=9)
    assert p["probability_of_loss"] == 1.0, p
    assert p["probability_of_profit"] == 0.0, p


def test_terminal_percentiles_monotonic():
    curve = _curve([0.0, 1.0, -0.8, 0.6, -1.2, 0.9, -0.4])
    p = compute_monte_carlo_projection(curve, num_simulations=2000, horizon_days=25, seed=13)
    te = p["terminal_equity"]
    assert te["p5"] <= te["p25"] <= te["p50"] <= te["p75"] <= te["p95"], te


def test_expected_max_drawdown_non_positive():
    curve = _curve([0.0, 1.0, -0.8, 0.6, -1.2, 0.9])
    p = compute_monte_carlo_projection(curve, num_simulations=1000, horizon_days=20, seed=17)
    assert p["expected_max_drawdown_pct"] is not None, p
    assert p["expected_max_drawdown_pct"] <= 0.0, p["expected_max_drawdown_pct"]


def test_zero_horizon_stable():
    curve = _curve([0.0, 1.0, -0.5, 0.4])
    p = compute_monte_carlo_projection(curve, num_simulations=100, horizon_days=0, seed=1)
    se = p["inputs"]["start_equity"]
    assert p["terminal_equity"]["p50"] == se, p
    assert p["equity_percentile_bands"] == [], p


def test_zero_simulations_stable():
    curve = _curve([0.0, 1.0, -0.5, 0.4])
    p = compute_monte_carlo_projection(curve, num_simulations=0, horizon_days=10, seed=1)
    se = p["inputs"]["start_equity"]
    assert p["terminal_equity"]["p50"] == se, p
    assert p["probability_of_profit"] is None, p


def test_bands_present_and_ordered():
    curve = _curve([0.0, 1.0, -0.8, 0.6, -1.2, 0.9, -0.4])
    p = compute_monte_carlo_projection(curve, num_simulations=2000, horizon_days=30, seed=21)
    bands = p["equity_percentile_bands"]
    assert len(bands) > 0, "bands must be non-empty for valid input"
    for b in bands:
        assert b["p5"] <= b["p50"] <= b["p95"], b
        assert 1 <= b["day"] <= 30, b
    # Bands terminate at the horizon.
    assert bands[-1]["day"] == 30, bands[-1]


def test_terminal_return_sign_consistent():
    curve = _curve([0.0, 0.5, 0.3, 0.7, 0.2])  # all positive
    p = compute_monte_carlo_projection(curve, num_simulations=500, horizon_days=10, seed=9)
    # Positive history → median terminal return % should be positive, and the
    # sign should agree with terminal equity vs start.
    start = p["inputs"]["start_equity"]
    assert p["terminal_return_pct"]["p50"] > 0, p["terminal_return_pct"]
    assert (p["terminal_equity"]["p50"] > start) == (p["terminal_return_pct"]["p50"] > 0), p


def test_percentile_helper():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert approx(_percentile(vals, 0.0), 0.0)
    assert approx(_percentile(vals, 1.0), 4.0)
    assert approx(_percentile(vals, 0.5), 2.0)
    assert approx(_percentile(vals, 0.25), 1.0)


def test_band_day_indices_caps_and_includes_horizon():
    idx = _band_day_indices(30, 10)
    assert len(idx) <= 10, idx
    assert idx[-1] == 30, idx
    assert idx[0] >= 1, idx
    # Short horizon → one point per day.
    assert _band_day_indices(5, 10) == [1, 2, 3, 4, 5]


def test_default_confidence_keys_present():
    curve = _curve([0.0, 1.0, -0.5, 0.4])
    p = compute_monte_carlo_projection(curve, num_simulations=300, horizon_days=10, seed=1)
    for level in DEFAULT_CONFIDENCE_LEVELS:
        key = "p" + format(level * 100.0, "g")
        assert key in p["terminal_equity"], (key, p["terminal_equity"])


def test_report_write_to_tmp():
    # generate_*_report must write a valid JSON file atomically.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "mc.json"
        rep = generate_monte_carlo_report(
            out_path=out, num_simulations=300, horizon_days=10, seed=42)
        assert out.exists(), "report file must be written"
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert "projection" in loaded and "generated_at" in loaded, loaded
        assert loaded["projection"]["inputs"]["seed"] == 42, loaded
        # round-trips identically to the returned dict
        assert loaded["projection"]["inputs"] == rep["projection"]["inputs"], loaded


def test_report_smoke_real_history():
    # Run against the real history file, compute-only (out_path=None).
    rep = generate_monte_carlo_report(out_path=None, num_simulations=500, seed=42)
    assert "projection" in rep and "generated_at" in rep, rep
    proj = rep["projection"]
    assert isinstance(proj["inputs"]["num_historical_returns"], int), rep
    # All present numeric scalars must be finite & JSON-serializable.
    for block in ("terminal_equity", "terminal_return_pct"):
        for k, v in proj[block].items():
            if isinstance(v, float):
                assert math.isfinite(v), (block, k, v)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_monte_carlo_projection (SPA-V395)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_seed_day_no_returns)
    run("determinism: same seed identical", test_determinism_same_seed)
    run("determinism: different seed differs", test_determinism_different_seed)
    run("default start equity = last close", test_default_start_equity_from_last_close)
    run("explicit start equity respected", test_explicit_start_equity_respected)
    run("positive history → reasonable median", test_positive_history_median_reasonable)
    run("all-zero returns → terminal == start", test_all_zero_returns_terminal_equals_start)
    run("all-positive → P(profit)=1", test_all_positive_prob_profit_one)
    run("all-negative → P(loss)=1", test_all_negative_prob_loss_one)
    run("terminal percentiles monotonic", test_terminal_percentiles_monotonic)
    run("expected max drawdown <= 0", test_expected_max_drawdown_non_positive)
    run("horizon=0 → stable", test_zero_horizon_stable)
    run("simulations=0 → stable", test_zero_simulations_stable)
    run("bands present + ordered", test_bands_present_and_ordered)
    run("terminal return sign consistent", test_terminal_return_sign_consistent)
    run("percentile helper", test_percentile_helper)
    run("band day indices cap + horizon", test_band_day_indices_caps_and_includes_horizon)
    run("default confidence keys present", test_default_confidence_keys_present)
    run("report write to tmp dir", test_report_write_to_tmp)
    run("report smoke (real data)", test_report_smoke_real_history)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
