"""
Tests for MP-1087: ProtocolDeFiLiquidationCascadeRiskAnalyzer
Target: >=110 tests, all pass with `python3 -m unittest`
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_defi_liquidation_cascade_risk_analyzer import (
    ProtocolDeFiLiquidationCascadeRiskAnalyzer,
)


def _make(
    total_collateral_usd=1_000_000.0,
    total_debt_usd=600_000.0,
    liquidation_threshold_pct=80.0,
    current_ltv_pct=60.0,
    price_drop_pct=10.0,
    liquidation_penalty_pct=5.0,
    protocol_tvl_usd=5_000_000.0,
    daily_volume_usd=500_000.0,
    protocol_name="TestProtocol",
    data_dir=None,
):
    a = ProtocolDeFiLiquidationCascadeRiskAnalyzer(data_dir=data_dir or tempfile.mkdtemp())
    return a.analyze(
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        liquidation_threshold_pct=liquidation_threshold_pct,
        current_ltv_pct=current_ltv_pct,
        price_drop_pct=price_drop_pct,
        liquidation_penalty_pct=liquidation_penalty_pct,
        protocol_tvl_usd=protocol_tvl_usd,
        daily_volume_usd=daily_volume_usd,
        protocol_name=protocol_name,
    )


class TestReturnStructure(unittest.TestCase):
    def test_returns_dict(self): self.assertIsInstance(_make(), dict)
    def test_has_buffer(self): self.assertIn("buffer_to_liquidation_pct", _make())
    def test_has_at_risk(self): self.assertIn("at_risk_collateral_usd", _make())
    def test_has_liquidations(self): self.assertIn("estimated_liquidations_usd", _make())
    def test_has_market_impact(self): self.assertIn("market_impact_pct", _make())
    def test_has_risk_score(self): self.assertIn("cascade_risk_score", _make())
    def test_has_label(self): self.assertIn("cascade_label", _make())
    def test_has_log_entry(self): self.assertIn("log_entry", _make())
    def test_seven_keys(self): self.assertEqual(len(_make()), 7)
    def test_buffer_is_float(self): self.assertIsInstance(_make()["buffer_to_liquidation_pct"], float)
    def test_at_risk_is_float(self): self.assertIsInstance(_make()["at_risk_collateral_usd"], float)
    def test_liquidations_is_float(self): self.assertIsInstance(_make()["estimated_liquidations_usd"], float)
    def test_market_impact_is_float(self): self.assertIsInstance(_make()["market_impact_pct"], float)
    def test_risk_score_is_int(self): self.assertIsInstance(_make()["cascade_risk_score"], int)
    def test_label_is_str(self): self.assertIsInstance(_make()["cascade_label"], str)
    def test_log_entry_is_dict(self): self.assertIsInstance(_make()["log_entry"], dict)


class TestBufferToLiquidation(unittest.TestCase):
    def test_formula_60_80(self):
        r = _make(current_ltv_pct=60.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 25.0, places=6)

    def test_zero_when_ltv_equals_threshold(self):
        r = _make(current_ltv_pct=80.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 0.0, places=6)

    def test_negative_when_ltv_exceeds_threshold(self):
        r = _make(current_ltv_pct=90.0, liquidation_threshold_pct=80.0)
        self.assertLess(r["buffer_to_liquidation_pct"], 0.0)

    def test_large_buffer_low_ltv(self):
        r = _make(current_ltv_pct=10.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 87.5, places=6)

    def test_formula_50_80(self):
        r = _make(current_ltv_pct=50.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 37.5, places=6)

    def test_formula_68_85(self):
        r = _make(current_ltv_pct=68.0, liquidation_threshold_pct=85.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 20.0, places=4)

    def test_zero_threshold_returns_zero(self):
        r = _make(current_ltv_pct=50.0, liquidation_threshold_pct=0.0)
        self.assertEqual(r["buffer_to_liquidation_pct"], 0.0)

    def test_negative_buffer_exact(self):
        r = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], -6.25, places=4)

    def test_formula_75_75_zero(self):
        r = _make(current_ltv_pct=75.0, liquidation_threshold_pct=75.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 0.0, places=6)

    def test_formula_64_80_twenty(self):
        r = _make(current_ltv_pct=64.0, liquidation_threshold_pct=80.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 20.0, places=4)


class TestAtRiskCollateral(unittest.TestCase):
    def test_10pct_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=10.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 900_000.0, places=2)

    def test_zero_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=0.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 1_000_000.0, places=2)

    def test_100_pct_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=100.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 0.0, places=2)

    def test_50_pct_drop(self):
        r = _make(total_collateral_usd=2_000_000.0, price_drop_pct=50.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 1_000_000.0, places=2)

    def test_20_pct_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=20.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 800_000.0, places=2)

    def test_never_negative(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=150.0)
        self.assertGreaterEqual(r["at_risk_collateral_usd"], 0.0)

    def test_1_pct_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, price_drop_pct=1.0)
        self.assertAlmostEqual(r["at_risk_collateral_usd"], 990_000.0, places=2)


class TestEstimatedLiquidations(unittest.TestCase):
    def test_zero_when_safe_after_drop(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=600_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=60.0, price_drop_pct=20.0)
        # at_risk=800K; safe_debt=0.8*800K=640K > 600K → 0
        self.assertEqual(r["estimated_liquidations_usd"], 0.0)

    def test_positive_when_cascade(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=20.0)
        self.assertAlmostEqual(r["estimated_liquidations_usd"], 60_000.0, places=2)

    def test_formula_2m_debt_1_4m_drop_30(self):
        r = _make(total_collateral_usd=2_000_000.0, total_debt_usd=1_400_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=30.0)
        self.assertAlmostEqual(r["estimated_liquidations_usd"], 280_000.0, places=2)

    def test_never_negative(self):
        r = _make(total_debt_usd=100.0, price_drop_pct=50.0)
        self.assertGreaterEqual(r["estimated_liquidations_usd"], 0.0)

    def test_zero_debt(self):
        r = _make(total_debt_usd=0.0, price_drop_pct=50.0)
        self.assertEqual(r["estimated_liquidations_usd"], 0.0)

    def test_zero_threshold(self):
        r = _make(liquidation_threshold_pct=0.0)
        self.assertEqual(r["estimated_liquidations_usd"], 0.0)

    def test_large_drop_large_liq(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=950_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=95.0, price_drop_pct=80.0)
        self.assertAlmostEqual(r["estimated_liquidations_usd"], 790_000.0, places=2)

    def test_no_drop_no_liquidation(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=600_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=60.0, price_drop_pct=0.0)
        self.assertEqual(r["estimated_liquidations_usd"], 0.0)


class TestMarketImpact(unittest.TestCase):
    def test_zero_when_no_liquidations(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=400_000.0,
                  current_ltv_pct=40.0, price_drop_pct=5.0)
        self.assertEqual(r["market_impact_pct"], 0.0)

    def test_formula_60k_500k(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=20.0,
                  daily_volume_usd=500_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 12.0, places=4)

    def test_100_when_zero_volume_with_liq(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=20.0,
                  daily_volume_usd=0.0)
        self.assertEqual(r["market_impact_pct"], 100.0)

    def test_zero_when_zero_volume_no_liq(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=400_000.0,
                  current_ltv_pct=40.0, price_drop_pct=5.0, daily_volume_usd=0.0)
        self.assertEqual(r["market_impact_pct"], 0.0)

    def test_above_100_when_large_liq(self):
        r = _make(total_collateral_usd=10_000_000.0, total_debt_usd=9_000_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=90.0, price_drop_pct=50.0,
                  daily_volume_usd=100_000.0)
        self.assertGreater(r["market_impact_pct"], 100.0)

    def test_small_impact(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=20.0,
                  daily_volume_usd=10_000_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 0.6, places=4)

    def test_impact_60pct(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0, price_drop_pct=20.0,
                  daily_volume_usd=100_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 60.0, places=4)


class TestCascadeLabel(unittest.TestCase):
    def test_safe_margins(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=400_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=40.0,
                  price_drop_pct=1.0, daily_volume_usd=10_000_000.0)
        self.assertEqual(r["cascade_label"], "SAFE_MARGINS")

    def test_safe_margins_high_buffer_zero_impact(self):
        r = _make(current_ltv_pct=40.0, price_drop_pct=0.0,
                  daily_volume_usd=100_000_000.0)
        self.assertEqual(r["cascade_label"], "SAFE_MARGINS")

    def test_watchlist_buffer_15(self):
        r = _make(current_ltv_pct=68.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=10_000_000.0)
        self.assertEqual(r["cascade_label"], "WATCHLIST")

    def test_watchlist_buffer_exactly_20(self):
        r = _make(current_ltv_pct=64.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        self.assertEqual(r["cascade_label"], "WATCHLIST")

    def test_watchlist_impact_8pct(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0,
                  price_drop_pct=20.0, daily_volume_usd=750_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 8.0, places=4)
        self.assertEqual(r["cascade_label"], "WATCHLIST")

    def test_cascade_risk_buffer_7(self):
        r = _make(current_ltv_pct=74.4, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        self.assertEqual(r["cascade_label"], "CASCADE_RISK")

    def test_cascade_risk_impact_20pct(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0,
                  price_drop_pct=20.0, daily_volume_usd=300_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 20.0, places=4)
        self.assertEqual(r["cascade_label"], "CASCADE_RISK")

    def test_high_cascade_buffer_2_5(self):
        r = _make(current_ltv_pct=78.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        self.assertEqual(r["cascade_label"], "HIGH_CASCADE")

    def test_high_cascade_impact_60pct(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0,
                  price_drop_pct=20.0, daily_volume_usd=100_000.0)
        self.assertAlmostEqual(r["market_impact_pct"], 60.0, places=4)
        self.assertEqual(r["cascade_label"], "HIGH_CASCADE")

    def test_systemic_cascade_impact_61(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=70.0,
                  price_drop_pct=20.0, daily_volume_usd=90_000.0)
        self.assertGreater(r["market_impact_pct"], 60.0)
        self.assertEqual(r["cascade_label"], "SYSTEMIC_CASCADE")

    def test_systemic_cascade_ltv_exceeds_threshold(self):
        r = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=10_000_000.0)
        self.assertEqual(r["cascade_label"], "SYSTEMIC_CASCADE")

    def test_not_systemic_ltv_equals_threshold(self):
        r = _make(current_ltv_pct=80.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        # buffer=0 < 5 → HIGH_CASCADE
        self.assertEqual(r["cascade_label"], "HIGH_CASCADE")

    def test_systemic_priority_over_others(self):
        # LTV > threshold triggers systemic even with low impact
        r = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=100_000_000.0)
        self.assertEqual(r["cascade_label"], "SYSTEMIC_CASCADE")

    def test_cascade_boundary_buffer_exactly_5(self):
        r = _make(current_ltv_pct=76.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        # buffer=5 → not < 5 → cascade_risk (buffer < 10)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 5.0, places=4)
        self.assertEqual(r["cascade_label"], "CASCADE_RISK")

    def test_watchlist_boundary_buffer_10(self):
        # ltv=71, threshold=80 → buffer=11.25% which is clearly in (10,20] → WATCHLIST
        r = _make(current_ltv_pct=71.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=50_000_000.0)
        self.assertAlmostEqual(r["buffer_to_liquidation_pct"], 11.25, places=4)
        self.assertEqual(r["cascade_label"], "WATCHLIST")

    def test_safe_requires_both_conditions(self):
        # buffer=25>20 but impact=6%>=5 → WATCHLIST
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=700_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=60.0,
                  price_drop_pct=20.0, daily_volume_usd=1_000_000.0)
        self.assertEqual(r["cascade_label"], "WATCHLIST")


class TestCascadeRiskScore(unittest.TestCase):
    def test_type_is_int(self): self.assertIsInstance(_make()["cascade_risk_score"], int)
    def test_min_0(self): self.assertGreaterEqual(_make()["cascade_risk_score"], 0)
    def test_max_100(self): self.assertLessEqual(_make()["cascade_risk_score"], 100)

    def test_zero_minimum_risk(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=25, impact=0, ltv<threshold → 0
        self.assertEqual(a._compute_cascade_risk_score(25.0, 0.0, 60.0, 80.0), 0)

    def test_buffer_score_zero_at_25(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        self.assertEqual(a._compute_cascade_risk_score(25.0, 0.0, 60.0, 80.0), 0)

    def test_buffer_score_50_at_zero(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=0 → buffer_score=50; impact=0; no ltv_bonus → 50
        self.assertEqual(a._compute_cascade_risk_score(0.0, 0.0, 60.0, 80.0), 50)

    def test_buffer_score_25_at_12_5(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=12.5 → (25-12.5)/25*50=25; impact=0; no bonus → 25
        self.assertEqual(a._compute_cascade_risk_score(12.5, 0.0, 60.0, 80.0), 25)

    def test_impact_score_40_at_60pct(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=25; impact=60→40; no ltv_bonus → 40
        self.assertEqual(a._compute_cascade_risk_score(25.0, 60.0, 60.0, 80.0), 40)

    def test_impact_score_20_at_30pct(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        self.assertEqual(a._compute_cascade_risk_score(25.0, 30.0, 60.0, 80.0), 20)

    def test_ltv_bonus_when_ltv_equals_threshold(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=0→50; impact=0; ltv_bonus=10 → 60
        self.assertEqual(a._compute_cascade_risk_score(0.0, 0.0, 80.0, 80.0), 60)

    def test_ltv_bonus_when_ltv_above_threshold(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=-5→50 (capped); impact=0; ltv_bonus=10 → 60
        self.assertEqual(a._compute_cascade_risk_score(-5.0, 0.0, 85.0, 80.0), 60)

    def test_no_ltv_bonus_below_threshold(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        self.assertEqual(a._compute_cascade_risk_score(25.0, 0.0, 60.0, 80.0), 0)

    def test_max_score_100(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        # buffer=0→50; impact=60→40; ltv_bonus=10 → 100
        self.assertEqual(a._compute_cascade_risk_score(0.0, 60.0, 80.0, 80.0), 100)

    def test_score_clamped_below_100(self):
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer.__new__(
            ProtocolDeFiLiquidationCascadeRiskAnalyzer)
        score = a._compute_cascade_risk_score(-100.0, 200.0, 90.0, 80.0)
        self.assertLessEqual(score, 100)

    def test_score_low_for_safe_scenario(self):
        r = _make(total_collateral_usd=1_000_000.0, total_debt_usd=400_000.0,
                  liquidation_threshold_pct=80.0, current_ltv_pct=40.0,
                  price_drop_pct=0.0, daily_volume_usd=50_000_000.0)
        self.assertLess(r["cascade_risk_score"], 10)

    def test_score_high_for_systemic_scenario(self):
        r = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=50.0, daily_volume_usd=50_000.0)
        self.assertGreater(r["cascade_risk_score"], 60)


class TestLogEntryStructure(unittest.TestCase):
    REQUIRED = {
        "protocol_name", "total_collateral_usd", "total_debt_usd",
        "liquidation_threshold_pct", "current_ltv_pct", "price_drop_pct",
        "liquidation_penalty_pct", "protocol_tvl_usd", "daily_volume_usd",
        "buffer_to_liquidation_pct", "at_risk_collateral_usd",
        "estimated_liquidations_usd", "market_impact_pct",
        "cascade_risk_score", "cascade_label", "analyzed_at",
    }

    def _e(self): return _make()["log_entry"]

    def test_all_keys(self):
        e = self._e()
        for k in self.REQUIRED:
            self.assertIn(k, e, msg=f"Missing key: {k}")

    def test_protocol_name(self):
        r = _make(protocol_name="Morpho")
        self.assertEqual(r["log_entry"]["protocol_name"], "Morpho")

    def test_buffer_matches_result(self):
        r = _make()
        self.assertAlmostEqual(r["log_entry"]["buffer_to_liquidation_pct"], r["buffer_to_liquidation_pct"])

    def test_at_risk_matches_result(self):
        r = _make()
        self.assertAlmostEqual(r["log_entry"]["at_risk_collateral_usd"], r["at_risk_collateral_usd"])

    def test_liquidations_matches_result(self):
        r = _make()
        self.assertAlmostEqual(r["log_entry"]["estimated_liquidations_usd"], r["estimated_liquidations_usd"])

    def test_market_impact_matches_result(self):
        r = _make()
        self.assertAlmostEqual(r["log_entry"]["market_impact_pct"], r["market_impact_pct"])

    def test_score_matches_result(self):
        r = _make()
        self.assertEqual(r["log_entry"]["cascade_risk_score"], r["cascade_risk_score"])

    def test_label_matches_result(self):
        r = _make()
        self.assertEqual(r["log_entry"]["cascade_label"], r["cascade_label"])

    def test_analyzed_at_float(self):
        self.assertIsInstance(self._e()["analyzed_at"], float)

    def test_analyzed_at_positive(self):
        self.assertGreater(self._e()["analyzed_at"], 0.0)

    def test_penalty_in_entry(self):
        r = _make(liquidation_penalty_pct=7.5)
        self.assertAlmostEqual(r["log_entry"]["liquidation_penalty_pct"], 7.5)

    def test_tvl_in_entry(self):
        r = _make(protocol_tvl_usd=1e11)
        self.assertAlmostEqual(r["log_entry"]["protocol_tvl_usd"], 1e11)

    def test_daily_volume_in_entry(self):
        r = _make(daily_volume_usd=2_000_000.0)
        self.assertAlmostEqual(r["log_entry"]["daily_volume_usd"], 2_000_000.0)


class TestLogFilePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.a = ProtocolDeFiLiquidationCascadeRiskAnalyzer(data_dir=self.tmp_dir)
        self.log_path = os.path.join(self.tmp_dir, "liquidation_cascade_risk_log.json")

    def _run(self, name="P"):
        return self.a.analyze(
            total_collateral_usd=1_000_000.0, total_debt_usd=600_000.0,
            liquidation_threshold_pct=80.0, current_ltv_pct=60.0, price_drop_pct=10.0,
            liquidation_penalty_pct=5.0, protocol_tvl_usd=5_000_000.0,
            daily_volume_usd=500_000.0, protocol_name=name,
        )

    def test_analyze_alone_no_file(self):
        self._run()
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_result_creates_file(self):
        r = self._run()
        self.a.log_result(r["log_entry"])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        r = self._run()
        self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_one_entry(self):
        r = self._run()
        self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_appends(self):
        for _ in range(3):
            r = self._run()
            self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_cap_100(self):
        for i in range(105):
            r = self._run(name=f"P{i}")
            self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_cap_keeps_recent(self):
        for i in range(105):
            r = self._run(name=f"P{i}")
            self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "P5")
        self.assertEqual(data[-1]["protocol_name"], "P104")

    def test_exactly_100_no_trim(self):
        for i in range(100):
            r = self._run(name=f"P{i}")
            self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_200_entries_trimmed(self):
        for i in range(200):
            r = self._run(name=f"P{i}")
            self.a.log_result(r["log_entry"])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_no_tmp_left(self):
        r = self._run()
        self.a.log_result(r["log_entry"])
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_read_empty_no_file(self):
        self.assertEqual(self.a._read_log(), [])

    def test_read_returns_list(self):
        r = self._run()
        self.a.log_result(r["log_entry"])
        self.assertIsInstance(self.a._read_log(), list)

    def test_read_corrupted_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not json {{{")
        self.assertEqual(self.a._read_log(), [])

    def test_read_wrong_type_returns_empty(self):
        with open(self.log_path, "w") as f:
            json.dump({"k": "v"}, f)
        self.assertEqual(self.a._read_log(), [])

    def test_data_dir_created(self):
        nested = os.path.join(self.tmp_dir, "x", "y")
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer(data_dir=nested)
        r = a.analyze(
            total_collateral_usd=1_000_000.0, total_debt_usd=600_000.0,
            liquidation_threshold_pct=80.0, current_ltv_pct=60.0, price_drop_pct=10.0,
            liquidation_penalty_pct=5.0, protocol_tvl_usd=5_000_000.0,
            daily_volume_usd=500_000.0, protocol_name="P",
        )
        a.log_result(r["log_entry"])
        self.assertTrue(os.path.isdir(nested))


class TestIntegrationEdgeCases(unittest.TestCase):
    def test_multiple_independent(self):
        r1 = _make(current_ltv_pct=40.0, price_drop_pct=0.0, daily_volume_usd=1e7)
        r2 = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                   price_drop_pct=50.0, daily_volume_usd=50_000.0)
        self.assertEqual(r1["cascade_label"], "SAFE_MARGINS")
        self.assertEqual(r2["cascade_label"], "SYSTEMIC_CASCADE")

    def test_label_constants(self):
        self.assertEqual(ProtocolDeFiLiquidationCascadeRiskAnalyzer.SAFE_MARGINS, "SAFE_MARGINS")
        self.assertEqual(ProtocolDeFiLiquidationCascadeRiskAnalyzer.WATCHLIST, "WATCHLIST")
        self.assertEqual(ProtocolDeFiLiquidationCascadeRiskAnalyzer.CASCADE_RISK, "CASCADE_RISK")
        self.assertEqual(ProtocolDeFiLiquidationCascadeRiskAnalyzer.HIGH_CASCADE, "HIGH_CASCADE")
        self.assertEqual(ProtocolDeFiLiquidationCascadeRiskAnalyzer.SYSTEMIC_CASCADE, "SYSTEMIC_CASCADE")

    def test_all_labels_valid(self):
        valid = {"SAFE_MARGINS", "WATCHLIST", "CASCADE_RISK", "HIGH_CASCADE", "SYSTEMIC_CASCADE"}
        for params in [
            dict(current_ltv_pct=40.0, price_drop_pct=5.0, daily_volume_usd=10_000_000.0),
            dict(current_ltv_pct=65.0, price_drop_pct=5.0, daily_volume_usd=10_000_000.0),
            dict(current_ltv_pct=74.0, price_drop_pct=10.0, daily_volume_usd=500_000.0),
            dict(current_ltv_pct=79.0, price_drop_pct=20.0, daily_volume_usd=200_000.0),
            dict(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                 price_drop_pct=50.0, daily_volume_usd=50_000.0),
        ]:
            r = _make(**params)
            self.assertIn(r["cascade_label"], valid)

    def test_liquidations_never_negative(self):
        for drop in [0, 10, 50, 90, 100, 150]:
            r = _make(price_drop_pct=float(drop))
            self.assertGreaterEqual(r["estimated_liquidations_usd"], 0.0)

    def test_at_risk_never_negative(self):
        for drop in [0, 50, 100, 200]:
            r = _make(price_drop_pct=float(drop))
            self.assertGreaterEqual(r["at_risk_collateral_usd"], 0.0)

    def test_negative_buffer_systemic(self):
        r = _make(current_ltv_pct=85.0, liquidation_threshold_pct=80.0,
                  price_drop_pct=1.0, daily_volume_usd=100_000_000.0)
        self.assertLess(r["buffer_to_liquidation_pct"], 0.0)
        self.assertEqual(r["cascade_label"], "SYSTEMIC_CASCADE")

    def test_zero_collateral(self):
        r = _make(total_collateral_usd=0.0, total_debt_usd=0.0, price_drop_pct=50.0)
        self.assertEqual(r["at_risk_collateral_usd"], 0.0)
        self.assertEqual(r["estimated_liquidations_usd"], 0.0)

    def test_log_roundtrip(self):
        tmp = tempfile.mkdtemp()
        a = ProtocolDeFiLiquidationCascadeRiskAnalyzer(data_dir=tmp)
        for name in ["Aave", "Compound", "Morpho"]:
            r = a.analyze(
                total_collateral_usd=1_000_000.0, total_debt_usd=600_000.0,
                liquidation_threshold_pct=80.0, current_ltv_pct=60.0, price_drop_pct=10.0,
                liquidation_penalty_pct=5.0, protocol_tvl_usd=5_000_000.0,
                daily_volume_usd=500_000.0, protocol_name=name,
            )
            a.log_result(r["log_entry"])
        entries = a._read_log()
        self.assertEqual(len(entries), 3)
        self.assertEqual([e["protocol_name"] for e in entries], ["Aave", "Compound", "Morpho"])

    def test_score_increases_with_worse_params(self):
        safe = _make(current_ltv_pct=40.0, price_drop_pct=0.0, daily_volume_usd=10_000_000.0)
        risky = _make(current_ltv_pct=75.0, price_drop_pct=20.0, daily_volume_usd=500_000.0)
        self.assertGreater(risky["cascade_risk_score"], safe["cascade_risk_score"])

    def test_compound_safe_scenario(self):
        r = _make(total_collateral_usd=2_000_000_000.0, total_debt_usd=600_000_000.0,
                  liquidation_threshold_pct=83.0, current_ltv_pct=30.0,
                  price_drop_pct=5.0, protocol_name="Compound_V3",
                  daily_volume_usd=5_000_000_000.0)
        self.assertEqual(r["cascade_label"], "SAFE_MARGINS")

    def test_large_tvl_stored(self):
        r = _make(protocol_tvl_usd=5e10)
        self.assertAlmostEqual(r["log_entry"]["protocol_tvl_usd"], 5e10)

    def test_buffer_formula_multiple_ltvs(self):
        for ltv, thr, exp in [(50, 80, 37.5), (75, 80, 6.25), (60, 75, 20.0)]:
            r = _make(current_ltv_pct=float(ltv), liquidation_threshold_pct=float(thr))
            self.assertAlmostEqual(r["buffer_to_liquidation_pct"], exp, places=4,
                                   msg=f"ltv={ltv}, thr={thr}")


if __name__ == "__main__":
    unittest.main()
