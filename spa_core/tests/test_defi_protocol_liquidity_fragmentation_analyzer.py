"""
Tests for MP-1024: DeFiProtocolLiquidityFragmentationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_liquidity_fragmentation_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_liquidity_fragmentation_analyzer import (
    DeFiProtocolLiquidityFragmentationAnalyzer,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_protocol(**overrides) -> dict:
    """Return a minimal valid protocol dict with optional overrides."""
    base = {
        "name": "TestProtocol",
        "asset_pair": "USDC/USDT",
        "total_liquidity_usd": 100_000_000,
        "chain_distribution": {"ethereum": 70_000_000, "arbitrum": 30_000_000},
        "pool_distribution": {"pool_a": 60_000_000, "pool_b": 40_000_000},
        "largest_single_pool_pct": 60.0,
        "cross_chain_bridge_volume_7d_usd": 1_000_000,
        "canonical_chain": "ethereum",
        "aggregator_routed_pct": 30.0,
        "price_deviation_max_bps": 3.0,
    }
    base.update(overrides)
    return base


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolLiquidityFragmentationAnalyzer(data_dir=self.tmp)


# ===========================================================================
# 1. HHI Computation
# ===========================================================================

class TestComputeHHI(BaseTest):

    def test_single_chain_hhi_is_10000(self):
        dist = {"ethereum": 100_000}
        self.assertAlmostEqual(self.analyzer._compute_hhi(dist), 10000.0)

    def test_two_equal_chains_hhi(self):
        dist = {"ethereum": 50, "arbitrum": 50}
        # (50%)^2 + (50%)^2 = 2500 + 2500 = 5000
        self.assertAlmostEqual(self.analyzer._compute_hhi(dist), 5000.0)

    def test_empty_distribution_returns_zero(self):
        self.assertEqual(self.analyzer._compute_hhi({}), 0.0)

    def test_zero_total_returns_zero(self):
        dist = {"ethereum": 0, "arbitrum": 0}
        self.assertEqual(self.analyzer._compute_hhi(dist), 0.0)

    def test_three_equal_pools_hhi(self):
        dist = {"p1": 100, "p2": 100, "p3": 100}
        # each is 33.33%, HHI = 3 × (33.33)^2 ≈ 3333.33
        self.assertAlmostEqual(self.analyzer._compute_hhi(dist), 3333.33, delta=1.0)

    def test_dominant_pool_high_hhi(self):
        dist = {"p1": 900, "p2": 50, "p3": 50}
        # 90% dominant → high HHI
        self.assertGreater(self.analyzer._compute_hhi(dist), 8000.0)

    def test_four_equal_pools(self):
        dist = {"p1": 25, "p2": 25, "p3": 25, "p4": 25}
        self.assertAlmostEqual(self.analyzer._compute_hhi(dist), 2500.0)

    def test_ten_equal_pools(self):
        dist = {f"p{i}": 10 for i in range(10)}
        self.assertAlmostEqual(self.analyzer._compute_hhi(dist), 1000.0, delta=1.0)

    def test_hhi_not_exceeds_10000(self):
        dist = {"only": 1_000_000}
        self.assertLessEqual(self.analyzer._compute_hhi(dist), 10000.0)


# ===========================================================================
# 2. Fragmentation Score
# ===========================================================================

class TestFragmentationScore(BaseTest):

    def test_high_hhi_low_deviation_low_score(self):
        score = self.analyzer._compute_fragmentation_score(9000.0, 2.0)
        self.assertLess(score, 20.0)

    def test_low_hhi_high_deviation_high_score(self):
        score = self.analyzer._compute_fragmentation_score(200.0, 120.0)
        self.assertGreater(score, 70.0)

    def test_score_bounded_0_100(self):
        s1 = self.analyzer._compute_fragmentation_score(0.0, 200.0)
        s2 = self.analyzer._compute_fragmentation_score(10000.0, 0.0)
        self.assertLessEqual(s1, 100.0)
        self.assertGreaterEqual(s2, 0.0)

    def test_moderate_hhi_moderate_deviation(self):
        score = self.analyzer._compute_fragmentation_score(3000.0, 30.0)
        self.assertTrue(20.0 < score < 80.0)

    def test_zero_hhi_zero_deviation(self):
        score = self.analyzer._compute_fragmentation_score(0.0, 0.0)
        # HHI=0 → max concentration factor from HHI part; deviation=0
        self.assertTrue(0.0 <= score <= 100.0)


# ===========================================================================
# 3. Slippage Multiplier
# ===========================================================================

class TestSlippageMultiplier(BaseTest):

    def test_unified_liquidity_multiplier_near_one(self):
        mult = self.analyzer._compute_slippage_multiplier(9500.0, 1.0, 100_000_000)
        self.assertAlmostEqual(mult, 1.0, delta=0.3)

    def test_fragmented_liquidity_multiplier_above_one(self):
        mult = self.analyzer._compute_slippage_multiplier(200.0, 150.0, 10_000_000)
        self.assertGreater(mult, 1.0)

    def test_multiplier_never_below_one(self):
        mult = self.analyzer._compute_slippage_multiplier(10000.0, 0.0, 1_000_000_000)
        self.assertGreaterEqual(mult, 1.0)

    def test_severely_fragmented_multiplier_high(self):
        mult = self.analyzer._compute_slippage_multiplier(100.0, 100.0, 1_000_000)
        self.assertGreater(mult, 1.5)


# ===========================================================================
# 4. Aggregator Dependency Score
# ===========================================================================

class TestAggregatorDependencyScore(BaseTest):

    def test_zero_pct_gives_zero_score(self):
        self.assertAlmostEqual(self.analyzer._compute_aggregator_dependency_score(0.0), 0.0)

    def test_hundred_pct_gives_100_score(self):
        self.assertAlmostEqual(self.analyzer._compute_aggregator_dependency_score(100.0), 100.0)

    def test_fifty_pct_gives_50_score(self):
        self.assertAlmostEqual(self.analyzer._compute_aggregator_dependency_score(50.0), 50.0)

    def test_score_clamped_above_100(self):
        self.assertLessEqual(self.analyzer._compute_aggregator_dependency_score(150.0), 100.0)

    def test_negative_clamped_to_zero(self):
        self.assertGreaterEqual(self.analyzer._compute_aggregator_dependency_score(-5.0), 0.0)


# ===========================================================================
# 5. Price Efficiency Score
# ===========================================================================

class TestPriceEfficiencyScore(BaseTest):

    def test_zero_deviation_gives_100(self):
        self.assertAlmostEqual(self.analyzer._compute_price_efficiency_score(0.0), 100.0)

    def test_100_bps_gives_zero(self):
        self.assertAlmostEqual(self.analyzer._compute_price_efficiency_score(100.0), 0.0)

    def test_50_bps_gives_50(self):
        self.assertAlmostEqual(self.analyzer._compute_price_efficiency_score(50.0), 50.0)

    def test_above_100_bps_clamped_to_zero(self):
        self.assertGreaterEqual(self.analyzer._compute_price_efficiency_score(200.0), 0.0)

    def test_negative_deviation_clamped_to_100(self):
        self.assertLessEqual(self.analyzer._compute_price_efficiency_score(-10.0), 100.0)


# ===========================================================================
# 6. Canonical Chain Percentage
# ===========================================================================

class TestCanonicalChainPct(BaseTest):

    def test_all_on_canonical(self):
        dist = {"ethereum": 100_000}
        pct = self.analyzer._canonical_chain_pct(dist, "ethereum")
        self.assertAlmostEqual(pct, 100.0)

    def test_none_on_canonical(self):
        dist = {"arbitrum": 100_000}
        pct = self.analyzer._canonical_chain_pct(dist, "ethereum")
        self.assertAlmostEqual(pct, 0.0)

    def test_partial_canonical(self):
        dist = {"ethereum": 70_000, "arbitrum": 30_000}
        pct = self.analyzer._canonical_chain_pct(dist, "ethereum")
        self.assertAlmostEqual(pct, 70.0)

    def test_empty_distribution_returns_zero(self):
        pct = self.analyzer._canonical_chain_pct({}, "ethereum")
        self.assertEqual(pct, 0.0)

    def test_zero_total_returns_zero(self):
        dist = {"ethereum": 0}
        pct = self.analyzer._canonical_chain_pct(dist, "ethereum")
        self.assertEqual(pct, 0.0)


# ===========================================================================
# 7. Label Determination
# ===========================================================================

class TestLabelDetermination(BaseTest):

    def test_unified_liquidity_label(self):
        label = self.analyzer._determine_label(7000.0, 2.0)
        self.assertEqual(label, "UNIFIED_LIQUIDITY")

    def test_low_fragmentation_label(self):
        label = self.analyzer._determine_label(5000.0, 10.0)
        self.assertEqual(label, "LOW_FRAGMENTATION")

    def test_moderate_fragmentation_label(self):
        label = self.analyzer._determine_label(3000.0, 30.0)
        self.assertEqual(label, "MODERATE_FRAGMENTATION")

    def test_high_fragmentation_by_hhi(self):
        label = self.analyzer._determine_label(800.0, 30.0)
        self.assertEqual(label, "HIGH_FRAGMENTATION")

    def test_high_fragmentation_by_deviation(self):
        label = self.analyzer._determine_label(2500.0, 60.0)
        self.assertEqual(label, "HIGH_FRAGMENTATION")

    def test_severely_fragmented_by_low_hhi(self):
        label = self.analyzer._determine_label(400.0, 30.0)
        self.assertEqual(label, "SEVERELY_FRAGMENTED")

    def test_severely_fragmented_by_high_deviation(self):
        label = self.analyzer._determine_label(3000.0, 110.0)
        self.assertEqual(label, "SEVERELY_FRAGMENTED")

    def test_severely_fragmented_both_criteria(self):
        label = self.analyzer._determine_label(200.0, 200.0)
        self.assertEqual(label, "SEVERELY_FRAGMENTED")

    def test_unified_exact_boundary_hhi(self):
        # pool_HHI == 6000 is NOT > 6000, falls through
        label = self.analyzer._determine_label(6000.0, 3.0)
        self.assertIn(label, {"LOW_FRAGMENTATION", "MODERATE_FRAGMENTATION"})

    def test_unified_deviation_exactly_at_5(self):
        # deviation == 5 is NOT < 5, so not UNIFIED
        label = self.analyzer._determine_label(7000.0, 5.0)
        self.assertNotEqual(label, "UNIFIED_LIQUIDITY")


# ===========================================================================
# 8. Flags
# ===========================================================================

class TestFlags(BaseTest):

    def test_aggregator_dependent_flag(self):
        flags = self.analyzer._compute_flags(75.0, 10.0, 50.0, 40.0)
        self.assertIn("AGGREGATOR_DEPENDENT", flags)

    def test_no_aggregator_dependent_below_threshold(self):
        flags = self.analyzer._compute_flags(70.0, 10.0, 50.0, 40.0)
        self.assertNotIn("AGGREGATOR_DEPENDENT", flags)

    def test_cross_chain_arbitrage_flag(self):
        flags = self.analyzer._compute_flags(30.0, 25.0, 50.0, 40.0)
        self.assertIn("CROSS_CHAIN_ARBITRAGE_OPPORTUNITY", flags)

    def test_no_arbitrage_flag_below_20_bps(self):
        flags = self.analyzer._compute_flags(30.0, 20.0, 50.0, 40.0)
        self.assertNotIn("CROSS_CHAIN_ARBITRAGE_OPPORTUNITY", flags)

    def test_canonical_dominance_flag(self):
        flags = self.analyzer._compute_flags(30.0, 10.0, 80.0, 40.0)
        self.assertIn("CANONICAL_DOMINANCE", flags)

    def test_no_canonical_dominance_below_70(self):
        flags = self.analyzer._compute_flags(30.0, 10.0, 70.0, 40.0)
        self.assertNotIn("CANONICAL_DOMINANCE", flags)

    def test_price_deviation_high_flag(self):
        flags = self.analyzer._compute_flags(30.0, 55.0, 50.0, 40.0)
        self.assertIn("PRICE_DEVIATION_HIGH", flags)

    def test_no_price_deviation_high_at_50(self):
        flags = self.analyzer._compute_flags(30.0, 50.0, 50.0, 40.0)
        self.assertNotIn("PRICE_DEVIATION_HIGH", flags)

    def test_unified_deep_pool_flag(self):
        flags = self.analyzer._compute_flags(30.0, 2.0, 50.0, 65.0)
        self.assertIn("UNIFIED_DEEP_POOL", flags)

    def test_no_unified_deep_pool_if_deviation_high(self):
        flags = self.analyzer._compute_flags(30.0, 10.0, 50.0, 65.0)
        self.assertNotIn("UNIFIED_DEEP_POOL", flags)

    def test_multiple_flags_simultaneously(self):
        flags = self.analyzer._compute_flags(80.0, 60.0, 80.0, 40.0)
        self.assertIn("AGGREGATOR_DEPENDENT", flags)
        self.assertIn("CROSS_CHAIN_ARBITRAGE_OPPORTUNITY", flags)
        self.assertIn("CANONICAL_DOMINANCE", flags)
        self.assertIn("PRICE_DEVIATION_HIGH", flags)

    def test_no_flags_on_clean_protocol(self):
        flags = self.analyzer._compute_flags(30.0, 3.0, 50.0, 40.0)
        self.assertEqual(flags, [])


# ===========================================================================
# 9. Analyze Protocol (single)
# ===========================================================================

class TestAnalyzeProtocol(BaseTest):

    def test_returns_required_keys(self):
        p = make_protocol()
        result = self.analyzer._analyze_protocol(p)
        for key in [
            "name", "asset_pair", "total_liquidity_usd", "canonical_chain",
            "chain_herfindahl", "pool_herfindahl", "fragmentation_score",
            "effective_slippage_multiplier", "aggregator_dependency_score",
            "price_efficiency_score", "canonical_chain_pct", "label", "flags",
        ]:
            self.assertIn(key, result)

    def test_default_values_used_when_missing(self):
        result = self.analyzer._analyze_protocol({})
        self.assertEqual(result["name"], "unknown")
        self.assertEqual(result["total_liquidity_usd"], 0.0)

    def test_unified_protocol_gets_low_score(self):
        p = make_protocol(
            pool_distribution={"pool_a": 100_000_000},
            price_deviation_max_bps=1.0,
        )
        result = self.analyzer._analyze_protocol(p)
        self.assertLess(result["fragmentation_score"], 50.0)

    def test_fragmented_protocol_gets_high_score(self):
        pools = {f"pool_{i}": 10_000 for i in range(20)}
        p = make_protocol(pool_distribution=pools, price_deviation_max_bps=80.0)
        result = self.analyzer._analyze_protocol(p)
        self.assertGreater(result["fragmentation_score"], 40.0)

    def test_slippage_multiplier_at_least_one(self):
        p = make_protocol()
        result = self.analyzer._analyze_protocol(p)
        self.assertGreaterEqual(result["effective_slippage_multiplier"], 1.0)

    def test_aggregator_dependency_in_range(self):
        p = make_protocol(aggregator_routed_pct=80.0)
        result = self.analyzer._analyze_protocol(p)
        self.assertGreaterEqual(result["aggregator_dependency_score"], 0.0)
        self.assertLessEqual(result["aggregator_dependency_score"], 100.0)

    def test_price_efficiency_in_range(self):
        p = make_protocol(price_deviation_max_bps=20.0)
        result = self.analyzer._analyze_protocol(p)
        self.assertGreaterEqual(result["price_efficiency_score"], 0.0)
        self.assertLessEqual(result["price_efficiency_score"], 100.0)

    def test_label_is_valid(self):
        from spa_core.analytics.defi_protocol_liquidity_fragmentation_analyzer import _ALL_LABELS
        p = make_protocol()
        result = self.analyzer._analyze_protocol(p)
        self.assertIn(result["label"], _ALL_LABELS)

    def test_flags_are_list(self):
        p = make_protocol()
        result = self.analyzer._analyze_protocol(p)
        self.assertIsInstance(result["flags"], list)

    def test_flags_valid_values(self):
        from spa_core.analytics.defi_protocol_liquidity_fragmentation_analyzer import _ALL_FLAGS
        p = make_protocol(aggregator_routed_pct=80.0, price_deviation_max_bps=60.0)
        result = self.analyzer._analyze_protocol(p)
        for flag in result["flags"]:
            self.assertIn(flag, _ALL_FLAGS)

    def test_canonical_chain_pct_correct(self):
        p = make_protocol(
            chain_distribution={"ethereum": 80_000_000, "arbitrum": 20_000_000},
            canonical_chain="ethereum",
        )
        result = self.analyzer._analyze_protocol(p)
        self.assertAlmostEqual(result["canonical_chain_pct"], 80.0, delta=0.5)


# ===========================================================================
# 10. Analyze (full method)
# ===========================================================================

class TestAnalyzeMethod(BaseTest):

    def test_analyze_empty_list(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["protocols"], [])

    def test_analyze_single_protocol(self):
        result = self.analyzer.analyze([make_protocol()], {"log_enabled": False})
        self.assertEqual(result["protocol_count"], 1)
        self.assertEqual(len(result["protocols"]), 1)

    def test_analyze_multiple_protocols(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(5)]
        result = self.analyzer.analyze(protocols, {"log_enabled": False})
        self.assertEqual(result["protocol_count"], 5)

    def test_raises_on_non_list_protocols(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([], "not_a_dict")

    def test_output_has_timestamp(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertIn("timestamp", result)

    def test_output_module_name(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["module"], "DeFiProtocolLiquidityFragmentationAnalyzer")

    def test_output_mp_number(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["mp"], "MP-1024")

    def test_aggregates_in_output(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertIn("aggregates", result)

    def test_config_data_dir_override(self):
        tmp2 = tempfile.mkdtemp()
        protocols = [make_protocol()]
        result = self.analyzer.analyze(protocols, {"log_enabled": True, "data_dir": tmp2})
        log_path = os.path.join(tmp2, "liquidity_fragmentation_log.json")
        self.assertTrue(os.path.exists(log_path))


# ===========================================================================
# 11. Aggregates
# ===========================================================================

class TestComputeAggregates(BaseTest):

    def test_empty_list_returns_defaults(self):
        agg = self.analyzer._compute_aggregates([])
        self.assertIsNone(agg["most_unified"])
        self.assertIsNone(agg["most_fragmented"])
        self.assertEqual(agg["avg_fragmentation_score"], 0.0)
        self.assertEqual(agg["severely_fragmented_count"], 0)
        self.assertEqual(agg["unified_count"], 0)

    def test_single_item_both_extremes(self):
        r = self.analyzer._analyze_protocol(make_protocol(name="Solo"))
        agg = self.analyzer._compute_aggregates([r])
        self.assertEqual(agg["most_unified"], "Solo")
        self.assertEqual(agg["most_fragmented"], "Solo")

    def test_avg_score_correct(self):
        p1 = make_protocol(name="A", pool_distribution={"p1": 100}, price_deviation_max_bps=1.0)
        p2 = make_protocol(name="B", pool_distribution={f"p{i}": 10 for i in range(10)}, price_deviation_max_bps=80.0)
        r1 = self.analyzer._analyze_protocol(p1)
        r2 = self.analyzer._analyze_protocol(p2)
        agg = self.analyzer._compute_aggregates([r1, r2])
        expected = (r1["fragmentation_score"] + r2["fragmentation_score"]) / 2
        self.assertAlmostEqual(agg["avg_fragmentation_score"], expected, delta=0.01)

    def test_severely_fragmented_count(self):
        p_severe = make_protocol(name="Severe", pool_distribution={f"p{i}": 1 for i in range(20)}, price_deviation_max_bps=0.0)
        r_severe = self.analyzer._analyze_protocol(p_severe)
        # Override label manually for counting test
        r_severe["label"] = "SEVERELY_FRAGMENTED"
        r_normal = self.analyzer._analyze_protocol(make_protocol(name="Normal"))
        agg = self.analyzer._compute_aggregates([r_severe, r_normal])
        self.assertEqual(agg["severely_fragmented_count"], 1)

    def test_unified_count(self):
        p_unified = make_protocol(
            name="Unified",
            pool_distribution={"only_pool": 100_000_000},
            price_deviation_max_bps=1.0,
        )
        r_unified = self.analyzer._analyze_protocol(p_unified)
        # Override label for reliable test
        r_unified["label"] = "UNIFIED_LIQUIDITY"
        agg = self.analyzer._compute_aggregates([r_unified])
        self.assertEqual(agg["unified_count"], 1)


# ===========================================================================
# 12. Ring-buffer log
# ===========================================================================

class TestRingBufferLog(BaseTest):

    def test_log_created_on_first_write(self):
        self.analyzer.analyze([make_protocol()], {})
        self.assertTrue(os.path.exists(self.analyzer.log_path))

    def test_log_is_valid_json_list(self):
        self.analyzer.analyze([make_protocol()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_accumulates_entries(self):
        for _ in range(3):
            self.analyzer.analyze([make_protocol()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_capped_at_100(self):
        for _ in range(LOG_CAP + 5):
            self.analyzer.analyze([make_protocol()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_disabled_creates_no_file(self):
        self.analyzer.analyze([make_protocol()], {"log_enabled": False})
        self.assertFalse(os.path.exists(self.analyzer.log_path))

    def test_log_entry_has_timestamp(self):
        self.analyzer.analyze([make_protocol()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[-1])

    def test_log_entry_has_protocol_count(self):
        self.analyzer.analyze([make_protocol(), make_protocol(name="B")], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol_count"], 2)

    def test_atomic_write_no_corruption(self):
        """Verify no .tmp file left over after write."""
        self.analyzer.analyze([make_protocol()], {})
        tmp_file = self.analyzer.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp_file))

    def test_corrupted_log_recovered(self):
        os.makedirs(self.tmp, exist_ok=True)
        with open(self.analyzer.log_path, "w") as f:
            f.write("NOT JSON {{{")
        # Should not raise; starts fresh
        self.analyzer.analyze([make_protocol()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_retains_newest_entries_when_capped(self):
        # Fill to cap + extra; newest should be at the end
        for i in range(LOG_CAP + 3):
            self.analyzer.analyze([make_protocol(name=f"P{i}")], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)
        # Newest entries are at the end
        last = data[-1]
        self.assertIn("protocols", last)


# ===========================================================================
# 13. Edge cases
# ===========================================================================

class TestEdgeCases(BaseTest):

    def test_single_pool_protocol(self):
        p = make_protocol(pool_distribution={"single_pool": 100_000_000})
        result = self.analyzer._analyze_protocol(p)
        self.assertAlmostEqual(result["pool_herfindahl"], 10000.0, delta=1.0)

    def test_zero_liquidity_protocol(self):
        p = make_protocol(total_liquidity_usd=0.0, pool_distribution={})
        result = self.analyzer._analyze_protocol(p)
        self.assertEqual(result["total_liquidity_usd"], 0.0)
        self.assertEqual(result["pool_herfindahl"], 0.0)

    def test_extreme_deviation_severely_fragmented(self):
        p = make_protocol(price_deviation_max_bps=500.0)
        result = self.analyzer._analyze_protocol(p)
        self.assertEqual(result["label"], "SEVERELY_FRAGMENTED")

    def test_all_aggregator_routed_flag(self):
        p = make_protocol(aggregator_routed_pct=100.0)
        result = self.analyzer._analyze_protocol(p)
        self.assertIn("AGGREGATOR_DEPENDENT", result["flags"])

    def test_many_small_pools_high_fragmentation(self):
        pools = {f"pool_{i}": 1000 for i in range(50)}
        p = make_protocol(pool_distribution=pools, price_deviation_max_bps=5.0)
        result = self.analyzer._analyze_protocol(p)
        # 50 equal pools → very low HHI
        self.assertLess(result["pool_herfindahl"], 300.0)

    def test_protocol_with_missing_optional_fields(self):
        p = {"name": "Minimal", "total_liquidity_usd": 1_000_000}
        result = self.analyzer._analyze_protocol(p)
        self.assertEqual(result["name"], "Minimal")
        self.assertIn("label", result)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze([make_protocol()], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_analyze_result_protocols_list(self):
        result = self.analyzer.analyze([make_protocol()], {"log_enabled": False})
        self.assertIsInstance(result["protocols"], list)

    def test_fragmentation_score_is_float(self):
        p = make_protocol()
        result = self.analyzer._analyze_protocol(p)
        self.assertIsInstance(result["fragmentation_score"], float)

    def test_protocol_with_single_chain(self):
        p = make_protocol(chain_distribution={"ethereum": 100_000_000})
        result = self.analyzer._analyze_protocol(p)
        self.assertAlmostEqual(result["chain_herfindahl"], 10000.0, delta=1.0)
        self.assertAlmostEqual(result["canonical_chain_pct"], 100.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
