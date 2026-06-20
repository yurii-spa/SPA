"""
Tests for MP-1143 DeFiProtocolStablecoinPegArbitrageAnalyzer
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

from spa_core.analytics.defi_protocol_stablecoin_peg_arbitrage_analyzer import (
    analyze,
    analyze_portfolio,
    _discount_to_peg_pct,
    _convergence_gain_pct,
    _holding_yield_over_horizon_pct,
    _gross_arb_return_if_repeg_pct,
    _annualized_arb_return_if_repeg_pct,
    _downside_loss_if_fails_pct,
    _expected_value_pct,
    _expected_annualized_pct,
    _risk_reward_ratio,
    _breakeven_repeg_probability_pct,
    _peg_arb_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolStablecoinPegArbitrageAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_STRONG_ARB,
    CLASS_ATTRACTIVE,
    CLASS_MARGINAL,
    CLASS_UNATTRACTIVE,
    CLASS_AVOID,
    CLASS_NO_ARB_OPPORTUNITY,
    FLAG_DEEP_DISCOUNT,
    FLAG_HIGH_REPEG_PROBABILITY,
    FLAG_LOW_REPEG_PROBABILITY,
    FLAG_NEGATIVE_EXPECTED_VALUE,
    FLAG_HIGH_TAIL_LOSS,
    FLAG_FAVORABLE_RISK_REWARD,
    FLAG_TRADING_ABOVE_PEG,
    FLAG_NEAR_PEG_NO_ARB,
    FLAG_INSUFFICIENT_DATA,
    BREAKEVEN_SENTINEL,
    RATIO_SENTINEL_INF,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path):
    return {"log_path": str(tmp_path / "peg_arb_log.json")}


@pytest.fixture
def strong_opportunity():
    # Mild discount, high yield, high repeg probability, shallow downside.
    return {
        "name": "USDx (strong)",
        "current_price_usd": 0.97,
        "target_peg_usd": 1.0,
        "holding_apr_pct": 8.0,
        "expected_days_to_repeg": 30.0,
        "repeg_probability_pct": 90.0,
        "downside_price_if_fails_usd": 0.95,
    }


@pytest.fixture
def weak_opportunity():
    # Deep discount, no yield, low repeg, deep downside -> negative EV.
    return {
        "name": "USDy (weak)",
        "current_price_usd": 0.70,
        "target_peg_usd": 1.0,
        "holding_apr_pct": 0.0,
        "expected_days_to_repeg": 90.0,
        "repeg_probability_pct": 20.0,
        "downside_price_if_fails_usd": 0.20,
    }


@pytest.fixture
def near_peg_opportunity():
    return {
        "name": "USDz (near peg)",
        "current_price_usd": 0.999,
        "target_peg_usd": 1.0,
        "holding_apr_pct": 5.0,
        "expected_days_to_repeg": 30.0,
        "repeg_probability_pct": 95.0,
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
# _discount_to_peg tests
# ---------------------------------------------------------------------------

def test_discount_below_peg():
    assert _discount_to_peg_pct(0.97, 1.0) == pytest.approx(3.0)


def test_discount_above_peg_negative():
    assert _discount_to_peg_pct(1.02, 1.0) == pytest.approx(-2.0)


def test_discount_zero_peg():
    assert _discount_to_peg_pct(0.97, 0.0) == 0.0


# ---------------------------------------------------------------------------
# _convergence_gain tests
# ---------------------------------------------------------------------------

def test_convergence_gain_normal():
    # (1.0 - 0.97) / 0.97 * 100
    assert _convergence_gain_pct(0.97, 1.0) == pytest.approx((0.03 / 0.97) * 100)


def test_convergence_gain_zero_current():
    assert _convergence_gain_pct(0.0, 1.0) == 0.0


def test_convergence_gain_above_peg_negative():
    assert _convergence_gain_pct(1.05, 1.0) < 0.0


# ---------------------------------------------------------------------------
# _holding_yield tests
# ---------------------------------------------------------------------------

def test_holding_yield_full_year():
    assert _holding_yield_over_horizon_pct(8.0, 365.0) == pytest.approx(8.0)


def test_holding_yield_partial():
    assert _holding_yield_over_horizon_pct(8.0, 30.0) == pytest.approx(8.0 * 30 / 365)


def test_holding_yield_zero_days():
    assert _holding_yield_over_horizon_pct(8.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# _gross / _annualized return tests
# ---------------------------------------------------------------------------

def test_gross_arb_return():
    assert _gross_arb_return_if_repeg_pct(3.0, 0.65) == pytest.approx(3.65)


def test_annualized_arb_return():
    g = _annualized_arb_return_if_repeg_pct(3.65, 30.0)
    assert g == pytest.approx(3.65 * 365 / 30)


def test_annualized_arb_return_zero_days():
    assert _annualized_arb_return_if_repeg_pct(3.65, 0.0) == 3.65


# ---------------------------------------------------------------------------
# _downside_loss tests
# ---------------------------------------------------------------------------

def test_downside_loss_normal():
    # (0.97 - 0.80)/0.97 * 100
    assert _downside_loss_if_fails_pct(0.97, 0.80) == pytest.approx((0.17 / 0.97) * 100)


def test_downside_loss_zero_current():
    assert _downside_loss_if_fails_pct(0.0, 0.5) == 0.0


def test_downside_loss_floored_when_above():
    # downside price above current => no loss, floored at 0
    assert _downside_loss_if_fails_pct(0.97, 1.10) == 0.0


# ---------------------------------------------------------------------------
# _expected_value tests
# ---------------------------------------------------------------------------

def test_expected_value_positive():
    # p=0.9, repeg gain 3.65, fail outcome = yield(0.65) - loss(2.0)
    ev = _expected_value_pct(90.0, 3.65, 2.0, 0.65)
    expected = 0.9 * 3.65 + 0.1 * (0.65 - 2.0)
    assert ev == pytest.approx(expected)


def test_expected_value_negative_when_low_prob():
    ev = _expected_value_pct(10.0, 3.0, 30.0, 0.0)
    assert ev < 0.0


def test_expected_value_prob_clamped():
    ev_hi = _expected_value_pct(150.0, 3.0, 10.0, 0.0)
    ev_100 = _expected_value_pct(100.0, 3.0, 10.0, 0.0)
    assert ev_hi == pytest.approx(ev_100)


# ---------------------------------------------------------------------------
# _expected_annualized tests
# ---------------------------------------------------------------------------

def test_expected_annualized():
    assert _expected_annualized_pct(3.0, 30.0) == pytest.approx(3.0 * 365 / 30)


def test_expected_annualized_zero_days():
    assert _expected_annualized_pct(3.0, 0.0) == 3.0


# ---------------------------------------------------------------------------
# _risk_reward_ratio tests
# ---------------------------------------------------------------------------

def test_risk_reward_normal():
    assert _risk_reward_ratio(4.0, 2.0) == pytest.approx(2.0)


def test_risk_reward_zero_downside_positive_upside():
    assert _risk_reward_ratio(3.0, 0.0) == RATIO_SENTINEL_INF


def test_risk_reward_zero_downside_zero_upside():
    assert _risk_reward_ratio(0.0, 0.0) == 0.0


def test_risk_reward_negative_upside():
    assert _risk_reward_ratio(-2.0, 5.0) == 0.0


# ---------------------------------------------------------------------------
# _breakeven_repeg_probability tests
# ---------------------------------------------------------------------------

def test_breakeven_zero_when_fail_nonnegative():
    # fail outcome >= 0 -> any prob works -> 0%
    assert _breakeven_repeg_probability_pct(3.0, 1.0) == 0.0


def test_breakeven_sentinel_when_repeg_nonpositive():
    # repeg outcome <= 0 and fail < 0 -> never
    assert _breakeven_repeg_probability_pct(-1.0, -5.0) == BREAKEVEN_SENTINEL


def test_breakeven_normal():
    # repeg 3.0, fail -2.0 -> p = 2/(3+2) = 40%
    p = _breakeven_repeg_probability_pct(3.0, -2.0)
    assert p == pytest.approx(40.0)


def test_breakeven_high_but_capped_at_100():
    # tiny upside, huge downside -> breakeven approaches but stays <= 100%
    p = _breakeven_repeg_probability_pct(0.1, -100.0)
    assert 0.0 <= p <= 100.0


# ---------------------------------------------------------------------------
# Score tests
# ---------------------------------------------------------------------------

def test_score_no_data():
    assert _peg_arb_score(5.0, 40.0, 3.0, 90.0, False, has_data=False) == 0.0


def test_score_near_peg_zero():
    assert _peg_arb_score(5.0, 40.0, 3.0, 90.0, True, has_data=True) == 0.0


def test_score_range():
    s = _peg_arb_score(3.0, 20.0, 1.5, 70.0, False, has_data=True)
    assert 0.0 <= s <= 100.0


def test_score_strong_high():
    s = _peg_arb_score(10.0, 50.0, 2.0, 100.0, False, has_data=True)
    assert s >= 80.0


def test_score_weak_low():
    s = _peg_arb_score(-5.0, 0.0, 0.0, 10.0, False, has_data=True)
    assert s <= 20.0


def test_score_higher_ev_higher_score():
    s_lo = _peg_arb_score(1.0, 10.0, 1.0, 50.0, False, has_data=True)
    s_hi = _peg_arb_score(8.0, 10.0, 1.0, 50.0, False, has_data=True)
    assert s_hi > s_lo


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_classify_no_data():
    assert _classify(50.0, 5.0, False, has_data=False) == CLASS_NO_ARB_OPPORTUNITY


def test_classify_near_peg():
    assert _classify(50.0, 5.0, True, has_data=True) == CLASS_NO_ARB_OPPORTUNITY


def test_classify_avoid_negative_ev():
    assert _classify(70.0, -1.0, False, has_data=True) == CLASS_AVOID


def test_classify_strong():
    assert _classify(85.0, 5.0, False, has_data=True) == CLASS_STRONG_ARB


def test_classify_attractive():
    assert _classify(65.0, 3.0, False, has_data=True) == CLASS_ATTRACTIVE


def test_classify_marginal():
    assert _classify(45.0, 1.0, False, has_data=True) == CLASS_MARGINAL


def test_classify_unattractive():
    assert _classify(25.0, 0.5, False, has_data=True) == CLASS_UNATTRACTIVE


def test_classify_avoid_low_score():
    assert _classify(10.0, 0.1, False, has_data=True) == CLASS_AVOID


def test_classify_in_known_set():
    for score, ev in [(85, 5), (65, 3), (45, 1), (25, 0.5), (10, 0.1), (70, -1)]:
        assert _classify(score, ev, False, has_data=True) in ALL_CLASSIFICATIONS


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
    f = _flags(3.0, 90.0, 5.0, 10.0, 2.0, False, has_data=False)
    assert f == [FLAG_INSUFFICIENT_DATA]


def test_flags_near_peg():
    f = _flags(0.2, 90.0, 5.0, 10.0, 2.0, True, has_data=True)
    assert f == [FLAG_NEAR_PEG_NO_ARB]


def test_flag_deep_discount():
    f = _flags(8.0, 80.0, 5.0, 10.0, 2.0, False, has_data=True)
    assert FLAG_DEEP_DISCOUNT in f


def test_flag_high_repeg_probability():
    f = _flags(3.0, 80.0, 5.0, 10.0, 2.0, False, has_data=True)
    assert FLAG_HIGH_REPEG_PROBABILITY in f


def test_flag_low_repeg_probability():
    f = _flags(3.0, 30.0, 5.0, 10.0, 2.0, False, has_data=True)
    assert FLAG_LOW_REPEG_PROBABILITY in f


def test_flag_negative_expected_value():
    f = _flags(3.0, 30.0, -2.0, 10.0, 0.5, False, has_data=True)
    assert FLAG_NEGATIVE_EXPECTED_VALUE in f


def test_flag_high_tail_loss():
    f = _flags(3.0, 80.0, 5.0, 25.0, 2.0, False, has_data=True)
    assert FLAG_HIGH_TAIL_LOSS in f


def test_flag_favorable_risk_reward():
    f = _flags(3.0, 80.0, 5.0, 10.0, 3.0, False, has_data=True)
    assert FLAG_FAVORABLE_RISK_REWARD in f


def test_flag_favorable_risk_reward_sentinel():
    f = _flags(3.0, 80.0, 5.0, 10.0, RATIO_SENTINEL_INF, False, has_data=True)
    assert FLAG_FAVORABLE_RISK_REWARD in f


def test_flag_trading_above_peg():
    f = _flags(-2.0, 80.0, 5.0, 10.0, 2.0, False, has_data=True)
    assert FLAG_TRADING_ABOVE_PEG in f


def test_flags_subset_of_all():
    f = _flags(8.0, 80.0, 5.0, 25.0, 3.0, False, has_data=True)
    for flag in f:
        assert flag in ALL_FLAGS


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------

def test_recommendations_no_data():
    recs = _recommendations(CLASS_NO_ARB_OPPORTUNITY, [FLAG_INSUFFICIENT_DATA],
                            0, 0, 0, 0, 0, 0, 0, 0, has_data=False)
    assert len(recs) == 1
    assert "Insufficient data" in recs[0]


def test_recommendations_near_peg():
    recs = _recommendations(CLASS_NO_ARB_OPPORTUNITY, [FLAG_NEAR_PEG_NO_ARB],
                            0.2, 0.2, 0, 0, 90, 0, 0, 0, has_data=True)
    assert len(recs) >= 1
    assert "No arbitrage" in recs[0]


def test_recommendations_strong_nonempty():
    recs = _recommendations(CLASS_STRONG_ARB, [FLAG_HIGH_REPEG_PROBABILITY],
                            3.0, 3.1, 3.0, 36.0, 90, 40, 2.0, 2.0,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_avoid_nonempty():
    recs = _recommendations(CLASS_AVOID,
                            [FLAG_NEGATIVE_EXPECTED_VALUE],
                            30.0, 42.0, -5.0, -20.0, 20, 60, 28.0, 1.5,
                            has_data=True)
    assert len(recs) >= 1


def test_recommendations_never_breakeven_branch():
    recs = _recommendations(CLASS_AVOID,
                            [FLAG_NEGATIVE_EXPECTED_VALUE],
                            5.0, 5.0, -1.0, -10.0, 50, BREAKEVEN_SENTINEL, 3.0, 1.0,
                            has_data=True)
    joined = " ".join(recs)
    assert "even a certain repeg" in joined


# ---------------------------------------------------------------------------
# analyze() integration tests
# ---------------------------------------------------------------------------

def test_analyze_strong_opportunity(strong_opportunity, tmp_log):
    r = analyze(strong_opportunity, config=tmp_log)
    assert r["discount_to_peg_pct"] == pytest.approx(3.0)
    assert r["expected_value_pct"] > 0.0
    assert r["classification"] in (CLASS_STRONG_ARB, CLASS_ATTRACTIVE)
    assert FLAG_HIGH_REPEG_PROBABILITY in r["flags"]


def test_analyze_weak_opportunity(weak_opportunity, tmp_log):
    r = analyze(weak_opportunity, config=tmp_log)
    assert r["expected_value_pct"] < 0.0
    assert FLAG_NEGATIVE_EXPECTED_VALUE in r["flags"]
    assert r["classification"] == CLASS_AVOID


def test_analyze_near_peg(near_peg_opportunity, tmp_log):
    r = analyze(near_peg_opportunity, config=tmp_log)
    assert r["is_near_peg"] is True
    assert r["classification"] == CLASS_NO_ARB_OPPORTUNITY
    assert FLAG_NEAR_PEG_NO_ARB in r["flags"]
    assert r["peg_arb_score"] == 0.0


def test_analyze_above_peg(tmp_log):
    r = analyze({"current_price_usd": 1.03, "target_peg_usd": 1.0,
                 "holding_apr_pct": 5.0}, config=tmp_log)
    assert r["discount_to_peg_pct"] < 0.0
    assert FLAG_TRADING_ABOVE_PEG in r["flags"]


def test_analyze_deep_discount_flag(tmp_log):
    r = analyze({"current_price_usd": 0.85, "target_peg_usd": 1.0,
                 "holding_apr_pct": 5.0, "repeg_probability_pct": 70.0,
                 "downside_price_if_fails_usd": 0.80}, config=tmp_log)
    assert FLAG_DEEP_DISCOUNT in r["flags"]


def test_analyze_empty_no_data(tmp_log):
    r = analyze({}, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]
    assert r["peg_arb_score"] == 0.0
    assert r["classification"] == CLASS_NO_ARB_OPPORTUNITY


def test_analyze_poor_data_quality(strong_opportunity, tmp_log):
    pos = dict(strong_opportunity)
    pos["data_quality"] = "poor"
    r = analyze(pos, config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_analyze_kwargs_override(tmp_log):
    r = analyze({"current_price_usd": 0.50},
                current_price_usd=0.97, target_peg_usd=1.0,
                holding_apr_pct=8.0, repeg_probability_pct=85.0,
                config=tmp_log)
    assert r["current_price_usd"] == 0.97
    assert r["repeg_probability_pct"] == 85.0


def test_analyze_default_downside_derived(tmp_log):
    # No downside given -> defaults to 90% of current.
    r = analyze({"current_price_usd": 0.90, "target_peg_usd": 1.0,
                 "holding_apr_pct": 5.0}, config=tmp_log)
    assert r["downside_price_if_fails_usd"] == pytest.approx(0.90 * 0.9)


def test_analyze_result_keys(strong_opportunity, tmp_log):
    r = analyze(strong_opportunity, config=tmp_log)
    for key in (
        "name", "current_price_usd", "target_peg_usd", "holding_apr_pct",
        "expected_days_to_repeg", "repeg_probability_pct",
        "downside_price_if_fails_usd", "discount_to_peg_pct",
        "convergence_gain_pct", "holding_yield_over_horizon_pct",
        "gross_arb_return_if_repeg_pct", "annualized_arb_return_if_repeg_pct",
        "downside_loss_if_fails_pct", "expected_value_pct",
        "expected_annualized_pct", "risk_reward_ratio",
        "breakeven_repeg_probability_pct", "peg_arb_score", "classification",
        "grade", "flags", "recommendations", "timestamp",
    ):
        assert key in r


def test_analyze_never_raises_on_garbage(tmp_log):
    r = analyze({"current_price_usd": "abc", "target_peg_usd": None,
                 "holding_apr_pct": [], "repeg_probability_pct": {}},
                config=tmp_log)
    assert isinstance(r, dict)
    assert "peg_arb_score" in r


def test_analyze_json_serialisable(strong_opportunity, tmp_log):
    r = analyze(strong_opportunity, config=tmp_log)
    s = json.dumps(r)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_weak_json_serialisable(weak_opportunity, tmp_log):
    r = analyze(weak_opportunity, config=tmp_log)
    json.dumps(r)


def test_analyze_sentinel_serialisable(tmp_log):
    # zero downside (above current) -> RATIO_SENTINEL_INF risk/reward stays finite
    r = analyze({"current_price_usd": 0.97, "target_peg_usd": 1.0,
                 "holding_apr_pct": 8.0, "repeg_probability_pct": 90.0,
                 "downside_price_if_fails_usd": 1.50}, config=tmp_log)
    s = json.dumps(r)
    assert "Infinity" not in s
    assert "NaN" not in s


def test_analyze_breakeven_probability_present(strong_opportunity, tmp_log):
    r = analyze(strong_opportunity, config=tmp_log)
    assert isinstance(r["breakeven_repeg_probability_pct"], (int, float))


def test_analyze_position_size_pnl(tmp_log):
    r = analyze({"current_price_usd": 0.97, "target_peg_usd": 1.0,
                 "holding_apr_pct": 8.0, "repeg_probability_pct": 90.0,
                 "downside_price_if_fails_usd": 0.95,
                 "position_size_usd": 10000.0}, config=tmp_log)
    assert r["position_size_usd"] == 10000.0
    assert r["expected_pnl_usd"] == pytest.approx(
        10000.0 * r["expected_value_pct"] / 100.0)


def test_analyze_writes_log(strong_opportunity, tmp_log):
    analyze(strong_opportunity, config=tmp_log)
    assert os.path.exists(tmp_log["log_path"])
    with open(tmp_log["log_path"]) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 1


def test_analyze_low_repeg_flag(weak_opportunity, tmp_log):
    r = analyze(weak_opportunity, config=tmp_log)
    assert FLAG_LOW_REPEG_PROBABILITY in r["flags"]


def test_analyze_high_tail_loss_flag(weak_opportunity, tmp_log):
    r = analyze(weak_opportunity, config=tmp_log)
    assert FLAG_HIGH_TAIL_LOSS in r["flags"]


# ---------------------------------------------------------------------------
# analyze_portfolio() tests
# ---------------------------------------------------------------------------

def test_portfolio_empty():
    r = analyze_portfolio([])
    assert r["total_opportunities"] == 0
    assert r["best_opportunity"] is None
    assert r["avg_peg_arb_score"] == 0.0


def test_portfolio_not_a_list():
    r = analyze_portfolio("nope")
    assert r["total_opportunities"] == 0


def test_portfolio_basic(strong_opportunity, weak_opportunity, tmp_log):
    r = analyze_portfolio([strong_opportunity, weak_opportunity], config=tmp_log)
    assert r["total_opportunities"] == 2
    assert r["best_opportunity"] == "USDx (strong)"
    assert r["worst_opportunity"] == "USDy (weak)"
    assert 0.0 <= r["avg_peg_arb_score"] <= 100.0


def test_portfolio_negative_ev_count(weak_opportunity, tmp_log):
    r = analyze_portfolio([weak_opportunity, weak_opportunity], config=tmp_log)
    assert r["negative_ev_count"] == 2


def test_portfolio_handles_non_dicts(tmp_log):
    r = analyze_portfolio([None, 5, "x"], config=tmp_log)
    assert r["total_opportunities"] == 3


# ---------------------------------------------------------------------------
# Class wrapper tests
# ---------------------------------------------------------------------------

def test_class_wrapper_analyze(strong_opportunity, tmp_log):
    a = DeFiProtocolStablecoinPegArbitrageAnalyzer(config=tmp_log)
    r = a.analyze(strong_opportunity)
    assert r["name"] == "USDx (strong)"


def test_class_wrapper_portfolio(strong_opportunity, weak_opportunity, tmp_log):
    a = DeFiProtocolStablecoinPegArbitrageAnalyzer(config=tmp_log)
    r = a.analyze_portfolio([strong_opportunity, weak_opportunity])
    assert r["total_opportunities"] == 2


def test_class_wrapper_kwargs(tmp_log):
    a = DeFiProtocolStablecoinPegArbitrageAnalyzer(config=tmp_log)
    r = a.analyze(None, current_price_usd=0.97, target_peg_usd=1.0,
                  holding_apr_pct=8.0, repeg_probability_pct=85.0)
    assert r["current_price_usd"] == 0.97


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

def test_zero_current_price_no_data(tmp_log):
    r = analyze({"current_price_usd": 0.0, "target_peg_usd": 1.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_zero_peg_no_data(tmp_log):
    r = analyze({"current_price_usd": 0.97, "target_peg_usd": 0.0},
                config=tmp_log)
    assert FLAG_INSUFFICIENT_DATA in r["flags"]


def test_exactly_at_peg_near(tmp_log):
    r = analyze({"current_price_usd": 1.0, "target_peg_usd": 1.0,
                 "holding_apr_pct": 5.0}, config=tmp_log)
    assert r["is_near_peg"] is True
    assert r["classification"] == CLASS_NO_ARB_OPPORTUNITY


def test_certain_repeg_high_score(tmp_log):
    r = analyze({"current_price_usd": 0.95, "target_peg_usd": 1.0,
                 "holding_apr_pct": 10.0, "expected_days_to_repeg": 14.0,
                 "repeg_probability_pct": 100.0,
                 "downside_price_if_fails_usd": 0.93}, config=tmp_log)
    assert r["peg_arb_score"] >= 60.0
    assert r["grade"] in ("A", "B", "C")


def test_deep_discount_zero_prob_avoid(tmp_log):
    r = analyze({"current_price_usd": 0.50, "target_peg_usd": 1.0,
                 "holding_apr_pct": 0.0, "repeg_probability_pct": 0.0,
                 "downside_price_if_fails_usd": 0.10}, config=tmp_log)
    assert r["expected_value_pct"] < 0.0
    assert r["classification"] == CLASS_AVOID
    json.dumps(r)


def test_risk_reward_in_result(strong_opportunity, tmp_log):
    r = analyze(strong_opportunity, config=tmp_log)
    assert r["risk_reward_ratio"] >= 0.0


def test_demo_main_runs():
    import subprocess
    mod = os.path.join(
        _ROOT, "spa_core", "analytics",
        "defi_protocol_stablecoin_peg_arbitrage_analyzer.py")
    res = subprocess.run([sys.executable, mod], capture_output=True, text=True)
    assert res.returncode == 0
    assert "peg_arb_score" in res.stdout
