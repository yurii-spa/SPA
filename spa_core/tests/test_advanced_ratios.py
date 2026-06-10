"""
Tests for the paper-trading advanced-ratios module (SPA-V397).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_risk_metrics.py / test_return_distribution.py).

Run::
    python spa_core/tests/test_advanced_ratios.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.advanced_ratios import (
    ANNUALIZATION_DAYS,
    TAIL_LOWER_PCT,
    TAIL_UPPER_PCT,
    _percentile,
    _underwater_curve,
    compute_advanced_ratios,
    generate_advanced_ratios_report,
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
    Note: drawdown_pct is left 0.0 — the module reconstructs its own underwater
    curve from the return series, so these tests exercise that path.
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


_SCHEMA_KEYS = {
    "num_return_days", "mar_annual_pct", "mar_daily_pct", "omega_ratio",
    "gain_to_pain_ratio", "tail_ratio", "common_sense_ratio", "profit_factor",
    "ulcer_index", "martin_ratio", "pain_index", "pain_ratio",
    "max_drawdown_pct", "annualized_return_pct", "tail_upper_pct",
    "tail_lower_pct", "annualization_days",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_advanced_ratios([])
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_return_days"] == 0, m
    assert m["omega_ratio"] is None, m
    assert m["ulcer_index"] is None, m
    assert m["annualization_days"] == ANNUALIZATION_DAYS, m


def test_single_seed_day_no_returns():
    m = compute_advanced_ratios(_curve([0.0]))  # only the seed bar
    assert m["num_return_days"] == 0, m
    assert m["omega_ratio"] is None, m


def test_schema_keys_on_real_shape():
    m = compute_advanced_ratios(_curve([0.0, 1.0, -0.5, 0.3]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()


def test_percentile_helper_interpolation():
    vals = [0.0, 10.0, 20.0, 30.0, 40.0]
    assert approx(_percentile(vals, 0), 0.0)
    assert approx(_percentile(vals, 100), 40.0)
    assert approx(_percentile(vals, 50), 20.0)
    assert _percentile([], 50) is None
    assert approx(_percentile([7.0], 50), 7.0)


def test_underwater_curve_non_positive_and_recovers():
    # up, down, down, up: drawdown should be 0 at the new peak, negative in dips.
    uw = _underwater_curve([1.0, -2.0, -1.0, 5.0])
    assert all(d <= 1e-9 for d in uw), uw
    assert uw[0] == 0.0 or approx(uw[0], 0.0), uw  # first bar makes a new peak
    assert uw[2] < 0.0, uw                          # underwater after two drops


def test_all_positive_no_losses_undefined_pain_ratios():
    m = compute_advanced_ratios(_curve([0.0, 1.0, 2.0, 0.5]))
    # No losing days → no downside → omega, gain_to_pain, profit_factor undefined.
    assert m["omega_ratio"] is None, m
    assert m["gain_to_pain_ratio"] is None, m
    assert m["profit_factor"] is None, m
    # Never underwater → ulcer/pain are 0, ratios divide by zero → None.
    assert approx(m["ulcer_index"], 0.0), m
    assert approx(m["pain_index"], 0.0), m
    assert m["martin_ratio"] is None, m
    assert m["pain_ratio"] is None, m
    assert approx(m["max_drawdown_pct"], 0.0), m


def test_gain_to_pain_known_value():
    # returns: +2, -1, +3, -1  → sum=3, sum_losses=-2 → GPR=3/2=1.5
    m = compute_advanced_ratios(_curve([0.0, 2.0, -1.0, 3.0, -1.0]))
    assert approx(m["gain_to_pain_ratio"], 1.5, tol=1e-3), m
    # profit_factor = (2+3)/|(-1-1)| = 5/2 = 2.5
    assert approx(m["profit_factor"], 2.5, tol=1e-3), m


def test_omega_gt_one_when_upside_dominates_at_zero_mar():
    # With MAR=0, more/larger gains than losses → omega > 1.
    m = compute_advanced_ratios(_curve([0.0, 2.0, -1.0, 3.0, -1.0]), mar_annual_pct=0.0)
    assert m["omega_ratio"] is not None and m["omega_ratio"] > 1.0, m


def test_omega_lt_one_when_downside_dominates():
    m = compute_advanced_ratios(_curve([0.0, 1.0, -2.0, 0.5, -3.0]), mar_annual_pct=0.0)
    assert m["omega_ratio"] is not None and m["omega_ratio"] < 1.0, m


def test_omega_at_zero_mar_equals_gain_to_pain_plus_one_relation():
    # At MAR=0: upside = sum(gains); downside = abs(sum(losses)).
    # omega = sum_gains/abs(sum_losses) = profit_factor exactly.
    m = compute_advanced_ratios(_curve([0.0, 2.0, -1.0, 3.0, -1.0]), mar_annual_pct=0.0)
    assert m["omega_ratio"] is not None and m["profit_factor"] is not None
    assert approx(m["omega_ratio"], m["profit_factor"], tol=1e-6), m


def test_higher_mar_lowers_omega():
    rets = [0.0, 2.0, -1.0, 3.0, -1.0]
    low = compute_advanced_ratios(_curve(rets), mar_annual_pct=0.0)["omega_ratio"]
    high = compute_advanced_ratios(_curve(rets), mar_annual_pct=50.0)["omega_ratio"]
    assert low is not None and high is not None, (low, high)
    assert high <= low, (low, high)


def test_tail_ratio_present_and_positive():
    m = compute_advanced_ratios(_curve([0.0, 3.0, -1.0, 2.0, -2.0, 1.0, -0.5, 4.0]))
    assert m["tail_ratio"] is not None and m["tail_ratio"] > 0, m
    assert m["tail_upper_pct"] == TAIL_UPPER_PCT, m
    assert m["tail_lower_pct"] == TAIL_LOWER_PCT, m


def test_common_sense_ratio_is_product():
    m = compute_advanced_ratios(_curve([0.0, 3.0, -1.0, 2.0, -2.0, 1.0, -0.5, 4.0]))
    if m["tail_ratio"] is not None and m["profit_factor"] is not None:
        assert approx(m["common_sense_ratio"], m["tail_ratio"] * m["profit_factor"], tol=1e-3), m


def test_ulcer_index_positive_with_drawdown():
    m = compute_advanced_ratios(_curve([0.0, -1.0, -2.0, 1.0]))
    assert m["ulcer_index"] > 0, m
    assert m["pain_index"] > 0, m
    assert m["max_drawdown_pct"] < 0, m


def test_ulcer_geq_pain_index():
    # RMS (ulcer) >= mean-abs (pain) for any non-trivial underwater series.
    m = compute_advanced_ratios(_curve([0.0, -1.0, -2.0, 1.0, -0.5, 0.2]))
    assert m["ulcer_index"] + 1e-9 >= m["pain_index"], m


def test_martin_sign_matches_return_sign():
    up = compute_advanced_ratios(_curve([0.0, 1.0, -0.5, 2.0, -0.3]))
    if up["martin_ratio"] is not None and up["annualized_return_pct"] is not None:
        assert (up["martin_ratio"] >= 0) == (up["annualized_return_pct"] >= 0), up
    down = compute_advanced_ratios(_curve([0.0, -1.0, 0.5, -2.0, -0.3]))
    if down["martin_ratio"] is not None and down["annualized_return_pct"] is not None:
        assert (down["martin_ratio"] >= 0) == (down["annualized_return_pct"] >= 0), down


def test_flat_zero_returns_stable():
    m = compute_advanced_ratios(_curve([0.0, 0.0, 0.0, 0.0]))
    assert m["num_return_days"] == 3, m
    assert approx(m["ulcer_index"], 0.0), m
    assert approx(m["max_drawdown_pct"], 0.0), m
    # No strictly-negative returns → loss-based ratios undefined.
    assert m["gain_to_pain_ratio"] is None, m


def test_all_finite_outputs():
    m = compute_advanced_ratios(_curve([0.0, 1.5, -1.2, 0.8, -0.4, 2.1, -3.0]))
    for k, v in m.items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)


def test_report_no_write_smoke_real_data():
    report = generate_advanced_ratios_report(output_path=None)
    assert "generated_at" in report and "metrics" in report, report
    assert set(report["metrics"].keys()) == _SCHEMA_KEYS, report["metrics"].keys()


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "advanced_ratios.json"
        generate_advanced_ratios_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir() if p.name.startswith(".advanced_ratios_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_advanced_ratios (SPA-V397)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_seed_day_no_returns)
    run("schema keys on real shape", test_schema_keys_on_real_shape)
    run("percentile helper interpolation", test_percentile_helper_interpolation)
    run("underwater curve <=0 and recovers", test_underwater_curve_non_positive_and_recovers)
    run("all-positive → pain/loss ratios undefined", test_all_positive_no_losses_undefined_pain_ratios)
    run("gain-to-pain / profit-factor known values", test_gain_to_pain_known_value)
    run("omega > 1 when upside dominates", test_omega_gt_one_when_upside_dominates_at_zero_mar)
    run("omega < 1 when downside dominates", test_omega_lt_one_when_downside_dominates)
    run("omega == profit_factor at MAR=0", test_omega_at_zero_mar_equals_gain_to_pain_plus_one_relation)
    run("higher MAR lowers omega", test_higher_mar_lowers_omega)
    run("tail ratio present + positive", test_tail_ratio_present_and_positive)
    run("common-sense ratio is product", test_common_sense_ratio_is_product)
    run("ulcer/pain positive with drawdown", test_ulcer_index_positive_with_drawdown)
    run("ulcer >= pain index", test_ulcer_geq_pain_index)
    run("martin sign matches return sign", test_martin_sign_matches_return_sign)
    run("flat zero returns stable", test_flat_zero_returns_stable)
    run("all outputs finite", test_all_finite_outputs)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
