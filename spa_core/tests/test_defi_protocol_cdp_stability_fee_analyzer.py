"""
Tests for DeFiProtocolCdpStabilityFeeAnalyzer (MP-1082).
Run: python3 -m unittest spa_core.tests.test_defi_protocol_cdp_stability_fee_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_cdp_stability_fee_analyzer import (
    DeFiProtocolCdpStabilityFeeAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_data(**overrides):
    """Return a well-formed CDP data dict with sensible defaults."""
    base = {
        "protocol_name": "MakerDAO",
        "collateral_asset": "ETH",
        "collateral_value_usd": 300_000.0,
        "debt_usd": 100_000.0,
        "stability_fee_pct": 5.0,
        "liquidation_ratio_pct": 150.0,
        "current_price_usd": 3_000.0,
        "target_price_usd": 1.0,
        "surplus_buffer_usd": 50_000.0,
        "total_debt_ceiling_usd": 1_000_000.0,
        "debt_utilization_pct": 10.0,
    }
    base.update(overrides)
    return base


def _make_analyzer(tmp_dir=None):
    log_path = os.path.join(tmp_dir, "cdp_log.json") if tmp_dir else None
    return DeFiProtocolCdpStabilityFeeAnalyzer(log_path=log_path)


# ===========================================================================
# 1. Output Structure
# ===========================================================================

class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_returns_dict(self):
        result = self.a.analyze(_base_data())
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        result = self.a.analyze(_base_data())
        required = {
            "protocol_name", "collateral_asset",
            "collateralization_ratio_pct", "safe_debt_capacity_usd",
            "liquidation_price_usd", "fee_cost_usd_per_year",
            "cdp_health_score", "cdp_label",
        }
        self.assertEqual(required, required & result.keys())

    def test_protocol_name_passthrough(self):
        result = self.a.analyze(_base_data(protocol_name="Aave"))
        self.assertEqual(result["protocol_name"], "Aave")

    def test_collateral_asset_passthrough(self):
        result = self.a.analyze(_base_data(collateral_asset="wBTC"))
        self.assertEqual(result["collateral_asset"], "wBTC")

    def test_health_score_in_range(self):
        result = self.a.analyze(_base_data())
        self.assertGreaterEqual(result["cdp_health_score"], 0.0)
        self.assertLessEqual(result["cdp_health_score"], 100.0)

    def test_label_is_valid_string(self):
        result = self.a.analyze(_base_data())
        valid = {"FORTRESS_CDP", "SAFE", "WATCH", "DANGER", "NEAR_LIQUIDATION"}
        self.assertIn(result["cdp_label"], valid)

    def test_numeric_outputs_are_floats(self):
        result = self.a.analyze(_base_data())
        for key in ("collateralization_ratio_pct", "safe_debt_capacity_usd",
                    "liquidation_price_usd", "fee_cost_usd_per_year",
                    "cdp_health_score"):
            self.assertIsInstance(result[key], float, msg=key)

    def test_safe_debt_capacity_non_negative(self):
        result = self.a.analyze(_base_data())
        self.assertGreaterEqual(result["safe_debt_capacity_usd"], 0.0)

    def test_liquidation_price_non_negative(self):
        result = self.a.analyze(_base_data())
        self.assertGreaterEqual(result["liquidation_price_usd"], 0.0)

    def test_fee_cost_non_negative(self):
        result = self.a.analyze(_base_data())
        self.assertGreaterEqual(result["fee_cost_usd_per_year"], 0.0)


# ===========================================================================
# 2. Collateralization Ratio
# ===========================================================================

class TestCollateralizationRatio(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_basic_300_percent(self):
        r = self.a.analyze(_base_data(collateral_value_usd=300_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 300.0, places=2)

    def test_exact_150_percent(self):
        r = self.a.analyze(_base_data(collateral_value_usd=150_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 150.0, places=2)

    def test_exact_200_percent(self):
        r = self.a.analyze(_base_data(collateral_value_usd=200_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 200.0, places=2)

    def test_ratio_100_percent(self):
        r = self.a.analyze(_base_data(collateral_value_usd=100_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 100.0, places=2)

    def test_ratio_under_liquidation(self):
        r = self.a.analyze(_base_data(collateral_value_usd=130_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 130.0, places=2)

    def test_high_collateral(self):
        r = self.a.analyze(_base_data(collateral_value_usd=1_000_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 1000.0, places=2)

    def test_small_debt(self):
        r = self.a.analyze(_base_data(collateral_value_usd=100_000, debt_usd=1_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 10000.0, places=1)

    def test_fractional_ratio(self):
        r = self.a.analyze(_base_data(collateral_value_usd=175_000, debt_usd=100_000))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 175.0, places=2)

    def test_zero_debt_returns_zero(self):
        r = self.a.analyze(_base_data(debt_usd=0))
        self.assertEqual(r["collateralization_ratio_pct"], 0.0)

    def test_large_values(self):
        r = self.a.analyze(_base_data(collateral_value_usd=1e9, debt_usd=5e8))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 200.0, places=2)


# ===========================================================================
# 3. Safe Debt Capacity
# ===========================================================================

class TestSafeDebtCapacity(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_typical_capacity(self):
        # max_safe_debt = 300000 / 1.5 = 200000; capacity = 200000 - 100000 = 100000
        r = self.a.analyze(_base_data(
            collateral_value_usd=300_000, debt_usd=100_000, liquidation_ratio_pct=150
        ))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 100_000.0, places=2)

    def test_at_liquidation_threshold(self):
        # collateral=150k, debt=100k, liq=150%
        # max_safe_debt = 150000/1.5 = 100000; capacity = 0
        r = self.a.analyze(_base_data(
            collateral_value_usd=150_000, debt_usd=100_000, liquidation_ratio_pct=150
        ))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 0.0, places=2)

    def test_below_liquidation_returns_zero(self):
        # collateral=130k, debt=100k, liq=150%
        # max_safe_debt = 130000/1.5 = 86666; capacity = max(0, 86666-100000) = 0
        r = self.a.analyze(_base_data(
            collateral_value_usd=130_000, debt_usd=100_000, liquidation_ratio_pct=150
        ))
        self.assertEqual(r["safe_debt_capacity_usd"], 0.0)

    def test_higher_liq_ratio_reduces_capacity(self):
        r_150 = self.a.analyze(_base_data(liquidation_ratio_pct=150))
        r_200 = self.a.analyze(_base_data(liquidation_ratio_pct=200))
        self.assertGreater(r_150["safe_debt_capacity_usd"], r_200["safe_debt_capacity_usd"])

    def test_no_debt_full_capacity(self):
        # capacity = collateral / (liq/100) - 0 = 300000/1.5 = 200000
        r = self.a.analyze(_base_data(debt_usd=0))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 200_000.0, places=2)

    def test_200_pct_liq_ratio(self):
        # max_safe_debt = 300000/2.0 = 150000; capacity = 150000-100000 = 50000
        r = self.a.analyze(_base_data(liquidation_ratio_pct=200, debt_usd=100_000))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 50_000.0, places=2)

    def test_very_low_liq_ratio(self):
        # liq=110%: max_safe_debt = 300000/1.1 = 272727; capacity ~172727
        r = self.a.analyze(_base_data(liquidation_ratio_pct=110, debt_usd=100_000))
        expected = 300_000.0 / 1.1 - 100_000.0
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], expected, delta=1.0)

    def test_capacity_non_negative(self):
        for ratio in [100, 130, 150, 200, 300]:
            r = self.a.analyze(_base_data(
                collateral_value_usd=150_000, debt_usd=100_000, liquidation_ratio_pct=ratio
            ))
            self.assertGreaterEqual(r["safe_debt_capacity_usd"], 0.0)

    def test_exact_boundary(self):
        # collateral=200k, debt=100k, liq=200% → cap=0
        r = self.a.analyze(_base_data(
            collateral_value_usd=200_000, debt_usd=100_000, liquidation_ratio_pct=200
        ))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 0.0, places=4)

    def test_half_liq_ratio_large_cap(self):
        # liq=50%: max_safe_debt=300000/0.5=600000; cap=500000
        r = self.a.analyze(_base_data(liquidation_ratio_pct=50, debt_usd=100_000))
        self.assertAlmostEqual(r["safe_debt_capacity_usd"], 500_000.0, places=2)


# ===========================================================================
# 4. Liquidation Price
# ===========================================================================

class TestLiquidationPrice(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_basic_liquidation_price(self):
        # collateral=100 ETH (300k / 3000), debt=100k, liq=150%
        # liq_price = 100000 * 1.5 / 100 = 1500 USD
        r = self.a.analyze(_base_data(
            collateral_value_usd=300_000, debt_usd=100_000,
            current_price_usd=3_000, liquidation_ratio_pct=150
        ))
        self.assertAlmostEqual(r["liquidation_price_usd"], 1500.0, places=2)

    def test_liquidation_price_scales_with_debt(self):
        r1 = self.a.analyze(_base_data(debt_usd=100_000))
        r2 = self.a.analyze(_base_data(debt_usd=200_000))
        self.assertAlmostEqual(r2["liquidation_price_usd"], r1["liquidation_price_usd"] * 2, places=1)

    def test_higher_liq_ratio_higher_liq_price(self):
        r1 = self.a.analyze(_base_data(liquidation_ratio_pct=130))
        r2 = self.a.analyze(_base_data(liquidation_ratio_pct=170))
        self.assertGreater(r2["liquidation_price_usd"], r1["liquidation_price_usd"])

    def test_zero_debt_zero_liq_price(self):
        r = self.a.analyze(_base_data(debt_usd=0))
        self.assertEqual(r["liquidation_price_usd"], 0.0)

    def test_zero_collateral_zero_liq_price(self):
        r = self.a.analyze(_base_data(collateral_value_usd=0))
        self.assertEqual(r["liquidation_price_usd"], 0.0)

    def test_liq_price_less_than_current(self):
        # For a healthy CDP the liq price should be < current price
        r = self.a.analyze(_base_data(
            collateral_value_usd=300_000, debt_usd=100_000,
            current_price_usd=3_000, liquidation_ratio_pct=150
        ))
        self.assertLess(r["liquidation_price_usd"], 3_000.0)

    def test_liq_price_near_current_when_near_liq(self):
        # collateral=155k, debt=100k, liq=150%, current=3000
        # collateral_amount = 155000/3000 = 51.67
        # liq_price = 100000*1.5/51.67 = 2903
        r = self.a.analyze(_base_data(
            collateral_value_usd=155_000, debt_usd=100_000,
            current_price_usd=3_000, liquidation_ratio_pct=150
        ))
        expected = 100_000 * 1.5 / (155_000 / 3_000)
        self.assertAlmostEqual(r["liquidation_price_usd"], expected, places=2)

    def test_double_collateral_halves_liq_price(self):
        r1 = self.a.analyze(_base_data(collateral_value_usd=200_000))
        r2 = self.a.analyze(_base_data(collateral_value_usd=400_000))
        self.assertAlmostEqual(r1["liquidation_price_usd"], r2["liquidation_price_usd"] * 2, places=2)

    def test_liq_price_with_wbtc(self):
        # 10 wBTC at $60000 each = $600000; debt=$200000; liq=150%
        # collateral_amount=10; liq_price = 200000*1.5/10 = 30000
        r = self.a.analyze(_base_data(
            collateral_asset="wBTC",
            collateral_value_usd=600_000, debt_usd=200_000,
            current_price_usd=60_000, liquidation_ratio_pct=150
        ))
        self.assertAlmostEqual(r["liquidation_price_usd"], 30_000.0, places=1)

    def test_liq_price_100_pct_ratio(self):
        # liq=100%: liq_price = debt*1.0 / collateral_amount
        # collateral=300k, current=3000 → amount=100; debt=100k
        # liq_price = 100000 * 1.0 / 100 = 1000
        r = self.a.analyze(_base_data(
            collateral_value_usd=300_000, debt_usd=100_000,
            current_price_usd=3_000, liquidation_ratio_pct=100
        ))
        self.assertAlmostEqual(r["liquidation_price_usd"], 1_000.0, places=2)


# ===========================================================================
# 5. Fee Cost Calculations
# ===========================================================================

class TestFeeCalculations(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_5pct_fee_100k_debt(self):
        r = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=5.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 5_000.0, places=2)

    def test_zero_fee(self):
        r = self.a.analyze(_base_data(stability_fee_pct=0.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 0.0, places=4)

    def test_2pct_fee(self):
        r = self.a.analyze(_base_data(debt_usd=200_000, stability_fee_pct=2.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 4_000.0, places=2)

    def test_high_fee_rate(self):
        r = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 20_000.0, places=2)

    def test_fee_scales_with_debt(self):
        r1 = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=5.0))
        r2 = self.a.analyze(_base_data(debt_usd=200_000, stability_fee_pct=5.0))
        self.assertAlmostEqual(r2["fee_cost_usd_per_year"], r1["fee_cost_usd_per_year"] * 2, places=2)

    def test_fee_scales_with_rate(self):
        r1 = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=5.0))
        r2 = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=10.0))
        self.assertAlmostEqual(r2["fee_cost_usd_per_year"], r1["fee_cost_usd_per_year"] * 2, places=2)

    def test_zero_debt_zero_fee(self):
        r = self.a.analyze(_base_data(debt_usd=0, stability_fee_pct=10.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 0.0, places=4)

    def test_fractional_fee_pct(self):
        r = self.a.analyze(_base_data(debt_usd=100_000, stability_fee_pct=0.5))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 500.0, places=2)

    def test_large_debt_large_fee(self):
        r = self.a.analyze(_base_data(debt_usd=10_000_000, stability_fee_pct=3.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 300_000.0, places=2)

    def test_1pct_fee_50k_debt(self):
        r = self.a.analyze(_base_data(debt_usd=50_000, stability_fee_pct=1.0))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 500.0, places=2)


# ===========================================================================
# 6. Health Score
# ===========================================================================

class TestHealthScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_well_collateralized_high_score(self):
        # 400% collat ratio; liq=150% → big safety margin
        r = self.a.analyze(_base_data(
            collateral_value_usd=400_000, debt_usd=100_000,
            stability_fee_pct=2.0, debt_utilization_pct=10.0
        ))
        self.assertGreater(r["cdp_health_score"], 50.0)

    def test_near_liquidation_low_score(self):
        # collat ratio = 155% vs liq=150% → tiny safety margin
        r = self.a.analyze(_base_data(
            collateral_value_usd=155_000, debt_usd=100_000, stability_fee_pct=5.0
        ))
        self.assertLess(r["cdp_health_score"], 20.0)

    def test_no_debt_full_score(self):
        r = self.a.analyze(_base_data(debt_usd=0))
        self.assertEqual(r["cdp_health_score"], 100.0)

    def test_high_fee_lowers_score(self):
        r_low = self.a.analyze(_base_data(stability_fee_pct=1.0))
        r_high = self.a.analyze(_base_data(stability_fee_pct=20.0))
        self.assertGreater(r_low["cdp_health_score"], r_high["cdp_health_score"])

    def test_peg_deviation_lowers_score(self):
        # target=1.0, current=0.80 → 20% depeg
        r_ok = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_depeg = self.a.analyze(_base_data(current_price_usd=0.80, target_price_usd=1.0))
        self.assertGreater(r_ok["cdp_health_score"], r_depeg["cdp_health_score"])

    def test_high_utilization_lowers_score(self):
        r_low = self.a.analyze(_base_data(debt_utilization_pct=10.0))
        r_high = self.a.analyze(_base_data(debt_utilization_pct=95.0))
        self.assertGreater(r_low["cdp_health_score"], r_high["cdp_health_score"])

    def test_score_bounded_above(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd=1_000_000, debt_usd=1_000,
            stability_fee_pct=0.0, debt_utilization_pct=0.0
        ))
        self.assertLessEqual(r["cdp_health_score"], 100.0)

    def test_score_bounded_below(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd=100_000, debt_usd=1_000_000,
            stability_fee_pct=30.0, debt_utilization_pct=99.0
        ))
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)

    def test_higher_collat_higher_score(self):
        r1 = self.a.analyze(_base_data(collateral_value_usd=200_000))
        r2 = self.a.analyze(_base_data(collateral_value_usd=500_000))
        self.assertGreater(r2["cdp_health_score"], r1["cdp_health_score"])

    def test_surplus_buffer_improves_score(self):
        r_no_buf = self.a.analyze(_base_data(surplus_buffer_usd=0.0))
        r_buf = self.a.analyze(_base_data(surplus_buffer_usd=100_000.0))
        self.assertGreaterEqual(r_buf["cdp_health_score"], r_no_buf["cdp_health_score"])

    def test_95pct_utilization_penalty(self):
        r = self.a.analyze(_base_data(debt_utilization_pct=95.0))
        r_low = self.a.analyze(_base_data(debt_utilization_pct=20.0))
        self.assertGreater(r_low["cdp_health_score"], r["cdp_health_score"])

    def test_at_liquidation_very_low(self):
        # exactly at liquidation: collat_ratio == liq_ratio → safety_margin=0
        r = self.a.analyze(_base_data(
            collateral_value_usd=150_000, debt_usd=100_000,
            liquidation_ratio_pct=150, stability_fee_pct=0, debt_utilization_pct=0
        ))
        self.assertLessEqual(r["cdp_health_score"], 10.0)

    def test_below_liquidation_near_zero(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd=100_000, debt_usd=100_000,
            liquidation_ratio_pct=150, stability_fee_pct=0
        ))
        self.assertLessEqual(r["cdp_health_score"], 5.0)

    def test_score_increases_with_safety_margin(self):
        scores = []
        for cv in [160_000, 200_000, 250_000, 300_000, 400_000]:
            r = self.a.analyze(_base_data(collateral_value_usd=cv, debt_usd=100_000))
            scores.append(r["cdp_health_score"])
        # Scores should be monotonically non-decreasing
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_zero_fee_and_low_utilization_no_penalties(self):
        r = self.a.analyze(_base_data(
            stability_fee_pct=0, debt_utilization_pct=0,
            collateral_value_usd=400_000, debt_usd=100_000,
            surplus_buffer_usd=0
        ))
        # safety margin = (400% - 150%) / 150% * 100 = 166.67%
        # base = min(100, 166.67 * 0.65) = 100  but capped at 100
        # However with no debt: collat_ratio = 400; liq = 150; margin = 250/150*100 = 166.67%
        self.assertGreaterEqual(r["cdp_health_score"], 50.0)


# ===========================================================================
# 7. Labels
# ===========================================================================

class TestLabels(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def _label_for_score(self, score):
        return DeFiProtocolCdpStabilityFeeAnalyzer._assign_label(score)

    def test_score_100_fortress(self):
        self.assertEqual(self._label_for_score(100.0), "FORTRESS_CDP")

    def test_score_80_fortress(self):
        self.assertEqual(self._label_for_score(80.0), "FORTRESS_CDP")

    def test_score_79_safe(self):
        self.assertEqual(self._label_for_score(79.9), "SAFE")

    def test_score_60_safe(self):
        self.assertEqual(self._label_for_score(60.0), "SAFE")

    def test_score_59_watch(self):
        self.assertEqual(self._label_for_score(59.9), "WATCH")

    def test_score_40_watch(self):
        self.assertEqual(self._label_for_score(40.0), "WATCH")

    def test_score_39_danger(self):
        self.assertEqual(self._label_for_score(39.9), "DANGER")

    def test_score_20_danger(self):
        self.assertEqual(self._label_for_score(20.0), "DANGER")

    def test_score_19_near_liquidation(self):
        self.assertEqual(self._label_for_score(19.9), "NEAR_LIQUIDATION")

    def test_score_0_near_liquidation(self):
        self.assertEqual(self._label_for_score(0.0), "NEAR_LIQUIDATION")

    def test_no_debt_fortress_label(self):
        r = self.a.analyze(_base_data(debt_usd=0))
        self.assertEqual(r["cdp_label"], "FORTRESS_CDP")

    def test_well_collat_fortress_or_safe(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd=600_000, debt_usd=100_000,
            stability_fee_pct=1.0, debt_utilization_pct=5.0
        ))
        self.assertIn(r["cdp_label"], {"FORTRESS_CDP", "SAFE"})

    def test_near_liq_cdp_label(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd=152_000, debt_usd=100_000,
            liquidation_ratio_pct=150, stability_fee_pct=10.0,
            debt_utilization_pct=90.0
        ))
        self.assertIn(r["cdp_label"], {"NEAR_LIQUIDATION", "DANGER"})

    def test_all_valid_labels_returned(self):
        valid = {"FORTRESS_CDP", "SAFE", "WATCH", "DANGER", "NEAR_LIQUIDATION"}
        for col in [152_000, 165_000, 180_000, 250_000, 600_000]:
            r = self.a.analyze(_base_data(
                collateral_value_usd=col, debt_usd=100_000,
                stability_fee_pct=5.0, debt_utilization_pct=80.0
            ))
            self.assertIn(r["cdp_label"], valid)

    def test_exact_boundary_80(self):
        self.assertEqual(self._label_for_score(80.0), "FORTRESS_CDP")

    def test_exact_boundary_60(self):
        self.assertEqual(self._label_for_score(60.0), "SAFE")

    def test_exact_boundary_40(self):
        self.assertEqual(self._label_for_score(40.0), "WATCH")

    def test_exact_boundary_20(self):
        self.assertEqual(self._label_for_score(20.0), "DANGER")


# ===========================================================================
# 8. Peg Deviation
# ===========================================================================

class TestPegDeviation(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_no_deviation_no_penalty(self):
        r = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_ref = self.a.analyze(_base_data(current_price_usd=3.0, target_price_usd=3.0))
        # Both should have same peg penalty (zero)
        self.assertEqual(r["cdp_health_score"], r_ref["cdp_health_score"])

    def test_5pct_depeg_penalty(self):
        r_ok = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_depeg = self.a.analyze(_base_data(current_price_usd=0.95, target_price_usd=1.0))
        self.assertGreater(r_ok["cdp_health_score"], r_depeg["cdp_health_score"])

    def test_10pct_depeg_10pt_penalty(self):
        r_ok = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_depeg = self.a.analyze(_base_data(current_price_usd=0.90, target_price_usd=1.0))
        diff = r_ok["cdp_health_score"] - r_depeg["cdp_health_score"]
        self.assertAlmostEqual(diff, 20.0, delta=2.0)

    def test_upward_deviation_also_penalized(self):
        # Current above target (e.g. premium): same abs deviation
        r_ok = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_premium = self.a.analyze(_base_data(current_price_usd=1.10, target_price_usd=1.0))
        self.assertGreater(r_ok["cdp_health_score"], r_premium["cdp_health_score"])

    def test_large_depeg_capped_at_20(self):
        # 50% deviation → peg_dev * 2 = 100, capped at 20
        r_nodep = self.a.analyze(_base_data(current_price_usd=1.0, target_price_usd=1.0))
        r_dep = self.a.analyze(_base_data(current_price_usd=0.5, target_price_usd=1.0))
        diff = r_nodep["cdp_health_score"] - r_dep["cdp_health_score"]
        self.assertAlmostEqual(diff, 20.0, delta=1.0)

    def test_symmetric_deviation(self):
        r_low = self.a.analyze(_base_data(current_price_usd=0.9, target_price_usd=1.0))
        r_high = self.a.analyze(_base_data(current_price_usd=1.1, target_price_usd=1.0))
        self.assertAlmostEqual(r_low["cdp_health_score"], r_high["cdp_health_score"], places=3)

    def test_non_pegged_asset_target_equals_current(self):
        # ETH has no meaningful peg - set current=target
        r = self.a.analyze(_base_data(current_price_usd=3000, target_price_usd=3000))
        # No peg penalty
        self.assertGreater(r["cdp_health_score"], 0.0)

    def test_zero_target_price_no_crash(self):
        r = self.a.analyze(_base_data(target_price_usd=0.0))
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)


# ===========================================================================
# 9. Debt Utilization
# ===========================================================================

class TestDebtUtilization(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_low_utilization_no_penalty(self):
        r = self.a.analyze(_base_data(debt_utilization_pct=30.0))
        r_ref = self.a.analyze(_base_data(debt_utilization_pct=0.0))
        self.assertEqual(r["cdp_health_score"], r_ref["cdp_health_score"])

    def test_70_pct_utilization_small_penalty(self):
        r_low = self.a.analyze(_base_data(debt_utilization_pct=30.0))
        r_high = self.a.analyze(_base_data(debt_utilization_pct=70.0))
        self.assertGreater(r_low["cdp_health_score"], r_high["cdp_health_score"])

    def test_90_pct_utilization_larger_penalty(self):
        r_low = self.a.analyze(_base_data(debt_utilization_pct=30.0))
        r_high = self.a.analyze(_base_data(debt_utilization_pct=90.0))
        diff = r_low["cdp_health_score"] - r_high["cdp_health_score"]
        self.assertGreater(diff, 10.0)

    def test_95_pct_utilization_max_penalty(self):
        r_low = self.a.analyze(_base_data(debt_utilization_pct=10.0))
        r_max = self.a.analyze(_base_data(debt_utilization_pct=95.0))
        diff = r_low["cdp_health_score"] - r_max["cdp_health_score"]
        self.assertGreater(diff, 15.0)

    def test_over_100_utilization_no_crash(self):
        r = self.a.analyze(_base_data(debt_utilization_pct=110.0))
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)


# ===========================================================================
# 10. Edge Cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_all_zeros(self):
        r = self.a.analyze({
            "protocol_name": "", "collateral_asset": "",
            "collateral_value_usd": 0, "debt_usd": 0,
            "stability_fee_pct": 0, "liquidation_ratio_pct": 0,
            "current_price_usd": 0, "target_price_usd": 0,
            "surplus_buffer_usd": 0, "total_debt_ceiling_usd": 0,
            "debt_utilization_pct": 0,
        })
        self.assertIsInstance(r, dict)
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)

    def test_empty_dict_no_crash(self):
        r = self.a.analyze({})
        self.assertIsInstance(r, dict)

    def test_string_numeric_values(self):
        r = self.a.analyze(_base_data(
            collateral_value_usd="300000",
            debt_usd="100000",
            stability_fee_pct="5.0",
        ))
        self.assertAlmostEqual(r["collateralization_ratio_pct"], 300.0, places=2)

    def test_zero_current_price(self):
        r = self.a.analyze(_base_data(current_price_usd=0))
        self.assertEqual(r["liquidation_price_usd"], 0.0)

    def test_zero_liq_ratio(self):
        r = self.a.analyze(_base_data(liquidation_ratio_pct=0))
        self.assertIsInstance(r, dict)

    def test_very_high_collateral(self):
        r = self.a.analyze(_base_data(collateral_value_usd=1e12, debt_usd=1_000))
        self.assertGreater(r["collateralization_ratio_pct"], 1e8)

    def test_very_small_stability_fee(self):
        r = self.a.analyze(_base_data(stability_fee_pct=0.001))
        self.assertAlmostEqual(r["fee_cost_usd_per_year"], 1.0, places=0)

    def test_missing_keys_use_defaults(self):
        r = self.a.analyze({"protocol_name": "TestProto", "debt_usd": 50_000})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["protocol_name"], "TestProto")

    def test_negative_surplus_buffer_handled(self):
        r = self.a.analyze(_base_data(surplus_buffer_usd=-1000))
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)

    def test_multiple_calls_independent(self):
        r1 = self.a.analyze(_base_data(debt_usd=100_000))
        r2 = self.a.analyze(_base_data(debt_usd=200_000))
        self.assertNotEqual(r1["fee_cost_usd_per_year"], r2["fee_cost_usd_per_year"])


# ===========================================================================
# 11. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "cdp_log.json")
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer(log_path=self.log_path)

    def test_log_file_created(self):
        self.a.analyze_and_log(_base_data())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_result_keys(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        entry = data[0]
        self.assertIn("cdp_label", entry)
        self.assertIn("cdp_health_score", entry)

    def test_log_entry_has_logged_at(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("_logged_at", data[0])

    def test_multiple_entries_accumulate(self):
        for _ in range(5):
            self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            self.a.analyze_and_log(_base_data(debt_usd=float(i + 1) * 1000))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(110):
            self.a.analyze_and_log(_base_data(debt_usd=float(i + 1) * 1000))
        with open(self.log_path) as f:
            data = json.load(f)
        # Last entry should be from i=109 → debt=110000
        self.assertAlmostEqual(data[-1]["fee_cost_usd_per_year"], 110_000 * 5.0 / 100, places=0)

    def test_log_atomic_tmp_cleaned_up(self):
        self.a.analyze_and_log(_base_data())
        tmp = self.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_analyze_returns_same_as_analyze(self):
        r_plain = self.a.analyze(_base_data())
        r_log = self.a.analyze_and_log(_base_data())
        for key in r_plain:
            self.assertEqual(r_plain[key], r_log[key])

    def test_corrupt_log_file_recovers(self):
        with open(self.log_path, "w") as f:
            f.write("not-json")
        # Should not crash; should overwrite with fresh log
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ===========================================================================
# 12. Protocol-level Metrics
# ===========================================================================

class TestProtocolMetrics(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolCdpStabilityFeeAnalyzer()

    def test_surplus_buffer_zero_no_bonus(self):
        r = self.a.analyze(_base_data(surplus_buffer_usd=0.0, total_debt_ceiling_usd=1_000_000))
        r2 = self.a.analyze(_base_data(surplus_buffer_usd=100_000.0, total_debt_ceiling_usd=1_000_000))
        self.assertGreaterEqual(r2["cdp_health_score"], r["cdp_health_score"])

    def test_large_surplus_buffer_bonus_capped(self):
        r_small = self.a.analyze(_base_data(surplus_buffer_usd=1_000.0))
        r_large = self.a.analyze(_base_data(surplus_buffer_usd=1_000_000_000.0))
        diff = r_large["cdp_health_score"] - r_small["cdp_health_score"]
        self.assertLessEqual(diff, 5.1)  # bonus capped at 5

    def test_debt_ceiling_zero_handled(self):
        r = self.a.analyze(_base_data(total_debt_ceiling_usd=0))
        self.assertIsInstance(r, dict)

    def test_real_world_makerdao_eth_vault(self):
        # Simulated MakerDAO ETH-A vault
        r = self.a.analyze({
            "protocol_name": "MakerDAO",
            "collateral_asset": "ETH",
            "collateral_value_usd": 300_000,
            "debt_usd": 100_000,
            "stability_fee_pct": 3.25,
            "liquidation_ratio_pct": 145.0,
            "current_price_usd": 3_000,
            "target_price_usd": 3_000,
            "surplus_buffer_usd": 50_000_000,
            "total_debt_ceiling_usd": 5_000_000_000,
            "debt_utilization_pct": 45.0,
        })
        self.assertIn(r["cdp_label"], {"FORTRESS_CDP", "SAFE"})

    def test_real_world_near_liq_vault(self):
        r = self.a.analyze({
            "protocol_name": "Aave",
            "collateral_asset": "stETH",
            "collateral_value_usd": 155_000,
            "debt_usd": 100_000,
            "stability_fee_pct": 8.0,
            "liquidation_ratio_pct": 150.0,
            "current_price_usd": 3_100,
            "target_price_usd": 3_100,
            "surplus_buffer_usd": 0,
            "total_debt_ceiling_usd": 500_000_000,
            "debt_utilization_pct": 88.0,
        })
        self.assertIn(r["cdp_label"], {"NEAR_LIQUIDATION", "DANGER"})

    def test_analyze_does_not_mutate_input(self):
        data = _base_data()
        original = dict(data)
        self.a.analyze(data)
        self.assertEqual(data, original)

    def test_large_surplus_relative_to_ceiling(self):
        # 10% surplus ratio → bonus near 5 pts
        r = self.a.analyze(_base_data(
            surplus_buffer_usd=100_000, total_debt_ceiling_usd=1_000_000
        ))
        self.assertGreaterEqual(r["cdp_health_score"], 0.0)

    def test_default_log_path_attribute(self):
        a = DeFiProtocolCdpStabilityFeeAnalyzer()
        self.assertEqual(a.log_path, "data/cdp_stability_fee_log.json")

    def test_custom_log_path_attribute(self):
        a = DeFiProtocolCdpStabilityFeeAnalyzer(log_path="/tmp/custom.json")
        self.assertEqual(a.log_path, "/tmp/custom.json")

    def test_max_log_entries_is_100(self):
        self.assertEqual(DeFiProtocolCdpStabilityFeeAnalyzer.MAX_LOG_ENTRIES, 100)


if __name__ == "__main__":
    unittest.main()
