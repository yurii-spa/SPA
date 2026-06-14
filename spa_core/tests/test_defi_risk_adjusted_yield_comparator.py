"""
Tests for MP-976: DeFiRiskAdjustedYieldComparator
Run: python3 -m unittest spa_core.tests.test_defi_risk_adjusted_yield_comparator
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_risk_adjusted_yield_comparator import (
    DeFiRiskAdjustedYieldComparator,
    FLAG_NEW_PROTOCOL,
    FLAG_HIGH_VOLATILITY,
    FLAG_SMART_CONTRACT_CONCERN,
    FLAG_EFFICIENT_FRONTIER,
    FLAG_RISK_TRAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(**kwargs):
    """Return a minimal valid strategy dict with overridable defaults."""
    base = {
        "name": "TestStrategy",
        "protocol": "TestProtocol",
        "gross_apy_pct": 10.0,
        "smart_contract_risk_score": 20.0,
        "liquidity_risk_score": 20.0,
        "counterparty_risk_score": 20.0,
        "il_risk_score": 20.0,
        "regulatory_risk_score": 20.0,
        "gas_cost_annual_pct": 1.0,
        "days_of_track_record": 365,
        "max_drawdown_pct": 5.0,
        "yield_volatility_pct": 3.0,
    }
    base.update(kwargs)
    return base


class TestDeFiRiskAdjustedYieldComparator(unittest.TestCase):
    """Unit tests for DeFiRiskAdjustedYieldComparator."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "risk_adjusted_yield_log.json")
        self.comparator = DeFiRiskAdjustedYieldComparator(data_file=self.log_file)

    # ------------------------------------------------------------------
    # 1. Basic structure
    # ------------------------------------------------------------------

    def test_compare_returns_dict(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIsInstance(result, dict)

    def test_compare_has_results_key(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("results", result)

    def test_compare_has_aggregates_key(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("aggregates", result)

    def test_compare_has_run_ts(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("run_ts", result)

    def test_compare_has_strategy_count(self):
        result = self.comparator.compare([_make_strategy(), _make_strategy()])
        self.assertEqual(result["strategy_count"], 2)

    def test_compare_empty_list(self):
        result = self.comparator.compare([])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["strategy_count"], 0)

    def test_compare_single_strategy(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertEqual(len(result["results"]), 1)

    def test_compare_multiple_strategies(self):
        strategies = [_make_strategy(name=f"S{i}") for i in range(5)]
        result = self.comparator.compare(strategies)
        self.assertEqual(len(result["results"]), 5)

    # ------------------------------------------------------------------
    # 2. Result fields per strategy
    # ------------------------------------------------------------------

    def test_result_has_name(self):
        result = self.comparator.compare([_make_strategy(name="MyStrat")])
        self.assertEqual(result["results"][0]["name"], "MyStrat")

    def test_result_has_protocol(self):
        result = self.comparator.compare([_make_strategy(protocol="Aave")])
        self.assertEqual(result["results"][0]["protocol"], "Aave")

    def test_result_has_composite_risk_score(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("composite_risk_score", result["results"][0])

    def test_result_has_risk_adjusted_yield(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("risk_adjusted_yield", result["results"][0])

    def test_result_has_net_apy_after_gas(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("net_apy_after_gas", result["results"][0])

    def test_result_has_defi_sharpe_ratio(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("defi_sharpe_ratio", result["results"][0])

    def test_result_has_risk_efficiency_score(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("risk_efficiency_score", result["results"][0])

    def test_result_has_label(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("label", result["results"][0])

    def test_result_has_flags(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("flags", result["results"][0])

    # ------------------------------------------------------------------
    # 3. Composite risk score computation
    # ------------------------------------------------------------------

    def test_composite_risk_equal_weights(self):
        s = _make_strategy(
            smart_contract_risk_score=50.0,
            liquidity_risk_score=50.0,
            counterparty_risk_score=50.0,
            il_risk_score=50.0,
            regulatory_risk_score=50.0,
        )
        result = self.comparator.compare([s])
        # All risks = 50, weighted sum = 50*(0.3+0.2+0.2+0.15+0.15) = 50
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 50.0, places=2)

    def test_composite_risk_zero(self):
        s = _make_strategy(
            smart_contract_risk_score=0,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 0.0, places=4)

    def test_composite_risk_max(self):
        s = _make_strategy(
            smart_contract_risk_score=100,
            liquidity_risk_score=100,
            counterparty_risk_score=100,
            il_risk_score=100,
            regulatory_risk_score=100,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 100.0, places=2)

    def test_composite_risk_weighted(self):
        # SC=100 (w=0.3), rest=0 → composite = 30
        s = _make_strategy(
            smart_contract_risk_score=100,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 30.0, places=2)

    def test_composite_risk_liq_weight(self):
        # LIQ=100 (w=0.2), rest=0 → composite = 20
        s = _make_strategy(
            smart_contract_risk_score=0,
            liquidity_risk_score=100,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 20.0, places=2)

    def test_composite_risk_il_weight(self):
        # IL=100 (w=0.15), rest=0 → composite = 15
        s = _make_strategy(
            smart_contract_risk_score=0,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=100,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 15.0, places=2)

    def test_composite_risk_reg_weight(self):
        # REG=100 (w=0.15), rest=0 → composite = 15
        s = _make_strategy(
            smart_contract_risk_score=0,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=100,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["composite_risk_score"], 15.0, places=2)

    def test_composite_risk_clamped_0_100(self):
        s = _make_strategy(
            smart_contract_risk_score=200,
            liquidity_risk_score=200,
            counterparty_risk_score=200,
            il_risk_score=200,
            regulatory_risk_score=200,
        )
        result = self.comparator.compare([s])
        self.assertLessEqual(result["results"][0]["composite_risk_score"], 100.0)

    # ------------------------------------------------------------------
    # 4. Risk-adjusted yield computation
    # ------------------------------------------------------------------

    def test_risk_adjusted_yield_positive(self):
        result = self.comparator.compare([_make_strategy(gross_apy_pct=10.0)])
        self.assertGreater(result["results"][0]["risk_adjusted_yield"], 0.0)

    def test_risk_adjusted_yield_less_than_gross(self):
        s = _make_strategy(gross_apy_pct=10.0, smart_contract_risk_score=50)
        result = self.comparator.compare([s])
        r = result["results"][0]
        self.assertLess(r["risk_adjusted_yield"], r["gross_apy_pct"])

    def test_risk_adjusted_yield_zero_risk(self):
        s = _make_strategy(
            gross_apy_pct=10.0,
            smart_contract_risk_score=0,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        # With 0 composite risk: RAY = gross/(1+0) = gross
        self.assertAlmostEqual(
            result["results"][0]["risk_adjusted_yield"],
            10.0, places=3
        )

    def test_risk_adjusted_yield_formula(self):
        s = _make_strategy(
            gross_apy_pct=20.0,
            smart_contract_risk_score=40,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        # composite = 40*0.3 = 12; RAY = 20/(1+12/100) = 20/1.12 ≈ 17.857
        result = self.comparator.compare([s])
        expected = 20.0 / 1.12
        self.assertAlmostEqual(
            result["results"][0]["risk_adjusted_yield"], expected, places=2
        )

    # ------------------------------------------------------------------
    # 5. Net APY after gas
    # ------------------------------------------------------------------

    def test_net_apy_after_gas(self):
        s = _make_strategy(gross_apy_pct=10.0, gas_cost_annual_pct=2.0)
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["net_apy_after_gas"], 8.0, places=4)

    def test_net_apy_can_be_negative(self):
        s = _make_strategy(gross_apy_pct=1.0, gas_cost_annual_pct=5.0)
        result = self.comparator.compare([s])
        self.assertLess(result["results"][0]["net_apy_after_gas"], 0.0)

    def test_net_apy_zero_gas(self):
        s = _make_strategy(gross_apy_pct=8.0, gas_cost_annual_pct=0.0)
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["net_apy_after_gas"], 8.0, places=4)

    # ------------------------------------------------------------------
    # 6. DeFi Sharpe ratio
    # ------------------------------------------------------------------

    def test_defi_sharpe_positive(self):
        s = _make_strategy(gross_apy_pct=15.0, gas_cost_annual_pct=1.0, yield_volatility_pct=5.0)
        result = self.comparator.compare([s])
        # net = 14; vol = 5; sharpe = 14/5 = 2.8
        self.assertAlmostEqual(result["results"][0]["defi_sharpe_ratio"], 2.8, places=4)

    def test_defi_sharpe_high_volatility_lower(self):
        s1 = _make_strategy(gross_apy_pct=10.0, gas_cost_annual_pct=0.0, yield_volatility_pct=2.0)
        s2 = _make_strategy(gross_apy_pct=10.0, gas_cost_annual_pct=0.0, yield_volatility_pct=10.0)
        r1 = self.comparator.compare([s1])["results"][0]["defi_sharpe_ratio"]
        r2 = self.comparator.compare([s2])["results"][0]["defi_sharpe_ratio"]
        self.assertGreater(r1, r2)

    def test_defi_sharpe_zero_vol_not_crash(self):
        s = _make_strategy(yield_volatility_pct=0.0)
        result = self.comparator.compare([s])
        self.assertIn("defi_sharpe_ratio", result["results"][0])

    # ------------------------------------------------------------------
    # 7. Risk efficiency score
    # ------------------------------------------------------------------

    def test_risk_efficiency_between_0_100(self):
        result = self.comparator.compare([_make_strategy()])
        score = result["results"][0]["risk_efficiency_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_risk_efficiency_zero_risk_is_100(self):
        s = _make_strategy(
            gross_apy_pct=10.0,
            smart_contract_risk_score=0,
            liquidity_risk_score=0,
            counterparty_risk_score=0,
            il_risk_score=0,
            regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["risk_efficiency_score"], 100.0, places=2)

    def test_risk_efficiency_decreases_with_higher_risk(self):
        s_low = _make_strategy(
            smart_contract_risk_score=10, liquidity_risk_score=10,
            counterparty_risk_score=10, il_risk_score=10, regulatory_risk_score=10
        )
        s_high = _make_strategy(
            smart_contract_risk_score=80, liquidity_risk_score=80,
            counterparty_risk_score=80, il_risk_score=80, regulatory_risk_score=80
        )
        r_low = self.comparator.compare([s_low])["results"][0]["risk_efficiency_score"]
        r_high = self.comparator.compare([s_high])["results"][0]["risk_efficiency_score"]
        self.assertGreater(r_low, r_high)

    # ------------------------------------------------------------------
    # 8. Labels
    # ------------------------------------------------------------------

    def test_label_top_tier(self):
        # High sharpe (>2) + low risk (<40)
        s = _make_strategy(
            gross_apy_pct=30.0,
            gas_cost_annual_pct=0.5,
            yield_volatility_pct=5.0,
            smart_contract_risk_score=10,
            liquidity_risk_score=10,
            counterparty_risk_score=10,
            il_risk_score=10,
            regulatory_risk_score=10,
        )
        result = self.comparator.compare([s])
        self.assertEqual(result["results"][0]["label"], "TOP_TIER")

    def test_label_risk_trap(self):
        # High risk (>70) AND low yield (<5)
        s = _make_strategy(
            gross_apy_pct=3.0,
            gas_cost_annual_pct=0.5,
            yield_volatility_pct=50.0,
            smart_contract_risk_score=95,
            liquidity_risk_score=95,
            counterparty_risk_score=95,
            il_risk_score=95,
            regulatory_risk_score=95,
        )
        result = self.comparator.compare([s])
        self.assertEqual(result["results"][0]["label"], "RISK_TRAP")

    def test_label_high_risk(self):
        # composite_risk > 60 but not risk trap (yield>5)
        s = _make_strategy(
            gross_apy_pct=15.0,
            gas_cost_annual_pct=1.0,
            yield_volatility_pct=20.0,
            smart_contract_risk_score=90,
            liquidity_risk_score=90,
            counterparty_risk_score=90,
            il_risk_score=90,
            regulatory_risk_score=90,
        )
        result = self.comparator.compare([s])
        label = result["results"][0]["label"]
        self.assertIn(label, ["HIGH_RISK", "RISK_TRAP"])

    def test_label_standard(self):
        # Moderate risk, moderate yield
        s = _make_strategy(
            gross_apy_pct=5.0,
            gas_cost_annual_pct=1.0,
            yield_volatility_pct=10.0,
            smart_contract_risk_score=40,
            liquidity_risk_score=40,
            counterparty_risk_score=40,
            il_risk_score=40,
            regulatory_risk_score=40,
        )
        result = self.comparator.compare([s])
        label = result["results"][0]["label"]
        self.assertIn(label, ["STANDARD", "HIGH_RISK"])

    def test_label_is_string(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIsInstance(result["results"][0]["label"], str)

    def test_valid_labels_set(self):
        valid = {"TOP_TIER", "HIGH_QUALITY", "STANDARD", "HIGH_RISK", "RISK_TRAP"}
        s = _make_strategy()
        result = self.comparator.compare([s])
        self.assertIn(result["results"][0]["label"], valid)

    # ------------------------------------------------------------------
    # 9. Flags
    # ------------------------------------------------------------------

    def test_flag_new_protocol(self):
        s = _make_strategy(days_of_track_record=30)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_NEW_PROTOCOL, result["results"][0]["flags"])

    def test_no_flag_new_protocol_when_old(self):
        s = _make_strategy(days_of_track_record=365)
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_NEW_PROTOCOL, result["results"][0]["flags"])

    def test_flag_high_volatility(self):
        s = _make_strategy(yield_volatility_pct=75.0)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_HIGH_VOLATILITY, result["results"][0]["flags"])

    def test_no_flag_high_volatility_when_low(self):
        s = _make_strategy(yield_volatility_pct=10.0)
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_HIGH_VOLATILITY, result["results"][0]["flags"])

    def test_flag_smart_contract_concern(self):
        s = _make_strategy(smart_contract_risk_score=80.0)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_SMART_CONTRACT_CONCERN, result["results"][0]["flags"])

    def test_no_flag_smart_contract_concern_when_safe(self):
        s = _make_strategy(smart_contract_risk_score=30.0)
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_SMART_CONTRACT_CONCERN, result["results"][0]["flags"])

    def test_flag_efficient_frontier(self):
        # risk<30 AND net_apy>10
        s = _make_strategy(
            gross_apy_pct=20.0,
            gas_cost_annual_pct=0.5,
            smart_contract_risk_score=5,
            liquidity_risk_score=5,
            counterparty_risk_score=5,
            il_risk_score=5,
            regulatory_risk_score=5,
        )
        result = self.comparator.compare([s])
        self.assertIn(FLAG_EFFICIENT_FRONTIER, result["results"][0]["flags"])

    def test_no_flag_efficient_frontier_high_risk(self):
        s = _make_strategy(
            gross_apy_pct=20.0,
            smart_contract_risk_score=60,
            liquidity_risk_score=60,
            counterparty_risk_score=60,
            il_risk_score=60,
            regulatory_risk_score=60,
        )
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_EFFICIENT_FRONTIER, result["results"][0]["flags"])

    def test_flag_risk_trap(self):
        s = _make_strategy(
            gross_apy_pct=2.0,
            gas_cost_annual_pct=0.5,
            smart_contract_risk_score=95,
            liquidity_risk_score=95,
            counterparty_risk_score=95,
            il_risk_score=95,
            regulatory_risk_score=95,
        )
        result = self.comparator.compare([s])
        self.assertIn(FLAG_RISK_TRAP, result["results"][0]["flags"])

    def test_flags_is_list(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIsInstance(result["results"][0]["flags"], list)

    def test_multiple_flags_possible(self):
        # New protocol + high volatility + smart contract concern
        s = _make_strategy(
            days_of_track_record=20,
            yield_volatility_pct=80.0,
            smart_contract_risk_score=90.0,
        )
        result = self.comparator.compare([s])
        flags = result["results"][0]["flags"]
        self.assertGreater(len(flags), 1)

    def test_new_protocol_threshold_boundary_89(self):
        s = _make_strategy(days_of_track_record=89)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_NEW_PROTOCOL, result["results"][0]["flags"])

    def test_new_protocol_threshold_boundary_90(self):
        s = _make_strategy(days_of_track_record=90)
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_NEW_PROTOCOL, result["results"][0]["flags"])

    def test_high_vol_threshold_boundary_50(self):
        # yield_vol > 50 triggers
        s = _make_strategy(yield_volatility_pct=51.0)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_HIGH_VOLATILITY, result["results"][0]["flags"])

    def test_sc_concern_threshold_boundary_60(self):
        # sc_risk > 60 triggers
        s = _make_strategy(smart_contract_risk_score=61.0)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_SMART_CONTRACT_CONCERN, result["results"][0]["flags"])

    def test_sc_concern_at_60_no_flag(self):
        s = _make_strategy(smart_contract_risk_score=60.0)
        result = self.comparator.compare([s])
        self.assertNotIn(FLAG_SMART_CONTRACT_CONCERN, result["results"][0]["flags"])

    # ------------------------------------------------------------------
    # 10. Aggregates
    # ------------------------------------------------------------------

    def test_aggregates_best_risk_adjusted(self):
        s1 = _make_strategy(name="LowRisk", gross_apy_pct=10.0,
                             smart_contract_risk_score=5, liquidity_risk_score=5,
                             counterparty_risk_score=5, il_risk_score=5, regulatory_risk_score=5)
        s2 = _make_strategy(name="HighRisk", gross_apy_pct=5.0,
                             smart_contract_risk_score=90, liquidity_risk_score=90,
                             counterparty_risk_score=90, il_risk_score=90, regulatory_risk_score=90)
        result = self.comparator.compare([s1, s2])
        self.assertEqual(result["aggregates"]["best_risk_adjusted"], "LowRisk")

    def test_aggregates_worst_risk_adjusted(self):
        s1 = _make_strategy(name="Good", gross_apy_pct=20.0,
                             smart_contract_risk_score=5, liquidity_risk_score=5,
                             counterparty_risk_score=5, il_risk_score=5, regulatory_risk_score=5)
        s2 = _make_strategy(name="Bad", gross_apy_pct=5.0,
                             smart_contract_risk_score=90, liquidity_risk_score=90,
                             counterparty_risk_score=90, il_risk_score=90, regulatory_risk_score=90)
        result = self.comparator.compare([s1, s2])
        self.assertEqual(result["aggregates"]["worst_risk_adjusted"], "Bad")

    def test_aggregates_best_defi_sharpe(self):
        s1 = _make_strategy(name="HighSharpe", gross_apy_pct=30.0,
                             gas_cost_annual_pct=0.5, yield_volatility_pct=2.0)
        s2 = _make_strategy(name="LowSharpe", gross_apy_pct=5.0,
                             gas_cost_annual_pct=0.5, yield_volatility_pct=20.0)
        result = self.comparator.compare([s1, s2])
        self.assertEqual(result["aggregates"]["best_defi_sharpe"], "HighSharpe")

    def test_aggregates_top_tier_count(self):
        s_top = _make_strategy(
            name="TopTier",
            gross_apy_pct=30.0,
            gas_cost_annual_pct=0.5,
            yield_volatility_pct=5.0,
            smart_contract_risk_score=5,
            liquidity_risk_score=5,
            counterparty_risk_score=5,
            il_risk_score=5,
            regulatory_risk_score=5,
        )
        s_bad = _make_strategy(
            name="Bad",
            gross_apy_pct=2.0,
            smart_contract_risk_score=90,
            liquidity_risk_score=90,
            counterparty_risk_score=90,
            il_risk_score=90,
            regulatory_risk_score=90,
        )
        result = self.comparator.compare([s_top, s_bad])
        self.assertGreaterEqual(result["aggregates"]["top_tier_count"], 1)

    def test_aggregates_average_risk_adjusted_yield(self):
        result = self.comparator.compare([_make_strategy()])
        self.assertIn("average_risk_adjusted_yield", result["aggregates"])
        self.assertIsInstance(result["aggregates"]["average_risk_adjusted_yield"], float)

    def test_aggregates_empty_returns_defaults(self):
        result = self.comparator.compare([])
        agg = result["aggregates"]
        self.assertIsNone(agg["best_risk_adjusted"])
        self.assertIsNone(agg["worst_risk_adjusted"])
        self.assertIsNone(agg["best_defi_sharpe"])
        self.assertEqual(agg["top_tier_count"], 0)
        self.assertEqual(agg["average_risk_adjusted_yield"], 0.0)

    def test_aggregates_average_multiple(self):
        s1 = _make_strategy(name="A", gross_apy_pct=20.0,
                             smart_contract_risk_score=0, liquidity_risk_score=0,
                             counterparty_risk_score=0, il_risk_score=0, regulatory_risk_score=0,
                             gas_cost_annual_pct=0.0)
        s2 = _make_strategy(name="B", gross_apy_pct=10.0,
                             smart_contract_risk_score=0, liquidity_risk_score=0,
                             counterparty_risk_score=0, il_risk_score=0, regulatory_risk_score=0,
                             gas_cost_annual_pct=0.0)
        result = self.comparator.compare([s1, s2])
        # RAY(s1)=20, RAY(s2)=10, avg=15
        self.assertAlmostEqual(result["aggregates"]["average_risk_adjusted_yield"], 15.0, places=2)

    # ------------------------------------------------------------------
    # 11. Log file (ring-buffer)
    # ------------------------------------------------------------------

    def test_log_file_created(self):
        self.comparator.compare([_make_strategy()])
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_file_is_valid_json(self):
        self.comparator.compare([_make_strategy()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        for i in range(3):
            self.comparator.compare([_make_strategy(name=f"S{i}")])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.comparator.compare([_make_strategy()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_ring_buffer_keeps_latest(self):
        # Overfill and check last entry
        for i in range(105):
            self.comparator.compare([_make_strategy(name=f"Run{i}")])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 100)

    def test_log_has_run_ts(self):
        self.comparator.compare([_make_strategy()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertIn("run_ts", log[0])

    def test_log_has_results(self):
        self.comparator.compare([_make_strategy()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertIn("results", log[0])

    # ------------------------------------------------------------------
    # 12. Custom config
    # ------------------------------------------------------------------

    def test_custom_top_tier_sharpe_threshold(self):
        config = {"top_tier_sharpe_threshold": 0.1, "top_tier_risk_threshold": 100.0}
        s = _make_strategy(
            gross_apy_pct=5.0,
            gas_cost_annual_pct=0.5,
            yield_volatility_pct=3.0,
            smart_contract_risk_score=5,
            liquidity_risk_score=5,
            counterparty_risk_score=5,
            il_risk_score=5,
            regulatory_risk_score=5,
        )
        result = self.comparator.compare([s], config=config)
        self.assertEqual(result["results"][0]["label"], "TOP_TIER")

    def test_custom_risk_trap_threshold(self):
        # composite = 40*0.3 + 5*0.2 + 5*0.2 + 5*0.15 + 5*0.15 = 12+1+1+0.75+0.75 = 15.5 > 10
        # net_apy = 5.0 - 0.5 = 4.5 < 20 → RISK_TRAP
        config = {"risk_trap_risk_threshold": 10.0, "risk_trap_yield_threshold": 20.0}
        s = _make_strategy(
            gross_apy_pct=5.0,
            gas_cost_annual_pct=0.5,
            smart_contract_risk_score=40,
            liquidity_risk_score=5,
            counterparty_risk_score=5,
            il_risk_score=5,
            regulatory_risk_score=5,
        )
        result = self.comparator.compare([s], config=config)
        self.assertEqual(result["results"][0]["label"], "RISK_TRAP")

    def test_none_config_defaults_applied(self):
        result = self.comparator.compare([_make_strategy()], config=None)
        self.assertIn("label", result["results"][0])

    # ------------------------------------------------------------------
    # 13. Edge cases
    # ------------------------------------------------------------------

    def test_zero_gross_apy(self):
        s = _make_strategy(gross_apy_pct=0.0)
        result = self.comparator.compare([s])
        self.assertIsNotNone(result["results"][0])

    def test_very_high_gross_apy(self):
        s = _make_strategy(gross_apy_pct=1000.0, yield_volatility_pct=1.0)
        result = self.comparator.compare([s])
        self.assertGreater(result["results"][0]["defi_sharpe_ratio"], 0)

    def test_negative_days_track_record(self):
        s = _make_strategy(days_of_track_record=0)
        result = self.comparator.compare([s])
        self.assertIn(FLAG_NEW_PROTOCOL, result["results"][0]["flags"])

    def test_strategy_with_all_zero_risks_efficiency_100(self):
        s = _make_strategy(
            gross_apy_pct=10.0,
            smart_contract_risk_score=0, liquidity_risk_score=0,
            counterparty_risk_score=0, il_risk_score=0, regulatory_risk_score=0,
        )
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["risk_efficiency_score"], 100.0, places=2)

    def test_strategy_name_preserved(self):
        name = "MySpecialStrategy"
        result = self.comparator.compare([_make_strategy(name=name)])
        self.assertEqual(result["results"][0]["name"], name)

    def test_protocol_name_preserved(self):
        result = self.comparator.compare([_make_strategy(protocol="Compound")])
        self.assertEqual(result["results"][0]["protocol"], "Compound")

    def test_max_drawdown_preserved(self):
        s = _make_strategy(max_drawdown_pct=12.5)
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["max_drawdown_pct"], 12.5, places=4)

    def test_days_track_record_preserved(self):
        s = _make_strategy(days_of_track_record=200)
        result = self.comparator.compare([s])
        self.assertEqual(result["results"][0]["days_of_track_record"], 200)

    def test_large_number_of_strategies(self):
        strategies = [_make_strategy(name=f"S{i}") for i in range(50)]
        result = self.comparator.compare(strategies)
        self.assertEqual(result["strategy_count"], 50)
        self.assertEqual(len(result["results"]), 50)

    def test_different_data_file_path(self):
        other_log = os.path.join(self.tmp_dir, "other_log.json")
        comparator = DeFiRiskAdjustedYieldComparator(data_file=other_log)
        comparator.compare([_make_strategy()])
        self.assertTrue(os.path.exists(other_log))

    def test_returns_gross_apy_in_result(self):
        s = _make_strategy(gross_apy_pct=7.77)
        result = self.comparator.compare([s])
        self.assertAlmostEqual(result["results"][0]["gross_apy_pct"], 7.77, places=4)

    def test_strategy_count_matches_input(self):
        n = 7
        result = self.comparator.compare([_make_strategy(name=f"S{i}") for i in range(n)])
        self.assertEqual(result["strategy_count"], n)


if __name__ == "__main__":
    unittest.main()
