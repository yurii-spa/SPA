"""
Tests for the paper-trading return-predictability & complexity module (SPA-V407).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_distribution_normality.py).

Run::
    python spa_core/tests/test_return_predictability.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics_lab.return_predictability import (
    DEFAULT_EMBED_DIM,
    SAMPEN_M,
    _approx_entropy,
    _permutation_entropy,
    _predictability_grade,
    _sample_entropy,
    _shannon_entropy,
    _sign_entropy,
    _verdict,
    compute_predictability,
    generate_predictability_report,
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
    "embed_dim", "sampen_m", "sampen_r",
    "shannon_entropy_bits", "shannon_entropy_normalized",
    "sign_entropy_bits", "sign_entropy_normalized",
    "permutation_entropy", "permutation_entropy_normalized",
    "sample_entropy", "approximate_entropy",
    "predictability_score", "predictability_grade", "verdict",
    "execution_mode",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_predictability([])
    assert set(m.keys()) == _TOP_KEYS, m.keys()
    assert m["count"] == 0, m
    assert m["shannon_entropy_bits"] is None, m
    assert m["permutation_entropy"] is None, m
    assert m["sample_entropy"] is None, m
    assert m["approximate_entropy"] is None, m
    assert m["predictability_score"] is None, m
    assert m["predictability_grade"] is None, m
    assert m["verdict"] == "insufficient_data", m
    assert m["execution_mode"] == "read_only_simulation", m


def test_single_return_stable_no_crash():
    m = compute_predictability(_curve_from_returns([0.5]))
    assert set(m.keys()) == _TOP_KEYS, m.keys()
    assert m["count"] == 1, m
    # One value → no windows, undefined entropies, but stable schema, no crash.
    assert m["permutation_entropy"] is None, m
    assert m["predictability_score"] is None, m
    assert m["verdict"] == "insufficient_data", m


def test_top_level_keys_present():
    m = compute_predictability(_curve_from_returns([0.1, -0.2, 0.3, -0.1, 0.05, 0.2]))
    assert set(m.keys()) == _TOP_KEYS, m.keys()


def test_full_key_set_on_realistic_series():
    rets = [0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.15, 0.4, -0.25, 0.12]
    m = compute_predictability(_curve_from_returns(rets))
    assert m["count"] == 10, m
    assert m["embed_dim"] == DEFAULT_EMBED_DIM, m
    assert m["sampen_m"] == SAMPEN_M, m
    assert m["sampen_r"] is not None, m


def test_shannon_spread_greater_than_concentrated():
    # Spread series occupies many bins; concentrated occupies few.
    spread = [float(i) for i in range(20)]
    concentrated = [0.0] * 18 + [0.0001, 5.0]
    hs = _shannon_entropy(spread)
    hc = _shannon_entropy(concentrated)
    assert hs["bits"] is not None and hc["bits"] is not None, (hs, hc)
    assert hs["bits"] > hc["bits"], (hs, hc)


def test_shannon_normalized_in_unit_interval():
    rets = [0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.15, 0.4, -0.25, 0.12, 0.0, -0.3]
    h = _shannon_entropy(rets)
    assert h["normalized"] is not None, h
    assert 0.0 <= h["normalized"] <= 1.0 + 1e-9, h


def test_shannon_empty_and_flat_no_crash():
    assert _shannon_entropy([])["bits"] is None
    flat = _shannon_entropy([0.25, 0.25, 0.25])
    assert flat["bits"] == 0.0, flat
    assert flat["normalized"] is None, flat


def test_sign_entropy_bounds():
    s = _sign_entropy([0.1, -0.2, 0.3, -0.1, 0.0])
    assert s["bits"] is not None, s
    assert s["bits"] >= 0.0, s
    if s["normalized"] is not None:
        assert 0.0 <= s["normalized"] <= 1.0 + 1e-9, s
    assert s["up"] + s["down"] + s["flat"] == 5, s


def test_sign_entropy_balanced_is_one():
    # Exactly 50/50 up/down, no flats → 2 equiprobable classes → normalized 1.0.
    s = _sign_entropy([1.0, -1.0, 2.0, -2.0, 0.5, -0.5])
    assert s["up"] == 3 and s["down"] == 3 and s["flat"] == 0, s
    assert approx(s["bits"], 1.0, tol=1e-9), s
    assert approx(s["normalized"], 1.0, tol=1e-9), s


def test_sign_entropy_single_class_normalized_none():
    s = _sign_entropy([0.1, 0.2, 0.3, 0.4])  # all up → one class
    assert s["up"] == 4, s
    assert s["bits"] == 0.0, s
    assert s["normalized"] is None, s


def test_permutation_entropy_monotone_is_near_zero():
    # Strictly increasing → a single ordinal pattern → PE ≈ 0.
    rets = [float(i) for i in range(15)]
    p = _permutation_entropy(rets, embed_dim=3)
    assert p["bits"] is not None, p
    assert approx(p["bits"], 0.0, tol=1e-9), p
    assert approx(p["normalized"], 0.0, tol=1e-9), p


def test_permutation_entropy_normalized_in_unit_interval():
    rets = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1, -0.3, 0.7, -0.2, 0.4]
    p = _permutation_entropy(rets, embed_dim=3)
    assert p["normalized"] is not None, p
    assert 0.0 <= p["normalized"] <= 1.0 + 1e-9, p


def test_permutation_entropy_varied_greater_than_monotone():
    monotone = [float(i) for i in range(15)]
    varied = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1, -0.3, 0.7, -0.2, 0.4, 0.8, -0.5, 0.0]
    pm = _permutation_entropy(monotone, embed_dim=3)
    pv = _permutation_entropy(varied, embed_dim=3)
    assert pv["bits"] > pm["bits"], (pm, pv)


def test_permutation_entropy_too_few_windows_none():
    # n < m+1 → fewer than 2 windows → None.
    p = _permutation_entropy([0.1, 0.2], embed_dim=3)
    assert p["bits"] is None, p
    assert p["normalized"] is None, p
    assert p["num_windows"] == 0, p


def test_sample_entropy_repeating_pattern_low_or_none():
    # A perfectly repeating pattern is highly regular: SampEn low, or None-safe.
    rets = [0.5, -0.5] * 10
    s = _sample_entropy(rets)
    assert s["value"] is None or (math.isfinite(s["value"]) and s["value"] >= 0.0), s


def test_sample_entropy_varied_finite_or_none():
    rets = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1, -0.3, 0.7, -0.2, 0.4]
    s = _sample_entropy(rets)
    assert s["value"] is None or math.isfinite(s["value"]), s


def test_sample_entropy_too_small_no_crash():
    s = _sample_entropy([0.1, 0.2])
    assert s["value"] is None, s


def test_sample_entropy_zero_variance_none():
    s = _sample_entropy([0.25] * 8)  # r = 0 → undefined
    assert s["value"] is None, s


def test_approx_entropy_finite_or_none():
    rets = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1, -0.3, 0.7, -0.2, 0.4]
    a = _approx_entropy(rets)
    assert a["value"] is None or math.isfinite(a["value"]), a


def test_approx_entropy_zero_variance_none():
    a = _approx_entropy([0.25] * 8)
    assert a["value"] is None, a


def test_predictability_score_equals_one_minus_perm_norm():
    rets = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1, -0.3, 0.7, -0.2, 0.4]
    m = compute_predictability(_curve_from_returns(rets))
    pn = m["permutation_entropy_normalized"]
    assert pn is not None, m
    assert approx(m["predictability_score"], round(1.0 - pn, 6), tol=1e-6), m
    assert 0.0 <= m["predictability_score"] <= 1.0 + 1e-9, m


def test_predictability_score_none_when_perm_undefined():
    m = compute_predictability(_curve_from_returns([0.1, 0.2]))  # too few windows
    assert m["permutation_entropy_normalized"] is None, m
    assert m["predictability_score"] is None, m
    assert m["predictability_grade"] is None, m
    assert m["verdict"] == "insufficient_data", m


def test_grade_helper_thresholds():
    assert _predictability_grade(0.9) == "A"
    assert _predictability_grade(0.66) == "A"
    assert _predictability_grade(0.5) == "B"
    assert _predictability_grade(0.40) == "B"
    assert _predictability_grade(0.25) == "C"
    assert _predictability_grade(0.20) == "C"
    assert _predictability_grade(0.1) == "D"
    assert _predictability_grade(None) is None


def test_verdict_helper_thresholds():
    assert _verdict(None) == "insufficient_data"
    assert _verdict(0.8) == "structured"
    assert _verdict(0.66) == "structured"
    assert _verdict(0.4) == "weakly_structured"
    assert _verdict(0.20) == "weakly_structured"
    assert _verdict(0.05) == "random_walk_like"


def test_monotone_series_is_structured():
    # Monotone increasing → PE ≈ 0 → score ≈ 1 → grade A / structured.
    rets = [float(i) for i in range(15)]
    m = compute_predictability(_curve_from_returns(rets))
    assert m["predictability_score"] is not None and m["predictability_score"] > 0.9, m
    assert m["predictability_grade"] == "A", m
    assert m["verdict"] == "structured", m


def test_zero_variance_no_crash():
    m = compute_predictability(_curve_from_returns([0.25] * 8))
    assert m["sample_entropy"] is None, m
    assert m["approximate_entropy"] is None, m
    # Flat series → one shannon bin, normalized undefined.
    assert m["shannon_entropy_normalized"] is None, m
    # Permutation entropy of a flat series: ties → all windows identical pattern.
    assert m["permutation_entropy"] is not None, m


def test_all_numeric_outputs_finite_when_not_none():
    rets = [0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.15, 0.4, -0.25, 0.12, 0.33, -0.4]
    m = compute_predictability(_curve_from_returns(rets))

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
        if val is not None:
            _check(val)


def test_embed_dim_clamped_to_two():
    rets = [0.3, -0.1, 0.5, -0.4, 0.2, 0.9, -0.6, 0.1]
    m = compute_predictability(_curve_from_returns(rets), embed_dim=1)
    assert m["embed_dim"] == 2, m


def test_report_no_write_smoke_real_data():
    report = generate_predictability_report(output_path=None)
    assert "generated_at" in report and "metrics" in report, report
    assert set(report["metrics"].keys()) == _TOP_KEYS, report["metrics"].keys()


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "return_predictability.json"
        generate_predictability_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir()
                     if p.name.startswith(".return_predictability_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_return_predictability (SPA-V407)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single return → stable, no crash", test_single_return_stable_no_crash)
    run("top-level keys present", test_top_level_keys_present)
    run("full key set on realistic series", test_full_key_set_on_realistic_series)
    run("shannon spread > concentrated", test_shannon_spread_greater_than_concentrated)
    run("shannon normalized in [0,1]", test_shannon_normalized_in_unit_interval)
    run("shannon empty + flat no crash", test_shannon_empty_and_flat_no_crash)
    run("sign entropy bounds", test_sign_entropy_bounds)
    run("sign entropy balanced 50/50 → 1", test_sign_entropy_balanced_is_one)
    run("sign entropy single class → None norm", test_sign_entropy_single_class_normalized_none)
    run("perm entropy monotone ≈ 0", test_permutation_entropy_monotone_is_near_zero)
    run("perm entropy normalized in [0,1]", test_permutation_entropy_normalized_in_unit_interval)
    run("perm entropy varied > monotone", test_permutation_entropy_varied_greater_than_monotone)
    run("perm entropy too few windows → None", test_permutation_entropy_too_few_windows_none)
    run("sample entropy repeating low/None", test_sample_entropy_repeating_pattern_low_or_none)
    run("sample entropy varied finite/None", test_sample_entropy_varied_finite_or_none)
    run("sample entropy too small no crash", test_sample_entropy_too_small_no_crash)
    run("sample entropy zero-variance → None", test_sample_entropy_zero_variance_none)
    run("approx entropy finite/None", test_approx_entropy_finite_or_none)
    run("approx entropy zero-variance → None", test_approx_entropy_zero_variance_none)
    run("score == 1 - perm_norm", test_predictability_score_equals_one_minus_perm_norm)
    run("score None when perm undefined", test_predictability_score_none_when_perm_undefined)
    run("grade helper thresholds", test_grade_helper_thresholds)
    run("verdict helper thresholds", test_verdict_helper_thresholds)
    run("monotone series structured", test_monotone_series_is_structured)
    run("zero-variance no crash", test_zero_variance_no_crash)
    run("all numeric outputs finite", test_all_numeric_outputs_finite_when_not_none)
    run("embed_dim clamped to 2", test_embed_dim_clamped_to_two)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
