"""
Tests for MP-1142 DeFiProtocolYieldTermStructureAnalyzer
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_yield_term_structure_analyzer import (
    analyze,
    analyze_portfolio,
    _normalise_points,
    _term_spread_pct,
    _curve_slope_pct_per_year,
    _inversion_magnitude_pct,
    _reinvest_adjusted_carry_pct,
    _optimal_tenor,
    _pickup_vs_short_pct,
    _term_structure_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolYieldTermStructureAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_STEEP_NORMAL,
    CLASS_NORMAL,
    CLASS_FLAT,
    CLASS_SLIGHTLY_INVERTED,
    CLASS_DEEPLY_INVERTED,
    FLAG_INVERTED_CURVE,
    FLAG_FLAT_CURVE,
    FLAG_STEEP_CURVE,
    FLAG_HIGH_TERM_PREMIUM,
    FLAG_NEGATIVE_TERM_PREMIUM,
    FLAG_LONG_LOCK_NO_PICKUP,
    FLAG_DEEPLY_INVERTED,
    FLAG_OPTIMAL_IS_SHORT,
    FLAG_INSUFFICIENT_DATA,
    TENOR_SENTINEL_NONE,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "term_structure_log.json")}


@pytest.fixture
def normal_curve():
    # Upward sloping, steep, healthy pickup.
    return {
        "name": "Pendle-PT (normal)",
        "points": [
            {"tenor_days": 30, "apr_pct": 5.0},
            {"tenor_days": 180, "apr_pct": 8.0},
            {"tenor_days": 365, "apr_pct": 11.0},
        ],
        "reinvestment_rate_assumption_pct": 4.0,
    }


@pytest.fixture
def inverted_curve():
    # Short rate above long rate.
    return {
        "name": "Lock-vault (inverted)",
        "points": [
            {"tenor_days": 30, "apr_pct": 12.0},
            {"tenor_days": 180, "apr_pct": 9.0},
            {"tenor_days": 365, "apr_pct": 7.0},
        ],
        "reinvestment_rate_assumption_pct": 4.0,
    }


@pytest.fixture
def flat_curve():
    # Long barely above short.
    return {
        "name": "Flat-market",
        "points": [
            {"tenor_days": 30, "apr_pct": 6.0},
            {"tenor_days": 365, "apr_pct": 6.05},
        ],
        "reinvestment_rate_assumption_pct": 4.0,
    }


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_safe_float_valid():
    assert _safe_float("3.5") == 3.5
    assert _safe_float(7) == 7.0


def test_safe_float_invalid():
    assert _safe_float(None) == 0.0
    assert _safe_float("abc") == 0.0
    assert _safe_float([], 1.0) == 1.0


def test_clamp_bounds():
    assert _clamp(-5) == 0.0
    assert _clamp(150) == 100.0
    assert _clamp(50) == 50.0
    assert _clamp(5, 0, 10) == 5


# ---------------------------------------------------------------------------
# _normalise_points tests
# ---------------------------------------------------------------------------

def test_normalise_points_sorts():
    raw = [
        {"tenor_days": 365, "apr_pct": 10.0},
        {"tenor_days": 30, "apr_pct": 5.0},
    ]
    out = _normalise_points(raw)
    assert [p["tenor_days"] for p in out] == [30.0, 365.0]


def test_normalise_points_drops_non_dict():
    out = _normalise_points([5, "x", None, {"tenor_days": 30, "apr_pct": 5}])
    assert len(out) == 1


def test_normalise_points_drops_nonpositive_tenor():
    out = _normalise_points([
        {"tenor_days": 0, "apr_pct": 5},
        {"tenor_days": -10, "apr_pct": 5},
        {"tenor_days": 30, "apr_pct": 5},
    ])
    assert len(out) == 1
    assert out[0]["tenor_days"] == 30.0


def test_normalise_points_not_a_list():
    assert _normalise_points("nope") == []
    assert _normalise_points(None) == []


def test_normalise_points_coerces_garbage_apr():
    out = _normalise_points([{"tenor_days": 30, "apr_pct": "abc"}])
    assert out[0]["apr_pct"] == 0.0


# ---------------------------------------------------------------------------
# _term_spread_pct tests
# ---------------------------------------------------------------------------

def test_term_spread_positive():
    assert _term_spread_pct(5.0, 11.0) == pytest.approx(6.0)


def test_term_spread_negative():
    assert _term_spread_pct(12.0, 7.0) == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# _curve_slope_pct_per_year tests
# ---------------------------------------------------------------------------

def test_slope_normal():
    # (11-5) over (365-30)/365 years
    slope = _curve_slope_pct_per_year(5.0, 11.0, 30.0, 365.0)
    expected = 6.0 / ((365.0 - 30.0) / 365.0)
    assert slope == pytest.approx(expected)


def test_slope_inverted_negative():
    slope = _curve_slope_pct_per_year(12.0, 7.0, 30.0, 365.0)
    assert slope < 0.0


def test_slope_zero_span():
    assert _curve_slope_pct_per_year(5.0, 8.0, 100.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# _inversion_magnitude_pct tests
# ---------------------------------------------------------------------------

def test_inversion_when_inverted():
    assert _inversion_magnitude_pct(12.0, 7.0) == pytest.approx(5.0)


def test_inversion_zero_when_normal():
    assert _inversion_magnitude_pct(5.0, 11.0) == 0.0


# ---------------------------------------------------------------------------
# _reinvest_adjusted_carry tests
# ---------------------------------------------------------------------------

def test_reinvest_carry_full_tenor_is_own_apr():
    # tenor == longest -> own APR throughout
    c = _reinvest_adjusted_carry_pct(10.0, 365.0, 365.0, 4.0)
    assert c == pytest.approx(10.0)


def test_reinvest_carry_short_blends_with_reinvest():
    # short tenor 30d, longest 365d -> mostly reinvest rate
    c = _reinvest_adjusted_carry_pct(12.0, 30.0, 365.0, 4.0)
    assert 4.0 < c < 12.0


def test_reinvest_carry_zero_longest():
    assert _reinvest_adjusted_carry_pct(8.0, 30.0, 0.0, 4.0) == 8.0


def test_reinvest_carry_high_short_does_not_dominate():
    # high short rate blended down should be below a steady long rate
    short = _reinvest_adjusted_carry_pct(12.0, 30.0, 365.0, 4.0)
    long_ = _reinvest_adjusted_carry_pct(7.0, 365.0, 365.0, 4.0)
    assert short < long_


# ---------------------------------------------------------------------------
# _optimal_tenor tests
# ---------------------------------------------------------------------------

def test_optimal_tenor_empty():
    assert _optimal_tenor([], 4.0) == (TENOR_SENTINEL_NONE, 0.0, 0.0)


def test_optimal_tenor_normal_picks_long():
    points = [
        {"tenor_days": 30, "apr_pct": 5.0},
        {"tenor_days": 365, "apr_pct": 11.0},
    ]
    tenor, apr, carry = _optimal_tenor(points, 4.0)
    assert tenor == 365.0
    assert apr == 11.0


def test_optimal_tenor_inverted_may_pick_short():
    points = [
        {"tenor_days": 30, "apr_pct": 20.0},
        {"tenor_days": 365, "apr_pct": 5.0},
    ]
    tenor, apr, carry = _optimal_tenor(points, 4.0)
    # short blended with low reinvest could still beat 5% long; just ensure valid
    assert tenor in (30.0, 365.0)
    assert carry >= 0.0


# ---------------------------------------------------------------------------
# _pickup tests
# ---------------------------------------------------------------------------

def test_pickup_positive():
    assert _pickup_vs_short_pct(10.0, 6.0) == pytest.approx(4.0)


def test_pickup_negative():
    assert _pickup_vs_short_pct(5.0, 8.0) == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _term_structure_score(2.0, 6.0, False, 0.0, 4.0, has_data=False) == 0.0


def test_score_range():
    s = _term_structure_score(1.0, 3.0, False, 0.0, 2.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_steep_normal_high():
    s = _term_structure_score(3.0, 6.0, False, 0.0, 4.0, has_data=True)
    assert s >= 90.0


def test_score_inverted_low():
    s = _term_structure_score(-3.0, -5.0, True, 5.0, -2.0, has_data=True)
    assert s <= 30.0


def test_score_normal_above_inverted():
    s_normal = _term_structure_score(1.0, 3.0, False, 0.0, 2.0, has_data=True)
    s_inv = _term_structure_score(-1.0, -2.0, True, 2.0, -1.0, has_data=True)
    assert s_normal > s_inv


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data_flat():
    assert _classify(0.0, False, 0.0, has_data=False) == CLASS_FLAT


def test_classify_steep_normal():
    assert _classify(3.0, False, 0.0, has_data=True) == CLASS_STEEP_NORMAL


def test_classify_normal():
    assert _classify(1.0, False, 0.0, has_data=True) == CLASS_NORMAL


def test_classify_flat():
    assert _classify(0.1, False, 0.0, has_data=True) == CLASS_FLAT


def test_classify_slightly_inverted():
    assert _classify(-1.0, True, 0.5, has_data=True) == CLASS_SLIGHTLY_INVERTED


def test_classify_deeply_inverted():
    assert _classify(-3.0, True, 5.0, has_data=True) == CLASS_DEEPLY_INVERTED


def test_classify_in_known_set():
    cases = [
        (3.0, False, 0.0),
        (1.0, False, 0.0),
        (0.1, False, 0.0),
        (-1.0, True, 0.5),
        (-3.0, True, 5.0),
    ]
    for slope, inv, mag in cases:
        assert _classify(slope, inv, mag, has_data=True) in ALL_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# Grade tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,grade", [
    (95, "A"), (90, "A"),
    (80, "B"), (70, "B"),
    (60, "C"), (50, "C"),
    (40, "D"), (30, "D"),
    (10, "F"), (0, "F"),
])
def test_grade_bands(score, grade):
    assert _grade(score) == grade


def test_grade_in_known_set():
    for s in range(0, 101, 7):
        assert _grade(s) in ALL_GRADES


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(False, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, CLASS_FLAT, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_inverted_curve():
    f = _flags(True, 5.0, -3.0, -5.0, -2.0, 30.0, 30.0,
               CLASS_DEEPLY_INVERTED, has_data=True)
    assert FLAG_INVERTED_CURVE in f
    assert FLAG_DEEPLY_INVERTED in f
    assert FLAG_NEGATIVE_TERM_PREMIUM in f


def test_flag_slightly_inverted_not_deep():
    f = _flags(True, 0.5, -0.5, -0.5, -0.2, 30.0, 30.0,
               CLASS_SLIGHTLY_INVERTED, has_data=True)
    assert FLAG_INVERTED_CURVE in f
    assert FLAG_DEEPLY_INVERTED not in f


def test_flag_flat_curve():
    f = _flags(False, 0.0, 0.1, 0.05, 0.05, 365.0, 30.0,
               CLASS_FLAT, has_data=True)
    assert FLAG_FLAT_CURVE in f


def test_flag_steep_curve():
    f = _flags(False, 0.0, 3.0, 6.0, 4.0, 365.0, 30.0,
               CLASS_STEEP_NORMAL, has_data=True)
    assert FLAG_STEEP_CURVE in f


def test_flag_high_term_premium():
    f = _flags(False, 0.0, 2.0, 5.0, 4.0, 365.0, 30.0,
               CLASS_STEEP_NORMAL, has_data=True)
    assert FLAG_HIGH_TERM_PREMIUM in f


def test_flag_long_lock_no_pickup():
    f = _flags(False, 0.0, 0.05, 0.1, 0.05, 365.0, 30.0,
               CLASS_FLAT, has_data=True)
    assert FLAG_LONG_LOCK_NO_PICKUP in f


def test_flag_optimal_is_short():
    # optimal tenor equals short tenor
    f = _flags(True, 2.0, -2.0, -3.0, -1.0, 30.0, 30.0,
               CLASS_SLIGHTLY_INVERTED, has_data=True)
    assert FLAG_OPTIMAL_IS_SHORT in f


def test_flags_subset_of_all():
    f = _flags(True, 5.0, -3.0, -5.0, -2.0, 30.0, 30.0,
               CLASS_DEEPLY_INVERTED, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_FLAT, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_steep_nonempty():
    recs = _recommendations(CLASS_STEEP_NORMAL, [], 5.0, 11.0, 6.0, 3.0, 0.0,
                            365.0, 11.0, 4.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_inverted_nonempty():
    recs = _recommendations(CLASS_DEEPLY_INVERTED,
                            [FLAG_INVERTED_CURVE, FLAG_OPTIMAL_IS_SHORT],
                            12.0, 7.0, -5.0, -3.0, 5.0, 30.0, 12.0, -1.0,
                            has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_normal_curve(normal_curve, tmp_log):
    r = analyze(normal_curve, config=tmp_log)
    assert r["is_inverted"] is False
    assert r["term_spread_pct"] > 0.0
    assert r["classification"] in (CLASS_STEEP_NORMAL, CLASS_NORMAL)
    assert r["term_structure_score"] > 50.0


def test_analyze_inverted_curve(inverted_curve, tmp_log):
    r = analyze(inverted_curve, config=tmp_log)
    assert r["is_inverted"] is True
    assert r["inversion_magnitude_pct"] > 0.0
    assert FLAG_INVERTED_CURVE in r["flags"]
    assert r["classification"] in (CLASS_SLIGHTLY_INVERTED, CLASS_DEEPLY_INVERTED)


def test_analyze_flat_curve(flat_curve, tmp_log):
    r = analyze(flat_curve, config=tmp_log)
    assert r["classification"] == CLASS_FLAT
    assert FLAG_FLAT_CURVE in r["flags"]


def test_analyze_short_long_extremes(normal_curve, tmp_log):
    r = analyze(normal_curve, config=tmp_log)
    assert r["short_tenor_days"] == 30.0
    assert r["long_tenor_days"] == 365.0
    assert r["short_apr_pct"] == 5.0
    assert r["long_apr_pct"] == 11.0


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["term_structure_score"] == 0.0


def test_analyze_single_point_insufficient(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 5.0}]}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["point_count"] == 1


def test_analyze_poor_data_quality(normal_curve, tmp_log):
    pos = dict(normal_curve)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 5.0}]},
                points=[{"tenor_days": 30, "apr_pct": 5.0},
                        {"tenor_days": 365, "apr_pct": 11.0}],
                config=tmp_log)
    assert r["point_count"] == 2


def test_analyze_reinvest_kwarg_override(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 5.0},
                            {"tenor_days": 365, "apr_pct": 11.0}]},
                reinvestment_rate_assumption_pct=7.0, config=tmp_log)
    assert r["reinvestment_rate_assumption_pct"] == 7.0


def test_analyze_result_keys(normal_curve, tmp_log):
    r = analyze(normal_curve, config=tmp_log)
    for key in (
        "name", "points", "point_count", "short_tenor_days", "long_tenor_days",
        "short_apr_pct", "long_apr_pct", "term_spread_pct",
        "curve_slope_pct_per_year", "is_inverted", "inversion_magnitude_pct",
        "optimal_tenor_days", "optimal_tenor_apr_pct", "pickup_vs_short_pct",
        "term_structure_score", "steepness_classification", "classification",
        "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"points": "abc", "reinvestment_rate_assumption_pct": None},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "term_structure_score" in r


def test_analyze_garbage_points_list(tmp_log):
    r = analyze({"points": [{"tenor_days": "x", "apr_pct": "y"}, 5, None]},
                config=tmp_log)
    assert isinstance(r, dict)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_json_serialisable(inverted_curve, tmp_log):
    r = analyze(inverted_curve, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_normal_json_serialisable(normal_curve, tmp_log):
    r = analyze(normal_curve, config=tmp_log)
    json.dumps(r)


def test_analyze_writes_log(normal_curve, tmp_log):
    analyze(normal_curve, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_negative_term_premium_flag(inverted_curve, tmp_log):
    r = analyze(inverted_curve, config=tmp_log)
    assert FLAG_NEGATIVE_TERM_PREMIUM in r["flags"]


def test_analyze_high_term_premium_flag(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 3.0},
                            {"tenor_days": 365, "apr_pct": 9.0}]},
                config=tmp_log)
    assert FLAG_HIGH_TERM_PREMIUM in r["flags"]


def test_analyze_unsorted_points_handled(tmp_log):
    r = analyze({"points": [{"tenor_days": 365, "apr_pct": 11.0},
                            {"tenor_days": 30, "apr_pct": 5.0}]},
                config=tmp_log)
    assert r["short_tenor_days"] == 30.0
    assert r["long_tenor_days"] == 365.0


def test_analyze_optimal_tenor_valid(normal_curve, tmp_log):
    r = analyze(normal_curve, config=tmp_log)
    tenors = [p["tenor_days"] for p in r["points"]]
    assert r["optimal_tenor_days"] in tenors


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_curves"] == 0
    assert r["most_inverted_market"] is None
    assert r["avg_term_structure_score"] == 0.0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_curves"] == 0


def test_portfolio_basic(normal_curve, inverted_curve, tmp_log):
    r = analyze_portfolio([normal_curve, inverted_curve], config=tmp_log)
    assert r["total_curves"] == 2
    assert r["most_inverted_market"] == "Lock-vault (inverted)"
    assert r["least_inverted_market"] == "Pendle-PT (normal)"
    assert 0.0 <= r["avg_term_structure_score"] <= 100.0


def test_portfolio_inverted_count(inverted_curve, normal_curve, tmp_log):
    r = analyze_portfolio([inverted_curve, normal_curve, inverted_curve],
                          config=tmp_log)
    assert r["inverted_count"] == 2


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_curves"] == 3


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(normal_curve, tmp_log):
    a = DeFiProtocolYieldTermStructureAnalyzer(config=tmp_log)
    r = a.analyze(normal_curve)
    assert r["name"] == "Pendle-PT (normal)"


def test_class_wrapper_portfolio(normal_curve, inverted_curve, tmp_log):
    a = DeFiProtocolYieldTermStructureAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([normal_curve, inverted_curve])
    assert r["total_curves"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolYieldTermStructureAnalyzer(config=tmp_log)
    r = a.analyze(None, points=[{"tenor_days": 30, "apr_pct": 5.0},
                                {"tenor_days": 365, "apr_pct": 10.0}])
    assert r["point_count"] == 2


# ---------------------------------------------------------------------------
# Atomic log tests
# ---------------------------------------------------------------------------

def test_atomic_log_ring_buffer(tmp_path):
    log_path = str(tmp_path / "ring.json")
    for i in range(120):
        _atomic_log(log_path, {"i": i})
    with open(log_path) as fh:
        data = json.load(fh)
    assert len(data) == 100
    assert data[0]["i"] == 20
    assert data[-1]["i"] == 119


def test_atomic_log_corrupt_recovers(tmp_path):
    log_path = str(tmp_path / "corrupt.json")
    with open(log_path, "w") as fh:
        fh.write("{not json")
    _atomic_log(log_path, {"ok": True})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"ok": True}]


def test_atomic_log_non_list_recovers(tmp_path):
    log_path = str(tmp_path / "obj.json")
    with open(log_path, "w") as fh:
        json.dump({"some": "object"}, fh)
    _atomic_log(log_path, {"ok": 1})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"ok": 1}]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_two_point_normal_curve(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 5.0},
                            {"tenor_days": 365, "apr_pct": 10.0}]},
                config=tmp_log)
    assert r["is_inverted"] is False
    assert r["term_spread_pct"] == pytest.approx(5.0)


def test_equal_apr_flat(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 6.0},
                            {"tenor_days": 365, "apr_pct": 6.0}]},
                config=tmp_log)
    assert r["term_spread_pct"] == pytest.approx(0.0)
    assert r["classification"] == CLASS_FLAT


def test_inverted_serialisable(inverted_curve, tmp_log):
    r = analyze(inverted_curve, config=tmp_log)
    json.dumps(r)  # must not raise


def test_steep_curve_grade(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 3.0},
                            {"tenor_days": 365, "apr_pct": 12.0}]},
                config=tmp_log)
    assert r["grade"] in ("A", "B")


def test_deeply_inverted_grade(tmp_log):
    r = analyze({"points": [{"tenor_days": 30, "apr_pct": 15.0},
                            {"tenor_days": 365, "apr_pct": 5.0}]},
                config=tmp_log)
    assert r["grade"] in ("D", "F")


def test_many_point_curve(tmp_log):
    points = [{"tenor_days": d, "apr_pct": 4.0 + d / 100.0}
              for d in (7, 14, 30, 90, 180, 365)]
    r = analyze({"points": points}, config=tmp_log)
    assert r["point_count"] == 6
    assert r["is_inverted"] is False


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_yield_term_structure_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "term_structure_score" in res.stdout
