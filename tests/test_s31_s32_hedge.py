"""
tests/test_s31_s32_hedge.py — S31 Bear Market Hedge + S32 Market Neutral (35 tests)

Motivation: the S7 Pendle-YT backtest posted −14.28% APY (3.73% max DD) in the
bear scenario. S31 detects the regime and rotates to a capital-preservation book;
S32 holds a fixed market-neutral 50/45/5 split rebalanced weekly. These tests are
offline / stdlib-safe — strategies fall back to deterministic default APYs, so no
assertion depends on the network.

Coverage:
  - S31 allocates correctly in BEAR / BULL regimes (zero T2, zero YT in bear)
  - S31 regime detection across all three signals
  - S31 gradual 7-day / ~14%-per-day transition (anti-whipsaw)
  - S32 fixed 50% T1 / 45% T2 / 5% cash with equal weights inside sleeves
  - S32 top-3 T2 selection by APY + weekly rebalance cadence
"""
from __future__ import annotations

import pytest

from spa_core.strategies.s31_bear_market_hedge import (
    BearMarketHedgeStrategy,
    BEAR_WEIGHTS,
    BULL_WEIGHTS,
    TRANSITION_DAYS,
    DAILY_ROTATION_FRACTION,
    AAVE_UTIL_BEAR_THRESHOLD,
    T2_APY_BEAR_THRESHOLD,
    APY_DECLINE_BEAR_THRESHOLD,
    BEAR_TARGET_APY_MIN,
    BEAR_TARGET_APY_MAX,
    BULL_TARGET_APY_MIN,
    BULL_TARGET_APY_MAX,
)
from spa_core.strategies.s32_market_neutral import (
    MarketNeutralStrategy,
    T1_SLEEVE_WEIGHT,
    T2_SLEEVE_WEIGHT,
    CASH_WEIGHT,
    T1_PROTOCOLS,
    T2_PICK_COUNT,
    REBALANCE_INTERVAL_DAYS,
    TARGET_APY_MIN as S32_APY_MIN,
    TARGET_APY_MAX as S32_APY_MAX,
)

CAPITAL = 100_000.0
T2_PROTOS = {"fluid", "ethena", "yearn_v3", "morpho_steakhouse", "euler_v2", "morpho_blue"}
YT_PROTOS = {"pendle_yt", "yt"}


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def s31():
    return BearMarketHedgeStrategy()


@pytest.fixture
def s32():
    return MarketNeutralStrategy()


# ════════════════════════════════════════════════════════════════════════════
# S31 — Bear Market Hedge: allocation in each regime (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s31_instantiation(s31):
    assert s31.STRATEGY_ID == "S31"
    assert s31.STRATEGY_NAME == "Bear Market Hedge"


def test_s31_bear_weights_sum_to_one():
    assert abs(sum(BEAR_WEIGHTS.values()) - 1.0) < 1e-9


def test_s31_bull_weights_sum_to_one():
    assert abs(sum(BULL_WEIGHTS.values()) - 1.0) < 1e-9


def test_s31_bear_allocation_80pct_t1(s31):
    alloc = s31.get_allocation(CAPITAL, "bear")
    t1 = alloc["aave_v3"] + alloc["compound_v3"]
    assert abs(t1 - 0.80 * CAPITAL) < 1e-6          # 40% + 40%
    assert abs(alloc["sky_susds"] - 0.15 * CAPITAL) < 1e-6
    assert abs(alloc["cash"] - 0.05 * CAPITAL) < 1e-6


def test_s31_bear_zero_t2_exposure(s31):
    alloc = s31.get_allocation(CAPITAL, "bear")
    for p in T2_PROTOS:
        assert alloc.get(p, 0.0) == 0.0


def test_s31_bear_zero_pendle_yt_exposure(s31):
    alloc = s31.get_allocation(CAPITAL, "bear")
    assert alloc.get("pendle_pt", 0.0) == 0.0
    for p in YT_PROTOS:
        assert alloc.get(p, 0.0) == 0.0


def test_s31_bull_allocation_split(s31):
    alloc = s31.get_allocation(CAPITAL, "bull")
    t1 = alloc["aave_v3"] + alloc["compound_v3"]
    t2 = alloc["fluid"] + alloc["ethena"]
    assert abs(t1 - 0.50 * CAPITAL) < 1e-6
    assert abs(t2 - 0.35 * CAPITAL) < 1e-6
    assert abs(alloc["pendle_pt"] - 0.10 * CAPITAL) < 1e-6
    assert abs(alloc["cash"] - 0.05 * CAPITAL) < 1e-6


def test_s31_bull_uses_pendle_pt_not_yt(s31):
    alloc = s31.get_allocation(CAPITAL, "bull")
    assert alloc["pendle_pt"] > 0.0          # PT (fixed-rate) allowed in bull
    for p in YT_PROTOS:
        assert alloc.get(p, 0.0) == 0.0      # never YT


# ════════════════════════════════════════════════════════════════════════════
# S31 — APY targets in each regime (4)
# ════════════════════════════════════════════════════════════════════════════

def test_s31_bear_apy_in_target_range(s31):
    apy = s31.get_expected_apy("bear")
    assert BEAR_TARGET_APY_MIN <= apy <= BEAR_TARGET_APY_MAX


def test_s31_bull_apy_in_target_range(s31):
    apy = s31.get_expected_apy("bull")
    assert BULL_TARGET_APY_MIN <= apy <= BULL_TARGET_APY_MAX


def test_s31_bull_apy_exceeds_bear_apy(s31):
    assert s31.get_expected_apy("bull") > s31.get_expected_apy("bear")


def test_s31_apy_map_override_changes_apy(s31):
    base = s31.get_expected_apy("bear")
    bumped = s31.get_expected_apy("bear", {"aave_v3": 8.0, "compound_v3": 8.0})
    assert bumped > base


# ════════════════════════════════════════════════════════════════════════════
# S31 — Regime detection (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s31_detect_bull_when_no_signals(s31):
    assert s31.detect_regime({"aave_utilization": 0.75, "avg_t2_apy": 8.0,
                              "max_weekly_apy_decline": 0.1}) == "bull"


def test_s31_detect_bear_low_utilization(s31):
    assert s31.detect_regime({"aave_utilization": 0.40}) == "bear"


def test_s31_detect_bear_low_t2_apy(s31):
    assert s31.detect_regime({"avg_t2_apy": 3.5}) == "bear"


def test_s31_detect_bear_apy_declining(s31):
    assert s31.detect_regime({"max_weekly_apy_decline": 1.5}) == "bear"


def test_s31_utilization_threshold_boundary(s31):
    sig = s31.bear_signals({"aave_utilization": AAVE_UTIL_BEAR_THRESHOLD})
    assert sig["low_utilization"] is False        # exactly at threshold = not bear
    sig2 = s31.bear_signals({"aave_utilization": AAVE_UTIL_BEAR_THRESHOLD - 0.01})
    assert sig2["low_utilization"] is True


def test_s31_utilization_accepts_percent_form(s31):
    # 45.0 (percent) and 0.45 (fraction) must both read as bear.
    assert s31.detect_regime({"aave_utilization": 45.0}) == "bear"
    assert s31.detect_regime({"aave_utilization": 0.45}) == "bear"


def test_s31_t2_apy_threshold_boundary(s31):
    assert s31.bear_signals({"avg_t2_apy": T2_APY_BEAR_THRESHOLD})["low_t2_apy"] is False
    assert s31.bear_signals({"avg_t2_apy": T2_APY_BEAR_THRESHOLD - 0.1})["low_t2_apy"] is True


def test_s31_decline_threshold_boundary(s31):
    assert s31.bear_signals({"max_weekly_apy_decline": APY_DECLINE_BEAR_THRESHOLD})["apy_declining"] is False
    assert s31.bear_signals({"max_weekly_apy_decline": APY_DECLINE_BEAR_THRESHOLD + 0.1})["apy_declining"] is True


# ════════════════════════════════════════════════════════════════════════════
# S31 — Gradual 7-day / ~14%-per-day transition (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s31_transition_days_is_7():
    assert TRANSITION_DAYS == 7


def test_s31_daily_rotation_is_about_14pct():
    assert abs(DAILY_ROTATION_FRACTION - 1.0 / 7.0) < 1e-9
    assert 0.14 <= DAILY_ROTATION_FRACTION <= 0.15


def test_s31_transition_completes_in_7_days():
    s = BearMarketHedgeStrategy("bull")
    for _ in range(TRANSITION_DAYS):
        s.step_day("bear")
    assert s.transition_progress == pytest.approx(1.0)
    assert s.get_current_weights()["aave_v3"] == pytest.approx(BEAR_WEIGHTS["aave_v3"])


def test_s31_transition_step_size_is_one_seventh():
    s = BearMarketHedgeStrategy("bull")
    start = BULL_WEIGHTS["aave_v3"]
    target = BEAR_WEIGHTS["aave_v3"]
    s.step_day("bear")                       # day 1
    expected = start + (target - start) * (1.0 / 7.0)
    assert s.get_current_weights()["aave_v3"] == pytest.approx(expected)


def test_s31_transition_not_instant():
    s = BearMarketHedgeStrategy("bull")
    s.step_day("bear")                       # one day only
    # After a single day the book is NOT yet fully defensive.
    assert s.get_current_weights()["aave_v3"] < BEAR_WEIGHTS["aave_v3"]
    assert s.is_transitioning() is True


def test_s31_transition_per_day_turnover_about_14pct():
    s = BearMarketHedgeStrategy("bull")
    prev = s.get_current_weights()
    s.step_day("bear")
    cur = s.get_current_weights()
    # L1 turnover / 2 (one-sided) ≈ 1/7 of the total weight that must move.
    turnover = sum(abs(cur[p] - prev[p]) for p in cur) / 2.0
    total_move = sum(abs(BEAR_WEIGHTS[p] - BULL_WEIGHTS[p]) for p in BEAR_WEIGHTS) / 2.0
    assert turnover == pytest.approx(total_move / 7.0, rel=1e-6)


def test_s31_transition_resets_on_regime_flip():
    s = BearMarketHedgeStrategy("bull")
    s.step_day("bear")
    s.step_day("bear")                       # progress ~2/7 toward bear
    mid = s.get_current_weights()["aave_v3"]
    s.step_day("bull")                       # flip back — fresh rotation from mid
    assert s.active_regime == "bull"
    assert s.transition_progress == pytest.approx(1.0 / 7.0)
    # Heading back toward bull (lower aave weight than the partial-bear midpoint).
    assert s.get_current_weights()["aave_v3"] < mid


def test_s31_no_transition_when_regime_unchanged():
    s = BearMarketHedgeStrategy("bear")      # already settled at bear
    before = s.get_current_weights()
    s.step_day("bear")
    assert s.get_current_weights() == before
    assert s.transition_progress == pytest.approx(1.0)


# ════════════════════════════════════════════════════════════════════════════
# S31 — Simulation, risk, structure (3)
# ════════════════════════════════════════════════════════════════════════════

def test_s31_simulate_bear_positive_yield(s31):
    res = s31.simulate(CAPITAL, {"aave_utilization": 0.40})
    assert res["detected_regime"] == "bear"
    assert res["expected_annual_yield_usd"] > 0.0
    assert res["status"] == "ok"


def test_s31_risk_summary_zero_yt_both_regimes(s31):
    assert s31.get_risk_summary("bear")["yt_exposure_pct"] == 0.0
    assert s31.get_risk_summary("bull")["yt_exposure_pct"] == 0.0


def test_s31_bear_drawdown_target_under_half_pct(s31):
    assert s31.get_risk_summary("bear")["max_drawdown_pct"] <= 0.5


# ════════════════════════════════════════════════════════════════════════════
# S32 — Market Neutral: fixed 50/45/5 (7)
# ════════════════════════════════════════════════════════════════════════════

def test_s32_instantiation(s32):
    assert s32.STRATEGY_ID == "S32"
    assert s32.STRATEGY_NAME == "Market Neutral"


def test_s32_sleeve_weights_50_45_5():
    assert abs(T1_SLEEVE_WEIGHT - 0.50) < 1e-9
    assert abs(T2_SLEEVE_WEIGHT - 0.45) < 1e-9
    assert abs(CASH_WEIGHT - 0.05) < 1e-9
    assert abs(T1_SLEEVE_WEIGHT + T2_SLEEVE_WEIGHT + CASH_WEIGHT - 1.0) < 1e-9


def test_s32_allocation_sleeve_totals(s32):
    alloc = s32.get_allocation(CAPITAL)
    t1 = sum(alloc[p] for p in T1_PROTOCOLS)
    t2 = sum(alloc[p] for p in s32.select_t2())
    assert abs(t1 - 0.50 * CAPITAL) < 1e-3      # equal-weight thirds → 6dp rounding
    assert abs(t2 - 0.45 * CAPITAL) < 1e-3
    assert abs(alloc["cash"] - 0.05 * CAPITAL) < 1e-6


def test_s32_allocation_sums_to_capital(s32):
    alloc = s32.get_allocation(CAPITAL)
    assert abs(sum(alloc.values()) - CAPITAL) < 1e-3   # 6dp rounding on equal thirds


def test_s32_t1_equal_weight(s32):
    tw = s32.target_weights()
    each = T1_SLEEVE_WEIGHT / len(T1_PROTOCOLS)
    for p in T1_PROTOCOLS:
        assert tw[p] == pytest.approx(each)


def test_s32_t2_equal_weight(s32):
    tw = s32.target_weights()
    picks = s32.select_t2()
    each = T2_SLEEVE_WEIGHT / len(picks)
    for p in picks:
        assert tw[p] == pytest.approx(each)


def test_s32_t1_protocols_are_aave_compound_sky():
    assert set(T1_PROTOCOLS) == {"aave_v3", "compound_v3", "sky_susds"}


# ════════════════════════════════════════════════════════════════════════════
# S32 — T2 selection, rebalance cadence, APY (7)
# ════════════════════════════════════════════════════════════════════════════

def test_s32_selects_top3_t2(s32):
    assert len(s32.select_t2()) == T2_PICK_COUNT == 3


def test_s32_t2_selection_follows_apy(s32):
    # Force euler_v2 and morpho_blue to the top via a live-APY override.
    picks = s32.select_t2({"euler_v2": 20.0, "morpho_blue": 19.0})
    assert "euler_v2" in picks
    assert "morpho_blue" in picks


def test_s32_t2_selection_deterministic(s32):
    assert s32.select_t2() == s32.select_t2()        # stable ordering, no RNG


def test_s32_rebalance_weekly_cadence(s32):
    assert s32.should_rebalance(0) is True
    assert s32.should_rebalance(7) is True
    assert s32.should_rebalance(14) is True
    assert s32.should_rebalance(REBALANCE_INTERVAL_DAYS) is True


def test_s32_no_rebalance_off_cadence(s32):
    for d in (1, 3, 5, 6, 8, 13):
        assert s32.should_rebalance(d) is False


def test_s32_apy_in_target_range(s32):
    apy = s32.get_expected_apy()
    assert S32_APY_MIN <= apy <= S32_APY_MAX


def test_s32_simulate_rebalances_on_day7(s32):
    assert s32.simulate(CAPITAL, day=7)["rebalanced"] is True
    assert s32.simulate(CAPITAL, day=5)["rebalanced"] is False


# ════════════════════════════════════════════════════════════════════════════
# Cross-cutting: registry + drawdown discipline (2)
# ════════════════════════════════════════════════════════════════════════════

def test_both_registered_in_registry():
    from spa_core.strategies.strategy_registry import REGISTRY
    assert REGISTRY.get("S31") is not None
    assert REGISTRY.get("S32") is not None
    assert REGISTRY.get("S31").handler_class == "BearMarketHedgeStrategy"
    assert REGISTRY.get("S32").handler_class == "MarketNeutralStrategy"


def test_s32_low_drawdown_target(s32):
    assert s32.get_risk_summary()["max_drawdown_pct"] <= 1.0
    assert s32.get_risk_summary()["market_neutral"] is True
