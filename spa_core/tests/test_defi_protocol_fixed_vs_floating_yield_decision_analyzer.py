"""
Tests for MP-1147 DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer
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

from spa_core.analytics.defi_protocol_fixed_vs_floating_yield_decision_analyzer import (
    analyze,
    analyze_portfolio,
    _fixed_minus_current_floating_spread_pct,
    _fixed_vs_expected_spread_pct,
    _breakeven_avg_floating_apr_pct,
    _total_return_pct,
    _advantage_of_fixed_pct,
    _phi,
    _probability_floating_beats_fixed_pct,
    _decision_score,
    _classify,
    _recommendation,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    ALL_RECOMMENDATIONS,
    CLASS_STRONG_LOCK,
    CLASS_LEAN_LOCK,
    CLASS_NEUTRAL,
    CLASS_LEAN_FLOAT,
    CLASS_STRONG_FLOAT,
    REC_LOCK_FIXED,
    REC_STAY_FLOATING,
    REC_NEUTRAL,
    FLAG_LOCK_FIXED,
    FLAG_STAY_FLOATING,
    FLAG_FIXED_BELOW_CURRENT_FLOATING,
    FLAG_HIGH_FLOATING_VOLATILITY,
    FLAG_FLOATING_LIKELY_WINS,
    FLAG_FIXED_LIKELY_WINS,
    FLAG_NEAR_INDIFFERENT,
    FLAG_INSUFFICIENT_DATA,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "fvf_log.json")}


@pytest.fixture
def lock_worthy_position():
    # Fixed well above expected floating -> lock fixed.
    return {
        "name": "PT-stETH (lock)",
        "fixed_apr_pct": 8.0,
        "current_floating_apr_pct": 5.0,
        "expected_floating_apr_pct": 4.0,
        "floating_apr_volatility_pct": 1.0,
        "horizon_days": 180.0,
    }


@pytest.fixture
def float_worthy_position():
    # Expected floating well above fixed -> stay floating.
    return {
        "name": "Variable vault (float)",
        "fixed_apr_pct": 3.0,
        "current_floating_apr_pct": 6.0,
        "expected_floating_apr_pct": 8.0,
        "floating_apr_volatility_pct": 2.0,
        "horizon_days": 365.0,
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


def test_clamp_custom_range():
    assert _clamp(-2.0, -1.0, 1.0) == -1.0
    assert _clamp(2.0, -1.0, 1.0) == 1.0


# ---------------------------------------------------------------------------
# spread tests
# ---------------------------------------------------------------------------

def test_spread_current_positive():
    assert _fixed_minus_current_floating_spread_pct(6.0, 4.0) == pytest.approx(2.0)


def test_spread_current_negative():
    assert _fixed_minus_current_floating_spread_pct(4.0, 6.0) == pytest.approx(-2.0)


def test_spread_expected_positive():
    assert _fixed_vs_expected_spread_pct(6.0, 4.0) == pytest.approx(2.0)


def test_spread_expected_negative():
    assert _fixed_vs_expected_spread_pct(4.0, 7.0) == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# breakeven tests
# ---------------------------------------------------------------------------

def test_breakeven_equals_fixed():
    assert _breakeven_avg_floating_apr_pct(6.0) == 6.0
    assert _breakeven_avg_floating_apr_pct(0.0) == 0.0
    assert _breakeven_avg_floating_apr_pct(-3.0) == -3.0


# ---------------------------------------------------------------------------
# total return tests
# ---------------------------------------------------------------------------

def test_total_return_full_year():
    assert _total_return_pct(6.0, 365.0) == pytest.approx(6.0)


def test_total_return_half_year():
    assert _total_return_pct(6.0, 182.5) == pytest.approx(3.0)


def test_total_return_zero_days():
    assert _total_return_pct(6.0, 0.0) == 0.0


def test_total_return_floors_negative_days():
    assert _total_return_pct(6.0, -100.0) == 0.0


# ---------------------------------------------------------------------------
# advantage tests
# ---------------------------------------------------------------------------

def test_advantage_positive():
    assert _advantage_of_fixed_pct(6.0, 4.0) == pytest.approx(2.0)


def test_advantage_negative():
    assert _advantage_of_fixed_pct(4.0, 7.0) == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# phi / probability tests
# ---------------------------------------------------------------------------

def test_phi_zero():
    assert _phi(0.0) == pytest.approx(0.5)


def test_phi_symmetry():
    assert _phi(1.0) + _phi(-1.0) == pytest.approx(1.0)


def test_phi_bounds():
    assert 0.0 < _phi(-5.0) < 0.5
    assert 0.5 < _phi(5.0) < 1.0


def test_prob_zero_vol_expected_above():
    # expected > fixed, no vol -> floating certainly wins
    assert _probability_floating_beats_fixed_pct(4.0, 6.0, 0.0) == 100.0


def test_prob_zero_vol_expected_below():
    assert _probability_floating_beats_fixed_pct(6.0, 4.0, 0.0) == 0.0


def test_prob_zero_vol_equal():
    assert _probability_floating_beats_fixed_pct(5.0, 5.0, 0.0) == 50.0


def test_prob_with_vol_equal_means_50():
    # expected == fixed, positive vol -> 50%
    assert _probability_floating_beats_fixed_pct(5.0, 5.0, 2.0) == pytest.approx(50.0)


def test_prob_with_vol_expected_above_gt_50():
    p = _probability_floating_beats_fixed_pct(4.0, 6.0, 2.0)
    assert p > 50.0


def test_prob_with_vol_expected_below_lt_50():
    p = _probability_floating_beats_fixed_pct(6.0, 4.0, 2.0)
    assert p < 50.0


def test_prob_bounds():
    for fixed, exp, vol in [(4.0, 6.0, 2.0), (10.0, 1.0, 0.5),
                            (5.0, 5.0, 0.0), (1.0, 10.0, 0.0)]:
        p = _probability_floating_beats_fixed_pct(fixed, exp, vol)
        assert 0.0 <= p <= 100.0


def test_prob_finite():
    p = _probability_floating_beats_fixed_pct(6.0, 4.0, 2.0)
    assert math.isfinite(p)


def test_prob_negative_vol_floored():
    # negative vol treated as 0 -> deterministic
    assert _probability_floating_beats_fixed_pct(6.0, 4.0, -5.0) == 0.0


# ---------------------------------------------------------------------------
# Decision score tests
# ---------------------------------------------------------------------------

def test_decision_score_no_data():
    assert _decision_score(5.0, 10.0, 2.0, has_data=False) == 0.0


def test_decision_score_range():
    s = _decision_score(2.0, 40.0, 1.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_decision_score_strong_lock_high():
    # big advantage, low floating-wins prob, positive spread -> high
    s = _decision_score(4.0, 5.0, 2.0, has_data=True)
    assert s >= 75.0


def test_decision_score_strong_float_low():
    # big disadvantage, high floating-wins prob, negative spread -> low
    s = _decision_score(-4.0, 95.0, -2.0, has_data=True)
    assert s <= 25.0


def test_decision_score_neutral_mid():
    # zero advantage, 50% prob, zero spread -> mid
    s = _decision_score(0.0, 50.0, 0.0, has_data=True)
    assert 40.0 <= s <= 60.0


def test_decision_score_advantage_monotonic():
    s_low = _decision_score(-2.0, 50.0, 0.0, has_data=True)
    s_high = _decision_score(2.0, 50.0, 0.0, has_data=True)
    assert s_high > s_low


def test_decision_score_prob_monotonic():
    # lower floating-wins prob -> higher lock score
    s_low_prob = _decision_score(0.0, 10.0, 0.0, has_data=True)
    s_high_prob = _decision_score(0.0, 90.0, 0.0, has_data=True)
    assert s_low_prob > s_high_prob


def test_decision_score_advantage_saturates():
    s4 = _decision_score(4.0, 50.0, 0.0, has_data=True)
    s10 = _decision_score(10.0, 50.0, 0.0, has_data=True)
    assert s4 == pytest.approx(s10)


def test_decision_score_negative_spread_no_bonus():
    s = _decision_score(0.0, 50.0, -2.0, has_data=True)
    s_zero_spread = _decision_score(0.0, 50.0, 0.0, has_data=True)
    assert s == pytest.approx(s_zero_spread)


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data_neutral():
    assert _classify(90.0, has_data=False) == CLASS_NEUTRAL


def test_classify_strong_lock():
    assert _classify(75.0, has_data=True) == CLASS_STRONG_LOCK
    assert _classify(90.0, has_data=True) == CLASS_STRONG_LOCK


def test_classify_lean_lock():
    assert _classify(58.0, has_data=True) == CLASS_LEAN_LOCK
    assert _classify(70.0, has_data=True) == CLASS_LEAN_LOCK


def test_classify_neutral():
    assert _classify(42.0, has_data=True) == CLASS_NEUTRAL
    assert _classify(50.0, has_data=True) == CLASS_NEUTRAL


def test_classify_lean_float():
    assert _classify(25.0, has_data=True) == CLASS_LEAN_FLOAT
    assert _classify(40.0, has_data=True) == CLASS_LEAN_FLOAT


def test_classify_strong_float():
    assert _classify(10.0, has_data=True) == CLASS_STRONG_FLOAT
    assert _classify(0.0, has_data=True) == CLASS_STRONG_FLOAT


def test_classify_in_known_set():
    for s in (0, 25, 42, 58, 75, 100):
        assert _classify(s, has_data=True) in ALL_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# Recommendation tests
# ---------------------------------------------------------------------------

def test_recommendation_no_data():
    assert _recommendation(90.0, has_data=False) == REC_NEUTRAL


def test_recommendation_lock():
    assert _recommendation(58.0, has_data=True) == REC_LOCK_FIXED
    assert _recommendation(80.0, has_data=True) == REC_LOCK_FIXED


def test_recommendation_float():
    assert _recommendation(42.0, has_data=True) == REC_STAY_FLOATING
    assert _recommendation(10.0, has_data=True) == REC_STAY_FLOATING


def test_recommendation_neutral():
    assert _recommendation(50.0, has_data=True) == REC_NEUTRAL


def test_recommendation_in_known_set():
    for s in (0, 42, 50, 58, 100):
        assert _recommendation(s, has_data=True) in ALL_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# Grade tests
# ---------------------------------------------------------------------------

def test_grade_decisive_high():
    # score 100 -> decisiveness 100 -> A
    assert _grade(100.0) == "A"
    assert _grade(0.0) == "A"


def test_grade_neutral_low():
    # score 50 -> decisiveness 0 -> F
    assert _grade(50.0) == "F"


def test_grade_in_known_set():
    for s in range(0, 101, 7):
        assert _grade(s) in ALL_GRADES


@pytest.mark.parametrize("score,grade", [
    (95.0, "A"), (5.0, "A"),
    (85.0, "B"), (15.0, "B"),
    (75.0, "C"), (25.0, "C"),
    (65.0, "D"), (35.0, "D"),
    (50.0, "F"), (55.0, "F"),
])
def test_grade_bands(score, grade):
    assert _grade(score) == grade


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(REC_NEUTRAL, 0, 0, 0, 0, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_lock_fixed():
    f = _flags(REC_LOCK_FIXED, 2.0, 1.0, 30.0, 3.0, has_data=True)
    assert FLAG_LOCK_FIXED in f
    assert FLAG_STAY_FLOATING not in f


def test_flag_stay_floating():
    f = _flags(REC_STAY_FLOATING, -2.0, 1.0, 70.0, -3.0, has_data=True)
    assert FLAG_STAY_FLOATING in f
    assert FLAG_LOCK_FIXED not in f


def test_flag_fixed_below_current():
    f = _flags(REC_STAY_FLOATING, -1.0, 1.0, 70.0, -2.0, has_data=True)
    assert FLAG_FIXED_BELOW_CURRENT_FLOATING in f


def test_flag_fixed_below_current_not_triggered():
    f = _flags(REC_LOCK_FIXED, 1.0, 1.0, 30.0, 2.0, has_data=True)
    assert FLAG_FIXED_BELOW_CURRENT_FLOATING not in f


def test_flag_high_floating_volatility():
    f = _flags(REC_NEUTRAL, 0.0, 5.0, 50.0, 0.0, has_data=True)
    assert FLAG_HIGH_FLOATING_VOLATILITY in f


def test_flag_high_volatility_boundary():
    f = _flags(REC_NEUTRAL, 0.0, 5.0, 50.0, 0.0, has_data=True)
    assert FLAG_HIGH_FLOATING_VOLATILITY in f


def test_flag_high_volatility_not_triggered():
    f = _flags(REC_NEUTRAL, 0.0, 4.99, 50.0, 0.0, has_data=True)
    assert FLAG_HIGH_FLOATING_VOLATILITY not in f


def test_flag_floating_likely_wins():
    f = _flags(REC_STAY_FLOATING, -1.0, 1.0, 60.0, -1.0, has_data=True)
    assert FLAG_FLOATING_LIKELY_WINS in f


def test_flag_fixed_likely_wins():
    f = _flags(REC_LOCK_FIXED, 1.0, 1.0, 40.0, 1.0, has_data=True)
    assert FLAG_FIXED_LIKELY_WINS in f


def test_flag_both_likely_not_at_50():
    f = _flags(REC_NEUTRAL, 0.0, 1.0, 50.0, 0.0, has_data=True)
    assert FLAG_FLOATING_LIKELY_WINS not in f
    assert FLAG_FIXED_LIKELY_WINS not in f


def test_flag_near_indifferent():
    f = _flags(REC_NEUTRAL, 0.0, 1.0, 50.0, 0.1, has_data=True)
    assert FLAG_NEAR_INDIFFERENT in f


def test_flag_near_indifferent_not_triggered():
    f = _flags(REC_LOCK_FIXED, 2.0, 1.0, 30.0, 1.0, has_data=True)
    assert FLAG_NEAR_INDIFFERENT not in f


def test_flags_subset_of_all():
    f = _flags(REC_STAY_FLOATING, -3.0, 8.0, 90.0, -5.0, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_NEUTRAL, REC_NEUTRAL, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_lock_nonempty():
    recs = _recommendations(CLASS_STRONG_LOCK, REC_LOCK_FIXED,
                            [FLAG_LOCK_FIXED, FLAG_FIXED_LIKELY_WINS],
                            8.0, 4.0, 4.0, 20.0, 8.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_float_nonempty():
    recs = _recommendations(CLASS_STRONG_FLOAT, REC_STAY_FLOATING,
                            [FLAG_STAY_FLOATING, FLAG_FLOATING_LIKELY_WINS],
                            3.0, 8.0, -5.0, 80.0, 3.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_neutral_nonempty():
    recs = _recommendations(CLASS_NEUTRAL, REC_NEUTRAL, [FLAG_NEAR_INDIFFERENT],
                            5.0, 5.0, 0.1, 50.0, 5.0, has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_lock_worthy(lock_worthy_position, tmp_log):
    r = analyze(lock_worthy_position, config=tmp_log)
    assert r["recommendation"] == REC_LOCK_FIXED
    assert r["classification"] in (CLASS_STRONG_LOCK, CLASS_LEAN_LOCK)
    assert r["decision_score"] >= 58.0


def test_analyze_float_worthy(float_worthy_position, tmp_log):
    r = analyze(float_worthy_position, config=tmp_log)
    assert r["recommendation"] == REC_STAY_FLOATING
    assert r["classification"] in (CLASS_STRONG_FLOAT, CLASS_LEAN_FLOAT)
    assert r["decision_score"] <= 42.0


def test_analyze_spread_correct(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0},
                config=tmp_log)
    assert r["fixed_minus_current_floating_spread_pct"] == pytest.approx(2.0)


def test_analyze_breakeven_equals_fixed(tmp_log):
    r = analyze({"fixed_apr_pct": 7.0, "current_floating_apr_pct": 5.0},
                config=tmp_log)
    assert r["breakeven_avg_floating_apr_pct"] == 7.0


def test_analyze_total_returns_correct(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0,
                 "expected_floating_apr_pct": 4.0, "horizon_days": 182.5},
                config=tmp_log)
    assert r["fixed_total_return_pct"] == pytest.approx(3.0)
    assert r["expected_floating_total_return_pct"] == pytest.approx(2.0)
    assert r["advantage_of_fixed_pct"] == pytest.approx(1.0)


def test_analyze_expected_falls_back_to_current(tmp_log):
    # expected not provided -> falls back to current floating
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 5.0},
                config=tmp_log)
    assert r["expected_floating_apr_pct"] == 5.0


def test_analyze_expected_kwarg_fallback(tmp_log):
    # neither token nor kwarg expected -> falls back to resolved current
    r = analyze(current_floating_apr_pct=4.5, fixed_apr_pct=6.0, config=tmp_log)
    assert r["expected_floating_apr_pct"] == 4.5


def test_analyze_expected_explicit(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 5.0,
                 "expected_floating_apr_pct": 3.0}, config=tmp_log)
    assert r["expected_floating_apr_pct"] == 3.0


def test_analyze_default_horizon(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0}, config=tmp_log)
    assert r["horizon_days"] == 365.0


def test_analyze_default_volatility(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0}, config=tmp_log)
    assert r["floating_apr_volatility_pct"] == 0.0


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["decision_score"] == 0.0
    assert r["classification"] == CLASS_NEUTRAL
    assert r["recommendation"] == REC_NEUTRAL


def test_analyze_poor_data_quality(lock_worthy_position, tmp_log):
    pos = dict(lock_worthy_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["classification"] == CLASS_NEUTRAL


def test_analyze_data_quality_bool_false(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0}, data_quality=False, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_has_data_from_floating_only(tmp_log):
    # only current floating provided -> still has data
    r = analyze({"current_floating_apr_pct": 5.0}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA not in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"fixed_apr_pct": 1.0, "current_floating_apr_pct": 1.0},
                fixed_apr_pct=8.0, current_floating_apr_pct=4.0, config=tmp_log)
    assert r["fixed_apr_pct"] == 8.0
    assert r["current_floating_apr_pct"] == 4.0


def test_analyze_name_kwarg(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0}, name="Custom", config=tmp_log)
    assert r["name"] == "Custom"


def test_analyze_name_default(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0}, config=tmp_log)
    assert r["name"] == "UNKNOWN"


def test_analyze_result_keys(lock_worthy_position, tmp_log):
    r = analyze(lock_worthy_position, config=tmp_log)
    for key in (
        "name", "fixed_apr_pct", "current_floating_apr_pct",
        "expected_floating_apr_pct", "floating_apr_volatility_pct",
        "horizon_days", "data_quality_ok",
        "fixed_minus_current_floating_spread_pct", "fixed_vs_expected_spread_pct",
        "breakeven_avg_floating_apr_pct", "fixed_total_return_pct",
        "expected_floating_total_return_pct", "advantage_of_fixed_pct",
        "probability_floating_beats_fixed_pct", "decision_score",
        "classification", "recommendation", "grade", "flags",
        "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"fixed_apr_pct": "abc", "current_floating_apr_pct": None,
                 "expected_floating_apr_pct": [], "horizon_days": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "decision_score" in r


def test_analyze_json_serialisable(float_worthy_position, tmp_log):
    r = analyze(float_worthy_position, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_all_numeric_finite(tmp_log):
    for pos in (
        {"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0},
        {"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0,
         "floating_apr_volatility_pct": 0.0},
        {"fixed_apr_pct": -3.0, "current_floating_apr_pct": 10.0,
         "floating_apr_volatility_pct": 20.0},
        {"current_floating_apr_pct": 0.001},
    ):
        r = analyze(pos)
        s = json.dumps(r)
        d = json.loads(s)
        for k, v in d.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                assert math.isfinite(v), f"{k}={v} not finite"


def test_analyze_score_bounds(tmp_log):
    for pos in (
        {"fixed_apr_pct": 20.0, "current_floating_apr_pct": 1.0,
         "expected_floating_apr_pct": 1.0},
        {"fixed_apr_pct": 1.0, "current_floating_apr_pct": 20.0,
         "expected_floating_apr_pct": 20.0},
        {"fixed_apr_pct": 5.0, "current_floating_apr_pct": 5.0},
    ):
        r = analyze(pos, config=tmp_log)
        assert 0.0 <= r["decision_score"] <= 100.0


def test_analyze_prob_in_result_bounds(lock_worthy_position, tmp_log):
    r = analyze(lock_worthy_position, config=tmp_log)
    assert 0.0 <= r["probability_floating_beats_fixed_pct"] <= 100.0


def test_analyze_high_volatility_flag(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 5.0,
                 "floating_apr_volatility_pct": 8.0}, config=tmp_log)
    assert FLAG_HIGH_FLOATING_VOLATILITY in r["flags"]


def test_analyze_fixed_below_current_flag(tmp_log):
    r = analyze({"fixed_apr_pct": 3.0, "current_floating_apr_pct": 6.0,
                 "expected_floating_apr_pct": 6.0}, config=tmp_log)
    assert FLAG_FIXED_BELOW_CURRENT_FLOATING in r["flags"]


def test_analyze_lock_flag_in_result(lock_worthy_position, tmp_log):
    r = analyze(lock_worthy_position, config=tmp_log)
    assert FLAG_LOCK_FIXED in r["flags"]


def test_analyze_float_flag_in_result(float_worthy_position, tmp_log):
    r = analyze(float_worthy_position, config=tmp_log)
    assert FLAG_STAY_FLOATING in r["flags"]


def test_analyze_negative_horizon_floored(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0,
                 "horizon_days": -100.0}, config=tmp_log)
    assert r["horizon_days"] == 0.0
    assert r["fixed_total_return_pct"] == 0.0


def test_analyze_writes_log(lock_worthy_position, tmp_log):
    analyze(lock_worthy_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["most_lock_worthy_position"] is None
    assert r["most_float_worthy_position"] is None
    assert r["avg_decision_score"] == 0.0
    assert r["lock_fixed_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_basic(lock_worthy_position, float_worthy_position, tmp_log):
    r = analyze_portfolio([lock_worthy_position, float_worthy_position],
                          config=tmp_log)
    assert r["total_positions"] == 2
    assert r["most_lock_worthy_position"] == "PT-stETH (lock)"
    assert r["most_float_worthy_position"] == "Variable vault (float)"
    assert 0.0 <= r["avg_decision_score"] <= 100.0


def test_portfolio_lock_fixed_count(lock_worthy_position, tmp_log):
    r = analyze_portfolio([lock_worthy_position, lock_worthy_position],
                          config=tmp_log)
    assert r["lock_fixed_count"] == 2


def test_portfolio_summary_fields(lock_worthy_position, tmp_log):
    r = analyze_portfolio([lock_worthy_position], config=tmp_log)
    for key in ("total_positions", "results", "most_lock_worthy_position",
                "most_float_worthy_position", "avg_decision_score",
                "lock_fixed_count", "timestamp"):
        assert key in r


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


def test_portfolio_results_length(lock_worthy_position, float_worthy_position,
                                  tmp_log):
    r = analyze_portfolio([lock_worthy_position, float_worthy_position],
                          config=tmp_log)
    assert len(r["results"]) == 2


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(lock_worthy_position, tmp_log):
    a = DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer(config=tmp_log)
    r = a.analyze(lock_worthy_position)
    assert r["name"] == "PT-stETH (lock)"


def test_class_wrapper_portfolio(lock_worthy_position, float_worthy_position,
                                 tmp_log):
    a = DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([lock_worthy_position, float_worthy_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer(config=tmp_log)
    r = a.analyze(None, fixed_apr_pct=8.0, current_floating_apr_pct=4.0)
    assert r["fixed_apr_pct"] == 8.0


def test_class_wrapper_default_config():
    a = DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer()
    assert a._config == {}


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


def test_atomic_log_cap_exact(tmp_path):
    log_path = str(tmp_path / "cap.json")
    for i in range(100):
        _atomic_log(log_path, {"i": i})
    with open(log_path) as fh:
        data = json.load(fh)
    assert len(data) == 100


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


def test_atomic_log_atomic_to_tmp_path(tmp_path):
    log_path = str(tmp_path / "sub" / "deep" / "atomic.json")
    _atomic_log(log_path, {"a": 1})
    assert os.path.exists(log_path)
    with open(log_path) as fh:
        assert json.load(fh) == [{"a": 1}]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_fixed_equals_expected_neutral(tmp_log):
    # fixed == expected floating, no vol -> 50% prob, near indifferent
    r = analyze({"fixed_apr_pct": 5.0, "current_floating_apr_pct": 5.0,
                 "expected_floating_apr_pct": 5.0}, config=tmp_log)
    assert r["probability_floating_beats_fixed_pct"] == pytest.approx(50.0)
    assert r["advantage_of_fixed_pct"] == pytest.approx(0.0)
    assert FLAG_NEAR_INDIFFERENT in r["flags"]


def test_zero_horizon_zero_returns(tmp_log):
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 4.0,
                 "horizon_days": 0.0}, config=tmp_log)
    assert r["fixed_total_return_pct"] == 0.0
    assert r["expected_floating_total_return_pct"] == 0.0
    assert r["advantage_of_fixed_pct"] == 0.0


def test_high_vol_prob_near_50(tmp_log):
    # large vol relative to spread -> probability pulled toward 50
    r = analyze({"fixed_apr_pct": 6.0, "current_floating_apr_pct": 5.0,
                 "expected_floating_apr_pct": 5.0,
                 "floating_apr_volatility_pct": 50.0}, config=tmp_log)
    assert 40.0 <= r["probability_floating_beats_fixed_pct"] <= 60.0


def test_strong_lock_classification(tmp_log):
    r = analyze({"fixed_apr_pct": 10.0, "current_floating_apr_pct": 4.0,
                 "expected_floating_apr_pct": 3.0,
                 "floating_apr_volatility_pct": 0.5}, config=tmp_log)
    assert r["classification"] == CLASS_STRONG_LOCK
    assert r["recommendation"] == REC_LOCK_FIXED


def test_strong_float_classification(tmp_log):
    r = analyze({"fixed_apr_pct": 2.0, "current_floating_apr_pct": 8.0,
                 "expected_floating_apr_pct": 10.0,
                 "floating_apr_volatility_pct": 0.5}, config=tmp_log)
    assert r["classification"] == CLASS_STRONG_FLOAT
    assert r["recommendation"] == REC_STAY_FLOATING


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_fixed_vs_floating_yield_decision_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "decision_score" in res.stdout
