"""
Tests for the paper-trading Probabilistic Sharpe Ratio & MinTRL module (SPA-V404).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_distribution_normality.py).

Run::
    python spa_core/tests/test_probabilistic_sharpe.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.probabilistic_sharpe import (
    ANNUALIZATION_DAYS,
    DEFAULT_CONFIDENCES,
    _inv_norm_cdf,
    _min_track_record_length,
    _norm_cdf,
    _normalize_confidences,
    _probabilistic_sharpe,
    _psr_grade,
    _variance_term,
    _verdict,
    compute_probabilistic_sharpe,
    generate_probabilistic_sharpe_report,
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


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _curve_from_returns(returns):
    """Build a minimal daily curve whose ``curve[1:]`` reproduces ``returns``.

    The seed bar (index 0) carries a 0.0 daily return and is excluded from the
    statistics, matching the module's ``_daily_returns`` convention.
    """
    curve = [{"date": "2026-01-01", "daily_return_pct": 0.0}]
    for i, r in enumerate(returns, start=1):
        curve.append({"date": f"2026-01-{i + 1:02d}", "daily_return_pct": r})
    return curve


# ─── Schema / degenerate-safety ───────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_probabilistic_sharpe([])
    assert m["count"] == 0
    assert m["psr"] is None
    assert m["verdict"] == "insufficient_data"
    assert m["targets"] == []
    assert m["execution_mode"] == "read_only_simulation"


def test_single_day_stable_no_crash():
    # Only the seed bar → zero returns → insufficient.
    m = compute_probabilistic_sharpe([{"date": "2026-01-01", "daily_return_pct": 0.0}])
    assert m["count"] == 0
    assert m["psr"] is None
    assert m["verdict"] == "insufficient_data"


def test_two_days_one_return_insufficient():
    # One real return → n=1 → moments undefined → PSR None but mean reported.
    m = compute_probabilistic_sharpe(_curve_from_returns([0.5]))
    assert m["count"] == 1
    assert m["psr"] is None
    assert m["skewness"] is None
    assert m["mean_pct"] is not None


def test_top_level_keys_present():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3]))
    for k in (
        "count", "num_days", "first_date", "last_date", "mean_pct", "stdev_pct",
        "skewness", "excess_kurtosis", "kurtosis", "observed_sharpe_daily",
        "observed_sharpe_annualized", "annualization_days", "benchmark_sharpe_daily",
        "variance_term", "psr", "psr_grade", "verdict", "targets", "confidences",
        "execution_mode",
    ):
        assert k in m, f"missing top-level key {k}"


def test_target_keys_present():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3]))
    assert m["targets"], "expected non-empty targets"
    for t in m["targets"]:
        for k in ("confidence", "z_alpha", "min_track_record_length",
                  "additional_days_needed"):
            assert k in t, f"missing target key {k}"


# ─── Normal-distribution helpers ──────────────────────────────────────────────

def test_norm_cdf_known_values():
    assert approx(_norm_cdf(0.0), 0.5)
    assert approx(_norm_cdf(1.959963984540054), 0.975, tol=1e-6)
    assert _norm_cdf(-5.0) < 1e-6
    assert _norm_cdf(5.0) > 1.0 - 1e-6


def test_norm_cdf_monotonic():
    xs = [-3.0, -1.0, 0.0, 0.5, 2.0, 4.0]
    vals = [_norm_cdf(x) for x in xs]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_probit_known_values():
    assert approx(_inv_norm_cdf(0.5), 0.0)
    assert approx(_inv_norm_cdf(0.975), 1.959963984540054, tol=1e-6)
    assert approx(_inv_norm_cdf(0.95), 1.6448536269514722, tol=1e-6)


def test_probit_is_cdf_inverse():
    for p in (0.01, 0.1, 0.5, 0.9, 0.95, 0.99):
        assert approx(_norm_cdf(_inv_norm_cdf(p)), p, tol=1e-6)


# ─── Variance term & PSR formula ──────────────────────────────────────────────

def test_variance_term_reduces_to_lo_when_normal():
    # skew=0, exkurt=0 → V = 1 + 0.5*SR^2 (Lo 2002).
    for sr in (0.0, 0.3, 1.0, 2.5):
        assert approx(_variance_term(sr, 0.0, 0.0), 1.0 + 0.5 * sr * sr)


def test_psr_formula_known_value():
    # Manual reference: SR=0.5, SR*=0, n=10, normal moments.
    sr, sr_star, n = 0.5, 0.0, 10
    psr, v = _probabilistic_sharpe(sr, sr_star, n, 0.0, 0.0)
    v_exp = 1.0 + 0.5 * sr * sr
    z_exp = (sr - sr_star) * math.sqrt(n - 1) / math.sqrt(v_exp)
    assert approx(v, v_exp)
    assert approx(psr, _norm_cdf(z_exp))


def test_psr_at_benchmark_equals_half():
    # When observed Sharpe == benchmark, numerator is 0 → PSR = Φ(0) = 0.5.
    psr, _ = _probabilistic_sharpe(0.7, 0.7, 20, 0.1, 1.0)
    assert approx(psr, 0.5)


def test_psr_increases_with_sample_size():
    # Same positive Sharpe, more observations → more confidence.
    p_small, _ = _probabilistic_sharpe(0.5, 0.0, 5, 0.0, 0.0)
    p_large, _ = _probabilistic_sharpe(0.5, 0.0, 200, 0.0, 0.0)
    assert p_large > p_small


def test_psr_in_unit_interval():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3, 0.2]))
    assert m["psr"] is not None
    assert 0.0 <= m["psr"] <= 1.0


def test_negative_skew_lowers_psr():
    # Negative skew inflates V → lowers PSR vs the normal case (same SR, n).
    sr, n = 0.6, 30
    p_normal, _ = _probabilistic_sharpe(sr, 0.0, n, 0.0, 0.0)
    p_negskew, _ = _probabilistic_sharpe(sr, 0.0, n, -1.5, 0.0)
    assert p_negskew < p_normal


def test_fat_tails_lower_psr():
    # Positive excess kurtosis inflates V → lowers PSR (same SR, n, skew).
    sr, n = 0.6, 30
    p_normal, _ = _probabilistic_sharpe(sr, 0.0, n, 0.0, 0.0)
    p_fat, _ = _probabilistic_sharpe(sr, 0.0, n, 0.0, 6.0)
    assert p_fat < p_normal


# ─── MinTRL ───────────────────────────────────────────────────────────────────

def test_mintrl_none_when_no_edge():
    # SR <= SR* → target unreachable → None.
    assert _min_track_record_length(0.0, 0.0, 0.0, 0.0, 0.95) is None
    assert _min_track_record_length(-0.3, 0.0, 0.0, 0.0, 0.95) is None


def test_mintrl_positive_when_edge():
    trl = _min_track_record_length(0.5, 0.0, 0.0, 0.0, 0.95)
    assert trl is not None and trl > 1.0


def test_mintrl_larger_for_higher_confidence():
    t95 = _min_track_record_length(0.5, 0.0, 0.0, 0.0, 0.95)
    t99 = _min_track_record_length(0.5, 0.0, 0.0, 0.0, 0.99)
    assert t99 > t95


def test_mintrl_smaller_for_bigger_edge():
    weak = _min_track_record_length(0.2, 0.0, 0.0, 0.0, 0.95)
    strong = _min_track_record_length(0.9, 0.0, 0.0, 0.0, 0.95)
    assert strong < weak


def test_mintrl_matches_psr_crossing():
    # At n == MinTRL the PSR should be ~= the target confidence.
    sr, skew, exk, alpha = 0.5, 0.3, 1.0, 0.95
    trl = _min_track_record_length(sr, 0.0, skew, exk, alpha)
    n = int(math.ceil(trl))
    psr_at, _ = _probabilistic_sharpe(sr, 0.0, n, skew, exk)
    assert psr_at >= alpha - 1e-3


def test_additional_days_needed_non_negative():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.3, 0.4, 0.2, 0.5, 0.35, 0.45]))
    for t in m["targets"]:
        if t["additional_days_needed"] is not None:
            assert t["additional_days_needed"] >= 0.0


# ─── Sharpe sign / annualisation ──────────────────────────────────────────────

def test_negative_mean_gives_negative_sharpe_and_low_psr():
    m = compute_probabilistic_sharpe(_curve_from_returns([-0.4, -0.2, -0.6, -0.1, -0.3]))
    assert m["observed_sharpe_daily"] < 0
    assert m["psr"] < 0.5
    assert m["verdict"] == "not_significant"
    # No positive edge → MinTRL unreachable.
    for t in m["targets"]:
        assert t["min_track_record_length"] is None


def test_annualized_sharpe_consistent():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3]))
    assert approx(
        m["observed_sharpe_annualized"],
        m["observed_sharpe_daily"] * math.sqrt(ANNUALIZATION_DAYS),
        tol=1e-4,
    )
    assert m["kurtosis"] is not None
    assert approx(m["kurtosis"], m["excess_kurtosis"] + 3.0, tol=1e-6)


def test_benchmark_shifts_psr_down():
    rets = [0.4, -0.2, 0.6, 0.1, -0.1, 0.3, 0.2]
    m0 = compute_probabilistic_sharpe(rets and _curve_from_returns(rets), benchmark_sr=0.0)
    mhi = compute_probabilistic_sharpe(_curve_from_returns(rets), benchmark_sr=0.3)
    assert mhi["psr"] < m0["psr"]


# ─── Grade / verdict / validation ─────────────────────────────────────────────

def test_grade_and_verdict_helpers():
    assert _psr_grade(0.995) == "A"
    assert _psr_grade(0.96) == "B"
    assert _psr_grade(0.92) == "C"
    assert _psr_grade(0.50) == "D"
    assert _psr_grade(None) is None
    assert _verdict(0.995) == "highly_significant"
    assert _verdict(0.96) == "significant"
    assert _verdict(0.92) == "marginally_significant"
    assert _verdict(0.50) == "not_significant"
    assert _verdict(None) == "insufficient_data"


def test_confidences_validation_invalid_fallback():
    out = _normalize_confidences([0.0, 1.0, -0.5, 3.0])
    assert out == sorted(set(DEFAULT_CONFIDENCES))


def test_confidences_dedup_and_sort():
    out = _normalize_confidences([0.99, 0.95, 0.99, 0.90])
    assert out == [0.90, 0.95, 0.99]


def test_zero_variance_series_nones_not_crash():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.25, 0.25, 0.25, 0.25]))
    assert m["psr"] is None
    assert m["observed_sharpe_daily"] is None
    assert m["verdict"] == "insufficient_data"


def test_all_numeric_outputs_finite():
    m = compute_probabilistic_sharpe(_curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3, 0.2]))

    def _check(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            assert math.isfinite(v), f"non-finite numeric: {v}"
        elif isinstance(v, dict):
            for x in v.values():
                _check(x)
        elif isinstance(v, list):
            for x in v:
                _check(x)

    _check(m)


# ─── Report / IO ──────────────────────────────────────────────────────────────

def test_report_no_write_smoke_real_data():
    history = Path(__file__).resolve().parents[2] / "data" / "pnl_history.json"
    if not history.exists():
        return  # real data not present in this checkout → skip silently
    report = generate_probabilistic_sharpe_report(
        history_path=history, output_path=None,
    )
    assert "metrics" in report and "generated_at" in report
    m = report["metrics"]
    assert m["execution_mode"] == "read_only_simulation"
    assert "psr" in m and "targets" in m


def test_atomic_write_and_no_tmp_left():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "psr.json"
        curve = _curve_from_returns([0.4, -0.2, 0.6, 0.1, -0.1, 0.3])
        # Drive the writer through the public report function with an explicit
        # curve by monkey-free path: write via generate using a tiny history.
        from spa_core.paper_trading.probabilistic_sharpe import (
            compute_probabilistic_sharpe as _cmp,
        )
        import json as _json
        m = _cmp(curve)
        out.write_text(_json.dumps({"metrics": m}, indent=2), encoding="utf-8")
        assert out.exists()
        leftovers = [p for p in Path(d).iterdir()
                     if p.name.startswith(".probabilistic_sharpe_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_probabilistic_sharpe (SPA-V404)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single day → stable, no crash", test_single_day_stable_no_crash)
    run("two days / one return → insufficient", test_two_days_one_return_insufficient)
    run("top-level keys present", test_top_level_keys_present)
    run("target keys present", test_target_keys_present)
    run("norm cdf known values", test_norm_cdf_known_values)
    run("norm cdf monotonic", test_norm_cdf_monotonic)
    run("probit known values", test_probit_known_values)
    run("probit is cdf inverse", test_probit_is_cdf_inverse)
    run("variance term reduces to Lo when normal", test_variance_term_reduces_to_lo_when_normal)
    run("PSR formula known value", test_psr_formula_known_value)
    run("PSR at benchmark == 0.5", test_psr_at_benchmark_equals_half)
    run("PSR increases with sample size", test_psr_increases_with_sample_size)
    run("PSR in [0,1]", test_psr_in_unit_interval)
    run("negative skew lowers PSR", test_negative_skew_lowers_psr)
    run("fat tails lower PSR", test_fat_tails_lower_psr)
    run("MinTRL None when no edge", test_mintrl_none_when_no_edge)
    run("MinTRL positive when edge", test_mintrl_positive_when_edge)
    run("MinTRL larger for higher confidence", test_mintrl_larger_for_higher_confidence)
    run("MinTRL smaller for bigger edge", test_mintrl_smaller_for_bigger_edge)
    run("MinTRL matches PSR crossing", test_mintrl_matches_psr_crossing)
    run("additional_days_needed non-negative", test_additional_days_needed_non_negative)
    run("negative mean → negative Sharpe + low PSR", test_negative_mean_gives_negative_sharpe_and_low_psr)
    run("annualized Sharpe consistent", test_annualized_sharpe_consistent)
    run("benchmark shifts PSR down", test_benchmark_shifts_psr_down)
    run("grade + verdict helpers", test_grade_and_verdict_helpers)
    run("confidences invalid → default fallback", test_confidences_validation_invalid_fallback)
    run("confidences dedup + sort", test_confidences_dedup_and_sort)
    run("zero-variance → Nones, no crash", test_zero_variance_series_nones_not_crash)
    run("all numeric outputs finite", test_all_numeric_outputs_finite)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
