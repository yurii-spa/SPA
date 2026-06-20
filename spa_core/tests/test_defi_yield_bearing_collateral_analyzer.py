#!/usr/bin/env python3
"""Tests for DeFiYieldBearingCollateralAnalyzer (MP-966).

Run with:
    python3 -m unittest spa_core.tests.test_defi_yield_bearing_collateral_analyzer -v
"""
import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spa_core.analytics.defi_yield_bearing_collateral_analyzer import (
    DeFiYieldBearingCollateralAnalyzer,
    write_log,
    LABEL_OPTIMAL,
    LABEL_POSITIVE,
    LABEL_BREAK_EVEN,
    LABEL_NEGATIVE,
    LABEL_LIQUIDATION,
    LOG_FILE,
    LOG_CAP,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _pos(
    asset="stETH",
    protocol="Aave V3",
    apy=5.0,
    cf=75.0,
    liq_threshold=80.0,
    current_ltv=60.0,
    value=100_000.0,
    borrow_rate=3.0,
    rebasing="non_rebasing",
    oracle="chainlink",
    price_dev=1.0,
):
    return {
        "asset_name": asset,
        "protocol_used_as_collateral": protocol,
        "underlying_apy_pct": apy,
        "collateral_factor_pct": cf,
        "liquidation_threshold_pct": liq_threshold,
        "current_ltv_pct": current_ltv,
        "position_value_usd": value,
        "borrow_rate_pct": borrow_rate,
        "rebasing_type": rebasing,
        "oracle_type": oracle,
        "price_deviation_risk_pct": price_dev,
    }


class TestNetCarry(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_positive_carry(self):
        r = self.a.analyze([_pos(apy=6.0, borrow_rate=3.0)], {})
        self.assertGreater(r["positions"][0]["net_carry_pct"], 0)

    def test_negative_carry(self):
        r = self.a.analyze([_pos(apy=2.0, borrow_rate=5.0)], {})
        self.assertLess(r["positions"][0]["net_carry_pct"], 0)

    def test_break_even_carry(self):
        r = self.a.analyze([_pos(apy=4.0, borrow_rate=4.0)], {})
        self.assertEqual(r["positions"][0]["net_carry_pct"], 0.0)

    def test_carry_precision(self):
        r = self.a.analyze([_pos(apy=5.123456789, borrow_rate=3.111111111)], {})
        carry = r["positions"][0]["net_carry_pct"]
        self.assertIsInstance(carry, float)

    def test_carry_value(self):
        r = self.a.analyze([_pos(apy=7.5, borrow_rate=2.5)], {})
        self.assertAlmostEqual(r["positions"][0]["net_carry_pct"], 5.0, places=4)

    def test_zero_borrow_rate(self):
        r = self.a.analyze([_pos(apy=5.0, borrow_rate=0.0)], {})
        self.assertAlmostEqual(r["positions"][0]["net_carry_pct"], 5.0, places=4)

    def test_zero_apy(self):
        r = self.a.analyze([_pos(apy=0.0, borrow_rate=3.0)], {})
        self.assertAlmostEqual(r["positions"][0]["net_carry_pct"], -3.0, places=4)


class TestSafetyMargin(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_safety_margin_computed(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=60.0)], {})
        self.assertAlmostEqual(r["positions"][0]["safety_margin_pct"], 20.0, places=4)

    def test_tight_safety_margin(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=76.0)], {})
        # 4% margin < 5% threshold → TIGHT_LIQUIDATION flag
        self.assertIn("TIGHT_LIQUIDATION", r["positions"][0]["flags"])

    def test_zero_safety_margin(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=80.0)], {})
        self.assertAlmostEqual(r["positions"][0]["safety_margin_pct"], 0.0, places=4)

    def test_negative_safety_margin(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=82.0)], {})
        self.assertLess(r["positions"][0]["safety_margin_pct"], 0)

    def test_safe_margin_no_tight_flag(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=60.0)], {})
        self.assertNotIn("TIGHT_LIQUIDATION", r["positions"][0]["flags"])


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_optimal_carry_label(self):
        r = self.a.analyze([_pos(apy=8.0, borrow_rate=3.0, liq_threshold=80.0, current_ltv=50.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_OPTIMAL)

    def test_positive_carry_label(self):
        r = self.a.analyze([_pos(apy=4.5, borrow_rate=3.5, liq_threshold=80.0, current_ltv=50.0)], {})
        # net carry = 1.0 < optimal_min=2.0 → POSITIVE_CARRY
        self.assertEqual(r["positions"][0]["label"], LABEL_POSITIVE)

    def test_break_even_label(self):
        r = self.a.analyze([_pos(apy=3.0, borrow_rate=3.0, liq_threshold=80.0, current_ltv=50.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_BREAK_EVEN)

    def test_negative_carry_label(self):
        r = self.a.analyze([_pos(apy=2.0, borrow_rate=5.0, liq_threshold=80.0, current_ltv=50.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_NEGATIVE)

    def test_liquidation_imminent_label(self):
        # safety margin = 80 - 79 = 1 ≤ 2.0 (default liq_imminent margin)
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=79.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_LIQUIDATION)

    def test_liquidation_imminent_overrides_carry(self):
        # Even positive carry → LIQUIDATION if margin ≤ threshold
        r = self.a.analyze([_pos(apy=10.0, borrow_rate=1.0, liq_threshold=80.0, current_ltv=79.5)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_LIQUIDATION)

    def test_label_is_string(self):
        r = self.a.analyze([_pos()], {})
        self.assertIsInstance(r["positions"][0]["label"], str)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_rebasing_oracle_risk_flag(self):
        r = self.a.analyze([_pos(rebasing="rebasing", oracle="protocol_native")], {})
        self.assertIn("REBASING_ORACLE_RISK", r["positions"][0]["flags"])

    def test_no_rebasing_oracle_risk_chainlink(self):
        r = self.a.analyze([_pos(rebasing="rebasing", oracle="chainlink")], {})
        self.assertNotIn("REBASING_ORACLE_RISK", r["positions"][0]["flags"])

    def test_no_rebasing_oracle_risk_non_rebasing(self):
        r = self.a.analyze([_pos(rebasing="non_rebasing", oracle="protocol_native")], {})
        self.assertNotIn("REBASING_ORACLE_RISK", r["positions"][0]["flags"])

    def test_positive_carry_flag(self):
        r = self.a.analyze([_pos(apy=6.0, borrow_rate=2.0)], {})
        self.assertIn("POSITIVE_CARRY", r["positions"][0]["flags"])

    def test_no_positive_carry_flag_when_negative(self):
        r = self.a.analyze([_pos(apy=2.0, borrow_rate=5.0)], {})
        self.assertNotIn("POSITIVE_CARRY", r["positions"][0]["flags"])

    def test_yield_dominant_flag(self):
        # apy = 6, borrow = 2, ratio = 3 > 2.0 threshold
        r = self.a.analyze([_pos(apy=6.0, borrow_rate=2.0)], {})
        self.assertIn("YIELD_DOMINANT", r["positions"][0]["flags"])

    def test_no_yield_dominant_flag_when_below_ratio(self):
        # apy=3, borrow=2, ratio=1.5 < 2.0 → not YIELD_DOMINANT
        r = self.a.analyze([_pos(apy=3.0, borrow_rate=2.0)], {})
        self.assertNotIn("YIELD_DOMINANT", r["positions"][0]["flags"])

    def test_yield_dominant_zero_borrow(self):
        # borrow_rate=0 and apy>0 → YIELD_DOMINANT
        r = self.a.analyze([_pos(apy=5.0, borrow_rate=0.0)], {})
        self.assertIn("YIELD_DOMINANT", r["positions"][0]["flags"])

    def test_high_oracle_lag_flag(self):
        # protocol_native oracle + rebasing + high price deviation → lag > 70
        r = self.a.analyze([_pos(rebasing="rebasing", oracle="protocol_native", price_dev=10.0)], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        if score > 70:
            self.assertIn("HIGH_ORACLE_LAG", r["positions"][0]["flags"])

    def test_flags_is_list(self):
        r = self.a.analyze([_pos()], {})
        self.assertIsInstance(r["positions"][0]["flags"], list)

    def test_tight_liquidation_exactly_at_threshold(self):
        # safety margin exactly 5.0 — borderline, should NOT trigger TIGHT (<5%)
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=75.0)], {})
        self.assertNotIn("TIGHT_LIQUIDATION", r["positions"][0]["flags"])

    def test_tight_liquidation_just_below_threshold(self):
        # safety margin = 4.9 → TIGHT
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=75.1)], {})
        self.assertIn("TIGHT_LIQUIDATION", r["positions"][0]["flags"])


class TestOracleLagRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_chainlink_lowest_base(self):
        r = self.a.analyze([_pos(oracle="chainlink", rebasing="non_rebasing", price_dev=0.0)], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        self.assertLessEqual(score, 50.0)

    def test_protocol_native_higher_than_chainlink(self):
        r_cl = self.a.analyze([_pos(oracle="chainlink", rebasing="non_rebasing", price_dev=0.0)], {})
        r_pn = self.a.analyze([_pos(oracle="protocol_native", rebasing="non_rebasing", price_dev=0.0)], {})
        self.assertGreater(
            r_pn["positions"][0]["oracle_lag_risk_score"],
            r_cl["positions"][0]["oracle_lag_risk_score"],
        )

    def test_twap_between_chainlink_and_protocol_native(self):
        r_cl = self.a.analyze([_pos(oracle="chainlink", rebasing="non_rebasing", price_dev=0.0)], {})
        r_tw = self.a.analyze([_pos(oracle="twap", rebasing="non_rebasing", price_dev=0.0)], {})
        r_pn = self.a.analyze([_pos(oracle="protocol_native", rebasing="non_rebasing", price_dev=0.0)], {})
        self.assertGreater(
            r_tw["positions"][0]["oracle_lag_risk_score"],
            r_cl["positions"][0]["oracle_lag_risk_score"],
        )
        self.assertLess(
            r_tw["positions"][0]["oracle_lag_risk_score"],
            r_pn["positions"][0]["oracle_lag_risk_score"],
        )

    def test_rebasing_adds_penalty(self):
        r_non = self.a.analyze([_pos(oracle="chainlink", rebasing="non_rebasing", price_dev=0.0)], {})
        r_reb = self.a.analyze([_pos(oracle="chainlink", rebasing="rebasing", price_dev=0.0)], {})
        self.assertGreater(
            r_reb["positions"][0]["oracle_lag_risk_score"],
            r_non["positions"][0]["oracle_lag_risk_score"],
        )

    def test_price_deviation_adds_penalty(self):
        r_low = self.a.analyze([_pos(price_dev=0.0)], {})
        r_high = self.a.analyze([_pos(price_dev=10.0)], {})
        self.assertGreater(
            r_high["positions"][0]["oracle_lag_risk_score"],
            r_low["positions"][0]["oracle_lag_risk_score"],
        )

    def test_score_capped_at_100(self):
        r = self.a.analyze([_pos(oracle="protocol_native", rebasing="rebasing", price_dev=100.0)], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        self.assertLessEqual(score, 100.0)

    def test_score_non_negative(self):
        r = self.a.analyze([_pos()], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        self.assertGreaterEqual(score, 0.0)


class TestYieldCaptureEfficiency(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_full_efficiency_no_borrow(self):
        r = self.a.analyze([_pos(apy=5.0, borrow_rate=0.0)], {})
        self.assertAlmostEqual(r["positions"][0]["yield_capture_efficiency_pct"], 100.0, places=2)

    def test_zero_efficiency_negative_carry(self):
        r = self.a.analyze([_pos(apy=0.0, borrow_rate=5.0)], {})
        self.assertAlmostEqual(r["positions"][0]["yield_capture_efficiency_pct"], 0.0, places=2)

    def test_partial_efficiency(self):
        r = self.a.analyze([_pos(apy=10.0, borrow_rate=5.0)], {})
        # net=5, apy=10 → 50%
        self.assertAlmostEqual(r["positions"][0]["yield_capture_efficiency_pct"], 50.0, places=2)

    def test_efficiency_100_when_both_zero(self):
        r = self.a.analyze([_pos(apy=0.0, borrow_rate=0.0)], {})
        self.assertAlmostEqual(r["positions"][0]["yield_capture_efficiency_pct"], 100.0, places=2)

    def test_efficiency_above_100_not_possible(self):
        # apy=10, borrow=0 → 100% capped
        r = self.a.analyze([_pos(apy=10.0, borrow_rate=0.0)], {})
        eff = r["positions"][0]["yield_capture_efficiency_pct"]
        self.assertLessEqual(eff, 100.0)


class TestLiquidationBuffer(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_liq_buffer_positive_when_safe(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=60.0)], {})
        self.assertGreater(r["positions"][0]["liquidation_buffer_days_estimate"], 0)

    def test_liq_buffer_zero_when_at_threshold(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=80.0)], {})
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_days_estimate"], 0.0, places=2)

    def test_liq_buffer_zero_when_breached(self):
        r = self.a.analyze([_pos(liq_threshold=80.0, current_ltv=85.0)], {})
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_days_estimate"], 0.0, places=2)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_aggregates_empty(self):
        r = self.a.analyze([], {})
        agg = r["aggregates"]
        self.assertIsNone(agg["best_carry_pct"])
        self.assertEqual(agg["total_positions"], 0)
        self.assertEqual(agg["total_position_value_usd"], 0.0)

    def test_aggregates_best_carry(self):
        r = self.a.analyze([
            _pos(apy=8.0, borrow_rate=2.0, value=100_000),  # carry=6
            _pos(apy=5.0, borrow_rate=4.0, value=50_000),   # carry=1
        ], {})
        self.assertAlmostEqual(r["aggregates"]["best_carry_pct"], 6.0, places=2)

    def test_aggregates_worst_carry(self):
        r = self.a.analyze([
            _pos(apy=8.0, borrow_rate=2.0),  # carry=6
            _pos(apy=2.0, borrow_rate=5.0),  # carry=-3
        ], {})
        self.assertAlmostEqual(r["aggregates"]["worst_carry_pct"], -3.0, places=2)

    def test_aggregates_total_value(self):
        r = self.a.analyze([
            _pos(value=100_000),
            _pos(value=200_000),
        ], {})
        self.assertAlmostEqual(r["aggregates"]["total_position_value_usd"], 300_000.0, places=2)

    def test_aggregates_average_carry(self):
        r = self.a.analyze([
            _pos(apy=6.0, borrow_rate=2.0),  # carry=4
            _pos(apy=4.0, borrow_rate=2.0),  # carry=2
        ], {})
        self.assertAlmostEqual(r["aggregates"]["average_net_carry_pct"], 3.0, places=2)

    def test_aggregates_liquidation_imminent_count(self):
        r = self.a.analyze([
            _pos(liq_threshold=80.0, current_ltv=79.5),  # imminent
            _pos(liq_threshold=80.0, current_ltv=50.0),  # safe
        ], {})
        self.assertEqual(r["aggregates"]["liquidation_imminent_count"], 1)

    def test_aggregates_positive_carry_count(self):
        r = self.a.analyze([
            _pos(apy=8.0, borrow_rate=2.0),  # positive
            _pos(apy=2.0, borrow_rate=5.0),  # negative
            _pos(apy=3.0, borrow_rate=3.0),  # break even
        ], {})
        self.assertEqual(r["aggregates"]["positive_carry_count"], 1)

    def test_aggregates_negative_carry_count(self):
        r = self.a.analyze([
            _pos(apy=2.0, borrow_rate=5.0),
            _pos(apy=2.0, borrow_rate=6.0),
        ], {})
        self.assertEqual(r["aggregates"]["negative_carry_count"], 2)

    def test_aggregates_rebasing_oracle_risk_count(self):
        r = self.a.analyze([
            _pos(rebasing="rebasing", oracle="protocol_native"),
            _pos(rebasing="non_rebasing", oracle="protocol_native"),
        ], {})
        self.assertEqual(r["aggregates"]["rebasing_oracle_risk_count"], 1)

    def test_aggregates_total_positions(self):
        r = self.a.analyze([_pos(), _pos(), _pos()], {})
        self.assertEqual(r["aggregates"]["total_positions"], 3)


class TestOutputSchema(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_output_has_positions_key(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("positions", r)

    def test_output_has_aggregates_key(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("aggregates", r)

    def test_output_has_meta_key(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("meta", r)

    def test_meta_module(self):
        r = self.a.analyze([_pos()], {})
        self.assertEqual(r["meta"]["module"], "MP-966")

    def test_meta_version(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("version", r["meta"])

    def test_meta_generated_at(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("generated_at", r["meta"])

    def test_position_has_net_carry(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("net_carry_pct", r["positions"][0])

    def test_position_has_safety_margin(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("safety_margin_pct", r["positions"][0])

    def test_position_has_liq_buffer(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("liquidation_buffer_days_estimate", r["positions"][0])

    def test_position_has_yield_capture_eff(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("yield_capture_efficiency_pct", r["positions"][0])

    def test_position_has_oracle_lag_risk(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("oracle_lag_risk_score", r["positions"][0])

    def test_position_has_label(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("label", r["positions"][0])

    def test_position_has_flags(self):
        r = self.a.analyze([_pos()], {})
        self.assertIn("flags", r["positions"][0])

    def test_result_serializable(self):
        r = self.a.analyze([_pos()], {})
        # Must not raise
        json.dumps(r)

    def test_multiple_positions(self):
        positions = [_pos(asset=f"token_{i}") for i in range(5)]
        r = self.a.analyze(positions, {})
        self.assertEqual(len(r["positions"]), 5)


class TestConfigOverrides(unittest.TestCase):
    def test_custom_optimal_carry_min(self):
        a = DeFiYieldBearingCollateralAnalyzer({"optimal_carry_min_pct": 5.0})
        # carry=3 < 5.0 → POSITIVE_CARRY not OPTIMAL
        r = a.analyze([_pos(apy=6.0, borrow_rate=3.0, liq_threshold=80.0, current_ltv=50.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_POSITIVE)

    def test_custom_tight_liquidation_threshold(self):
        a = DeFiYieldBearingCollateralAnalyzer({"tight_liquidation_threshold": 15.0})
        # safety margin = 20 - 15 = 5 → would be TIGHT at threshold=15
        r = a.analyze([_pos(liq_threshold=80.0, current_ltv=70.0)], {})
        # margin=10, threshold=15 → TIGHT
        self.assertIn("TIGHT_LIQUIDATION", r["positions"][0]["flags"])

    def test_custom_liq_imminent_margin(self):
        a = DeFiYieldBearingCollateralAnalyzer({"liquidation_imminent_safety_margin": 10.0})
        # safety margin=8 ≤ 10 → LIQUIDATION_IMMINENT
        r = a.analyze([_pos(liq_threshold=80.0, current_ltv=72.0)], {})
        self.assertEqual(r["positions"][0]["label"], LABEL_LIQUIDATION)

    def test_runtime_config_override(self):
        a = DeFiYieldBearingCollateralAnalyzer()
        r = a.analyze(
            [_pos(apy=5.0, borrow_rate=0.0, liq_threshold=80.0, current_ltv=50.0)],
            {"optimal_carry_min_pct": 10.0},  # carry=5 < 10 → POSITIVE
        )
        self.assertEqual(r["positions"][0]["label"], LABEL_POSITIVE)

    def test_custom_yield_dominant_ratio(self):
        a = DeFiYieldBearingCollateralAnalyzer({"yield_dominant_ratio": 3.0})
        # apy=5, borrow=2, ratio=2.5 < 3 → NOT YIELD_DOMINANT
        r = a.analyze([_pos(apy=5.0, borrow_rate=2.0)], {})
        self.assertNotIn("YIELD_DOMINANT", r["positions"][0]["flags"])


class TestRebasingTypes(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_wrapped_oracle_lag_between_non_and_rebasing(self):
        r_non = self.a.analyze([_pos(rebasing="non_rebasing", oracle="chainlink", price_dev=0)], {})
        r_wrp = self.a.analyze([_pos(rebasing="wrapped", oracle="chainlink", price_dev=0)], {})
        r_reb = self.a.analyze([_pos(rebasing="rebasing", oracle="chainlink", price_dev=0)], {})
        self.assertGreater(
            r_wrp["positions"][0]["oracle_lag_risk_score"],
            r_non["positions"][0]["oracle_lag_risk_score"],
        )
        self.assertLess(
            r_wrp["positions"][0]["oracle_lag_risk_score"],
            r_reb["positions"][0]["oracle_lag_risk_score"],
        )

    def test_rebasing_preserved_in_output(self):
        r = self.a.analyze([_pos(rebasing="rebasing")], {})
        self.assertEqual(r["positions"][0]["rebasing_type"], "rebasing")


class TestPositionPassthrough(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_asset_name_passthrough(self):
        r = self.a.analyze([_pos(asset="cDAI")], {})
        self.assertEqual(r["positions"][0]["asset_name"], "cDAI")

    def test_protocol_passthrough(self):
        r = self.a.analyze([_pos(protocol="Compound V3")], {})
        self.assertEqual(r["positions"][0]["protocol_used_as_collateral"], "Compound V3")

    def test_position_value_passthrough(self):
        r = self.a.analyze([_pos(value=777_000.0)], {})
        self.assertAlmostEqual(r["positions"][0]["position_value_usd"], 777_000.0, places=2)

    def test_oracle_type_passthrough(self):
        r = self.a.analyze([_pos(oracle="twap")], {})
        self.assertEqual(r["positions"][0]["oracle_type"], "twap")

    def test_price_deviation_passthrough(self):
        r = self.a.analyze([_pos(price_dev=3.5)], {})
        self.assertAlmostEqual(r["positions"][0]["price_deviation_risk_pct"], 3.5, places=4)


class TestWriteLog(unittest.TestCase):
    def _make_result(self):
        a = DeFiYieldBearingCollateralAnalyzer()
        return a.analyze([_pos()], {})

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            self.assertTrue((Path(td) / LOG_FILE).exists())

    def test_write_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertIsInstance(data, list)

    def test_write_appends(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            for _ in range(LOG_CAP + 5):
                write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertLessEqual(len(data), LOG_CAP)

    def test_atomic_write_no_partial(self):
        """File should be complete JSON after write_log."""
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            content = (Path(td) / LOG_FILE).read_text()
            # Should parse without error
            json.loads(content)

    def test_write_to_nonexistent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = Path(td) / "nested" / "dir"
            write_log(self._make_result(), new_dir)
            self.assertTrue((new_dir / LOG_FILE).exists())


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiYieldBearingCollateralAnalyzer()

    def test_empty_positions_list(self):
        r = self.a.analyze([], {})
        self.assertEqual(r["positions"], [])
        self.assertEqual(r["aggregates"]["total_positions"], 0)

    def test_none_config(self):
        r = self.a.analyze([_pos()], None)
        self.assertIn("positions", r)

    def test_missing_optional_keys_dont_crash(self):
        minimal = {"asset_name": "X", "protocol_used_as_collateral": "P"}
        r = self.a.analyze([minimal], {})
        self.assertEqual(len(r["positions"]), 1)

    def test_large_position_value(self):
        r = self.a.analyze([_pos(value=1e9)], {})
        self.assertAlmostEqual(r["positions"][0]["position_value_usd"], 1e9, delta=1.0)

    def test_very_high_apy(self):
        r = self.a.analyze([_pos(apy=999.0, borrow_rate=1.0)], {})
        self.assertGreater(r["positions"][0]["net_carry_pct"], 0)

    def test_zero_position_value(self):
        r = self.a.analyze([_pos(value=0.0)], {})
        self.assertAlmostEqual(r["aggregates"]["total_position_value_usd"], 0.0, places=2)

    def test_unknown_oracle_type(self):
        r = self.a.analyze([_pos(oracle="custom_oracle")], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_unknown_rebasing_type(self):
        r = self.a.analyze([_pos(rebasing="hybrid")], {})
        score = r["positions"][0]["oracle_lag_risk_score"]
        self.assertGreaterEqual(score, 0.0)

    def test_meta_position_count_matches(self):
        positions = [_pos() for _ in range(7)]
        r = self.a.analyze(positions, {})
        self.assertEqual(r["meta"]["position_count"], 7)

    def test_single_position_aggregates(self):
        r = self.a.analyze([_pos(apy=5.0, borrow_rate=3.0, value=100_000)], {})
        agg = r["aggregates"]
        self.assertAlmostEqual(agg["best_carry_pct"], 2.0, places=2)
        self.assertAlmostEqual(agg["worst_carry_pct"], 2.0, places=2)
        self.assertAlmostEqual(agg["average_net_carry_pct"], 2.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
