"""Tests for spa_core.paper_trading.withdrawal_planner (MP-577).

90+ unit tests covering:
  - WithdrawalStep dataclass
  - plan_withdrawal (all 3 strategies + edge cases)
  - estimate_slippage
  - get_withdrawal_sequence
  - record_withdrawal (atomic writes, ring-buffer)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from spa_core.paper_trading.withdrawal_planner import (
    HISTORY_MAX,
    STRATEGY_MAX_YIELD,
    STRATEGY_MIN_IMPACT,
    STRATEGY_PRO_RATA,
    WithdrawalPlanner,
    WithdrawalStep,
)


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def planner():
    return WithdrawalPlanner()


@pytest.fixture
def portfolio():
    return {
        "aave_v3":           40_000.0,
        "compound_v3":       30_000.0,
        "morpho_steakhouse": 15_000.0,
        "yearn_v3":          10_000.0,
    }


@pytest.fixture
def adapters():
    return {
        "aave_v3":           {"apy": 3.5, "tvl": 9_000_000_000.0, "tier": "T1"},
        "compound_v3":       {"apy": 4.8, "tvl": 2_000_000_000.0, "tier": "T1"},
        "morpho_steakhouse": {"apy": 6.5, "tvl":   800_000_000.0, "tier": "T1"},
        "yearn_v3":          {"apy": 5.2, "tvl":   300_000_000.0, "tier": "T2"},
    }


@pytest.fixture
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — WithdrawalStep dataclass (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWithdrawalStep:
    def test_fields_stored(self):
        step = WithdrawalStep(adapter_id="aave_v3", amount_usd=5000.0,
                              pct_of_position=0.125, order=1)
        assert step.adapter_id == "aave_v3"
        assert step.amount_usd == 5000.0
        assert step.pct_of_position == 0.125
        assert step.order == 1

    def test_default_slippage_zero(self):
        step = WithdrawalStep(adapter_id="x", amount_usd=100.0,
                              pct_of_position=0.1, order=1)
        assert step.estimated_slippage == 0.0

    def test_explicit_slippage(self):
        step = WithdrawalStep(adapter_id="x", amount_usd=100.0,
                              pct_of_position=0.1, order=1,
                              estimated_slippage=0.003)
        assert step.estimated_slippage == 0.003

    def test_to_dict_keys(self):
        step = WithdrawalStep(adapter_id="y", amount_usd=200.0,
                              pct_of_position=0.5, order=2)
        d = step.to_dict()
        assert set(d.keys()) == {
            "adapter_id", "amount_usd", "pct_of_position",
            "order", "estimated_slippage",
        }

    def test_to_dict_values(self):
        step = WithdrawalStep(adapter_id="z", amount_usd=1234.5,
                              pct_of_position=0.333, order=3,
                              estimated_slippage=0.01)
        d = step.to_dict()
        assert d["adapter_id"]         == "z"
        assert d["amount_usd"]         == 1234.5
        assert d["pct_of_position"]    == 0.333
        assert d["order"]              == 3
        assert d["estimated_slippage"] == 0.01

    def test_to_dict_is_serialisable(self):
        step = WithdrawalStep(adapter_id="a", amount_usd=999.0,
                              pct_of_position=1.0, order=1)
        j = json.dumps(step.to_dict())
        assert isinstance(j, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — plan_withdrawal basics (11 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanWithdrawalBasics:
    def test_empty_portfolio_returns_empty(self, planner):
        steps = planner.plan_withdrawal(5000.0, {}, {})
        assert steps == []

    def test_zero_amount_returns_empty(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(0.0, portfolio, adapters)
        assert steps == []

    def test_negative_amount_returns_empty(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(-100.0, portfolio, adapters)
        assert steps == []

    def test_invalid_strategy_raises(self, planner, portfolio, adapters):
        with pytest.raises(ValueError, match="Unknown strategy"):
            planner.plan_withdrawal(1000.0, portfolio, adapters, strategy="bogus")

    def test_returns_list_of_withdrawal_steps(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(1000.0, portfolio, adapters)
        assert all(isinstance(s, WithdrawalStep) for s in steps)

    def test_all_amounts_positive(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(5000.0, portfolio, adapters)
        assert all(s.amount_usd > 0.0 for s in steps)

    def test_order_is_sequential(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(5000.0, portfolio, adapters)
        for i, step in enumerate(steps, start=1):
            assert step.order == i

    def test_pct_clamped_to_one(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(1_000_000.0, portfolio, adapters)
        assert all(0.0 <= s.pct_of_position <= 1.0 for s in steps)

    def test_cap_to_available_capital(self, planner):
        port = {"a": 1000.0, "b": 2000.0}
        steps = planner.plan_withdrawal(999_999.0, port, {})
        total = sum(s.amount_usd for s in steps)
        assert abs(total - 3000.0) < 1e-3

    def test_slippage_attached_to_steps(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(5000.0, portfolio, adapters)
        for step in steps:
            assert isinstance(step.estimated_slippage, float)
            assert 0.0 <= step.estimated_slippage <= 1.0

    def test_zero_positions_skipped(self, planner, adapters):
        port = {"aave_v3": 50000.0, "compound_v3": 0.0}
        steps = planner.plan_withdrawal(1000.0, port, adapters)
        ids = [s.adapter_id for s in steps]
        assert "compound_v3" not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — min_impact strategy (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMinImpactStrategy:
    def test_t1_before_t2(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(45000.0, portfolio, adapters,
                                        strategy=STRATEGY_MIN_IMPACT)
        ids = [s.adapter_id for s in steps]
        t1_ids = {"aave_v3", "compound_v3", "morpho_steakhouse"}
        t2_ids = {"yearn_v3"}
        last_t1 = max((i for i, aid in enumerate(ids) if aid in t1_ids), default=-1)
        first_t2 = min((i for i, aid in enumerate(ids) if aid in t2_ids), default=999)
        assert last_t1 < first_t2

    def test_highest_tvl_t1_first(self, planner):
        port = {"aave_v3": 10000.0, "compound_v3": 10000.0}
        adp = {
            "aave_v3":     {"apy": 3.5, "tvl": 9_000_000_000.0, "tier": "T1"},
            "compound_v3": {"apy": 4.8, "tvl": 2_000_000_000.0, "tier": "T1"},
        }
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert steps[0].adapter_id == "aave_v3"

    def test_single_step_sufficient(self, planner):
        port = {"aave_v3": 50000.0}
        adp  = {"aave_v3": {"apy": 3.5, "tvl": 9e9, "tier": "T1"}}
        steps = planner.plan_withdrawal(10000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert len(steps) == 1
        assert abs(steps[0].amount_usd - 10000.0) < 1e-3

    def test_two_steps_for_larger_amount(self, planner):
        port = {"a": 15000.0, "b": 20000.0}
        adp  = {
            "a": {"apy": 3.0, "tvl": 1e10, "tier": "T1"},
            "b": {"apy": 4.0, "tvl": 5e9,  "tier": "T1"},
        }
        steps = planner.plan_withdrawal(20000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert len(steps) == 2

    def test_total_equals_requested(self, planner, portfolio, adapters):
        amount = 25000.0
        steps = planner.plan_withdrawal(amount, portfolio, adapters,
                                        strategy=STRATEGY_MIN_IMPACT)
        total = sum(s.amount_usd for s in steps)
        assert abs(total - amount) < 1e-3

    def test_partial_withdrawal_leaves_position(self, planner):
        port = {"aave_v3": 50000.0}
        adp  = {"aave_v3": {"apy": 3.5, "tvl": 9e9, "tier": "T1"}}
        steps = planner.plan_withdrawal(20000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert steps[0].pct_of_position < 1.0

    def test_full_portfolio_sweep(self, planner, portfolio, adapters):
        total = sum(portfolio.values())
        steps = planner.plan_withdrawal(total, portfolio, adapters,
                                        strategy=STRATEGY_MIN_IMPACT)
        total_planned = sum(s.amount_usd for s in steps)
        assert abs(total_planned - total) < 1e-2

    def test_skips_zero_positions(self, planner, adapters):
        port = {"aave_v3": 30000.0, "compound_v3": 0.0, "morpho_steakhouse": 10000.0}
        steps = planner.plan_withdrawal(5000.0, port, adapters,
                                        strategy=STRATEGY_MIN_IMPACT)
        for step in steps:
            assert step.adapter_id != "compound_v3"

    def test_no_adapter_meta_still_works(self, planner):
        port = {"unknown_proto": 20000.0}
        steps = planner.plan_withdrawal(5000.0, port, {},
                                        strategy=STRATEGY_MIN_IMPACT)
        assert len(steps) == 1
        assert steps[0].adapter_id == "unknown_proto"

    def test_t1_only_uses_tvl_order(self, planner):
        port = {"low_tvl": 20000.0, "high_tvl": 20000.0}
        adp  = {
            "low_tvl":  {"apy": 4.0, "tvl": 1e8,  "tier": "T1"},
            "high_tvl": {"apy": 4.0, "tvl": 1e10, "tier": "T1"},
        }
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert steps[0].adapter_id == "high_tvl"

    def test_t2_only_ordering(self, planner):
        port = {"t2_a": 10000.0, "t2_b": 10000.0}
        adp  = {
            "t2_a": {"apy": 5.0, "tvl": 1e9, "tier": "T2"},
            "t2_b": {"apy": 5.0, "tvl": 2e9, "tier": "T2"},
        }
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert steps[0].adapter_id == "t2_b"   # higher TVL first

    def test_mixed_tiers_t1_exhausted_before_t2(self, planner):
        port = {"t1_proto": 10000.0, "t2_proto": 20000.0}
        adp  = {
            "t1_proto": {"apy": 3.0, "tvl": 1e9, "tier": "T1"},
            "t2_proto": {"apy": 7.0, "tvl": 5e8, "tier": "T2"},
        }
        steps = planner.plan_withdrawal(15000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        ids = [s.adapter_id for s in steps]
        assert ids[0] == "t1_proto"

    def test_deterministic_on_repeated_calls(self, planner, portfolio, adapters):
        s1 = planner.plan_withdrawal(20000.0, portfolio, adapters,
                                     strategy=STRATEGY_MIN_IMPACT)
        s2 = planner.plan_withdrawal(20000.0, portfolio, adapters,
                                     strategy=STRATEGY_MIN_IMPACT)
        assert [s.adapter_id for s in s1] == [s.adapter_id for s in s2]

    def test_dust_avoidance_sweeps_whole_position(self):
        planner = WithdrawalPlanner(min_position_residual_usd=500.0)
        port = {"aave_v3": 5000.0}
        adp  = {"aave_v3": {"apy": 3.5, "tvl": 9e9, "tier": "T1"}}
        # Request leaves 400 residual → should sweep full position
        steps = planner.plan_withdrawal(4700.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert abs(steps[0].amount_usd - 5000.0) < 1e-3
        assert steps[0].pct_of_position == 1.0

    def test_dust_avoidance_large_residual_no_sweep(self):
        planner = WithdrawalPlanner(min_position_residual_usd=100.0)
        port = {"aave_v3": 50000.0}
        adp  = {"aave_v3": {"apy": 3.5, "tvl": 9e9, "tier": "T1"}}
        # Residual = 45000 >> 100 → no sweep
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MIN_IMPACT)
        assert abs(steps[0].amount_usd - 5000.0) < 1e-3


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — max_yield strategy (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMaxYieldStrategy:
    def test_lowest_apy_first(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(50000.0, portfolio, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        # aave_v3 has lowest APY (3.5%) → should appear first
        assert steps[0].adapter_id == "aave_v3"

    def test_high_yield_preserved(self, planner, portfolio, adapters):
        # morpho_steakhouse has APY 6.5% (highest T1); yearn_v3 has 5.2%
        steps = planner.plan_withdrawal(10000.0, portfolio, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        ids = [s.adapter_id for s in steps]
        assert "morpho_steakhouse" not in ids

    def test_single_position(self, planner):
        port = {"only_one": 20000.0}
        adp  = {"only_one": {"apy": 5.0, "tvl": 1e9, "tier": "T1"}}
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MAX_YIELD)
        assert len(steps) == 1
        assert abs(steps[0].amount_usd - 5000.0) < 1e-3

    def test_all_same_apy_alphabetical(self, planner):
        port = {"z_proto": 10000.0, "a_proto": 10000.0}
        adp  = {
            "z_proto": {"apy": 4.0, "tier": "T1"},
            "a_proto": {"apy": 4.0, "tier": "T1"},
        }
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MAX_YIELD)
        assert steps[0].adapter_id == "a_proto"   # alphabetical tie-break

    def test_skips_zero_positions(self, planner, adapters):
        port = {"aave_v3": 0.0, "compound_v3": 30000.0, "yearn_v3": 10000.0}
        steps = planner.plan_withdrawal(5000.0, port, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        assert all(s.adapter_id != "aave_v3" for s in steps)

    def test_total_correct(self, planner, portfolio, adapters):
        amount = 15000.0
        steps = planner.plan_withdrawal(amount, portfolio, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        total = sum(s.amount_usd for s in steps)
        assert abs(total - amount) < 1e-3

    def test_no_adapter_meta_apy_uses_zero(self, planner):
        port = {"known": 10000.0, "unknown": 10000.0}
        adp  = {"known": {"apy": 5.0, "tier": "T1"}}
        # unknown has no APY → defaults to 0.0 → comes first
        steps = planner.plan_withdrawal(5000.0, port, adp,
                                        strategy=STRATEGY_MAX_YIELD)
        assert steps[0].adapter_id == "unknown"

    def test_orders_are_sequential(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(50000.0, portfolio, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        for i, s in enumerate(steps, start=1):
            assert s.order == i

    def test_exact_amount_one_step(self, planner):
        port = {"x": 10000.0}
        steps = planner.plan_withdrawal(10000.0, port, {},
                                        strategy=STRATEGY_MAX_YIELD)
        assert abs(steps[0].amount_usd - 10000.0) < 1e-3
        assert steps[0].pct_of_position == 1.0

    def test_full_sweep_all_positions(self, planner, portfolio, adapters):
        total = sum(portfolio.values())
        steps = planner.plan_withdrawal(total, portfolio, adapters,
                                        strategy=STRATEGY_MAX_YIELD)
        assert abs(sum(s.amount_usd for s in steps) - total) < 1e-2


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — pro_rata strategy (11 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestProRataStrategy:
    def test_proportional_amounts(self, planner):
        port = {"a": 60000.0, "b": 40000.0}
        steps = planner.plan_withdrawal(10000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        by_id = {s.adapter_id: s.amount_usd for s in steps}
        assert abs(by_id["a"] - 6000.0) < 1e-3
        assert abs(by_id["b"] - 4000.0) < 1e-3

    def test_weights_match_portfolio(self, planner):
        port = {"a": 50000.0, "b": 50000.0}
        steps = planner.plan_withdrawal(20000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        by_id = {s.adapter_id: s.amount_usd for s in steps}
        assert abs(by_id["a"] - by_id["b"]) < 1e-3   # equal weights → equal amounts

    def test_total_correct(self, planner, portfolio, adapters):
        amount = 25000.0
        steps = planner.plan_withdrawal(amount, portfolio, adapters,
                                        strategy=STRATEGY_PRO_RATA)
        total = sum(s.amount_usd for s in steps)
        assert abs(total - amount) < 1e-3

    def test_single_position(self, planner):
        port = {"solo": 20000.0}
        steps = planner.plan_withdrawal(5000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        assert len(steps) == 1
        assert abs(steps[0].amount_usd - 5000.0) < 1e-3

    def test_equal_positions_equal_amounts(self, planner):
        port = {"x": 10000.0, "y": 10000.0, "z": 10000.0}
        steps = planner.plan_withdrawal(9000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        amounts = [s.amount_usd for s in steps]
        assert all(abs(a - 3000.0) < 1e-3 for a in amounts)

    def test_skips_zero_positions(self, planner):
        port = {"a": 30000.0, "b": 0.0, "c": 20000.0}
        steps = planner.plan_withdrawal(5000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        assert all(s.adapter_id != "b" for s in steps)

    def test_all_nonzero_steps_present(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(10000.0, portfolio, adapters,
                                        strategy=STRATEGY_PRO_RATA)
        ids = {s.adapter_id for s in steps}
        expected = {k for k, v in portfolio.items() if v > 0}
        assert ids == expected

    def test_pct_matches_weight(self, planner):
        port = {"big": 80000.0, "small": 20000.0}
        steps = planner.plan_withdrawal(10000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        by_id = {s.adapter_id: s for s in steps}
        # big: 80% of portfolio, 10000 withdrawal → 8000 taken = 10%
        assert abs(by_id["big"].pct_of_position - 0.1) < 1e-4
        # small: 20% of portfolio, 2000 taken = 10%
        assert abs(by_id["small"].pct_of_position - 0.1) < 1e-4

    def test_dust_avoidance(self):
        planner = WithdrawalPlanner(min_position_residual_usd=200.0)
        # small position: weight = 1/1000; 10000 * (100/100100) ≈ 9.99 → residual = 90 < 200
        # → should sweep whole small position
        port = {"big": 100000.0, "tiny": 100.0}
        steps = planner.plan_withdrawal(10000.0, port, {},
                                        strategy=STRATEGY_PRO_RATA)
        by_id = {s.adapter_id: s for s in steps}
        # tiny residual would be ~0 → swept to 100
        assert by_id["tiny"].pct_of_position == 1.0

    def test_large_withdrawal_all_positions(self, planner, portfolio, adapters):
        total = sum(portfolio.values())
        steps = planner.plan_withdrawal(total * 0.9, portfolio, adapters,
                                        strategy=STRATEGY_PRO_RATA)
        assert len(steps) == len([v for v in portfolio.values() if v > 0])

    def test_deterministic(self, planner, portfolio, adapters):
        s1 = planner.plan_withdrawal(20000.0, portfolio, adapters,
                                     strategy=STRATEGY_PRO_RATA)
        s2 = planner.plan_withdrawal(20000.0, portfolio, adapters,
                                     strategy=STRATEGY_PRO_RATA)
        assert [s.adapter_id for s in s1] == [s.adapter_id for s in s2]


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — estimate_slippage (16 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateSlippage:
    def _step(self, amount_usd: float) -> WithdrawalStep:
        return WithdrawalStep(adapter_id="x", amount_usd=amount_usd,
                              pct_of_position=0.1, order=1)

    def test_t1_large_tvl_gives_low_slippage(self, planner):
        step = self._step(1_000_000.0)
        slip = planner.estimate_slippage(step, {"tvl": 9e9, "tier": "T1"})
        assert slip < 0.01

    def test_t2_higher_than_t1_same_tvl(self, planner):
        step = self._step(1_000_000.0)
        tvl  = 1_000_000_000.0
        s_t1 = planner.estimate_slippage(step, {"tvl": tvl, "tier": "T1"})
        s_t2 = planner.estimate_slippage(step, {"tvl": tvl, "tier": "T2"})
        assert s_t2 > s_t1

    def test_t3_higher_than_t2_same_tvl(self, planner):
        step = self._step(1_000_000.0)
        tvl  = 1_000_000_000.0
        s_t2 = planner.estimate_slippage(step, {"tvl": tvl, "tier": "T2"})
        s_t3 = planner.estimate_slippage(step, {"tvl": tvl, "tier": "T3"})
        assert s_t3 > s_t2

    def test_zero_tvl_uses_baseline(self, planner):
        step = self._step(10000.0)
        slip = planner.estimate_slippage(step, {"tvl": 0.0, "tier": "T1"})
        assert slip > 0.0

    def test_negative_tvl_uses_baseline(self, planner):
        step = self._step(10000.0)
        slip = planner.estimate_slippage(step, {"tvl": -1000.0, "tier": "T1"})
        assert slip > 0.0

    def test_clamped_to_one_max(self, planner):
        step = self._step(1e12)   # absurdly large withdrawal
        slip = planner.estimate_slippage(step, {"tvl": 1000.0, "tier": "T3"})
        assert slip == 1.0

    def test_clamped_to_zero_min(self, planner):
        step = self._step(0.0)
        slip = planner.estimate_slippage(step, {"tvl": 1e9, "tier": "T1"})
        assert slip == 0.0

    def test_zero_amount_zero_slippage(self, planner):
        step = self._step(0.0)
        slip = planner.estimate_slippage(step, {"tvl": 1e9, "tier": "T1"})
        assert slip == 0.0

    def test_formula_t1(self, planner):
        # slippage = amount / (tvl * factor_T1)
        # factor_T1 = 0.01
        step  = self._step(9_000_000.0)
        tvl   = 9_000_000_000.0
        # expected = 9e6 / (9e9 * 0.01) = 9e6 / 9e7 = 0.1
        expected = 9_000_000.0 / (9_000_000_000.0 * 0.01)
        slip = planner.estimate_slippage(step, {"tvl": tvl, "tier": "T1"})
        assert abs(slip - expected) < 1e-9

    def test_custom_liquidity_factor(self, planner):
        step = self._step(1000.0)
        # factor = 1.0 → depth = tvl; slippage = 1000/1e6 = 0.001
        slip = planner.estimate_slippage(step,
                                         {"tvl": 1_000_000.0, "liquidity_factor": 1.0})
        assert abs(slip - 0.001) < 1e-9

    def test_unknown_tier_uses_default_factor(self, planner):
        step  = self._step(10000.0)
        tvl   = 1_000_000_000.0
        # default factor = 0.10
        expected = 10000.0 / (1_000_000_000.0 * 0.10)
        slip = planner.estimate_slippage(step, {"tvl": tvl, "tier": "UNKNOWN"})
        assert abs(slip - expected) < 1e-9

    def test_no_meta_uses_conservative_defaults(self, planner):
        step = self._step(1000.0)
        slip = planner.estimate_slippage(step, {})
        # tvl defaults to 1M, tier "T2" → factor 0.05
        expected = 1000.0 / (1_000_000.0 * 0.05)
        assert abs(slip - expected) < 1e-9

    def test_t1_t2_t3_ordering_consistent(self, planner):
        step = self._step(5_000_000.0)
        tvl  = 1_000_000_000.0
        slips = {
            t: planner.estimate_slippage(step, {"tvl": tvl, "tier": t})
            for t in ("T1", "T2", "T3")
        }
        assert slips["T1"] < slips["T2"] < slips["T3"]

    def test_high_tvl_near_zero_slippage(self, planner):
        step = self._step(1.0)   # $1 withdrawal
        slip = planner.estimate_slippage(step, {"tvl": 1e12, "tier": "T1"})
        assert slip < 1e-8

    def test_slippage_scales_with_amount(self, planner):
        meta = {"tvl": 1e9, "tier": "T1"}
        s1 = planner.estimate_slippage(self._step(1000.0), meta)
        s2 = planner.estimate_slippage(self._step(2000.0), meta)
        assert abs(s2 - 2 * s1) < 1e-12

    def test_slippage_returns_float(self, planner):
        step = self._step(1000.0)
        slip = planner.estimate_slippage(step, {"tvl": 1e9, "tier": "T1"})
        assert isinstance(slip, float)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7 — get_withdrawal_sequence (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetWithdrawalSequence:
    def test_required_keys_present(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters)
        required = {
            "generated_at", "strategy", "requested_usd", "planned_usd",
            "coverage_pct", "step_count", "total_slippage_cost_usd",
            "weighted_slippage", "steps", "warnings",
        }
        assert required.issubset(plan.keys())

    def test_default_strategy_min_impact(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters)
        assert plan["strategy"] == STRATEGY_MIN_IMPACT

    def test_max_yield_strategy_recorded(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters,
                                               strategy=STRATEGY_MAX_YIELD)
        assert plan["strategy"] == STRATEGY_MAX_YIELD

    def test_pro_rata_strategy_recorded(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters,
                                               strategy=STRATEGY_PRO_RATA)
        assert plan["strategy"] == STRATEGY_PRO_RATA

    def test_coverage_pct_one_when_sufficient(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(5000.0, portfolio, adapters)
        assert abs(plan["coverage_pct"] - 1.0) < 1e-6

    def test_coverage_pct_partial_when_insufficient(self, planner):
        port = {"only": 5000.0}
        plan = planner.get_withdrawal_sequence(20000.0, port, {})
        assert plan["coverage_pct"] < 1.0

    def test_insufficient_funds_warning(self, planner):
        port = {"only": 5000.0}
        plan = planner.get_withdrawal_sequence(20000.0, port, {})
        assert len(plan["warnings"]) > 0
        assert any("Insufficient" in w for w in plan["warnings"])

    def test_slippage_warning_emitted(self):
        planner = WithdrawalPlanner(slippage_cap=0.0)   # cap = 0 → always warns
        port = {"a": 50000.0}
        adp  = {"a": {"tvl": 1000.0, "tier": "T3"}}    # low TVL → high slippage
        plan = planner.get_withdrawal_sequence(1000.0, port, adp)
        assert any("slippage" in w.lower() for w in plan["warnings"])

    def test_planned_usd_equals_sum_of_steps(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(20000.0, portfolio, adapters)
        step_total = sum(s["amount_usd"] for s in plan["steps"])
        assert abs(plan["planned_usd"] - step_total) < 1e-3

    def test_step_count_matches_steps_length(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters)
        assert plan["step_count"] == len(plan["steps"])

    def test_empty_portfolio_returns_zero_steps(self, planner):
        plan = planner.get_withdrawal_sequence(10000.0, {}, {})
        assert plan["step_count"] == 0
        assert plan["planned_usd"] == 0.0

    def test_zero_amount_returns_zero_steps(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(0.0, portfolio, adapters)
        assert plan["step_count"] == 0

    def test_generated_at_is_iso8601(self, planner, portfolio, adapters):
        from datetime import datetime
        plan = planner.get_withdrawal_sequence(1000.0, portfolio, adapters)
        dt = datetime.fromisoformat(plan["generated_at"])
        assert dt is not None

    def test_warnings_is_list(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(1000.0, portfolio, adapters)
        assert isinstance(plan["warnings"], list)

    def test_weighted_slippage_bounded(self, planner, portfolio, adapters):
        plan = planner.get_withdrawal_sequence(10000.0, portfolio, adapters)
        assert 0.0 <= plan["weighted_slippage"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Group 8 — record_withdrawal (12 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordWithdrawal:
    def _make_plan(self, planner, portfolio, adapters, amount=10000.0):
        return planner.get_withdrawal_sequence(amount, portfolio, adapters)

    def test_creates_file(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        assert (Path(tmp_data_dir) / "withdrawal_history.json").exists()

    def test_file_is_valid_json(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        raw = (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        data = json.loads(raw)
        assert isinstance(data, list)

    def test_appends_entries(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert len(data) == 2

    def test_ring_buffer_evicts_oldest(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        # Write HISTORY_MAX + 5 entries
        for _ in range(HISTORY_MAX + 5):
            planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert len(data) == HISTORY_MAX

    def test_actual_usd_sum_stored(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        actuals = {"aave_v3": 5000.0, "compound_v3": 3000.0}
        planner.record_withdrawal(plan, actuals, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert abs(data[0]["actual_usd"] - 8000.0) < 1e-3

    def test_execution_gap_computed(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters, amount=10000.0)
        actuals = {"aave_v3": 9500.0}   # 500 short
        planner.record_withdrawal(plan, actuals, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert data[0]["execution_gap_usd"] > 0.0

    def test_entry_structure(self, planner, portfolio, adapters, tmp_data_dir):
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {"aave_v3": 3000.0}, data_dir=tmp_data_dir)
        entry = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )[0]
        required = {
            "recorded_at", "strategy", "requested_usd", "planned_usd",
            "actual_usd", "execution_gap_usd", "coverage_pct",
            "step_count", "weighted_slippage", "steps",
            "actual_amounts", "warnings",
        }
        assert required.issubset(entry.keys())

    def test_actual_amounts_stored(self, planner, portfolio, adapters, tmp_data_dir):
        plan  = self._make_plan(planner, portfolio, adapters)
        actuals = {"aave_v3": 4000.0, "compound_v3": 6000.0}
        planner.record_withdrawal(plan, actuals, data_dir=tmp_data_dir)
        entry = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )[0]
        assert entry["actual_amounts"]["aave_v3"] == 4000.0
        assert entry["actual_amounts"]["compound_v3"] == 6000.0

    def test_tolerates_corrupt_file(self, planner, portfolio, adapters, tmp_data_dir):
        hist_path = Path(tmp_data_dir) / "withdrawal_history.json"
        hist_path.write_text("NOT_VALID_JSON", encoding="utf-8")
        plan = self._make_plan(planner, portfolio, adapters)
        # Should not raise; starts fresh
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        data = json.loads(hist_path.read_text())
        assert len(data) == 1

    def test_recorded_at_is_iso8601(self, planner, portfolio, adapters, tmp_data_dir):
        from datetime import datetime
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        entry = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )[0]
        dt = datetime.fromisoformat(entry["recorded_at"])
        assert dt is not None

    def test_atomic_write_no_partial_file(self, planner, portfolio, adapters, tmp_data_dir):
        """Verify no .tmp file is left after a successful write."""
        plan = self._make_plan(planner, portfolio, adapters)
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        tmp_files = list(Path(tmp_data_dir).glob(".withdrawal_history_*.tmp"))
        assert len(tmp_files) == 0

    def test_strategy_recorded_correctly(self, planner, portfolio, adapters, tmp_data_dir):
        plan = planner.get_withdrawal_sequence(
            5000.0, portfolio, adapters, strategy=STRATEGY_MAX_YIELD
        )
        planner.record_withdrawal(plan, {}, data_dir=tmp_data_dir)
        entry = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )[0]
        assert entry["strategy"] == STRATEGY_MAX_YIELD


# ═══════════════════════════════════════════════════════════════════════════════
# Group 9 — WithdrawalPlanner init & configuration (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWithdrawalPlannerInit:
    def test_default_min_residual(self):
        p = WithdrawalPlanner()
        assert p.min_position_residual_usd == WithdrawalPlanner.MIN_POSITION_RESIDUAL_USD

    def test_default_slippage_cap(self):
        p = WithdrawalPlanner()
        assert p.slippage_cap == WithdrawalPlanner.SLIPPAGE_CAP

    def test_custom_min_residual(self):
        p = WithdrawalPlanner(min_position_residual_usd=50.0)
        assert p.min_position_residual_usd == 50.0

    def test_custom_slippage_cap(self):
        p = WithdrawalPlanner(slippage_cap=0.02)
        assert p.slippage_cap == 0.02

    def test_float_coercion(self):
        p = WithdrawalPlanner(min_position_residual_usd=200, slippage_cap=1)
        assert isinstance(p.min_position_residual_usd, float)
        assert isinstance(p.slippage_cap, float)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 10 — integration / cross-strategy (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_all_strategies_cover_same_amount(self, planner, portfolio, adapters):
        amount = 20000.0
        for strategy in (STRATEGY_MIN_IMPACT, STRATEGY_MAX_YIELD, STRATEGY_PRO_RATA):
            steps = planner.plan_withdrawal(amount, portfolio, adapters,
                                            strategy=strategy)
            total = sum(s.amount_usd for s in steps)
            assert abs(total - amount) < 1e-2, f"{strategy} total mismatch"

    def test_record_then_reload_consistent(self, planner, portfolio, adapters,
                                           tmp_data_dir):
        plan = planner.get_withdrawal_sequence(15000.0, portfolio, adapters)
        actuals = {s["adapter_id"]: s["amount_usd"] for s in plan["steps"]}
        planner.record_withdrawal(plan, actuals, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert len(data) == 1
        entry = data[0]
        assert abs(entry["actual_usd"] - plan["planned_usd"]) < 1e-3
        assert abs(entry["execution_gap_usd"]) < 1e-3

    def test_multiple_strategies_different_order(self, planner, portfolio, adapters):
        s_impact = planner.plan_withdrawal(50000.0, portfolio, adapters,
                                           strategy=STRATEGY_MIN_IMPACT)
        s_yield  = planner.plan_withdrawal(50000.0, portfolio, adapters,
                                           strategy=STRATEGY_MAX_YIELD)
        ids_impact = [s.adapter_id for s in s_impact]
        ids_yield  = [s.adapter_id for s in s_yield]
        # The two strategies should produce different orderings for this portfolio
        assert ids_impact != ids_yield

    def test_plan_to_sequence_consistency(self, planner, portfolio, adapters):
        steps = planner.plan_withdrawal(10000.0, portfolio, adapters)
        plan  = planner.get_withdrawal_sequence(10000.0, portfolio, adapters)
        # step_count from plan matches direct plan_withdrawal result
        assert plan["step_count"] == len(steps)

    def test_full_cycle_all_three_strategies(self, planner, portfolio, adapters,
                                             tmp_data_dir):
        for strategy in (STRATEGY_MIN_IMPACT, STRATEGY_MAX_YIELD, STRATEGY_PRO_RATA):
            plan    = planner.get_withdrawal_sequence(5000.0, portfolio, adapters,
                                                      strategy=strategy)
            actuals = {s["adapter_id"]: s["amount_usd"] for s in plan["steps"]}
            planner.record_withdrawal(plan, actuals, data_dir=tmp_data_dir)
        data = json.loads(
            (Path(tmp_data_dir) / "withdrawal_history.json").read_text()
        )
        assert len(data) == 3
        strategies_recorded = [e["strategy"] for e in data]
        assert set(strategies_recorded) == {
            STRATEGY_MIN_IMPACT, STRATEGY_MAX_YIELD, STRATEGY_PRO_RATA
        }
