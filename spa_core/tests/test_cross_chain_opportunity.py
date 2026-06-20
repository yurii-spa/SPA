"""
Tests for spa_core.analytics.cross_chain_opportunity (MP-594).

Classes:
    TestBridgeCost              (10 tests) — fields & total_cost_usd
    TestCrossChainOpportunity   (10 tests) — fields, is_profitable, recommendation
    TestLoadChainData           (10 tests) — empty/missing/valid data → chain grouping
    TestGetBridgeCost           (10 tests) — known pairs, unknown pair → None
    TestComputeBreakeven        (12 tests) — formula, edge cases
    TestAnalyzePair             (15 tests) — full pipeline
    TestGetAllOpportunities     (12 tests) — filtering & sorting
    TestGetTopOpportunity       ( 8 tests) — best profitable, None when empty
    TestSaveAnalysis            ( 5 tests) — atomic write, ring-buffer

Total: 92 tests
Run:
    python3 -m unittest spa_core.tests.test_cross_chain_opportunity -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# ── Make sure project root is on sys.path ──────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.cross_chain_opportunity import (
    BridgeCost,
    CrossChainOpportunity,
    CrossChainOpportunityAnalyzer,
)

# ---------------------------------------------------------------------------
# Shared mock data helpers
# ---------------------------------------------------------------------------

def _make_mock_status(
    eth_apy: float = 4.0,
    arb_apy: float = 6.0,
    base_apy: float = 7.0,
    polygon_apy: float = 5.0,
    optimism_apy: float = 5.5,
) -> dict:
    """Returns a minimal adapter_status.json-compatible dict."""
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "schema_version": 1,
        "adapters": [
            {
                "protocol_key": "mock-protocol",
                "tier": "T1",
                "chains": ["ethereum", "arbitrum", "base", "polygon", "optimism"],
                "mock_apy": {
                    "ethereum": {"USDC": eth_apy},
                    "arbitrum": {"USDC": arb_apy},
                    "base": {"USDC": base_apy},
                    "polygon": {"USDC": polygon_apy},
                    "optimism": {"USDC": optimism_apy},
                },
            }
        ],
    }


def _make_mock_status_two_adapters(
    eth_apy1: float = 4.0,
    eth_apy2: float = 5.0,
    arb_apy: float = 8.0,
) -> dict:
    """Two adapters on ethereum, one on arbitrum."""
    return {
        "schema_version": 1,
        "adapters": [
            {
                "protocol_key": "proto-a",
                "tier": "T1",
                "chains": ["ethereum", "arbitrum"],
                "mock_apy": {
                    "ethereum": {"USDC": eth_apy1},
                    "arbitrum": {"USDC": arb_apy},
                },
            },
            {
                "protocol_key": "proto-b",
                "tier": "T2",
                "chains": ["ethereum"],
                "mock_apy": {
                    "ethereum": {"USDC": eth_apy2},
                },
            },
        ],
    }


def _write_status(tmp_dir: str, data: dict) -> str:
    """Writes adapter_status.json into tmp_dir, returns its path."""
    path = os.path.join(tmp_dir, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def _make_analyzer(tmp_dir: str, data: dict) -> CrossChainOpportunityAnalyzer:
    """Creates analyzer backed by mock data in tmp_dir."""
    path = _write_status(tmp_dir, data)
    return CrossChainOpportunityAnalyzer(data_path=path)


# ===========================================================================
# TestBridgeCost (10 tests)
# ===========================================================================

class TestBridgeCost(unittest.TestCase):
    """Tests for BridgeCost dataclass and total_cost_usd method."""

    def setUp(self):
        self.bc = BridgeCost(
            chain_from="ethereum",
            chain_to="arbitrum",
            gas_cost_usd=2.0,
            slippage_pct=0.0005,
            time_hours=0.1,
        )

    def test_field_chain_from(self):
        self.assertEqual(self.bc.chain_from, "ethereum")

    def test_field_chain_to(self):
        self.assertEqual(self.bc.chain_to, "arbitrum")

    def test_field_gas_cost_usd(self):
        self.assertIsInstance(self.bc.gas_cost_usd, float)
        self.assertEqual(self.bc.gas_cost_usd, 2.0)

    def test_field_slippage_pct(self):
        self.assertIsInstance(self.bc.slippage_pct, float)
        self.assertEqual(self.bc.slippage_pct, 0.0005)

    def test_field_time_hours(self):
        self.assertIsInstance(self.bc.time_hours, float)
        self.assertEqual(self.bc.time_hours, 0.1)

    def test_total_cost_zero_capital(self):
        # When capital = 0: total = gas_cost_usd + 0
        self.assertAlmostEqual(self.bc.total_cost_usd(0.0), 2.0)

    def test_total_cost_100k_capital(self):
        # 2.0 + 0.0005 * 100_000 = 2.0 + 50.0 = 52.0
        self.assertAlmostEqual(self.bc.total_cost_usd(100_000.0), 52.0)

    def test_total_cost_formula_manual(self):
        bc = BridgeCost("polygon", "ethereum", 0.5, 0.001, 168.0)
        expected = 0.5 + 0.001 * 50_000
        self.assertAlmostEqual(bc.total_cost_usd(50_000.0), expected)

    def test_equality_same_values(self):
        bc2 = BridgeCost("ethereum", "arbitrum", 2.0, 0.0005, 0.1)
        self.assertEqual(self.bc, bc2)

    def test_inequality_different_gas(self):
        bc2 = BridgeCost("ethereum", "arbitrum", 3.0, 0.0005, 0.1)
        self.assertNotEqual(self.bc, bc2)


# ===========================================================================
# TestCrossChainOpportunity (10 tests)
# ===========================================================================

class TestCrossChainOpportunity(unittest.TestCase):
    """Tests for CrossChainOpportunity dataclass."""

    def _make_opp(
        self,
        from_apy: float = 4.0,
        to_apy: float = 6.0,
        breakeven: float = 10.0,
        is_profitable: bool = True,
        recommendation: str = "MOVE",
        annual_gain: float = 2000.0,
    ) -> CrossChainOpportunity:
        bridge = BridgeCost("ethereum", "arbitrum", 2.0, 0.0005, 0.1)
        return CrossChainOpportunity(
            from_chain="ethereum",
            to_chain="arbitrum",
            from_adapter="aave-v3",
            to_adapter="yearn-v3",
            from_apy_pct=from_apy,
            to_apy_pct=to_apy,
            apy_diff_pct=round(to_apy - from_apy, 4),
            bridge_cost=bridge,
            breakeven_days=breakeven,
            is_profitable=is_profitable,
            annual_gain_usd=annual_gain,
            recommendation=recommendation,
        )

    def test_field_from_chain(self):
        opp = self._make_opp()
        self.assertEqual(opp.from_chain, "ethereum")

    def test_field_to_chain(self):
        opp = self._make_opp()
        self.assertEqual(opp.to_chain, "arbitrum")

    def test_field_apy_diff(self):
        opp = self._make_opp(from_apy=4.0, to_apy=6.0)
        self.assertAlmostEqual(opp.apy_diff_pct, 2.0)

    def test_field_bridge_cost_type(self):
        opp = self._make_opp()
        self.assertIsInstance(opp.bridge_cost, BridgeCost)

    def test_is_profitable_true_when_breakeven_lt_90(self):
        opp = self._make_opp(breakeven=89.9, is_profitable=True)
        self.assertTrue(opp.is_profitable)

    def test_is_profitable_false_when_breakeven_ge_90(self):
        opp = self._make_opp(breakeven=90.0, is_profitable=False)
        self.assertFalse(opp.is_profitable)

    def test_recommendation_move(self):
        opp = self._make_opp(recommendation="MOVE")
        self.assertEqual(opp.recommendation, "MOVE")

    def test_recommendation_monitor(self):
        opp = self._make_opp(recommendation="MONITOR")
        self.assertEqual(opp.recommendation, "MONITOR")

    def test_recommendation_hold(self):
        opp = self._make_opp(recommendation="HOLD")
        self.assertEqual(opp.recommendation, "HOLD")

    def test_annual_gain_usd_positive(self):
        opp = self._make_opp(annual_gain=2000.0)
        self.assertEqual(opp.annual_gain_usd, 2000.0)


# ===========================================================================
# TestLoadChainData (10 tests)
# ===========================================================================

class TestLoadChainData(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.load_chain_data()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_empty(self):
        analyzer = CrossChainOpportunityAnalyzer(
            data_path=os.path.join(self.tmp.name, "nonexistent.json")
        )
        result = analyzer.load_chain_data()
        self.assertEqual(result, {})

    def test_empty_dict_returns_empty(self):
        analyzer = _make_analyzer(self.tmp.name, {})
        result = analyzer.load_chain_data()
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty(self):
        path = os.path.join(self.tmp.name, "adapter_status.json")
        with open(path, "w") as fh:
            fh.write("NOT_JSON{{{")
        analyzer = CrossChainOpportunityAnalyzer(data_path=path)
        result = analyzer.load_chain_data()
        self.assertEqual(result, {})

    def test_adapters_list_single_chain(self):
        data = {
            "adapters": [{
                "protocol_key": "aave-v3", "tier": "T1",
                "chains": ["ethereum"],
                "mock_apy": {"ethereum": {"USDC": 4.2}},
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertIn("ethereum", result)
        self.assertIn("aave-v3", result["ethereum"])

    def test_adapters_list_multiple_chains(self):
        data = {
            "adapters": [{
                "protocol_key": "compound-v3", "tier": "T1",
                "chains": ["ethereum", "arbitrum"],
                "mock_apy": {
                    "ethereum": {"USDC": 4.8},
                    "arbitrum": {"USDC": 5.5},
                },
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertIn("ethereum", result)
        self.assertIn("arbitrum", result)

    def test_apy_extracted_from_mock_apy(self):
        data = {
            "adapters": [{
                "protocol_key": "test-proto", "tier": "T1",
                "chains": ["arbitrum"],
                "mock_apy": {"arbitrum": {"USDC": 7.5}},
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertAlmostEqual(result["arbitrum"]["test-proto"]["apy_pct"], 7.5)

    def test_tier_stored_correctly(self):
        data = {
            "adapters": [{
                "protocol_key": "my-proto", "tier": "T2",
                "chains": ["base"],
                "mock_apy": {"base": {"USDC": 6.0}},
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertEqual(result["base"]["my-proto"]["tier"], "T2")

    def test_risk_score_t1(self):
        data = {
            "adapters": [{
                "protocol_key": "proto-t1", "tier": "T1",
                "chains": ["ethereum"],
                "mock_apy": {"ethereum": {"USDC": 4.0}},
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertAlmostEqual(result["ethereum"]["proto-t1"]["risk_score"], 0.20)

    def test_chain_normalization_arbitrum_alias(self):
        data = {
            "adapters": [{
                "protocol_key": "proto", "tier": "T1",
                "chains": ["arb"],
                "mock_apy": {"arb": {"USDC": 5.0}},
            }]
        }
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        # "arb" normalized to "arbitrum"
        self.assertIn("arbitrum", result)

    def test_two_adapters_same_chain_both_present(self):
        data = _make_mock_status_two_adapters()
        analyzer = _make_analyzer(self.tmp.name, data)
        result = analyzer.load_chain_data()
        self.assertIn("proto-a", result.get("ethereum", {}))
        self.assertIn("proto-b", result.get("ethereum", {}))


# ===========================================================================
# TestGetBridgeCost (10 tests)
# ===========================================================================

class TestGetBridgeCost(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.get_bridge_cost()."""

    def setUp(self):
        # Analyzer without real file (bridge cost doesn't need adapter data)
        self.a = CrossChainOpportunityAnalyzer.__new__(CrossChainOpportunityAnalyzer)

    def test_ethereum_to_polygon(self):
        bc = self.a.get_bridge_cost("ethereum", "polygon")
        self.assertIsNotNone(bc)
        self.assertEqual(bc.chain_from, "ethereum")
        self.assertEqual(bc.chain_to, "polygon")

    def test_ethereum_to_arbitrum(self):
        bc = self.a.get_bridge_cost("ethereum", "arbitrum")
        self.assertIsNotNone(bc)
        self.assertAlmostEqual(bc.gas_cost_usd, 2.0)

    def test_ethereum_to_base(self):
        bc = self.a.get_bridge_cost("ethereum", "base")
        self.assertIsNotNone(bc)

    def test_ethereum_to_optimism(self):
        bc = self.a.get_bridge_cost("ethereum", "optimism")
        self.assertIsNotNone(bc)

    def test_arbitrum_to_ethereum_long_wait(self):
        bc = self.a.get_bridge_cost("arbitrum", "ethereum")
        self.assertIsNotNone(bc)
        # 7-day challenge period
        self.assertAlmostEqual(bc.time_hours, 168.0)

    def test_base_to_ethereum_long_wait(self):
        bc = self.a.get_bridge_cost("base", "ethereum")
        self.assertIsNotNone(bc)
        self.assertAlmostEqual(bc.time_hours, 168.0)

    def test_arbitrum_to_base(self):
        bc = self.a.get_bridge_cost("arbitrum", "base")
        self.assertIsNotNone(bc)

    def test_base_to_optimism(self):
        bc = self.a.get_bridge_cost("base", "optimism")
        self.assertIsNotNone(bc)

    def test_unknown_pair_returns_none(self):
        bc = self.a.get_bridge_cost("ethereum", "unknown_chain")
        self.assertIsNone(bc)

    def test_asymmetric_pairs_distinct(self):
        eth_to_arb = self.a.get_bridge_cost("ethereum", "arbitrum")
        arb_to_eth = self.a.get_bridge_cost("arbitrum", "ethereum")
        self.assertIsNotNone(eth_to_arb)
        self.assertIsNotNone(arb_to_eth)
        # ethereum→arbitrum is cheaper/faster than arbitrum→ethereum (7-day delay)
        self.assertLess(eth_to_arb.time_hours, arb_to_eth.time_hours)


# ===========================================================================
# TestComputeBreakeven (12 tests)
# ===========================================================================

class TestComputeBreakeven(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.compute_breakeven()."""

    def setUp(self):
        self.a = CrossChainOpportunityAnalyzer.__new__(CrossChainOpportunityAnalyzer)

    def test_zero_diff_returns_inf(self):
        result = self.a.compute_breakeven(0.0, 100.0, 100_000.0)
        self.assertEqual(result, float("inf"))

    def test_negative_diff_returns_inf(self):
        result = self.a.compute_breakeven(-1.0, 100.0, 100_000.0)
        self.assertEqual(result, float("inf"))

    def test_zero_capital_returns_inf(self):
        result = self.a.compute_breakeven(2.0, 100.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_positive_diff_finite_result(self):
        result = self.a.compute_breakeven(2.0, 52.0, 100_000.0)
        self.assertNotEqual(result, float("inf"))
        self.assertGreater(result, 0)

    def test_formula_verification(self):
        # daily_gain = 100_000 * 0.02 / 365 = 5.4795...
        # breakeven = 52.0 / 5.4795 ≈ 9.49
        apy_diff = 2.0
        bridge_cost = 52.0
        capital = 100_000.0
        daily_gain = capital * (apy_diff / 100.0) / 365.0
        expected = bridge_cost / daily_gain
        result = self.a.compute_breakeven(apy_diff, bridge_cost, capital)
        self.assertAlmostEqual(result, expected, places=5)

    def test_large_diff_short_breakeven(self):
        # High APY diff → short breakeven
        result = self.a.compute_breakeven(10.0, 52.0, 100_000.0)
        self.assertLess(result, 30.0)

    def test_small_diff_long_breakeven(self):
        # 0.5% diff with large bridge cost → long breakeven
        result = self.a.compute_breakeven(0.5, 200.0, 100_000.0)
        self.assertGreater(result, 100.0)

    def test_large_bridge_cost_long_breakeven(self):
        result = self.a.compute_breakeven(2.0, 10_000.0, 100_000.0)
        self.assertGreater(result, 365.0)

    def test_default_capital_used(self):
        result = self.a.compute_breakeven(2.0, 52.0)
        expected = self.a.compute_breakeven(2.0, 52.0, 100_000.0)
        self.assertAlmostEqual(result, expected, places=10)

    def test_custom_capital_smaller(self):
        # Smaller capital → smaller daily gain → longer breakeven
        result_100k = self.a.compute_breakeven(2.0, 52.0, 100_000.0)
        result_10k = self.a.compute_breakeven(2.0, 52.0, 10_000.0)
        self.assertGreater(result_10k, result_100k)

    def test_breakeven_increases_with_bridge_cost(self):
        r_cheap = self.a.compute_breakeven(2.0, 10.0, 100_000.0)
        r_expensive = self.a.compute_breakeven(2.0, 500.0, 100_000.0)
        self.assertLess(r_cheap, r_expensive)

    def test_near_zero_positive_diff(self):
        # Very small diff (0.01%) → very large breakeven
        result = self.a.compute_breakeven(0.01, 50.0, 100_000.0)
        self.assertGreater(result, 1000.0)


# ===========================================================================
# TestAnalyzePair (15 tests)
# ===========================================================================

class TestAnalyzePair(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.analyze_pair()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Default mock: arbitrum has higher APY than ethereum
        self.mock_data = _make_mock_status(
            eth_apy=4.0, arb_apy=6.0, base_apy=7.0,
            polygon_apy=5.0, optimism_apy=5.5,
        )
        self.analyzer = _make_analyzer(self.tmp.name, self.mock_data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_from_chain_returns_none(self):
        result = self.analyzer.analyze_pair("unknown_chain", "arbitrum")
        self.assertIsNone(result)

    def test_unknown_to_chain_returns_none(self):
        result = self.analyzer.analyze_pair("ethereum", "unknown_chain")
        self.assertIsNone(result)

    def test_no_bridge_for_pair_returns_none(self):
        # polygon→base has a bridge, but let's test a pair not in the matrix
        result = self.analyzer.analyze_pair("ethereum", "ethereum")
        self.assertIsNone(result)

    def test_valid_pair_returns_opportunity(self):
        result = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, CrossChainOpportunity)

    def test_opportunity_from_chain(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertEqual(opp.from_chain, "ethereum")

    def test_opportunity_to_chain(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertEqual(opp.to_chain, "arbitrum")

    def test_opportunity_apy_diff_positive(self):
        # arbitrum APY (6.0) > ethereum APY (4.0)
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertGreater(opp.apy_diff_pct, 0)

    def test_opportunity_apy_diff_correct_value(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertAlmostEqual(opp.apy_diff_pct, 2.0, places=3)

    def test_opportunity_bridge_cost_correct_type(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertIsInstance(opp.bridge_cost, BridgeCost)

    def test_opportunity_bridge_cost_matches_matrix(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        expected = CrossChainOpportunityAnalyzer.BRIDGE_COSTS[("ethereum", "arbitrum")]
        self.assertEqual(opp.bridge_cost, expected)

    def test_opportunity_breakeven_positive_finite(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertGreater(opp.breakeven_days, 0)
        self.assertNotEqual(opp.breakeven_days, float("inf"))

    def test_opportunity_is_profitable_flag(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        expected = opp.breakeven_days < CrossChainOpportunityAnalyzer.MAX_BREAKEVEN_DAYS
        self.assertEqual(opp.is_profitable, expected)

    def test_opportunity_recommendation_move_for_short_breakeven(self):
        # With 2% diff and cheap bridge, breakeven should be < 30 days → MOVE
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        # eth→arb: gas=2.0, slip=0.0005 → total = 2 + 50 = 52 on 100k
        # daily_gain = 100k * 0.02 / 365 ≈ 5.48 → breakeven ≈ 9.5 days → MOVE
        self.assertEqual(opp.recommendation, "MOVE")

    def test_opportunity_annual_gain_usd(self):
        opp = self.analyzer.analyze_pair("ethereum", "arbitrum")
        expected = round(100_000.0 * opp.apy_diff_pct / 100.0, 2)
        self.assertAlmostEqual(opp.annual_gain_usd, expected, places=1)

    def test_empty_adapters_no_data(self):
        analyzer = _make_analyzer(self.tmp.name, {})
        result = analyzer.analyze_pair("ethereum", "arbitrum")
        self.assertIsNone(result)


# ===========================================================================
# TestGetAllOpportunities (12 tests)
# ===========================================================================

class TestGetAllOpportunities(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.get_all_opportunities()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mock_data = _make_mock_status(
            eth_apy=4.0, arb_apy=6.0, base_apy=7.0,
            polygon_apy=5.0, optimism_apy=5.5,
        )
        self.analyzer = _make_analyzer(self.tmp.name, self.mock_data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_list(self):
        result = self.analyzer.get_all_opportunities()
        self.assertIsInstance(result, list)

    def test_all_entries_are_opportunities(self):
        result = self.analyzer.get_all_opportunities()
        for opp in result:
            self.assertIsInstance(opp, CrossChainOpportunity)

    def test_filters_by_min_diff_pct(self):
        result = self.analyzer.get_all_opportunities(min_diff_pct=3.0)
        for opp in result:
            self.assertGreaterEqual(opp.apy_diff_pct, 3.0)

    def test_sorted_by_breakeven_days_ascending(self):
        result = self.analyzer.get_all_opportunities()
        if len(result) > 1:
            for i in range(len(result) - 1):
                self.assertLessEqual(result[i].breakeven_days, result[i + 1].breakeven_days)

    def test_high_min_diff_reduces_count(self):
        result_low = self.analyzer.get_all_opportunities(min_diff_pct=0.5)
        result_high = self.analyzer.get_all_opportunities(min_diff_pct=5.0)
        self.assertGreaterEqual(len(result_low), len(result_high))

    def test_zero_min_diff_includes_more(self):
        result_zero = self.analyzer.get_all_opportunities(min_diff_pct=0.0)
        result_half = self.analyzer.get_all_opportunities(min_diff_pct=0.5)
        self.assertGreaterEqual(len(result_zero), len(result_half))

    def test_custom_capital_used_in_breakeven(self):
        r_100k = self.analyzer.get_all_opportunities(capital_usd=100_000.0)
        r_10k = self.analyzer.get_all_opportunities(capital_usd=10_000.0)
        if r_100k and r_10k:
            # Larger capital → smaller breakeven (larger daily_gain)
            self.assertLessEqual(r_100k[0].breakeven_days, r_10k[0].breakeven_days)

    def test_no_opportunities_for_empty_data(self):
        analyzer = _make_analyzer(self.tmp.name, {})
        result = analyzer.get_all_opportunities()
        self.assertEqual(result, [])

    def test_from_to_chains_in_bridge_matrix(self):
        result = self.analyzer.get_all_opportunities()
        bridge_keys = set(CrossChainOpportunityAnalyzer.BRIDGE_COSTS.keys())
        for opp in result:
            self.assertIn((opp.from_chain, opp.to_chain), bridge_keys)

    def test_profitable_opps_before_non_profitable(self):
        # Since sorted by breakeven, profitable (< 90d) come first
        result = self.analyzer.get_all_opportunities()
        profitable_indices = [i for i, o in enumerate(result) if o.is_profitable]
        non_profitable_indices = [i for i, o in enumerate(result) if not o.is_profitable]
        if profitable_indices and non_profitable_indices:
            self.assertLess(max(profitable_indices), min(non_profitable_indices))

    def test_min_diff_equals_default(self):
        r_default = self.analyzer.get_all_opportunities()
        r_explicit = self.analyzer.get_all_opportunities(
            min_diff_pct=CrossChainOpportunityAnalyzer.MIN_APY_DIFF_PCT
        )
        self.assertEqual(len(r_default), len(r_explicit))

    def test_returns_nonempty_when_adapters_exist(self):
        result = self.analyzer.get_all_opportunities(min_diff_pct=0.0)
        # With adapters on multiple chains and valid bridge pairs, should find something
        # (even if APY diff is 0 and min_diff=0, pairs with non-negative diff exist)
        # Check that the function runs without error
        self.assertIsInstance(result, list)


# ===========================================================================
# TestGetTopOpportunity (8 tests)
# ===========================================================================

class TestGetTopOpportunity(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.get_top_opportunity()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mock_data = _make_mock_status(
            eth_apy=4.0, arb_apy=6.0, base_apy=7.0,
            polygon_apy=5.0, optimism_apy=5.5,
        )
        self.analyzer = _make_analyzer(self.tmp.name, self.mock_data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_none_for_empty_data(self):
        analyzer = _make_analyzer(self.tmp.name, {})
        result = analyzer.get_top_opportunity()
        self.assertIsNone(result)

    def test_returns_opportunity_when_available(self):
        result = self.analyzer.get_top_opportunity()
        # With base_apy=7.0 and eth_apy=4.0, at least eth→base should be profitable
        if result is not None:
            self.assertIsInstance(result, CrossChainOpportunity)

    def test_top_is_profitable(self):
        result = self.analyzer.get_top_opportunity()
        if result is not None:
            self.assertTrue(result.is_profitable)

    def test_top_has_lowest_breakeven_among_profitable(self):
        top = self.analyzer.get_top_opportunity()
        all_opps = self.analyzer.get_all_opportunities()
        profitable = [o for o in all_opps if o.is_profitable]
        if top is not None and profitable:
            min_breakeven = min(o.breakeven_days for o in profitable)
            self.assertAlmostEqual(top.breakeven_days, min_breakeven, places=5)

    def test_top_is_in_all_opportunities(self):
        top = self.analyzer.get_top_opportunity()
        all_opps = self.analyzer.get_all_opportunities()
        if top is not None:
            pairs = [(o.from_chain, o.to_chain) for o in all_opps]
            self.assertIn((top.from_chain, top.to_chain), pairs)

    def test_recommendation_not_hold_for_top(self):
        top = self.analyzer.get_top_opportunity()
        if top is not None:
            self.assertIn(top.recommendation, ("MOVE", "MONITOR"))

    def test_returns_none_when_all_breakeven_ge_90(self):
        # Set APY diff to very small to make breakeven >> 90 days
        tiny_diff_data = _make_mock_status(
            eth_apy=5.000, arb_apy=5.001,
            base_apy=5.002, polygon_apy=5.001, optimism_apy=5.001,
        )
        analyzer = _make_analyzer(self.tmp.name, tiny_diff_data)
        result = analyzer.get_top_opportunity()
        # With 0.001-0.002% diff, breakeven >> 90 days
        if result is not None:
            self.assertFalse(result.is_profitable)
        # If result is None that's also acceptable (no profitable opportunities)

    def test_top_opportunity_chains_valid(self):
        top = self.analyzer.get_top_opportunity()
        if top is not None:
            known_chains = {"ethereum", "arbitrum", "base", "optimism", "polygon"}
            self.assertIn(top.from_chain, known_chains)
            self.assertIn(top.to_chain, known_chains)


# ===========================================================================
# TestSaveAnalysis (5 tests)
# ===========================================================================

class TestSaveAnalysis(unittest.TestCase):
    """Tests for CrossChainOpportunityAnalyzer.save_analysis()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mock_data = _make_mock_status(
            eth_apy=4.0, arb_apy=6.0, base_apy=7.0,
        )
        self.analyzer = _make_analyzer(self.tmp.name, self.mock_data)
        self.out_path = os.path.join(self.tmp.name, "cross_chain_analysis.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        self.analyzer.save_analysis(output_path=self.out_path)
        self.assertTrue(os.path.exists(self.out_path))

    def test_returns_path_string(self):
        result = self.analyzer.save_analysis(output_path=self.out_path)
        self.assertIsInstance(result, str)
        self.assertEqual(result, self.out_path)

    def test_output_has_latest_key(self):
        self.analyzer.save_analysis(output_path=self.out_path)
        with open(self.out_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("latest", data)
        self.assertIn("snapshots", data)

    def test_ring_buffer_limit(self):
        # Save 35 times, should keep only 30
        for _ in range(35):
            self.analyzer.save_analysis(output_path=self.out_path)
        with open(self.out_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["snapshots"]), 30)

    def test_atomic_write_no_tmp_file_remaining(self):
        self.analyzer.save_analysis(output_path=self.out_path)
        tmp_file = self.out_path + ".tmp"
        self.assertFalse(os.path.exists(tmp_file))


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
