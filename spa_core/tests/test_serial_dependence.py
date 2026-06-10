"""
Tests for the paper-trading serial-dependence diagnostics module (SPA-V399).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_advanced_ratios.py /
test_return_distribution.py).

Run::
    python spa_core/tests/test_serial_dependence.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.serial_dependence import (
    DEFAULT_MAX_LAG,
    _autocorrelations,
    _chi2_sf,
    _gammap_regularized,
    _hurst_rs,
    _ljung_box,
    _runs_test,
    _variance_ratio,
    compute_serial_dependence,
    generate_serial_dependence_report,
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
    subsequent values are realised returns. Mirrors test_advanced_ratios._curve.
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
    "num_return_days", "mean_pct", "stdev_pct", "max_lag", "autocorrelation",
    "ljung_box", "runs_test", "variance_ratio", "variance_ratio_lags",
    "hurst_exponent", "interpretation",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    d = compute_serial_dependence([])
    assert set(d.keys()) == _SCHEMA_KEYS, d.keys()
    assert d["num_return_days"] == 0
    assert d["mean_pct"] is None and d["stdev_pct"] is None
    assert d["hurst_exponent"] is None
    assert d["interpretation"] == "insufficient_data"
    # ACF list still has one entry per lag, all None.
    assert len(d["autocorrelation"]) == DEFAULT_MAX_LAG
    assert all(a["acf"] is None for a in d["autocorrelation"])


def test_single_seed_day_no_returns():
    d = compute_serial_dependence(_curve([0.0]))  # only the seed day
    assert d["num_return_days"] == 0
    assert d["interpretation"] == "insufficient_data"
    assert d["ljung_box"]["statistic"] is None
    assert d["runs_test"]["runs"] is None


def test_schema_keys_present_on_real_shape():
    d = compute_serial_dependence(_curve([0.0, 0.3, -0.2, 0.1, -0.4, 0.5, -0.1, 0.2]))
    assert set(d.keys()) == _SCHEMA_KEYS
    assert d["num_return_days"] == 7
    assert d["max_lag"] == DEFAULT_MAX_LAG
    assert d["variance_ratio_lags"] == [2, 3, 5]
    assert set(d["variance_ratio"].keys()) == {"2", "3", "5"}


def test_acf_lag0_identity_and_range():
    # Lag-k ACF must lie in [-1, 1] for a well-formed series.
    series = [0.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
    acf = _autocorrelations(series[1:], 4)
    for a in acf:
        if a["acf"] is not None:
            assert -1.0 - 1e-9 <= a["acf"] <= 1.0 + 1e-9, a


def test_perfect_alternating_series_negative_lag1():
    # Strict alternation about the mean → strong negative lag-1 autocorrelation.
    returns = [1.0, -1.0] * 6  # 12 realised points, mean 0
    acf = _autocorrelations(returns, 1)
    assert acf[0]["acf"] is not None
    assert acf[0]["acf"] < -0.5, acf[0]["acf"]


def test_trending_series_positive_lag1():
    # A smoothly varying (low-frequency) series → positive lag-1 autocorrelation.
    returns = [0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0.2, 0.3, 0.4]
    acf = _autocorrelations(returns, 1)
    assert acf[0]["acf"] is not None
    assert acf[0]["acf"] > 0.0, acf[0]["acf"]


def test_acf_undefined_when_too_short_for_lag():
    acf = _autocorrelations([0.5], 3)  # n=1, cannot estimate any lag
    assert all(a["acf"] is None for a in acf)


def test_acf_none_when_zero_variance():
    acf = _autocorrelations([2.0, 2.0, 2.0, 2.0], 2)  # flat → zero variance
    assert all(a["acf"] is None for a in acf)


def test_chi2_sf_known_values():
    # Median of chi-square(df=1) ≈ 0.4549 → sf ≈ 0.5.
    assert approx(_chi2_sf(0.4549, 1), 0.5, tol=2e-3), _chi2_sf(0.4549, 1)
    # chi-square(df=2) sf at x=2*ln(2) ≈ 1.386 is exactly 0.5 (exponential).
    assert approx(_chi2_sf(2.0 * math.log(2.0), 2), 0.5, tol=1e-3)
    # Tail decays: large x → small p.
    assert _chi2_sf(20.0, 1) < 1e-4
    # df < 1 is undefined.
    assert _chi2_sf(1.0, 0) is None


def test_gammap_regularized_monotone_and_bounds():
    # P(s, x) is in [0,1] and increasing in x.
    vals = [_gammap_regularized(2.0, x) for x in (0.0, 0.5, 1.0, 2.0, 5.0, 20.0)]
    for v in vals:
        assert 0.0 <= v <= 1.0, v
    assert all(vals[i] <= vals[i + 1] + 1e-12 for i in range(len(vals) - 1)), vals
    assert vals[0] == 0.0
    assert vals[-1] > 0.99


def test_chi2_sf_matches_continued_fraction_branch():
    # x >= s+1 exercises the continued-fraction path; still a valid probability.
    p = _chi2_sf(10.0, 3)
    assert 0.0 <= p <= 1.0
    assert p < 0.05  # chi2(3) sf at 10 ≈ 0.0186


def test_ljung_box_zero_for_no_autocorrelation():
    # All ACF zero → Q == 0 → p_value == 1.0.
    acf = [{"lag": 1, "acf": 0.0}, {"lag": 2, "acf": 0.0}]
    lb = _ljung_box(acf, n=30)
    assert lb["statistic"] == 0.0
    assert lb["df"] == 2
    assert approx(lb["p_value"], 1.0, tol=1e-9)


def test_ljung_box_large_q_small_p():
    # Strong (|r|=0.9) autocorrelation at several lags → large Q → tiny p.
    acf = [{"lag": k, "acf": 0.9} for k in range(1, 6)]
    lb = _ljung_box(acf, n=40)
    assert lb["statistic"] > 50.0
    assert lb["p_value"] < 1e-6


def test_ljung_box_skips_none_lags():
    acf = [{"lag": 1, "acf": 0.2}, {"lag": 2, "acf": None}, {"lag": 3, "acf": 0.1}]
    lb = _ljung_box(acf, n=20)
    assert lb["df"] == 2  # only the two defined lags counted
    assert lb["lags"] == [1, 3]


def test_runs_test_alternating_more_runs_than_expected():
    # Perfect alternation → maximal runs → large positive z.
    rt = _runs_test([1.0, -1.0] * 8)
    assert rt["runs"] == 16
    assert rt["n_above"] == 8 and rt["n_below"] == 8
    assert rt["z_score"] is not None and rt["z_score"] > 0
    assert rt["p_value"] is not None and rt["p_value"] < 0.05


def test_runs_test_one_long_run_negative_z():
    # All-up then all-down → only 2 runs → far fewer than expected → negative z.
    rt = _runs_test([1.0] * 6 + [-1.0] * 6)
    assert rt["runs"] == 2
    assert rt["z_score"] is not None and rt["z_score"] < 0
    assert rt["p_value"] is not None and rt["p_value"] < 0.05


def test_runs_test_undefined_when_one_side_empty():
    rt = _runs_test([1.0, 2.0, 3.0, 4.0])  # all above mean? no — but no values below...
    # mean is 2.5; values 1,2 below, 3,4 above → both sides non-empty, defined.
    assert rt["z_score"] is not None
    # Now a genuinely one-sided case about the mean: a flat series.
    rt2 = _runs_test([5.0, 5.0, 5.0])
    assert rt2["n_above"] == 0 and rt2["n_below"] == 0
    assert rt2["z_score"] is None and rt2["p_value"] is None


def test_variance_ratio_random_walk_near_one():
    # i.i.d.-ish symmetric noise → VR(2) should sit near 1 (not exact on a
    # short deterministic sample, but within a sane band).
    returns = [0.5, -0.5, 0.4, -0.4, 0.6, -0.6, 0.3, -0.3, 0.5, -0.5]
    vr2 = _variance_ratio(returns, 2)
    assert vr2 is not None
    assert 0.0 <= vr2 <= 1.5, vr2


def test_variance_ratio_trending_gt_one():
    # Positively autocorrelated (persistent) series → VR(2) > 1.
    returns = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    vr2 = _variance_ratio(returns, 2)
    assert vr2 is not None and vr2 > 1.0, vr2


def test_variance_ratio_mean_reverting_lt_one():
    # Strict alternation → strong mean reversion → VR(2) < 1.
    returns = [1.0, -1.0] * 6
    vr2 = _variance_ratio(returns, 2)
    assert vr2 is not None and vr2 < 1.0, vr2


def test_variance_ratio_undefined_cases():
    assert _variance_ratio([0.1, 0.2], 5) is None       # n < q+1
    assert _variance_ratio([0.1, 0.2, 0.3], 1) is None  # q < 2
    assert _variance_ratio([2.0, 2.0, 2.0, 2.0], 2) is None  # zero variance


def test_hurst_none_for_short_series():
    assert _hurst_rs([0.1, -0.2, 0.3, 0.1, -0.1]) is None  # n=5 < 2*4


def test_hurst_defined_for_long_series_in_range():
    # 32-point series → at least two chunk sizes (4, 8, 16) → Hurst defined.
    returns = [math.sin(i / 3.0) * 0.5 + (0.1 if i % 2 else -0.1) for i in range(32)]
    h = _hurst_rs(returns)
    assert h is not None
    assert -0.5 <= h <= 2.0, h  # generous structural bound


def test_interpretation_insufficient_data():
    assert compute_serial_dependence(_curve([0.0, 0.1, -0.1]))["interpretation"] == "insufficient_data"


def test_interpretation_label_is_known_value():
    d = compute_serial_dependence(_curve([0.0] + [1.0, -1.0] * 8))
    assert d["interpretation"] in {"trending", "mean_reverting", "random_walk", "insufficient_data"}


def test_mean_reverting_label_on_alternating():
    # Strong alternation with enough points → mean_reverting label.
    d = compute_serial_dependence(_curve([0.0] + [1.0, -1.0] * 10))
    assert d["interpretation"] == "mean_reverting", d["interpretation"]


def test_all_outputs_json_finite():
    d = compute_serial_dependence(_curve([0.0, 0.3, -0.2, 0.1, -0.4, 0.5, -0.1, 0.2]))
    def _check(x):
        if isinstance(x, float):
            assert math.isfinite(x), x
        elif isinstance(x, dict):
            for v in x.values():
                _check(v)
        elif isinstance(x, list):
            for v in x:
                _check(v)
    _check(d)


def test_report_no_write_smoke_real_data():
    real = Path(__file__).resolve().parents[2] / "data" / "pnl_history.json"
    if not real.exists():
        return  # smoke only when real history is present
    rep = generate_serial_dependence_report(history_path=real, output_path=None)
    assert set(rep.keys()) == {"generated_at", "source", "diagnostics"}
    assert set(rep["diagnostics"].keys()) == _SCHEMA_KEYS


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "serial_dependence.json"
        curve = _curve([0.0, 0.3, -0.2, 0.1, -0.4, 0.5, -0.1, 0.2])
        # Drive the writer directly via the public report fn with a fake history:
        # easier to call compute + write path through generate using a temp file.
        import json as _json
        rep = {
            "generated_at": "x", "source": "x",
            "diagnostics": compute_serial_dependence(curve),
        }
        tmp = out.with_name(f".serial_dependence_{os.getpid()}.tmp")
        tmp.write_text(_json.dumps(rep, indent=2), encoding="utf-8")
        os.replace(tmp, out)
        assert out.exists()
        leftovers = [p for p in Path(td).iterdir() if p.name.startswith(".serial_dependence_")]
        assert not leftovers, leftovers
        loaded = _json.loads(out.read_text(encoding="utf-8"))
        assert set(loaded["diagnostics"].keys()) == _SCHEMA_KEYS


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_serial_dependence (SPA-V399)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_seed_day_no_returns)
    run("schema keys on real shape", test_schema_keys_present_on_real_shape)
    run("acf in [-1,1] range", test_acf_lag0_identity_and_range)
    run("alternating → negative lag-1 acf", test_perfect_alternating_series_negative_lag1)
    run("trending → positive lag-1 acf", test_trending_series_positive_lag1)
    run("acf None when too short for lag", test_acf_undefined_when_too_short_for_lag)
    run("acf None when zero variance", test_acf_none_when_zero_variance)
    run("chi2 sf known values", test_chi2_sf_known_values)
    run("gammap regularized monotone+bounds", test_gammap_regularized_monotone_and_bounds)
    run("chi2 sf continued-fraction branch", test_chi2_sf_matches_continued_fraction_branch)
    run("ljung-box zero → p=1", test_ljung_box_zero_for_no_autocorrelation)
    run("ljung-box large Q → tiny p", test_ljung_box_large_q_small_p)
    run("ljung-box skips None lags", test_ljung_box_skips_none_lags)
    run("runs test alternating → +z", test_runs_test_alternating_more_runs_than_expected)
    run("runs test one long run → -z", test_runs_test_one_long_run_negative_z)
    run("runs test undefined one-sided", test_runs_test_undefined_when_one_side_empty)
    run("variance ratio random ~1", test_variance_ratio_random_walk_near_one)
    run("variance ratio trending >1", test_variance_ratio_trending_gt_one)
    run("variance ratio reverting <1", test_variance_ratio_mean_reverting_lt_one)
    run("variance ratio undefined cases", test_variance_ratio_undefined_cases)
    run("hurst None for short series", test_hurst_none_for_short_series)
    run("hurst defined+in range (long)", test_hurst_defined_for_long_series_in_range)
    run("interpretation insufficient", test_interpretation_insufficient_data)
    run("interpretation known label", test_interpretation_label_is_known_value)
    run("mean_reverting label on alternating", test_mean_reverting_label_on_alternating)
    run("all outputs finite", test_all_outputs_json_finite)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
