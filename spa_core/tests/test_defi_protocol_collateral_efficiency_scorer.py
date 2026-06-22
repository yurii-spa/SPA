"""
Tests for MP-1120: DeFiProtocolCollateralEfficiencyScorer

Run: python3 -m unittest spa_core.tests.test_defi_protocol_collateral_efficiency_scorer

Covers:
  - compute_collateral_utilization_pct
  - compute_available_borrow_headroom_pct
  - compute_capital_efficiency_ratio
  - compute_risk_adjusted_efficiency
  - compute_efficiency_score (all segments + boundaries)
  - get_efficiency_label (all 5 labels)
  - DeFiProtocolCollateralEfficiencyScorer.score() (comprehensive scenarios)
  - save_result() (atomic write, ring-buffer, corruption recovery)
  - Import hygiene (no external deps)
  - Edge cases and boundary conditions

Python 3.9 compatible. unittest only (NOT pytest). No network. All I/O in tempdir.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from spa_core.analytics.defi_protocol_collateral_efficiency_scorer import (
    DeFiProtocolCollateralEfficiencyScorer,
    RING_BUFFER_CAP,
    LABEL_HIGHLY_EFFICIENT,
    LABEL_EFFICIENT,
    LABEL_MODERATE,
    LABEL_UNDERUTILIZED,
    LABEL_IDLE_COLLATERAL,
    THRESHOLD_HIGHLY_EFFICIENT,
    THRESHOLD_EFFICIENT,
    THRESHOLD_MODERATE,
    THRESHOLD_UNDERUTILIZED,
    compute_collateral_utilization_pct,
    compute_available_borrow_headroom_pct,
    compute_capital_efficiency_ratio,
    compute_risk_adjusted_efficiency,
    compute_efficiency_score,
    get_efficiency_label,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = (
    _REPO_ROOT / "spa_core" / "analytics"
    / "defi_protocol_collateral_efficiency_scorer.py"
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_scorer(tmp_dir: str) -> DeFiProtocolCollateralEfficiencyScorer:
    log_file = os.path.join(tmp_dir, "collateral_efficiency_log.json")
    return DeFiProtocolCollateralEfficiencyScorer(data_file=log_file)


def _basic_score(scorer: DeFiProtocolCollateralEfficiencyScorer, **overrides) -> dict:
    """Return a score result with sensible defaults, allowing key overrides."""
    defaults = dict(
        collateral_value_usd=100_000.0,
        debt_value_usd=50_000.0,
        annual_yield_earned_usd=8_000.0,
        liquidation_threshold_pct=80.0,
        current_ltv_pct=50.0,
        collateral_volatility_30d_pct=10.0,
        protocol_name="TestProtocol",
    )
    defaults.update(overrides)
    return scorer.score(**defaults)


# ===========================================================================
# 1. compute_collateral_utilization_pct
# ===========================================================================

class TestComputeCollateralUtilizationPct(unittest.TestCase):

    def test_zero_collateral_returns_zero(self):
        self.assertEqual(compute_collateral_utilization_pct(50_000, 0), 0.0)

    def test_negative_collateral_returns_zero(self):
        self.assertEqual(compute_collateral_utilization_pct(50_000, -1), 0.0)

    def test_zero_debt_nonzero_collateral(self):
        self.assertEqual(compute_collateral_utilization_pct(0, 100_000), 0.0)

    def test_fifty_percent(self):
        result = compute_collateral_utilization_pct(50_000, 100_000)
        self.assertAlmostEqual(result, 50.0, places=6)

    def test_one_hundred_percent(self):
        result = compute_collateral_utilization_pct(100_000, 100_000)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_over_one_hundred_percent(self):
        result = compute_collateral_utilization_pct(150_000, 100_000)
        self.assertAlmostEqual(result, 150.0, places=6)

    def test_small_values(self):
        result = compute_collateral_utilization_pct(1.0, 1000.0)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_large_values(self):
        result = compute_collateral_utilization_pct(1e9, 1e10)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_debt_equals_collateral(self):
        self.assertAlmostEqual(
            compute_collateral_utilization_pct(77_777, 77_777), 100.0, places=4
        )

    def test_fractional_result(self):
        result = compute_collateral_utilization_pct(1, 3)
        self.assertAlmostEqual(result, 100.0 / 3.0, places=6)


# ===========================================================================
# 2. compute_available_borrow_headroom_pct
# ===========================================================================

class TestComputeAvailableBorrowHeadroomPct(unittest.TestCase):

    def test_basic_positive_headroom(self):
        result = compute_available_borrow_headroom_pct(80.0, 50.0)
        self.assertAlmostEqual(result, 30.0, places=6)

    def test_zero_headroom(self):
        result = compute_available_borrow_headroom_pct(80.0, 80.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_negative_headroom_over_leveraged(self):
        result = compute_available_borrow_headroom_pct(80.0, 90.0)
        self.assertAlmostEqual(result, -10.0, places=6)

    def test_full_headroom_no_debt(self):
        result = compute_available_borrow_headroom_pct(80.0, 0.0)
        self.assertAlmostEqual(result, 80.0, places=6)

    def test_small_values(self):
        result = compute_available_borrow_headroom_pct(1.5, 1.0)
        self.assertAlmostEqual(result, 0.5, places=6)

    def test_large_values(self):
        result = compute_available_borrow_headroom_pct(95.0, 30.0)
        self.assertAlmostEqual(result, 65.0, places=6)

    def test_fractional(self):
        result = compute_available_borrow_headroom_pct(82.5, 67.3)
        self.assertAlmostEqual(result, 15.2, places=5)

    def test_both_zero(self):
        result = compute_available_borrow_headroom_pct(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=6)


# ===========================================================================
# 3. compute_capital_efficiency_ratio
# ===========================================================================

class TestComputeCapitalEfficiencyRatio(unittest.TestCase):

    def test_zero_collateral_returns_zero(self):
        self.assertEqual(compute_capital_efficiency_ratio(1000, 0), 0.0)

    def test_negative_collateral_returns_zero(self):
        self.assertEqual(compute_capital_efficiency_ratio(1000, -500), 0.0)

    def test_zero_yield(self):
        self.assertEqual(compute_capital_efficiency_ratio(0, 100_000), 0.0)

    def test_five_percent(self):
        result = compute_capital_efficiency_ratio(5_000, 100_000)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_ten_percent(self):
        result = compute_capital_efficiency_ratio(10_000, 100_000)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_fifteen_percent(self):
        result = compute_capital_efficiency_ratio(15_000, 100_000)
        self.assertAlmostEqual(result, 15.0, places=6)

    def test_twenty_percent(self):
        result = compute_capital_efficiency_ratio(20_000, 100_000)
        self.assertAlmostEqual(result, 20.0, places=6)

    def test_yield_equals_collateral(self):
        result = compute_capital_efficiency_ratio(50_000, 50_000)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_negative_yield(self):
        result = compute_capital_efficiency_ratio(-3_000, 100_000)
        self.assertAlmostEqual(result, -3.0, places=6)

    def test_large_values(self):
        result = compute_capital_efficiency_ratio(1e9, 1e10)
        self.assertAlmostEqual(result, 10.0, places=6)


# ===========================================================================
# 4. compute_risk_adjusted_efficiency
# ===========================================================================

class TestComputeRiskAdjustedEfficiency(unittest.TestCase):

    def test_zero_volatility_unchanged(self):
        cer = 12.0
        result = compute_risk_adjusted_efficiency(cer, 0.0)
        self.assertAlmostEqual(result, 12.0, places=6)

    def test_100_volatility_halved(self):
        cer = 20.0
        result = compute_risk_adjusted_efficiency(cer, 100.0)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_200_volatility_one_third(self):
        cer = 30.0
        result = compute_risk_adjusted_efficiency(cer, 200.0)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_basic_ten_percent_vol(self):
        cer = 11.0
        result = compute_risk_adjusted_efficiency(cer, 10.0)
        expected = 11.0 / 1.1
        self.assertAlmostEqual(result, expected, places=6)

    def test_high_efficiency_high_vol(self):
        cer = 30.0
        result = compute_risk_adjusted_efficiency(cer, 50.0)
        expected = 30.0 / 1.5
        self.assertAlmostEqual(result, expected, places=6)

    def test_low_efficiency_low_vol(self):
        cer = 2.0
        result = compute_risk_adjusted_efficiency(cer, 5.0)
        expected = 2.0 / 1.05
        self.assertAlmostEqual(result, expected, places=6)

    def test_negative_volatility_treated_as_zero(self):
        cer = 8.0
        result = compute_risk_adjusted_efficiency(cer, -10.0)
        self.assertAlmostEqual(result, 8.0, places=6)

    def test_high_vol_reduces_efficiency(self):
        cer = 15.0
        low_vol = compute_risk_adjusted_efficiency(cer, 10.0)
        high_vol = compute_risk_adjusted_efficiency(cer, 100.0)
        self.assertGreater(low_vol, high_vol)

    def test_vol_at_50_pct(self):
        cer = 9.0
        result = compute_risk_adjusted_efficiency(cer, 50.0)
        expected = 9.0 / 1.5
        self.assertAlmostEqual(result, expected, places=6)

    def test_zero_efficiency_stays_zero(self):
        result = compute_risk_adjusted_efficiency(0.0, 100.0)
        self.assertAlmostEqual(result, 0.0, places=6)


# ===========================================================================
# 5. compute_efficiency_score
# ===========================================================================

class TestComputeEfficiencyScore(unittest.TestCase):

    def test_zero_rae_score_zero(self):
        self.assertEqual(compute_efficiency_score(0.0), 0)

    def test_negative_rae_score_zero(self):
        self.assertEqual(compute_efficiency_score(-5.0), 0)

    def test_rae_at_anchor_1_score_20(self):
        self.assertEqual(compute_efficiency_score(1.0), 20)

    def test_rae_at_anchor_5_score_40(self):
        self.assertEqual(compute_efficiency_score(5.0), 40)

    def test_rae_at_anchor_10_score_60(self):
        self.assertEqual(compute_efficiency_score(10.0), 60)

    def test_rae_at_anchor_15_score_80(self):
        self.assertEqual(compute_efficiency_score(15.0), 80)

    def test_rae_at_20_score_100(self):
        self.assertEqual(compute_efficiency_score(20.0), 100)

    def test_rae_above_20_score_100(self):
        self.assertEqual(compute_efficiency_score(50.0), 100)

    def test_rae_between_0_and_1_below_20(self):
        score = compute_efficiency_score(0.5)
        self.assertGreater(score, 0)
        self.assertLess(score, 20)

    def test_rae_between_1_and_5_range(self):
        score = compute_efficiency_score(3.0)
        self.assertGreaterEqual(score, 20)
        self.assertLess(score, 40)

    def test_rae_between_5_and_10_range(self):
        score = compute_efficiency_score(7.5)
        self.assertGreaterEqual(score, 40)
        self.assertLess(score, 60)

    def test_rae_between_10_and_15_range(self):
        score = compute_efficiency_score(12.5)
        self.assertGreaterEqual(score, 60)
        self.assertLess(score, 80)

    def test_rae_between_15_and_20_range(self):
        score = compute_efficiency_score(17.5)
        self.assertGreaterEqual(score, 80)
        self.assertLess(score, 100)

    def test_always_returns_int(self):
        for rae in [-1, 0, 0.5, 1, 3, 5, 8, 10, 12, 15, 18, 20, 25]:
            self.assertIsInstance(compute_efficiency_score(rae), int)

    def test_score_monotone_increases(self):
        values = [0, 0.5, 1, 2, 3, 5, 7, 10, 12, 15, 17, 20]
        scores = [compute_efficiency_score(v) for v in values]
        for i in range(len(scores) - 1):
            self.assertLessEqual(
                scores[i], scores[i + 1],
                f"score not monotone at index {i}: {values[i]} → {scores[i]}, "
                f"{values[i+1]} → {scores[i+1]}"
            )

    def test_score_clamped_0_100(self):
        for rae in [-100, 0, 10, 20, 100, 1000]:
            s = compute_efficiency_score(rae)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)


# ===========================================================================
# 6. get_efficiency_label
# ===========================================================================

class TestGetEfficiencyLabel(unittest.TestCase):

    def test_idle_at_zero(self):
        self.assertEqual(get_efficiency_label(0.0), LABEL_IDLE_COLLATERAL)

    def test_idle_negative(self):
        self.assertEqual(get_efficiency_label(-5.0), LABEL_IDLE_COLLATERAL)

    def test_idle_just_below_threshold(self):
        self.assertEqual(get_efficiency_label(0.999), LABEL_IDLE_COLLATERAL)

    def test_underutilized_at_threshold(self):
        self.assertEqual(get_efficiency_label(1.0), LABEL_UNDERUTILIZED)

    def test_underutilized_mid(self):
        self.assertEqual(get_efficiency_label(3.0), LABEL_UNDERUTILIZED)

    def test_underutilized_near_top(self):
        self.assertEqual(get_efficiency_label(4.999), LABEL_UNDERUTILIZED)

    def test_moderate_at_threshold(self):
        self.assertEqual(get_efficiency_label(5.0), LABEL_MODERATE)

    def test_moderate_mid(self):
        self.assertEqual(get_efficiency_label(7.5), LABEL_MODERATE)

    def test_moderate_near_top(self):
        self.assertEqual(get_efficiency_label(9.999), LABEL_MODERATE)

    def test_efficient_at_threshold(self):
        self.assertEqual(get_efficiency_label(10.0), LABEL_EFFICIENT)

    def test_efficient_mid(self):
        self.assertEqual(get_efficiency_label(12.5), LABEL_EFFICIENT)

    def test_efficient_near_top(self):
        self.assertEqual(get_efficiency_label(14.999), LABEL_EFFICIENT)

    def test_highly_efficient_at_threshold(self):
        self.assertEqual(get_efficiency_label(15.0), LABEL_HIGHLY_EFFICIENT)

    def test_highly_efficient_well_above(self):
        self.assertEqual(get_efficiency_label(30.0), LABEL_HIGHLY_EFFICIENT)

    def test_all_five_labels_returned(self):
        labels = {
            get_efficiency_label(0.0),
            get_efficiency_label(1.0),
            get_efficiency_label(5.0),
            get_efficiency_label(10.0),
            get_efficiency_label(15.0),
        }
        self.assertEqual(
            labels,
            {
                LABEL_IDLE_COLLATERAL,
                LABEL_UNDERUTILIZED,
                LABEL_MODERATE,
                LABEL_EFFICIENT,
                LABEL_HIGHLY_EFFICIENT,
            },
        )


# ===========================================================================
# 7. DeFiProtocolCollateralEfficiencyScorer.score()
# ===========================================================================

class TestDeFiProtocolCollateralEfficiencyScorerScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    # --- Return type and keys ---

    def test_returns_dict(self):
        result = _basic_score(self.scorer)
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        result = _basic_score(self.scorer)
        expected_keys = {
            "protocol_name",
            "collateral_value_usd",
            "debt_value_usd",
            "annual_yield_earned_usd",
            "liquidation_threshold_pct",
            "current_ltv_pct",
            "collateral_volatility_30d_pct",
            "collateral_utilization_pct",
            "available_borrow_headroom_pct",
            "capital_efficiency_ratio",
            "risk_adjusted_efficiency",
            "efficiency_score",
            "efficiency_label",
            "run_ts",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_protocol_name_stored(self):
        result = self.scorer.score(
            100_000, 50_000, 8_000, 80.0, 50.0, 10.0, "AaveEMode"
        )
        self.assertEqual(result["protocol_name"], "AaveEMode")

    def test_efficiency_score_is_int(self):
        result = _basic_score(self.scorer)
        self.assertIsInstance(result["efficiency_score"], int)

    def test_efficiency_label_is_str(self):
        result = _basic_score(self.scorer)
        self.assertIsInstance(result["efficiency_label"], str)

    def test_run_ts_is_float(self):
        t_before = time.time()
        result = _basic_score(self.scorer)
        t_after = time.time()
        self.assertGreaterEqual(result["run_ts"], t_before)
        self.assertLessEqual(result["run_ts"], t_after)

    # --- Numeric output correctness ---

    def test_collateral_utilization_correct(self):
        result = self.scorer.score(
            100_000, 60_000, 8_000, 80.0, 60.0, 10.0
        )
        self.assertAlmostEqual(result["collateral_utilization_pct"], 60.0, places=4)

    def test_capital_efficiency_ratio_correct(self):
        result = self.scorer.score(
            100_000, 50_000, 10_000, 80.0, 50.0, 0.0
        )
        self.assertAlmostEqual(result["capital_efficiency_ratio"], 10.0, places=4)

    def test_risk_adjusted_efficiency_correct(self):
        # cer = 10%, vol = 100% → rae = 10 / 2 = 5%
        result = self.scorer.score(
            100_000, 50_000, 10_000, 80.0, 50.0, 100.0
        )
        self.assertAlmostEqual(result["risk_adjusted_efficiency"], 5.0, places=4)

    def test_headroom_correct(self):
        result = self.scorer.score(
            100_000, 50_000, 8_000, 80.0, 30.0, 10.0
        )
        self.assertAlmostEqual(
            result["available_borrow_headroom_pct"], 50.0, places=4
        )

    def test_negative_headroom_stored(self):
        result = self.scorer.score(
            100_000, 90_000, 8_000, 80.0, 92.0, 10.0
        )
        self.assertLess(result["available_borrow_headroom_pct"], 0.0)

    # --- Efficiency score range ---

    def test_efficiency_score_in_range_0_100(self):
        for cer_pct in [0, 1, 5, 10, 15, 20, 50]:
            yield_usd = 100_000 * cer_pct / 100
            result = self.scorer.score(
                100_000, 50_000, yield_usd, 80.0, 50.0, 0.0
            )
            s = result["efficiency_score"]
            self.assertGreaterEqual(s, 0, f"cer={cer_pct}%")
            self.assertLessEqual(s, 100, f"cer={cer_pct}%")

    # --- Label correctness ---

    def test_label_idle_when_zero_yield(self):
        result = self.scorer.score(100_000, 50_000, 0, 80.0, 50.0, 0.0)
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)

    def test_label_underutilized_around_2pct(self):
        result = self.scorer.score(
            100_000, 50_000, 2_000, 80.0, 50.0, 0.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_UNDERUTILIZED)

    def test_label_moderate_around_7pct(self):
        result = self.scorer.score(
            100_000, 50_000, 7_000, 80.0, 50.0, 0.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_MODERATE)

    def test_label_efficient_around_12pct(self):
        result = self.scorer.score(
            100_000, 50_000, 12_000, 80.0, 50.0, 0.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_EFFICIENT)

    def test_label_highly_efficient_around_20pct(self):
        result = self.scorer.score(
            100_000, 50_000, 20_000, 80.0, 50.0, 0.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_HIGHLY_EFFICIENT)

    # --- Protocol scenarios ---

    def test_aave_e_mode_scenario(self):
        # Aave E-Mode: high LTV, efficient capital deployment
        result = self.scorer.score(
            collateral_value_usd=500_000,
            debt_value_usd=450_000,
            annual_yield_earned_usd=30_000,
            liquidation_threshold_pct=95.0,
            current_ltv_pct=90.0,
            collateral_volatility_30d_pct=2.0,
            protocol_name="AaveV3EMode",
        )
        self.assertGreater(result["efficiency_score"], 0)
        self.assertIn(result["efficiency_label"], [
            LABEL_EFFICIENT, LABEL_HIGHLY_EFFICIENT, LABEL_MODERATE
        ])

    def test_maker_dao_scenario(self):
        # MakerDAO: typical 150% collateral ratio
        result = self.scorer.score(
            collateral_value_usd=150_000,
            debt_value_usd=100_000,
            annual_yield_earned_usd=5_000,
            liquidation_threshold_pct=75.0,
            current_ltv_pct=66.7,
            collateral_volatility_30d_pct=40.0,
            protocol_name="MakerDAO",
        )
        self.assertIsNotNone(result["efficiency_label"])

    def test_liquity_scenario(self):
        result = self.scorer.score(
            collateral_value_usd=200_000,
            debt_value_usd=100_000,
            annual_yield_earned_usd=1_000,
            liquidation_threshold_pct=110.0,
            current_ltv_pct=50.0,
            collateral_volatility_30d_pct=35.0,
            protocol_name="Liquity",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("efficiency_label", result)

    def test_zero_debt_scenario(self):
        result = self.scorer.score(
            100_000, 0, 5_000, 80.0, 0.0, 10.0
        )
        self.assertAlmostEqual(result["collateral_utilization_pct"], 0.0, places=6)
        self.assertAlmostEqual(result["available_borrow_headroom_pct"], 80.0, places=6)

    def test_zero_yield_scenario(self):
        result = self.scorer.score(
            100_000, 50_000, 0, 80.0, 50.0, 10.0
        )
        self.assertEqual(result["efficiency_score"], 0)
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)

    def test_near_liquidation_scenario(self):
        result = self.scorer.score(
            100_000, 79_000, 3_000, 80.0, 79.0, 30.0
        )
        self.assertLess(result["available_borrow_headroom_pct"], 2.0)

    def test_float_coercion_from_int_inputs(self):
        result = self.scorer.score(100_000, 50_000, 8_000, 80, 50, 10)
        self.assertIsInstance(result["collateral_value_usd"], float)
        self.assertIsInstance(result["collateral_utilization_pct"], float)

    def test_default_protocol_name(self):
        result = self.scorer.score(100_000, 50_000, 8_000, 80.0, 50.0, 10.0)
        self.assertEqual(result["protocol_name"], "unknown")

    def test_rae_boundary_at_1pct(self):
        # cer = 1%, vol = 0% → rae = 1% → UNDERUTILIZED, score = 20
        result = self.scorer.score(100_000, 50_000, 1_000, 80.0, 50.0, 0.0)
        self.assertAlmostEqual(result["risk_adjusted_efficiency"], 1.0, places=4)
        self.assertEqual(result["efficiency_label"], LABEL_UNDERUTILIZED)
        self.assertEqual(result["efficiency_score"], 20)

    def test_rae_boundary_at_5pct(self):
        result = self.scorer.score(100_000, 50_000, 5_000, 80.0, 50.0, 0.0)
        self.assertAlmostEqual(result["risk_adjusted_efficiency"], 5.0, places=4)
        self.assertEqual(result["efficiency_label"], LABEL_MODERATE)
        self.assertEqual(result["efficiency_score"], 40)

    def test_rae_boundary_at_10pct(self):
        result = self.scorer.score(100_000, 50_000, 10_000, 80.0, 50.0, 0.0)
        self.assertAlmostEqual(result["risk_adjusted_efficiency"], 10.0, places=4)
        self.assertEqual(result["efficiency_label"], LABEL_EFFICIENT)
        self.assertEqual(result["efficiency_score"], 60)

    def test_rae_boundary_at_15pct(self):
        result = self.scorer.score(100_000, 50_000, 15_000, 80.0, 50.0, 0.0)
        self.assertAlmostEqual(result["risk_adjusted_efficiency"], 15.0, places=4)
        self.assertEqual(result["efficiency_label"], LABEL_HIGHLY_EFFICIENT)
        self.assertEqual(result["efficiency_score"], 80)

    def test_high_volatility_demotes_label(self):
        # cer = 15% (would be HIGHLY_EFFICIENT) but vol = 200% → rae = 5%
        result = self.scorer.score(100_000, 50_000, 15_000, 80.0, 50.0, 200.0)
        self.assertEqual(result["efficiency_label"], LABEL_MODERATE)

    def test_rounded_outputs_to_6_places(self):
        result = _basic_score(self.scorer)
        for key in [
            "collateral_utilization_pct",
            "available_borrow_headroom_pct",
            "capital_efficiency_ratio",
            "risk_adjusted_efficiency",
        ]:
            val = result[key]
            self.assertAlmostEqual(val, round(val, 6), places=9)

    def test_score_increases_with_yield(self):
        scores = []
        for yield_usd in [0, 1_000, 5_000, 10_000, 15_000, 20_000]:
            r = self.scorer.score(100_000, 50_000, yield_usd, 80.0, 50.0, 0.0)
            scores.append(r["efficiency_score"])
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_score_decreases_with_volatility(self):
        s_low = self.scorer.score(100_000, 50_000, 12_000, 80.0, 50.0, 0.0)
        s_high = self.scorer.score(100_000, 50_000, 12_000, 80.0, 50.0, 200.0)
        self.assertGreaterEqual(
            s_low["efficiency_score"], s_high["efficiency_score"]
        )


# ===========================================================================
# 8. save_result()
# ===========================================================================

class TestSaveResult(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp, "col_eff.json")
        self.scorer = DeFiProtocolCollateralEfficiencyScorer(data_file=self.log_file)

    def _result(self, tag: str = "x") -> dict:
        r = _basic_score(self.scorer, protocol_name=tag)
        return r

    def test_creates_file_if_not_exist(self):
        self.assertFalse(os.path.exists(self.log_file))
        self.scorer.save_result(self._result("a"))
        self.assertTrue(os.path.exists(self.log_file))

    def test_saved_data_is_list(self):
        self.scorer.save_result(self._result("b"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_to_existing(self):
        self.scorer.save_result(self._result("c1"))
        self.scorer.save_result(self._result("c2"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_enforced(self):
        for i in range(RING_BUFFER_CAP + 10):
            self.scorer.save_result(self._result(f"r{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(RING_BUFFER_CAP + 5):
            self.scorer.save_result(self._result(f"p{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        last_name = data[-1]["protocol_name"]
        self.assertEqual(last_name, f"p{RING_BUFFER_CAP + 4}")

    def test_atomic_write_no_partial_file(self):
        self.scorer.save_result(self._result("atomic"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_corrupted_file_recovered(self):
        with open(self.log_file, "w") as f:
            f.write("not valid json {{{")
        self.scorer.save_result(self._result("recovery"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_json_recovered(self):
        with open(self.log_file, "w") as f:
            json.dump({"key": "value"}, f)
        self.scorer.save_result(self._result("nonlist"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_empty_list_file_appended(self):
        with open(self.log_file, "w") as f:
            json.dump([], f)
        self.scorer.save_result(self._result("append_empty"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_data_dir_created_if_missing(self):
        deep_dir = os.path.join(self.tmp, "deep", "nested")
        log_file = os.path.join(deep_dir, "test.json")
        scorer = DeFiProtocolCollateralEfficiencyScorer(data_file=log_file)
        scorer.save_result(self._result("deep"))
        self.assertTrue(os.path.exists(log_file))

    def test_multiple_sequential_saves_correct_count(self):
        for i in range(5):
            self.scorer.save_result(self._result(f"seq{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_saved_result_preserves_protocol_name(self):
        r = _basic_score(self.scorer, protocol_name="Compound")
        self.scorer.save_result(r)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "Compound")


# ===========================================================================
# 9. Import hygiene — no external dependencies
# ===========================================================================

class TestImportHygiene(unittest.TestCase):

    def test_module_file_exists(self):
        self.assertTrue(_MODULE_PATH.exists(), f"Module not found: {_MODULE_PATH}")

    def test_no_external_imports(self):
        """Only stdlib modules may be imported."""
        stdlib_modules = {
            "json", "math", "os", "tempfile", "time",
            "typing", "__future__", "abc", "collections",
            "functools", "itertools", "re", "sys",
            "spa_core",  # centralized stdlib-only atomic IO helper (MP-1453)
        }
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    names = [node.module.split(".")[0]] if node.module else []
                for name in names:
                    self.assertIn(
                        name, stdlib_modules,
                        f"External import detected: {name}"
                    )

    def test_class_instantiable_no_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            scorer = DeFiProtocolCollateralEfficiencyScorer(
                data_file=os.path.join(tmp, "tmp.json")
            )
            self.assertIsInstance(scorer, DeFiProtocolCollateralEfficiencyScorer)

    def test_constants_exported(self):
        from spa_core.analytics import defi_protocol_collateral_efficiency_scorer as m
        self.assertEqual(m.RING_BUFFER_CAP, 100)
        self.assertTrue(hasattr(m, "LABEL_HIGHLY_EFFICIENT"))
        self.assertTrue(hasattr(m, "LABEL_IDLE_COLLATERAL"))


# ===========================================================================
# 10. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def test_very_large_collateral(self):
        result = self.scorer.score(
            1e12, 5e11, 1e11, 80.0, 50.0, 5.0
        )
        self.assertAlmostEqual(result["capital_efficiency_ratio"], 10.0, places=4)

    def test_very_small_yield(self):
        result = self.scorer.score(
            1_000_000, 0, 0.01, 80.0, 0.0, 0.0
        )
        self.assertLess(result["risk_adjusted_efficiency"], 0.01)
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)

    def test_extreme_volatility_reduces_score_to_min(self):
        # yield = 10%, vol = 10000% → rae ≈ 0.1% → IDLE
        result = self.scorer.score(
            100_000, 0, 10_000, 80.0, 0.0, 10_000.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)

    def test_zero_everything(self):
        result = self.scorer.score(0, 0, 0, 0.0, 0.0, 0.0)
        self.assertEqual(result["efficiency_score"], 0)
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)

    def test_rae_precision_near_boundary(self):
        # Ensure the boundary 10% → EFFICIENT not MODERATE
        # cer = 10%, vol = 0% → rae = exactly 10%
        result = self.scorer.score(100_000, 0, 10_000, 80.0, 0.0, 0.0)
        self.assertEqual(result["efficiency_label"], LABEL_EFFICIENT)

    def test_score_method_is_pure_function(self):
        r1 = _basic_score(self.scorer)
        r2 = _basic_score(self.scorer)
        self.assertEqual(r1["efficiency_score"], r2["efficiency_score"])
        self.assertEqual(r1["efficiency_label"], r2["efficiency_label"])
        self.assertEqual(r1["collateral_utilization_pct"], r2["collateral_utilization_pct"])

    def test_negative_rae_label_is_idle(self):
        # negative yield → negative cer → negative rae → IDLE
        result = self.scorer.score(
            100_000, 50_000, -5_000, 80.0, 50.0, 0.0
        )
        self.assertEqual(result["efficiency_label"], LABEL_IDLE_COLLATERAL)
        self.assertEqual(result["efficiency_score"], 0)

    def test_all_five_labels_reachable_via_score(self):
        yields = [0, 1_000, 5_000, 10_000, 15_000]
        labels = set()
        for y in yields:
            r = self.scorer.score(100_000, 50_000, y, 80.0, 50.0, 0.0)
            labels.add(r["efficiency_label"])
        self.assertEqual(len(labels), 5)


if __name__ == "__main__":
    unittest.main()
