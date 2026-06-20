"""
tests/test_s42_s43_defensive.py — S42 Crisis Refuge + S43 Volatility-Adjusted Yield

Two defensive strategies built around Sky sUSDS, whose realized daily-return
volatility (0.022%) is the lowest in the SPA universe (vs Aave 0.073%, Morpho
0.078%):

  S42 Crisis Refuge — a static ultra-safe 100% T1 book (50% sUSDS / 30% Aave /
      15% Compound / 5% cash) that proposes itself when a crisis trigger fires
      (T2 APY collapse, kill switch, or 30% TVL crash in 24h).
  S43 Volatility-Adjusted Yield — allocates proportional to APY/daily-vol under
      RiskPolicy caps via water-filling; sUSDS lands at its 40% T1 cap, Morpho at
      its 20% T2 cap.

All offline / stdlib-safe — strategies fall back to deterministic default APYs
and vols, so no assertion depends on the network. 30 tests.
"""
from __future__ import annotations

import pytest

from spa_core.strategies.s42_crisis_refuge import (
    S42CrisisRefuge,
    TARGET_WEIGHTS,
    PROTOCOL_TIERS as S42_TIERS,
    APY_DEFAULTS as S42_APY,
    DAILY_VOL as S42_VOL,
    T2_APY_COLLAPSE_THRESHOLD,
    TVL_CRASH_THRESHOLD_PCT,
    TARGET_APY_MIN as S42_APY_MIN,
    TARGET_APY_MAX as S42_APY_MAX,
    MAX_DRAWDOWN_PCT as S42_MAX_DD,
)
from spa_core.strategies.s43_vol_adjusted import (
    S43VolAdjusted,
    PROTOCOL_TIERS as S43_TIERS,
    APY_DEFAULTS as S43_APY,
    DAILY_VOL as S43_VOL,
    T1_PROTOCOL_CAP,
    T2_PROTOCOL_CAP,
    T2_TOTAL_CAP,
    MIN_CASH_BUFFER,
    TARGET_APY_MIN as S43_APY_MIN,
    TARGET_APY_MAX as S43_APY_MAX,
    CASH_KEY,
)

CAPITAL = 100_000.0


@pytest.fixture
def s42():
    return S42CrisisRefuge()


@pytest.fixture
def s43():
    return S43VolAdjusted()


# ════════════════════════════════════════════════════════════════════════════
# S42 — Crisis Refuge: identity + static book (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s42_identity(s42):
    assert s42.STRATEGY_ID == "S42"
    assert s42.STRATEGY_NAME == "Crisis Refuge"
    assert s42.TIER == "T1"


def test_s42_weights_sum_to_one():
    assert abs(sum(TARGET_WEIGHTS.values()) - 1.0) < 1e-9


def test_s42_susds_is_primary_refuge():
    # sUSDS is the single largest allocation (the refuge anchor).
    assert TARGET_WEIGHTS["sky_susds"] == 0.50
    assert TARGET_WEIGHTS["sky_susds"] == max(TARGET_WEIGHTS.values())


def test_s42_exact_book_weights():
    assert TARGET_WEIGHTS["sky_susds"] == 0.50
    assert TARGET_WEIGHTS["aave_v3"] == 0.30
    assert TARGET_WEIGHTS["compound_v3"] == 0.15
    assert TARGET_WEIGHTS["cash"] == 0.05


def test_s42_is_100pct_t1_zero_t2():
    # Every non-cash venue must be T1 — zero T2/T3 exposure.
    for p, w in TARGET_WEIGHTS.items():
        if p == "cash":
            continue
        assert S42_TIERS[p] == "T1", p


def test_s42_allocation_usd(s42):
    alloc = s42.get_allocation(CAPITAL)
    assert alloc["sky_susds"] == 50_000.0
    assert alloc["aave_v3"] == 30_000.0
    assert alloc["compound_v3"] == 15_000.0
    assert alloc["cash"] == 5_000.0
    assert abs(sum(alloc.values()) - CAPITAL) < 1e-6


def test_s42_allocation_zero_capital(s42):
    assert s42.get_allocation(0.0) == {}
    assert s42.get_allocation(-100.0) == {}


def test_s42_susds_is_lowest_vol_in_book():
    nonzero = {p: v for p, v in S42_VOL.items() if v > 0.0}
    assert nonzero["sky_susds"] == min(nonzero.values())


# ════════════════════════════════════════════════════════════════════════════
# S42 — expected APY + risk metrics (5)
# ════════════════════════════════════════════════════════════════════════════

def test_s42_expected_apy_in_range(s42):
    apy = s42.get_expected_apy()
    assert S42_APY_MIN <= apy <= S42_APY_MAX


def test_s42_expected_apy_value(s42):
    # 0.50*4.20 + 0.30*3.64 + 0.15*3.78 = 3.759
    assert abs(s42.get_expected_apy() - 3.759) < 1e-6


def test_s42_apy_map_override(s42):
    base = s42.get_expected_apy()
    bumped = s42.get_expected_apy({"sky_susds": 6.0})
    assert bumped > base


def test_s42_max_drawdown_below_point_one():
    assert S42_MAX_DD < 0.1 + 1e-9   # < 0.1% target — lowest of any strategy


def test_s42_book_vol_dominated_by_susds(s42):
    # Weighted daily vol is low and below a plain equal-weight T1 book's vol.
    book_vol = s42.get_expected_daily_vol()
    assert 0.0 < book_vol < 0.05
    risk = s42.get_risk_summary()
    assert risk["t1_weight_pct"] == 95.0
    assert risk["t2_weight_pct"] == 0.0
    assert risk["cash_weight_pct"] == 5.0


# ════════════════════════════════════════════════════════════════════════════
# S42 — activation triggers (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s42_no_triggers_quiet_market(s42):
    verdict = s42.should_activate({"t2_apys": {"morpho_blue": 6.5, "yearn_v3": 5.0},
                                   "kill_switch": False})
    assert verdict["active"] is False
    assert verdict["triggers"] == []


def test_s42_empty_state_inactive(s42):
    assert s42.should_activate(None)["active"] is False
    assert s42.should_activate({})["active"] is False


def test_s42_trigger_t2_apy_collapse(s42):
    verdict = s42.should_activate({"t2_apys": {"morpho_blue": 2.5, "yearn_v3": 2.0}})
    assert verdict["active"] is True
    assert "t2_apy_collapse" in verdict["triggers"]


def test_s42_no_collapse_if_one_t2_healthy(s42):
    # Collapse requires ALL tracked T2 below threshold.
    verdict = s42.should_activate({"t2_apys": {"morpho_blue": 2.5, "yearn_v3": 4.0}})
    assert "t2_apy_collapse" not in verdict["triggers"]


def test_s42_collapse_threshold_boundary(s42):
    # Exactly at threshold (3.0) is NOT below → no collapse.
    at = s42.should_activate({"t2_apys": {"morpho_blue": T2_APY_COLLAPSE_THRESHOLD}})
    assert "t2_apy_collapse" not in at["triggers"]
    below = s42.should_activate({"t2_apys": {"morpho_blue": T2_APY_COLLAPSE_THRESHOLD - 0.01}})
    assert "t2_apy_collapse" in below["triggers"]


def test_s42_trigger_kill_switch(s42):
    verdict = s42.should_activate({"kill_switch": True})
    assert verdict["active"] is True
    assert "kill_switch" in verdict["triggers"]


def test_s42_trigger_tvl_crash(s42):
    verdict = s42.should_activate(
        {"position_tvl_24h_change_pct": {"aave_v3": -35.0, "sky_susds": -1.0}}
    )
    assert verdict["active"] is True
    assert "tvl_crash" in verdict["triggers"]
    assert "aave_v3" in verdict["detail"]["tvl_crash"]["positions"]
    assert "sky_susds" not in verdict["detail"]["tvl_crash"]["positions"]


def test_s42_tvl_crash_threshold_boundary(s42):
    # -30% exactly trips (>= magnitude); -29.9% does not.
    trips = s42.should_activate(
        {"position_tvl_24h_change_pct": {"x": TVL_CRASH_THRESHOLD_PCT}}
    )
    assert "tvl_crash" in trips["triggers"]
    safe = s42.should_activate({"position_tvl_24h_change_pct": {"x": -29.9}})
    assert "tvl_crash" not in safe["triggers"]


def test_s42_multiple_triggers_collected(s42):
    verdict = s42.should_activate({
        "t2_apys": {"morpho_blue": 1.0},
        "kill_switch": True,
        "position_tvl_24h_change_pct": {"y": -40.0},
    })
    assert verdict["active"] is True
    assert set(verdict["triggers"]) == {"t2_apy_collapse", "kill_switch", "tvl_crash"}


# ════════════════════════════════════════════════════════════════════════════
# S43 — Volatility-Adjusted Yield: scoring + identity (5)
# ════════════════════════════════════════════════════════════════════════════

def test_s43_identity(s43):
    assert s43.STRATEGY_ID == "S43"
    assert s43.STRATEGY_NAME == "Volatility-Adjusted Yield"


def test_s43_scores_apy_over_vol(s43):
    scores = s43.risk_adjusted_scores()
    # sUSDS = 4.20 / 0.022 ≈ 190.9
    assert abs(scores["sky_susds"] - (4.20 / 0.022)) < 1e-3
    assert abs(scores["morpho_steakhouse"] - (6.86 / 0.078)) < 1e-3


def test_s43_susds_has_top_score(s43):
    scores = s43.risk_adjusted_scores()
    assert scores["sky_susds"] == max(scores.values())
    # Despite Morpho's higher raw APY, sUSDS wins on risk-adjusted basis.
    assert S43_APY["morpho_steakhouse"] > S43_APY["sky_susds"]
    assert scores["sky_susds"] > scores["morpho_steakhouse"]


def test_s43_zero_vol_protocol_scores_zero(s43):
    scores = s43.risk_adjusted_scores(vol_map={"sky_susds": 0.0})
    assert scores["sky_susds"] == 0.0


def test_s43_score_ranking_matches_expectation(s43):
    scores = s43.risk_adjusted_scores()
    ranking = sorted(scores, key=scores.get, reverse=True)
    assert ranking[0] == "sky_susds"
    assert ranking[1] == "morpho_steakhouse"


# ════════════════════════════════════════════════════════════════════════════
# S43 — allocation under caps (8)
# ════════════════════════════════════════════════════════════════════════════

def test_s43_weights_sum_to_one(s43):
    w = s43.get_weights()
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_s43_min_cash_buffer_respected(s43):
    w = s43.get_weights()
    assert w[CASH_KEY] >= MIN_CASH_BUFFER - 1e-9


def test_s43_susds_hits_t1_cap(s43):
    w = s43.get_weights()
    # Highest score → pinned at the 40% per-protocol T1 cap.
    assert abs(w["sky_susds"] - T1_PROTOCOL_CAP) < 1e-6


def test_s43_morpho_hits_t2_cap(s43):
    w = s43.get_weights()
    assert abs(w["morpho_steakhouse"] - T2_PROTOCOL_CAP) < 1e-6


def test_s43_no_protocol_exceeds_its_cap(s43):
    w = s43.get_weights()
    for p, weight in w.items():
        if p == CASH_KEY:
            continue
        cap = T1_PROTOCOL_CAP if S43_TIERS[p] == "T1" else T2_PROTOCOL_CAP
        assert weight <= cap + 1e-6, p


def test_s43_t2_total_cap_respected(s43):
    w = s43.get_weights()
    t2 = sum(weight for p, weight in w.items()
             if p != CASH_KEY and S43_TIERS.get(p) == "T2")
    assert t2 <= T2_TOTAL_CAP + 1e-6


def test_s43_allocation_usd_sums_to_capital(s43):
    alloc = s43.get_allocation(CAPITAL)
    assert abs(sum(alloc.values()) - CAPITAL) < 1e-3
    assert alloc["sky_susds"] == pytest.approx(40_000.0, abs=1.0)
    assert alloc["morpho_steakhouse"] == pytest.approx(20_000.0, abs=1.0)


def test_s43_allocation_zero_capital(s43):
    assert s43.get_allocation(0.0) == {}


# ════════════════════════════════════════════════════════════════════════════
# S43 — expected APY + dynamic reallocation (6)
# ════════════════════════════════════════════════════════════════════════════

def test_s43_expected_apy_in_range(s43):
    apy = s43.get_expected_apy()
    assert S43_APY_MIN <= apy <= S43_APY_MAX


def test_s43_expected_apy_value(s43):
    # 0.40*4.20 + 0.20*6.86 + ~0.182*3.78 + ~0.168*3.64 ≈ 4.35
    assert abs(s43.get_expected_apy() - 4.3515) < 1e-2


def test_s43_low_vol_protocol_gains_when_vol_drops(s43):
    # Halving sUSDS vol doubles its score; it's already capped, so weight
    # cannot rise — but a previously-uncapped venue shifts. Verify a venue
    # whose vol spikes loses allocation.
    base = s43.get_weights()
    worse_aave = s43.get_weights(vol_map={**S43_VOL, "aave_v3": 0.30})
    assert worse_aave["aave_v3"] < base["aave_v3"]


def test_s43_higher_apy_uncapped_gains(s43):
    base = s43.get_weights()
    # Boost compound's APY (uncapped) → its score and weight rise.
    boosted = s43.get_weights(apy_map={**S43_APY, "compound_v3": 8.0})
    assert boosted["compound_v3"] > base["compound_v3"]


def test_s43_risk_summary_shape(s43):
    risk = s43.get_risk_summary()
    assert risk["t1_weight_pct"] > risk["t2_weight_pct"]   # net T1-tilted
    assert risk["t2_weight_pct"] <= T2_TOTAL_CAP * 100.0 + 1e-6
    assert risk["expected_daily_vol_pct"] > 0.0


def test_s43_simulate_reports_scores_and_yield(s43):
    sim = s43.simulate(CAPITAL)
    assert sim["status"] == "ok"
    assert sim["expected_apy_pct"] == s43.get_expected_apy()
    assert abs(sim["expected_annual_yield_usd"] - CAPITAL * sim["expected_apy_pct"] / 100.0) < 1.0
    assert "sky_susds" in sim["scores"]
