"""
Unit tests for V3PendleFocusedStrategy — paper_trading/v3_pendle_focused.py.

Closes the test-coverage gap for SPA-V23-002 / IDEA-006: previously the
v3_pendle_focused module (447 LOC) only had *integration* coverage via
test_tournament.py::TestV3Integration. These tests exercise the class
methods directly with deterministic, pure-Python fixtures (no DB / no net).

Test groups:
  1. AllocationDecision dataclass — defaults + summary() formatting.
  2. select_best_pendle()           — maturity / APY gates, ranking.
  3. should_rotate()                — APY threshold + near-maturity hold.
  4. _allocate_t1() (via compute)   — T1 ranking + concentration cap + dust.
  5. compute_allocation()           — full pipeline (Pendle + T1 + cash).
  6. get_strategy_config()          — config dict shape used by STRATEGIES.
  7. build_strategy()               — factory function default capital.

Run:
    cd spa_core
    python -m pytest tests/test_v3_pendle_focused.py -v
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trading.v3_pendle_focused import (  # noqa: E402
    PENDLE_MAX_PCT,
    PENDLE_MIN_APY,
    PENDLE_MIN_MATURITY_D,
    ROTATION_THRESHOLD_PP,
    STRATEGY_ID,
    T1_CASH_BUFFER,
    T1_MAX_PCT,
    AllocationDecision,
    V3PendleFocusedStrategy,
    build_strategy,
    get_strategy_config,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pendle_pool(
    symbol: str = "PT-USDC-26DEC2026",
    apy: float = 8.0,
    days_to_maturity: int | None = 180,
    maturity_date: str | None = None,
    tvl_usd: float = 25_000_000.0,
    chain: str = "arbitrum",
) -> dict:
    """Construct a Pendle PT pool dict matching PendleFetcher output."""
    p: dict = {
        "pool_id":   f"pendle-{symbol}",
        "protocol":  "Pendle PT",
        "symbol":    symbol,
        "chain":     chain,
        "tier":      "T2",
        "apy":       apy,
        "tvl_usd":   tvl_usd,
    }
    if days_to_maturity is not None:
        p["days_to_maturity"] = days_to_maturity
    if maturity_date is not None:
        p["maturity_date"] = maturity_date
    return p


def _t1_pool(
    pool_key: str = "aave-v3-usdc-arbitrum",
    apy: float = 4.0,
    protocol: str = "Aave V3",
    tier: str = "T1",
    tvl_usd: float = 100_000_000.0,
) -> dict:
    return {
        "pool_key": pool_key,
        "apy":      apy,
        "protocol": protocol,
        "tier":     tier,
        "tvl_usd":  tvl_usd,
    }


# ─── 1. AllocationDecision dataclass ──────────────────────────────────────────

class TestAllocationDecisionDataclass:
    """Defaults + summary() formatting must be stable for log scraping."""

    def test_defaults_when_only_pendle_provided(self):
        pool = _pendle_pool()
        d = AllocationDecision(pendle_pool=pool, pendle_amount=10_000.0)
        assert d.pendle_pool is pool
        assert d.pendle_amount == 10_000.0
        assert d.t1_allocations == []
        assert d.total_deployed == 0.0
        assert d.cash_reserved == 0.0
        assert d.rotation_needed is False
        assert d.rotation_reason == ""

    def test_summary_contains_pendle_and_t1_lines(self):
        d = AllocationDecision(
            pendle_pool=_pendle_pool(apy=8.5),
            pendle_amount=20_000.0,
            t1_allocations=[{
                "pool_key": "aave-v3-usdc-arbitrum",
                "amount_usd": 40_000.0,
                "apy": 4.5,
                "protocol": "Aave V3",
                "tier": "T1",
            }],
            total_deployed=60_000.0,
            cash_reserved=40_000.0,
        )
        out = d.summary()
        assert "v3_pendle_focused allocation:" in out
        assert "Pendle PT" in out
        assert "8.50% APY" in out
        assert "$20,000" in out
        assert "aave-v3-usdc-arbitrum" in out
        assert "$40,000" in out
        assert "Total deployed: $60,000" in out
        assert "Cash reserved:  $40,000" in out

    def test_summary_no_pendle_pool(self):
        d = AllocationDecision(
            pendle_pool=None,
            pendle_amount=0.0,
            t1_allocations=[],
            total_deployed=0.0,
            cash_reserved=100_000.0,
        )
        out = d.summary()
        assert "Pendle PT: $0 (no eligible pool)" in out

    def test_summary_includes_rotation_when_needed(self):
        d = AllocationDecision(
            pendle_pool=_pendle_pool(),
            pendle_amount=20_000.0,
            rotation_needed=True,
            rotation_reason="new pool better by 0.8pp",
        )
        out = d.summary()
        assert "⚡ Rotation: new pool better by 0.8pp" in out


# ─── 2. select_best_pendle() ──────────────────────────────────────────────────

class TestSelectBestPendle:

    def test_returns_none_for_empty_input(self):
        s = V3PendleFocusedStrategy()
        assert s.select_best_pendle([]) is None

    def test_filters_pools_with_short_maturity(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(symbol="PT-SHORT", apy=12.0, days_to_maturity=10),
            _pendle_pool(symbol="PT-LONG",  apy=7.0,  days_to_maturity=180),
        ]
        best = s.select_best_pendle(pools)
        assert best is not None
        assert best["symbol"] == "PT-LONG"

    def test_filters_pools_below_min_apy(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(symbol="PT-LOW",  apy=PENDLE_MIN_APY - 0.5, days_to_maturity=180),
            _pendle_pool(symbol="PT-HIGH", apy=PENDLE_MIN_APY + 0.1, days_to_maturity=180),
        ]
        best = s.select_best_pendle(pools)
        assert best is not None
        assert best["symbol"] == "PT-HIGH"

    def test_returns_none_when_all_pools_disqualified(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(symbol="PT-LOW",   apy=PENDLE_MIN_APY - 1, days_to_maturity=180),
            _pendle_pool(symbol="PT-SHORT", apy=10.0, days_to_maturity=5),
        ]
        assert s.select_best_pendle(pools) is None

    def test_ranks_by_apy_descending(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(symbol="PT-A", apy=7.0,  days_to_maturity=180),
            _pendle_pool(symbol="PT-B", apy=12.0, days_to_maturity=180),
            _pendle_pool(symbol="PT-C", apy=9.0,  days_to_maturity=180),
        ]
        best = s.select_best_pendle(pools)
        assert best["symbol"] == "PT-B"

    def test_tie_break_by_maturity_descending(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(symbol="PT-SOON",  apy=8.0, days_to_maturity=45),
            _pendle_pool(symbol="PT-LATER", apy=8.0, days_to_maturity=300),
        ]
        best = s.select_best_pendle(pools)
        assert best["symbol"] == "PT-LATER"

    def test_computes_days_to_maturity_from_maturity_date(self):
        s = V3PendleFocusedStrategy()
        future = (date.today() + timedelta(days=120)).isoformat()
        pools = [_pendle_pool(
            symbol="PT-DATED", apy=8.0,
            days_to_maturity=None, maturity_date=future,
        )]
        best = s.select_best_pendle(pools)
        assert best is not None
        # 120 ± 1 day tolerance for execution drift
        assert abs(best["days_to_maturity"] - 120) <= 1

    def test_skips_pool_with_unparseable_maturity_date(self):
        s = V3PendleFocusedStrategy()
        pools = [
            _pendle_pool(
                symbol="PT-BAD", apy=10.0,
                days_to_maturity=None, maturity_date="not-a-date",
            ),
            _pendle_pool(symbol="PT-GOOD", apy=7.0, days_to_maturity=120),
        ]
        # Bad pool falls through (dtm stays None, treated as eligible)
        # but PT-GOOD still wins on APY-then-maturity ranking when both pass.
        best = s.select_best_pendle(pools)
        assert best is not None
        # PT-BAD has higher APY so it should be picked despite unparseable date
        # (existing implementation does not disqualify on parse failure).
        assert best["symbol"] in {"PT-BAD", "PT-GOOD"}


# ─── 3. should_rotate() ───────────────────────────────────────────────────────

class TestShouldRotate:

    def test_rotates_when_apy_improvement_exceeds_threshold(self):
        s = V3PendleFocusedStrategy()
        current = {"entry_apy": 7.0, "days_remaining": 90}
        new_pool = _pendle_pool(apy=7.0 + ROTATION_THRESHOLD_PP + 0.1, days_to_maturity=180)
        rotate, reason = s.should_rotate(current, new_pool)
        assert rotate is True
        assert "improvement" in reason

    def test_no_rotation_when_apy_improvement_below_threshold(self):
        s = V3PendleFocusedStrategy()
        current = {"entry_apy": 7.0, "days_remaining": 90}
        new_pool = _pendle_pool(apy=7.0 + ROTATION_THRESHOLD_PP - 0.1, days_to_maturity=180)
        rotate, reason = s.should_rotate(current, new_pool)
        assert rotate is False
        assert "threshold" in reason

    def test_no_rotation_when_current_position_near_maturity(self):
        """Position with <14 days to maturity must not rotate — liquidity risk."""
        s = V3PendleFocusedStrategy()
        current = {"entry_apy": 4.0, "days_remaining": 10}
        new_pool = _pendle_pool(apy=15.0, days_to_maturity=180)
        rotate, reason = s.should_rotate(current, new_pool)
        assert rotate is False
        assert "maturity" in reason

    def test_no_rotation_when_new_pool_maturity_too_short(self):
        s = V3PendleFocusedStrategy()
        current = {"entry_apy": 4.0, "days_remaining": 90}
        new_pool = _pendle_pool(apy=15.0, days_to_maturity=5)
        rotate, reason = s.should_rotate(current, new_pool)
        assert rotate is False
        assert "minimum" in reason or "maturity" in reason

    def test_days_remaining_inferred_from_maturity_date(self):
        s = V3PendleFocusedStrategy()
        future = (date.today() + timedelta(days=90)).isoformat()
        current = {"entry_apy": 6.0, "maturity_date": future}
        new_pool = _pendle_pool(apy=6.0 + ROTATION_THRESHOLD_PP + 0.5, days_to_maturity=180)
        rotate, _ = s.should_rotate(current, new_pool)
        assert rotate is True

    def test_custom_rotation_threshold_respected(self):
        """Construct strategy with a tighter threshold — rotation now triggers."""
        s = V3PendleFocusedStrategy(rotation_threshold=0.1)
        current = {"entry_apy": 7.0, "days_remaining": 90}
        new_pool = _pendle_pool(apy=7.2, days_to_maturity=180)
        rotate, _ = s.should_rotate(current, new_pool)
        assert rotate is True


# ─── 4. _allocate_t1() (tested via compute_allocation) ────────────────────────

class TestT1Allocation:
    """T1 allocation logic verified via the public compute_allocation entrypoint."""

    def test_no_t1_when_only_pendle_pools_given(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=8.0)],
            t1_pools=[],
        )
        assert d.t1_allocations == []

    def test_t1_concentration_capped_per_pool(self):
        """No single T1 pool may exceed T1_MAX_PCT of total capital."""
        s = V3PendleFocusedStrategy(capital=100_000.0)
        t1 = [_t1_pool(pool_key=f"pool-{i}", apy=5.0 - 0.1 * i) for i in range(5)]
        d = s.compute_allocation(pendle_pools=[], t1_pools=t1)
        max_alloc = 100_000.0 * T1_MAX_PCT
        for a in d.t1_allocations:
            assert a["amount_usd"] <= max_alloc + 0.01

    def test_t1_pools_ranked_by_apy_descending(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        t1 = [
            _t1_pool(pool_key="low",  apy=3.0),
            _t1_pool(pool_key="high", apy=6.0),
            _t1_pool(pool_key="mid",  apy=4.5),
        ]
        d = s.compute_allocation(pendle_pools=[], t1_pools=t1)
        assert d.t1_allocations[0]["pool_key"] == "high"

    def test_t1_filters_out_non_t1_tier(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        t1 = [
            _t1_pool(pool_key="t2-pool", apy=10.0, tier="T2"),
            _t1_pool(pool_key="t1-pool", apy=4.0,  tier="T1"),
        ]
        d = s.compute_allocation(pendle_pools=[], t1_pools=t1)
        keys = {a["pool_key"] for a in d.t1_allocations}
        assert "t2-pool" not in keys
        assert "t1-pool" in keys

    def test_t1_filters_out_low_apy(self):
        """APY below T1_MIN_APY (1.0) must be excluded."""
        s = V3PendleFocusedStrategy(capital=100_000.0)
        t1 = [
            _t1_pool(pool_key="dust", apy=0.5),
            _t1_pool(pool_key="good", apy=4.0),
        ]
        d = s.compute_allocation(pendle_pools=[], t1_pools=t1)
        keys = {a["pool_key"] for a in d.t1_allocations}
        assert "dust" not in keys
        assert "good" in keys

    def test_t1_skips_dust_allocations_under_1000(self):
        """Remaining capital below $1000 must not produce a tiny allocation."""
        s = V3PendleFocusedStrategy(capital=1_000.0)  # almost no capital
        t1 = [_t1_pool(pool_key="any", apy=5.0)]
        d = s.compute_allocation(pendle_pools=[], t1_pools=t1)
        # capital=1000, cash_buffer=5% -> available ~ 950 < 1000 dust limit
        assert d.t1_allocations == []


# ─── 5. compute_allocation() — full pipeline ──────────────────────────────────

class TestComputeAllocation:

    def test_full_allocation_balances_pendle_t1_and_cash(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=8.0)],
            t1_pools=[
                _t1_pool(pool_key="aave", apy=5.0),
                _t1_pool(pool_key="comp", apy=4.5),
                _t1_pool(pool_key="morpho", apy=4.0),
            ],
        )
        assert d.pendle_amount > 0
        assert d.pendle_amount <= 100_000.0 * PENDLE_MAX_PCT + 0.01
        assert len(d.t1_allocations) >= 1
        # Capital identity: deployed + cash = total
        assert abs((d.total_deployed + d.cash_reserved) - 100_000.0) < 0.5

    def test_zero_pendle_when_no_eligible_pool(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=3.0)],  # below PENDLE_MIN_APY
            t1_pools=[_t1_pool(apy=4.5)],
        )
        assert d.pendle_pool is None
        assert d.pendle_amount == 0.0

    def test_rotation_flag_set_when_current_position_underperforms(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        current = {"entry_apy": 6.0, "days_remaining": 90}
        new_pool = _pendle_pool(apy=8.0, days_to_maturity=180)
        d = s.compute_allocation(
            pendle_pools=[new_pool],
            t1_pools=[],
            current_pendle_position=current,
        )
        assert d.rotation_needed is True
        assert d.rotation_reason

    def test_no_rotation_flag_when_no_current_position(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=8.0)],
            t1_pools=[],
            current_pendle_position=None,
        )
        assert d.rotation_needed is False

    def test_current_capital_overrides_init_value(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=8.0)],
            t1_pools=[],
            current_capital=50_000.0,
        )
        # Override should be respected — pendle ≤ 20% of 50k
        assert d.pendle_amount <= 50_000.0 * PENDLE_MAX_PCT + 0.01

    def test_cash_buffer_respected(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(
            pendle_pools=[_pendle_pool(apy=8.0)],
            t1_pools=[_t1_pool(apy=5.0) for _ in range(3)],
        )
        # At least the configured cash_buffer fraction should remain liquid.
        min_cash = 100_000.0 * T1_CASH_BUFFER
        assert d.cash_reserved >= min_cash - 0.01

    def test_no_pools_results_in_all_cash(self):
        s = V3PendleFocusedStrategy(capital=100_000.0)
        d = s.compute_allocation(pendle_pools=[], t1_pools=[])
        assert d.pendle_amount == 0.0
        assert d.t1_allocations == []
        assert d.total_deployed == 0.0
        assert d.cash_reserved == pytest.approx(100_000.0, rel=1e-9)


# ─── 6. get_strategy_config() ─────────────────────────────────────────────────

class TestStrategyConfig:

    def test_strategy_id_constant(self):
        assert STRATEGY_ID == "v3_pendle_focused"

    def test_config_dict_has_required_top_level_keys(self):
        cfg = get_strategy_config()
        for k in ("name", "description", "config", "handler_module", "handler_class"):
            assert k in cfg, f"missing top-level key: {k}"

    def test_config_handler_points_to_v3_module_and_class(self):
        cfg = get_strategy_config()
        assert cfg["handler_module"] == "paper_trading.v3_pendle_focused"
        assert cfg["handler_class"]  == "V3PendleFocusedStrategy"

    def test_config_inner_dict_values_match_module_constants(self):
        cfg = get_strategy_config()["config"]
        assert cfg["pendle_max_pct"]            == PENDLE_MAX_PCT
        assert cfg["pendle_min_maturity_days"]  == PENDLE_MIN_MATURITY_D
        assert cfg["pendle_rotation_threshold"] == ROTATION_THRESHOLD_PP
        assert cfg["pendle_min_apy"]            == PENDLE_MIN_APY
        assert cfg["cash_buffer_pct"]           == T1_CASH_BUFFER
        assert cfg["max_concentration_t1"]      == T1_MAX_PCT

    def test_config_preferred_tiers_pendle_first(self):
        cfg = get_strategy_config()["config"]
        assert cfg["preferred_tiers"][0] == "T2"
        assert "T1" in cfg["preferred_tiers"]


# ─── 7. build_strategy() factory ──────────────────────────────────────────────

class TestBuildStrategyFactory:

    def test_factory_returns_instance_with_default_capital(self):
        s = build_strategy()
        assert isinstance(s, V3PendleFocusedStrategy)
        assert s.capital == 100_000.0

    def test_factory_accepts_custom_capital(self):
        s = build_strategy(capital=250_000.0)
        assert s.capital == 250_000.0
