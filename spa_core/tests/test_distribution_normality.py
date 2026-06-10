"""
Tests for the paper-trading return-normality & parametric-tail module (SPA-V403).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_linearity_analytics.py).

Run::
    python spa_core/tests/test_distribution_normality.py
"""
from __future__ import annotations

import math
import os
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.distribution_normality import (
    DEFAULT_CONFIDENCES,
    JB_ALPHA,
    _cornish_fisher,
    _inv_norm_cdf,
    _jarque_bera,
    _norm_pdf,
    _normality_grade,
    _normalize_confidences,
    _verdict,
    compute_normality,
    generate_normality_report,
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

    The module reads daily_return_pct from curve[1:] (seed day excluded), so we
    prepend one seed bar and then one bar per supplied return value.
    """
    bars = [{
        "date": "2026-05-14",
        "close_equity": 100.0,
        "daily_return_pct": 0.0,
    }]
    for i, r in enumerate(returns):
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "close_equity": 100.0,
            "daily_return_pct": float(r),
        })
    return bars


_TOP_KEYS = {
    "count", "num_days", "first_date", "last_date", "mean_pct", "stdev_pct",
    "skewness", "excess_kurtosis", "jarque_bera", "levels", "normality_grade",
    "verdict", "confidences", "execution_mode",
}
_JB_KEYS = {"statistic", "p_value", "is_normal", "alpha"}
_LEVEL_KEYS = {
    "confidence", "z", "gaussian_var_pct", "gaussian_cvar_pct", "cf_z",
    "modified_var_pct", "modified_cvar_pct", "tail_inflation_pct",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_normality([])
    assert set(m.keys()) == _TOP_KEYS, m.keys()
    assert m["count"] == 0, m
    assert m["jarque_bera"] == {"statistic": None, "p_value": None,
                                "is_normal": None, "alpha": JB_ALPHA}, m
    assert m["levels"] == [], m
    assert m["verdict"] == "insufficient_data", m
    assert m["execution_mode"] == "read_only_simulation", m


def test_single_day_stable_no_crash():
    # one return value → moments undefined, but no crash, stable schema.
    m = compute_normality(_curve_from_returns([0.5]))
    assert set(m.keys()) == _TOP_KEYS, m.keys()
    assert m["count"] == 1, m
    assert m["skewness"] is None, m
    assert m["excess_kurtosis"] is None, m
    assert m["normality_grade"] is None, m
    assert m["verdict"] == "insufficient_data", m


def test_top_level_keys_present():
    m = compute_normality(_curve_from_returns([0.1, -0.2, 0.3, -0.1, 0.05, 0.2]))
    assert set(m.keys()) == _TOP_KEYS, m.keys()
    assert set(m["jarque_bera"].keys()) == _JB_KEYS, m["jarque_bera"].keys()


def test_level_keys_present():
    m = compute_normality(_curve_from_returns([0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.15]))
    assert len(m["levels"]) == len(m["confidences"]), m
    for lvl in m["levels"]:
        assert set(lvl.keys()) == _LEVEL_KEYS, lvl.keys()


def test_jb_statistic_formula_known_sample():
    # Compute moments independently and check the JB formula matches.
    rets = [0.4, -0.6, 0.1, 0.9, -0.3, 0.2, -0.8, 0.5]
    m = compute_normality(_curve_from_returns(rets))
    n = m["count"]
    s = m["skewness"]
    k = m["excess_kurtosis"]
    expected = (n / 6.0) * (s * s + (k * k) / 4.0)
    assert approx(m["jarque_bera"]["statistic"], round(expected, 6), tol=1e-6), m["jarque_bera"]


def test_jb_pvalue_is_exp_minus_half_jb():
    rets = [0.4, -0.6, 0.1, 0.9, -0.3, 0.2, -0.8, 0.5, 0.0, 0.3]
    m = compute_normality(_curve_from_returns(rets))
    jb = m["jarque_bera"]["statistic"]
    p = m["jarque_bera"]["p_value"]
    assert approx(p, round(math.exp(-0.5 * jb), 6), tol=1e-6), (jb, p)


def test_is_normal_boolean():
    m = compute_normality(_curve_from_returns([0.1, -0.1, 0.2, -0.2, 0.15, -0.15, 0.05]))
    assert isinstance(m["jarque_bera"]["is_normal"], bool), m["jarque_bera"]


def test_clearly_non_normal_series_grade_and_verdict():
    # Many tiny returns with a few huge symmetric outliers → very fat tails,
    # strong enough excess kurtosis that JB rejects normality.
    rets = ([0.01, -0.01, 0.02, -0.02, 0.0] * 6) + [10.0, -10.0, 9.5, -9.5]
    m = compute_normality(_curve_from_returns(rets))
    assert m["excess_kurtosis"] is not None and m["excess_kurtosis"] > 2.0, m
    assert m["normality_grade"] in ("C", "D"), m
    assert m["verdict"] != "approximately_normal", m
    assert m["jarque_bera"]["is_normal"] is False, m


def test_skewed_series_detected():
    # Strongly right-skewed: many small negatives, few large positives.
    rets = [-0.1] * 10 + [3.0, 4.0, 5.0]
    m = compute_normality(_curve_from_returns(rets))
    assert m["skewness"] is not None and m["skewness"] > 0.5, m
    assert m["verdict"] != "approximately_normal", m


def test_approximately_symmetric_reasonable():
    # A symmetric, mild series should not be flagged as strongly non-normal.
    rets = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, -0.15, 0.15, -0.05, 0.05, 0.0]
    m = compute_normality(_curve_from_returns(rets))
    assert abs(m["skewness"]) < 0.5, m
    assert m["normality_grade"] in ("A", "B", "C"), m


def test_probit_known_values():
    assert approx(_inv_norm_cdf(0.975), 1.959964, tol=1e-3), _inv_norm_cdf(0.975)
    assert _inv_norm_cdf(0.5) == 0.0, _inv_norm_cdf(0.5)
    assert approx(_inv_norm_cdf(0.025), -1.959964, tol=1e-3), _inv_norm_cdf(0.025)
    # 0.95 quantile ≈ 1.644854
    assert approx(_inv_norm_cdf(0.95), 1.644854, tol=1e-3), _inv_norm_cdf(0.95)


def test_probit_monotonic():
    prev = _inv_norm_cdf(0.001)
    for i in range(2, 1000):
        cur = _inv_norm_cdf(i / 1000.0)
        assert cur > prev, (i, prev, cur)
        prev = cur


def test_norm_pdf_peak_and_symmetry():
    assert approx(_norm_pdf(0.0), 1.0 / math.sqrt(2.0 * math.pi), tol=1e-9)
    assert approx(_norm_pdf(1.0), _norm_pdf(-1.0), tol=1e-12)
    assert _norm_pdf(0.0) > _norm_pdf(1.0)


def test_gaussian_var_is_a_loss():
    # Roughly zero-mean series → Gaussian VaR (lower tail) should be negative.
    rets = [-0.5, 0.5, -0.4, 0.4, -0.3, 0.3, -0.6, 0.6, -0.2, 0.2]
    m = compute_normality(_curve_from_returns(rets))
    for lvl in m["levels"]:
        assert lvl["gaussian_var_pct"] < 0, lvl
        assert lvl["gaussian_cvar_pct"] <= lvl["gaussian_var_pct"] + 1e-9, lvl


def test_modified_var_differs_when_kurtosis_positive():
    # Fat-tailed series → excess kurtosis > 0 → CF modified VaR != gaussian VaR.
    rets = [0.01, -0.01, 0.0, 0.02, -0.02, 0.0, 5.0, -4.8, 0.0, 0.01, -0.01, 0.0]
    m = compute_normality(_curve_from_returns(rets))
    assert m["excess_kurtosis"] is not None and m["excess_kurtosis"] > 0, m
    for lvl in m["levels"]:
        assert abs(lvl["modified_var_pct"] - lvl["gaussian_var_pct"]) > 1e-9, lvl


def test_tail_inflation_equals_modified_minus_gaussian():
    rets = [0.1, -0.2, 0.3, -0.4, 0.5, -0.1, 0.2, -0.3, 1.5, -1.2]
    m = compute_normality(_curve_from_returns(rets))
    for lvl in m["levels"]:
        expected = round(lvl["modified_var_pct"] - lvl["gaussian_var_pct"], 6)
        assert approx(lvl["tail_inflation_pct"], expected, tol=1e-6), lvl


def test_all_numeric_outputs_finite():
    rets = [0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.15, 0.4, -0.25, 0.12]
    m = compute_normality(_curve_from_returns(rets))

    def _check(v):
        if isinstance(v, float):
            assert math.isfinite(v), v
        elif isinstance(v, dict):
            for vv in v.values():
                _check(vv)
        elif isinstance(v, list):
            for vv in v:
                _check(vv)

    for val in m.values():
        _check(val)


def test_confidences_validation_invalid_fallback():
    # all invalid → fall back to default.
    m = compute_normality(_curve_from_returns([0.1, -0.1, 0.2]),
                          confidences=[0.0, 1.0, -0.5, 2.0])
    assert m["confidences"] == sorted(set(DEFAULT_CONFIDENCES)), m["confidences"]


def test_confidences_dedup_and_sort():
    out = _normalize_confidences([0.99, 0.95, 0.99, 0.90, 1.5, 0.0])
    assert out == [0.90, 0.95, 0.99], out


def test_zero_variance_series_nones_not_crash():
    # Flat returns → stdev 0 → moments undefined → level fields None, no crash.
    m = compute_normality(_curve_from_returns([0.25, 0.25, 0.25, 0.25, 0.25]))
    assert m["skewness"] is None, m
    assert m["excess_kurtosis"] is None, m
    assert m["verdict"] == "insufficient_data", m
    for lvl in m["levels"]:
        assert lvl["gaussian_var_pct"] is None, lvl
        assert lvl["modified_var_pct"] is None, lvl
        assert lvl["z"] is not None, lvl  # z is data-independent, still present


def test_jb_helper_degenerate_safe():
    base = _jarque_bera(0, None, None)
    assert base["statistic"] is None and base["alpha"] == JB_ALPHA, base
    jb = _jarque_bera(10, 0.0, 0.0)
    assert approx(jb["statistic"], 0.0), jb
    assert approx(jb["p_value"], 1.0), jb  # exp(0) == 1
    assert jb["is_normal"] is True, jb


def test_cornish_fisher_reduces_to_z_when_normal():
    z = _inv_norm_cdf(0.05)
    assert approx(_cornish_fisher(z, 0.0, 0.0), z, tol=1e-12)


def test_grade_and_verdict_helpers():
    assert _normality_grade(0.1, 0.2, 0.5) == "A"
    assert _normality_grade(3.0, 9.0, 0.0001) == "D"
    assert _normality_grade(None, None, None) is None
    jb_norm = {"statistic": 0.1, "p_value": 0.95, "is_normal": True, "alpha": JB_ALPHA}
    assert _verdict(20, 0.1, 0.2, jb_norm) == "approximately_normal"
    assert _verdict(20, None, None, jb_norm) == "insufficient_data"


def test_report_no_write_smoke_real_data():
    report = generate_normality_report(output_path=None)
    assert "generated_at" in report and "metrics" in report, report
    assert set(report["metrics"].keys()) == _TOP_KEYS, report["metrics"].keys()


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "distribution_normality.json"
        generate_normality_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir()
                     if p.name.startswith(".distribution_normality_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_distribution_normality (SPA-V403)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single day → stable, no crash", test_single_day_stable_no_crash)
    run("top-level keys present", test_top_level_keys_present)
    run("level keys present", test_level_keys_present)
    run("JB statistic formula (known sample)", test_jb_statistic_formula_known_sample)
    run("JB p_value == exp(-JB/2)", test_jb_pvalue_is_exp_minus_half_jb)
    run("is_normal is boolean", test_is_normal_boolean)
    run("non-normal series → grade C/D, verdict", test_clearly_non_normal_series_grade_and_verdict)
    run("skewed series detected", test_skewed_series_detected)
    run("approximately symmetric reasonable", test_approximately_symmetric_reasonable)
    run("probit known values", test_probit_known_values)
    run("probit monotonic", test_probit_monotonic)
    run("norm pdf peak + symmetry", test_norm_pdf_peak_and_symmetry)
    run("gaussian VaR is a loss", test_gaussian_var_is_a_loss)
    run("modified VaR differs when kurtosis>0", test_modified_var_differs_when_kurtosis_positive)
    run("tail_inflation == modified - gaussian", test_tail_inflation_equals_modified_minus_gaussian)
    run("all numeric outputs finite", test_all_numeric_outputs_finite)
    run("confidences invalid → default fallback", test_confidences_validation_invalid_fallback)
    run("confidences dedup + sort", test_confidences_dedup_and_sort)
    run("zero-variance → Nones, no crash", test_zero_variance_series_nones_not_crash)
    run("JB helper degenerate-safe", test_jb_helper_degenerate_safe)
    run("cornish-fisher reduces to z when normal", test_cornish_fisher_reduces_to_z_when_normal)
    run("grade + verdict helpers", test_grade_and_verdict_helpers)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
