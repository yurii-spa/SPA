"""
Tests for MP-923 ProtocolLiquidityFragmentationAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_liquidity_fragmentation_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_liquidity_fragmentation_analyzer import (
    ProtocolLiquidityFragmentationAnalyzer,
    _atomic_append_log,
    _compute_hhi,
    _fragmentation_label,
    _PRICE_DEVIATION_THRESHOLD_PCT,
    _CHAIN_FRAGMENTED_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(**kwargs):
    """Return a safe default pool dict, overridden by kwargs."""
    defaults = {
        "token_pair": "WETH/USDC",
        "dex": "Uniswap",
        "chain": "Ethereum",
        "tvl_usd": 10_000_000.0,
        "volume_24h_usd": 500_000.0,
        "fee_tier_pct": 0.05,
        "price_usd": 3800.0,
        "slippage_1k_usd": 0.005,
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer_with_tmplog():
    tmp_dir = tempfile.mkdtemp()
    log_path = os.path.join(tmp_dir, "frag_log.json")
    return ProtocolLiquidityFragmentationAnalyzer(log_path=log_path), log_path, tmp_dir


# ---------------------------------------------------------------------------
# 1. Module-level helpers
# ---------------------------------------------------------------------------

class TestComputeHHI(unittest.TestCase):

    def test_monopoly_returns_10000(self):
        self.assertAlmostEqual(_compute_hhi([100.0]), 10000.0)

    def test_duopoly_equal_split(self):
        # 50/50 → HHI = 50^2 + 50^2 = 5000
        self.assertAlmostEqual(_compute_hhi([50.0, 50.0]), 5000.0)

    def test_four_equal_players(self):
        # 25^2 * 4 = 2500
        self.assertAlmostEqual(_compute_hhi([25.0, 25.0, 25.0, 25.0]), 2500.0)

    def test_empty_list_returns_zero(self):
        self.assertEqual(_compute_hhi([]), 0.0)

    def test_single_zero_share(self):
        self.assertEqual(_compute_hhi([0.0]), 0.0)

    def test_asymmetric_split(self):
        # 80/20 → 6400 + 400 = 6800
        self.assertAlmostEqual(_compute_hhi([80.0, 20.0]), 6800.0)

    def test_hhi_increases_with_concentration(self):
        equal = _compute_hhi([33.33, 33.33, 33.33])
        dominant = _compute_hhi([80.0, 10.0, 10.0])
        self.assertGreater(dominant, equal)


class TestFragmentationLabel(unittest.TestCase):

    def test_unified(self):
        self.assertEqual(_fragmentation_label(0.0), "UNIFIED")

    def test_unified_boundary(self):
        self.assertEqual(_fragmentation_label(19.9), "UNIFIED")

    def test_slightly_fragmented(self):
        self.assertEqual(_fragmentation_label(20.0), "SLIGHTLY_FRAGMENTED")

    def test_slightly_fragmented_mid(self):
        self.assertEqual(_fragmentation_label(30.0), "SLIGHTLY_FRAGMENTED")

    def test_slightly_fragmented_boundary(self):
        self.assertEqual(_fragmentation_label(39.9), "SLIGHTLY_FRAGMENTED")

    def test_fragmented(self):
        self.assertEqual(_fragmentation_label(40.0), "FRAGMENTED")

    def test_fragmented_mid(self):
        self.assertEqual(_fragmentation_label(50.0), "FRAGMENTED")

    def test_fragmented_boundary(self):
        self.assertEqual(_fragmentation_label(59.9), "FRAGMENTED")

    def test_highly_fragmented(self):
        self.assertEqual(_fragmentation_label(60.0), "HIGHLY_FRAGMENTED")

    def test_highly_fragmented_mid(self):
        self.assertEqual(_fragmentation_label(70.0), "HIGHLY_FRAGMENTED")

    def test_highly_fragmented_boundary(self):
        self.assertEqual(_fragmentation_label(79.9), "HIGHLY_FRAGMENTED")

    def test_chaotic(self):
        self.assertEqual(_fragmentation_label(80.0), "CHAOTIC")

    def test_chaotic_max(self):
        self.assertEqual(_fragmentation_label(100.0), "CHAOTIC")


# ---------------------------------------------------------------------------
# 2. HHI by DEX
# ---------------------------------------------------------------------------

class TestHHIByDex(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_single_dex_monopoly(self):
        pools = [_make_pool(dex="Uniswap", tvl_usd=1000)]
        self.assertAlmostEqual(self.a.compute_hhi_by_dex(pools), 10000.0)

    def test_two_equal_dexes(self):
        pools = [
            _make_pool(dex="Uniswap", tvl_usd=1000),
            _make_pool(dex="Curve", tvl_usd=1000),
        ]
        self.assertAlmostEqual(self.a.compute_hhi_by_dex(pools), 5000.0)

    def test_empty_returns_zero(self):
        self.assertEqual(self.a.compute_hhi_by_dex([]), 0.0)

    def test_zero_tvl_returns_zero(self):
        pools = [_make_pool(dex="Uniswap", tvl_usd=0), _make_pool(dex="Curve", tvl_usd=0)]
        self.assertEqual(self.a.compute_hhi_by_dex(pools), 0.0)

    def test_dominant_dex_high_hhi(self):
        pools = [
            _make_pool(dex="Uniswap", tvl_usd=9000),
            _make_pool(dex="Curve", tvl_usd=1000),
        ]
        # 90/10 → 8100 + 100 = 8200
        self.assertAlmostEqual(self.a.compute_hhi_by_dex(pools), 8200.0)

    def test_four_equal_dexes(self):
        pools = [_make_pool(dex=f"DEX{i}", tvl_usd=2500) for i in range(4)]
        self.assertAlmostEqual(self.a.compute_hhi_by_dex(pools), 2500.0)

    def test_same_dex_different_pools_counts_once(self):
        # Two pools on same DEX → treated as 100% on that DEX
        pools = [
            _make_pool(dex="Uniswap", tvl_usd=500),
            _make_pool(dex="Uniswap", tvl_usd=500),
        ]
        self.assertAlmostEqual(self.a.compute_hhi_by_dex(pools), 10000.0)

    def test_negative_tvl_clamped(self):
        pools = [_make_pool(dex="Uniswap", tvl_usd=-100), _make_pool(dex="Curve", tvl_usd=1000)]
        hhi = self.a.compute_hhi_by_dex(pools)
        self.assertGreaterEqual(hhi, 0.0)
        self.assertLessEqual(hhi, 10000.0)


# ---------------------------------------------------------------------------
# 3. HHI by Chain
# ---------------------------------------------------------------------------

class TestHHIByChain(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_single_chain_monopoly(self):
        pools = [_make_pool(chain="Ethereum", tvl_usd=1000)]
        self.assertAlmostEqual(self.a.compute_hhi_by_chain(pools), 10000.0)

    def test_two_equal_chains(self):
        pools = [
            _make_pool(chain="Ethereum", tvl_usd=1000),
            _make_pool(chain="Arbitrum", tvl_usd=1000),
        ]
        self.assertAlmostEqual(self.a.compute_hhi_by_chain(pools), 5000.0)

    def test_empty_returns_zero(self):
        self.assertEqual(self.a.compute_hhi_by_chain([]), 0.0)

    def test_zero_tvl_returns_zero(self):
        pools = [_make_pool(chain="Ethereum", tvl_usd=0)]
        self.assertEqual(self.a.compute_hhi_by_chain(pools), 0.0)

    def test_dominant_chain_higher_hhi(self):
        pools = [
            _make_pool(chain="Ethereum", tvl_usd=8000),
            _make_pool(chain="Arbitrum", tvl_usd=1000),
            _make_pool(chain="Optimism", tvl_usd=1000),
        ]
        # 80/10/10 → 6400+100+100=6600
        self.assertAlmostEqual(self.a.compute_hhi_by_chain(pools), 6600.0)

    def test_more_chains_lower_hhi(self):
        two = [_make_pool(chain=f"C{i}", tvl_usd=500) for i in range(2)]
        six = [_make_pool(chain=f"C{i}", tvl_usd=500) for i in range(6)]
        self.assertGreater(
            self.a.compute_hhi_by_chain(two),
            self.a.compute_hhi_by_chain(six),
        )


# ---------------------------------------------------------------------------
# 4. Price deviation
# ---------------------------------------------------------------------------

class TestPriceDeviation(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_single_pool_zero_deviation(self):
        pools = [_make_pool(price_usd=3800)]
        self.assertEqual(self.a.compute_price_deviation_pct(pools), 0.0)

    def test_equal_prices_zero_deviation(self):
        pools = [_make_pool(price_usd=3800), _make_pool(price_usd=3800)]
        self.assertEqual(self.a.compute_price_deviation_pct(pools), 0.0)

    def test_1_percent_deviation(self):
        pools = [_make_pool(price_usd=100), _make_pool(price_usd=101)]
        dev = self.a.compute_price_deviation_pct(pools)
        self.assertAlmostEqual(dev, 1.0, places=4)

    def test_half_percent_deviation(self):
        pools = [_make_pool(price_usd=200), _make_pool(price_usd=201)]
        dev = self.a.compute_price_deviation_pct(pools)
        self.assertAlmostEqual(dev, 0.5, places=4)

    def test_zero_price_excluded(self):
        pools = [_make_pool(price_usd=0), _make_pool(price_usd=100)]
        dev = self.a.compute_price_deviation_pct(pools)
        # Only one valid price → 0 deviation
        self.assertEqual(dev, 0.0)

    def test_empty_pools_zero_deviation(self):
        self.assertEqual(self.a.compute_price_deviation_pct([]), 0.0)

    def test_three_prices_max_spread(self):
        pools = [
            _make_pool(price_usd=100),
            _make_pool(price_usd=105),
            _make_pool(price_usd=102),
        ]
        dev = self.a.compute_price_deviation_pct(pools)
        # (105 - 100) / 100 * 100 = 5%
        self.assertAlmostEqual(dev, 5.0, places=4)

    def test_deviation_is_always_non_negative(self):
        pools = [_make_pool(price_usd=200), _make_pool(price_usd=190)]
        dev = self.a.compute_price_deviation_pct(pools)
        self.assertGreaterEqual(dev, 0.0)


# ---------------------------------------------------------------------------
# 5. Fragmentation score
# ---------------------------------------------------------------------------

class TestFragmentationScore(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_monopoly_low_fragmentation(self):
        # One DEX, one chain → low fragmentation
        score = self.a.compute_fragmentation_score(10000, 10000, 1, 1)
        self.assertLess(score, 20.0)

    def test_full_fragmentation(self):
        # Zero HHI, many chains, many pools → high fragmentation
        score = self.a.compute_fragmentation_score(0, 0, 10, 20)
        self.assertGreater(score, 60.0)

    def test_score_bounded_0_to_100(self):
        for hhi in [0, 2500, 5000, 10000]:
            for chains in [1, 2, 5]:
                for pools in [1, 3, 10]:
                    s = self.a.compute_fragmentation_score(hhi, hhi, chains, pools)
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_more_chains_higher_score(self):
        s1 = self.a.compute_fragmentation_score(5000, 5000, 1, 3)
        s5 = self.a.compute_fragmentation_score(5000, 5000, 5, 3)
        self.assertGreater(s5, s1)

    def test_lower_hhi_higher_fragmentation(self):
        s_concentrated = self.a.compute_fragmentation_score(9000, 9000, 2, 3)
        s_distributed  = self.a.compute_fragmentation_score(1000, 1000, 2, 3)
        self.assertGreater(s_distributed, s_concentrated)

    def test_more_pools_higher_fragmentation(self):
        s3  = self.a.compute_fragmentation_score(5000, 5000, 2, 3)
        s20 = self.a.compute_fragmentation_score(5000, 5000, 2, 20)
        self.assertGreater(s20, s3)


# ---------------------------------------------------------------------------
# 6. Flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_no_flags_normal_case(self):
        pools = [
            _make_pool(dex="Uniswap", chain="Ethereum", tvl_usd=50_000, price_usd=100),
            _make_pool(dex="Curve",   chain="Ethereum", tvl_usd=30_000, price_usd=100),
            _make_pool(dex="Balancer",chain="Ethereum", tvl_usd=20_000, price_usd=100),
        ]
        flags = self.a.compute_flags(pools, 0.1, 4000)
        self.assertEqual(flags, [])

    def test_price_deviation_flag_above_threshold(self):
        pools = [_make_pool(price_usd=100), _make_pool(price_usd=102)]
        flags = self.a.compute_flags(pools, _PRICE_DEVIATION_THRESHOLD_PCT + 0.1, 10000)
        self.assertIn("PRICE_DEVIATION", flags)

    def test_price_deviation_flag_exactly_at_threshold_no_flag(self):
        pools = [_make_pool(price_usd=100)]
        flags = self.a.compute_flags(pools, _PRICE_DEVIATION_THRESHOLD_PCT, 10000)
        self.assertNotIn("PRICE_DEVIATION", flags)

    def test_chain_fragmented_flag_more_than_threshold_chains(self):
        pools = [_make_pool(chain=f"C{i}") for i in range(_CHAIN_FRAGMENTED_THRESHOLD + 1)]
        flags = self.a.compute_flags(pools, 0.1, 5000)
        self.assertIn("CHAIN_FRAGMENTED", flags)

    def test_chain_fragmented_at_threshold_no_flag(self):
        pools = [_make_pool(chain=f"C{i}") for i in range(_CHAIN_FRAGMENTED_THRESHOLD)]
        flags = self.a.compute_flags(pools, 0.1, 5000)
        self.assertNotIn("CHAIN_FRAGMENTED", flags)

    def test_dex_monopoly_flag_above_80_pct(self):
        pools = [
            _make_pool(dex="Uniswap", tvl_usd=9000),
            _make_pool(dex="Curve",   tvl_usd=1000),
        ]
        flags = self.a.compute_flags(pools, 0.1, 8200)
        self.assertIn("DEX_MONOPOLY", flags)

    def test_dex_monopoly_not_triggered_below_threshold(self):
        pools = [
            _make_pool(dex="Uniswap", tvl_usd=5000),
            _make_pool(dex="Curve",   tvl_usd=5000),
        ]
        flags = self.a.compute_flags(pools, 0.1, 5000)
        self.assertNotIn("DEX_MONOPOLY", flags)

    def test_low_cross_chain_bridge_flag(self):
        # One chain has <1% TVL
        pools = [
            _make_pool(chain="Ethereum", tvl_usd=99_000),
            _make_pool(chain="Arbitrum", tvl_usd=100),  # 0.1% of total
        ]
        flags = self.a.compute_flags(pools, 0.1, 9800)
        self.assertIn("LOW_CROSS_CHAIN_BRIDGE", flags)

    def test_low_cross_chain_bridge_not_single_chain(self):
        # Single chain → no bridge
        pools = [_make_pool(chain="Ethereum", tvl_usd=1000)]
        flags = self.a.compute_flags(pools, 0.1, 10000)
        self.assertNotIn("LOW_CROSS_CHAIN_BRIDGE", flags)

    def test_all_flags_triggered(self):
        # price_dev > 0.5%, >3 chains, one DEX >80%, one chain <1%
        pools = [
            _make_pool(dex="Uniswap", chain="Eth",  tvl_usd=90_000, price_usd=100),
            _make_pool(dex="Curve",   chain="Arb",  tvl_usd=9_000,  price_usd=101),
            _make_pool(dex="Balancer",chain="Opt",  tvl_usd=100,    price_usd=99),
            _make_pool(dex="Velodrome",chain="Base", tvl_usd=900,   price_usd=100.6),
        ]
        # DEX Uniswap = 90k/(109k) ≈ 82.6% → DEX_MONOPOLY
        # 4 chains > 3 → CHAIN_FRAGMENTED
        # Opt chain has 100/100000 = 0.1% → LOW_CROSS_CHAIN_BRIDGE
        flags = self.a.compute_flags(pools, 2.0, 7000)
        self.assertIn("PRICE_DEVIATION", flags)
        self.assertIn("CHAIN_FRAGMENTED", flags)
        self.assertIn("DEX_MONOPOLY", flags)
        self.assertIn("LOW_CROSS_CHAIN_BRIDGE", flags)

    def test_flags_returns_list(self):
        pools = [_make_pool()]
        self.assertIsInstance(self.a.compute_flags(pools, 0.0, 10000), list)


# ---------------------------------------------------------------------------
# 7. analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp = _make_analyzer_with_tmplog()

    def test_empty_returns_dict(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_empty_pairs_list(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertEqual(result["pairs"], [])

    def test_empty_aggregates_nulled(self):
        agg = self.a.analyze([], {"log_enabled": False})["aggregates"]
        self.assertIsNone(agg["most_fragmented_pair"])
        self.assertIsNone(agg["most_unified_pair"])
        self.assertEqual(agg["total_tvl"], 0.0)
        self.assertEqual(agg["average_fragmentation"], 0.0)
        self.assertEqual(agg["chaotic_count"], 0)

    def test_empty_has_timestamp(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIn("timestamp", result)


# ---------------------------------------------------------------------------
# 8. analyze() — single pool / single pair
# ---------------------------------------------------------------------------

class TestAnalyzeSinglePair(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp = _make_analyzer_with_tmplog()

    def test_single_pool_returns_one_pair(self):
        result = self.a.analyze([_make_pool()], {"log_enabled": False})
        self.assertEqual(len(result["pairs"]), 1)

    def test_single_pool_pair_name(self):
        result = self.a.analyze([_make_pool(token_pair="WBTC/USDC")], {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["token_pair"], "WBTC/USDC")

    def test_single_pool_monopoly_hhi(self):
        result = self.a.analyze([_make_pool(dex="Uniswap")], {"log_enabled": False})
        self.assertAlmostEqual(result["pairs"][0]["hhi_by_dex"], 10000.0)

    def test_single_pool_chain_hhi_monopoly(self):
        result = self.a.analyze([_make_pool(chain="Ethereum")], {"log_enabled": False})
        self.assertAlmostEqual(result["pairs"][0]["hhi_by_chain"], 10000.0)

    def test_single_pool_zero_price_deviation(self):
        result = self.a.analyze([_make_pool(price_usd=3800)], {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["price_deviation_pct"], 0.0)

    def test_single_pool_total_tvl(self):
        result = self.a.analyze([_make_pool(tvl_usd=5_000_000)], {"log_enabled": False})
        self.assertAlmostEqual(result["pairs"][0]["total_tvl_usd"], 5_000_000.0)

    def test_single_pool_dominant_pool(self):
        result = self.a.analyze([_make_pool(dex="Uniswap", chain="Ethereum")], {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["dominant_pool"], "Uniswap@Ethereum")

    def test_single_pool_best_execution(self):
        result = self.a.analyze([_make_pool(dex="Uniswap", chain="Ethereum", slippage_1k_usd=0.002)],
                                 {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["best_execution_pool"], "Uniswap@Ethereum")

    def test_single_pool_fragmentation_label_valid(self):
        result = self.a.analyze([_make_pool()], {"log_enabled": False})
        valid = {"UNIFIED", "SLIGHTLY_FRAGMENTED", "FRAGMENTED", "HIGHLY_FRAGMENTED", "CHAOTIC"}
        self.assertIn(result["pairs"][0]["fragmentation_label"], valid)

    def test_single_pair_most_fragmented_equals_most_unified(self):
        agg = self.a.analyze([_make_pool()], {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["most_fragmented_pair"], agg["most_unified_pair"])


# ---------------------------------------------------------------------------
# 9. analyze() — multiple pairs
# ---------------------------------------------------------------------------

class TestAnalyzeMultiplePairs(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp = _make_analyzer_with_tmplog()
        # Unified pair: all on one DEX/chain
        self.unified_pools = [
            _make_pool(token_pair="stETH/ETH", dex="Curve", chain="Ethereum",
                       tvl_usd=1_000_000, price_usd=0.9998),
        ]
        # Fragmented pair: many DEXes and chains
        self.frag_pools = [
            _make_pool(token_pair="WETH/USDC", dex="Uniswap", chain="Ethereum",
                       tvl_usd=400_000, price_usd=3800),
            _make_pool(token_pair="WETH/USDC", dex="Curve",   chain="Ethereum",
                       tvl_usd=200_000, price_usd=3801),
            _make_pool(token_pair="WETH/USDC", dex="SushiSwap", chain="Arbitrum",
                       tvl_usd=100_000, price_usd=3799),
            _make_pool(token_pair="WETH/USDC", dex="Velodrome", chain="Optimism",
                       tvl_usd=100_000, price_usd=3802),
            _make_pool(token_pair="WETH/USDC", dex="Aerodrome", chain="Base",
                       tvl_usd=200_000, price_usd=3798),
        ]
        self.all_pools = self.unified_pools + self.frag_pools

    def test_two_pairs_returned(self):
        result = self.a.analyze(self.all_pools, {"log_enabled": False})
        self.assertEqual(len(result["pairs"]), 2)

    def test_frag_pair_higher_score(self):
        result = self.a.analyze(self.all_pools, {"log_enabled": False})
        scores = {p["token_pair"]: p["fragmentation_score"] for p in result["pairs"]}
        self.assertGreater(scores["WETH/USDC"], scores["stETH/ETH"])

    def test_most_unified_is_steth(self):
        agg = self.a.analyze(self.all_pools, {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["most_unified_pair"], "stETH/ETH")

    def test_most_fragmented_is_weth(self):
        agg = self.a.analyze(self.all_pools, {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["most_fragmented_pair"], "WETH/USDC")

    def test_total_tvl_sum(self):
        agg = self.a.analyze(self.all_pools, {"log_enabled": False})["aggregates"]
        expected = 1_000_000 + 400_000 + 200_000 + 100_000 + 100_000 + 200_000
        self.assertAlmostEqual(agg["total_tvl"], expected, delta=1)

    def test_average_fragmentation_is_mean(self):
        result = self.a.analyze(self.all_pools, {"log_enabled": False})
        scores = [p["fragmentation_score"] for p in result["pairs"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["aggregates"]["average_fragmentation"], expected_avg, places=3)

    def test_chaotic_count_correct(self):
        agg = self.a.analyze(self.all_pools, {"log_enabled": False})["aggregates"]
        result = self.a.analyze(self.all_pools, {"log_enabled": False})
        chaotic_labels = [p for p in result["pairs"] if p["fragmentation_label"] == "CHAOTIC"]
        self.assertEqual(agg["chaotic_count"], len(chaotic_labels))

    def test_pool_count_per_pair(self):
        result = self.a.analyze(self.all_pools, {"log_enabled": False})
        counts = {p["token_pair"]: p["pool_count"] for p in result["pairs"]}
        self.assertEqual(counts["stETH/ETH"], 1)
        self.assertEqual(counts["WETH/USDC"], 5)


# ---------------------------------------------------------------------------
# 10. Best execution pool selection
# ---------------------------------------------------------------------------

class TestBestExecutionPool(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_lowest_slippage_selected(self):
        pools = [
            _make_pool(dex="Uniswap", chain="Eth", slippage_1k_usd=0.010),
            _make_pool(dex="Curve",   chain="Eth", slippage_1k_usd=0.002),
            _make_pool(dex="Balancer",chain="Eth", slippage_1k_usd=0.005),
        ]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["best_execution_pool"], "Curve@Eth")

    def test_tiebreak_by_tvl(self):
        pools = [
            _make_pool(dex="Uniswap", chain="Eth", slippage_1k_usd=0.005, tvl_usd=1000),
            _make_pool(dex="Curve",   chain="Eth", slippage_1k_usd=0.005, tvl_usd=9000),
        ]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["best_execution_pool"], "Curve@Eth")

    def test_dominant_pool_is_highest_tvl(self):
        pools = [
            _make_pool(dex="Uniswap", chain="Eth", tvl_usd=80_000),
            _make_pool(dex="Curve",   chain="Eth", tvl_usd=20_000),
        ]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["dominant_pool"], "Uniswap@Eth")


# ---------------------------------------------------------------------------
# 11. Logging behavior
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "frag_log.json")
        self.a = ProtocolLiquidityFragmentationAnalyzer(log_path=self.log_path)

    def _cfg(self, **kw):
        base = {"log_enabled": True, "log_path": self.log_path}
        base.update(kw)
        return base

    def test_log_file_created(self):
        self.a.analyze([_make_pool()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count_grows(self):
        for _ in range(4):
            self.a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_log_ring_buffer_capped(self):
        cap = 3
        a = ProtocolLiquidityFragmentationAnalyzer(log_path=self.log_path, log_cap=cap)
        for _ in range(7):
            a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), cap)

    def test_log_disabled_no_file(self):
        log_path = os.path.join(self.tmp_dir, "no_log.json")
        a = ProtocolLiquidityFragmentationAnalyzer(log_path=log_path)
        a.analyze([_make_pool()], {"log_enabled": False})
        self.assertFalse(os.path.exists(log_path))

    def test_log_entry_has_pairs_key(self):
        self.a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("pairs", data[0])

    def test_log_entry_has_aggregates_key(self):
        self.a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_entry_has_timestamp(self):
        self.a.analyze([_make_pool()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_atomic_log_helper_creates_file(self):
        path = os.path.join(self.tmp_dir, "direct.json")
        _atomic_append_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))

    def test_atomic_log_helper_ring_buffer(self):
        path = os.path.join(self.tmp_dir, "ring.json")
        for i in range(7):
            _atomic_append_log(path, {"i": i}, cap=4)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)
        self.assertEqual(data[-1]["i"], 6)

    def test_custom_log_path_via_config(self):
        custom = os.path.join(self.tmp_dir, "custom.json")
        self.a.analyze([_make_pool()], {"log_enabled": True, "log_path": custom})
        self.assertTrue(os.path.exists(custom))

    def test_log_default_enabled_when_missing_from_config(self):
        a = ProtocolLiquidityFragmentationAnalyzer(log_path=self.log_path)
        a.analyze([_make_pool()], {})  # no log_enabled key
        self.assertTrue(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# 12. Output structure validation
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()
        self.result = self.a.analyze(
            [
                _make_pool(token_pair="A/B"),
                _make_pool(token_pair="C/D"),
            ],
            {"log_enabled": False},
        )

    def test_top_level_keys(self):
        for k in ("pairs", "aggregates", "timestamp"):
            self.assertIn(k, self.result)

    def test_pair_keys(self):
        expected = {
            "token_pair", "pool_count", "total_tvl_usd", "hhi_by_dex",
            "hhi_by_chain", "dominant_pool", "fragmentation_score",
            "best_execution_pool", "price_deviation_pct", "fragmentation_label",
            "flags",
        }
        for pair in self.result["pairs"]:
            for k in expected:
                self.assertIn(k, pair, f"Missing key {k!r} in pair result")

    def test_aggregate_keys(self):
        expected = {
            "most_fragmented_pair", "most_unified_pair", "total_tvl",
            "average_fragmentation", "chaotic_count",
        }
        for k in expected:
            self.assertIn(k, self.result["aggregates"])

    def test_numeric_fields_are_floats(self):
        for pair in self.result["pairs"]:
            for k in ("total_tvl_usd", "hhi_by_dex", "hhi_by_chain",
                       "fragmentation_score", "price_deviation_pct"):
                self.assertIsInstance(pair[k], float, f"{k} should be float")

    def test_fragmentation_label_is_string(self):
        for pair in self.result["pairs"]:
            self.assertIsInstance(pair["fragmentation_label"], str)

    def test_flags_is_list(self):
        for pair in self.result["pairs"]:
            self.assertIsInstance(pair["flags"], list)

    def test_chaotic_count_is_int(self):
        self.assertIsInstance(self.result["aggregates"]["chaotic_count"], int)

    def test_pool_count_is_int(self):
        for pair in self.result["pairs"]:
            self.assertIsInstance(pair["pool_count"], int)

    def test_timestamp_is_string(self):
        self.assertIsInstance(self.result["timestamp"], str)


# ---------------------------------------------------------------------------
# 13. Edge cases and robustness
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = ProtocolLiquidityFragmentationAnalyzer()

    def test_all_pools_same_pair(self):
        pools = [_make_pool(token_pair="WETH/USDC", dex=f"DEX{i}", chain=f"C{i}")
                 for i in range(5)]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["pool_count"], 5)

    def test_many_pairs(self):
        pools = [_make_pool(token_pair=f"TOK{i}/USDC") for i in range(20)]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(len(result["pairs"]), 20)

    def test_missing_token_pair_defaults_to_unknown(self):
        pool = {"dex": "Uniswap", "chain": "Eth", "tvl_usd": 1000, "price_usd": 100}
        result = self.a.analyze([pool], {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["token_pair"], "UNKNOWN")

    def test_zero_tvl_all_pools(self):
        pools = [_make_pool(tvl_usd=0), _make_pool(tvl_usd=0)]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(result["aggregates"]["total_tvl"], 0.0)

    def test_very_large_tvl(self):
        pools = [_make_pool(tvl_usd=1e12)]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertAlmostEqual(result["aggregates"]["total_tvl"], 1e12, delta=1)

    def test_empty_string_pair_name(self):
        pools = [_make_pool(token_pair="")]
        result = self.a.analyze(pools, {"log_enabled": False})
        self.assertEqual(result["pairs"][0]["token_pair"], "")

    def test_pool_with_minimal_fields(self):
        result = self.a.analyze([{"token_pair": "X/Y"}], {"log_enabled": False})
        self.assertEqual(len(result["pairs"]), 1)

    def test_hhi_values_within_bounds_all_pairs(self):
        pools = [
            _make_pool(token_pair="A/B", dex="U1", chain="C1", tvl_usd=5000),
            _make_pool(token_pair="A/B", dex="U2", chain="C2", tvl_usd=5000),
            _make_pool(token_pair="C/D", dex="U1", chain="C1", tvl_usd=9000),
            _make_pool(token_pair="C/D", dex="U3", chain="C3", tvl_usd=1000),
        ]
        result = self.a.analyze(pools, {"log_enabled": False})
        for pair in result["pairs"]:
            self.assertGreaterEqual(pair["hhi_by_dex"], 0.0)
            self.assertLessEqual(pair["hhi_by_dex"], 10000.0)
            self.assertGreaterEqual(pair["hhi_by_chain"], 0.0)
            self.assertLessEqual(pair["hhi_by_chain"], 10000.0)

    def test_fragmentation_score_within_bounds_various(self):
        pools = [
            _make_pool(dex=f"DEX{i}", chain=f"C{i}", tvl_usd=1000)
            for i in range(8)
        ]
        result = self.a.analyze(pools, {"log_enabled": False})
        score = result["pairs"][0]["fragmentation_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


if __name__ == "__main__":
    unittest.main()
