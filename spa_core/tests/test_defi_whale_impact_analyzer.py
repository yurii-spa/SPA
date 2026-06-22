"""
Tests for MP-847 DeFiWhaleImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_whale_impact_analyzer -v
"""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Patch DATA_FILE before import to avoid writing to real data/
import spa_core.analytics.defi_whale_impact_analyzer as _mod
import tempfile

_ORIG_DATA_FILE = _mod.DATA_FILE


def _make_pool(
    protocol="Aave",
    pool_id="pool-1",
    tvl_usd=1_000_000.0,
    txs=None,
    daily_volume_usd=500_000.0,
    fee_apy=5.0,
):
    return {
        "protocol": protocol,
        "pool_id": pool_id,
        "tvl_usd": tvl_usd,
        "whale_transactions": txs or [],
        "daily_volume_usd": daily_volume_usd,
        "fee_apy": fee_apy,
    }


def _deposit(amount, direction="IN"):
    return {"tx_type": "DEPOSIT", "amount_usd": amount, "direction": direction}


def _withdraw(amount, direction="OUT"):
    return {"tx_type": "WITHDRAW", "amount_usd": amount, "direction": direction}


def _swap(amount, direction="IN"):
    return {"tx_type": "SWAP", "amount_usd": amount, "direction": direction}


class TestAnalyzeEmpty(unittest.TestCase):
    """Edge cases: empty input."""

    def test_empty_pools_returns_structure(self):
        result = _mod.analyze([])
        self.assertIn("pools", result)
        self.assertIn("most_impacted_pool", result)
        self.assertIn("safest_pool", result)
        self.assertIn("total_whale_volume_usd", result)
        self.assertIn("timestamp", result)

    def test_empty_pools_list_is_empty(self):
        result = _mod.analyze([])
        self.assertEqual(result["pools"], [])

    def test_empty_pools_most_impacted_none(self):
        result = _mod.analyze([])
        self.assertIsNone(result["most_impacted_pool"])

    def test_empty_pools_safest_none(self):
        result = _mod.analyze([])
        self.assertIsNone(result["safest_pool"])

    def test_empty_pools_total_volume_zero(self):
        result = _mod.analyze([])
        self.assertEqual(result["total_whale_volume_usd"], 0.0)

    def test_empty_pools_timestamp_recent(self):
        before = time.time()
        result = _mod.analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAnalyzeSinglePoolNoTxs(unittest.TestCase):
    """Single pool with no transactions."""

    def setUp(self):
        self.pool = _make_pool(txs=[])
        with patch.object(_mod, "_append_log"):
            self.result = _mod.analyze([self.pool])

    def test_pool_count(self):
        self.assertEqual(len(self.result["pools"]), 1)

    def test_whale_tx_count_zero(self):
        self.assertEqual(self.result["pools"][0]["whale_tx_count"], 0)

    def test_whale_volume_zero(self):
        self.assertEqual(self.result["pools"][0]["whale_volume_usd"], 0.0)

    def test_pct_tvl_zero(self):
        self.assertEqual(self.result["pools"][0]["whale_volume_pct_tvl"], 0.0)

    def test_net_flow_zero(self):
        self.assertEqual(self.result["pools"][0]["net_whale_flow_usd"], 0.0)

    def test_yield_dilution_zero(self):
        self.assertEqual(self.result["pools"][0]["yield_dilution_pct"], 0.0)

    def test_price_impact_zero(self):
        self.assertEqual(self.result["pools"][0]["price_impact_pct"], 0.0)

    def test_impact_level_low(self):
        self.assertEqual(self.result["pools"][0]["impact_level"], "LOW")

    def test_user_impact_str(self):
        ui = self.result["pools"][0]["user_impact"]
        self.assertIn("normal parameters", ui)

    def test_recommended_action_no_action(self):
        ra = self.result["pools"][0]["recommended_action"]
        self.assertIn("No action required", ra)


class TestWhaleThresholdFiltering(unittest.TestCase):
    """Verify whale_threshold_pct filtering."""

    def _run(self, tvl, amount, threshold_pct=5.0):
        pool = _make_pool(tvl_usd=tvl, txs=[_deposit(amount)])
        with patch.object(_mod, "_append_log"):
            return _mod.analyze([pool], config={"whale_threshold_pct": threshold_pct})

    def test_tx_below_threshold_not_whale(self):
        # 4% of $1M TVL = $40k — below 5% threshold
        r = self._run(1_000_000, 40_000, threshold_pct=5.0)
        self.assertEqual(r["pools"][0]["whale_tx_count"], 0)

    def test_tx_at_threshold_is_whale(self):
        # Exactly 5% of $1M = $50k
        r = self._run(1_000_000, 50_000, threshold_pct=5.0)
        self.assertEqual(r["pools"][0]["whale_tx_count"], 1)

    def test_tx_above_threshold_is_whale(self):
        r = self._run(1_000_000, 100_000, threshold_pct=5.0)
        self.assertEqual(r["pools"][0]["whale_tx_count"], 1)

    def test_custom_threshold_1pct(self):
        # 1% of $1M = $10k
        r = self._run(1_000_000, 10_000, threshold_pct=1.0)
        self.assertEqual(r["pools"][0]["whale_tx_count"], 1)

    def test_zero_tvl_all_are_whales(self):
        pool = _make_pool(tvl_usd=0, txs=[_deposit(100)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["pools"][0]["whale_tx_count"], 1)


class TestNetWhaleFlow(unittest.TestCase):
    """Verify net_whale_flow_usd computation."""

    def _run(self, txs, tvl=1_000_000):
        pool = _make_pool(tvl_usd=tvl, txs=txs)
        with patch.object(_mod, "_append_log"):
            return _mod.analyze([pool], config={"whale_threshold_pct": 1.0})

    def test_pure_deposit_positive_flow(self):
        r = self._run([_deposit(100_000)])
        self.assertGreater(r["pools"][0]["net_whale_flow_usd"], 0)

    def test_pure_withdraw_negative_flow(self):
        r = self._run([_withdraw(100_000)])
        self.assertLess(r["pools"][0]["net_whale_flow_usd"], 0)

    def test_equal_deposit_withdraw_zero_flow(self):
        r = self._run([_deposit(100_000), _withdraw(100_000)])
        self.assertAlmostEqual(r["pools"][0]["net_whale_flow_usd"], 0.0, places=2)

    def test_swap_in_adds_to_flow(self):
        r = self._run([_swap(100_000, "IN")])
        self.assertGreater(r["pools"][0]["net_whale_flow_usd"], 0)

    def test_swap_out_reduces_flow(self):
        r = self._run([_swap(100_000, "OUT")])
        self.assertLess(r["pools"][0]["net_whale_flow_usd"], 0)

    def test_multiple_txs_net_calculation(self):
        txs = [_deposit(200_000), _withdraw(50_000), _swap(30_000, "IN")]
        r = self._run(txs)
        self.assertAlmostEqual(r["pools"][0]["net_whale_flow_usd"], 180_000.0, places=2)


class TestYieldDilution(unittest.TestCase):
    """Verify yield_dilution_pct calculation."""

    def _run(self, tvl, amount, fee_apy):
        pool = _make_pool(tvl_usd=tvl, txs=[_deposit(amount)], fee_apy=fee_apy)
        with patch.object(_mod, "_append_log"):
            return _mod.analyze([pool], config={"whale_threshold_pct": 1.0})

    def test_deposit_causes_dilution(self):
        r = self._run(1_000_000, 500_000, 10.0)
        self.assertGreater(r["pools"][0]["yield_dilution_pct"], 0)

    def test_dilution_formula_correct(self):
        tvl = 1_000_000
        amount = 1_000_000
        fee_apy = 10.0
        r = self._run(tvl, amount, fee_apy)
        # new_yield = 10 * 1M / 2M = 5
        # dilution = (10 - 5) / 10 * 100 = 50%
        self.assertAlmostEqual(r["pools"][0]["yield_dilution_pct"], 50.0, places=2)

    def test_no_dilution_on_withdrawal(self):
        pool = _make_pool(tvl_usd=1_000_000, txs=[_withdraw(500_000)], fee_apy=10.0)
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertEqual(r["pools"][0]["yield_dilution_pct"], 0.0)

    def test_zero_fee_apy_no_dilution(self):
        r = self._run(1_000_000, 500_000, 0.0)
        self.assertEqual(r["pools"][0]["yield_dilution_pct"], 0.0)

    def test_zero_tvl_no_dilution(self):
        pool = _make_pool(tvl_usd=0, txs=[_deposit(500_000)], fee_apy=10.0)
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 0.0})
        self.assertEqual(r["pools"][0]["yield_dilution_pct"], 0.0)


class TestPriceImpact(unittest.TestCase):
    """Verify price_impact_pct calculation."""

    def _run(self, swap_amount, daily_vol, tvl=10_000_000):
        pool = _make_pool(
            tvl_usd=tvl,
            txs=[_swap(swap_amount)],
            daily_volume_usd=daily_vol,
        )
        with patch.object(_mod, "_append_log"):
            return _mod.analyze([pool], config={"whale_threshold_pct": 0.1})

    def test_price_impact_formula(self):
        # swap_whale_vol=100k, daily_vol=1M → 100k/1M * 0.3 = 0.03
        r = self._run(100_000, 1_000_000)
        self.assertAlmostEqual(r["pools"][0]["price_impact_pct"], 0.03, places=4)

    def test_price_impact_capped_at_20(self):
        # Very large swap relative to volume
        r = self._run(10_000_000, 1_000)
        self.assertEqual(r["pools"][0]["price_impact_pct"], 20.0)

    def test_zero_daily_volume_no_impact(self):
        r = self._run(100_000, 0)
        self.assertEqual(r["pools"][0]["price_impact_pct"], 0.0)

    def test_no_swap_no_impact(self):
        pool = _make_pool(txs=[_deposit(100_000)], daily_volume_usd=500_000)
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertEqual(r["pools"][0]["price_impact_pct"], 0.0)


class TestImpactLevels(unittest.TestCase):
    """Verify impact level classification."""

    def _run_with_pct_tvl(self, whale_vol_pct, tvl=10_000_000, daily_vol=1_000_000_000):
        """Create scenario where whale_volume_pct_tvl ≈ whale_vol_pct."""
        whale_amount = tvl * whale_vol_pct / 100
        pool = _make_pool(
            tvl_usd=tvl,
            txs=[_deposit(whale_amount)],
            daily_volume_usd=daily_vol,
        )
        with patch.object(_mod, "_append_log"):
            return _mod.analyze([pool], config={"whale_threshold_pct": 0.01})

    def test_low_impact_level(self):
        r = self._run_with_pct_tvl(0.5)  # 0.5% TVL
        self.assertEqual(r["pools"][0]["impact_level"], "LOW")

    def test_medium_impact_level(self):
        r = self._run_with_pct_tvl(3.0)  # 3% TVL > default 2.0
        self.assertEqual(r["pools"][0]["impact_level"], "MEDIUM")

    def test_high_impact_level(self):
        r = self._run_with_pct_tvl(12.0)  # 12% TVL ≥ 10%
        self.assertEqual(r["pools"][0]["impact_level"], "HIGH")

    def test_critical_impact_level(self):
        r = self._run_with_pct_tvl(25.0)  # 25% TVL ≥ 20%
        self.assertEqual(r["pools"][0]["impact_level"], "CRITICAL")

    def test_price_impact_critical(self):
        # Swap that causes >10 price_impact
        pool = _make_pool(
            tvl_usd=100_000_000,
            txs=[_swap(1_000_000)],
            daily_volume_usd=3_000,  # tiny volume → huge price impact
        )
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 0.001})
        self.assertEqual(r["pools"][0]["impact_level"], "CRITICAL")

    def test_price_impact_high(self):
        # swap / daily_vol * 0.3 ≥ 5
        pool = _make_pool(
            tvl_usd=100_000_000,
            txs=[_swap(1_000_000)],
            daily_volume_usd=60_000,
        )
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 0.001})
        self.assertEqual(r["pools"][0]["impact_level"], "HIGH")

    def test_custom_max_safe_impact(self):
        # Use max_safe_impact_pct=10 → 3% whale_vol_pct_tvl should be LOW
        r = _mod.analyze(
            [_make_pool(tvl_usd=1_000_000, txs=[_deposit(30_000)], daily_volume_usd=1e9)],
            config={"whale_threshold_pct": 0.1, "max_safe_impact_pct": 10.0},
        )
        with patch.object(_mod, "_append_log"):
            r2 = _mod.analyze(
                [_make_pool(tvl_usd=1_000_000, txs=[_deposit(30_000)], daily_volume_usd=1e9)],
                config={"whale_threshold_pct": 0.1, "max_safe_impact_pct": 10.0},
            )
        self.assertEqual(r2["pools"][0]["impact_level"], "LOW")


class TestUserImpactMessages(unittest.TestCase):
    """Verify user_impact strings."""

    def _impact(self, level, pct_tvl=5.0, count=1):
        return _mod._user_impact_msg(level, pct_tvl, count)

    def test_critical_message_contains_pct(self):
        msg = self._impact("CRITICAL", pct_tvl=22.5)
        self.assertIn("22.5%", msg)
        self.assertIn("slippage", msg)

    def test_high_message_contains_pct(self):
        msg = self._impact("HIGH", pct_tvl=12.3)
        self.assertIn("12.3%", msg)
        self.assertIn("monitor", msg.lower())

    def test_medium_message_contains_count(self):
        msg = self._impact("MEDIUM", count=7)
        self.assertIn("7", msg)
        self.assertIn("Moderate", msg)

    def test_low_message_contains_count(self):
        msg = self._impact("LOW", count=2)
        self.assertIn("2", msg)
        self.assertIn("normal parameters", msg)


class TestRecommendedActions(unittest.TestCase):
    """Verify recommended_action strings."""

    def _action(self, level, flow):
        return _mod._recommended_action(level, flow)

    def test_critical_withdrawal_exit(self):
        msg = self._action("CRITICAL", -100_000)
        self.assertIn("exiting", msg.lower())

    def test_critical_deposit_wait(self):
        msg = self._action("CRITICAL", 100_000)
        self.assertIn("Wait", msg)

    def test_high_reduce_position(self):
        msg = self._action("HIGH", 0)
        self.assertIn("Reduce", msg)

    def test_medium_monitor(self):
        msg = self._action("MEDIUM", 0)
        self.assertIn("Monitor", msg)

    def test_low_no_action(self):
        msg = self._action("LOW", 0)
        self.assertIn("No action", msg)


class TestMostImpactedAndSafest(unittest.TestCase):
    """Verify most_impacted_pool and safest_pool selection."""

    def setUp(self):
        pools = [
            _make_pool(protocol="A", pool_id="pool-low", tvl_usd=10_000_000, txs=[]),
            _make_pool(
                protocol="B",
                pool_id="pool-critical",
                tvl_usd=1_000_000,
                txs=[_deposit(300_000)],
            ),
            _make_pool(
                protocol="C",
                pool_id="pool-medium",
                tvl_usd=1_000_000,
                txs=[_deposit(30_000)],
            ),
        ]
        with patch.object(_mod, "_append_log"):
            self.result = _mod.analyze(pools, config={"whale_threshold_pct": 0.1})

    def test_most_impacted_is_critical(self):
        self.assertEqual(self.result["most_impacted_pool"], "pool-critical")

    def test_safest_is_low(self):
        self.assertEqual(self.result["safest_pool"], "pool-low")

    def test_total_volume_is_sum(self):
        total = sum(p["whale_volume_usd"] for p in self.result["pools"])
        self.assertAlmostEqual(self.result["total_whale_volume_usd"], total, places=2)


class TestSinglePool(unittest.TestCase):
    """Single pool: most_impacted == safest == pool_id."""

    def test_single_pool_both_same(self):
        pool = _make_pool(pool_id="only-pool")
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["most_impacted_pool"], "only-pool")
        self.assertEqual(r["safest_pool"], "only-pool")


class TestPoolMetadata(unittest.TestCase):
    """Verify protocol/pool_id fields are propagated."""

    def test_protocol_propagated(self):
        pool = _make_pool(protocol="Compound", pool_id="comp-1")
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["pools"][0]["protocol"], "Compound")

    def test_pool_id_propagated(self):
        pool = _make_pool(pool_id="my-pool-xyz")
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["pools"][0]["pool_id"], "my-pool-xyz")


class TestNoneConfig(unittest.TestCase):
    """analyze() with config=None uses defaults."""

    def test_none_config_uses_defaults(self):
        pool = _make_pool(tvl_usd=1_000_000, txs=[_deposit(50_000)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config=None)
        # 50k/1M = 5% which is exactly at threshold, so it IS a whale
        self.assertEqual(r["pools"][0]["whale_tx_count"], 1)


class TestMultipleTransactionsInPool(unittest.TestCase):
    """Multiple txs of different types in one pool."""

    def setUp(self):
        txs = [
            _deposit(200_000),   # whale (20% of 1M TVL)
            _withdraw(50_000),   # whale (5% of 1M TVL)
            _swap(80_000, "IN"), # whale (8% of 1M TVL)
            _deposit(1_000),     # not whale (0.1%)
        ]
        pool = _make_pool(tvl_usd=1_000_000, txs=txs, daily_volume_usd=500_000)
        with patch.object(_mod, "_append_log"):
            self.result = _mod.analyze([pool], config={"whale_threshold_pct": 5.0})
        self.pool_r = self.result["pools"][0]

    def test_whale_count_excludes_small(self):
        # 200k (20%), 50k (5%), 80k (8%) are whales; 1k is not
        self.assertEqual(self.pool_r["whale_tx_count"], 3)

    def test_whale_volume_excludes_small(self):
        self.assertAlmostEqual(self.pool_r["whale_volume_usd"], 330_000.0, places=2)

    def test_net_flow_is_correct(self):
        # deposit=200k, withdraw=-50k, swap_in=+80k → 230k
        self.assertAlmostEqual(self.pool_r["net_whale_flow_usd"], 230_000.0, places=2)


class TestZeroTVLDivisionSafety(unittest.TestCase):
    """Ensure no ZeroDivisionError when tvl_usd=0."""

    def test_zero_tvl_no_crash(self):
        pool = _make_pool(tvl_usd=0, txs=[_deposit(10_000)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["pools"][0]["whale_volume_pct_tvl"], 0.0)


class TestLogAppend(unittest.TestCase):
    """Verify atomic log append behavior."""

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "whale_impact_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod._append_log({"test": True, "timestamp": 1.0})
            self.assertTrue(log_path.exists())

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "whale_impact_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod._append_log({"entry": 1})
                _mod._append_log({"entry": 2})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 2)

    def test_log_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "whale_impact_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                with patch.object(_mod, "MAX_ENTRIES", 3):
                    for i in range(5):
                        _mod._append_log({"entry": i})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
            self.assertEqual(data[0]["entry"], 2)  # oldest 2 dropped


class TestInitLog(unittest.TestCase):
    """Verify init_log creates file if absent."""

    def test_init_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "whale_impact_log.json"
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod.init_log()
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data, [])

    def test_init_does_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "whale_impact_log.json"
            with open(log_path, "w") as f:
                json.dump([{"existing": True}], f)
            with patch.object(_mod, "DATA_FILE", log_path):
                _mod.init_log()
            with open(log_path) as f:
                data = json.load(f)
            # Should NOT be overwritten
            self.assertEqual(data, [{"existing": True}])


class TestWhaleVolumeAccumulation(unittest.TestCase):
    """Multiple whale txs accumulate correctly."""

    def test_total_whale_volume_across_pools(self):
        p1 = _make_pool(pool_id="p1", tvl_usd=2_000_000, txs=[_deposit(200_000)])
        p2 = _make_pool(pool_id="p2", tvl_usd=2_000_000, txs=[_deposit(400_000)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([p1, p2], config={"whale_threshold_pct": 5.0})
        self.assertAlmostEqual(r["total_whale_volume_usd"], 600_000.0, places=2)


class TestMixedImpactLevelsMultiplePools(unittest.TestCase):
    """Multiple pools with different impact levels."""

    def setUp(self):
        pools = [
            _make_pool(pool_id="p-low", tvl_usd=100_000_000, txs=[_deposit(100_000)]),
            _make_pool(pool_id="p-high", tvl_usd=1_000_000, txs=[_deposit(200_000)]),
        ]
        with patch.object(_mod, "_append_log"):
            self.r = _mod.analyze(pools, config={"whale_threshold_pct": 0.01})

    def test_two_pools_returned(self):
        self.assertEqual(len(self.r["pools"]), 2)

    def test_most_impacted_is_high_impact(self):
        # p-high: 200k/1M = 20% → CRITICAL; p-low: 100k/100M = 0.1% → LOW
        self.assertEqual(self.r["most_impacted_pool"], "p-high")

    def test_safest_is_low_impact(self):
        self.assertEqual(self.r["safest_pool"], "p-low")


class TestMergeConfig(unittest.TestCase):
    """Internal _merge_config utility."""

    def test_defaults_applied(self):
        cfg = _mod._merge_config(None)
        self.assertEqual(cfg["whale_threshold_pct"], 5.0)
        self.assertEqual(cfg["max_safe_impact_pct"], 2.0)

    def test_partial_override(self):
        cfg = _mod._merge_config({"whale_threshold_pct": 1.0})
        self.assertEqual(cfg["whale_threshold_pct"], 1.0)
        self.assertEqual(cfg["max_safe_impact_pct"], 2.0)

    def test_full_override(self):
        cfg = _mod._merge_config({"whale_threshold_pct": 3.0, "max_safe_impact_pct": 5.0})
        self.assertEqual(cfg["whale_threshold_pct"], 3.0)
        self.assertEqual(cfg["max_safe_impact_pct"], 5.0)


class TestSwapDirectionAccountability(unittest.TestCase):
    """SWAP direction=OUT reduces net flow."""

    def test_swap_out_reduces_net(self):
        pool = _make_pool(tvl_usd=1_000_000, txs=[_swap(100_000, "OUT")])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertAlmostEqual(r["pools"][0]["net_whale_flow_usd"], -100_000.0, places=2)

    def test_swap_in_adds_to_net(self):
        pool = _make_pool(tvl_usd=1_000_000, txs=[_swap(100_000, "IN")])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertAlmostEqual(r["pools"][0]["net_whale_flow_usd"], 100_000.0, places=2)


class TestPriceImpactOnlyFromSwaps(unittest.TestCase):
    """price_impact only counts SWAP txs."""

    def test_deposit_does_not_affect_price_impact(self):
        pool = _make_pool(
            tvl_usd=1_000_000,
            txs=[_deposit(500_000)],
            daily_volume_usd=500_000,
        )
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertEqual(r["pools"][0]["price_impact_pct"], 0.0)

    def test_withdraw_does_not_affect_price_impact(self):
        pool = _make_pool(
            tvl_usd=1_000_000,
            txs=[_withdraw(500_000)],
            daily_volume_usd=500_000,
        )
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertEqual(r["pools"][0]["price_impact_pct"], 0.0)


class TestTimestampPresent(unittest.TestCase):
    """Timestamp is in the result."""

    def test_timestamp_in_result(self):
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([_make_pool()])
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)


class TestNonWhaleTransactionsIgnored(unittest.TestCase):
    """Transactions below threshold don't count as whale."""

    def test_small_txs_not_counted(self):
        # 1% of 1M = $10k; threshold 5% → not whale
        pool = _make_pool(tvl_usd=1_000_000, txs=[_deposit(10_000)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool])
        self.assertEqual(r["pools"][0]["whale_tx_count"], 0)
        self.assertEqual(r["pools"][0]["whale_volume_usd"], 0.0)


class TestAllImpactMessagesPresent(unittest.TestCase):
    """All impact levels produce non-empty strings."""

    def test_all_levels_have_user_impact(self):
        for level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            msg = _mod._user_impact_msg(level, 5.0, 1)
            self.assertTrue(len(msg) > 0, f"Empty user_impact for {level}")

    def test_all_levels_have_recommended_action(self):
        for level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            msg = _mod._recommended_action(level, 1000.0)
            self.assertTrue(len(msg) > 0, f"Empty recommended_action for {level}")


class TestReturnStructureKeys(unittest.TestCase):
    """Verify all required keys are present in pool result."""

    def test_pool_result_keys(self):
        required = {
            "protocol", "pool_id", "whale_tx_count", "whale_volume_usd",
            "whale_volume_pct_tvl", "net_whale_flow_usd", "yield_dilution_pct",
            "price_impact_pct", "impact_level", "user_impact", "recommended_action",
        }
        pool = _make_pool(txs=[_deposit(100_000)])
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([pool], config={"whale_threshold_pct": 1.0})
        self.assertTrue(required.issubset(r["pools"][0].keys()))

    def test_top_level_result_keys(self):
        required = {
            "pools", "most_impacted_pool", "safest_pool",
            "total_whale_volume_usd", "timestamp",
        }
        with patch.object(_mod, "_append_log"):
            r = _mod.analyze([_make_pool()])
        self.assertTrue(required.issubset(r.keys()))


if __name__ == "__main__":
    unittest.main()
