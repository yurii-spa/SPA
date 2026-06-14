"""
Tests for MP-1145 DeFiProtocolTVLYieldElasticityAnalyzer
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

from spa_core.analytics.defi_protocol_tvl_yield_elasticity_analyzer import (
    analyze,
    analyze_portfolio,
    _incentive_share_of_apr_pct,
    _fixed_reward_flow_usd_per_year,
    _projected_incentive_apr_pct,
    _self_dilution_pct,
    _external_dilution_pct,
    _yield_elasticity,
    _total_apr_compression_pct,
    _compression_share_of_apr_pct,
    _elasticity_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolTVLYieldElasticityAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_STICKY_YIELD,
    CLASS_MILD_COMPRESSION,
    CLASS_MODERATE_COMPRESSION,
    CLASS_HIGH_COMPRESSION,
    CLASS_SEVERE_COMPRESSION,
    CLASS_INSUFFICIENT_DATA,
    FLAG_SEVERE_COMPRESSION,
    FLAG_INCENTIVE_DOMINATED,
    FLAG_BASE_YIELD_STICKY,
    FLAG_LARGE_SELF_DILUTION,
    FLAG_HIGH_EXTERNAL_INFLOW_RISK,
    FLAG_LOW_TVL_FRAGILE,
    FLAG_STICKY_YIELD,
    FLAG_INSUFFICIENT_DATA,
    ELASTICITY_SENTINEL,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "tvl_yield_elasticity_log.json")}


@pytest.fixture
def incentive_heavy_market():
    # Small, incentive-dominated pool; large self deposit -> high compression.
    return {
        "name": "FARM-pool (incentive-heavy)",
        "current_tvl_usd": 500_000.0,
        "current_apr_pct": 40.0,
        "incentive_apr_pct": 36.0,
        "your_deposit_usd": 250_000.0,
        "projected_external_inflow_usd": 500_000.0,
    }


@pytest.fixture
def base_heavy_market():
    # Deep, base-driven pool; small deposit -> sticky yield.
    return {
        "name": "stETH (base-heavy)",
        "current_tvl_usd": 50_000_000.0,
        "current_apr_pct": 4.0,
        "incentive_apr_pct": 0.5,
        "your_deposit_usd": 100_000.0,
        "projected_external_inflow_usd": 0.0,
    }


@pytest.fixture
def moderate_market():
    return {
        "name": "moderate-pool",
        "current_tvl_usd": 2_000_000.0,
        "current_apr_pct": 12.0,
        "incentive_apr_pct": 6.0,
        "your_deposit_usd": 400_000.0,
        "projected_external_inflow_usd": 0.0,
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


def test_safe_float_default():
    assert _safe_float(None, 4.0) == 4.0


def test_clamp_bounds():
    assert _clamp(-5) == 0.0
    assert _clamp(150) == 100.0
    assert _clamp(50) == 50.0


def test_clamp_custom_range():
    assert _clamp(-1, -10, 10) == -1
    assert _clamp(50, 0, 35) == 35


# ---------------------------------------------------------------------------
# _incentive_share_of_apr_pct tests
# ---------------------------------------------------------------------------

def test_incentive_share_normal():
    assert _incentive_share_of_apr_pct(36.0, 40.0) == pytest.approx(90.0)


def test_incentive_share_half():
    assert _incentive_share_of_apr_pct(6.0, 12.0) == pytest.approx(50.0)


def test_incentive_share_zero_apr():
    assert _incentive_share_of_apr_pct(5.0, 0.0) == 0.0


def test_incentive_share_clamped_100():
    assert _incentive_share_of_apr_pct(50.0, 40.0) == 100.0


def test_incentive_share_zero_incentive():
    assert _incentive_share_of_apr_pct(0.0, 10.0) == 0.0


def test_incentive_share_finite():
    assert math.isfinite(_incentive_share_of_apr_pct(5.0, 0.0))


# ---------------------------------------------------------------------------
# _fixed_reward_flow_usd_per_year tests
# ---------------------------------------------------------------------------

def test_fixed_flow_normal():
    # 36% of 500k = 180k
    assert _fixed_reward_flow_usd_per_year(36.0, 500_000.0) == pytest.approx(180_000.0)


def test_fixed_flow_zero_tvl():
    assert _fixed_reward_flow_usd_per_year(36.0, 0.0) == 0.0


def test_fixed_flow_zero_incentive():
    assert _fixed_reward_flow_usd_per_year(0.0, 500_000.0) == 0.0


def test_fixed_flow_negative_tvl_floored():
    assert _fixed_reward_flow_usd_per_year(36.0, -100.0) == 0.0


def test_fixed_flow_finite():
    assert math.isfinite(_fixed_reward_flow_usd_per_year(36.0, 500_000.0))


# ---------------------------------------------------------------------------
# _projected_incentive_apr_pct tests
# ---------------------------------------------------------------------------

def test_projected_incentive_normal():
    # flow 180k / 1.25M = 14.4%
    assert _projected_incentive_apr_pct(180_000.0, 1_250_000.0) == pytest.approx(14.4)


def test_projected_incentive_doubling_halves():
    # doubling TVL halves incentive APR
    flow = 180_000.0
    a1 = _projected_incentive_apr_pct(flow, 1_000_000.0)
    a2 = _projected_incentive_apr_pct(flow, 2_000_000.0)
    assert a2 == pytest.approx(a1 / 2.0)


def test_projected_incentive_zero_tvl():
    assert _projected_incentive_apr_pct(180_000.0, 0.0) == 0.0


def test_projected_incentive_finite():
    assert math.isfinite(_projected_incentive_apr_pct(180_000.0, 0.0))


# ---------------------------------------------------------------------------
# _self_dilution_pct tests
# ---------------------------------------------------------------------------

def test_self_dilution_normal():
    # flow 180k, tvl 500k -> 36% before; +250k -> 180k/750k=24% -> drop 12pp
    d = _self_dilution_pct(4.0, 180_000.0, 500_000.0, 250_000.0)
    assert d == pytest.approx(12.0)


def test_self_dilution_zero_deposit():
    d = _self_dilution_pct(4.0, 180_000.0, 500_000.0, 0.0)
    assert d == pytest.approx(0.0)


def test_self_dilution_zero_tvl():
    assert _self_dilution_pct(4.0, 180_000.0, 0.0, 250_000.0) == 0.0


def test_self_dilution_nonnegative():
    d = _self_dilution_pct(4.0, 180_000.0, 500_000.0, 250_000.0)
    assert d >= 0.0


def test_self_dilution_larger_deposit_more():
    d_small = _self_dilution_pct(4.0, 180_000.0, 500_000.0, 100_000.0)
    d_big = _self_dilution_pct(4.0, 180_000.0, 500_000.0, 500_000.0)
    assert d_big > d_small


def test_self_dilution_finite():
    assert math.isfinite(_self_dilution_pct(4.0, 180_000.0, 500_000.0, 250_000.0))


# ---------------------------------------------------------------------------
# _external_dilution_pct tests
# ---------------------------------------------------------------------------

def test_external_dilution_normal():
    # tvl_self = 750k -> 24%; +500k external -> 1.25M -> 14.4% -> drop 9.6pp
    d = _external_dilution_pct(180_000.0, 500_000.0, 250_000.0, 500_000.0)
    assert d == pytest.approx(9.6)


def test_external_dilution_zero_inflow():
    d = _external_dilution_pct(180_000.0, 500_000.0, 250_000.0, 0.0)
    assert d == pytest.approx(0.0)


def test_external_dilution_nonnegative():
    d = _external_dilution_pct(180_000.0, 500_000.0, 250_000.0, 500_000.0)
    assert d >= 0.0


def test_external_dilution_finite():
    assert math.isfinite(
        _external_dilution_pct(180_000.0, 500_000.0, 250_000.0, 500_000.0))


def test_external_dilution_zero_when_no_self_or_tvl():
    assert _external_dilution_pct(180_000.0, 0.0, 0.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# _yield_elasticity tests
# ---------------------------------------------------------------------------

def test_elasticity_pure_incentive_near_minus_one():
    # pure incentive (base 0): doubling TVL halves APR -> elasticity ~ -1
    # current apr 10, tvl 1M; post tvl 2M -> projected apr 5
    e = _yield_elasticity(10.0, 5.0, 1_000_000.0, 2_000_000.0)
    assert e == pytest.approx(-0.5)


def test_elasticity_smaller_drop_less_negative():
    # A smaller APR drop for the same TVL change yields a less-negative (closer
    # to 0) elasticity than a larger APR drop.
    e_small_drop = _yield_elasticity(4.0, 3.992, 50_000_000.0, 50_100_000.0)
    e_big_drop = _yield_elasticity(4.0, 3.98, 50_000_000.0, 50_100_000.0)
    assert e_small_drop > e_big_drop
    assert math.isfinite(e_small_drop)
    assert e_small_drop < 0.0


def test_elasticity_zero_apr_sentinel():
    assert _yield_elasticity(0.0, 0.0, 1_000_000.0, 2_000_000.0) == ELASTICITY_SENTINEL


def test_elasticity_zero_tvl_sentinel():
    assert _yield_elasticity(10.0, 5.0, 0.0, 100.0) == ELASTICITY_SENTINEL


def test_elasticity_no_tvl_change_sentinel():
    assert _yield_elasticity(10.0, 5.0, 1_000_000.0, 1_000_000.0) == ELASTICITY_SENTINEL


def test_elasticity_negative_for_compression():
    e = _yield_elasticity(40.0, 18.4, 500_000.0, 1_250_000.0)
    assert e < 0.0


def test_elasticity_finite():
    assert math.isfinite(_yield_elasticity(10.0, 5.0, 1_000_000.0, 2_000_000.0))
    assert math.isfinite(_yield_elasticity(0.0, 0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# _total_apr_compression_pct tests
# ---------------------------------------------------------------------------

def test_compression_positive():
    assert _total_apr_compression_pct(40.0, 18.4) == pytest.approx(21.6)


def test_compression_zero():
    assert _total_apr_compression_pct(10.0, 10.0) == 0.0


def test_compression_negative_when_apr_rises():
    assert _total_apr_compression_pct(10.0, 12.0) == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# _compression_share_of_apr_pct tests
# ---------------------------------------------------------------------------

def test_compression_share_normal():
    # 21.6 / 40 = 54%
    assert _compression_share_of_apr_pct(21.6, 40.0) == pytest.approx(54.0)


def test_compression_share_zero_apr():
    assert _compression_share_of_apr_pct(5.0, 0.0) == 0.0


def test_compression_share_negative_floored():
    assert _compression_share_of_apr_pct(-2.0, 10.0) == 0.0


def test_compression_share_finite():
    assert math.isfinite(_compression_share_of_apr_pct(21.6, 40.0))


# ---------------------------------------------------------------------------
# _elasticity_score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _elasticity_score(54.0, 90.0, has_data=False) == 0.0


def test_score_range():
    s = _elasticity_score(30.0, 50.0, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_sticky_high():
    # no compression, base-heavy (low incentive share)
    s = _elasticity_score(0.0, 10.0, has_data=True)
    assert s >= 85.0


def test_score_severe_low():
    # full compression, fully incentive
    s = _elasticity_score(100.0, 100.0, has_data=True)
    assert s <= 10.0


def test_score_sticky_above_severe():
    s_sticky = _elasticity_score(2.0, 10.0, has_data=True)
    s_severe = _elasticity_score(80.0, 95.0, has_data=True)
    assert s_sticky > s_severe


def test_score_finite():
    assert math.isfinite(_elasticity_score(54.0, 90.0, has_data=True))


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data():
    assert _classify(54.0, has_data=False) == CLASS_INSUFFICIENT_DATA


def test_classify_sticky():
    assert _classify(2.0, has_data=True) == CLASS_STICKY_YIELD


def test_classify_mild():
    assert _classify(10.0, has_data=True) == CLASS_MILD_COMPRESSION


def test_classify_moderate():
    assert _classify(25.0, has_data=True) == CLASS_MODERATE_COMPRESSION


def test_classify_high():
    assert _classify(50.0, has_data=True) == CLASS_HIGH_COMPRESSION


def test_classify_severe():
    assert _classify(70.0, has_data=True) == CLASS_SEVERE_COMPRESSION


def test_classify_boundary_sticky_mild():
    assert _classify(4.99, has_data=True) == CLASS_STICKY_YIELD
    assert _classify(5.0, has_data=True) == CLASS_MILD_COMPRESSION


def test_classify_boundary_high_severe():
    assert _classify(59.99, has_data=True) == CLASS_HIGH_COMPRESSION
    assert _classify(60.0, has_data=True) == CLASS_SEVERE_COMPRESSION


def test_classify_in_known_set():
    for share in (2.0, 10.0, 25.0, 50.0, 70.0):
        assert _classify(share, has_data=True) in ALL_CLASSIFICATIONS


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
    assert _grade(49.99) == "D"


# ---------------------------------------------------------------------------
# Flags tests
# ---------------------------------------------------------------------------

def test_flags_no_data():
    f = _flags(54.0, 90.0, 12.0, 40.0, 500_000.0, 250_000.0, 500_000.0,
               CLASS_HIGH_COMPRESSION, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flag_severe_compression():
    f = _flags(70.0, 90.0, 12.0, 40.0, 500_000.0, 250_000.0, 0.0,
               CLASS_SEVERE_COMPRESSION, has_data=True)
    assert FLAG_SEVERE_COMPRESSION in f


def test_flag_incentive_dominated():
    f = _flags(54.0, 90.0, 12.0, 40.0, 500_000.0, 250_000.0, 0.0,
               CLASS_HIGH_COMPRESSION, has_data=True)
    assert FLAG_INCENTIVE_DOMINATED in f


def test_flag_base_yield_sticky():
    # incentive share low -> base share high
    f = _flags(2.0, 12.0, 0.5, 4.0, 50_000_000.0, 100_000.0, 0.0,
               CLASS_STICKY_YIELD, has_data=True)
    assert FLAG_BASE_YIELD_STICKY in f


def test_flag_large_self_dilution():
    # self dilution 12pp / 40 apr = 30% > 10% threshold
    f = _flags(54.0, 90.0, 12.0, 40.0, 500_000.0, 250_000.0, 0.0,
               CLASS_HIGH_COMPRESSION, has_data=True)
    assert FLAG_LARGE_SELF_DILUTION in f


def test_flag_high_external_inflow_risk():
    # external inflow 500k >= 50% of 500k tvl
    f = _flags(54.0, 90.0, 12.0, 40.0, 500_000.0, 250_000.0, 500_000.0,
               CLASS_HIGH_COMPRESSION, has_data=True)
    assert FLAG_HIGH_EXTERNAL_INFLOW_RISK in f


def test_flag_low_tvl_fragile():
    f = _flags(54.0, 90.0, 5.0, 40.0, 50_000.0, 10_000.0, 0.0,
               CLASS_HIGH_COMPRESSION, has_data=True)
    assert FLAG_LOW_TVL_FRAGILE in f


def test_flag_no_low_tvl_when_deep():
    f = _flags(2.0, 12.0, 0.5, 4.0, 50_000_000.0, 100_000.0, 0.0,
               CLASS_STICKY_YIELD, has_data=True)
    assert FLAG_LOW_TVL_FRAGILE not in f


def test_flag_sticky_yield():
    f = _flags(2.0, 12.0, 0.5, 4.0, 50_000_000.0, 100_000.0, 0.0,
               CLASS_STICKY_YIELD, has_data=True)
    assert FLAG_STICKY_YIELD in f


def test_flags_subset_of_all():
    f = _flags(70.0, 90.0, 12.0, 40.0, 50_000.0, 250_000.0, 500_000.0,
               CLASS_SEVERE_COMPRESSION, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_INSUFFICIENT_DATA, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_severe_nonempty():
    recs = _recommendations(CLASS_SEVERE_COMPRESSION, [FLAG_SEVERE_COMPRESSION],
                            40.0, 14.0, 26.0, 90.0, 12.0, 9.6, -0.6,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_sticky_nonempty():
    recs = _recommendations(CLASS_STICKY_YIELD, [FLAG_STICKY_YIELD],
                            4.0, 3.99, 0.01, 12.0, 0.0, 0.0, -0.01,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_moderate_nonempty():
    recs = _recommendations(CLASS_MODERATE_COMPRESSION, [],
                            12.0, 9.0, 3.0, 50.0, 2.0, 0.0, -0.4,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_high_nonempty():
    recs = _recommendations(CLASS_HIGH_COMPRESSION, [FLAG_LARGE_SELF_DILUTION],
                            40.0, 18.4, 21.6, 90.0, 12.0, 9.6, -0.36,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_mild_nonempty():
    recs = _recommendations(CLASS_MILD_COMPRESSION, [],
                            12.0, 11.0, 1.0, 30.0, 0.5, 0.0, -0.1,
                            has_data=True)
    assert len(recs) >= 1


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_incentive_heavy(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    assert r["total_apr_compression_pct"] > 0.0
    assert FLAG_INCENTIVE_DOMINATED in r["flags"]
    assert r["classification"] in (
        CLASS_HIGH_COMPRESSION, CLASS_SEVERE_COMPRESSION,
        CLASS_MODERATE_COMPRESSION)


def test_analyze_base_heavy(base_heavy_market, tmp_log):
    r = analyze(base_heavy_market, config=tmp_log)
    assert r["classification"] in (CLASS_STICKY_YIELD, CLASS_MILD_COMPRESSION)
    assert r["elasticity_score"] > 50.0


def test_analyze_base_apr_computed(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    assert r["base_apr_pct"] == pytest.approx(4.0)


def test_analyze_incentive_defaults_to_full_apr(tmp_log):
    # no incentive_apr_pct provided -> whole APR is incentive, base 0
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "your_deposit_usd": 0.0}, config=tmp_log)
    assert r["incentive_apr_pct"] == pytest.approx(10.0)
    assert r["base_apr_pct"] == pytest.approx(0.0)


def test_analyze_incentive_clamped_to_apr(tmp_log):
    # incentive > current apr -> clamped
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 50.0}, config=tmp_log)
    assert r["incentive_apr_pct"] == pytest.approx(10.0)
    assert r["base_apr_pct"] == pytest.approx(0.0)


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["elasticity_score"] == 0.0
    assert r["classification"] == CLASS_INSUFFICIENT_DATA


def test_analyze_zero_tvl_insufficient(tmp_log):
    r = analyze({"current_tvl_usd": 0.0, "current_apr_pct": 10.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_zero_apr_insufficient(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 0.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_negative_tvl_insufficient(tmp_log):
    r = analyze({"current_tvl_usd": -100.0, "current_apr_pct": 10.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["current_tvl_usd"] == 0.0


def test_analyze_poor_data_quality(incentive_heavy_market, tmp_log):
    m = dict(incentive_heavy_market)
    m["data_quality"] = "poor"
    r = analyze(m, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"current_tvl_usd": 100.0, "current_apr_pct": 5.0},
                current_tvl_usd=1_000_000.0, config=tmp_log)
    assert r["current_tvl_usd"] == 1_000_000.0


def test_analyze_external_inflow_default_zero(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 5.0, "your_deposit_usd": 0.0},
                config=tmp_log)
    assert r["projected_external_inflow_usd"] == 0.0


def test_analyze_result_keys(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    for key in (
        "name", "current_tvl_usd", "current_apr_pct", "incentive_apr_pct",
        "base_apr_pct", "your_deposit_usd", "projected_external_inflow_usd",
        "data_quality_ok", "incentive_share_of_apr_pct",
        "fixed_reward_flow_usd_per_year", "post_deposit_tvl_usd",
        "projected_incentive_apr_pct", "projected_apr_pct", "self_dilution_pct",
        "external_dilution_pct", "total_apr_compression_pct",
        "compression_share_of_apr_pct", "yield_elasticity", "elasticity_score",
        "classification", "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"current_tvl_usd": "x", "current_apr_pct": None,
                 "incentive_apr_pct": "y"}, config=tmp_log)
    assert isinstance(r, dict)
    assert "elasticity_score" in r


def test_analyze_json_serialisable(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    s = json.dumps(r)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_base_heavy_json_serialisable(base_heavy_market, tmp_log):
    r = analyze(base_heavy_market, config=tmp_log)
    json.dumps(r)


def test_analyze_empty_json_serialisable(tmp_log):
    r = analyze({}, config=tmp_log)
    json.dumps(r)


def test_analyze_numeric_fields_finite(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v), f"{k} not finite"


def test_analyze_base_heavy_numeric_finite(base_heavy_market, tmp_log):
    r = analyze(base_heavy_market, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v), f"{k} not finite"


def test_analyze_empty_numeric_finite(tmp_log):
    r = analyze({}, config=tmp_log)
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert math.isfinite(v)


def test_analyze_writes_log(incentive_heavy_market, tmp_log):
    analyze(incentive_heavy_market, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_post_deposit_tvl(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 8.0, "your_deposit_usd": 200_000.0,
                 "projected_external_inflow_usd": 300_000.0}, config=tmp_log)
    assert r["post_deposit_tvl_usd"] == pytest.approx(1_500_000.0)


def test_analyze_fixed_flow_value(tmp_log):
    r = analyze({"current_tvl_usd": 500_000.0, "current_apr_pct": 40.0,
                 "incentive_apr_pct": 36.0}, config=tmp_log)
    assert r["fixed_reward_flow_usd_per_year"] == pytest.approx(180_000.0)


def test_analyze_doubling_tvl_halves_incentive(tmp_log):
    # deposit equal to current tvl doubles tvl -> incentive apr halves
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 10.0, "your_deposit_usd": 1_000_000.0},
                config=tmp_log)
    assert r["projected_incentive_apr_pct"] == pytest.approx(5.0)
    assert r["projected_apr_pct"] == pytest.approx(5.0)


def test_analyze_sticky_base_no_dilution(tmp_log):
    # all base, no incentive -> no compression regardless of deposit
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 5.0,
                 "incentive_apr_pct": 0.0, "your_deposit_usd": 1_000_000.0},
                config=tmp_log)
    assert r["total_apr_compression_pct"] == pytest.approx(0.0)
    assert r["classification"] == CLASS_STICKY_YIELD


def test_analyze_self_dilution_value(tmp_log):
    r = analyze({"current_tvl_usd": 500_000.0, "current_apr_pct": 40.0,
                 "incentive_apr_pct": 36.0, "your_deposit_usd": 250_000.0},
                config=tmp_log)
    assert r["self_dilution_pct"] == pytest.approx(12.0)


def test_analyze_default_name(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0},
                config=tmp_log)
    assert r["name"] == "UNKNOWN"


def test_analyze_name_kwarg(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0},
                name="MyPool", config=tmp_log)
    assert r["name"] == "MyPool"


def test_analyze_score_in_range(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    assert 0.0 <= r["elasticity_score"] <= 100.0


def test_analyze_grade_consistent_with_score(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    assert r["grade"] == _grade(r["elasticity_score"])


def test_analyze_elasticity_negative_for_incentive(incentive_heavy_market, tmp_log):
    r = analyze(incentive_heavy_market, config=tmp_log)
    assert r["yield_elasticity"] < 0.0


def test_analyze_no_deposit_no_compression(tmp_log):
    # no deposit, no inflow -> no tvl change -> no compression
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 8.0, "your_deposit_usd": 0.0,
                 "projected_external_inflow_usd": 0.0}, config=tmp_log)
    assert r["total_apr_compression_pct"] == pytest.approx(0.0)
    assert r["yield_elasticity"] == ELASTICITY_SENTINEL


def test_analyze_low_tvl_fragile_flag(tmp_log):
    r = analyze({"current_tvl_usd": 50_000.0, "current_apr_pct": 30.0,
                 "incentive_apr_pct": 28.0, "your_deposit_usd": 10_000.0},
                config=tmp_log)
    assert FLAG_LOW_TVL_FRAGILE in r["flags"]


def test_analyze_data_quality_ok_explicit(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "data_quality": "ok"}, config=tmp_log)
    assert r["data_quality_ok"] is True


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_markets"] == 0
    assert r["most_compression_prone_market"] is None
    assert r["least_compression_prone_market"] is None
    assert r["avg_elasticity_score"] == 0.0
    assert r["severe_compression_count"] == 0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_markets"] == 0


def test_portfolio_basic(incentive_heavy_market, base_heavy_market, tmp_log):
    r = analyze_portfolio([incentive_heavy_market, base_heavy_market],
                          config=tmp_log)
    assert r["total_markets"] == 2
    # incentive-heavy is most compression-prone (lowest elasticity score)
    assert r["most_compression_prone_market"] == "FARM-pool (incentive-heavy)"
    assert r["least_compression_prone_market"] == "stETH (base-heavy)"
    assert 0.0 <= r["avg_elasticity_score"] <= 100.0


def test_portfolio_severe_count(tmp_log):
    severe = {"current_tvl_usd": 100_000.0, "current_apr_pct": 50.0,
              "incentive_apr_pct": 50.0, "your_deposit_usd": 300_000.0}
    r = analyze_portfolio([severe, severe], config=tmp_log)
    assert r["severe_compression_count"] >= 1


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_markets"] == 3


def test_portfolio_results_length(incentive_heavy_market, base_heavy_market, tmp_log):
    r = analyze_portfolio([incentive_heavy_market, base_heavy_market],
                          config=tmp_log)
    assert len(r["results"]) == 2


def test_portfolio_serialisable(incentive_heavy_market, base_heavy_market, tmp_log):
    r = analyze_portfolio([incentive_heavy_market, base_heavy_market],
                          config=tmp_log)
    json.dumps(r)


def test_portfolio_avg_correct(moderate_market, tmp_log):
    r = analyze_portfolio([moderate_market, moderate_market], config=tmp_log)
    scores = [res["elasticity_score"] for res in r["results"]]
    assert r["avg_elasticity_score"] == pytest.approx(sum(scores) / 2.0)


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(incentive_heavy_market, tmp_log):
    a = DeFiProtocolTVLYieldElasticityAnalyzer(config=tmp_log)
    r = a.analyze(incentive_heavy_market)
    assert r["name"] == "FARM-pool (incentive-heavy)"


def test_class_wrapper_portfolio(incentive_heavy_market, base_heavy_market, tmp_log):
    a = DeFiProtocolTVLYieldElasticityAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([incentive_heavy_market, base_heavy_market])
    assert r["total_markets"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolTVLYieldElasticityAnalyzer(config=tmp_log)
    r = a.analyze(None, current_tvl_usd=1_000_000.0, current_apr_pct=10.0,
                  incentive_apr_pct=5.0)
    assert r["current_tvl_usd"] == 1_000_000.0


def test_class_wrapper_default_config():
    a = DeFiProtocolTVLYieldElasticityAnalyzer()
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


def test_analyze_log_accumulates(incentive_heavy_market, tmp_log):
    analyze(incentive_heavy_market, config=tmp_log)
    analyze(incentive_heavy_market, config=tmp_log)
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert len(data) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_edge_tiny_tvl_huge_deposit(tmp_log):
    r = analyze({"current_tvl_usd": 1_000.0, "current_apr_pct": 100.0,
                 "incentive_apr_pct": 100.0, "your_deposit_usd": 1_000_000.0},
                config=tmp_log)
    assert math.isfinite(r["elasticity_score"])
    assert r["classification"] == CLASS_SEVERE_COMPRESSION
    json.dumps(r)


def test_edge_deep_pool_tiny_deposit(tmp_log):
    r = analyze({"current_tvl_usd": 100_000_000.0, "current_apr_pct": 4.0,
                 "incentive_apr_pct": 0.2, "your_deposit_usd": 1_000.0},
                config=tmp_log)
    assert r["classification"] == CLASS_STICKY_YIELD


def test_edge_all_incentive_doubling(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 20.0,
                 "incentive_apr_pct": 20.0, "your_deposit_usd": 1_000_000.0},
                config=tmp_log)
    # halving the incentive APR (= total) -> 50% compression -> severe-ish
    assert r["projected_apr_pct"] == pytest.approx(10.0)
    assert r["compression_share_of_apr_pct"] == pytest.approx(50.0)


def test_edge_external_inflow_only(tmp_log):
    r = analyze({"current_tvl_usd": 1_000_000.0, "current_apr_pct": 10.0,
                 "incentive_apr_pct": 10.0, "your_deposit_usd": 0.0,
                 "projected_external_inflow_usd": 1_000_000.0}, config=tmp_log)
    assert r["self_dilution_pct"] == pytest.approx(0.0)
    assert r["external_dilution_pct"] > 0.0


def test_edge_negative_inputs_handled(tmp_log):
    r = analyze({"current_tvl_usd": -100.0, "current_apr_pct": -5.0,
                 "your_deposit_usd": -200.0}, config=tmp_log)
    assert isinstance(r, dict)
    assert r["current_tvl_usd"] == 0.0
    assert r["your_deposit_usd"] == 0.0


def test_edge_grade_severe_low(tmp_log):
    r = analyze({"current_tvl_usd": 100_000.0, "current_apr_pct": 60.0,
                 "incentive_apr_pct": 60.0, "your_deposit_usd": 500_000.0},
                config=tmp_log)
    assert r["grade"] in ("D", "F")


def test_edge_grade_sticky_high(tmp_log):
    r = analyze({"current_tvl_usd": 50_000_000.0, "current_apr_pct": 4.0,
                 "incentive_apr_pct": 0.1, "your_deposit_usd": 10_000.0},
                config=tmp_log)
    assert r["grade"] in ("A", "B")


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_tvl_yield_elasticity_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "elasticity_score" in res.stdout
