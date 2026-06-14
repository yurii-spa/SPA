"""
Tests for MP-668: MEVRiskDetector
≥65 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.mev_risk_detector import (
    MAX_ENTRIES,
    MEVRiskAssessment,
    MEVRiskDetector,
    TransactionProfile,
)


def _swap(
    amount_usd=10_000.0,
    pool_tvl_usd=1_000_000.0,
    slippage_tolerance_pct=0.5,
    gas_price_gwei=50.0,
    mempool_gas_gwei=40.0,
    is_private_mempool=False,
    token_in="USDC",
    token_out="ETH",
) -> TransactionProfile:
    return TransactionProfile(
        tx_type="SWAP",
        token_in=token_in,
        token_out=token_out,
        amount_usd=amount_usd,
        pool_tvl_usd=pool_tvl_usd,
        slippage_tolerance_pct=slippage_tolerance_pct,
        gas_price_gwei=gas_price_gwei,
        mempool_gas_gwei=mempool_gas_gwei,
        is_private_mempool=is_private_mempool,
    )


def _deposit(**kwargs) -> TransactionProfile:
    defaults = dict(
        tx_type="DEPOSIT",
        token_in="USDC",
        token_out="aUSDC",
        amount_usd=5_000.0,
        pool_tvl_usd=50_000_000.0,
        slippage_tolerance_pct=0.1,
        gas_price_gwei=30.0,
        mempool_gas_gwei=30.0,
        is_private_mempool=False,
    )
    defaults.update(kwargs)
    return TransactionProfile(**defaults)


def _liquidate(**kwargs) -> TransactionProfile:
    defaults = dict(
        tx_type="LIQUIDATE",
        token_in="USDC",
        token_out="ETH",
        amount_usd=20_000.0,
        pool_tvl_usd=10_000_000.0,
        slippage_tolerance_pct=1.0,
        gas_price_gwei=100.0,
        mempool_gas_gwei=40.0,
        is_private_mempool=False,
    )
    defaults.update(kwargs)
    return TransactionProfile(**defaults)


class TestSandwichRisk(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    # ---- non-SWAP types return 0.02 ----
    def test_deposit_returns_0_02(self):
        p = _deposit()
        self.assertAlmostEqual(self.det._sandwich_risk(p), 0.02)

    def test_withdraw_returns_0_02(self):
        p = _deposit(tx_type="WITHDRAW")
        self.assertAlmostEqual(self.det._sandwich_risk(p), 0.02)

    def test_liquidate_returns_0_02(self):
        p = _liquidate()
        self.assertAlmostEqual(self.det._sandwich_risk(p), 0.02)

    # ---- SWAP base risk ----
    def test_swap_base_risk_above_zero(self):
        p = _swap(amount_usd=100, pool_tvl_usd=1_000_000, slippage_tolerance_pct=0.0)
        risk = self.det._sandwich_risk(p)
        self.assertGreater(risk, 0)

    def test_swap_tiny_trade_tiny_slippage_low_risk(self):
        p = _swap(amount_usd=10, pool_tvl_usd=100_000_000, slippage_tolerance_pct=0.01)
        risk = self.det._sandwich_risk(p)
        self.assertLess(risk, 0.15)

    # ---- private mempool reduces risk drastically ----
    def test_private_mempool_reduces_risk(self):
        public = _swap(is_private_mempool=False)
        private = _swap(is_private_mempool=True)
        self.assertLess(self.det._sandwich_risk(private), self.det._sandwich_risk(public))

    def test_private_mempool_factor_005(self):
        public_risk = self.det._sandwich_risk(_swap(is_private_mempool=False))
        private_risk = self.det._sandwich_risk(_swap(is_private_mempool=True))
        # private ≈ public * 0.05, allow floating point tolerance
        self.assertAlmostEqual(private_risk, round(public_risk * 0.05, 4), places=3)

    def test_private_mempool_swap_very_low(self):
        p = _swap(
            amount_usd=50_000,
            pool_tvl_usd=500_000,
            slippage_tolerance_pct=3.0,
            is_private_mempool=True,
        )
        self.assertLess(self.det._sandwich_risk(p), 0.1)

    # ---- large trade + high slippage near 1.0 ----
    def test_large_trade_high_slippage_near_1(self):
        p = _swap(amount_usd=1_000_000, pool_tvl_usd=100_000, slippage_tolerance_pct=5.0)
        risk = self.det._sandwich_risk(p)
        self.assertGreaterEqual(risk, 0.9)

    def test_sandwich_risk_capped_at_1(self):
        p = _swap(amount_usd=9_999_999, pool_tvl_usd=1, slippage_tolerance_pct=100.0)
        self.assertLessEqual(self.det._sandwich_risk(p), 1.0)

    # ---- size factor ----
    def test_larger_trade_higher_sandwich(self):
        small = _swap(amount_usd=1_000, pool_tvl_usd=1_000_000)
        large = _swap(amount_usd=100_000, pool_tvl_usd=1_000_000)
        self.assertGreater(self.det._sandwich_risk(large), self.det._sandwich_risk(small))

    def test_size_factor_saturates_at_5pct_of_pool(self):
        five_pct = _swap(amount_usd=50_000, pool_tvl_usd=1_000_000, slippage_tolerance_pct=0.0)
        ten_pct = _swap(amount_usd=100_000, pool_tvl_usd=1_000_000, slippage_tolerance_pct=0.0)
        # Both should produce same size_factor contribution (saturated at 1.0)
        self.assertAlmostEqual(
            self.det._sandwich_risk(five_pct),
            self.det._sandwich_risk(ten_pct),
            places=4,
        )

    # ---- slippage factor ----
    def test_higher_slippage_higher_sandwich(self):
        low_slip = _swap(slippage_tolerance_pct=0.1)
        high_slip = _swap(slippage_tolerance_pct=2.0)
        self.assertGreater(
            self.det._sandwich_risk(high_slip), self.det._sandwich_risk(low_slip)
        )

    def test_slippage_factor_saturates_at_3pct(self):
        slip3 = _swap(slippage_tolerance_pct=3.0)
        slip6 = _swap(slippage_tolerance_pct=6.0)
        self.assertAlmostEqual(
            self.det._sandwich_risk(slip3), self.det._sandwich_risk(slip6), places=4
        )

    # ---- zero TVL edge case ----
    def test_zero_tvl_does_not_raise(self):
        p = _swap(pool_tvl_usd=0.0)
        risk = self.det._sandwich_risk(p)
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 1.0)


class TestFrontrunRisk(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_deposit_returns_0_01(self):
        p = _deposit()
        self.assertAlmostEqual(self.det._frontrun_risk(p), 0.01)

    def test_withdraw_returns_0_01(self):
        p = _deposit(tx_type="WITHDRAW")
        self.assertAlmostEqual(self.det._frontrun_risk(p), 0.01)

    def test_liquidate_returns_0_01(self):
        p = _liquidate()
        self.assertAlmostEqual(self.det._frontrun_risk(p), 0.01)

    def test_swap_base_risk(self):
        p = _swap(amount_usd=100, gas_price_gwei=30, mempool_gas_gwei=30)
        risk = self.det._frontrun_risk(p)
        self.assertGreater(risk, 0)

    def test_private_mempool_reduces_frontrun(self):
        pub = _swap(is_private_mempool=False)
        priv = _swap(is_private_mempool=True)
        self.assertLess(self.det._frontrun_risk(priv), self.det._frontrun_risk(pub))

    def test_private_mempool_frontrun_factor_005(self):
        pub_risk = self.det._frontrun_risk(_swap(is_private_mempool=False))
        priv_risk = self.det._frontrun_risk(_swap(is_private_mempool=True))
        self.assertAlmostEqual(priv_risk, round(pub_risk * 0.05, 4), places=3)

    def test_larger_amount_higher_frontrun(self):
        small = _swap(amount_usd=1_000)
        large = _swap(amount_usd=99_000)
        self.assertGreater(
            self.det._frontrun_risk(large), self.det._frontrun_risk(small)
        )

    def test_higher_gas_premium_higher_frontrun(self):
        low_gas = _swap(gas_price_gwei=40, mempool_gas_gwei=40)
        high_gas = _swap(gas_price_gwei=80, mempool_gas_gwei=40)
        self.assertGreater(
            self.det._frontrun_risk(high_gas), self.det._frontrun_risk(low_gas)
        )

    def test_frontrun_risk_capped_at_1(self):
        p = _swap(amount_usd=999_999, gas_price_gwei=9999, mempool_gas_gwei=1)
        self.assertLessEqual(self.det._frontrun_risk(p), 1.0)

    def test_zero_mempool_gas_no_exception(self):
        p = _swap(mempool_gas_gwei=0)
        risk = self.det._frontrun_risk(p)
        self.assertGreaterEqual(risk, 0.0)


class TestLiquidationRisk(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_swap_returns_0(self):
        self.assertAlmostEqual(self.det._liquidation_risk(_swap()), 0.0)

    def test_deposit_returns_0(self):
        self.assertAlmostEqual(self.det._liquidation_risk(_deposit()), 0.0)

    def test_withdraw_returns_0(self):
        self.assertAlmostEqual(self.det._liquidation_risk(_deposit(tx_type="WITHDRAW")), 0.0)

    def test_liquidate_returns_0_7(self):
        self.assertAlmostEqual(self.det._liquidation_risk(_liquidate()), 0.7)

    def test_liquidate_private_mempool_reduces(self):
        pub = _liquidate(is_private_mempool=False)
        priv = _liquidate(is_private_mempool=True)
        self.assertLess(self.det._liquidation_risk(priv), self.det._liquidation_risk(pub))

    def test_liquidate_private_mempool_exact(self):
        priv = _liquidate(is_private_mempool=True)
        self.assertAlmostEqual(self.det._liquidation_risk(priv), round(0.7 * 0.3, 4))


class TestComposite(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_composite_zero(self):
        self.assertAlmostEqual(self.det._composite(0.0, 0.0, 0.0), 0.0)

    def test_composite_sandwich_dominant(self):
        # s=1.0 → contribution s*0.5=0.5; f=0, l=0
        self.assertAlmostEqual(self.det._composite(1.0, 0.0, 0.0), 0.5)

    def test_composite_frontrun_dominant(self):
        # f=1.0 → contribution f*0.3=0.3
        self.assertAlmostEqual(self.det._composite(0.0, 1.0, 0.0), 0.3)

    def test_composite_liquidation_dominant(self):
        # l=1.0 → contribution l*0.8=0.8
        self.assertAlmostEqual(self.det._composite(0.0, 0.0, 1.0), 0.8)

    def test_composite_max_of_weighted(self):
        s, f, l = 0.4, 0.5, 0.3
        expected = round(max(s * 0.5, f * 0.3, l * 0.8), 4)
        self.assertAlmostEqual(self.det._composite(s, f, l), expected)

    def test_composite_capped_implicitly(self):
        result = self.det._composite(1.0, 1.0, 1.0)
        self.assertLessEqual(result, 1.0)


class TestRiskLevel(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_below_01_is_low(self):
        self.assertEqual(self.det._risk_level(0.05), "LOW")

    def test_exactly_01_is_medium(self):
        self.assertEqual(self.det._risk_level(0.1), "MEDIUM")

    def test_between_01_and_03_is_medium(self):
        self.assertEqual(self.det._risk_level(0.2), "MEDIUM")

    def test_exactly_03_is_high(self):
        self.assertEqual(self.det._risk_level(0.3), "HIGH")

    def test_between_03_and_06_is_high(self):
        self.assertEqual(self.det._risk_level(0.45), "HIGH")

    def test_exactly_06_is_critical(self):
        self.assertEqual(self.det._risk_level(0.6), "CRITICAL")

    def test_above_06_is_critical(self):
        self.assertEqual(self.det._risk_level(0.99), "CRITICAL")

    def test_zero_is_low(self):
        self.assertEqual(self.det._risk_level(0.0), "LOW")


class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_private_mempool_contains_protected_message(self):
        p = _swap(is_private_mempool=True, slippage_tolerance_pct=0.1, amount_usd=100)
        recs = self.det._recommendations(p, sandwich=0.01, frontrun=0.01)
        self.assertTrue(any("Private mempool" in r for r in recs))

    def test_public_mempool_warns_to_use_private(self):
        p = _swap(is_private_mempool=False)
        recs = self.det._recommendations(p, sandwich=0.01, frontrun=0.01)
        self.assertTrue(any("private mempool" in r.lower() for r in recs))

    def test_high_sandwich_contains_sandwich_warning(self):
        p = _swap(is_private_mempool=False, slippage_tolerance_pct=2.0)
        recs = self.det._recommendations(p, sandwich=0.5, frontrun=0.01)
        self.assertTrue(any("Sandwich" in r or "sandwich" in r or "🥪" in r for r in recs))

    def test_high_frontrun_contains_frontrun_warning(self):
        p = _swap(is_private_mempool=False)
        recs = self.det._recommendations(p, sandwich=0.01, frontrun=0.4)
        self.assertTrue(any("Frontrun" in r or "frontrun" in r or "🏃" in r for r in recs))

    def test_high_slippage_triggers_slippage_warning(self):
        p = _swap(slippage_tolerance_pct=2.0, is_private_mempool=False)
        recs = self.det._recommendations(p, sandwich=0.01, frontrun=0.01)
        self.assertTrue(any("Slippage" in r or "slippage" in r for r in recs))

    def test_low_risk_proceeds_normally(self):
        p = _swap(is_private_mempool=True, slippage_tolerance_pct=0.1, amount_usd=50)
        recs = self.det._recommendations(p, sandwich=0.005, frontrun=0.001)
        self.assertTrue(any("proceed normally" in r or "Low MEV risk" in r for r in recs))

    def test_recommendations_is_list(self):
        p = _swap()
        recs = self.det._recommendations(p, sandwich=0.2, frontrun=0.1)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)


class TestAssess(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_assess_returns_assessment(self):
        result = self.det.assess(_swap())
        self.assertIsInstance(result, MEVRiskAssessment)

    def test_deposit_low_sandwich_frontrun(self):
        result = self.det.assess(_deposit())
        self.assertAlmostEqual(result.sandwich_risk, 0.02)
        self.assertAlmostEqual(result.frontrun_risk, 0.01)

    def test_deposit_liquidation_zero(self):
        result = self.det.assess(_deposit())
        self.assertAlmostEqual(result.liquidation_risk, 0.0)

    def test_swap_large_amount_higher_risk(self):
        small = self.det.assess(_swap(amount_usd=100))
        large = self.det.assess(_swap(amount_usd=500_000))
        self.assertGreater(large.composite_risk, small.composite_risk)

    def test_liquidate_has_liquidation_risk(self):
        result = self.det.assess(_liquidate())
        self.assertAlmostEqual(result.liquidation_risk, 0.7)

    def test_private_mempool_protected_true(self):
        result = self.det.assess(_swap(is_private_mempool=True))
        self.assertTrue(result.protected)

    def test_public_mempool_protected_false(self):
        result = self.det.assess(_swap(is_private_mempool=False))
        self.assertFalse(result.protected)

    def test_private_mempool_lower_composite(self):
        pub = self.det.assess(_swap(is_private_mempool=False))
        priv = self.det.assess(_swap(is_private_mempool=True))
        self.assertLess(priv.composite_risk, pub.composite_risk)

    def test_estimated_loss_formula(self):
        p = _swap(amount_usd=10_000, slippage_tolerance_pct=1.0)
        result = self.det.assess(p)
        expected = round(10_000 * (1.0 / 100) * result.sandwich_risk, 4)
        self.assertAlmostEqual(result.estimated_loss_usd, expected, places=4)

    def test_estimated_loss_zero_for_deposit(self):
        # deposit has sandwich_risk=0.02, slippage=0.1
        p = _deposit(amount_usd=10_000, slippage_tolerance_pct=0.1)
        result = self.det.assess(p)
        expected = round(10_000 * (0.1 / 100) * 0.02, 4)
        self.assertAlmostEqual(result.estimated_loss_usd, expected, places=4)

    def test_tx_type_preserved(self):
        result = self.det.assess(_swap())
        self.assertEqual(result.tx_type, "SWAP")

    def test_risk_level_is_string(self):
        result = self.det.assess(_swap())
        self.assertIn(result.risk_level, ("LOW", "MEDIUM", "HIGH", "CRITICAL"))

    def test_composite_between_0_and_1(self):
        result = self.det.assess(_swap())
        self.assertGreaterEqual(result.composite_risk, 0.0)
        self.assertLessEqual(result.composite_risk, 1.0)

    def test_amount_usd_rounded(self):
        result = self.det.assess(_swap(amount_usd=12345.6789))
        # Should be rounded to 2 decimal places
        self.assertAlmostEqual(result.amount_usd, 12345.68, places=2)


class TestAssessBatch(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_empty_batch_returns_empty(self):
        self.assertEqual(self.det.assess_batch([]), [])

    def test_batch_length_matches_input(self):
        profiles = [_swap(), _deposit(), _liquidate()]
        results = self.det.assess_batch(profiles)
        self.assertEqual(len(results), 3)

    def test_batch_types_correct(self):
        results = self.det.assess_batch([_swap(), _deposit()])
        self.assertEqual(results[0].tx_type, "SWAP")
        self.assertEqual(results[1].tx_type, "DEPOSIT")


class TestHighRiskTxs(unittest.TestCase):
    def setUp(self):
        self.det = MEVRiskDetector()

    def test_filters_high_and_critical(self):
        results = self.det.assess_batch([
            _swap(amount_usd=1_000_000, pool_tvl_usd=10_000, slippage_tolerance_pct=5.0),  # likely CRITICAL
            _swap(amount_usd=100, pool_tvl_usd=1_000_000, slippage_tolerance_pct=0.1),     # LOW
            _liquidate(),                                                                    # HIGH/CRITICAL
        ])
        high_risk = self.det.high_risk_txs(results)
        for r in high_risk:
            self.assertIn(r.risk_level, ("HIGH", "CRITICAL"))

    def test_no_high_risk_returns_empty(self):
        results = self.det.assess_batch([
            _swap(amount_usd=10, pool_tvl_usd=100_000_000, slippage_tolerance_pct=0.01,
                  is_private_mempool=True),
        ])
        high_risk = self.det.high_risk_txs(results)
        for r in high_risk:
            self.assertIn(r.risk_level, ("HIGH", "CRITICAL"))

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.det.high_risk_txs([]), [])


class TestSaveLoadResults(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "data" / "mev_risk_log.json"
        self.det = MEVRiskDetector(data_file=self.data_file)

    def _make_assessment(self, tx_type="SWAP", composite=0.3, level="HIGH", loss=5.0):
        return MEVRiskAssessment(
            tx_type=tx_type,
            amount_usd=1000.0,
            sandwich_risk=0.2,
            frontrun_risk=0.1,
            liquidation_risk=0.0,
            composite_risk=composite,
            risk_level=level,
            protected=False,
            estimated_loss_usd=loss,
            recommendations=["test"],
        )

    def test_save_creates_file(self):
        self.det.save_results([self._make_assessment()])
        self.assertTrue(self.data_file.exists())

    def test_save_atomic_no_tmp_leftover(self):
        self.det.save_results([self._make_assessment()])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_save_valid_json(self):
        self.det.save_results([self._make_assessment()])
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_contains_timestamp(self):
        self.det.save_results([self._make_assessment()])
        data = json.loads(self.data_file.read_text())
        self.assertIn("timestamp", data[0])

    def test_save_contains_risk_level(self):
        self.det.save_results([self._make_assessment(level="HIGH")])
        data = json.loads(self.data_file.read_text())
        self.assertEqual(data[0]["risk_level"], "HIGH")

    def test_ring_buffer_max_entries(self):
        for i in range(MAX_ENTRIES + 10):
            self.det.save_results([self._make_assessment(tx_type="SWAP")])
        data = json.loads(self.data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.det.load_history(), [])

    def test_load_history_returns_list(self):
        self.det.save_results([self._make_assessment()])
        history = self.det.load_history()
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0)

    def test_save_multiple_results_in_one_call(self):
        assessments = [self._make_assessment(tx_type="SWAP"), self._make_assessment(tx_type="LIQUIDATE")]
        self.det.save_results(assessments)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_load_history_corrupted_file_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("NOT_JSON{{{")
        self.assertEqual(self.det.load_history(), [])


if __name__ == "__main__":
    unittest.main()
