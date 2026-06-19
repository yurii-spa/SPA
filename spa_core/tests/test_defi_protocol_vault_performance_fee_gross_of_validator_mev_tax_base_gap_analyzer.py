"""
Tests for MP-1239:
DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer
Run: python3 -m pytest spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_validator_mev_tax_base_gap_analyzer.py -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_performance_fee_gross_of_validator_mev_tax_base_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_signed,
    _coerce_count,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    estimate_annual_mev_tax_bps,
    get_mev_boost_adoption,
    apply_gap,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_VALIDATOR_MEV_TAX_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
    CHAIN_MEV_TAX_BPS,
    MEV_BOOST_ADOPTION_RATE,
    PROPOSER_PAYMENT_THRESHOLD_ETH,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    net_of_validator_mev_tax_yield_pct=None,
    performance_fee_pct=None,
    validator_mev_tax_rate_pct=None,
    fee_on_validator_mev_tax_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_validator_mev_tax_yield_pct is not None:
        pos["net_of_validator_mev_tax_yield_pct"] = (
            net_of_validator_mev_tax_yield_pct)
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if validator_mev_tax_rate_pct is not None:
        pos["validator_mev_tax_rate_pct"] = validator_mev_tax_rate_pct
    if fee_on_validator_mev_tax_gap_pct is not None:
        pos["fee_on_validator_mev_tax_gap_pct"] = (
            fee_on_validator_mev_tax_gap_pct)
    if fee_charged_pct is not None:
        pos["fee_charged_pct"] = fee_charged_pct
    return pos


def _all_floats_finite(obj):
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_floats_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_floats_finite(v) for v in obj)
    return True


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 3.0), 3.0)
        self.assertEqual(_f("x", 1.0), 1.0)
        self.assertEqual(_f("2.5"), 2.5)
        self.assertEqual(_f(4), 4.0)

    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-5, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertEqual(_mean([2, 4]), 3.0)
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0, places=6)

    def test_safe_div_positive(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(10, -1, None))

    def test_coerce_num_basic(self):
        self.assertAlmostEqual(_coerce_num(3.14), 3.14)
        self.assertAlmostEqual(_coerce_num("2.5"), 2.5)
        self.assertAlmostEqual(_coerce_num(5), 5.0)

    def test_coerce_num_rejects_bool(self):
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))

    def test_coerce_num_rejects_nan_inf(self):
        self.assertIsNone(_coerce_num(float("nan")))
        self.assertIsNone(_coerce_num(float("inf")))
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_coerce_signed_accepts_negative(self):
        self.assertAlmostEqual(_coerce_signed(-3.5), -3.5)

    def test_coerce_count_basic(self):
        self.assertEqual(_coerce_count(5), 5)
        self.assertEqual(_coerce_count(0), 0)
        self.assertIsNone(_coerce_count(-1))

    def test_grade_from_score_boundaries(self):
        self.assertEqual(_grade_from_score(100.0), "A")
        self.assertEqual(_grade_from_score(85.0), "A")
        self.assertEqual(_grade_from_score(84.9), "B")
        self.assertEqual(_grade_from_score(70.0), "B")
        self.assertEqual(_grade_from_score(69.9), "C")
        self.assertEqual(_grade_from_score(55.0), "C")
        self.assertEqual(_grade_from_score(54.9), "D")
        self.assertEqual(_grade_from_score(40.0), "D")
        self.assertEqual(_grade_from_score(39.9), "F")
        self.assertEqual(_grade_from_score(0.0), "F")


# ── chain-specific estimate tests ────────────────────────────────────────────

class TestEstimateAnnualMevTaxBps(unittest.TestCase):
    def test_ethereum_mainnet(self):
        self.assertEqual(estimate_annual_mev_tax_bps("ethereum"), 8)

    def test_ethereum_case_insensitive(self):
        self.assertEqual(estimate_annual_mev_tax_bps("Ethereum"), 8)
        self.assertEqual(estimate_annual_mev_tax_bps("ETHEREUM"), 8)

    def test_arbitrum_near_zero(self):
        self.assertEqual(estimate_annual_mev_tax_bps("arbitrum"), 1)

    def test_base_near_zero(self):
        self.assertEqual(estimate_annual_mev_tax_bps("base"), 1)

    def test_optimism_near_zero(self):
        self.assertEqual(estimate_annual_mev_tax_bps("optimism"), 1)

    def test_unknown_chain_zero(self):
        self.assertEqual(estimate_annual_mev_tax_bps("solana"), 0)
        self.assertEqual(estimate_annual_mev_tax_bps("unknown"), 0)

    def test_l2_lower_than_l1(self):
        eth = estimate_annual_mev_tax_bps("ethereum")
        for chain in ["arbitrum", "base", "optimism"]:
            self.assertLess(estimate_annual_mev_tax_bps(chain), eth)


class TestGetMevBoostAdoption(unittest.TestCase):
    def test_ethereum(self):
        self.assertAlmostEqual(get_mev_boost_adoption("ethereum"), 0.92)

    def test_unknown_chain(self):
        self.assertAlmostEqual(get_mev_boost_adoption("arbitrum"), 0.0)
        self.assertAlmostEqual(get_mev_boost_adoption("solana"), 0.0)


class TestApplyGap(unittest.TestCase):
    def test_apply_gap_basic(self):
        result = apply_gap(10.0, 8)
        self.assertAlmostEqual(result, 9.92, places=4)

    def test_apply_gap_zero_bps(self):
        self.assertAlmostEqual(apply_gap(10.0, 0), 10.0)

    def test_apply_gap_large_bps(self):
        result = apply_gap(5.0, 600)
        self.assertAlmostEqual(result, 0.0)

    def test_apply_gap_negative_yield_floor(self):
        result = apply_gap(0.5, 200)
        self.assertAlmostEqual(result, 0.0)


# ── main-path classification ─────────────────────────────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_clean_equal_net_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_validator_mev_tax_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_clean_net_slightly_below_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_validator_mev_tax_yield_pct=14.8,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")

    def test_mild_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.2, places=4)
        self.assertEqual(
            r["classification"],
            "MILD_FEE_ON_VALIDATOR_MEV_TAX_GAP")

    def test_moderate_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.5, places=4)
        self.assertEqual(
            r["classification"],
            "MODERATE_FEE_ON_VALIDATOR_MEV_TAX_GAP")

    def test_severe_gap_high_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=4.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.8, places=4)
        self.assertEqual(
            r["classification"],
            "SEVERE_FEE_ON_VALIDATOR_MEV_TAX_GAP")

    def test_severe_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(
            r["classification"],
            "SEVERE_FEE_ON_VALIDATOR_MEV_TAX_GAP")
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_net_zero_default(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["fee_on_validator_mev_tax_fraction"], 1.0)
        self.assertEqual(
            r["classification"],
            "SEVERE_FEE_ON_VALIDATOR_MEV_TAX_GAP")

    def test_net_exceeds_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.0)
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")


# ── override path ────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_override_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.4, places=4)
        self.assertEqual(
            r["classification"],
            "MODERATE_FEE_ON_VALIDATOR_MEV_TAX_GAP")

    def test_override_gap_exceeds_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=15.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_gap_pct"], 10.0, places=4)
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 1.0, places=4)

    def test_override_negative_gap_uses_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=-3.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_gap_pct"], 3.0, places=4)

    def test_override_geometry_fields_none(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=2.0,
            fee_charged_pct=10.0))
        self.assertIsNone(r["net_of_validator_mev_tax_yield_pct"])
        self.assertIsNone(r["validator_mev_tax_consumed_yield_pct"])

    def test_override_has_gap_from_override_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=2.0,
            fee_charged_pct=10.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_no_geometry_flags(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=2.0,
            fee_charged_pct=10.0))
        self.assertNotIn("FEE_ON_VALIDATOR_MEV_TAX", r["flags"])
        self.assertNotIn("FULL_FEE_ON_VALIDATOR_MEV_TAX", r["flags"])

    def test_override_realization_ratio(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=4.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.6, places=4)

    def test_override_zero_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            fee_on_validator_mev_tax_gap_pct=0.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_fraction"], 0.0, places=4)
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")


# ── insufficient data ────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_no_gross_yield(self):
        r = self.an.analyze(make_pos(
            performance_fee_pct=20.0,
            net_of_validator_mev_tax_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_zero_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=-5.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("nan"),
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("inf"),
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            performance_fee_pct=float("nan"),
            net_of_validator_mev_tax_yield_pct=8.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_position(self):
        r = self.an.analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")


# ── scoring ──────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_clean_score_high(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertGreaterEqual(r["score"], 85.0)
        self.assertEqual(r["grade"], "A")

    def test_severe_score_low(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertLessEqual(r["score"], 40.0)
        self.assertIn(r["grade"], ("D", "F"))

    def test_moderate_score_mid(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertGreater(r["score"], 40.0)
        self.assertLess(r["score"], 85.0)

    def test_score_monotonic_with_net(self):
        scores = []
        for net in [2.0, 6.0, 10.0, 14.0, 18.0]:
            r = self.an.analyze(make_pos(
                gross_yield_pct=20.0,
                net_of_validator_mev_tax_yield_pct=net,
                performance_fee_pct=20.0))
            scores.append(r["score"])
        for i in range(1, len(scores)):
            self.assertGreaterEqual(scores[i], scores[i - 1])


# ── flags ────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_high_validator_mev_tax_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=20.0,
            validator_mev_tax_rate_pct=0.5))
        self.assertIn("HIGH_VALIDATOR_MEV_TAX", r["flags"])

    def test_no_high_tax_flag_below_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=20.0,
            validator_mev_tax_rate_pct=0.1))
        self.assertNotIn("HIGH_VALIDATOR_MEV_TAX", r["flags"])

    def test_fee_on_validator_mev_tax_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_VALIDATOR_MEV_TAX", r["flags"])

    def test_full_fee_on_validator_mev_tax_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_VALIDATOR_MEV_TAX", r["flags"])

    def test_full_fee_negative_net(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=-1.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_VALIDATOR_MEV_TAX", r["flags"])
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])


# ── recommendation ───────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_trust_fee_structure(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_minor_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["recommendation"], "MINOR_FEE_ON_VALIDATOR_MEV_TAX")

    def test_demand_net_base(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_validator_mev_tax_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["recommendation"],
            "DEMAND_NET_OF_VALIDATOR_MEV_TAX_BASE")

    def test_avoid_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(
            r["recommendation"], "AVOID_FEE_ON_VALIDATOR_MEV_TAX")


# ── portfolio / aggregate ────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_portfolio_basic(self):
        positions = [
            make_pos(
                vault="A",
                gross_yield_pct=15.0,
                net_of_validator_mev_tax_yield_pct=15.0,
                performance_fee_pct=20.0),
            make_pos(
                vault="B",
                gross_yield_pct=10.0,
                net_of_validator_mev_tax_yield_pct=-2.0,
                performance_fee_pct=50.0),
        ]
        result = self.an.analyze_portfolio(positions)
        self.assertEqual(len(result["positions"]), 2)
        agg = result["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "A")
        self.assertEqual(
            agg["worst_validator_mev_tax_gap_vault"], "B")
        self.assertEqual(agg["position_count"], 2)

    def test_portfolio_all_insufficient(self):
        positions = [make_pos(), make_pos()]
        result = self.an.analyze_portfolio(positions)
        agg = result["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    def test_portfolio_net_negative_count(self):
        positions = [
            make_pos(
                vault="X",
                gross_yield_pct=10.0,
                net_of_validator_mev_tax_yield_pct=-1.0,
                performance_fee_pct=20.0),
            make_pos(
                vault="Y",
                gross_yield_pct=10.0,
                net_of_validator_mev_tax_yield_pct=-3.0,
                performance_fee_pct=30.0),
            make_pos(
                vault="Z",
                gross_yield_pct=10.0,
                net_of_validator_mev_tax_yield_pct=10.0,
                performance_fee_pct=20.0),
        ]
        result = self.an.analyze_portfolio(positions)
        self.assertEqual(result["aggregate"]["net_negative_count"], 2)


# ── write log ────────────────────────────────────────────────────────────────

class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, "test_log.json")
            self.an.analyze(
                make_pos(
                    gross_yield_pct=10.0,
                    net_of_validator_mev_tax_yield_pct=8.0,
                    performance_fee_pct=20.0),
                cfg={"log_path": lp, "log_cap": 10},
                write_log=True)
            self.assertTrue(os.path.exists(lp))
            with open(lp) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertIn("ts", data[0])
            self.assertIn("aggregate", data[0])

    def test_write_log_ring_buffer(self):
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, "test_log.json")
            for i in range(15):
                self.an.analyze(
                    make_pos(
                        vault=f"V-{i}",
                        gross_yield_pct=10.0,
                        net_of_validator_mev_tax_yield_pct=8.0,
                        performance_fee_pct=20.0),
                    cfg={"log_path": lp, "log_cap": 5},
                    write_log=True)
            with open(lp) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 5)

    def test_write_log_portfolio(self):
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, "test_log.json")
            self.an.analyze_portfolio(
                [make_pos(
                    vault="PF",
                    gross_yield_pct=10.0,
                    net_of_validator_mev_tax_yield_pct=8.0,
                    performance_fee_pct=20.0)],
                cfg={"log_path": lp, "log_cap": 10},
                write_log=True)
            self.assertTrue(os.path.exists(lp))


# ── edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_zero_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 0.0)
        self.assertAlmostEqual(
            r["fee_on_validator_mev_tax_gap_pct"], 0.0)
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")

    def test_100_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=100.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 10.0)

    def test_very_small_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.001,
            net_of_validator_mev_tax_yield_pct=0.001,
            performance_fee_pct=20.0))
        self.assertEqual(
            r["classification"],
            "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE")

    def test_token_key_fallback(self):
        r = self.an.analyze({
            "token": "MY-TOKEN",
            "gross_yield_pct": 10.0,
            "net_of_validator_mev_tax_yield_pct": 10.0,
            "performance_fee_pct": 20.0,
        })
        self.assertEqual(r["token"], "MY-TOKEN")

    def test_string_numeric_values(self):
        r = self.an.analyze({
            "vault": "STR-Vault",
            "gross_yield_pct": "10.0",
            "net_of_validator_mev_tax_yield_pct": "8.0",
            "performance_fee_pct": "20",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bool_gross_yield_rejected(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=True,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_floats_finite_in_result(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=20.0,
            validator_mev_tax_rate_pct=0.1))
        self.assertTrue(_all_floats_finite(r))

    def test_all_floats_finite_insufficient(self):
        r = self.an.analyze(make_pos())
        self.assertTrue(_all_floats_finite(r))

    def test_performance_fee_clamped_above_100(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=200.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0)

    def test_performance_fee_clamped_below_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=-10.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 0.0)

    def test_override_not_triggered_without_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            fee_on_validator_mev_tax_gap_pct=2.0,
            performance_fee_pct=20.0,
            net_of_validator_mev_tax_yield_pct=8.0))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])

    def test_override_not_triggered_zero_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            fee_on_validator_mev_tax_gap_pct=2.0,
            fee_charged_pct=0.0,
            performance_fee_pct=20.0,
            net_of_validator_mev_tax_yield_pct=8.0))
        self.assertTrue(r["used_main"])


# ── config constants ─────────────────────────────────────────────────────────

class TestConfigConstants(unittest.TestCase):
    def test_chain_mev_tax_bps_keys(self):
        for chain in ["ethereum", "arbitrum", "base", "optimism"]:
            self.assertIn(chain, CHAIN_MEV_TAX_BPS)

    def test_mev_boost_adoption_ethereum(self):
        self.assertIn("ethereum", MEV_BOOST_ADOPTION_RATE)
        self.assertGreater(MEV_BOOST_ADOPTION_RATE["ethereum"], 0.5)

    def test_proposer_payment_threshold(self):
        self.assertGreater(PROPOSER_PAYMENT_THRESHOLD_ETH, 0.0)

    def test_clean_fraction_value(self):
        self.assertAlmostEqual(CLEAN_FRACTION, 0.05)

    def test_mild_fraction_value(self):
        self.assertAlmostEqual(MILD_FRACTION, 0.20)

    def test_moderate_fraction_value(self):
        self.assertAlmostEqual(MODERATE_FRACTION, 0.50)

    def test_high_tax_threshold(self):
        self.assertAlmostEqual(HIGH_VALIDATOR_MEV_TAX_PCT, 0.3)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


# ── comparison vs bundler_fee (different layers) ─────────────────────────────

class TestComparisonVsBundlerFee(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_validator_mev_tax_is_distinct_module(self):
        self.assertIn("Validator", type(self.an).__name__)
        self.assertNotIn("Bundler", type(self.an).__name__)

    def test_validator_mev_tax_uses_own_fields(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_validator_mev_tax_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertIn("fee_on_validator_mev_tax_fraction", r)
        self.assertIn("net_of_validator_mev_tax_yield_pct", r)
        self.assertNotIn("fee_on_bundler_fee_fraction", r)


# ── demo positions ───────────────────────────────────────────────────────────

class TestDemoPositions(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_positions_all_run(self):
        result = self.an.analyze_portfolio(_demo_positions())
        self.assertEqual(len(result["positions"]), 5)
        for r in result["positions"]:
            self.assertIn("classification", r)

    def test_demo_positions_no_nan_inf(self):
        result = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(result))


# ── registry check ───────────────────────────────────────────────────────────

class TestRegistryCheck(unittest.TestCase):
    def test_module_importable(self):
        import importlib
        mod = importlib.import_module(
            "spa_core.analytics."
            "defi_protocol_vault_performance_fee_gross_of_"
            "validator_mev_tax_base_gap_analyzer")
        self.assertTrue(hasattr(
            mod,
            "DeFiProtocolVaultPerformanceFeeGrossOf"
            "ValidatorMevTaxBaseGapAnalyzer"))

    def test_class_has_analyze(self):
        self.assertTrue(hasattr(
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer,
            "analyze"))

    def test_class_has_analyze_portfolio(self):
        self.assertTrue(hasattr(
            DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer,
            "analyze_portfolio"))

    def test_estimate_and_apply_gap_roundtrip(self):
        bps = estimate_annual_mev_tax_bps("ethereum")
        adjusted = apply_gap(10.0, bps)
        self.assertLess(adjusted, 10.0)
        self.assertGreater(adjusted, 9.0)


if __name__ == "__main__":
    unittest.main()
