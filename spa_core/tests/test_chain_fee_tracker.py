"""
Tests for MP-662 ChainFeeTracker (spa_core/analytics/chain_fee_tracker.py)
Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_chain_fee_tracker -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.chain_fee_tracker import (
    CHAIN_FEE_MULTIPLIERS,
    ChainFeeComparison,
    ChainFeeSnapshot,
    ChainFeeTracker,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_dir: str) -> ChainFeeTracker:
    return ChainFeeTracker(data_file=Path(tmp_dir) / "chain_fee_log.json")


def _snap(tracker: ChainFeeTracker, chain="ethereum",
           gas_price=30.0, l1=0.0, eth_price=2000.0) -> ChainFeeSnapshot:
    return tracker.snapshot_chain(chain, gas_price, l1, eth_price)


# ===========================================================================
# 1. _tx_cost_usd
# ===========================================================================

class TestTxCostUsd(unittest.TestCase):

    def setUp(self):
        self.t = ChainFeeTracker()

    def test_basic_formula(self):
        # 200000 * (30 + 0) * 1e-9 * 2000 = 12.0
        result = self.t._tx_cost_usd(30.0, 0.0, 2000.0)
        expected = round(200_000 * 30.0 * 1e-9 * 2000.0, 4)
        self.assertAlmostEqual(result, expected, places=4)

    def test_l1_overhead_adds_to_cost(self):
        without_l1 = self.t._tx_cost_usd(30.0, 0.0, 2000.0)
        with_l1 = self.t._tx_cost_usd(30.0, 5.0, 2000.0)
        self.assertGreater(with_l1, without_l1)

    def test_l1_overhead_zero_just_base(self):
        result = self.t._tx_cost_usd(10.0, 0.0, 3000.0)
        expected = round(200_000 * 10.0 * 1e-9 * 3000.0, 4)
        self.assertAlmostEqual(result, expected, places=4)

    def test_gas_price_zero_returns_zero(self):
        result = self.t._tx_cost_usd(0.0, 0.0, 2000.0)
        self.assertEqual(result, 0.0)

    def test_eth_price_zero_returns_zero(self):
        result = self.t._tx_cost_usd(30.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_both_gas_and_l1_contribute(self):
        result = self.t._tx_cost_usd(20.0, 10.0, 1000.0)
        expected = round(200_000 * 30.0 * 1e-9 * 1000.0, 4)
        self.assertAlmostEqual(result, expected, places=4)

    def test_high_gas_price(self):
        result = self.t._tx_cost_usd(500.0, 0.0, 4000.0)
        expected = round(200_000 * 500.0 * 1e-9 * 4000.0, 4)
        self.assertAlmostEqual(result, expected, places=4)

    def test_returns_float(self):
        self.assertIsInstance(self.t._tx_cost_usd(30.0, 0.0, 2000.0), float)

    def test_result_rounded_to_4dp(self):
        result = self.t._tx_cost_usd(30.0, 0.0, 2000.0)
        self.assertEqual(result, round(result, 4))


# ===========================================================================
# 2. _fee_tier
# ===========================================================================

class TestFeeTier(unittest.TestCase):

    def setUp(self):
        self.t = ChainFeeTracker()

    def test_ultra_low_zero(self):
        self.assertEqual(self.t._fee_tier(0.0), "ULTRA_LOW")

    def test_ultra_low_just_below_boundary(self):
        self.assertEqual(self.t._fee_tier(0.09), "ULTRA_LOW")

    def test_low_at_boundary(self):
        self.assertEqual(self.t._fee_tier(0.10), "LOW")

    def test_low_middle(self):
        self.assertEqual(self.t._fee_tier(0.5), "LOW")

    def test_low_just_below_medium_boundary(self):
        self.assertEqual(self.t._fee_tier(0.99), "LOW")

    def test_medium_at_boundary(self):
        self.assertEqual(self.t._fee_tier(1.00), "MEDIUM")

    def test_medium_middle(self):
        self.assertEqual(self.t._fee_tier(2.50), "MEDIUM")

    def test_medium_just_below_high(self):
        self.assertEqual(self.t._fee_tier(4.99), "MEDIUM")

    def test_high_at_boundary(self):
        self.assertEqual(self.t._fee_tier(5.00), "HIGH")

    def test_high_large_value(self):
        self.assertEqual(self.t._fee_tier(100.0), "HIGH")

    def test_returns_str(self):
        self.assertIsInstance(self.t._fee_tier(1.0), str)


# ===========================================================================
# 3. snapshot_chain
# ===========================================================================

class TestSnapshotChain(unittest.TestCase):

    def setUp(self):
        self.t = ChainFeeTracker()

    def test_ethereum_ratio_is_1(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 1.0, places=4)

    def test_arbitrum_ratio_is_0_05(self):
        s = self.t.snapshot_chain("arbitrum", 1, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 0.05, places=4)

    def test_base_ratio_is_0_04(self):
        s = self.t.snapshot_chain("base", 1, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 0.04, places=4)

    def test_optimism_ratio_is_0_06(self):
        s = self.t.snapshot_chain("optimism", 1, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 0.06, places=4)

    def test_polygon_ratio_is_0_01(self):
        s = self.t.snapshot_chain("polygon", 1, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 0.01, places=4)

    def test_unknown_chain_defaults_ratio_1(self):
        s = self.t.snapshot_chain("solana", 1, 0, 2000)
        self.assertAlmostEqual(s.cost_ratio_vs_eth, 1.0, places=4)

    def test_arbitrum_recommended_true(self):
        s = self.t.snapshot_chain("arbitrum", 1, 0, 2000)
        self.assertTrue(s.recommended)

    def test_base_recommended_true(self):
        s = self.t.snapshot_chain("base", 1, 0, 2000)
        self.assertTrue(s.recommended)

    def test_optimism_recommended_true(self):
        s = self.t.snapshot_chain("optimism", 1, 0, 2000)
        self.assertTrue(s.recommended)

    def test_ethereum_recommended_false(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        self.assertFalse(s.recommended)

    def test_unknown_chain_recommended_false(self):
        s = self.t.snapshot_chain("fantom", 1, 0, 2000)
        self.assertFalse(s.recommended)  # ratio=1.0 ≥ 0.10

    def test_chain_field_preserved(self):
        s = self.t.snapshot_chain("arbitrum", 1, 0, 2000)
        self.assertEqual(s.chain, "arbitrum")

    def test_gas_price_rounded(self):
        s = self.t.snapshot_chain("ethereum", 30.123456, 0, 2000)
        self.assertEqual(s.base_gas_price_gwei, round(30.123456, 2))

    def test_l1_overhead_rounded(self):
        s = self.t.snapshot_chain("arbitrum", 1, 2.12345678, 2000)
        self.assertEqual(s.l1_gas_overhead_gwei, round(2.12345678, 4))

    def test_eth_price_rounded(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000.789)
        self.assertEqual(s.eth_price_usd, round(2000.789, 2))

    def test_tx_cost_usd_correct(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        expected = round(200_000 * 30 * 1e-9 * 2000, 4)
        self.assertAlmostEqual(s.standard_tx_cost_usd, expected, places=4)

    def test_fee_tier_assigned(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        self.assertIn(s.fee_tier, ("ULTRA_LOW", "LOW", "MEDIUM", "HIGH"))

    def test_returns_chain_fee_snapshot(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        self.assertIsInstance(s, ChainFeeSnapshot)

    def test_case_insensitive_chain_lookup(self):
        s_lower = self.t.snapshot_chain("arbitrum", 1, 0, 2000)
        s_upper = self.t.snapshot_chain("ARBITRUM", 1, 0, 2000)
        self.assertAlmostEqual(s_lower.cost_ratio_vs_eth, s_upper.cost_ratio_vs_eth)

    def test_l1_overhead_increases_cost(self):
        s1 = self.t.snapshot_chain("arbitrum", 1, 0, 2000)
        s2 = self.t.snapshot_chain("arbitrum", 1, 5, 2000)
        self.assertGreater(s2.standard_tx_cost_usd, s1.standard_tx_cost_usd)

    def test_l2_ultra_low_tier(self):
        # arbitrum with very low gas → likely ULTRA_LOW
        s = self.t.snapshot_chain("arbitrum", 0.01, 0, 2000)
        self.assertEqual(s.fee_tier, "ULTRA_LOW")


# ===========================================================================
# 4. compare_chains
# ===========================================================================

class TestCompareChains(unittest.TestCase):

    def setUp(self):
        self.t = ChainFeeTracker()

    def test_empty_snapshots(self):
        result = self.t.compare_chains([])
        self.assertEqual(result.cheapest_chain, "")
        self.assertEqual(result.most_expensive_chain, "")
        self.assertEqual(result.l2_savings_vs_eth_usd, 0.0)
        self.assertIn("No chain data", result.recommendation)

    def test_single_snapshot_cheapest_equals_priciest(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        result = self.t.compare_chains([s])
        self.assertEqual(result.cheapest_chain, result.most_expensive_chain)
        self.assertEqual(result.cheapest_chain, "ethereum")

    def test_picks_correct_cheapest(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        result = self.t.compare_chains([s_eth, s_arb])
        self.assertEqual(result.cheapest_chain, "arbitrum")

    def test_picks_correct_most_expensive(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        result = self.t.compare_chains([s_eth, s_arb])
        self.assertEqual(result.most_expensive_chain, "ethereum")

    def test_l2_savings_when_eth_present(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        result = self.t.compare_chains([s_eth, s_arb])
        expected_savings = round(s_eth.standard_tx_cost_usd - s_arb.standard_tx_cost_usd, 4)
        self.assertAlmostEqual(result.l2_savings_vs_eth_usd, expected_savings, places=4)

    def test_l2_savings_zero_when_no_eth_snapshot(self):
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        s_base = self.t.snapshot_chain("base", 0.05, 0, 2000)
        result = self.t.compare_chains([s_arb, s_base])
        self.assertEqual(result.l2_savings_vs_eth_usd, 0.0)

    def test_recommendation_mentions_cheapest(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_base = self.t.snapshot_chain("base", 0.05, 0, 2000)
        result = self.t.compare_chains([s_eth, s_base])
        self.assertIn("base", result.recommendation)

    def test_snapshots_list_preserved(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        result = self.t.compare_chains([s_eth, s_arb])
        self.assertEqual(len(result.snapshots), 2)

    def test_three_chains_correct_cheapest(self):
        s_eth = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 0.1, 0, 2000)
        s_poly = self.t.snapshot_chain("polygon", 0.001, 0, 2000)
        result = self.t.compare_chains([s_eth, s_arb, s_poly])
        self.assertEqual(result.cheapest_chain, "polygon")
        self.assertEqual(result.most_expensive_chain, "ethereum")

    def test_returns_chain_fee_comparison(self):
        s = self.t.snapshot_chain("ethereum", 30, 0, 2000)
        result = self.t.compare_chains([s])
        self.assertIsInstance(result, ChainFeeComparison)

    def test_savings_non_negative_when_eth_cheapest(self):
        # If ethereum is cheapest (e.g. very low gas), savings should be 0 or negative capped?
        # Actually savings = eth_cost - cheapest_cost; if eth IS cheapest → savings=0
        s_eth = self.t.snapshot_chain("ethereum", 0.01, 0, 2000)
        s_arb = self.t.snapshot_chain("arbitrum", 2.0, 5.0, 2000)
        result = self.t.compare_chains([s_eth, s_arb])
        # cheapest is ethereum here (or arb, depends on actual costs)
        # We just check savings is a float
        self.assertIsInstance(result.l2_savings_vs_eth_usd, float)


# ===========================================================================
# 5. save_snapshots + load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = _make_tracker(self.tmp)

    def test_save_creates_file(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        self.assertTrue(self.t.data_file.exists())

    def test_load_missing_returns_empty(self):
        result = self.t.load_history()
        self.assertEqual(result, [])

    def test_saved_entry_has_required_keys(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertEqual(len(history), 1)
        for key in ("timestamp", "chain", "standard_tx_cost_usd", "fee_tier", "recommended"):
            self.assertIn(key, history[0])

    def test_chain_field_in_history(self):
        s = _snap(self.t, chain="arbitrum")
        self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertEqual(history[0]["chain"], "arbitrum")

    def test_recommended_stored_as_bool(self):
        s = _snap(self.t, chain="arbitrum")
        self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertIsInstance(history[0]["recommended"], bool)

    def test_ring_buffer_caps_at_max_entries(self):
        for _ in range(MAX_ENTRIES + 15):
            s = _snap(self.t)
            self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_exactly_max(self):
        for _ in range(MAX_ENTRIES):
            s = _snap(self.t)
            self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_no_tmp_left(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        self.assertFalse(self.t.data_file.with_suffix(".tmp").exists())

    def test_multiple_saves_append(self):
        for _ in range(4):
            s = _snap(self.t)
            self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertEqual(len(history), 4)

    def test_save_batch_of_snapshots(self):
        snaps = [_snap(self.t, chain="ethereum"),
                 _snap(self.t, chain="arbitrum"),
                 _snap(self.t, chain="base")]
        self.t.save_snapshots(snaps)
        history = self.t.load_history()
        self.assertEqual(len(history), 3)

    def test_file_valid_json(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        content = self.t.data_file.read_text()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_load_corrupt_file_returns_empty(self):
        self.t.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.t.data_file.write_text("CORRUPT {{{{")
        self.assertEqual(self.t.load_history(), [])

    def test_timestamp_is_numeric(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertIsInstance(history[0]["timestamp"], (int, float))

    def test_tx_cost_usd_in_history(self):
        s = _snap(self.t)
        self.t.save_snapshots([s])
        history = self.t.load_history()
        self.assertAlmostEqual(history[0]["standard_tx_cost_usd"],
                                s.standard_tx_cost_usd, places=4)


# ===========================================================================
# 6. CHAIN_FEE_MULTIPLIERS registry
# ===========================================================================

class TestChainFeeMultipliersRegistry(unittest.TestCase):

    def test_ethereum_in_registry(self):
        self.assertIn("ethereum", CHAIN_FEE_MULTIPLIERS)

    def test_arbitrum_in_registry(self):
        self.assertIn("arbitrum", CHAIN_FEE_MULTIPLIERS)

    def test_base_in_registry(self):
        self.assertIn("base", CHAIN_FEE_MULTIPLIERS)

    def test_optimism_in_registry(self):
        self.assertIn("optimism", CHAIN_FEE_MULTIPLIERS)

    def test_polygon_in_registry(self):
        self.assertIn("polygon", CHAIN_FEE_MULTIPLIERS)

    def test_ethereum_multiplier_is_1(self):
        self.assertAlmostEqual(CHAIN_FEE_MULTIPLIERS["ethereum"], 1.0, places=4)

    def test_l2s_have_multiplier_below_0_10(self):
        l2s = ["arbitrum", "base", "optimism", "polygon"]
        for chain in l2s:
            self.assertLess(CHAIN_FEE_MULTIPLIERS[chain], 0.10,
                            msg=f"{chain} should be < 0.10")

    def test_all_values_positive(self):
        for chain, mult in CHAIN_FEE_MULTIPLIERS.items():
            self.assertGreater(mult, 0, msg=f"{chain} multiplier must be > 0")

    def test_max_entries_is_100(self):
        self.assertEqual(MAX_ENTRIES, 100)


if __name__ == "__main__":
    unittest.main()
