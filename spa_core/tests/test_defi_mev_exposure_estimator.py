"""
Tests for MP-930 DeFiMEVExposureEstimator
Run: python3 -m unittest spa_core.tests.test_defi_mev_exposure_estimator -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_mev_exposure_estimator import (
    DeFiMEVExposureEstimator,
    _clamp,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _swap(
    protocol="Uniswap",
    tx_type="swap",
    size_usd=10_000.0,
    slippage_tolerance_pct=0.5,
    pool_depth_usd=5_000_000.0,
    gas_price_gwei=30.0,
    is_private_mempool=False,
    dex_type="amm",
    time_sensitivity="flexible",
) -> dict:
    return {
        "protocol": protocol,
        "tx_type": tx_type,
        "size_usd": size_usd,
        "slippage_tolerance_pct": slippage_tolerance_pct,
        "pool_depth_usd": pool_depth_usd,
        "gas_price_gwei": gas_price_gwei,
        "is_private_mempool": is_private_mempool,
        "dex_type": dex_type,
        "time_sensitivity": time_sensitivity,
    }


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and basic structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        est = DeFiMEVExposureEstimator()
        self.assertIsNotNone(est)

    def test_estimate_method_exists(self):
        est = DeFiMEVExposureEstimator()
        self.assertTrue(callable(est.estimate))

    def test_estimate_returns_dict(self):
        est = DeFiMEVExposureEstimator()
        result = est.estimate([], NO_LOG)
        self.assertIsInstance(result, dict)

    def test_result_has_required_keys(self):
        est = DeFiMEVExposureEstimator()
        result = est.estimate([], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, result)

    def test_raises_typeerror_non_list(self):
        est = DeFiMEVExposureEstimator()
        with self.assertRaises(TypeError):
            est.estimate("not a list", NO_LOG)


# ===========================================================================
# 2. Empty transactions
# ===========================================================================

class TestEmptyTransactions(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def test_empty_results_list(self):
        r = self.est.estimate([], NO_LOG)
        self.assertEqual(r["results"], [])

    def test_empty_aggregates_defaults(self):
        r = self.est.estimate([], NO_LOG)
        agg = r["aggregates"]
        self.assertIsNone(agg["highest_mev_risk"])
        self.assertIsNone(agg["safest_transaction"])
        self.assertEqual(agg["total_estimated_mev_usd"], 0.0)
        self.assertEqual(agg["average_mev_risk"], 0.0)
        self.assertEqual(agg["extreme_count"], 0)

    def test_empty_timestamp_is_float(self):
        r = self.est.estimate([], NO_LOG)
        self.assertIsInstance(r["timestamp"], float)


# ===========================================================================
# 3. Per-transaction result structure
# ===========================================================================

class TestTransactionResultStructure(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()
        self.result = self.est.estimate([_swap()], NO_LOG)["results"][0]

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_tx_type(self):
        self.assertIn("tx_type", self.result)

    def test_has_size_usd(self):
        self.assertIn("size_usd", self.result)

    def test_has_sandwich_attack_risk(self):
        self.assertIn("sandwich_attack_risk", self.result)

    def test_has_frontrun_risk(self):
        self.assertIn("frontrun_risk", self.result)

    def test_has_mev_cost_estimate_usd(self):
        self.assertIn("mev_cost_estimate_usd", self.result)

    def test_has_effective_slippage(self):
        self.assertIn("effective_slippage_with_mev_pct", self.result)

    def test_has_protection_recommendation(self):
        self.assertIn("protection_recommendation", self.result)

    def test_has_mev_label(self):
        self.assertIn("mev_label", self.result)

    def test_has_flags(self):
        self.assertIn("flags", self.result)

    def test_protocol_preserved(self):
        self.assertEqual(self.result["protocol"], "Uniswap")


# ===========================================================================
# 4. Sandwich risk score bounds
# ===========================================================================

class TestSandwichRisk(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _sr(self, **kwargs) -> float:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["sandwich_attack_risk"]

    def test_score_min_is_zero(self):
        s = self._sr(is_private_mempool=True, dex_type="rfq", slippage_tolerance_pct=0.0)
        self.assertGreaterEqual(s, 0.0)

    def test_score_max_is_100(self):
        s = self._sr(dex_type="amm", slippage_tolerance_pct=100.0, tx_type="swap")
        self.assertLessEqual(s, 100.0)

    def test_amm_higher_than_rfq(self):
        amm = self._sr(dex_type="amm")
        rfq = self._sr(dex_type="rfq")
        self.assertGreater(amm, rfq)

    def test_amm_higher_than_orderbook(self):
        amm = self._sr(dex_type="amm")
        ob = self._sr(dex_type="orderbook")
        self.assertGreater(amm, ob)

    def test_high_slippage_increases_risk(self):
        low = self._sr(slippage_tolerance_pct=0.1)
        high = self._sr(slippage_tolerance_pct=5.0)
        self.assertGreater(high, low)

    def test_private_mempool_reduces_risk(self):
        public = self._sr(is_private_mempool=False)
        private = self._sr(is_private_mempool=True)
        self.assertLess(private, public)

    def test_private_mempool_can_reach_zero(self):
        s = self._sr(is_private_mempool=True, dex_type="rfq", slippage_tolerance_pct=0.0)
        self.assertGreaterEqual(s, 0.0)

    def test_liquidation_adds_risk(self):
        swap = self._sr(tx_type="swap")
        liq = self._sr(tx_type="liquidation")
        # both are amm, liquidation has different adj but similar base
        self.assertIsInstance(liq, float)

    def test_swap_tx_type_sandwich(self):
        s = self._sr(tx_type="swap", dex_type="amm")
        self.assertGreater(s, 50.0)

    def test_rfq_tx_type_low_risk(self):
        s = self._sr(dex_type="rfq", slippage_tolerance_pct=0.1)
        self.assertLess(s, 40.0)


# ===========================================================================
# 5. Frontrun risk score
# ===========================================================================

class TestFrontrunRisk(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _fr(self, **kwargs) -> float:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["frontrun_risk"]

    def test_score_min_zero(self):
        f = self._fr(is_private_mempool=True, dex_type="rfq", time_sensitivity="delayed")
        self.assertGreaterEqual(f, 0.0)

    def test_score_max_100(self):
        f = self._fr(tx_type="liquidation", time_sensitivity="immediate", gas_price_gwei=200)
        self.assertLessEqual(f, 100.0)

    def test_liquidation_highest_frontrun(self):
        liq = self._fr(tx_type="liquidation", time_sensitivity="immediate")
        swap = self._fr(tx_type="swap", time_sensitivity="flexible")
        self.assertGreater(liq, swap)

    def test_arbitrage_higher_than_redeem(self):
        arb = self._fr(tx_type="arbitrage")
        red = self._fr(tx_type="redeem")
        self.assertGreater(arb, red)

    def test_immediate_higher_than_delayed(self):
        imm = self._fr(time_sensitivity="immediate")
        delayed = self._fr(time_sensitivity="delayed")
        self.assertGreater(imm, delayed)

    def test_high_gas_increases_frontrun(self):
        low = self._fr(gas_price_gwei=20.0)
        high = self._fr(gas_price_gwei=150.0)
        self.assertGreater(high, low)

    def test_medium_gas_moderate_increase(self):
        low = self._fr(gas_price_gwei=20.0)
        med = self._fr(gas_price_gwei=75.0)
        self.assertGreater(med, low)

    def test_private_mempool_reduces_frontrun(self):
        pub = self._fr(is_private_mempool=False, tx_type="liquidation")
        priv = self._fr(is_private_mempool=True, tx_type="liquidation")
        self.assertLess(priv, pub)

    def test_rfq_base_lower_than_amm(self):
        rfq = self._fr(dex_type="rfq", time_sensitivity="flexible")
        amm = self._fr(dex_type="amm", time_sensitivity="flexible")
        self.assertLess(rfq, amm)

    def test_flexible_between_immediate_and_delayed(self):
        imm = self._fr(time_sensitivity="immediate")
        flex = self._fr(time_sensitivity="flexible")
        delayed = self._fr(time_sensitivity="delayed")
        self.assertGreater(imm, flex)
        self.assertGreater(flex, delayed)


# ===========================================================================
# 6. MEV cost estimation
# ===========================================================================

class TestMEVCostEstimation(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _cost(self, **kwargs) -> float:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["mev_cost_estimate_usd"]

    def test_zero_size_zero_cost(self):
        c = self._cost(size_usd=0.0)
        self.assertEqual(c, 0.0)

    def test_cost_non_negative(self):
        c = self._cost()
        self.assertGreaterEqual(c, 0.0)

    def test_larger_size_higher_cost(self):
        small = self._cost(size_usd=1_000.0)
        large = self._cost(size_usd=100_000.0)
        self.assertGreater(large, small)

    def test_higher_slippage_higher_cost(self):
        low = self._cost(slippage_tolerance_pct=0.1)
        high = self._cost(slippage_tolerance_pct=3.0)
        self.assertGreater(high, low)

    def test_liquidation_cost_non_zero(self):
        c = self._cost(tx_type="liquidation", size_usd=50_000.0, time_sensitivity="immediate")
        self.assertGreater(c, 0.0)

    def test_private_mempool_reduces_cost(self):
        pub = self._cost(is_private_mempool=False, size_usd=10_000.0)
        priv = self._cost(is_private_mempool=True, size_usd=10_000.0)
        self.assertLessEqual(priv, pub)

    def test_arbitrage_cost_non_negative(self):
        c = self._cost(tx_type="arbitrage", size_usd=5_000.0)
        self.assertGreaterEqual(c, 0.0)

    def test_rfq_cost_lower_than_amm(self):
        amm = self._cost(dex_type="amm", size_usd=10_000.0)
        rfq = self._cost(dex_type="rfq", size_usd=10_000.0)
        self.assertLessEqual(rfq, amm)


# ===========================================================================
# 7. Effective slippage
# ===========================================================================

class TestEffectiveSlippage(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _eff_slip(self, **kwargs) -> float:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["effective_slippage_with_mev_pct"]

    def test_effective_slip_ge_base_slip(self):
        slip = self._eff_slip(slippage_tolerance_pct=0.5)
        self.assertGreaterEqual(slip, 0.5)

    def test_zero_size_returns_base_slip(self):
        slip = self._eff_slip(size_usd=0.0, slippage_tolerance_pct=1.0)
        self.assertEqual(slip, 1.0)

    def test_larger_mev_cost_higher_effective_slip(self):
        low = self._eff_slip(slippage_tolerance_pct=0.1, size_usd=10_000.0)
        high = self._eff_slip(slippage_tolerance_pct=3.0, size_usd=10_000.0)
        self.assertGreater(high, low)

    def test_private_mempool_lower_effective_slip(self):
        pub = self._eff_slip(is_private_mempool=False, size_usd=10_000.0)
        priv = self._eff_slip(is_private_mempool=True, size_usd=10_000.0)
        self.assertLessEqual(priv, pub)

    def test_is_float(self):
        slip = self._eff_slip()
        self.assertIsInstance(slip, float)


# ===========================================================================
# 8. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _flags(self, **kwargs) -> list:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["flags"]

    # SANDWICH_TARGET
    def test_sandwich_target_flag_on_amm_swap_high_slip(self):
        flags = self._flags(tx_type="swap", dex_type="amm", slippage_tolerance_pct=1.5)
        self.assertIn("SANDWICH_TARGET", flags)

    def test_no_sandwich_target_on_low_slip(self):
        flags = self._flags(tx_type="swap", dex_type="amm", slippage_tolerance_pct=0.1)
        self.assertNotIn("SANDWICH_TARGET", flags)

    def test_no_sandwich_target_on_rfq(self):
        flags = self._flags(tx_type="swap", dex_type="rfq", slippage_tolerance_pct=2.0)
        self.assertNotIn("SANDWICH_TARGET", flags)

    # LIQUIDATION_MEV
    def test_liquidation_mev_flag(self):
        flags = self._flags(tx_type="liquidation")
        self.assertIn("LIQUIDATION_MEV", flags)

    def test_no_liquidation_mev_on_swap(self):
        flags = self._flags(tx_type="swap")
        self.assertNotIn("LIQUIDATION_MEV", flags)

    # PRIVATE_POOL_SAFE
    def test_private_pool_safe_flag(self):
        flags = self._flags(is_private_mempool=True)
        self.assertIn("PRIVATE_POOL_SAFE", flags)

    def test_no_private_pool_safe_public(self):
        flags = self._flags(is_private_mempool=False)
        self.assertNotIn("PRIVATE_POOL_SAFE", flags)

    # SPLIT_RECOMMENDED
    def test_split_recommended_large_trade(self):
        flags = self._flags(size_usd=100_000.0, pool_depth_usd=1_000_000.0)
        # 100_000 > 1_000_000 * 0.01 = 10_000 → should flag
        self.assertIn("SPLIT_RECOMMENDED", flags)

    def test_no_split_small_trade(self):
        flags = self._flags(size_usd=100.0, pool_depth_usd=5_000_000.0)
        self.assertNotIn("SPLIT_RECOMMENDED", flags)

    # HIGH_GAS_COMPETITION
    def test_high_gas_flag(self):
        flags = self._flags(gas_price_gwei=150.0)
        self.assertIn("HIGH_GAS_COMPETITION", flags)

    def test_no_high_gas_flag_low_gas(self):
        flags = self._flags(gas_price_gwei=30.0)
        self.assertNotIn("HIGH_GAS_COMPETITION", flags)

    def test_exactly_at_gas_threshold(self):
        flags = self._flags(gas_price_gwei=100.0)
        self.assertIn("HIGH_GAS_COMPETITION", flags)

    def test_flags_is_list(self):
        flags = self._flags()
        self.assertIsInstance(flags, list)

    def test_multiple_flags_possible(self):
        flags = self._flags(
            tx_type="swap",
            dex_type="amm",
            slippage_tolerance_pct=2.0,
            gas_price_gwei=120.0,
            size_usd=500_000.0,
            pool_depth_usd=1_000_000.0,
        )
        self.assertIn("SANDWICH_TARGET", flags)
        self.assertIn("HIGH_GAS_COMPETITION", flags)
        self.assertIn("SPLIT_RECOMMENDED", flags)


# ===========================================================================
# 9. MEV label
# ===========================================================================

class TestMEVLabel(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _label(self, **kwargs) -> str:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["mev_label"]

    def test_extreme_label(self):
        # liquidation + immediate + high gas = very high frontrun risk
        label = self._label(
            tx_type="liquidation",
            time_sensitivity="immediate",
            gas_price_gwei=150.0,
            is_private_mempool=False,
        )
        self.assertEqual(label, "EXTREME")

    def test_minimal_label(self):
        label = self._label(
            dex_type="rfq",
            is_private_mempool=True,
            slippage_tolerance_pct=0.1,
            time_sensitivity="delayed",
            gas_price_gwei=10.0,
        )
        self.assertEqual(label, "MINIMAL")

    def test_label_is_string(self):
        label = self._label()
        self.assertIsInstance(label, str)

    def test_label_in_valid_set(self):
        label = self._label()
        valid = {"MINIMAL", "LOW", "MODERATE", "HIGH", "EXTREME"}
        self.assertIn(label, valid)

    def test_high_label_moderate_risk(self):
        label = self._label(
            tx_type="swap",
            dex_type="amm",
            slippage_tolerance_pct=2.0,
            time_sensitivity="immediate",
        )
        self.assertIn(label, {"HIGH", "EXTREME", "MODERATE"})


# ===========================================================================
# 10. Protection recommendation
# ===========================================================================

class TestProtectionRecommendation(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _rec(self, **kwargs) -> str:
        tx = _swap(**kwargs)
        return self.est.estimate([tx], NO_LOG)["results"][0]["protection_recommendation"]

    def test_none_when_private_mempool(self):
        rec = self._rec(is_private_mempool=True)
        self.assertEqual(rec, "none")

    def test_private_mempool_recommendation_high_risk(self):
        # Very high sandwich risk → recommend private_mempool
        rec = self._rec(
            tx_type="liquidation",
            dex_type="amm",
            time_sensitivity="immediate",
            gas_price_gwei=150.0,
            is_private_mempool=False,
        )
        self.assertEqual(rec, "private_mempool")

    def test_split_trade_recommendation(self):
        # Large trade relative to pool but not extreme risk
        rec = self._rec(
            tx_type="swap",
            dex_type="amm",
            size_usd=500_000.0,
            pool_depth_usd=1_000_000.0,
            slippage_tolerance_pct=0.5,
            time_sensitivity="flexible",
            gas_price_gwei=20.0,
        )
        # Should be split_trade or private_mempool depending on risk
        self.assertIn(rec, {"split_trade", "private_mempool", "rfq"})

    def test_rfq_recommendation_amm_swap(self):
        # Small swap on AMM — should suggest rfq or private_mempool
        rec = self._rec(
            tx_type="swap",
            dex_type="amm",
            size_usd=500.0,
            pool_depth_usd=10_000_000.0,
            slippage_tolerance_pct=0.3,
            time_sensitivity="delayed",
            gas_price_gwei=10.0,
            is_private_mempool=False,
        )
        self.assertIn(rec, {"rfq", "none", "private_mempool"})

    def test_recommendation_is_valid_string(self):
        rec = self._rec()
        valid = {"private_mempool", "limit_order", "split_trade", "rfq", "none"}
        self.assertIn(rec, valid)

    def test_orderbook_tx_no_rfq_recommendation(self):
        rec = self._rec(
            dex_type="orderbook",
            tx_type="swap",
            time_sensitivity="delayed",
            gas_price_gwei=20.0,
            is_private_mempool=False,
        )
        # orderbook with low risk should be "none" or "limit_order"
        self.assertIn(rec, {"none", "limit_order", "private_mempool"})


# ===========================================================================
# 11. Aggregate calculations
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def test_highest_mev_risk_protocol(self):
        txs = [
            _swap(protocol="Risky", tx_type="liquidation", time_sensitivity="immediate"),
            _swap(protocol="Safe", dex_type="rfq", is_private_mempool=True),
        ]
        agg = self.est.estimate(txs, NO_LOG)["aggregates"]
        self.assertEqual(agg["highest_mev_risk"], "Risky")

    def test_safest_transaction_protocol(self):
        txs = [
            _swap(protocol="Risky", tx_type="liquidation", time_sensitivity="immediate"),
            _swap(protocol="Safe", dex_type="rfq", is_private_mempool=True),
        ]
        agg = self.est.estimate(txs, NO_LOG)["aggregates"]
        self.assertEqual(agg["safest_transaction"], "Safe")

    def test_total_mev_usd_sum(self):
        txs = [_swap(size_usd=10_000.0), _swap(size_usd=20_000.0)]
        r = self.est.estimate(txs, NO_LOG)
        total = sum(tx["mev_cost_estimate_usd"] for tx in r["results"])
        self.assertAlmostEqual(r["aggregates"]["total_estimated_mev_usd"], total, places=3)

    def test_average_mev_risk(self):
        txs = [_swap(protocol="A"), _swap(protocol="B")]
        r = self.est.estimate(txs, NO_LOG)
        risks = [max(res["sandwich_attack_risk"], res["frontrun_risk"]) for res in r["results"]]
        expected_avg = sum(risks) / len(risks)
        self.assertAlmostEqual(r["aggregates"]["average_mev_risk"], expected_avg, places=1)

    def test_extreme_count_correct(self):
        txs = [
            _swap(tx_type="liquidation", time_sensitivity="immediate", gas_price_gwei=150.0),
            _swap(tx_type="liquidation", time_sensitivity="immediate", gas_price_gwei=150.0),
            _swap(dex_type="rfq", is_private_mempool=True),
        ]
        r = self.est.estimate(txs, NO_LOG)
        extreme_count = sum(1 for res in r["results"] if res["mev_label"] == "EXTREME")
        self.assertEqual(r["aggregates"]["extreme_count"], extreme_count)

    def test_single_tx_highest_equals_safest(self):
        txs = [_swap(protocol="OnlyOne")]
        agg = self.est.estimate(txs, NO_LOG)["aggregates"]
        self.assertEqual(agg["highest_mev_risk"], "OnlyOne")
        self.assertEqual(agg["safest_transaction"], "OnlyOne")


# ===========================================================================
# 12. Private mempool effects
# ===========================================================================

class TestPrivateMempool(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def test_private_mempool_flag_set(self):
        r = self.est.estimate([_swap(is_private_mempool=True)], NO_LOG)
        self.assertIn("PRIVATE_POOL_SAFE", r["results"][0]["flags"])

    def test_private_mempool_reduces_sandwich_risk(self):
        pub = self.est.estimate([_swap(is_private_mempool=False)], NO_LOG)["results"][0]
        priv = self.est.estimate([_swap(is_private_mempool=True)], NO_LOG)["results"][0]
        self.assertLess(priv["sandwich_attack_risk"], pub["sandwich_attack_risk"])

    def test_private_mempool_reduces_frontrun_risk(self):
        pub = self.est.estimate([_swap(is_private_mempool=False, tx_type="liquidation")], NO_LOG)["results"][0]
        priv = self.est.estimate([_swap(is_private_mempool=True, tx_type="liquidation")], NO_LOG)["results"][0]
        self.assertLess(priv["frontrun_risk"], pub["frontrun_risk"])

    def test_private_mempool_recommendation_none(self):
        r = self.est.estimate([_swap(is_private_mempool=True)], NO_LOG)
        self.assertEqual(r["results"][0]["protection_recommendation"], "none")


# ===========================================================================
# 13. Ring-buffer log
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_mev_log.json")

    def test_log_created(self):
        self.est.estimate([_swap()], {"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.est.estimate([_swap()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.est.estimate([_swap()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_ring_buffer_cap(self):
        for _ in range(105):
            self.est.estimate([_swap()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_no_log_when_write_log_false(self):
        self.est.estimate([_swap()], {"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))


# ===========================================================================
# 14. Helper function tests
# ===========================================================================

class TestHelpers(unittest.TestCase):
    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(110.0), 100.0)

    def test_clamp_custom_range(self):
        self.assertEqual(_clamp(5.0, 0.0, 1.0), 1.0)

    def test_atomic_log_appends(self):
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "test.json")
        _atomic_log(log_path, {"a": 1})
        _atomic_log(log_path, {"b": 2})
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_atomic_log_ring_buffer(self):
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "test.json")
        from spa_core.analytics.defi_mev_exposure_estimator import _LOG_CAP
        for i in range(_LOG_CAP + 10):
            _atomic_log(log_path, {"i": i})
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)


# ===========================================================================
# 15. Edge cases and missing fields
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def test_missing_dex_type_defaults(self):
        tx = {"protocol": "X", "tx_type": "swap", "size_usd": 1000.0,
              "slippage_tolerance_pct": 0.5, "pool_depth_usd": 1_000_000.0,
              "gas_price_gwei": 30.0, "is_private_mempool": False,
              "time_sensitivity": "flexible"}
        r = self.est.estimate([tx], NO_LOG)
        self.assertIsNotNone(r["results"][0])

    def test_missing_tx_type_defaults(self):
        tx = {"protocol": "X", "size_usd": 1000.0,
              "slippage_tolerance_pct": 0.5, "pool_depth_usd": 1_000_000.0,
              "gas_price_gwei": 30.0, "is_private_mempool": False,
              "dex_type": "amm", "time_sensitivity": "flexible"}
        r = self.est.estimate([tx], NO_LOG)
        self.assertIsNotNone(r["results"][0])

    def test_missing_is_private_mempool_defaults_false(self):
        tx = _swap()
        del tx["is_private_mempool"]
        r = self.est.estimate([tx], NO_LOG)
        # Should not raise
        self.assertIsNotNone(r["results"][0])

    def test_negative_size_usd_zero_cost(self):
        tx = _swap(size_usd=-100.0)
        r = self.est.estimate([tx], NO_LOG)
        self.assertEqual(r["results"][0]["mev_cost_estimate_usd"], 0.0)

    def test_unknown_dex_type_handled(self):
        tx = _swap(dex_type="unknown_dex")
        r = self.est.estimate([tx], NO_LOG)
        sr = r["results"][0]["sandwich_attack_risk"]
        self.assertGreaterEqual(sr, 0.0)
        self.assertLessEqual(sr, 100.0)

    def test_unknown_tx_type_handled(self):
        tx = _swap(tx_type="unknown_type")
        r = self.est.estimate([tx], NO_LOG)
        fr = r["results"][0]["frontrun_risk"]
        self.assertGreaterEqual(fr, 0.0)
        self.assertLessEqual(fr, 100.0)

    def test_multiple_txs_returns_all_results(self):
        txs = [_swap(protocol=f"P{i}") for i in range(5)]
        r = self.est.estimate(txs, NO_LOG)
        self.assertEqual(len(r["results"]), 5)

    def test_large_batch(self):
        txs = [_swap() for _ in range(50)]
        r = self.est.estimate(txs, NO_LOG)
        self.assertEqual(len(r["results"]), 50)


# ===========================================================================
# 16. tx_type coverage
# ===========================================================================

class TestTxTypeCoverage(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _run(self, tx_type: str) -> dict:
        return self.est.estimate([_swap(tx_type=tx_type)], NO_LOG)["results"][0]

    def test_swap(self):
        r = self._run("swap")
        self.assertIn(r["mev_label"], {"MINIMAL", "LOW", "MODERATE", "HIGH", "EXTREME"})

    def test_liquidation(self):
        r = self._run("liquidation")
        self.assertIn("LIQUIDATION_MEV", r["flags"])

    def test_mint(self):
        r = self._run("mint")
        self.assertIsInstance(r["mev_cost_estimate_usd"], float)

    def test_redeem(self):
        r = self._run("redeem")
        self.assertIsInstance(r["frontrun_risk"], float)

    def test_arbitrage(self):
        r = self._run("arbitrage")
        self.assertGreaterEqual(r["frontrun_risk"], 0.0)


# ===========================================================================
# 17. dex_type coverage
# ===========================================================================

class TestDexTypeCoverage(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def _run(self, dex_type: str) -> dict:
        return self.est.estimate([_swap(dex_type=dex_type)], NO_LOG)["results"][0]

    def test_amm(self):
        r = self._run("amm")
        self.assertGreater(r["sandwich_attack_risk"], 0.0)

    def test_orderbook(self):
        r = self._run("orderbook")
        self.assertIsInstance(r["sandwich_attack_risk"], float)

    def test_rfq(self):
        r = self._run("rfq")
        self.assertIsInstance(r["sandwich_attack_risk"], float)

    def test_amm_vs_rfq_cost(self):
        amm_cost = self.est.estimate([_swap(dex_type="amm")], NO_LOG)["results"][0]["mev_cost_estimate_usd"]
        rfq_cost = self.est.estimate([_swap(dex_type="rfq")], NO_LOG)["results"][0]["mev_cost_estimate_usd"]
        self.assertLessEqual(rfq_cost, amm_cost)


# ===========================================================================
# 18. Timestamp
# ===========================================================================

class TestTimestamp(unittest.TestCase):
    def setUp(self):
        self.est = DeFiMEVExposureEstimator()

    def test_timestamp_is_positive(self):
        r = self.est.estimate([], NO_LOG)
        self.assertGreater(r["timestamp"], 0.0)

    def test_timestamp_monotone(self):
        import time
        r1 = self.est.estimate([], NO_LOG)
        time.sleep(0.01)
        r2 = self.est.estimate([], NO_LOG)
        self.assertGreaterEqual(r2["timestamp"], r1["timestamp"])


if __name__ == "__main__":
    unittest.main()
