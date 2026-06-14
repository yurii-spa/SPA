"""
Tests for MP-939: ProtocolCrossChainYieldArbitrageDetector
Run: python3 -m unittest spa_core.tests.test_protocol_cross_chain_yield_arbitrage_detector -v
Target: ≥85 tests, stdlib unittest only.
"""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector import (
    ProtocolCrossChainYieldArbitrageDetector,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_opp(**kwargs):
    base = {
        "protocol": "Aave",
        "asset": "USDC",
        "source_chain": "Ethereum",
        "source_apy_pct": 3.5,
        "dest_chain": "Arbitrum",
        "dest_apy_pct": 8.2,
        "bridge_fee_pct": 0.05,
        "bridge_time_hours": 0.5,
        "gas_cost_usd": 25.0,
        "position_size_usd": 50_000.0,
        "bridge_risk_score": 25.0,
        "execution_complexity": "simple",
    }
    base.update(kwargs)
    return base


def _exceptional():
    return _make_opp(source_apy_pct=2.0, dest_apy_pct=10.0, bridge_fee_pct=0.1)


def _good():
    return _make_opp(source_apy_pct=3.0, dest_apy_pct=6.0, bridge_fee_pct=0.1)


def _marginal():
    return _make_opp(source_apy_pct=3.0, dest_apy_pct=3.8, bridge_fee_pct=0.1)


def _unprofitable():
    return _make_opp(source_apy_pct=5.0, dest_apy_pct=5.05, bridge_fee_pct=0.1)


def _negative():
    return _make_opp(source_apy_pct=8.0, dest_apy_pct=5.0, bridge_fee_pct=0.5)


class TestInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        d = ProtocolCrossChainYieldArbitrageDetector()
        self.assertIsNotNone(d)


class TestDetectReturnStructure(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_returns_dict(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIsInstance(result, dict)

    def test_has_opportunities_key(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIn("opportunities", result)

    def test_has_aggregates_key(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIn("aggregates", result)

    def test_has_timestamp_key(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIn("timestamp", result)

    def test_has_config_used_key(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIn("config_used", result)

    def test_opportunities_is_list(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIsInstance(result["opportunities"], list)

    def test_aggregates_is_dict(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIsInstance(result["aggregates"], dict)


class TestOpportunityOutputFields(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()
        result = self.d.detect([_exceptional()], {})
        self.o = result["opportunities"][0]

    def test_has_gross_spread_pct(self):
        self.assertIn("gross_spread_pct", self.o)

    def test_has_net_spread_pct(self):
        self.assertIn("net_spread_pct", self.o)

    def test_has_break_even_days(self):
        self.assertIn("break_even_days", self.o)

    def test_has_annualized_profit_usd(self):
        self.assertIn("annualized_profit_usd", self.o)

    def test_has_risk_adjusted_spread(self):
        self.assertIn("risk_adjusted_spread", self.o)

    def test_has_opportunity_label(self):
        self.assertIn("opportunity_label", self.o)

    def test_has_flags(self):
        self.assertIn("flags", self.o)

    def test_flags_is_list(self):
        self.assertIsInstance(self.o["flags"], list)

    def test_has_protocol(self):
        self.assertIn("protocol", self.o)

    def test_has_source_chain(self):
        self.assertIn("source_chain", self.o)

    def test_has_dest_chain(self):
        self.assertIn("dest_chain", self.o)


class TestGrossSpread(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_positive_spread(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["gross_spread_pct"], 5.0, places=4)

    def test_zero_spread(self):
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["gross_spread_pct"], 0.0, places=4)

    def test_negative_spread(self):
        o = _make_opp(source_apy_pct=8.0, dest_apy_pct=5.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["gross_spread_pct"], -3.0, places=4)


class TestNetSpread(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_net_spread_subtracts_bridge_fee(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=1.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["net_spread_pct"], 4.0, places=4)

    def test_net_spread_zero_bridge_fee(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["net_spread_pct"], 5.0, places=4)

    def test_net_spread_can_be_negative(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=3.5, bridge_fee_pct=1.0)
        result = self.d.detect([o], {})
        self.assertLess(result["opportunities"][0]["net_spread_pct"], 0)


class TestAnnualizedProfit(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_basic_annualized_profit(self):
        # net_spread=5%, position=100_000 → profit = 5000
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0,
                      position_size_usd=100_000.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["annualized_profit_usd"], 5000.0, places=2)

    def test_negative_net_spread_negative_profit(self):
        o = _make_opp(source_apy_pct=10.0, dest_apy_pct=3.0, bridge_fee_pct=0.0,
                      position_size_usd=10_000.0)
        result = self.d.detect([o], {})
        self.assertLess(result["opportunities"][0]["annualized_profit_usd"], 0)

    def test_zero_position_size(self):
        o = _make_opp(position_size_usd=0.0)
        result = self.d.detect([o], {})
        profit = result["opportunities"][0]["annualized_profit_usd"]
        self.assertAlmostEqual(profit, 0.0, places=4)


class TestBreakEvenDays(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_positive_profitable_breakeven_finite(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=10.0, bridge_fee_pct=0.0,
                      gas_cost_usd=100.0, position_size_usd=50_000.0)
        result = self.d.detect([o], {})
        be = result["opportunities"][0]["break_even_days"]
        self.assertIsNotNone(be)
        self.assertGreater(be, 0)

    def test_negative_spread_breakeven_none(self):
        o = _make_opp(source_apy_pct=8.0, dest_apy_pct=3.0, bridge_fee_pct=0.5,
                      gas_cost_usd=100.0, position_size_usd=50_000.0)
        result = self.d.detect([o], {})
        be = result["opportunities"][0]["break_even_days"]
        self.assertIsNone(be)

    def test_zero_gas_cost_gives_zero_breakeven(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=10.0, bridge_fee_pct=0.0,
                      gas_cost_usd=0.0, position_size_usd=50_000.0)
        result = self.d.detect([o], {})
        be = result["opportunities"][0]["break_even_days"]
        self.assertAlmostEqual(be, 0.0, places=4)


class TestRiskAdjustedSpread(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_zero_risk_equals_gross(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0,
                      bridge_risk_score=0.0)
        result = self.d.detect([o], {})
        op = result["opportunities"][0]
        self.assertAlmostEqual(op["risk_adjusted_spread"], op["gross_spread_pct"], places=4)

    def test_100_risk_gives_zero_adjusted(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0,
                      bridge_risk_score=100.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["risk_adjusted_spread"], 0.0, places=4)

    def test_50_risk_halves_spread(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0,
                      bridge_risk_score=50.0)
        result = self.d.detect([o], {})
        op = result["opportunities"][0]
        self.assertAlmostEqual(op["risk_adjusted_spread"], op["gross_spread_pct"] * 0.5, places=4)


class TestOpportunityLabels(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    _VALID = {"EXCEPTIONAL", "GOOD", "MARGINAL", "UNPROFITABLE", "NEGATIVE"}

    def test_label_is_valid(self):
        result = self.d.detect([_exceptional()], {})
        label = result["opportunities"][0]["opportunity_label"]
        self.assertIn(label, self._VALID)

    def test_exceptional_label_high_spread(self):
        o = _make_opp(source_apy_pct=1.0, dest_apy_pct=10.0, bridge_fee_pct=0.1)
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["opportunity_label"], "EXCEPTIONAL")

    def test_good_label(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=6.0, bridge_fee_pct=0.1)
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["opportunity_label"], "GOOD")

    def test_marginal_label(self):
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.6, bridge_fee_pct=0.05)
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["opportunity_label"], "MARGINAL")

    def test_unprofitable_label_zero_net(self):
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["opportunity_label"], "UNPROFITABLE")

    def test_negative_label(self):
        o = _make_opp(source_apy_pct=8.0, dest_apy_pct=3.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["opportunity_label"], "NEGATIVE")

    def test_all_labels_valid_for_batch(self):
        opps = [_exceptional(), _good(), _marginal(), _unprofitable(), _negative()]
        result = self.d.detect(opps, {})
        for o in result["opportunities"]:
            self.assertIn(o["opportunity_label"], self._VALID)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_high_bridge_risk_flag(self):
        o = _make_opp(bridge_risk_score=75.0)
        result = self.d.detect([o], {})
        self.assertIn("HIGH_BRIDGE_RISK", result["opportunities"][0]["flags"])

    def test_no_high_bridge_risk_flag_below_threshold(self):
        o = _make_opp(bridge_risk_score=30.0)
        result = self.d.detect([o], {})
        self.assertNotIn("HIGH_BRIDGE_RISK", result["opportunities"][0]["flags"])

    def test_fast_execution_flag(self):
        o = _make_opp(bridge_time_hours=0.3)
        result = self.d.detect([o], {})
        self.assertIn("FAST_EXECUTION", result["opportunities"][0]["flags"])

    def test_no_fast_execution_flag_slow(self):
        o = _make_opp(bridge_time_hours=5.0)
        result = self.d.detect([o], {})
        self.assertNotIn("FAST_EXECUTION", result["opportunities"][0]["flags"])

    def test_large_position_flag(self):
        o = _make_opp(position_size_usd=200_000.0)
        result = self.d.detect([o], {})
        self.assertIn("LARGE_POSITION", result["opportunities"][0]["flags"])

    def test_no_large_position_flag_small(self):
        o = _make_opp(position_size_usd=5_000.0)
        result = self.d.detect([o], {})
        self.assertNotIn("LARGE_POSITION", result["opportunities"][0]["flags"])

    def test_gas_heavy_flag_when_gas_exceeds_profit(self):
        # Very tiny spread → tiny annual profit → gas is huge relative to profit
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.002, bridge_fee_pct=0.0,
                      gas_cost_usd=10_000.0, position_size_usd=10_000.0)
        result = self.d.detect([o], {})
        self.assertIn("GAS_HEAVY", result["opportunities"][0]["flags"])

    def test_gas_heavy_flag_when_negative_profit(self):
        o = _make_opp(source_apy_pct=8.0, dest_apy_pct=5.0, bridge_fee_pct=0.5,
                      gas_cost_usd=50.0)
        result = self.d.detect([o], {})
        self.assertIn("GAS_HEAVY", result["opportunities"][0]["flags"])

    def test_short_breakeven_flag(self):
        # high spread, small gas → breakeven < 7 days
        o = _make_opp(source_apy_pct=1.0, dest_apy_pct=20.0, bridge_fee_pct=0.0,
                      gas_cost_usd=1.0, position_size_usd=100_000.0)
        result = self.d.detect([o], {})
        self.assertIn("SHORT_BREAKEVEN", result["opportunities"][0]["flags"])

    def test_no_short_breakeven_flag_long_breakeven(self):
        # tiny spread → breakeven >> 7 days
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.01, bridge_fee_pct=0.0,
                      gas_cost_usd=5000.0, position_size_usd=10_000.0)
        result = self.d.detect([o], {})
        self.assertNotIn("SHORT_BREAKEVEN", result["opportunities"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()
        self.result = self.d.detect(
            [_exceptional(), _good(), _marginal(), _negative()], {}
        )
        self.agg = self.result["aggregates"]

    def test_has_best_opportunity(self):
        self.assertIn("best_opportunity", self.agg)

    def test_has_worst_opportunity(self):
        self.assertIn("worst_opportunity", self.agg)

    def test_has_total_opportunities(self):
        self.assertIn("total_opportunities", self.agg)

    def test_has_profitable_count(self):
        self.assertIn("profitable_count", self.agg)

    def test_has_average_net_spread(self):
        self.assertIn("average_net_spread", self.agg)

    def test_total_opportunities_correct(self):
        self.assertEqual(self.agg["total_opportunities"], 4)

    def test_profitable_count_nonneg(self):
        self.assertGreaterEqual(self.agg["profitable_count"], 0)

    def test_profitable_count_not_greater_than_total(self):
        self.assertLessEqual(self.agg["profitable_count"], self.agg["total_opportunities"])

    def test_best_is_string(self):
        self.assertIsInstance(self.agg["best_opportunity"], str)

    def test_worst_is_string(self):
        self.assertIsInstance(self.agg["worst_opportunity"], str)

    def test_average_net_spread_is_float(self):
        self.assertIsInstance(self.agg["average_net_spread"], float)

    def test_best_contains_arrow(self):
        self.assertIn("→", self.agg["best_opportunity"])


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_empty_list_returns_dict(self):
        result = self.d.detect([], {})
        self.assertIsInstance(result, dict)

    def test_empty_opportunities_list(self):
        result = self.d.detect([], {})
        self.assertEqual(result["opportunities"], [])

    def test_empty_aggregates_none(self):
        result = self.d.detect([], {})
        self.assertIsNone(result["aggregates"]["best_opportunity"])

    def test_empty_total_zero(self):
        result = self.d.detect([], {})
        self.assertEqual(result["aggregates"]["total_opportunities"], 0)

    def test_empty_profitable_zero(self):
        result = self.d.detect([], {})
        self.assertEqual(result["aggregates"]["profitable_count"], 0)


class TestTypeValidation(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_raises_on_non_list(self):
        with self.assertRaises(TypeError):
            self.d.detect("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.d.detect([], "bad")


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_custom_bridge_risk_threshold(self):
        o = _make_opp(bridge_risk_score=55.0)
        # Default threshold 60 → no flag
        r1 = self.d.detect([o], {})
        self.assertNotIn("HIGH_BRIDGE_RISK", r1["opportunities"][0]["flags"])
        # Lower threshold to 50 → flag
        r2 = self.d.detect([o], {"high_bridge_risk_threshold": 50.0})
        self.assertIn("HIGH_BRIDGE_RISK", r2["opportunities"][0]["flags"])

    def test_custom_large_position_threshold(self):
        o = _make_opp(position_size_usd=80_000.0)
        r1 = self.d.detect([o], {})
        self.assertNotIn("LARGE_POSITION", r1["opportunities"][0]["flags"])
        r2 = self.d.detect([o], {"large_position_usd": 50_000.0})
        self.assertIn("LARGE_POSITION", r2["opportunities"][0]["flags"])

    def test_custom_fast_execution_threshold(self):
        o = _make_opp(bridge_time_hours=2.0)
        r1 = self.d.detect([o], {})
        self.assertNotIn("FAST_EXECUTION", r1["opportunities"][0]["flags"])
        r2 = self.d.detect([o], {"fast_execution_hours": 3.0})
        self.assertIn("FAST_EXECUTION", r2["opportunities"][0]["flags"])

    def test_config_reflected_in_output(self):
        r = self.d.detect([_exceptional()], {"high_bridge_risk_threshold": 40.0})
        self.assertEqual(r["config_used"]["high_bridge_risk_threshold"], 40.0)


class TestSingleOpportunity(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()
        self.result = self.d.detect([_exceptional()], {})

    def test_single_best_equals_worst(self):
        agg = self.result["aggregates"]
        self.assertEqual(agg["best_opportunity"], agg["worst_opportunity"])

    def test_single_total_one(self):
        self.assertEqual(self.result["aggregates"]["total_opportunities"], 1)


class TestMultipleOpportunities(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_five_opps_counted(self):
        opps = [_exceptional(), _good(), _marginal(), _unprofitable(), _negative()]
        result = self.d.detect(opps, {})
        self.assertEqual(result["aggregates"]["total_opportunities"], 5)

    def test_all_labels_present_in_batch(self):
        opps = [_exceptional(), _negative()]
        result = self.d.detect(opps, {})
        labels = {o["opportunity_label"] for o in result["opportunities"]}
        self.assertIn("EXCEPTIONAL", labels)
        self.assertIn("NEGATIVE", labels)

    def test_protocols_preserved(self):
        o1 = _make_opp(protocol="Aave")
        o2 = _make_opp(protocol="Compound")
        result = self.d.detect([o1, o2], {})
        protocols = {o["protocol"] for o in result["opportunities"]}
        self.assertEqual(protocols, {"Aave", "Compound"})


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_log_does_not_crash(self):
        self.d.detect([_exceptional()], {})

    def test_log_written_to_file(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            try:
                self.d.detect([_exceptional()], {})
                self.assertTrue(os.path.exists(mod.LOG_PATH))
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertIsInstance(buf, list)
                self.assertEqual(len(buf), 1)
            finally:
                mod.LOG_PATH = orig

    def test_log_ring_buffer_cap(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            orig_cap = mod.LOG_CAP
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            mod.LOG_CAP = 3
            try:
                for _ in range(5):
                    self.d.detect([_exceptional()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertLessEqual(len(buf), 3)
            finally:
                mod.LOG_PATH = orig
                mod.LOG_CAP = orig_cap

    def test_log_entry_has_ts(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            try:
                self.d.detect([_exceptional()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertIn("ts", buf[0])
            finally:
                mod.LOG_PATH = orig

    def test_log_entry_has_total_opportunities(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            try:
                self.d.detect([_exceptional(), _good()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertEqual(buf[0]["total_opportunities"], 2)
            finally:
                mod.LOG_PATH = orig

    def test_log_entry_has_profitable_count(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            try:
                self.d.detect([_exceptional(), _negative()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertIn("profitable_count", buf[0])
            finally:
                mod.LOG_PATH = orig

    def test_log_accumulates_entries(self):
        import spa_core.analytics.protocol_cross_chain_yield_arbitrage_detector as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "cross_chain_arbitrage_log.json")
            try:
                self.d.detect([_exceptional()], {})
                self.d.detect([_good()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertEqual(len(buf), 2)
            finally:
                mod.LOG_PATH = orig


class TestTimestamp(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_timestamp_is_string(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIsInstance(result["timestamp"], str)

    def test_timestamp_not_empty(self):
        result = self.d.detect([_exceptional()], {})
        self.assertGreater(len(result["timestamp"]), 0)

    def test_timestamp_contains_T(self):
        result = self.d.detect([_exceptional()], {})
        self.assertIn("T", result["timestamp"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_zero_bridge_fee(self):
        o = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        op = result["opportunities"][0]
        self.assertAlmostEqual(op["gross_spread_pct"], op["net_spread_pct"], places=4)

    def test_equal_chains_zero_spread(self):
        o = _make_opp(source_apy_pct=5.0, dest_apy_pct=5.0, bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        self.assertAlmostEqual(result["opportunities"][0]["gross_spread_pct"], 0.0, places=4)

    def test_very_large_position(self):
        o = _make_opp(position_size_usd=1e9)
        result = self.d.detect([o], {})
        self.assertIsNotNone(result["opportunities"][0])

    def test_extra_fields_ignored(self):
        o = _make_opp()
        o["random_field"] = "value"
        result = self.d.detect([o], {})
        self.assertIsNotNone(result)

    def test_complex_execution_preserved(self):
        o = _make_opp(execution_complexity="complex")
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["execution_complexity"], "complex")

    def test_simple_execution_preserved(self):
        o = _make_opp(execution_complexity="simple")
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["execution_complexity"], "simple")

    def test_medium_execution_preserved(self):
        o = _make_opp(execution_complexity="medium")
        result = self.d.detect([o], {})
        self.assertEqual(result["opportunities"][0]["execution_complexity"], "medium")

    def test_zero_bridge_risk_full_gross_in_risk_adjusted(self):
        o = _make_opp(bridge_risk_score=0.0, source_apy_pct=2.0, dest_apy_pct=9.0,
                      bridge_fee_pct=0.0)
        result = self.d.detect([o], {})
        op = result["opportunities"][0]
        self.assertAlmostEqual(op["risk_adjusted_spread"], op["gross_spread_pct"], places=4)


class TestProfitableCountAccuracy(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_all_profitable(self):
        opps = [_exceptional(), _good(), _marginal()]
        result = self.d.detect(opps, {})
        # All have net_spread > 0
        self.assertEqual(result["aggregates"]["profitable_count"], 3)

    def test_none_profitable(self):
        opps = [_negative(), _negative()]
        result = self.d.detect(opps, {})
        self.assertEqual(result["aggregates"]["profitable_count"], 0)

    def test_mixed(self):
        opps = [_exceptional(), _negative()]
        result = self.d.detect(opps, {})
        self.assertEqual(result["aggregates"]["profitable_count"], 1)


class TestAverageNetSpread(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_average_computed_correctly(self):
        # net spreads: 4.9, 2.9 → avg 3.9
        o1 = _make_opp(source_apy_pct=3.0, dest_apy_pct=8.0, bridge_fee_pct=0.1)
        o2 = _make_opp(source_apy_pct=3.0, dest_apy_pct=6.0, bridge_fee_pct=0.1)
        result = self.d.detect([o1, o2], {})
        agg = result["aggregates"]
        spread1 = result["opportunities"][0]["net_spread_pct"]
        spread2 = result["opportunities"][1]["net_spread_pct"]
        expected_avg = (spread1 + spread2) / 2
        self.assertAlmostEqual(agg["average_net_spread"], expected_avg, places=4)


class TestOpportunityLabelDirect(unittest.TestCase):
    def setUp(self):
        self.d = ProtocolCrossChainYieldArbitrageDetector()

    def test_exceptional_threshold_5(self):
        self.assertEqual(self.d._opportunity_label(5.0), "EXCEPTIONAL")

    def test_exceptional_above_5(self):
        self.assertEqual(self.d._opportunity_label(10.0), "EXCEPTIONAL")

    def test_good_at_2(self):
        self.assertEqual(self.d._opportunity_label(2.0), "GOOD")

    def test_good_between_2_and_5(self):
        self.assertEqual(self.d._opportunity_label(3.5), "GOOD")

    def test_marginal_at_0_5(self):
        self.assertEqual(self.d._opportunity_label(0.5), "MARGINAL")

    def test_marginal_between_0_5_and_2(self):
        self.assertEqual(self.d._opportunity_label(1.0), "MARGINAL")

    def test_unprofitable_at_0(self):
        self.assertEqual(self.d._opportunity_label(0.0), "UNPROFITABLE")

    def test_negative_below_0(self):
        self.assertEqual(self.d._opportunity_label(-1.0), "NEGATIVE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
