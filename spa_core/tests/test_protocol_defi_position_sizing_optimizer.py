"""
Tests for MP-1131: ProtocolDeFiPositionSizingOptimizer
=======================================================
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_position_sizing_optimizer
Framework: unittest (stdlib only — no pytest)
Target: ≥110 tests
"""

import json
import os
import sys
import tempfile
import unittest
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_position_sizing_optimizer import (
    ProtocolDeFiPositionSizingOptimizer,
    DEFAULT_LOG_FILE,
    LOG_CAP,
    _INF_SENTINEL,
    _LABEL_OPTIMAL,
    _LABEL_SLIGHTLY,
    _LABEL_OVERSIZED,
    _LABEL_SIGNIFICANTLY,
    _LABEL_DANGEROUS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _optimizer(log_file: Optional[str] = None) -> ProtocolDeFiPositionSizingOptimizer:
    if log_file is None:
        log_file = _tmp_log()
    return ProtocolDeFiPositionSizingOptimizer(log_file=log_file)


def _base(**overrides) -> dict:
    """Default kwargs for a typical safe DeFi strategy."""
    kw = dict(
        total_portfolio_usd=100_000.0,
        strategy_expected_apy_pct=10.0,
        strategy_win_probability=0.98,
        strategy_loss_pct_if_hack=80.0,
        max_concentration_pct=20.0,
        current_position_usd=18_000.0,
        num_similar_positions=3,
        protocol_name="TestProtocol",
    )
    kw.update(overrides)
    return kw


def _run(**overrides) -> dict:
    return _optimizer().analyze(**_base(**overrides))


# ===========================================================================
# 1 — Output structure
# ===========================================================================

class TestOutputKeys(unittest.TestCase):

    EXPECTED_KEYS = {
        "protocol_name",
        "kelly_fraction",
        "kelly_position_usd",
        "capped_kelly_pct",
        "recommended_position_usd",
        "current_vs_recommended_ratio",
        "sizing_label",
        "num_similar_positions",
        "analyzed_at",
    }

    def test_all_expected_keys_present(self):
        r = _run()
        for k in self.EXPECTED_KEYS:
            self.assertIn(k, r, f"missing key: {k}")

    def test_no_unexpected_keys(self):
        r = _run()
        for k in r:
            self.assertIn(k, self.EXPECTED_KEYS, f"unexpected key: {k}")

    def test_protocol_name_passthrough(self):
        r = _run(protocol_name="Morpho Blue")
        self.assertEqual(r["protocol_name"], "Morpho Blue")

    def test_num_similar_positions_passthrough(self):
        r = _run(num_similar_positions=5)
        self.assertEqual(r["num_similar_positions"], 5)

    def test_analyzed_at_is_string(self):
        r = _run()
        self.assertIsInstance(r["analyzed_at"], str)

    def test_analyzed_at_iso_format(self):
        r = _run()
        self.assertIn("T", r["analyzed_at"])
        self.assertTrue(r["analyzed_at"].endswith("Z"))

    def test_returns_dict(self):
        r = _run()
        self.assertIsInstance(r, dict)


# ===========================================================================
# 2 — kelly_fraction
# ===========================================================================

class TestKellyFraction(unittest.TestCase):
    """Verify the Kelly formula: (p*b - q) / b where b = apy/loss."""

    def test_basic_kelly(self):
        # b=10/80=0.125, p=0.98, q=0.02 → kelly=(0.98*0.125-0.02)/0.125=0.82
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.98,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["kelly_fraction"], 0.82, places=5)

    def test_kelly_formula_manual(self):
        apy, loss, p = 5.0, 80.0, 0.97
        b = apy / loss
        q = 1.0 - p
        expected = (p * b - q) / b
        r = _run(
            strategy_expected_apy_pct=apy,
            strategy_win_probability=p,
            strategy_loss_pct_if_hack=loss,
        )
        self.assertAlmostEqual(r["kelly_fraction"], expected, places=5)

    def test_kelly_negative_with_low_apy(self):
        # apy=1, loss=80, win_prob=0.5 → b=0.0125, kelly=(0.5*0.0125-0.5)/0.0125 < 0
        r = _run(
            strategy_expected_apy_pct=1.0,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertLess(r["kelly_fraction"], 0.0)

    def test_kelly_zero_win_prob_gives_negative(self):
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.0,
        )
        # p=0, q=1 → kelly=(0*b-1)/b=-1/b < 0
        self.assertLess(r["kelly_fraction"], 0.0)

    def test_kelly_win_prob_one(self):
        # p=1, q=0 → kelly=(b-0)/b=1.0
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=1.0,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["kelly_fraction"], 1.0, places=5)

    def test_kelly_is_float(self):
        r = _run()
        self.assertIsInstance(r["kelly_fraction"], float)

    def test_kelly_increases_with_higher_apy(self):
        r_low = _run(strategy_expected_apy_pct=3.0)
        r_high = _run(strategy_expected_apy_pct=20.0)
        self.assertLess(r_low["kelly_fraction"], r_high["kelly_fraction"])

    def test_kelly_decreases_with_higher_loss(self):
        r_low_loss = _run(strategy_loss_pct_if_hack=20.0)
        r_high_loss = _run(strategy_loss_pct_if_hack=90.0)
        # Higher loss → smaller b → smaller kelly
        self.assertGreater(r_low_loss["kelly_fraction"], r_high_loss["kelly_fraction"])

    def test_kelly_increases_with_higher_win_prob(self):
        r_low = _run(strategy_win_probability=0.90)
        r_high = _run(strategy_win_probability=0.99)
        self.assertLess(r_low["kelly_fraction"], r_high["kelly_fraction"])

    def test_kelly_high_apy_high_prob(self):
        r = _run(
            strategy_expected_apy_pct=25.0,
            strategy_win_probability=0.995,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertGreater(r["kelly_fraction"], 0.9)

    def test_kelly_fraction_precision(self):
        # Verify rounding to 6 decimal places
        r = _run()
        frac = r["kelly_fraction"]
        self.assertEqual(round(frac, 6), frac)

    def test_kelly_with_small_loss_pct(self):
        # b = apy/small_loss → very large b → kelly approaches p
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.9,
            strategy_loss_pct_if_hack=1.0,
        )
        # b=10; kelly=(0.9*10-0.1)/10=(9-0.1)/10=0.89
        self.assertAlmostEqual(r["kelly_fraction"], 0.89, places=5)


# ===========================================================================
# 3 — kelly_position_usd
# ===========================================================================

class TestKellyPositionUSD(unittest.TestCase):

    def test_basic_kelly_position(self):
        # kelly=0.82, portfolio=100k → position=82000
        r = _run(
            total_portfolio_usd=100_000.0,
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.98,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["kelly_position_usd"], 82_000.0, places=2)

    def test_kelly_position_floored_at_zero(self):
        # Negative kelly → kelly_position = 0
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["kelly_position_usd"], 0.0, places=2)

    def test_kelly_position_is_float(self):
        r = _run()
        self.assertIsInstance(r["kelly_position_usd"], float)

    def test_kelly_position_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["kelly_position_usd"], 0.0)

    def test_kelly_position_scales_with_portfolio(self):
        r1 = _run(total_portfolio_usd=100_000.0)
        r2 = _run(total_portfolio_usd=200_000.0)
        self.assertAlmostEqual(
            r2["kelly_position_usd"], r1["kelly_position_usd"] * 2, places=2
        )

    def test_kelly_position_formula(self):
        r = _run()
        expected = 100_000.0 * max(0.0, r["kelly_fraction"])
        self.assertAlmostEqual(r["kelly_position_usd"], expected, places=2)

    def test_kelly_position_at_most_portfolio_when_fraction_lte_1(self):
        r = _run(
            total_portfolio_usd=100_000.0,
            strategy_win_probability=0.98,
        )
        if r["kelly_fraction"] <= 1.0:
            self.assertLessEqual(r["kelly_position_usd"], 100_000.0)

    def test_kelly_position_zero_portfolio_no_position(self):
        # Can't test zero portfolio (validation), but small portfolio
        r = _run(total_portfolio_usd=1_000.0)
        expected = 1_000.0 * max(0.0, r["kelly_fraction"])
        self.assertAlmostEqual(r["kelly_position_usd"], expected, places=2)


# ===========================================================================
# 4 — capped_kelly_pct
# ===========================================================================

class TestCappedKellyPct(unittest.TestCase):

    def test_cap_applied_when_kelly_exceeds_max(self):
        # kelly=82% > max_conc=20% → capped=20%
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.98,
            strategy_loss_pct_if_hack=80.0,
            max_concentration_pct=20.0,
        )
        self.assertAlmostEqual(r["capped_kelly_pct"], 20.0, places=5)

    def test_no_cap_when_kelly_below_max(self):
        # kelly small, max=30% → no cap
        r = _run(
            strategy_expected_apy_pct=3.0,
            strategy_win_probability=0.97,
            strategy_loss_pct_if_hack=90.0,
            max_concentration_pct=30.0,
        )
        # kelly=(0.97*3/90-0.03)/(3/90)=...
        raw_kelly_pct = r["kelly_fraction"] * 100.0
        if raw_kelly_pct < 30.0:
            self.assertAlmostEqual(r["capped_kelly_pct"], max(0.0, raw_kelly_pct), places=4)

    def test_capped_kelly_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["capped_kelly_pct"], 0.0)

    def test_capped_kelly_never_exceeds_max_conc(self):
        for max_c in [5.0, 10.0, 20.0, 40.0]:
            r = _run(max_concentration_pct=max_c)
            self.assertLessEqual(r["capped_kelly_pct"], max_c + 1e-9)

    def test_negative_kelly_gives_zero_capped(self):
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["capped_kelly_pct"], 0.0, places=5)

    def test_capped_kelly_is_float(self):
        r = _run()
        self.assertIsInstance(r["capped_kelly_pct"], float)

    def test_capped_kelly_with_max_above_raw(self):
        # When max_conc > raw kelly → capped = raw kelly (no cap applied)
        # b=10/100=0.1; p=0.97, q=0.03; kelly=(0.97*0.1-0.03)/0.1=0.67 → 67%
        # max_conc=80% → capped=67% (no cap needed)
        r = _run(
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.97,
            strategy_loss_pct_if_hack=100.0,
            max_concentration_pct=80.0,
        )
        # raw kelly = 67%, max = 80% → capped = 67%
        self.assertAlmostEqual(r["capped_kelly_pct"], 67.0, places=3)

    def test_capped_increases_with_max_concentration(self):
        r_small = _run(max_concentration_pct=5.0)
        r_large = _run(max_concentration_pct=40.0)
        self.assertLessEqual(r_small["capped_kelly_pct"], r_large["capped_kelly_pct"])


# ===========================================================================
# 5 — recommended_position_usd
# ===========================================================================

class TestRecommendedPositionUSD(unittest.TestCase):

    def test_basic_recommended(self):
        # capped=20%, portfolio=100k → recommended=20000
        r = _run(
            total_portfolio_usd=100_000.0,
            max_concentration_pct=20.0,
            strategy_expected_apy_pct=10.0,
            strategy_win_probability=0.98,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["recommended_position_usd"], 20_000.0, places=2)

    def test_zero_capped_kelly_zero_recommended(self):
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
        )
        self.assertAlmostEqual(r["recommended_position_usd"], 0.0, places=2)

    def test_recommended_formula(self):
        r = _run()
        expected = 100_000.0 * r["capped_kelly_pct"] / 100.0
        self.assertAlmostEqual(r["recommended_position_usd"], expected, places=2)

    def test_recommended_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["recommended_position_usd"], 0.0)

    def test_recommended_is_float(self):
        r = _run()
        self.assertIsInstance(r["recommended_position_usd"], float)

    def test_recommended_never_exceeds_portfolio_times_max_conc(self):
        r = _run(total_portfolio_usd=100_000.0, max_concentration_pct=25.0)
        self.assertLessEqual(r["recommended_position_usd"], 25_000.0 + 1e-6)

    def test_recommended_scales_with_portfolio(self):
        r1 = _run(total_portfolio_usd=100_000.0)
        r2 = _run(total_portfolio_usd=500_000.0)
        self.assertAlmostEqual(
            r2["recommended_position_usd"] / r1["recommended_position_usd"],
            5.0, places=2
        )

    def test_recommended_matches_manual_calculation(self):
        portfolio = 250_000.0
        max_conc = 15.0
        r = _run(total_portfolio_usd=portfolio, max_concentration_pct=max_conc)
        expected = portfolio * r["capped_kelly_pct"] / 100.0
        self.assertAlmostEqual(r["recommended_position_usd"], expected, places=2)


# ===========================================================================
# 6 — current_vs_recommended_ratio
# ===========================================================================

class TestCurrentVsRecommendedRatio(unittest.TestCase):

    def test_basic_ratio(self):
        # current=18000, recommended=20000 → ratio=0.9
        r = _run(current_position_usd=18_000.0)
        # recommended = 100k * 20% = 20000
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], 0.9, places=4)

    def test_ratio_zero_when_both_zero(self):
        # kelly neg → recommended=0, current=0 → ratio=0
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
            current_position_usd=0.0,
        )
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], 0.0, places=5)

    def test_ratio_sentinel_when_current_nonzero_recommended_zero(self):
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
            current_position_usd=10_000.0,
        )
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], _INF_SENTINEL, places=5)

    def test_ratio_formula(self):
        r = _run(current_position_usd=15_000.0)
        if r["recommended_position_usd"] > 0:
            expected = 15_000.0 / r["recommended_position_usd"]
            self.assertAlmostEqual(r["current_vs_recommended_ratio"], expected, places=4)

    def test_ratio_is_float(self):
        r = _run()
        self.assertIsInstance(r["current_vs_recommended_ratio"], float)

    def test_ratio_one_when_current_equals_recommended(self):
        # Need current = recommended exactly
        r_base = _run(current_position_usd=0.0)
        rec = r_base["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec)
            self.assertAlmostEqual(r["current_vs_recommended_ratio"], 1.0, places=4)

    def test_ratio_increases_with_current_position(self):
        r_low = _run(current_position_usd=5_000.0)
        r_high = _run(current_position_usd=50_000.0)
        self.assertLess(
            r_low["current_vs_recommended_ratio"],
            r_high["current_vs_recommended_ratio"],
        )

    def test_ratio_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["current_vs_recommended_ratio"], 0.0)


# ===========================================================================
# 7 — Label: OPTIMAL_SIZE (ratio <= 1.1)
# ===========================================================================

class TestOptimalSizeLabel(unittest.TestCase):

    def test_ratio_below_1_is_optimal(self):
        r = _run(current_position_usd=10_000.0)
        # recommended=20000, ratio=0.5 → OPTIMAL
        self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_ratio_exactly_1_is_optimal(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec)
            self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_ratio_at_1_1_is_optimal(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.1)
            self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_zero_current_is_optimal(self):
        r = _run(current_position_usd=0.0)
        if r["recommended_position_usd"] > 0:
            self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_optimal_label_value(self):
        self.assertEqual(_LABEL_OPTIMAL, "OPTIMAL_SIZE")

    def test_label_is_string(self):
        r = _run()
        self.assertIsInstance(r["sizing_label"], str)

    def test_zero_both_optimal(self):
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
            current_position_usd=0.0,
        )
        self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_ratio_0_9_is_optimal(self):
        r = _run(current_position_usd=18_000.0)
        # recommended=20k, current=18k → ratio=0.9 → OPTIMAL
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], 0.9, places=3)
        self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)


# ===========================================================================
# 8 — Label: SLIGHTLY_OVERSIZED (1.1 < ratio <= 1.5)
# ===========================================================================

class TestSlightlyOversizedLabel(unittest.TestCase):

    def _slightly(self, ratio_target: float = 1.3) -> dict:
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            return _run(current_position_usd=rec * ratio_target)
        return _run(current_position_usd=0.0)

    def test_ratio_1_2_is_slightly(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.2)
            self.assertEqual(r["sizing_label"], _LABEL_SLIGHTLY)

    def test_ratio_1_3_is_slightly(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.3)
            self.assertEqual(r["sizing_label"], _LABEL_SLIGHTLY)

    def test_ratio_1_5_is_slightly(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.5)
            self.assertEqual(r["sizing_label"], _LABEL_SLIGHTLY)

    def test_slightly_label_value(self):
        self.assertEqual(_LABEL_SLIGHTLY, "SLIGHTLY_OVERSIZED")

    def test_ratio_just_above_1_1_is_slightly(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.11)
            self.assertEqual(r["sizing_label"], _LABEL_SLIGHTLY)

    def test_classify_helper_1_2(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.2)
        self.assertEqual(label, _LABEL_SLIGHTLY)

    def test_classify_helper_1_5(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.5)
        self.assertEqual(label, _LABEL_SLIGHTLY)

    def test_classify_helper_1_4(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.4)
        self.assertEqual(label, _LABEL_SLIGHTLY)


# ===========================================================================
# 9 — Label: OVERSIZED (1.5 < ratio <= 2.0)
# ===========================================================================

class TestOversizedLabel(unittest.TestCase):

    def test_ratio_1_6_is_oversized(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.6)
        self.assertEqual(label, _LABEL_OVERSIZED)

    def test_ratio_2_0_is_oversized(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(2.0)
        self.assertEqual(label, _LABEL_OVERSIZED)

    def test_ratio_1_8_is_oversized(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.8)
        self.assertEqual(label, _LABEL_OVERSIZED)

    def test_ratio_1_51_is_oversized(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.51)
        self.assertEqual(label, _LABEL_OVERSIZED)

    def test_oversized_label_value(self):
        self.assertEqual(_LABEL_OVERSIZED, "OVERSIZED")

    def test_via_analyze_oversized(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 1.8)
            self.assertEqual(r["sizing_label"], _LABEL_OVERSIZED)

    def test_ratio_1_99_is_oversized(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(1.99)
        self.assertEqual(label, _LABEL_OVERSIZED)

    def test_ratio_not_oversized_at_2_01(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(2.01)
        self.assertNotEqual(label, _LABEL_OVERSIZED)


# ===========================================================================
# 10 — Label: SIGNIFICANTLY_OVERSIZED (2.0 < ratio <= 3.0)
# ===========================================================================

class TestSignificantlyOversizedLabel(unittest.TestCase):

    def test_ratio_2_5_is_significantly(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(2.5)
        self.assertEqual(label, _LABEL_SIGNIFICANTLY)

    def test_ratio_3_0_is_significantly(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(3.0)
        self.assertEqual(label, _LABEL_SIGNIFICANTLY)

    def test_ratio_2_01_is_significantly(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(2.01)
        self.assertEqual(label, _LABEL_SIGNIFICANTLY)

    def test_significantly_label_value(self):
        self.assertEqual(_LABEL_SIGNIFICANTLY, "SIGNIFICANTLY_OVERSIZED")

    def test_via_analyze_significantly(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 2.5)
            self.assertEqual(r["sizing_label"], _LABEL_SIGNIFICANTLY)

    def test_via_analyze_ratio_50k_on_20k(self):
        r = _run(current_position_usd=50_000.0)
        # recommended=20000, ratio=2.5 → SIGNIFICANTLY
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], 2.5, places=4)
        self.assertEqual(r["sizing_label"], _LABEL_SIGNIFICANTLY)


# ===========================================================================
# 11 — Label: DANGEROUSLY_OVERSIZED (ratio > 3.0)
# ===========================================================================

class TestDangerouslyOversizedLabel(unittest.TestCase):

    def test_ratio_4_is_dangerous(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(4.0)
        self.assertEqual(label, _LABEL_DANGEROUS)

    def test_ratio_10_is_dangerous(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(10.0)
        self.assertEqual(label, _LABEL_DANGEROUS)

    def test_ratio_3_01_is_dangerous(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(3.01)
        self.assertEqual(label, _LABEL_DANGEROUS)

    def test_sentinel_is_dangerous(self):
        label = ProtocolDeFiPositionSizingOptimizer._classify(_INF_SENTINEL)
        self.assertEqual(label, _LABEL_DANGEROUS)

    def test_dangerous_label_value(self):
        self.assertEqual(_LABEL_DANGEROUS, "DANGEROUSLY_OVERSIZED")

    def test_via_analyze_dangerous(self):
        # Invest in bad protocol (negative kelly) → sentinel ratio → DANGEROUS
        r = _run(
            strategy_expected_apy_pct=0.5,
            strategy_win_probability=0.5,
            strategy_loss_pct_if_hack=80.0,
            current_position_usd=10_000.0,
        )
        self.assertEqual(r["sizing_label"], _LABEL_DANGEROUS)

    def test_large_current_position_dangerous(self):
        r_check = _run(current_position_usd=0.0)
        rec = r_check["recommended_position_usd"]
        if rec > 0:
            r = _run(current_position_usd=rec * 5.0)
            self.assertEqual(r["sizing_label"], _LABEL_DANGEROUS)


# ===========================================================================
# 12 — Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_win_prob_exactly_half(self):
        r = _run(strategy_win_probability=0.5)
        # Kelly can be negative
        self.assertIsNotNone(r)

    def test_very_small_apy(self):
        r = _run(strategy_expected_apy_pct=0.01)
        self.assertIsNotNone(r)
        self.assertLessEqual(r["recommended_position_usd"], 100_000.0)

    def test_very_large_portfolio(self):
        r = _run(total_portfolio_usd=100_000_000.0)
        self.assertIsNotNone(r)
        self.assertGreaterEqual(r["recommended_position_usd"], 0.0)

    def test_max_concentration_1pct(self):
        r = _run(max_concentration_pct=1.0)
        self.assertLessEqual(r["capped_kelly_pct"], 1.0 + 1e-9)
        self.assertLessEqual(r["recommended_position_usd"], 1_000.0 + 1.0)

    def test_max_concentration_100pct(self):
        r = _run(max_concentration_pct=100.0)
        self.assertLessEqual(r["capped_kelly_pct"], 100.0 + 1e-9)

    def test_current_zero_with_positive_recommended(self):
        r = _run(current_position_usd=0.0)
        self.assertAlmostEqual(r["current_vs_recommended_ratio"], 0.0, places=5)
        self.assertEqual(r["sizing_label"], _LABEL_OPTIMAL)

    def test_num_similar_positions_zero(self):
        r = _run(num_similar_positions=0)
        self.assertEqual(r["num_similar_positions"], 0)

    def test_all_labels_are_distinct(self):
        labels = {
            _LABEL_OPTIMAL, _LABEL_SLIGHTLY, _LABEL_OVERSIZED,
            _LABEL_SIGNIFICANTLY, _LABEL_DANGEROUS
        }
        self.assertEqual(len(labels), 5)

    def test_inf_sentinel_positive(self):
        self.assertGreater(_INF_SENTINEL, 3.0)

    def test_large_current_position_small_recommended(self):
        r = _run(
            current_position_usd=80_000.0,
            max_concentration_pct=5.0,
        )
        # recommended=5000, ratio=16 → DANGEROUS
        self.assertEqual(r["sizing_label"], _LABEL_DANGEROUS)


# ===========================================================================
# 13 — Validation
# ===========================================================================

class TestValidation(unittest.TestCase):

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_name="")

    def test_whitespace_name_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_name="  ")

    def test_negative_portfolio_raises(self):
        with self.assertRaises(ValueError):
            _run(total_portfolio_usd=-1.0)

    def test_zero_portfolio_raises(self):
        with self.assertRaises(ValueError):
            _run(total_portfolio_usd=0.0)

    def test_negative_apy_raises(self):
        with self.assertRaises(ValueError):
            _run(strategy_expected_apy_pct=-1.0)

    def test_win_prob_above_1_raises(self):
        with self.assertRaises(ValueError):
            _run(strategy_win_probability=1.01)

    def test_win_prob_below_0_raises(self):
        with self.assertRaises(ValueError):
            _run(strategy_win_probability=-0.01)

    def test_zero_loss_pct_raises(self):
        with self.assertRaises(ValueError):
            _run(strategy_loss_pct_if_hack=0.0)

    def test_negative_loss_pct_raises(self):
        with self.assertRaises(ValueError):
            _run(strategy_loss_pct_if_hack=-1.0)

    def test_zero_max_concentration_raises(self):
        with self.assertRaises(ValueError):
            _run(max_concentration_pct=0.0)

    def test_max_concentration_above_100_raises(self):
        with self.assertRaises(ValueError):
            _run(max_concentration_pct=101.0)

    def test_negative_current_position_raises(self):
        with self.assertRaises(ValueError):
            _run(current_position_usd=-1.0)

    def test_negative_num_positions_raises(self):
        with self.assertRaises(ValueError):
            _run(num_similar_positions=-1)

    def test_win_prob_exactly_0_valid(self):
        r = _run(strategy_win_probability=0.0)
        self.assertLess(r["kelly_fraction"], 0.0)

    def test_win_prob_exactly_1_valid(self):
        r = _run(strategy_win_probability=1.0)
        self.assertAlmostEqual(r["kelly_fraction"], 1.0, places=5)

    def test_max_concentration_exactly_100_valid(self):
        r = _run(max_concentration_pct=100.0)
        self.assertIsNotNone(r)

    def test_zero_current_position_valid(self):
        r = _run(current_position_usd=0.0)
        self.assertGreaterEqual(r["current_vs_recommended_ratio"], 0.0)

    def test_zero_apy_valid(self):
        # b=apy/loss=0 → kelly=-q (guarded, no ZeroDivisionError)
        r = _run(strategy_expected_apy_pct=0.0)
        self.assertIsNotNone(r)
        # kelly should be negative (no yield = no edge)
        self.assertLess(r["kelly_fraction"], 0.0)
        # recommended should be zero (no investment sensible)
        self.assertAlmostEqual(r["recommended_position_usd"], 0.0, places=4)

    def test_num_positions_zero_valid(self):
        r = _run(num_similar_positions=0)
        self.assertIsNotNone(r)


# ===========================================================================
# 14 — Log file (ring-buffer, atomic write)
# ===========================================================================

class TestLogFile(unittest.TestCase):

    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.log_path)
        self.o = ProtocolDeFiPositionSizingOptimizer(log_file=self.log_path, log_cap=5)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def _call(self, name: str = "P") -> dict:
        return self.o.analyze(**_base(protocol_name=name))

    def test_log_created_on_first_call(self):
        self._call()
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_one_entry_after_one_call(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_two_entries_after_two_calls(self):
        self._call("A")
        self._call("B")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_caps_at_log_cap(self):
        for i in range(10):
            self._call(f"P{i}")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_keeps_latest(self):
        for i in range(7):
            self._call(f"P{i}")
        with open(self.log_path) as f:
            data = json.load(f)
        names = [e["protocol_name"] for e in data]
        self.assertIn("P6", names)
        self.assertNotIn("P0", names)

    def test_entry_has_required_fields(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        entry = data[0]
        self.assertIn("protocol_name", entry)
        self.assertIn("kelly_fraction", entry)
        self.assertIn("sizing_label", entry)

    def test_load_log_returns_list(self):
        self._call()
        log = self.o.load_log()
        self.assertIsInstance(log, list)

    def test_load_log_empty_when_no_file(self):
        log = self.o.load_log()
        self.assertEqual(log, [])

    def test_load_log_matches_written(self):
        self._call("MyProto")
        log = self.o.load_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["protocol_name"], "MyProto")

    def test_log_cap_default(self):
        self.assertEqual(LOG_CAP, 100)

    def test_default_log_path_in_data_dir(self):
        self.assertIn("data", DEFAULT_LOG_FILE)
        self.assertIn("position_sizing_log", DEFAULT_LOG_FILE)

    def test_corrupted_log_starts_fresh(self):
        with open(self.log_path, "w") as f:
            f.write("{{not_json")
        self._call("Recovery")
        log = self.o.load_log()
        self.assertEqual(len(log), 1)

    def test_log_sizing_label_valid(self):
        self._call()
        log = self.o.load_log()
        valid = {_LABEL_OPTIMAL, _LABEL_SLIGHTLY, _LABEL_OVERSIZED,
                 _LABEL_SIGNIFICANTLY, _LABEL_DANGEROUS}
        self.assertIn(log[0]["sizing_label"], valid)

    def test_multiple_optimizers_same_log(self):
        o2 = ProtocolDeFiPositionSizingOptimizer(log_file=self.log_path, log_cap=5)
        self._call("A")
        o2.analyze(**_base(protocol_name="B"))
        log = self.o.load_log()
        self.assertEqual(len(log), 2)


# ===========================================================================
# 15 — Classify helper (unit tests)
# ===========================================================================

class TestClassifyHelper(unittest.TestCase):

    def _cls(self, ratio: float) -> str:
        return ProtocolDeFiPositionSizingOptimizer._classify(ratio)

    def test_zero_is_optimal(self):
        self.assertEqual(self._cls(0.0), _LABEL_OPTIMAL)

    def test_1_0_is_optimal(self):
        self.assertEqual(self._cls(1.0), _LABEL_OPTIMAL)

    def test_1_1_is_optimal(self):
        self.assertEqual(self._cls(1.1), _LABEL_OPTIMAL)

    def test_1_101_is_slightly(self):
        self.assertEqual(self._cls(1.101), _LABEL_SLIGHTLY)

    def test_1_5_is_slightly(self):
        self.assertEqual(self._cls(1.5), _LABEL_SLIGHTLY)

    def test_1_501_is_oversized(self):
        self.assertEqual(self._cls(1.501), _LABEL_OVERSIZED)

    def test_2_0_is_oversized(self):
        self.assertEqual(self._cls(2.0), _LABEL_OVERSIZED)

    def test_2_001_is_significantly(self):
        self.assertEqual(self._cls(2.001), _LABEL_SIGNIFICANTLY)

    def test_3_0_is_significantly(self):
        self.assertEqual(self._cls(3.0), _LABEL_SIGNIFICANTLY)

    def test_3_001_is_dangerous(self):
        self.assertEqual(self._cls(3.001), _LABEL_DANGEROUS)

    def test_100_is_dangerous(self):
        self.assertEqual(self._cls(100.0), _LABEL_DANGEROUS)

    def test_9999_is_dangerous(self):
        self.assertEqual(self._cls(9999.0), _LABEL_DANGEROUS)

    def test_boundary_1_1_inclusive_optimal(self):
        self.assertEqual(self._cls(1.1), _LABEL_OPTIMAL)

    def test_boundary_1_5_inclusive_slightly(self):
        self.assertEqual(self._cls(1.5), _LABEL_SLIGHTLY)

    def test_boundary_2_0_inclusive_oversized(self):
        self.assertEqual(self._cls(2.0), _LABEL_OVERSIZED)

    def test_boundary_3_0_inclusive_significantly(self):
        self.assertEqual(self._cls(3.0), _LABEL_SIGNIFICANTLY)


# ===========================================================================
# 16 — Compute ratio helper
# ===========================================================================

class TestComputeRatioHelper(unittest.TestCase):

    def _ratio(self, current: float, recommended: float) -> float:
        return ProtocolDeFiPositionSizingOptimizer._compute_ratio(current, recommended)

    def test_basic_ratio(self):
        self.assertAlmostEqual(self._ratio(18_000.0, 20_000.0), 0.9, places=5)

    def test_equal_gives_one(self):
        self.assertAlmostEqual(self._ratio(10_000.0, 10_000.0), 1.0, places=5)

    def test_both_zero_gives_zero(self):
        self.assertAlmostEqual(self._ratio(0.0, 0.0), 0.0, places=5)

    def test_current_nonzero_recommended_zero_gives_sentinel(self):
        self.assertAlmostEqual(self._ratio(1_000.0, 0.0), _INF_SENTINEL, places=5)

    def test_current_zero_recommended_positive_gives_zero(self):
        self.assertAlmostEqual(self._ratio(0.0, 20_000.0), 0.0, places=5)

    def test_ratio_2x(self):
        self.assertAlmostEqual(self._ratio(40_000.0, 20_000.0), 2.0, places=5)

    def test_ratio_half(self):
        self.assertAlmostEqual(self._ratio(10_000.0, 20_000.0), 0.5, places=5)

    def test_ratio_3x(self):
        self.assertAlmostEqual(self._ratio(60_000.0, 20_000.0), 3.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
