"""
tests/test_pendle_pt_adapters.py — MP-1250

40 tests for the Pendle PT (Principal Token) fixed-rate adapters and the S40
strategy:

  * PendlePTSusdeAdapter  (spa_core/adapters/pendle_pt_susde_adapter.py)
  * PendlePTUsdcAdapter   (spa_core/adapters/pendle_pt_usdc_adapter.py)
  * PendlePTFixedRateStrategy (spa_core/strategies/s40_pendle_pt_fixed.py)

All tests are offline: a FakeFeed is injected so no DeFiLlama network call is
made, and a fixed `today` reference date makes the maturity logic deterministic.
"""
import datetime

import pytest

from spa_core.adapters.pendle_pt_susde_adapter import PendlePTSusdeAdapter
from spa_core.adapters.pendle_pt_usdc_adapter import PendlePTUsdcAdapter

TODAY = datetime.date(2026, 6, 21)


class FakeFeed:
    """Minimal DeFiLlama feed stub. Returns a pool dict for any Pendle symbol,
    or None to simulate the feed being unavailable / no match."""

    def __init__(self, apy_pct=None, tvl_usd=None):
        self.apy_pct = apy_pct
        self.tvl_usd = tvl_usd

    def get_pool(self, project, symbol, chain="Ethereum"):
        if project != "pendle":
            return None
        if self.apy_pct is None:
            return None
        return {"apy": self.apy_pct, "tvlUsd": self.tvl_usd}


def susde(apy=None, tvl=None, maturity=None, today=TODAY):
    return PendlePTSusdeAdapter(
        feed=FakeFeed(apy, tvl), maturity_date=maturity, today=today
    )


def usdc(apy=None, tvl=None, maturity=None, today=TODAY):
    return PendlePTUsdcAdapter(
        feed=FakeFeed(apy, tvl), maturity_date=maturity, today=today
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1–8: sUSDe adapter — identity & tier
# ─────────────────────────────────────────────────────────────────────────────

def test_susde_protocol_id():
    assert susde().PROTOCOL == "pendle_pt_susde"


def test_susde_tier_is_t2():
    assert susde().TIER == "T2"
    assert susde().tier == "T2"


def test_susde_asset_is_susde():
    assert susde().ASSET == "sUSDe"


def test_susde_chain_ethereum():
    a = susde()
    assert a.CHAIN == "ethereum" and a.CHAIN_ID == 1


def test_susde_research_only_flag():
    assert susde().RESEARCH_ONLY is True


def test_susde_min_tvl_floor_is_50m():
    assert susde().MIN_TVL_USD == 50_000_000.0


def test_susde_rotation_floor_is_5pct():
    assert susde().ROTATION_APY_FLOOR == 0.05


def test_susde_unwind_window_is_30d():
    assert susde().MATURITY_UNWIND_DAYS == 30


# ─────────────────────────────────────────────────────────────────────────────
# 9–18: sUSDe adapter — APY, TVL, maturity, kill switch
# ─────────────────────────────────────────────────────────────────────────────

def test_susde_fallback_apy_when_feed_unavailable():
    a = susde(apy=None)
    assert a.fetch_apy() == pytest.approx(0.10)


def test_susde_live_apy_decimal_conversion():
    # DeFiLlama returns percent (10.5) → adapter exposes decimal 0.105.
    a = susde(apy=10.5, tvl=120e6)
    assert a.fetch_apy() == pytest.approx(0.105)


def test_susde_get_apy_normal_is_safe_apy():
    a = susde(apy=9.0, tvl=120e6)
    assert a.get_apy() == pytest.approx(0.09)


def test_susde_apy_clamped_to_max():
    a = susde(apy=45.0, tvl=120e6)  # 45% > MAX 30%
    assert a.safe_apy() == pytest.approx(0.30)


def test_susde_tvl_ok_above_floor():
    assert susde(apy=10.0, tvl=80e6).tvl_ok() is True


def test_susde_tvl_not_ok_below_floor():
    assert susde(apy=10.0, tvl=20e6).tvl_ok() is False


def test_susde_maturity_far_not_unwinding():
    a = susde(apy=10.0, tvl=120e6, maturity="2026-12-31")
    assert a.is_unwinding() is False
    assert a.get_apy() == pytest.approx(0.10)


def test_susde_maturity_near_reports_zero_apy():
    # 2026-07-01 is 10 days from TODAY (< 30) → unwinding → effective 0%.
    a = susde(apy=10.0, tvl=120e6, maturity="2026-07-01")
    assert a.is_unwinding() is True
    assert a.get_apy() == 0.0


def test_susde_days_to_maturity_none_without_date():
    assert susde().days_to_maturity() is None


def test_susde_days_to_maturity_computed():
    a = susde(maturity="2026-07-21")  # 30 days after TODAY
    assert a.days_to_maturity() == 30


# ─────────────────────────────────────────────────────────────────────────────
# 19–24: sUSDe adapter — rotation / eligibility / output
# ─────────────────────────────────────────────────────────────────────────────

def test_susde_kill_switch_below_morpho_floor():
    a = susde(apy=4.0, tvl=120e6)  # 4% < 5% floor
    assert a.should_rotate() is True


def test_susde_no_rotation_when_healthy():
    a = susde(apy=10.0, tvl=120e6, maturity="2026-12-31")
    assert a.should_rotate() is False


def test_susde_rotation_when_unwinding():
    a = susde(apy=10.0, tvl=120e6, maturity="2026-06-25")  # 4 days
    assert a.should_rotate() is True


def test_susde_eligible_when_healthy():
    a = susde(apy=10.0, tvl=120e6, maturity="2026-12-31")
    assert a.is_eligible() is True


def test_susde_not_eligible_below_tvl():
    a = susde(apy=10.0, tvl=10e6, maturity="2026-12-31")
    assert a.is_eligible() is False


def test_susde_yield_info_and_to_dict():
    a = susde(apy=10.0, tvl=120e6, maturity="2026-12-31")
    yi = a.get_yield_info()
    assert yi.tier == "T2" and yi.apy == pytest.approx(0.10)
    d = a.to_dict()
    assert d["protocol"] == "pendle_pt_susde"
    assert d["tvl_ok"] is True
    assert d["effective_apy_pct"] == pytest.approx(10.0)


# ─────────────────────────────────────────────────────────────────────────────
# 25–34: USDC adapter
# ─────────────────────────────────────────────────────────────────────────────

def test_usdc_protocol_id():
    assert usdc().PROTOCOL == "pendle_pt_usdc"


def test_usdc_tier_is_t2():
    assert usdc().TIER == "T2"


def test_usdc_asset_is_usdc():
    assert usdc().ASSET == "USDC"


def test_usdc_fallback_apy_is_8pct():
    assert usdc(apy=None).fetch_apy() == pytest.approx(0.08)


def test_usdc_live_apy_decimal_conversion():
    a = usdc(apy=7.5, tvl=90e6)
    assert a.get_apy() == pytest.approx(0.075)


def test_usdc_tvl_floor_50m():
    assert usdc(apy=8.0, tvl=40e6).tvl_ok() is False
    assert usdc(apy=8.0, tvl=60e6).tvl_ok() is True


def test_usdc_maturity_near_zero_apy():
    a = usdc(apy=8.0, tvl=90e6, maturity="2026-06-30")  # 9 days
    assert a.get_apy() == 0.0


def test_usdc_kill_switch_below_floor():
    assert usdc(apy=3.0, tvl=90e6).should_rotate() is True


def test_usdc_eligible_when_healthy():
    assert usdc(apy=8.0, tvl=90e6, maturity="2027-01-01").is_eligible() is True


def test_usdc_to_dict_keys():
    d = usdc(apy=8.0, tvl=90e6).to_dict()
    for key in ("protocol", "tier", "tvl_ok", "effective_apy_pct",
                "should_rotate", "days_to_maturity"):
        assert key in d


# ─────────────────────────────────────────────────────────────────────────────
# 35–36: registry wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_adapters_registered_in_registry():
    from spa_core.adapters import ADAPTER_REGISTRY
    keys = {row[0] for row in ADAPTER_REGISTRY}
    assert "pendle_pt_susde" in keys
    assert "pendle_pt_usdc" in keys


def test_registry_marks_pendle_pt_as_t2():
    from spa_core.adapters import ADAPTER_REGISTRY
    tiers = {row[0]: row[1] for row in ADAPTER_REGISTRY}
    assert tiers["pendle_pt_susde"] == "T2"
    assert tiers["pendle_pt_usdc"] == "T2"


# ─────────────────────────────────────────────────────────────────────────────
# 37–44: S40 strategy
# ─────────────────────────────────────────────────────────────────────────────

def _s40():
    from spa_core.strategies.s40_pendle_pt_fixed import PendlePTFixedRateStrategy
    return PendlePTFixedRateStrategy()


def test_s40_identity():
    s = _s40()
    assert s.STRATEGY_ID == "S40"
    assert s.TIER == "T2"


def test_s40_allocation_weights_sum_to_capital():
    s = _s40()
    alloc = s.get_allocation(100_000.0)
    assert sum(alloc.values()) == pytest.approx(100_000.0)


def test_s40_allocation_has_all_legs():
    s = _s40()
    alloc = s.get_allocation(100_000.0)
    for k in ("pendle_pt_susde", "pendle_pt_usdc", "aave_v3", "compound_v3", "cash"):
        assert k in alloc


def test_s40_pt_weights_correct():
    s = _s40()
    alloc = s.get_allocation(100_000.0)
    assert alloc["pendle_pt_susde"] == pytest.approx(20_000.0)
    assert alloc["pendle_pt_usdc"] == pytest.approx(15_000.0)
    assert alloc["cash"] == pytest.approx(5_000.0)


def test_s40_expected_apy_in_target_band():
    s = _s40()
    apy = s.get_expected_apy()
    assert 4.0 <= apy <= 7.0  # documented ~5.1%, allow live-feed drift


def test_s40_t2_within_cap():
    s = _s40()
    rs = s.get_risk_summary()
    assert rs["t2_weight_pct"] == pytest.approx(35.0)
    assert rs["t2_weight_pct"] <= 50.0  # ADR-019 T2 cap


def test_s40_rotation_folds_pt_into_aave():
    # Force both PT legs to rotate by giving them near-maturity adapters.
    s = _s40()
    s._adapters["pendle_pt_susde"] = susde(apy=10.0, tvl=120e6, maturity="2026-06-25")
    s._adapters["pendle_pt_usdc"] = usdc(apy=8.0, tvl=90e6, maturity="2026-06-25")
    rotations = s.pending_rotations()
    assert "pendle_pt_susde" in rotations and "pendle_pt_usdc" in rotations
    alloc = s.get_allocation(100_000.0)
    # PT weights (20% + 15%) folded into aave (35%) → aave = 70%.
    assert alloc["aave_v3"] == pytest.approx(70_000.0)
    assert "pendle_pt_susde" not in alloc
    assert sum(alloc.values()) == pytest.approx(100_000.0)


def test_s40_simulate_and_to_dict():
    s = _s40()
    sim = s.simulate(100_000.0)
    assert sim["status"] == "ok"
    assert sim["expected_annual_yield_usd"] > 0
    d = s.to_dict()
    assert d["strategy_id"] == "S40"
    assert d["rotation_target"] == "aave_v3"
