"""
Tests for MP-1056 DeFiProtocolCrossChainYieldComparator.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_cross_chain_yield_comparator -v
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_cross_chain_yield_comparator import (
    DeFiProtocolCrossChainYieldComparator,
    _atomic_write_json,
    _LOG_CAP,
    _REC_TOP_PICK,
    _REC_STRONG,
    _REC_NEUTRAL,
    _REC_WEAK,
    _REC_AVOID,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pos(**kwargs) -> dict:
    defaults = {
        "chain": "ethereum",
        "protocol": "aave",
        "apy_pct": 5.0,
        "tvl_usd": 1_000_000,
        "bridge_cost_usd": 0.0,
        "gas_cost_usd_per_year": 0.0,
        "slippage_pct": 0.0,
        "days_locked": 0,
    }
    defaults.update(kwargs)
    return defaults


def _analyzer(tmp: str) -> DeFiProtocolCrossChainYieldComparator:
    return DeFiProtocolCrossChainYieldComparator(log_path=os.path.join(tmp, "log.json"))


# ---------------------------------------------------------------------------
# 1. Migration cost computation
# ---------------------------------------------------------------------------

class TestMigrationCost(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_zero_cost(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=0, slippage_pct=0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 365), 0.0)

    def test_bridge_only(self):
        pos = _make_pos(bridge_cost_usd=50, gas_cost_usd_per_year=0, slippage_pct=0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 365), 50.0)

    def test_gas_only_full_year(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=365, slippage_pct=0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 365), 365.0)

    def test_gas_prorated_half_year(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=365, slippage_pct=0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 182.5), 182.5)

    def test_gas_prorated_one_day(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=365, slippage_pct=0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 1), 1.0)

    def test_slippage_only(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=0, slippage_pct=1.0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 10_000, 365), 100.0)

    def test_slippage_scales_with_capital(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=0, slippage_pct=0.5)
        self.assertAlmostEqual(self.a._migration_cost(pos, 100_000, 365), 500.0)

    def test_all_three_components(self):
        pos = _make_pos(bridge_cost_usd=10, gas_cost_usd_per_year=730, slippage_pct=0.1)
        # bridge=10, gas=365(half year), slippage=10_000*0.1/100=10
        cost = self.a._migration_cost(pos, 10_000, 182.5)
        self.assertAlmostEqual(cost, 10 + 365 + 10)

    def test_large_capital_slippage(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=0, slippage_pct=2.0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 1_000_000, 365), 20_000.0)

    def test_zero_capital_no_slippage_effect(self):
        pos = _make_pos(bridge_cost_usd=5, gas_cost_usd_per_year=0, slippage_pct=99.0)
        self.assertAlmostEqual(self.a._migration_cost(pos, 0, 365), 5.0)

    def test_fractional_holding_period(self):
        pos = _make_pos(bridge_cost_usd=0, gas_cost_usd_per_year=365, slippage_pct=0)
        cost = self.a._migration_cost(pos, 1_000, 0.5)
        self.assertAlmostEqual(cost, 0.5)

    def test_missing_keys_default_to_zero(self):
        pos = {"chain": "eth", "protocol": "x"}
        self.assertAlmostEqual(self.a._migration_cost(pos, 1_000, 30), 0.0)


# ---------------------------------------------------------------------------
# 2. Net APY computation
# ---------------------------------------------------------------------------

class TestNetApy(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_zero_cost_net_equals_gross(self):
        self.assertAlmostEqual(self.a._net_apy(5.0, 0.0, 100_000, 365), 5.0)

    def test_positive_net_after_costs(self):
        # 5 % APY on 100k = 5000 usd/year. cost 1000. net = 4000/100k * 100 = 4%
        net = self.a._net_apy(5.0, 1_000.0, 100_000, 365)
        self.assertAlmostEqual(net, 4.0)

    def test_negative_net_when_costs_exceed_yield(self):
        # APY 1% on 10k = 100 usd/year. cost 200. net negative
        net = self.a._net_apy(1.0, 200.0, 10_000, 365)
        self.assertLess(net, 0)

    def test_zero_capital_returns_zero(self):
        self.assertEqual(self.a._net_apy(10.0, 0.0, 0, 365), 0.0)

    def test_short_holding_period_amplifies_cost_drag(self):
        # 30-day hold. gross 5%/yr on 10k = 10k*0.05*(30/365)=41.1. cost 50 > yield → negative
        net = self.a._net_apy(5.0, 50.0, 10_000, 30)
        self.assertLess(net, 0)

    def test_annualised_correctly_short_period(self):
        # 5% gross, zero cost, 30 days → net should still be 5%
        self.assertAlmostEqual(self.a._net_apy(5.0, 0.0, 100_000, 30), 5.0, places=4)

    def test_high_apy_no_cost(self):
        self.assertAlmostEqual(self.a._net_apy(50.0, 0.0, 100_000, 365), 50.0)

    def test_zero_apy_positive_cost_is_negative(self):
        net = self.a._net_apy(0.0, 100.0, 10_000, 365)
        self.assertLess(net, 0)

    def test_rounding_to_6_places(self):
        net = self.a._net_apy(3.333333333, 0.0, 100_000, 365)
        # Result rounded to 6 decimal places
        self.assertEqual(net, round(net, 6))

    def test_cost_exactly_equals_gross_yield(self):
        # 5% on 10k = 500/yr. cost = 500 → net = 0
        net = self.a._net_apy(5.0, 500.0, 10_000, 365)
        self.assertAlmostEqual(net, 0.0, places=5)


# ---------------------------------------------------------------------------
# 3. Break-even days
# ---------------------------------------------------------------------------

class TestBreakEvenDays(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_zero_cost_returns_zero(self):
        self.assertEqual(self.a._break_even_days(5.0, 0.0, 100_000), 0.0)

    def test_basic_break_even(self):
        # daily yield = 100k * 0.05 / 365 ≈ 13.699
        # cost = 100  → be = 100 / 13.699 ≈ 7.3 days
        be = self.a._break_even_days(5.0, 100.0, 100_000)
        self.assertAlmostEqual(be, 100 / (100_000 * 0.05 / 365), places=2)

    def test_zero_apy_with_cost_is_inf(self):
        be = self.a._break_even_days(0.0, 50.0, 100_000)
        self.assertEqual(be, float("inf"))

    def test_negative_apy_is_inf(self):
        be = self.a._break_even_days(-2.0, 50.0, 100_000)
        self.assertEqual(be, float("inf"))

    def test_zero_capital_with_cost_is_inf(self):
        be = self.a._break_even_days(5.0, 50.0, 0.0)
        self.assertEqual(be, float("inf"))

    def test_large_cost_long_break_even(self):
        # daily yield = 100k * 0.01 / 365 ≈ 2.74
        # cost = 10000 → be ≈ 3650 days
        be = self.a._break_even_days(1.0, 10_000.0, 100_000)
        self.assertAlmostEqual(be, 10_000 / (100_000 * 0.01 / 365), places=1)

    def test_small_cost_short_break_even(self):
        # daily yield = 100k * 0.10 / 365 ≈ 27.4
        # cost = 1 → be ≈ 0.036 days
        be = self.a._break_even_days(10.0, 1.0, 100_000)
        self.assertLess(be, 1)

    def test_result_rounded_to_4_places(self):
        be = self.a._break_even_days(3.0, 7.0, 50_000)
        self.assertEqual(be, round(be, 4))

    def test_high_apy_moderate_cost_near_zero(self):
        # 50% APY on $1M → daily_yield ≈ 1369; cost = 5 → be ≈ 0.0037 days (rounds > 0)
        be = self.a._break_even_days(50.0, 5.0, 1_000_000)
        self.assertGreater(be, 0)
        self.assertLess(be, 1.0)

    def test_positive_cost_positive_apy_finite_result(self):
        be = self.a._break_even_days(5.0, 500.0, 100_000)
        self.assertFalse(math.isinf(be))
        self.assertGreater(be, 0)


# ---------------------------------------------------------------------------
# 4. Yield advantage vs worst
# ---------------------------------------------------------------------------

class TestYieldAdvantage(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def _run(self, positions, capital=100_000, holding=365):
        return self.a.analyze({
            "positions": positions,
            "capital_usd": capital,
            "holding_period_days": holding,
        })["ranked_positions"]

    def test_worst_position_has_zero_advantage(self):
        pos = [_make_pos(protocol="a", apy_pct=5), _make_pos(protocol="b", apy_pct=3)]
        ranked = self._run(pos)
        worst = ranked[-1]
        self.assertAlmostEqual(worst["yield_advantage_pct"], 0.0)

    def test_best_position_has_positive_advantage(self):
        pos = [_make_pos(protocol="a", apy_pct=5), _make_pos(protocol="b", apy_pct=3)]
        ranked = self._run(pos)
        best = ranked[0]
        self.assertGreater(best["yield_advantage_pct"], 0.0)

    def test_advantage_equals_net_apy_difference(self):
        pos = [_make_pos(protocol="a", apy_pct=5), _make_pos(protocol="b", apy_pct=2)]
        ranked = self._run(pos)
        diff = ranked[0]["net_apy_pct"] - ranked[-1]["net_apy_pct"]
        self.assertAlmostEqual(ranked[0]["yield_advantage_pct"], diff, places=5)

    def test_single_position_advantage_zero(self):
        ranked = self._run([_make_pos(apy_pct=7)])
        self.assertAlmostEqual(ranked[0]["yield_advantage_pct"], 0.0)

    def test_all_equal_apy_all_advantage_zero(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=5) for i in range(4)]
        ranked = self._run(pos)
        for p in ranked:
            self.assertAlmostEqual(p["yield_advantage_pct"], 0.0)

    def test_three_positions_ordered_advantage(self):
        pos = [
            _make_pos(protocol="a", apy_pct=10),
            _make_pos(protocol="b", apy_pct=6),
            _make_pos(protocol="c", apy_pct=2),
        ]
        ranked = self._run(pos)
        self.assertGreater(ranked[0]["yield_advantage_pct"], ranked[1]["yield_advantage_pct"])
        self.assertGreater(ranked[1]["yield_advantage_pct"], ranked[2]["yield_advantage_pct"])

    def test_advantage_non_negative(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=i) for i in range(1, 6)]
        ranked = self._run(pos)
        for p in ranked:
            self.assertGreaterEqual(p["yield_advantage_pct"], 0.0)

    def test_advantage_with_negative_net_apy(self):
        pos = [
            _make_pos(protocol="a", apy_pct=5),
            _make_pos(protocol="b", apy_pct=0.1, bridge_cost_usd=10_000),
        ]
        ranked = self._run(pos, capital=1_000)
        worst_adv = ranked[-1]["yield_advantage_pct"]
        self.assertAlmostEqual(worst_adv, 0.0)


# ---------------------------------------------------------------------------
# 5. Recommendation labels
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def _rec(self, net_apy, rank, best_net_apy):
        return self.a._recommend(net_apy, rank, best_net_apy)

    def test_rank0_always_top_pick(self):
        self.assertEqual(self._rec(5.0, 0, 5.0), _REC_TOP_PICK)

    def test_rank0_even_if_negative(self):
        self.assertEqual(self._rec(-1.0, 0, -1.0), _REC_TOP_PICK)

    def test_rank0_zero_net_apy(self):
        self.assertEqual(self._rec(0.0, 0, 0.0), _REC_TOP_PICK)

    def test_negative_net_apy_non_rank0_avoid(self):
        self.assertEqual(self._rec(-0.5, 1, 5.0), _REC_AVOID)

    def test_strongly_negative_avoid(self):
        self.assertEqual(self._rec(-100.0, 2, 5.0), _REC_AVOID)

    def test_best_zero_non_rank0_neutral(self):
        # best_net_apy <= 0, rank > 0, net_apy >= 0 → NEUTRAL
        self.assertEqual(self._rec(0.0, 1, 0.0), _REC_NEUTRAL)

    def test_ratio_at_90_is_strong(self):
        self.assertEqual(self._rec(9.0, 1, 10.0), _REC_STRONG)  # ratio = 0.9

    def test_ratio_above_90_is_strong(self):
        self.assertEqual(self._rec(9.5, 1, 10.0), _REC_STRONG)  # ratio = 0.95

    def test_ratio_70_is_neutral(self):
        self.assertEqual(self._rec(7.0, 1, 10.0), _REC_NEUTRAL)  # ratio = 0.7

    def test_ratio_80_is_neutral(self):
        self.assertEqual(self._rec(8.0, 1, 10.0), _REC_NEUTRAL)  # ratio = 0.8

    def test_ratio_50_is_weak(self):
        self.assertEqual(self._rec(5.0, 1, 10.0), _REC_WEAK)  # ratio = 0.5

    def test_ratio_60_is_weak(self):
        self.assertEqual(self._rec(6.0, 1, 10.0), _REC_WEAK)  # ratio = 0.6

    def test_ratio_below_50_is_avoid(self):
        self.assertEqual(self._rec(4.0, 1, 10.0), _REC_AVOID)  # ratio = 0.4

    def test_ratio_near_zero_is_avoid(self):
        self.assertEqual(self._rec(0.1, 1, 10.0), _REC_AVOID)  # ratio = 0.01

    def test_full_analyze_recommendations_present(self):
        pos = [
            _make_pos(protocol="a", apy_pct=10),
            _make_pos(protocol="b", apy_pct=9.2),
            _make_pos(protocol="c", apy_pct=7.5),
            _make_pos(protocol="d", apy_pct=4.0),
        ]
        ranked = self.a.analyze({
            "positions": pos, "capital_usd": 100_000, "holding_period_days": 365
        })["ranked_positions"]
        valid = {_REC_TOP_PICK, _REC_STRONG, _REC_NEUTRAL, _REC_WEAK, _REC_AVOID}
        for p in ranked:
            self.assertIn(p["recommendation"], valid)
        self.assertEqual(ranked[0]["recommendation"], _REC_TOP_PICK)


# ---------------------------------------------------------------------------
# 6. Ranking / sorting
# ---------------------------------------------------------------------------

class TestRanking(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def _run(self, positions, capital=100_000, holding=365):
        return self.a.analyze({
            "positions": positions,
            "capital_usd": capital,
            "holding_period_days": holding,
        })["ranked_positions"]

    def test_sorted_descending_by_net_apy(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=i+1) for i in range(5)]
        ranked = self._run(pos)
        net_apys = [p["net_apy_pct"] for p in ranked]
        self.assertEqual(net_apys, sorted(net_apys, reverse=True))

    def test_reverse_input_still_sorted(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=5-i) for i in range(5)]
        ranked = self._run(pos)
        net_apys = [p["net_apy_pct"] for p in ranked]
        self.assertEqual(net_apys, sorted(net_apys, reverse=True))

    def test_single_position_is_rank0(self):
        ranked = self._run([_make_pos(apy_pct=7)])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["recommendation"], _REC_TOP_PICK)

    def test_empty_positions_returns_empty(self):
        ranked = self._run([])
        self.assertEqual(ranked, [])

    def test_costs_change_ranking(self):
        # high APY but high bridge cost may drop below lower APY with no cost
        high_apy = _make_pos(protocol="a", apy_pct=20, bridge_cost_usd=5_000)
        low_apy  = _make_pos(protocol="b", apy_pct=5,  bridge_cost_usd=0)
        ranked   = self._run([high_apy, low_apy], capital=10_000, holding=30)
        # With 10k capital, 30 day hold, high_apy gross≈164 but cost=5000 → huge negative
        self.assertEqual(ranked[0]["protocol"], "b")

    def test_all_fields_preserved(self):
        pos = [_make_pos(protocol="aave", chain="mainnet", tvl_usd=9_000_000)]
        ranked = self._run(pos)
        self.assertEqual(ranked[0]["protocol"], "aave")
        self.assertEqual(ranked[0]["chain"], "mainnet")
        self.assertEqual(ranked[0]["tvl_usd"], 9_000_000)

    def test_output_keys_present(self):
        ranked = self._run([_make_pos()])
        p = ranked[0]
        for key in ("net_apy_pct", "migration_cost_usd", "break_even_days",
                    "yield_advantage_pct", "recommendation"):
            self.assertIn(key, p)

    def test_two_positions_both_negative_sorted(self):
        pos = [
            _make_pos(protocol="a", apy_pct=1, bridge_cost_usd=50_000),
            _make_pos(protocol="b", apy_pct=2, bridge_cost_usd=50_000),
        ]
        ranked = self._run(pos, capital=1_000, holding=30)
        # Both negative; higher apy (b) should be less negative → rank 0
        self.assertEqual(ranked[0]["protocol"], "b")


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def _run(self, **kwargs):
        return self.a.analyze(kwargs)["ranked_positions"]

    def test_no_positions_key(self):
        result = self.a.analyze({"capital_usd": 10000, "holding_period_days": 30})
        self.assertEqual(result["ranked_positions"], [])

    def test_zero_capital(self):
        pos = [_make_pos(apy_pct=5)]
        ranked = self._run(positions=pos, capital_usd=0, holding_period_days=365)
        self.assertEqual(ranked[0]["net_apy_pct"], 0.0)

    def test_negative_holding_period_clamped(self):
        pos = [_make_pos(apy_pct=5)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=-10)
        # Should not crash; holding clamped to 1
        self.assertIn("net_apy_pct", ranked[0])

    def test_zero_holding_period_clamped(self):
        pos = [_make_pos(apy_pct=5)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=0)
        self.assertIn("net_apy_pct", ranked[0])

    def test_very_large_capital(self):
        pos = [_make_pos(apy_pct=5, slippage_pct=0.01)]
        ranked = self._run(positions=pos, capital_usd=1e12, holding_period_days=365)
        self.assertAlmostEqual(ranked[0]["net_apy_pct"], 5.0 - 0.01, places=3)

    def test_many_positions(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=float(i)) for i in range(1, 21)]
        ranked = self._run(positions=pos, capital_usd=100_000, holding_period_days=365)
        self.assertEqual(len(ranked), 20)

    def test_position_missing_optional_fields(self):
        pos = [{"chain": "eth", "protocol": "x", "apy_pct": 5.0}]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=30)
        self.assertAlmostEqual(ranked[0]["migration_cost_usd"], 0.0)

    def test_days_locked_field_preserved(self):
        pos = [_make_pos(days_locked=90)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=365)
        self.assertEqual(ranked[0]["days_locked"], 90)

    def test_non_numeric_apy_defaults_to_zero(self):
        pos = [{"chain": "eth", "protocol": "x", "apy_pct": None}]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=30)
        self.assertEqual(ranked[0]["net_apy_pct"], 0.0)

    def test_ranked_positions_key_always_present(self):
        result = self.a.analyze({})
        self.assertIn("ranked_positions", result)

    def test_multiple_chains_allowed(self):
        pos = [
            _make_pos(protocol="aave",     chain="ethereum"),
            _make_pos(protocol="radiant",  chain="arbitrum"),
            _make_pos(protocol="moonwell", chain="base"),
        ]
        ranked = self._run(positions=pos, capital_usd=50_000, holding_period_days=180)
        chains = {p["chain"] for p in ranked}
        self.assertEqual(chains, {"ethereum", "arbitrum", "base"})

    def test_all_zero_apy_zero_cost(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=0) for i in range(3)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=365)
        for p in ranked:
            self.assertAlmostEqual(p["net_apy_pct"], 0.0)

    def test_holding_period_1_day(self):
        pos = [_make_pos(apy_pct=5)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=1)
        self.assertAlmostEqual(ranked[0]["net_apy_pct"], 5.0, places=3)

    def test_very_high_apy(self):
        pos = [_make_pos(apy_pct=10000)]
        ranked = self._run(positions=pos, capital_usd=10_000, holding_period_days=365)
        self.assertAlmostEqual(ranked[0]["net_apy_pct"], 10000.0)

    def test_migration_cost_exceeds_capital(self):
        pos = [_make_pos(apy_pct=5, bridge_cost_usd=1_000_000)]
        ranked = self._run(positions=pos, capital_usd=1_000, holding_period_days=365)
        self.assertLess(ranked[0]["net_apy_pct"], 0)


# ---------------------------------------------------------------------------
# 8. Log file
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):

    def _make_log_path(self, td):
        return os.path.join(td, "log.json")

    def test_log_created_on_analyze(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            a.analyze({"positions": [_make_pos()], "capital_usd": 1000, "holding_period_days": 30})
            self.assertTrue(os.path.exists(path))

    def test_log_is_json_list(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            a.analyze({"positions": [_make_pos()], "capital_usd": 1000, "holding_period_days": 30})
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            a.analyze({"positions": [], "capital_usd": 1000, "holding_period_days": 30})
            with open(path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_log_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            for _ in range(_LOG_CAP + 10):
                a.analyze({"positions": [], "capital_usd": 1000, "holding_period_days": 30})
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), _LOG_CAP)

    def test_corrupt_log_reset_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            with open(path, "w") as f:
                f.write("NOT JSON}}{{")
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            a.analyze({"positions": [], "capital_usd": 1000, "holding_period_days": 30})
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_n_positions_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make_log_path(td)
            a = DeFiProtocolCrossChainYieldComparator(log_path=path)
            pos = [_make_pos(protocol=f"p{i}") for i in range(3)]
            a.analyze({"positions": pos, "capital_usd": 1000, "holding_period_days": 30})
            with open(path) as f:
                entry = json.load(f)[0]
            self.assertEqual(entry["n_positions"], 3)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sub", "data.json")
            _atomic_write_json(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "value")


# ---------------------------------------------------------------------------
# 9. Integration (full analyze workflow)
# ---------------------------------------------------------------------------

class TestAnalyzeIntegration(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.a  = _analyzer(self.td)

    def test_realistic_three_chain_scenario(self):
        positions = [
            _make_pos(chain="ethereum", protocol="aave",    apy_pct=3.5,
                      bridge_cost_usd=0,   gas_cost_usd_per_year=200, slippage_pct=0.05),
            _make_pos(chain="arbitrum", protocol="radiant", apy_pct=8.0,
                      bridge_cost_usd=5,   gas_cost_usd_per_year=50,  slippage_pct=0.1),
            _make_pos(chain="base",     protocol="moonwell",apy_pct=6.5,
                      bridge_cost_usd=3,   gas_cost_usd_per_year=30,  slippage_pct=0.08),
        ]
        result = self.a.analyze({
            "positions": positions,
            "capital_usd": 100_000,
            "holding_period_days": 180,
        })
        ranked = result["ranked_positions"]
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0]["recommendation"], _REC_TOP_PICK)
        self.assertEqual(ranked[-1]["yield_advantage_pct"], 0.0)

    def test_result_dict_has_ranked_positions_key(self):
        result = self.a.analyze({"positions": [], "capital_usd": 0, "holding_period_days": 1})
        self.assertIn("ranked_positions", result)

    def test_all_output_fields_present(self):
        ranked = self.a.analyze({
            "positions": [_make_pos()],
            "capital_usd": 10_000,
            "holding_period_days": 90,
        })["ranked_positions"]
        for key in ("chain", "protocol", "apy_pct", "net_apy_pct",
                    "migration_cost_usd", "break_even_days",
                    "yield_advantage_pct", "recommendation"):
            self.assertIn(key, ranked[0])

    def test_top_pick_has_highest_net_apy(self):
        pos = [_make_pos(protocol=f"p{i}", apy_pct=float(i+1)) for i in range(5)]
        ranked = self.a.analyze({
            "positions": pos, "capital_usd": 50_000, "holding_period_days": 365
        })["ranked_positions"]
        top = ranked[0]
        for other in ranked[1:]:
            self.assertGreaterEqual(top["net_apy_pct"], other["net_apy_pct"])

    def test_no_trades_or_side_effects_on_allocator(self):
        # This module must be read-only; calling analyze many times is idempotent
        pos = [_make_pos(apy_pct=5)]
        r1 = self.a.analyze({"positions": pos, "capital_usd": 10_000, "holding_period_days": 30})
        r2 = self.a.analyze({"positions": pos, "capital_usd": 10_000, "holding_period_days": 30})
        self.assertEqual(
            r1["ranked_positions"][0]["net_apy_pct"],
            r2["ranked_positions"][0]["net_apy_pct"]
        )

    def test_single_position_complete_output(self):
        ranked = self.a.analyze({
            "positions": [_make_pos(apy_pct=4.5, bridge_cost_usd=20, slippage_pct=0.1)],
            "capital_usd": 50_000,
            "holding_period_days": 90,
        })["ranked_positions"]
        p = ranked[0]
        self.assertEqual(p["recommendation"], _REC_TOP_PICK)
        self.assertAlmostEqual(p["yield_advantage_pct"], 0.0)
        self.assertGreater(p["migration_cost_usd"], 0)

    def test_break_even_inf_for_zero_apy_with_cost(self):
        ranked = self.a.analyze({
            "positions": [_make_pos(apy_pct=0, bridge_cost_usd=100)],
            "capital_usd": 10_000,
            "holding_period_days": 365,
        })["ranked_positions"]
        self.assertEqual(ranked[0]["break_even_days"], float("inf"))

    def test_high_costs_make_multiple_positions_avoid(self):
        positions = [
            _make_pos(protocol="a", apy_pct=1, bridge_cost_usd=100_000),
            _make_pos(protocol="b", apy_pct=2, bridge_cost_usd=100_000),
        ]
        ranked = self.a.analyze({
            "positions": positions, "capital_usd": 1_000, "holding_period_days": 30
        })["ranked_positions"]
        # rank 0 → TOP_PICK; rank 1 with negative net_apy → AVOID
        self.assertEqual(ranked[0]["recommendation"], _REC_TOP_PICK)
        self.assertEqual(ranked[1]["recommendation"], _REC_AVOID)


if __name__ == "__main__":
    unittest.main()
