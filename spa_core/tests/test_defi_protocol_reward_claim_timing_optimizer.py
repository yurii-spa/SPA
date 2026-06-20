"""
Tests for MP-1144 DeFiProtocolRewardClaimTimingOptimizer
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

from spa_core.analytics.defi_protocol_reward_claim_timing_optimizer import (
    analyze,
    analyze_portfolio,
    _gas_to_accrued_ratio_pct,
    _optimal_claim_threshold_usd,
    _expected_days_to_threshold,
    _recommended_claim_frequency_days,
    _price_risk_haircut_pct,
    _opportunity_cost_usd,
    _net_benefit_of_claiming_now_usd,
    _claim_timing_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolRewardClaimTimingOptimizer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_CLAIM_NOW,
    CLASS_CLAIM_SOON,
    CLASS_ACCUMULATE,
    CLASS_TOO_SMALL_TO_CLAIM,
    CLASS_INSUFFICIENT_DATA,
    FLAG_CLAIM_NOW,
    FLAG_GAS_EXCEEDS_REWARD,
    FLAG_BELOW_THRESHOLD,
    FLAG_HIGH_PRICE_RISK,
    FLAG_HIGH_OPPORTUNITY_COST,
    FLAG_FREQUENT_CLAIMING_WASTEFUL,
    FLAG_MATURE_FOR_CLAIM,
    FLAG_ACCRUAL_STALLED,
    FLAG_INSUFFICIENT_DATA,
    DAYS_SENTINEL_NEVER,
    GAS_RATIO_SENTINEL,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "reward_claim_timing_log.json")}


@pytest.fixture
def mature_position():
    # Large accrued balance, well above threshold; claim now.
    return {
        "name": "CRV-rewards (mature)",
        "accrued_reward_usd": 220.0,
        "daily_accrual_usd": 8.0,
        "claim_gas_cost_usd": 3.0,
        "reward_token_volatility_pct": 70.0,
        "reinvestment_apr_pct": 6.0,
        "target_gas_drag_pct": 2.0,
    }


@pytest.fixture
def small_position():
    # Tiny accrued balance, gas dwarfs reward.
    return {
        "name": "tiny-rewards",
        "accrued_reward_usd": 1.5,
        "daily_accrual_usd": 0.05,
        "claim_gas_cost_usd": 4.0,
        "reward_token_volatility_pct": 90.0,
        "reinvestment_apr_pct": 5.0,
        "target_gas_drag_pct": 2.0,
    }


@pytest.fixture
def accumulating_position():
    # Below threshold but building; accumulate.
    return {
        "name": "accumulating",
        "accrued_reward_usd": 30.0,
        "daily_accrual_usd": 5.0,
        "claim_gas_cost_usd": 4.0,
        "reward_token_volatility_pct": 60.0,
        "reinvestment_apr_pct": 5.0,
        "target_gas_drag_pct": 2.0,
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


def test_safe_float_default_passthrough():
    assert _safe_float(None, 9.0) == 9.0
    assert _safe_float({}, -2.0) == -2.0


def test_clamp_bounds():
    assert _clamp(-5) == 0.0
    assert _clamp(150) == 100.0
    assert _clamp(50) == 50.0
    assert _clamp(5, 0, 10) == 5


def test_clamp_custom_range():
    assert _clamp(-1, -10, 10) == -1
    assert _clamp(-100, -10, 10) == -10
    assert _clamp(100, -10, 10) == 10


# ---------------------------------------------------------------------------
# _gas_to_accrued_ratio_pct tests
# ---------------------------------------------------------------------------

def test_gas_ratio_normal():
    assert _gas_to_accrued_ratio_pct(3.0, 300.0) == pytest.approx(1.0)


def test_gas_ratio_high():
    assert _gas_to_accrued_ratio_pct(5.0, 10.0) == pytest.approx(50.0)


def test_gas_ratio_exceeds_100():
    assert _gas_to_accrued_ratio_pct(20.0, 10.0) == pytest.approx(200.0)


def test_gas_ratio_zero_accrued_positive_gas():
    assert _gas_to_accrued_ratio_pct(5.0, 0.0) == GAS_RATIO_SENTINEL


def test_gas_ratio_zero_both():
    assert _gas_to_accrued_ratio_pct(0.0, 0.0) == 0.0


def test_gas_ratio_negative_accrued_treated_zero():
    assert _gas_to_accrued_ratio_pct(5.0, -10.0) == GAS_RATIO_SENTINEL


def test_gas_ratio_negative_gas_floored():
    assert _gas_to_accrued_ratio_pct(-5.0, 100.0) == 0.0


def test_gas_ratio_finite():
    assert math.isfinite(_gas_to_accrued_ratio_pct(5.0, 0.0))


# ---------------------------------------------------------------------------
# _optimal_claim_threshold_usd tests
# ---------------------------------------------------------------------------

def test_threshold_normal():
    # gas 3 / (2/100) = 150
    assert _optimal_claim_threshold_usd(3.0, 2.0) == pytest.approx(150.0)


def test_threshold_tighter_drag_higher():
    t1 = _optimal_claim_threshold_usd(3.0, 1.0)
    t2 = _optimal_claim_threshold_usd(3.0, 5.0)
    assert t1 > t2


def test_threshold_zero_gas():
    assert _optimal_claim_threshold_usd(0.0, 2.0) == 0.0


def test_threshold_zero_drag_sentinel():
    assert _optimal_claim_threshold_usd(3.0, 0.0) == DAYS_SENTINEL_NEVER


def test_threshold_negative_gas_floored():
    assert _optimal_claim_threshold_usd(-3.0, 2.0) == 0.0


def test_threshold_finite():
    assert math.isfinite(_optimal_claim_threshold_usd(3.0, 2.0))


# ---------------------------------------------------------------------------
# _expected_days_to_threshold tests
# ---------------------------------------------------------------------------

def test_days_to_threshold_normal():
    # threshold 150, accrued 50, accrual 10/day -> 10 days
    assert _expected_days_to_threshold(150.0, 50.0, 10.0) == pytest.approx(10.0)


def test_days_to_threshold_already_met():
    assert _expected_days_to_threshold(150.0, 200.0, 10.0) == 0.0


def test_days_to_threshold_exactly_met():
    assert _expected_days_to_threshold(150.0, 150.0, 10.0) == 0.0


def test_days_to_threshold_no_accrual_sentinel():
    assert _expected_days_to_threshold(150.0, 50.0, 0.0) == DAYS_SENTINEL_NEVER


def test_days_to_threshold_no_accrual_but_met():
    assert _expected_days_to_threshold(150.0, 200.0, 0.0) == 0.0


def test_days_to_threshold_negative_accrual_sentinel():
    assert _expected_days_to_threshold(150.0, 50.0, -5.0) == DAYS_SENTINEL_NEVER


def test_days_to_threshold_credits_accrued():
    far = _expected_days_to_threshold(150.0, 0.0, 10.0)
    near = _expected_days_to_threshold(150.0, 100.0, 10.0)
    assert near < far


def test_days_to_threshold_finite():
    assert math.isfinite(_expected_days_to_threshold(150.0, 50.0, 10.0))


# ---------------------------------------------------------------------------
# _recommended_claim_frequency_days tests
# ---------------------------------------------------------------------------

def test_claim_freq_normal():
    # threshold 150 / 10 per day = 15 days
    assert _recommended_claim_frequency_days(150.0, 10.0) == pytest.approx(15.0)


def test_claim_freq_zero_threshold():
    assert _recommended_claim_frequency_days(0.0, 10.0) == 0.0


def test_claim_freq_no_accrual_sentinel():
    assert _recommended_claim_frequency_days(150.0, 0.0) == DAYS_SENTINEL_NEVER


def test_claim_freq_high_accrual_low_freq():
    # very fast accrual -> sub-daily cadence
    f = _recommended_claim_frequency_days(10.0, 100.0)
    assert f < 1.0


def test_claim_freq_finite():
    assert math.isfinite(_recommended_claim_frequency_days(150.0, 10.0))


# ---------------------------------------------------------------------------
# _price_risk_haircut_pct tests
# ---------------------------------------------------------------------------

def test_price_risk_normal():
    # vol 60, 365 days -> 60 * sqrt(1) = 60
    assert _price_risk_haircut_pct(60.0, 365.0) == pytest.approx(60.0)


def test_price_risk_half_year():
    # vol 60, ~182.5 days -> 60 * sqrt(0.5)
    h = _price_risk_haircut_pct(60.0, 182.5)
    assert h == pytest.approx(60.0 * math.sqrt(0.5))


def test_price_risk_zero_days():
    assert _price_risk_haircut_pct(60.0, 0.0) == 0.0


def test_price_risk_zero_vol():
    assert _price_risk_haircut_pct(0.0, 365.0) == 0.0


def test_price_risk_negative_days_floored():
    assert _price_risk_haircut_pct(60.0, -10.0) == 0.0


def test_price_risk_capped():
    h = _price_risk_haircut_pct(500.0, 365.0 * 100.0)
    assert h <= 200.0


def test_price_risk_never_sentinel_capped():
    h = _price_risk_haircut_pct(60.0, DAYS_SENTINEL_NEVER)
    assert h == pytest.approx(200.0)


def test_price_risk_finite():
    assert math.isfinite(_price_risk_haircut_pct(60.0, DAYS_SENTINEL_NEVER))


def test_price_risk_grows_with_time():
    short = _price_risk_haircut_pct(60.0, 30.0)
    long_ = _price_risk_haircut_pct(60.0, 300.0)
    assert long_ > short


# ---------------------------------------------------------------------------
# _opportunity_cost_usd tests
# ---------------------------------------------------------------------------

def test_opp_cost_normal():
    # accrued 100, apr 5, 365 days -> 100 * 0.05 * 1 = 5
    assert _opportunity_cost_usd(100.0, 5.0, 365.0) == pytest.approx(5.0)


def test_opp_cost_partial_year():
    # accrued 100, apr 5, 73 days -> 100*0.05*(73/365)=1.0
    assert _opportunity_cost_usd(100.0, 5.0, 73.0) == pytest.approx(1.0)


def test_opp_cost_zero_days():
    assert _opportunity_cost_usd(100.0, 5.0, 0.0) == 0.0


def test_opp_cost_zero_accrued():
    assert _opportunity_cost_usd(0.0, 5.0, 365.0) == 0.0


def test_opp_cost_never_bounded_one_year():
    # never sentinel -> bounded at one year
    c = _opportunity_cost_usd(100.0, 5.0, DAYS_SENTINEL_NEVER)
    assert c == pytest.approx(5.0)


def test_opp_cost_negative_accrued_floored():
    assert _opportunity_cost_usd(-100.0, 5.0, 365.0) == 0.0


def test_opp_cost_finite():
    assert math.isfinite(_opportunity_cost_usd(100.0, 5.0, DAYS_SENTINEL_NEVER))


# ---------------------------------------------------------------------------
# _net_benefit_of_claiming_now_usd tests
# ---------------------------------------------------------------------------

def test_net_benefit_large_accrued_positive():
    # big accrued, modest gas -> positive net benefit (risk avoided dominates)
    nb = _net_benefit_of_claiming_now_usd(1000.0, 5.0, 365.0, 60.0, 3.0)
    assert nb > 0.0


def test_net_benefit_tiny_accrued_negative():
    # tiny accrued, large gas -> negative
    nb = _net_benefit_of_claiming_now_usd(2.0, 5.0, 30.0, 10.0, 10.0)
    assert nb < 0.0


def test_net_benefit_zero_accrued_is_negative_gas():
    nb = _net_benefit_of_claiming_now_usd(0.0, 5.0, 30.0, 10.0, 5.0)
    assert nb == pytest.approx(-5.0)


def test_net_benefit_finite():
    nb = _net_benefit_of_claiming_now_usd(100.0, 5.0, DAYS_SENTINEL_NEVER, 60.0, 3.0)
    assert math.isfinite(nb)


def test_net_benefit_risk_avoided_scales():
    low_risk = _net_benefit_of_claiming_now_usd(1000.0, 5.0, 30.0, 5.0, 3.0)
    high_risk = _net_benefit_of_claiming_now_usd(1000.0, 5.0, 30.0, 50.0, 3.0)
    assert high_risk > low_risk


# ---------------------------------------------------------------------------
# _claim_timing_score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _claim_timing_score(100.0, 150.0, 2.0, 10.0, 1.0, has_data=False) == 0.0


def test_score_range():
    s = _claim_timing_score(50.0, 150.0, 8.0, 5.0, 0.5, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_mature_high():
    # accrued above threshold, low gas drag, high risk + opp
    s = _claim_timing_score(300.0, 150.0, 1.0, 20.0, 5.0, has_data=True)
    assert s >= 70.0


def test_score_tiny_low():
    # accrued well below threshold, gas dwarfs
    s = _claim_timing_score(1.0, 150.0, 400.0, 0.0, 0.0, has_data=True)
    assert s <= 30.0


def test_score_mature_above_immature():
    s_mat = _claim_timing_score(300.0, 150.0, 1.0, 20.0, 5.0, has_data=True)
    s_imm = _claim_timing_score(5.0, 150.0, 80.0, 1.0, 0.0, has_data=True)
    assert s_mat > s_imm


def test_score_zero_threshold_full_maturity():
    # zero threshold (no gas) -> maturity component maxed
    s = _claim_timing_score(100.0, 0.0, 0.0, 0.0, 0.0, has_data=True)
    assert s >= 55.0


def test_score_never_threshold_zero_maturity():
    s = _claim_timing_score(100.0, DAYS_SENTINEL_NEVER, 0.0, 0.0, 0.0,
                            has_data=True)
    # maturity component is 0 in this case
    assert s <= 45.0


def test_score_finite():
    assert math.isfinite(
        _claim_timing_score(50.0, 150.0, 8.0, 5.0, 0.5, has_data=True))


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data():
    assert _classify(100.0, 150.0, 2.0, has_data=False) == CLASS_INSUFFICIENT_DATA


def test_classify_claim_now():
    assert _classify(200.0, 150.0, 1.0, has_data=True) == CLASS_CLAIM_NOW


def test_classify_claim_now_exact_threshold():
    assert _classify(150.0, 150.0, 1.0, has_data=True) == CLASS_CLAIM_NOW


def test_classify_claim_soon():
    # 50% to 100% of threshold
    assert _classify(90.0, 150.0, 5.0, has_data=True) == CLASS_CLAIM_SOON


def test_classify_accumulate():
    assert _classify(30.0, 150.0, 13.0, has_data=True) == CLASS_ACCUMULATE


def test_classify_too_small_zero_accrued():
    assert _classify(0.0, 150.0, 999.0, has_data=True) == CLASS_TOO_SMALL_TO_CLAIM


def test_classify_too_small_gas_exceeds():
    # gas ratio >= 100 and well below threshold
    assert _classify(2.0, 150.0, 200.0, has_data=True) == CLASS_TOO_SMALL_TO_CLAIM


def test_classify_zero_threshold_claim_now():
    # no gas -> threshold 0 -> claim now (free)
    assert _classify(100.0, 0.0, 0.0, has_data=True) == CLASS_CLAIM_NOW


def test_classify_never_threshold_accumulate():
    assert _classify(100.0, DAYS_SENTINEL_NEVER, 2.0,
                     has_data=True) == CLASS_ACCUMULATE


def test_classify_in_known_set():
    cases = [
        (200.0, 150.0, 1.0),
        (90.0, 150.0, 5.0),
        (30.0, 150.0, 13.0),
        (0.0, 150.0, 999.0),
        (2.0, 150.0, 200.0),
    ]
    for acc, thr, gr in cases:
        assert _classify(acc, thr, gr, has_data=True) in ALL_CLASSIFICATIONS


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


def test_grade_just_below_boundary():
    assert _grade(89.99) == "B"
    assert _grade(69.99) == "C"
    assert _grade(49.99) == "D"
    assert _grade(29.99) == "F"


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(100.0, 150.0, 2.0, 10.0, 1.0, 15.0, 8.0, 5.0,
               CLASS_CLAIM_NOW, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_claim_now():
    f = _flags(200.0, 150.0, 1.0, 5.0, 0.5, 18.0, 8.0, 100.0,
               CLASS_CLAIM_NOW, has_data=True)
    assert FLAG_CLAIM_NOW in f


def test_flag_gas_exceeds_reward():
    f = _flags(2.0, 150.0, 200.0, 5.0, 0.0, 18.0, 0.5, -10.0,
               CLASS_TOO_SMALL_TO_CLAIM, has_data=True)
    assert FLAG_GAS_EXCEEDS_REWARD in f


def test_flag_below_threshold():
    f = _flags(30.0, 150.0, 13.0, 5.0, 0.1, 18.0, 5.0, -3.0,
               CLASS_ACCUMULATE, has_data=True)
    assert FLAG_BELOW_THRESHOLD in f


def test_flag_high_price_risk():
    f = _flags(100.0, 150.0, 4.0, 20.0, 0.5, 18.0, 8.0, 10.0,
               CLASS_CLAIM_SOON, has_data=True)
    assert FLAG_HIGH_PRICE_RISK in f


def test_flag_high_opportunity_cost():
    f = _flags(100.0, 150.0, 4.0, 5.0, 2.0, 18.0, 8.0, 5.0,
               CLASS_CLAIM_SOON, has_data=True)
    assert FLAG_HIGH_OPPORTUNITY_COST in f


def test_flag_frequent_claiming_wasteful():
    # sub-daily cadence
    f = _flags(100.0, 150.0, 4.0, 5.0, 0.1, 0.5, 300.0, 5.0,
               CLASS_CLAIM_NOW, has_data=True)
    assert FLAG_FREQUENT_CLAIMING_WASTEFUL in f


def test_flag_mature_for_claim():
    f = _flags(200.0, 150.0, 1.0, 5.0, 0.5, 18.0, 8.0, 100.0,
               CLASS_CLAIM_NOW, has_data=True)
    assert FLAG_MATURE_FOR_CLAIM in f


def test_flag_mature_zero_threshold():
    # zero threshold but positive accrued -> mature
    f = _flags(100.0, 0.0, 0.0, 5.0, 0.5, 0.0, 8.0, 50.0,
               CLASS_CLAIM_NOW, has_data=True)
    assert FLAG_MATURE_FOR_CLAIM in f


def test_flag_accrual_stalled():
    f = _flags(100.0, 150.0, 4.0, 5.0, 0.5, 18.0, 0.0, 5.0,
               CLASS_ACCUMULATE, has_data=True)
    assert FLAG_ACCRUAL_STALLED in f


def test_flag_no_accrual_stalled_when_no_balance():
    f = _flags(0.0, 150.0, 999.0, 0.0, 0.0, 18.0, 0.0, -5.0,
               CLASS_TOO_SMALL_TO_CLAIM, has_data=True)
    assert FLAG_ACCRUAL_STALLED not in f


def test_flags_subset_of_all():
    f = _flags(2.0, 150.0, 200.0, 20.0, 2.0, 0.5, 0.0, -10.0,
               CLASS_TOO_SMALL_TO_CLAIM, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_INSUFFICIENT_DATA, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_claim_now_nonempty():
    recs = _recommendations(CLASS_CLAIM_NOW, [FLAG_CLAIM_NOW],
                            200.0, 3.0, 150.0, 0.0, 5.0, 1.0, 10.0, 18.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_too_small_nonempty():
    recs = _recommendations(CLASS_TOO_SMALL_TO_CLAIM,
                            [FLAG_GAS_EXCEEDS_REWARD],
                            2.0, 10.0, 500.0, 100.0, 30.0, 0.0, -8.0, 100.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_accumulate_nonempty():
    recs = _recommendations(CLASS_ACCUMULATE, [FLAG_BELOW_THRESHOLD],
                            30.0, 4.0, 200.0, 34.0, 10.0, 0.5, -3.0, 40.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_claim_soon_nonempty():
    recs = _recommendations(CLASS_CLAIM_SOON, [],
                            90.0, 3.0, 150.0, 6.0, 8.0, 0.5, 2.0, 30.0,
                            has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_mature_position(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    assert r["classification"] == CLASS_CLAIM_NOW
    assert FLAG_CLAIM_NOW in r["flags"]
    assert r["claim_timing_score"] > 50.0


def test_analyze_small_position(small_position, tmp_log):
    r = analyze(small_position, config=tmp_log)
    assert r["classification"] == CLASS_TOO_SMALL_TO_CLAIM
    assert FLAG_GAS_EXCEEDS_REWARD in r["flags"]


def test_analyze_accumulating_position(accumulating_position, tmp_log):
    r = analyze(accumulating_position, config=tmp_log)
    assert r["classification"] in (CLASS_ACCUMULATE, CLASS_CLAIM_SOON)
    assert FLAG_BELOW_THRESHOLD in r["flags"]


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["claim_timing_score"] == 0.0
    assert r["classification"] == CLASS_INSUFFICIENT_DATA


def test_analyze_no_gas_no_data(tmp_log):
    # accrued but no gas signal -> insufficient
    r = analyze({"accrued_reward_usd": 100.0, "daily_accrual_usd": 5.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_no_accrued_no_accrual_insufficient(tmp_log):
    r = analyze({"claim_gas_cost_usd": 5.0}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_poor_data_quality(mature_position, tmp_log):
    pos = dict(mature_position)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"accrued_reward_usd": 10.0, "claim_gas_cost_usd": 4.0},
                accrued_reward_usd=300.0, config=tmp_log)
    assert r["accrued_reward_usd"] == 300.0


def test_analyze_target_drag_kwarg_override(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0},
                target_gas_drag_pct=1.0, config=tmp_log)
    assert r["target_gas_drag_pct"] == 1.0
    assert r["optimal_claim_threshold_usd"] == pytest.approx(300.0)


def test_analyze_volatility_default(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0}, config=tmp_log)
    assert r["reward_token_volatility_pct"] == 60.0


def test_analyze_reinvest_default(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0}, config=tmp_log)
    assert r["reinvestment_apr_pct"] == 5.0


def test_analyze_result_keys(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    for key in (
        "name", "accrued_reward_usd", "daily_accrual_usd", "claim_gas_cost_usd",
        "reward_token_volatility_pct", "reinvestment_apr_pct",
        "days_since_last_claim", "target_gas_drag_pct", "data_quality_ok",
        "gas_to_accrued_ratio_pct", "optimal_claim_threshold_usd",
        "expected_days_to_threshold", "recommended_claim_frequency_days",
        "price_risk_haircut_pct", "opportunity_cost_usd",
        "net_benefit_of_claiming_now_usd", "claim_timing_score",
        "classification", "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"accrued_reward_usd": "x", "claim_gas_cost_usd": None,
                 "daily_accrual_usd": "y"}, config=tmp_log)
    assert isinstance(r, dict)
    assert "claim_timing_score" in r


def test_analyze_json_serialisable(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    s = json.dumps(r)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_small_json_serialisable(small_position, tmp_log):
    r = analyze(small_position, config=tmp_log)
    json.dumps(r)


def test_analyze_zero_accrued_serialisable(tmp_log):
    r = analyze({"accrued_reward_usd": 0.0, "daily_accrual_usd": 5.0,
                 "claim_gas_cost_usd": 4.0}, config=tmp_log)
    json.dumps(r)


def test_analyze_numeric_fields_finite(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v), f"{k} not finite"


def test_analyze_small_numeric_fields_finite(small_position, tmp_log):
    r = analyze(small_position, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v), f"{k} not finite"


def test_analyze_stalled_accrual_finite(tmp_log):
    # accrued but no accrual -> never sentinel internally, but result finite
    r = analyze({"accrued_reward_usd": 50.0, "daily_accrual_usd": 0.0,
                 "claim_gas_cost_usd": 4.0}, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v)
    assert FLAG_ACCRUAL_STALLED in r["flags"]


def test_analyze_writes_log(mature_position, tmp_log):
    analyze(mature_position, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_threshold_value(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0, "target_gas_drag_pct": 2.0},
                config=tmp_log)
    assert r["optimal_claim_threshold_usd"] == pytest.approx(150.0)


def test_analyze_mature_net_benefit_positive(tmp_log):
    # Large accrued still below a far-off threshold: a long wait means big
    # avoided price risk + foregone reinvest, so claiming now is clearly worth
    # the small gas. Use a tight target drag to push the threshold high and a
    # slow accrual so days-to-threshold (and thus the avoided costs) are large.
    r = analyze({"accrued_reward_usd": 5000.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 1.0, "reward_token_volatility_pct": 60.0,
                 "target_gas_drag_pct": 0.01},
                config=tmp_log)
    assert r["expected_days_to_threshold"] > 0.0
    assert r["net_benefit_of_claiming_now_usd"] > 0.0


def test_analyze_default_name(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0}, config=tmp_log)
    assert r["name"] == "UNKNOWN"


def test_analyze_name_kwarg(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0}, name="Custom", config=tmp_log)
    assert r["name"] == "Custom"


def test_analyze_gas_ratio_sentinel_when_no_accrued(tmp_log):
    r = analyze({"accrued_reward_usd": 0.0, "daily_accrual_usd": 5.0,
                 "claim_gas_cost_usd": 4.0}, config=tmp_log)
    assert r["gas_to_accrued_ratio_pct"] == GAS_RATIO_SENTINEL


def test_analyze_high_drag_target_higher_threshold(tmp_log):
    r1 = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                  "daily_accrual_usd": 5.0, "target_gas_drag_pct": 1.0},
                 config=tmp_log)
    r2 = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                  "daily_accrual_usd": 5.0, "target_gas_drag_pct": 5.0},
                 config=tmp_log)
    assert r1["optimal_claim_threshold_usd"] > r2["optimal_claim_threshold_usd"]


def test_analyze_days_since_last_claim_echoed(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0, "days_since_last_claim": 7.0},
                config=tmp_log)
    assert r["days_since_last_claim"] == 7.0


def test_analyze_score_in_range(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    assert 0.0 <= r["claim_timing_score"] <= 100.0


def test_analyze_grade_consistent_with_score(mature_position, tmp_log):
    r = analyze(mature_position, config=tmp_log)
    assert r["grade"] == _grade(r["claim_timing_score"])


def test_analyze_negative_inputs_handled(tmp_log):
    r = analyze({"accrued_reward_usd": -100.0, "claim_gas_cost_usd": -3.0,
                 "daily_accrual_usd": -5.0}, config=tmp_log)
    assert isinstance(r, dict)
    assert r["accrued_reward_usd"] == 0.0
    assert r["claim_gas_cost_usd"] == 0.0


def test_analyze_data_quality_ok_explicit(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0, "data_quality": "ok"},
                config=tmp_log)
    assert r["data_quality_ok"] is True


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_positions"] == 0
    assert r["most_ready_to_claim_position"] is None
    assert r["least_ready_to_claim_position"] is None
    assert r["avg_claim_timing_score"] == 0.0
    assert r["claim_now_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_positions"] == 0


def test_portfolio_basic(mature_position, small_position, tmp_log):
    r = analyze_portfolio([mature_position, small_position], config=tmp_log)
    assert r["total_positions"] == 2
    assert r["most_ready_to_claim_position"] == "CRV-rewards (mature)"
    assert r["least_ready_to_claim_position"] == "tiny-rewards"
    assert 0.0 <= r["avg_claim_timing_score"] <= 100.0


def test_portfolio_claim_now_count(mature_position, small_position, tmp_log):
    r = analyze_portfolio([mature_position, mature_position, small_position],
                          config=tmp_log)
    assert r["claim_now_count"] == 2


def test_portfolio_negative_net_benefit_count(small_position, tmp_log):
    r = analyze_portfolio([small_position, small_position], config=tmp_log)
    assert r["negative_net_benefit_count"] >= 1


def test_portfolio_wasteful_count(tmp_log):
    wasteful = {"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 0.5,
                "daily_accrual_usd": 500.0, "target_gas_drag_pct": 2.0}
    r = analyze_portfolio([wasteful], config=tmp_log)
    assert r["wasteful_claiming_count"] >= 0


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_positions"] == 3


def test_portfolio_results_length(mature_position, small_position, tmp_log):
    r = analyze_portfolio([mature_position, small_position], config=tmp_log)
    assert len(r["results"]) == 2


def test_portfolio_serialisable(mature_position, small_position, tmp_log):
    r = analyze_portfolio([mature_position, small_position], config=tmp_log)
    json.dumps(r)


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(mature_position, tmp_log):
    a = DeFiProtocolRewardClaimTimingOptimizer(config=tmp_log)
    r = a.analyze(mature_position)
    assert r["name"] == "CRV-rewards (mature)"


def test_class_wrapper_portfolio(mature_position, small_position, tmp_log):
    a = DeFiProtocolRewardClaimTimingOptimizer(config=tmp_log)
    r = a.analyze_portfolio([mature_position, small_position])
    assert r["total_positions"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolRewardClaimTimingOptimizer(config=tmp_log)
    r = a.analyze(None, accrued_reward_usd=200.0, claim_gas_cost_usd=3.0,
                  daily_accrual_usd=8.0)
    assert r["accrued_reward_usd"] == 200.0


def test_class_wrapper_default_config():
    a = DeFiProtocolRewardClaimTimingOptimizer()
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


def test_atomic_log_single_entry(tmp_path):
    log_path = str(tmp_path / "single.json")
    _atomic_log(log_path, {"x": 1})
    with open(log_path) as fh:
        data = json.load(fh)
    assert data == [{"x": 1}]


def test_analyze_log_accumulates(mature_position, tmp_log):
    analyze(mature_position, config=tmp_log)
    analyze(mature_position, config=tmp_log)
    analyze(mature_position, config=tmp_log)
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert len(data) == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_edge_exactly_threshold(tmp_log):
    # gas 2, drag 2 -> threshold 100; accrued exactly 100
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 2.0,
                 "daily_accrual_usd": 5.0, "target_gas_drag_pct": 2.0},
                config=tmp_log)
    assert r["optimal_claim_threshold_usd"] == pytest.approx(100.0)
    assert r["classification"] == CLASS_CLAIM_NOW


def test_edge_zero_target_drag(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 5.0, "target_gas_drag_pct": 0.0},
                config=tmp_log)
    assert r["optimal_claim_threshold_usd"] == DAYS_SENTINEL_NEVER
    json.dumps(r)


def test_edge_huge_accrued(tmp_log):
    r = analyze({"accrued_reward_usd": 1e8, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 1000.0}, config=tmp_log)
    assert r["classification"] == CLASS_CLAIM_NOW
    assert math.isfinite(r["claim_timing_score"])


def test_edge_high_volatility(tmp_log):
    r = analyze({"accrued_reward_usd": 100.0, "claim_gas_cost_usd": 3.0,
                 "daily_accrual_usd": 1.0, "reward_token_volatility_pct": 200.0},
                config=tmp_log)
    assert math.isfinite(r["price_risk_haircut_pct"])
    assert r["price_risk_haircut_pct"] <= 200.0


def test_edge_stalled_with_balance(tmp_log):
    r = analyze({"accrued_reward_usd": 50.0, "daily_accrual_usd": 0.0,
                 "claim_gas_cost_usd": 4.0}, config=tmp_log)
    assert FLAG_ACCRUAL_STALLED in r["flags"]
    assert math.isfinite(r["expected_days_to_threshold"]) or \
        r["expected_days_to_threshold"] == DAYS_SENTINEL_NEVER


def test_edge_claim_now_at_zero_gas(tmp_log):
    # accrual signal + tiny gas (still need gas>0 for has_data)
    r = analyze({"accrued_reward_usd": 100.0, "daily_accrual_usd": 5.0,
                 "claim_gas_cost_usd": 0.001}, config=tmp_log)
    assert isinstance(r, dict)
    json.dumps(r)


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_reward_claim_timing_optimizer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "claim_timing_score" in res.stdout
