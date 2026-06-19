"""
Tests for MP-1240: SequencerTipGapAnalyzer
Run: python3 -m pytest spa_core/tests/test_gross_of/test_sequencer_tip.py -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.gross_of.sequencer_tip import (
    SequencerTipGapAnalyzer,
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
    is_sequencer_chain,
    estimate_annual_tip_bps,
    compute_tip_drag,
    apply_gap,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_TIP_BPS,
    EPS,
    LOG_PATH,
    LOG_CAP,
)
from spa_core.analytics.gross_of.sequencer_tip_config import (
    CHAINS_WITH_SEQUENCER,
    CHAINS_WITHOUT_SEQUENCER,
    ANNUAL_TIP_BPS_ESTIMATE,
    TX_PER_YEAR_TYPICAL,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="Test-Vault",
    chain="arbitrum",
    gross_yield_pct=None,
    net_of_tip_yield_pct=None,
    performance_fee_pct=None,
    tip_rate_bps=None,
    fee_on_tip_gap_pct=None,
    fee_charged_pct=None,
    allocation_usd=None,
):
    pos = {"vault": vault, "chain": chain}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_tip_yield_pct is not None:
        pos["net_of_tip_yield_pct"] = net_of_tip_yield_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if tip_rate_bps is not None:
        pos["tip_rate_bps"] = tip_rate_bps
    if fee_on_tip_gap_pct is not None:
        pos["fee_on_tip_gap_pct"] = fee_on_tip_gap_pct
    if fee_charged_pct is not None:
        pos["fee_charged_pct"] = fee_charged_pct
    if allocation_usd is not None:
        pos["allocation_usd"] = allocation_usd
    return pos


def _all_floats_finite(obj):
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_floats_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_floats_finite(v) for v in obj)
    return True


# ── helper tests ─────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    # 1
    def test_f_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 3.0), 3.0)
        self.assertEqual(_f("x", 1.0), 1.0)
        self.assertEqual(_f("2.5"), 2.5)
        self.assertEqual(_f(4), 4.0)

    # 2
    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-5, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    # 3
    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    # 4
    def test_mean_values(self):
        self.assertEqual(_mean([2, 4]), 3.0)
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0, places=6)

    # 5
    def test_safe_div_positive(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)

    # 6
    def test_safe_div_zero_denom(self):
        self.assertIsNone(_safe_div(10, 0, None))
        self.assertEqual(_safe_div(10, -1, "fallback"), "fallback")

    # 7
    def test_coerce_num_basic(self):
        self.assertEqual(_coerce_num(3), 3.0)
        self.assertEqual(_coerce_num(3.14), 3.14)
        self.assertEqual(_coerce_num("5.5"), 5.5)

    # 8
    def test_coerce_num_rejects(self):
        self.assertIsNone(_coerce_num(None))
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))
        self.assertIsNone(_coerce_num("abc"))
        self.assertIsNone(_coerce_num(float("inf")))
        self.assertIsNone(_coerce_num(float("nan")))

    # 9
    def test_coerce_num_empty_string(self):
        self.assertIsNone(_coerce_num(""))
        self.assertIsNone(_coerce_num("  "))

    # 10
    def test_coerce_signed(self):
        self.assertEqual(_coerce_signed(-5.0), -5.0)
        self.assertEqual(_coerce_signed(0), 0.0)

    # 11
    def test_coerce_count(self):
        self.assertEqual(_coerce_count(5), 5)
        self.assertEqual(_coerce_count(3.7), 3)
        self.assertIsNone(_coerce_count(-1))
        self.assertIsNone(_coerce_count(None))

    # 12
    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    # 13
    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 50})
        self.assertEqual(cfg["log_cap"], 50)

    # 14
    def test_grade_from_score(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(75), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(30), "F")
        self.assertEqual(_grade_from_score(0), "F")


# ── config tests ─────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):
    # 15
    def test_chains_with_sequencer_contains_arbitrum(self):
        self.assertIn("arbitrum", CHAINS_WITH_SEQUENCER)

    # 16
    def test_chains_with_sequencer_contains_base(self):
        self.assertIn("base", CHAINS_WITH_SEQUENCER)

    # 17
    def test_chains_with_sequencer_contains_optimism(self):
        self.assertIn("optimism", CHAINS_WITH_SEQUENCER)

    # 18
    def test_chains_with_sequencer_contains_scroll(self):
        self.assertIn("scroll", CHAINS_WITH_SEQUENCER)

    # 19
    def test_chains_with_sequencer_contains_zksync(self):
        self.assertIn("zksync", CHAINS_WITH_SEQUENCER)

    # 20
    def test_chains_without_sequencer_contains_ethereum(self):
        self.assertIn("ethereum", CHAINS_WITHOUT_SEQUENCER)

    # 21
    def test_ethereum_not_in_sequencer_chains(self):
        self.assertNotIn("ethereum", CHAINS_WITH_SEQUENCER)

    # 22
    def test_annual_tip_bps_all_chains_present(self):
        for chain in CHAINS_WITH_SEQUENCER:
            self.assertIn(chain, ANNUAL_TIP_BPS_ESTIMATE)

    # 23
    def test_tx_per_year_typical(self):
        self.assertEqual(TX_PER_YEAR_TYPICAL, 730)


# ── standalone function tests ────────────────────────────────────────────────

class TestStandaloneFunctions(unittest.TestCase):
    # 24
    def test_is_sequencer_chain_arbitrum(self):
        self.assertTrue(is_sequencer_chain("arbitrum"))

    # 25
    def test_is_sequencer_chain_ethereum(self):
        self.assertFalse(is_sequencer_chain("ethereum"))

    # 26
    def test_is_sequencer_chain_case_insensitive(self):
        self.assertTrue(is_sequencer_chain("Arbitrum"))
        self.assertTrue(is_sequencer_chain("BASE"))

    # 27
    def test_is_sequencer_chain_unknown(self):
        self.assertFalse(is_sequencer_chain("solana"))

    # 28
    def test_estimate_annual_tip_bps_arbitrum(self):
        self.assertEqual(estimate_annual_tip_bps("arbitrum"), 3.0)

    # 29
    def test_estimate_annual_tip_bps_base(self):
        self.assertEqual(estimate_annual_tip_bps("base"), 2.0)

    # 30
    def test_estimate_annual_tip_bps_ethereum(self):
        self.assertEqual(estimate_annual_tip_bps("ethereum"), 0.0)

    # 31
    def test_estimate_annual_tip_bps_with_custom_tx_frequency(self):
        result = estimate_annual_tip_bps("arbitrum", tx_frequency=1460)
        self.assertAlmostEqual(result, 6.0, places=4)

    # 32
    def test_estimate_annual_tip_bps_zero_tx_frequency(self):
        result = estimate_annual_tip_bps("arbitrum", tx_frequency=0)
        self.assertEqual(result, 3.0)

    # 33
    def test_compute_tip_drag_basic(self):
        drag = compute_tip_drag(100000.0, 3.0)
        self.assertAlmostEqual(drag, 30.0, places=2)

    # 34
    def test_compute_tip_drag_zero_allocation(self):
        self.assertEqual(compute_tip_drag(0.0, 3.0), 0.0)

    # 35
    def test_compute_tip_drag_zero_bps(self):
        self.assertEqual(compute_tip_drag(100000.0, 0.0), 0.0)

    # 36
    def test_compute_tip_drag_negative_allocation(self):
        self.assertEqual(compute_tip_drag(-50000.0, 3.0), 0.0)

    # 37
    def test_apply_gap_basic(self):
        result = apply_gap(10.0, 3.0)
        self.assertAlmostEqual(result, 9.97, places=4)

    # 38
    def test_apply_gap_zero_tip(self):
        self.assertAlmostEqual(apply_gap(10.0, 0.0), 10.0, places=4)

    # 39
    def test_apply_gap_large_tip(self):
        result = apply_gap(5.0, 600.0)
        self.assertAlmostEqual(result, -1.0, places=4)


# ── ETH mainnet (no sequencer) tests ─────────────────────────────────────────

class TestNoSequencer(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 40
    def test_eth_mainnet_no_sequencer_classification(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "NO_SEQUENCER")

    # 41
    def test_eth_mainnet_score_100(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["score"], 100.0)

    # 42
    def test_eth_mainnet_grade_A(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["grade"], "A")

    # 43
    def test_eth_mainnet_no_gap(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["fee_on_tip_gap_pct"], 0.0)
        self.assertEqual(r["fee_on_tip_fraction"], 0.0)
        self.assertEqual(r["tip_drag_usd"], 0.0)

    # 44
    def test_eth_mainnet_has_sequencer_false(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertFalse(r["has_sequencer"])

    # 45
    def test_eth_mainnet_flags_contain_no_sequencer(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("NO_SEQUENCER", r["flags"])

    # 46
    def test_eth_mainnet_recommendation(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["recommendation"], "NO_ACTION_NEEDED")

    # 47
    def test_eth_mainnet_net_equals_gross(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=12.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["net_of_tip_yield_pct"], r["gross_yield_pct"])


# ── CLEAN main-path tests ────────────────────────────────────────────────────

class TestCleanMainPath(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 48
    def test_clean_classification(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=14.99,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "CLEAN_NET_OF_TIP_BASE")

    # 49
    def test_clean_flags(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=14.99,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    # 50
    def test_clean_score_high(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertGreaterEqual(r["score"], 85.0)

    # 51
    def test_clean_realization_ratio_near_1(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=2)

    # 52
    def test_clean_fee_on_tip_fraction_near_0(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["fee_on_tip_fraction"], 0.0, places=2)

    # 53
    def test_clean_recommendation(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=14.99,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    # 54
    def test_clean_has_sequencer_true(self):
        pos = make_pos(chain="arbitrum", gross_yield_pct=15.0,
                       net_of_tip_yield_pct=15.0, performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(r["has_sequencer"])


# ── MILD gap tests ───────────────────────────────────────────────────────────

class TestMildGap(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 55
    def test_mild_classification(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=8.5,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "MILD_FEE_ON_TIP_GAP")

    # 56
    def test_mild_recommendation(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=8.5,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["recommendation"], "MINOR_FEE_ON_TIP")

    # 57
    def test_mild_score_range(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=8.5,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertGreater(r["score"], 40.0)
        self.assertLess(r["score"], 100.0)

    # 58
    def test_mild_fee_on_tip_flag(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=8.5,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("FEE_ON_TIP", r["flags"])


# ── MODERATE gap tests ───────────────────────────────────────────────────────

class TestModerateGap(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 59
    def test_moderate_classification(self):
        pos = make_pos(gross_yield_pct=14.0, net_of_tip_yield_pct=7.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_TIP_GAP")

    # 60
    def test_moderate_recommendation(self):
        pos = make_pos(gross_yield_pct=14.0, net_of_tip_yield_pct=7.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["recommendation"], "DEMAND_NET_OF_TIP_BASE")

    # 61
    def test_moderate_fee_on_tip_fraction(self):
        pos = make_pos(gross_yield_pct=14.0, net_of_tip_yield_pct=7.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["fee_on_tip_fraction"], 0.5, places=2)


# ── SEVERE gap tests ─────────────────────────────────────────────────────────

class TestSevereGap(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 62
    def test_severe_classification(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_TIP_GAP")

    # 63
    def test_severe_net_negative(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(r["net_is_negative"])

    # 64
    def test_severe_net_negative_flag(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    # 65
    def test_severe_recommendation(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_TIP")

    # 66
    def test_severe_full_fee_on_tip_flag(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("FULL_FEE_ON_TIP", r["flags"])

    # 67
    def test_severe_low_score(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertLessEqual(r["score"], 30.0)


# ── INSUFFICIENT DATA tests ─────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 68
    def test_no_gross_yield(self):
        pos = make_pos(performance_fee_pct=20.0, net_of_tip_yield_pct=5.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 69
    def test_zero_gross_yield(self):
        pos = make_pos(gross_yield_pct=0.0, performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 70
    def test_negative_gross_yield(self):
        pos = make_pos(gross_yield_pct=-5.0, performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 71
    def test_nan_gross_yield(self):
        pos = make_pos(gross_yield_pct=float("nan"), performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 72
    def test_inf_gross_yield(self):
        pos = make_pos(gross_yield_pct=float("inf"), performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 73
    def test_no_performance_fee(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=9.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 74
    def test_insufficient_score_zero(self):
        pos = make_pos(performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")


# ── override path tests ──────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 75
    def test_override_used(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])

    # 76
    def test_override_fraction(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["fee_on_tip_fraction"], 0.4, places=2)

    # 77
    def test_override_classification_moderate(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_TIP_GAP")

    # 78
    def test_override_gap_from_override_flag(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    # 79
    def test_override_negative_gap_uses_magnitude(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=-3.0,
                       fee_charged_pct=10.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["fee_on_tip_fraction"], 0.3, places=2)

    # 80
    def test_override_gap_capped_at_fee_charged(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=15.0,
                       fee_charged_pct=10.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["fee_on_tip_fraction"], 1.0, places=2)

    # 81
    def test_override_geometry_none(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertIsNone(r["net_of_tip_yield_pct"])
        self.assertIsNone(r["tip_consumed_yield_pct"])


# ── tip drag / allocation tests ──────────────────────────────────────────────

class TestTipDrag(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 82
    def test_tip_drag_computed(self):
        pos = make_pos(chain="arbitrum", gross_yield_pct=10.0,
                       net_of_tip_yield_pct=9.97, performance_fee_pct=20.0,
                       allocation_usd=100000.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["tip_drag_usd"], 30.0, places=2)

    # 83
    def test_tip_drag_zero_for_eth(self):
        pos = make_pos(chain="ethereum", gross_yield_pct=10.0,
                       performance_fee_pct=20.0, allocation_usd=100000.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["tip_drag_usd"], 0.0)

    # 84
    def test_annual_tip_bps_estimate_set(self):
        pos = make_pos(chain="base", gross_yield_pct=10.0,
                       net_of_tip_yield_pct=9.98, performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertAlmostEqual(r["annual_tip_bps_estimate"], 2.0, places=2)

    # 85
    def test_tip_drag_no_allocation(self):
        pos = make_pos(chain="arbitrum", gross_yield_pct=10.0,
                       net_of_tip_yield_pct=9.97, performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertEqual(r["tip_drag_usd"], 0.0)


# ── high tip flag tests ──────────────────────────────────────────────────────

class TestHighTipFlag(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 86
    def test_high_tip_flag_present(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=9.0,
                       performance_fee_pct=20.0, tip_rate_bps=6.0)
        r = self.analyzer.analyze(pos)
        self.assertIn("HIGH_SEQUENCER_TIP", r["flags"])

    # 87
    def test_high_tip_flag_absent(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=9.0,
                       performance_fee_pct=20.0, tip_rate_bps=2.0)
        r = self.analyzer.analyze(pos)
        self.assertNotIn("HIGH_SEQUENCER_TIP", r["flags"])


# ── portfolio tests ──────────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 88
    def test_portfolio_returns_positions_and_aggregate(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_tip_yield_pct=15.0, performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=14.0,
                     net_of_tip_yield_pct=7.0, performance_fee_pct=20.0),
        ]
        r = self.analyzer.analyze_portfolio(positions)
        self.assertIn("positions", r)
        self.assertIn("aggregate", r)
        self.assertEqual(len(r["positions"]), 2)

    # 89
    def test_portfolio_aggregate_worst_vault(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=15.0,
                     net_of_tip_yield_pct=15.0, performance_fee_pct=20.0),
            make_pos(vault="Bad", gross_yield_pct=14.0,
                     net_of_tip_yield_pct=7.0, performance_fee_pct=20.0),
        ]
        r = self.analyzer.analyze_portfolio(positions)
        self.assertEqual(r["aggregate"]["worst_tip_gap_vault"], "Bad")
        self.assertEqual(r["aggregate"]["cleanest_vault"], "Clean")

    # 90
    def test_portfolio_aggregate_avg_score(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_tip_yield_pct=15.0, performance_fee_pct=20.0),
        ]
        r = self.analyzer.analyze_portfolio(positions)
        self.assertGreater(r["aggregate"]["avg_score"], 0.0)

    # 91
    def test_portfolio_all_insufficient(self):
        positions = [make_pos(vault="X", performance_fee_pct=20.0)]
        r = self.analyzer.analyze_portfolio(positions)
        self.assertIsNone(r["aggregate"]["cleanest_vault"])

    # 92
    def test_portfolio_total_tip_drag(self):
        positions = [
            make_pos(vault="A", chain="arbitrum", gross_yield_pct=10.0,
                     net_of_tip_yield_pct=9.97, performance_fee_pct=20.0,
                     allocation_usd=100000.0),
            make_pos(vault="B", chain="base", gross_yield_pct=12.0,
                     net_of_tip_yield_pct=11.98, performance_fee_pct=20.0,
                     allocation_usd=50000.0),
        ]
        r = self.analyzer.analyze_portfolio(positions)
        self.assertGreater(r["aggregate"]["total_tip_drag_usd"], 0.0)


# ── log tests ────────────────────────────────────────────────────────────────

class TestLog(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 93
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                           performance_fee_pct=20.0)
            self.analyzer.analyze(pos, cfg={"log_path": log_path, "log_cap": 10},
                                  write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertIn("ts", data[0])

    # 94
    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                           performance_fee_pct=20.0)
            for _ in range(5):
                self.analyzer.analyze(pos, cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)


# ── sentinel / finite tests ─────────────────────────────────────────────────

class TestSentinels(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 95
    def test_all_floats_finite_clean(self):
        pos = make_pos(gross_yield_pct=15.0, net_of_tip_yield_pct=15.0,
                       performance_fee_pct=20.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(_all_floats_finite(r))

    # 96
    def test_all_floats_finite_severe(self):
        pos = make_pos(gross_yield_pct=10.0, net_of_tip_yield_pct=-2.0,
                       performance_fee_pct=50.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(_all_floats_finite(r))

    # 97
    def test_all_floats_finite_override(self):
        pos = make_pos(gross_yield_pct=20.0, fee_on_tip_gap_pct=4.8,
                       fee_charged_pct=12.0)
        r = self.analyzer.analyze(pos)
        self.assertTrue(_all_floats_finite(r))


# ── demo positions test ──────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.analyzer = SequencerTipGapAnalyzer()

    # 98
    def test_demo_positions_all_valid(self):
        positions = _demo_positions()
        r = self.analyzer.analyze_portfolio(positions)
        self.assertEqual(len(r["positions"]), len(positions))
        for p in r["positions"]:
            self.assertIn(p["classification"], (
                "CLEAN_NET_OF_TIP_BASE",
                "MILD_FEE_ON_TIP_GAP",
                "MODERATE_FEE_ON_TIP_GAP",
                "SEVERE_FEE_ON_TIP_GAP",
                "NO_SEQUENCER",
                "INSUFFICIENT_DATA",
            ))
            self.assertTrue(_all_floats_finite(p))


if __name__ == "__main__":
    unittest.main()
