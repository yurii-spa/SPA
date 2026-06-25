"""
Tests for MP-1146 DeFiProtocolRiskAdjustedYieldHurdleAnalyzer
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_risk_adjusted_yield_hurdle_analyzer import (
    analyze,
    analyze_portfolio,
    _expected_annual_loss_pct,
    _risk_adjusted_apr_pct,
    _required_hurdle_apr_pct,
    _excess_over_hurdle_pct,
    _risk_premium_earned_pct,
    _risk_premium_coverage_ratio,
    _hurdle_clearance_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolRiskAdjustedYieldHurdleAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_GENEROUS_PREMIUM,
    CLASS_ADEQUATE,
    CLASS_THIN,
    CLASS_INADEQUATE,
    CLASS_NEGATIVE_PREMIUM,
    FLAG_CLEARS_HURDLE,
    FLAG_BELOW_HURDLE,
    FLAG_NEGATIVE_RISK_ADJUSTED_YIELD,
    FLAG_HIGH_LOSS_PROBABILITY,
    FLAG_TOTAL_LOSS_GIVEN_EVENT,
    FLAG_THIN_PREMIUM,
    FLAG_GENEROUS_PREMIUM,
    FLAG_INSUFFICIENT_DATA,
    RATIO_SENTINEL_INF,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "hurdle_log.json")}


@pytest.fixture
def generous_position():
    # High offered, low risk -> generous premium clears hurdle comfortably.
    return {
        "name": "Safe stable lending",
        "offered_apr_pct": 12.0,
        "risk_free_apr_pct": 4.0,
        "annual_loss_probability_pct": 1.0,
        "loss_given_event_pct": 50.0,
    }


@pytest.fixture
def risky_position():
    # Modest offered, very high risk -> does not clear hurdle.
    return {
        "name": "Exotic farm",
        "offered_apr_pct": 14.0,
        "risk_free_apr_pct": 4.0,
        "annual_loss_probability_pct": 20.0,
        "loss_given_event_pct": 100.0,
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


def test_clamp_custom_range():
    assert _clamp(-2.0, -1.0, 1.0) == -1.0
    assert _clamp(2.0, -1.0, 1.0) == 1.0


# ---------------------------------------------------------------------------
# expected_annual_loss tests
# ---------------------------------------------------------------------------

def test_expected_loss_normal():
    # 5% prob * 80% lge = 4% expected loss
    assert _expected_annual_loss_pct(5.0, 80.0) == pytest.approx(4.0)


def test_expected_loss_total_loss():
    # 10% prob * 100% lge = 10%
    assert _expected_annual_loss_pct(10.0, 100.0) == pytest.approx(10.0)


def test_expected_loss_zero_prob():
    assert _expected_annual_loss_pct(0.0, 100.0) == 0.0


def test_expected_loss_zero_lge():
    assert _expected_annual_loss_pct(50.0, 0.0) == 0.0


def test_expected_loss_floors_negatives():
    assert _expected_annual_loss_pct(-5.0, 50.0) == 0.0
    assert _expected_annual_loss_pct(5.0, -50.0) == 0.0


def test_expected_loss_caps_at_100():
    # over-100 inputs are clamped
    assert _expected_annual_loss_pct(200.0, 200.0) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# risk_adjusted_apr tests
# ---------------------------------------------------------------------------

def test_risk_adjusted_apr_normal():
    assert _risk_adjusted_apr_pct(12.0, 4.0) == pytest.approx(8.0)


def test_risk_adjusted_apr_negative():
    assert _risk_adjusted_apr_pct(3.0, 10.0) == pytest.approx(-7.0)


def test_risk_adjusted_apr_zero_loss():
    assert _risk_adjusted_apr_pct(12.0, 0.0) == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# required_hurdle tests
# ---------------------------------------------------------------------------

def test_required_hurdle_normal():
    assert _required_hurdle_apr_pct(4.0, 4.0) == pytest.approx(8.0)


def test_required_hurdle_zero_loss():
    assert _required_hurdle_apr_pct(4.0, 0.0) == pytest.approx(4.0)


def test_required_hurdle_floors_negative_loss():
    # a negative expected loss should not reduce the hurdle below risk-free
    assert _required_hurdle_apr_pct(4.0, -5.0) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# excess / premium tests
# ---------------------------------------------------------------------------

def test_excess_positive():
    assert _excess_over_hurdle_pct(12.0, 8.0) == pytest.approx(4.0)


def test_excess_negative():
    assert _excess_over_hurdle_pct(6.0, 8.0) == pytest.approx(-2.0)


def test_premium_positive():
    assert _risk_premium_earned_pct(12.0, 4.0) == pytest.approx(8.0)


def test_premium_negative():
    assert _risk_premium_earned_pct(2.0, 4.0) == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# coverage ratio tests (sentinels)
# ---------------------------------------------------------------------------

def test_coverage_ratio_normal():
    # premium 8 / loss 4 = 2x
    assert _risk_premium_coverage_ratio(8.0, 4.0) == pytest.approx(2.0)


def test_coverage_ratio_zero_loss_positive_premium():
    assert _risk_premium_coverage_ratio(8.0, 0.0) == RATIO_SENTINEL_INF


def test_coverage_ratio_zero_loss_zero_premium():
    assert _risk_premium_coverage_ratio(0.0, 0.0) == 0.0


def test_coverage_ratio_zero_loss_negative_premium():
    assert _risk_premium_coverage_ratio(-3.0, 0.0) == 0.0


def test_coverage_ratio_negative_premium():
    assert _risk_premium_coverage_ratio(-4.0, 4.0) == pytest.approx(-1.0)


def test_coverage_ratio_finite():
    r = _risk_premium_coverage_ratio(8.0, 0.0)
    assert math.isfinite(r)


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _hurdle_clearance_score(5.0, 2.0, 8.0, has_data=False) == 0.0


def test_score_range():
    s = _hurdle_clearance_score(2.0, 1.5, 5.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_generous_high():
    # big excess, big coverage, positive risk-adjusted -> high score
    s = _hurdle_clearance_score(8.0, RATIO_SENTINEL_INF, 10.0, has_data=True)
    assert s >= 90.0


def test_score_negative_low():
    # negative excess, negative coverage, negative risk-adjusted -> 0
    s = _hurdle_clearance_score(-5.0, -2.0, -3.0, has_data=True)
    assert s == 0.0


def test_score_excess_monotonic():
    s_low = _hurdle_clearance_score(1.0, 1.0, 5.0, has_data=True)
    s_high = _hurdle_clearance_score(5.0, 1.0, 5.0, has_data=True)
    assert s_high > s_low


def test_score_negative_excess_zero_component():
    s = _hurdle_clearance_score(-1.0, 1.0, 5.0, has_data=True)
    # only coverage + risk-adjusted components contribute
    assert s == pytest.approx(1.0 / 3.0 * 30.0 + 20.0)


def test_score_coverage_saturates():
    s3 = _hurdle_clearance_score(0.0, 3.0, 5.0, has_data=True)
    s10 = _hurdle_clearance_score(0.0, 10.0, 5.0, has_data=True)
    assert s3 == pytest.approx(s10)


def test_score_inf_coverage():
    s = _hurdle_clearance_score(0.0, RATIO_SENTINEL_INF, 5.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_negative_risk_adjusted_zero_component():
    s_pos = _hurdle_clearance_score(2.0, 1.0, 5.0, has_data=True)
    s_neg = _hurdle_clearance_score(2.0, 1.0, -5.0, has_data=True)
    assert s_pos > s_neg


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data():
    assert _classify(10.0, has_data=False) == CLASS_NEGATIVE_PREMIUM


def test_classify_generous():
    assert _classify(5.0, has_data=True) == CLASS_GENEROUS_PREMIUM
    assert _classify(10.0, has_data=True) == CLASS_GENEROUS_PREMIUM


def test_classify_adequate():
    assert _classify(1.0, has_data=True) == CLASS_ADEQUATE
    assert _classify(4.0, has_data=True) == CLASS_ADEQUATE


def test_classify_thin():
    assert _classify(0.0, has_data=True) == CLASS_THIN
    assert _classify(0.5, has_data=True) == CLASS_THIN


def test_classify_inadequate():
    assert _classify(-1.0, has_data=True) == CLASS_INADEQUATE
    assert _classify(-5.0, has_data=True) == CLASS_INADEQUATE


def test_classify_negative_premium():
    assert _classify(-6.0, has_data=True) == CLASS_NEGATIVE_PREMIUM


def test_classify_in_known_set():
    for excess in (-20, -6, -5, -1, 0, 0.5, 1, 4, 5, 20):
        assert _classify(excess, has_data=True) in ALL_CLASSIFICATIONS


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
    f = _flags(0, False, 0, 0, 0, CLASS_NEGATIVE_PREMIUM, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_clears_hurdle():
    f = _flags(4.0, True, 8.0, 1.0, 50.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_CLEARS_HURDLE in f
    assert FLAG_BELOW_HURDLE not in f


def test_flag_below_hurdle():
    f = _flags(-3.0, False, 5.0, 1.0, 50.0, CLASS_INADEQUATE, has_data=True)
    assert FLAG_BELOW_HURDLE in f
    assert FLAG_CLEARS_HURDLE not in f


def test_flag_negative_risk_adjusted():
    f = _flags(-3.0, False, -2.0, 1.0, 50.0, CLASS_INADEQUATE, has_data=True)
    assert FLAG_NEGATIVE_RISK_ADJUSTED_YIELD in f


def test_flag_high_loss_probability():
    f = _flags(2.0, True, 5.0, 15.0, 50.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_HIGH_LOSS_PROBABILITY in f


def test_flag_high_loss_probability_boundary():
    f = _flags(2.0, True, 5.0, 10.0, 50.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_HIGH_LOSS_PROBABILITY in f


def test_flag_high_loss_probability_not_triggered():
    f = _flags(2.0, True, 5.0, 9.99, 50.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_HIGH_LOSS_PROBABILITY not in f


def test_flag_total_loss_given_event():
    f = _flags(2.0, True, 5.0, 1.0, 100.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_TOTAL_LOSS_GIVEN_EVENT in f


def test_flag_total_loss_given_event_boundary():
    f = _flags(2.0, True, 5.0, 1.0, 95.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_TOTAL_LOSS_GIVEN_EVENT in f


def test_flag_total_loss_not_triggered():
    f = _flags(2.0, True, 5.0, 1.0, 94.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_TOTAL_LOSS_GIVEN_EVENT not in f


def test_flag_thin_premium():
    f = _flags(0.5, True, 5.0, 1.0, 50.0, CLASS_THIN, has_data=True)
    assert FLAG_THIN_PREMIUM in f


def test_flag_thin_premium_boundary_zero():
    f = _flags(0.0, False, 5.0, 1.0, 50.0, CLASS_THIN, has_data=True)
    assert FLAG_THIN_PREMIUM in f


def test_flag_thin_premium_not_triggered_at_one():
    f = _flags(1.0, True, 5.0, 1.0, 50.0, CLASS_ADEQUATE, has_data=True)
    assert FLAG_THIN_PREMIUM not in f


def test_flag_generous_premium():
    f = _flags(6.0, True, 8.0, 1.0, 50.0, CLASS_GENEROUS_PREMIUM, has_data=True)
    assert FLAG_GENEROUS_PREMIUM in f


def test_flags_subset_of_all():
    f = _flags(-10.0, False, -5.0, 50.0, 100.0, CLASS_NEGATIVE_PREMIUM,
               has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_NEGATIVE_PREMIUM, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_generous_nonempty():
    recs = _recommendations(CLASS_GENEROUS_PREMIUM, [FLAG_GENEROUS_PREMIUM],
                            12.0, 6.0, 6.0, 2.0, 10.0, 4.0, has_data=True)
    assert len(recs) >= 1


def test_recommendations_negative_nonempty():
    recs = _recommendations(CLASS_NEGATIVE_PREMIUM,
                            [FLAG_BELOW_HURDLE, FLAG_NEGATIVE_RISK_ADJUSTED_YIELD],
                            5.0, 20.0, -15.0, 16.0, -11.0, -0.5, has_data=True)
    assert len(recs) >= 2


def test_recommendations_each_band_nonempty():
    for cls in (CLASS_GENEROUS_PREMIUM, CLASS_ADEQUATE, CLASS_THIN,
                CLASS_INADEQUATE, CLASS_NEGATIVE_PREMIUM):
        recs = _recommendations(cls, [], 10.0, 8.0, 2.0, 2.0, 8.0, 2.0,
                                has_data=True)
        assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_generous(generous_position, tmp_log):
    r = analyze(generous_position, config=tmp_log)
    assert r["clears_hurdle"] is True
    assert r["classification"] in (CLASS_GENEROUS_PREMIUM, CLASS_ADEQUATE)
    assert r["hurdle_clearance_score"] >= 50.0


def test_analyze_risky(risky_position, tmp_log):
    r = analyze(risky_position, config=tmp_log)
    # offered 14, hurdle = 4 + 20 = 24 -> below hurdle
    assert r["clears_hurdle"] is False
    assert r["classification"] in (CLASS_INADEQUATE, CLASS_NEGATIVE_PREMIUM)


def test_analyze_expected_loss_correct(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "annual_loss_probability_pct": 5.0,
                 "loss_given_event_pct": 80.0}, config=tmp_log)
    assert r["expected_annual_loss_pct"] == pytest.approx(4.0)


def test_analyze_hurdle_correct(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 5.0,
                 "loss_given_event_pct": 80.0}, config=tmp_log)
    assert r["required_hurdle_apr_pct"] == pytest.approx(8.0)
    assert r["excess_over_hurdle_pct"] == pytest.approx(2.0)


def test_analyze_default_risk_free(tmp_log):
    r = analyze({"offered_apr_pct": 10.0}, config=tmp_log)
    assert r["risk_free_apr_pct"] == 4.0


def test_analyze_default_lge(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "annual_loss_probability_pct": 5.0},
                config=tmp_log)
    assert r["loss_given_event_pct"] == 100.0


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["hurdle_clearance_score"] == 0.0
    assert r["classification"] == CLASS_NEGATIVE_PREMIUM


def test_analyze_poor_data_quality(generous_position, tmp_log):
    pos = dict(generous_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["classification"] == CLASS_NEGATIVE_PREMIUM


def test_analyze_data_quality_bad(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "data_quality": "bad"}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_data_quality_bool_false(tmp_log):
    r = analyze({"offered_apr_pct": 10.0}, data_quality=False, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"offered_apr_pct": 5.0, "risk_free_apr_pct": 2.0},
                offered_apr_pct=15.0, risk_free_apr_pct=4.0, config=tmp_log)
    assert r["offered_apr_pct"] == 15.0
    assert r["risk_free_apr_pct"] == 4.0


def test_analyze_name_kwarg(tmp_log):
    r = analyze({"offered_apr_pct": 10.0}, name="MyVault", config=tmp_log)
    assert r["name"] == "MyVault"


def test_analyze_name_from_token(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "name": "TokenName"}, config=tmp_log)
    assert r["name"] == "TokenName"


def test_analyze_name_default(tmp_log):
    r = analyze({"offered_apr_pct": 10.0}, config=tmp_log)
    assert r["name"] == "UNKNOWN"


def test_analyze_result_keys(generous_position, tmp_log):
    r = analyze(generous_position, config=tmp_log)
    for key in (
        "name", "offered_apr_pct", "risk_free_apr_pct",
        "annual_loss_probability_pct", "loss_given_event_pct",
        "data_quality_ok", "expected_annual_loss_pct", "risk_adjusted_apr_pct",
        "required_hurdle_apr_pct", "excess_over_hurdle_pct",
        "risk_premium_earned_pct", "risk_premium_coverage_ratio",
        "clears_hurdle", "hurdle_clearance_score", "classification", "grade",
        "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"offered_apr_pct": "abc", "risk_free_apr_pct": None,
                 "annual_loss_probability_pct": [], "loss_given_event_pct": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "hurdle_clearance_score" in r


def test_analyze_json_serialisable(risky_position, tmp_log):
    r = analyze(risky_position, config=tmp_log)
    s = json.dumps(r)
    assert isinstance(s, str)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_all_numeric_finite(tmp_log):
    # round-trip through JSON and assert every numeric field is finite
    for pos in (
        {"offered_apr_pct": 12.0, "annual_loss_probability_pct": 0.0},
        {"offered_apr_pct": 12.0, "annual_loss_probability_pct": 100.0,
         "loss_given_event_pct": 100.0},
        {"offered_apr_pct": -5.0, "risk_free_apr_pct": 4.0},
        {"offered_apr_pct": 0.001},
    ):
        r = analyze(pos)
        s = json.dumps(r)
        d = json.loads(s)
        for k, v in d.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                assert math.isfinite(v), f"{k}={v} not finite"


def test_analyze_score_bounds(tmp_log):
    for pos in (
        {"offered_apr_pct": 50.0, "annual_loss_probability_pct": 0.0},
        {"offered_apr_pct": 1.0, "annual_loss_probability_pct": 50.0,
         "loss_given_event_pct": 100.0},
        {"offered_apr_pct": 8.0, "annual_loss_probability_pct": 2.0},
    ):
        r = analyze(pos, config=tmp_log)
        assert 0.0 <= r["hurdle_clearance_score"] <= 100.0


def test_analyze_clears_hurdle_flag(tmp_log):
    r = analyze({"offered_apr_pct": 20.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 1.0,
                 "loss_given_event_pct": 50.0}, config=tmp_log)
    assert FLAG_CLEARS_HURDLE in r["flags"]


def test_analyze_negative_risk_adjusted_flag(tmp_log):
    r = analyze({"offered_apr_pct": 5.0, "annual_loss_probability_pct": 10.0,
                 "loss_given_event_pct": 100.0}, config=tmp_log)
    # expected loss 10 > offered 5 -> risk adjusted negative
    assert r["risk_adjusted_apr_pct"] < 0.0
    assert FLAG_NEGATIVE_RISK_ADJUSTED_YIELD in r["flags"]


def test_analyze_loss_prob_clamped(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "annual_loss_probability_pct": 150.0},
                config=tmp_log)
    assert r["annual_loss_probability_pct"] == 100.0


def test_analyze_writes_log(generous_position, tmp_log):
    analyze(generous_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_coverage_sentinel_in_result(tmp_log):
    # zero loss probability, positive premium -> infinite coverage sentinel
    r = analyze({"offered_apr_pct": 10.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 0.0}, config=tmp_log)
    assert r["risk_premium_coverage_ratio"] == RATIO_SENTINEL_INF
    json.dumps(r)  # must not raise


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["best_hurdle_clearance_position"] is None
    assert r["worst_hurdle_clearance_position"] is None
    assert r["avg_hurdle_clearance_score"] == 0.0
    assert r["below_hurdle_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_basic(generous_position, risky_position, tmp_log):
    r = analyze_portfolio([generous_position, risky_position], config=tmp_log)
    assert r["total_positions"] == 2
    assert r["best_hurdle_clearance_position"] == "Safe stable lending"
    assert r["worst_hurdle_clearance_position"] == "Exotic farm"
    assert 0.0 <= r["avg_hurdle_clearance_score"] <= 100.0


def test_portfolio_below_hurdle_count(tmp_log):
    bad = {"offered_apr_pct": 5.0, "annual_loss_probability_pct": 20.0,
           "loss_given_event_pct": 100.0}
    r = analyze_portfolio([bad, bad], config=tmp_log)
    assert r["below_hurdle_count"] == 2


def test_portfolio_summary_fields(generous_position, tmp_log):
    r = analyze_portfolio([generous_position], config=tmp_log)
    for key in ("total_positions", "results", "best_hurdle_clearance_position",
                "worst_hurdle_clearance_position", "avg_hurdle_clearance_score",
                "below_hurdle_count", "timestamp"):
        assert key in r


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


def test_portfolio_results_length(generous_position, risky_position, tmp_log):
    r = analyze_portfolio([generous_position, risky_position], config=tmp_log)
    assert len(r["results"]) == 2


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(generous_position, tmp_log):
    a = DeFiProtocolRiskAdjustedYieldHurdleAnalyzer(config=tmp_log)
    r = a.analyze(generous_position)
    assert r["name"] == "Safe stable lending"


def test_class_wrapper_portfolio(generous_position, risky_position, tmp_log):
    a = DeFiProtocolRiskAdjustedYieldHurdleAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([generous_position, risky_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolRiskAdjustedYieldHurdleAnalyzer(config=tmp_log)
    r = a.analyze(None, offered_apr_pct=12.0, annual_loss_probability_pct=1.0)
    assert r["offered_apr_pct"] == 12.0


def test_class_wrapper_default_config():
    a = DeFiProtocolRiskAdjustedYieldHurdleAnalyzer()
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
    # writes to a custom path under tmp_path (no real data dir pollution)
    log_path = str(tmp_path / "sub" / "deep" / "atomic.json")
    _atomic_log(log_path, {"a": 1})
    assert os.path.exists(log_path)
    with open(log_path) as fh:
        assert json.load(fh) == [{"a": 1}]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_loss_probability_clears_easily(tmp_log):
    r = analyze({"offered_apr_pct": 10.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 0.0}, config=tmp_log)
    assert r["expected_annual_loss_pct"] == 0.0
    assert r["required_hurdle_apr_pct"] == pytest.approx(4.0)
    assert r["clears_hurdle"] is True


def test_offered_equals_hurdle_thin(tmp_log):
    # offered exactly equals hurdle -> excess 0 -> THIN, does NOT clear (>0)
    r = analyze({"offered_apr_pct": 8.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 5.0,
                 "loss_given_event_pct": 80.0}, config=tmp_log)
    assert r["excess_over_hurdle_pct"] == pytest.approx(0.0)
    assert r["clears_hurdle"] is False
    assert r["classification"] == CLASS_THIN


def test_negative_offered_apr(tmp_log):
    r = analyze({"offered_apr_pct": -2.0, "risk_free_apr_pct": 4.0},
                config=tmp_log)
    # signal present (abs > eps) -> has data
    json.dumps(r)
    assert r["clears_hurdle"] is False


def test_total_loss_given_event_flag_in_result(tmp_log):
    r = analyze({"offered_apr_pct": 30.0, "annual_loss_probability_pct": 2.0,
                 "loss_given_event_pct": 100.0}, config=tmp_log)
    assert FLAG_TOTAL_LOSS_GIVEN_EVENT in r["flags"]


def test_high_loss_probability_flag_in_result(tmp_log):
    r = analyze({"offered_apr_pct": 30.0, "annual_loss_probability_pct": 12.0,
                 "loss_given_event_pct": 50.0}, config=tmp_log)
    assert FLAG_HIGH_LOSS_PROBABILITY in r["flags"]


def test_generous_premium_flag_in_result(tmp_log):
    r = analyze({"offered_apr_pct": 25.0, "risk_free_apr_pct": 4.0,
                 "annual_loss_probability_pct": 1.0,
                 "loss_given_event_pct": 50.0}, config=tmp_log)
    assert FLAG_GENEROUS_PREMIUM in r["flags"]
    assert r["classification"] == CLASS_GENEROUS_PREMIUM


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_risk_adjusted_yield_hurdle_analyzer.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "hurdle_clearance_score" in res.stdout
