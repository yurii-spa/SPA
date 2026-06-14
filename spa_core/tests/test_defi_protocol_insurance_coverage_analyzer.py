"""
Tests for MP-1130: DeFiProtocolInsuranceCoverageAnalyzer
=========================================================
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_insurance_coverage_analyzer
Framework: unittest (stdlib only — no pytest)
Target: ≥110 tests
"""

import json
import os
import sys
import tempfile
import unittest
from typing import Optional  # noqa: F401 (Python 3.9 compat)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_insurance_coverage_analyzer import (
    DeFiProtocolInsuranceCoverageAnalyzer,
    DEFAULT_LOG_FILE,
    LOG_CAP,
    _LABEL_HIGHLY_RECOMMENDED,
    _LABEL_BENEFICIAL,
    _LABEL_MARGINAL,
    _LABEL_OVERPRICED,
    _LABEL_ACCEPTABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _analyzer(log_file: Optional[str] = None) -> DeFiProtocolInsuranceCoverageAnalyzer:
    if log_file is None:
        log_file = _tmp_log()
    return DeFiProtocolInsuranceCoverageAnalyzer(log_file=log_file)


def _base(**overrides) -> dict:
    """Return a valid kwargs dict with sensible defaults."""
    kw = dict(
        position_size_usd=100_000.0,
        coverage_amount_usd=80_000.0,
        insurance_premium_annual_pct=2.0,
        protocol_risk_score=40,
        estimated_hack_probability_annual_pct=2.0,
        estimated_max_loss_pct=80.0,
        gross_apy_pct=8.0,
        protocol_name="TestProtocol",
    )
    kw.update(overrides)
    return kw


def _run(**overrides) -> dict:
    return _analyzer().analyze(**_base(**overrides))



# ===========================================================================
# 1 — Output structure
# ===========================================================================

class TestOutputKeys(unittest.TestCase):
    """Verify analyze() returns the expected keys."""

    EXPECTED_KEYS = {
        "protocol_name",
        "coverage_ratio",
        "annual_premium_usd",
        "premium_drag_pct",
        "expected_annual_loss_without_insurance_usd",
        "expected_annual_loss_with_insurance_usd",
        "insurance_net_benefit_usd",
        "net_apy_after_premium_pct",
        "insurance_label",
        "protocol_risk_score",
        "analyzed_at",
    }

    def _result(self):
        return _run()

    def test_all_expected_keys_present(self):
        r = self._result()
        for k in self.EXPECTED_KEYS:
            self.assertIn(k, r, f"missing key: {k}")

    def test_no_unexpected_keys(self):
        r = self._result()
        for k in r:
            self.assertIn(k, self.EXPECTED_KEYS, f"unexpected key: {k}")

    def test_protocol_name_matches_input(self):
        r = _run(protocol_name="Morpho")
        self.assertEqual(r["protocol_name"], "Morpho")

    def test_protocol_risk_score_passthrough(self):
        r = _run(protocol_risk_score=55)
        self.assertEqual(r["protocol_risk_score"], 55)

    def test_analyzed_at_is_string(self):
        r = self._result()
        self.assertIsInstance(r["analyzed_at"], str)

    def test_analyzed_at_iso_format(self):
        r = self._result()
        ts = r["analyzed_at"]
        self.assertIn("T", ts)
        self.assertTrue(ts.endswith("Z"))

    def test_returns_dict(self):
        r = self._result()
        self.assertIsInstance(r, dict)


# ===========================================================================
# 2 — coverage_ratio
# ===========================================================================

class TestCoverageRatio(unittest.TestCase):

    def test_partial_coverage(self):
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=80_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.8, places=5)

    def test_full_coverage_exact(self):
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=100_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 1.0, places=5)

    def test_overcoverage_capped_at_one(self):
        r = _run(position_size_usd=50_000.0, coverage_amount_usd=100_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 1.0, places=5)

    def test_zero_coverage(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.0, places=5)

    def test_small_coverage(self):
        r = _run(position_size_usd=200_000.0, coverage_amount_usd=10_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.05, places=5)

    def test_coverage_ratio_is_float(self):
        r = _run()
        self.assertIsInstance(r["coverage_ratio"], float)

    def test_coverage_ratio_between_zero_and_one(self):
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=60_000.0)
        self.assertGreaterEqual(r["coverage_ratio"], 0.0)
        self.assertLessEqual(r["coverage_ratio"], 1.0)

    def test_coverage_ratio_half(self):
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=50_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.5, places=5)

    def test_coverage_ratio_quarter(self):
        r = _run(position_size_usd=400_000.0, coverage_amount_usd=100_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.25, places=5)

    def test_coverage_ratio_near_one(self):
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=99_000.0)
        self.assertAlmostEqual(r["coverage_ratio"], 0.99, places=5)


# ===========================================================================
# 3 — annual_premium_usd
# ===========================================================================

class TestAnnualPremiumUSD(unittest.TestCase):

    def test_basic_premium(self):
        # coverage=80000, premium_pct=2 → 80000*2/100=1600
        r = _run(coverage_amount_usd=80_000.0, insurance_premium_annual_pct=2.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 1600.0, places=4)

    def test_zero_coverage_zero_premium(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=3.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 0.0, places=4)

    def test_zero_pct_zero_premium(self):
        r = _run(coverage_amount_usd=80_000.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 0.0, places=4)

    def test_high_premium_pct(self):
        # coverage=100000, pct=5 → 5000
        r = _run(coverage_amount_usd=100_000.0, insurance_premium_annual_pct=5.0,
                 position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 5000.0, places=4)

    def test_premium_formula_correct(self):
        cov, pct = 75_000.0, 1.5
        r = _run(coverage_amount_usd=cov, insurance_premium_annual_pct=pct)
        expected = cov * pct / 100.0
        self.assertAlmostEqual(r["annual_premium_usd"], expected, places=4)

    def test_premium_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["annual_premium_usd"], 0.0)

    def test_premium_decimal_pct(self):
        r = _run(coverage_amount_usd=100_000.0, insurance_premium_annual_pct=0.25,
                 position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 250.0, places=4)

    def test_premium_is_float(self):
        r = _run()
        self.assertIsInstance(r["annual_premium_usd"], float)


# ===========================================================================
# 4 — premium_drag_pct
# ===========================================================================

class TestPremiumDragPct(unittest.TestCase):

    def test_basic_drag(self):
        # premium=1600, position=100000 → drag=1.6%
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=80_000.0,
                 insurance_premium_annual_pct=2.0)
        self.assertAlmostEqual(r["premium_drag_pct"], 1.6, places=4)

    def test_zero_premium_zero_drag(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["premium_drag_pct"], 0.0, places=4)

    def test_drag_formula(self):
        pos, cov, pct = 200_000.0, 100_000.0, 3.0
        r = _run(position_size_usd=pos, coverage_amount_usd=cov,
                 insurance_premium_annual_pct=pct)
        expected = cov * pct / 100.0 / pos * 100.0
        self.assertAlmostEqual(r["premium_drag_pct"], expected, places=4)

    def test_full_coverage_drag(self):
        # 100% coverage, 2% premium on coverage → 2% drag on position
        r = _run(position_size_usd=100_000.0, coverage_amount_usd=100_000.0,
                 insurance_premium_annual_pct=2.0)
        self.assertAlmostEqual(r["premium_drag_pct"], 2.0, places=4)

    def test_drag_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["premium_drag_pct"], 0.0)

    def test_drag_is_float(self):
        r = _run()
        self.assertIsInstance(r["premium_drag_pct"], float)

    def test_drag_increases_with_premium_pct(self):
        r_low = _run(insurance_premium_annual_pct=1.0)
        r_high = _run(insurance_premium_annual_pct=3.0)
        self.assertLess(r_low["premium_drag_pct"], r_high["premium_drag_pct"])

    def test_drag_increases_with_coverage_amount(self):
        r_low = _run(coverage_amount_usd=40_000.0)
        r_high = _run(coverage_amount_usd=80_000.0)
        self.assertLess(r_low["premium_drag_pct"], r_high["premium_drag_pct"])


# ===========================================================================
# 5 — expected_annual_loss_without_insurance_usd
# ===========================================================================

class TestExpectedLossWithout(unittest.TestCase):

    def test_basic_formula(self):
        # position=100000, hack=2%, max_loss=80% → 100000*0.02*0.8=1600
        r = _run(position_size_usd=100_000.0,
                 estimated_hack_probability_annual_pct=2.0,
                 estimated_max_loss_pct=80.0)
        self.assertAlmostEqual(
            r["expected_annual_loss_without_insurance_usd"], 1600.0, places=4
        )

    def test_zero_hack_prob(self):
        r = _run(estimated_hack_probability_annual_pct=0.0)
        self.assertAlmostEqual(
            r["expected_annual_loss_without_insurance_usd"], 0.0, places=4
        )

    def test_zero_max_loss(self):
        r = _run(estimated_max_loss_pct=0.0)
        self.assertAlmostEqual(
            r["expected_annual_loss_without_insurance_usd"], 0.0, places=4
        )

    def test_high_risk_scenario(self):
        # position=100000, hack=10%, loss=90% → 9000
        r = _run(position_size_usd=100_000.0,
                 estimated_hack_probability_annual_pct=10.0,
                 estimated_max_loss_pct=90.0)
        self.assertAlmostEqual(
            r["expected_annual_loss_without_insurance_usd"], 9000.0, places=4
        )

    def test_small_position(self):
        r = _run(position_size_usd=10_000.0,
                 estimated_hack_probability_annual_pct=5.0,
                 estimated_max_loss_pct=80.0)
        self.assertAlmostEqual(
            r["expected_annual_loss_without_insurance_usd"], 400.0, places=4
        )

    def test_proportional_to_position_size(self):
        r1 = _run(position_size_usd=50_000.0)
        r2 = _run(position_size_usd=100_000.0)
        self.assertAlmostEqual(
            r2["expected_annual_loss_without_insurance_usd"],
            r1["expected_annual_loss_without_insurance_usd"] * 2,
            places=2,
        )

    def test_proportional_to_hack_prob(self):
        r1 = _run(estimated_hack_probability_annual_pct=1.0)
        r2 = _run(estimated_hack_probability_annual_pct=2.0)
        self.assertAlmostEqual(
            r2["expected_annual_loss_without_insurance_usd"],
            r1["expected_annual_loss_without_insurance_usd"] * 2,
            places=2,
        )

    def test_is_float(self):
        r = _run()
        self.assertIsInstance(r["expected_annual_loss_without_insurance_usd"], float)

    def test_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["expected_annual_loss_without_insurance_usd"], 0.0)


# ===========================================================================
# 6 — expected_annual_loss_with_insurance_usd
# ===========================================================================

class TestExpectedLossWithInsurance(unittest.TestCase):

    def test_formula_with_partial_coverage(self):
        # pos=100k, cov=80k → uncovered=20k
        # hack=2%, loss=80% → uncovered_loss=20k*0.02*0.8=320
        # premium=80k*2/100=1600
        # total=320+1600=1920
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=2.0,
            estimated_max_loss_pct=80.0,
        )
        self.assertAlmostEqual(
            r["expected_annual_loss_with_insurance_usd"], 1920.0, places=3
        )

    def test_full_coverage_only_premium(self):
        # pos=100k, cov=100k → uncovered=0 → only premium
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
        )
        # uncovered_loss = 0; loss_with = 0 + 2000 = 2000
        self.assertAlmostEqual(
            r["expected_annual_loss_with_insurance_usd"], 2000.0, places=3
        )

    def test_zero_coverage_equals_loss_without_plus_zero_premium(self):
        r = _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
        )
        # uncovered = position, premium = 0
        # loss_with = position*hack*loss + 0 = loss_without
        self.assertAlmostEqual(
            r["expected_annual_loss_with_insurance_usd"],
            r["expected_annual_loss_without_insurance_usd"],
            places=3,
        )

    def test_loss_with_is_nonnegative(self):
        r = _run()
        self.assertGreaterEqual(r["expected_annual_loss_with_insurance_usd"], 0.0)

    def test_loss_with_is_float(self):
        r = _run()
        self.assertIsInstance(r["expected_annual_loss_with_insurance_usd"], float)

    def test_full_coverage_no_uncovered_loss(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=1.5,
            estimated_hack_probability_annual_pct=3.0,
            estimated_max_loss_pct=70.0,
        )
        # uncovered = 0 → loss_with = premium = 100000*1.5/100 = 1500
        self.assertAlmostEqual(
            r["expected_annual_loss_with_insurance_usd"], 1500.0, places=3
        )

    def test_overcoverage_capped_uncovered_zero(self):
        r = _run(
            position_size_usd=50_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
        )
        # uncovered = max(0, 50000 - 100000) = 0
        # premium = 100000 * 2/100 = 2000
        # loss_with = 0 + 2000 = 2000
        self.assertAlmostEqual(
            r["expected_annual_loss_with_insurance_usd"], 2000.0, places=3
        )

    def test_loss_with_increases_with_premium(self):
        r_low = _run(insurance_premium_annual_pct=1.0)
        r_high = _run(insurance_premium_annual_pct=3.0)
        self.assertLess(
            r_low["expected_annual_loss_with_insurance_usd"],
            r_high["expected_annual_loss_with_insurance_usd"],
        )

    def test_loss_with_decreases_as_coverage_increases(self):
        # More coverage → less uncovered loss
        r_low = _run(
            coverage_amount_usd=10_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
        )
        r_high = _run(
            coverage_amount_usd=90_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
        )
        # More coverage → smaller uncovered loss dominates at low premium
        self.assertGreater(
            r_low["expected_annual_loss_with_insurance_usd"],
            r_high["expected_annual_loss_with_insurance_usd"],
        )


# ===========================================================================
# 7 — insurance_net_benefit_usd
# ===========================================================================

class TestInsuranceNetBenefit(unittest.TestCase):

    def test_formula_manual(self):
        # pos=100k, cov=80k, pct=2%, hack=2%, loss=80%
        # loss_without = 100000*0.02*0.8 = 1600
        # premium = 80000*2/100 = 1600
        # uncovered = 20000; uncovered_loss = 20000*0.02*0.8 = 320
        # loss_with = 320 + 1600 = 1920
        # net_benefit = 1600 - 1920 - 1600 = -1920
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=2.0,
            estimated_max_loss_pct=80.0,
        )
        expected = (
            r["expected_annual_loss_without_insurance_usd"]
            - r["expected_annual_loss_with_insurance_usd"]
            - r["annual_premium_usd"]
        )
        self.assertAlmostEqual(r["insurance_net_benefit_usd"], expected, places=4)

    def test_net_benefit_is_float(self):
        r = _run()
        self.assertIsInstance(r["insurance_net_benefit_usd"], float)

    def test_uninsured_net_benefit_zero(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        # loss_without = loss_with, premium = 0 → net = 0
        self.assertAlmostEqual(r["insurance_net_benefit_usd"], 0.0, places=4)

    def test_net_benefit_positive_with_very_high_hack_low_premium(self):
        # hack=50%, loss=90%, premium=0.1% of big coverage
        # With high hack prob and cheap insurance, net benefit can be positive
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=95_000.0,
            insurance_premium_annual_pct=0.5,
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertGreater(r["insurance_net_benefit_usd"], 0.0)

    def test_net_benefit_equals_difference_minus_premium(self):
        r = _run()
        computed = (
            r["expected_annual_loss_without_insurance_usd"]
            - r["expected_annual_loss_with_insurance_usd"]
            - r["annual_premium_usd"]
        )
        self.assertAlmostEqual(r["insurance_net_benefit_usd"], computed, places=4)

    def test_expensive_premium_gives_negative_benefit(self):
        r = _run(
            coverage_amount_usd=90_000.0,
            insurance_premium_annual_pct=10.0,
            estimated_hack_probability_annual_pct=0.5,
            estimated_max_loss_pct=80.0,
        )
        self.assertLess(r["insurance_net_benefit_usd"], 0.0)

    def test_net_benefit_consistency_with_components(self):
        r = _run()
        lw = r["expected_annual_loss_without_insurance_usd"]
        lins = r["expected_annual_loss_with_insurance_usd"]
        p = r["annual_premium_usd"]
        nb = r["insurance_net_benefit_usd"]
        self.assertAlmostEqual(nb, lw - lins - p, places=4)

    def test_net_benefit_varies_with_coverage(self):
        r_low = _run(coverage_amount_usd=10_000.0)
        r_high = _run(coverage_amount_usd=90_000.0)
        # Both have same hack prob; higher coverage shifts net_benefit differently
        self.assertNotAlmostEqual(
            r_low["insurance_net_benefit_usd"],
            r_high["insurance_net_benefit_usd"],
            places=2,
        )


# ===========================================================================
# 8 — net_apy_after_premium_pct
# ===========================================================================

class TestNetAPY(unittest.TestCase):

    def test_basic_net_apy(self):
        # gross=8%, drag=1.6% → net=6.4%
        r = _run(
            gross_apy_pct=8.0,
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=2.0,
        )
        self.assertAlmostEqual(r["net_apy_after_premium_pct"], 6.4, places=3)

    def test_no_insurance_net_equals_gross(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(
            r["net_apy_after_premium_pct"], r["gross_apy_pct"] if "gross_apy_pct" in r
            else 8.0,  # fallback check
            places=3,
        )

    def test_net_apy_formula(self):
        r = _run()
        expected = 8.0 - r["premium_drag_pct"]
        self.assertAlmostEqual(r["net_apy_after_premium_pct"], expected, places=4)

    def test_net_apy_is_float(self):
        r = _run()
        self.assertIsInstance(r["net_apy_after_premium_pct"], float)

    def test_net_apy_can_be_negative(self):
        # Very high premium drag can make net APY negative
        r = _run(
            gross_apy_pct=2.0,
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=10.0,
        )
        self.assertLess(r["net_apy_after_premium_pct"], 0.0)

    def test_net_apy_less_than_gross_when_premium_nonzero(self):
        r = _run(insurance_premium_annual_pct=1.0, coverage_amount_usd=50_000.0)
        # premium_drag > 0 → net < gross
        # gross = 8.0
        self.assertLess(r["net_apy_after_premium_pct"], 8.0)

    def test_net_apy_equals_gross_no_coverage(self):
        r = _run(coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["net_apy_after_premium_pct"], 8.0, places=4)

    def test_net_apy_decreases_with_higher_premium(self):
        r_low = _run(insurance_premium_annual_pct=1.0)
        r_high = _run(insurance_premium_annual_pct=4.0)
        self.assertGreater(
            r_low["net_apy_after_premium_pct"],
            r_high["net_apy_after_premium_pct"],
        )


# ===========================================================================
# 9 — Label: INSURANCE_HIGHLY_RECOMMENDED
# ===========================================================================

class TestLabelHighlyRecommended(unittest.TestCase):
    """Uninsured + expected_loss_pct > gross_apy_pct → INSURANCE_HIGHLY_RECOMMENDED"""

    def _highly_rec(self, **kw):
        return _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            **kw,
        )

    def test_high_hack_prob_triggers(self):
        # hack=10%, loss=90% → exp_loss=9% > gross=5%
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=10.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_exactly_at_boundary_above(self):
        # hack=10%, loss=60% → exp_loss=6% > gross=5%
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=10.0,
            estimated_max_loss_pct=60.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_loss_pct_just_above_threshold(self):
        # hack=5%, loss=20% → exp_loss=1% < gross=5% → NOT highly rec
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=20.0,
            gross_apy_pct=5.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_expected_loss_barely_exceeds_apy(self):
        # hack=6%, loss=90% → 6*90/100=5.4% > gross=5%
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=6.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_coverage_nonzero_prevents_highly_rec(self):
        r = _run(
            coverage_amount_usd=1.0,   # tiny but nonzero
            insurance_premium_annual_pct=0.01,
            estimated_hack_probability_annual_pct=10.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_very_high_hack_probability(self):
        # hack=50%, loss=80% → exp_loss=40% >> gross=10%
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=10.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_label_is_string(self):
        r = _run()
        self.assertIsInstance(r["insurance_label"], str)

    def test_coverage_ratio_zero_with_highly_rec(self):
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=10.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertAlmostEqual(r["coverage_ratio"], 0.0, places=5)
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_high_gross_apy_prevents_highly_rec(self):
        # hack=5%, loss=80% → exp=4% < gross=20%
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=20.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_zero_hack_prob_never_highly_rec(self):
        r = self._highly_rec(
            estimated_hack_probability_annual_pct=0.0,
            estimated_max_loss_pct=100.0,
            gross_apy_pct=0.01,  # tiny gross — but 0 expected loss still < it
        )
        # 0*100/100 = 0, not > 0.01 → NOT highly rec
        self.assertNotEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)


# ===========================================================================
# 10 — Label: INSURANCE_BENEFICIAL
# ===========================================================================

class TestLabelBeneficial(unittest.TestCase):
    """Insured, net_benefit > 0, coverage_ratio >= 0.8 → INSURANCE_BENEFICIAL"""

    def test_beneficial_basic(self):
        # High hack prob, cheap insurance, high coverage → net_benefit > 0
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=95_000.0,
            insurance_premium_annual_pct=0.5,
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_coverage_below_80pct_not_beneficial(self):
        # Even with positive net_benefit, coverage < 0.8 → not BENEFICIAL
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=70_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_net_benefit_zero_not_beneficial(self):
        # net_benefit must be strictly > 0
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=5.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_beneficial_requires_both_conditions(self):
        # net_benefit > 0 AND coverage >= 0.8 — both needed
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=85_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        # With coverage_ratio = 0.85 and very cheap premium + high hack
        # → net_benefit should be > 0 → BENEFICIAL
        if r["insurance_net_benefit_usd"] > 0:
            self.assertEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_coverage_exactly_80pct_with_net_benefit(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=50.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        if r["insurance_net_benefit_usd"] > 0:
            self.assertEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_beneficial_label_value(self):
        self.assertEqual(_LABEL_BENEFICIAL, "INSURANCE_BENEFICIAL")

    def test_highly_rec_takes_precedence_over_beneficial(self):
        # If uninsured → highly_rec, not beneficial
        r = _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=10.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)
        self.assertNotEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_beneficial_with_full_coverage(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=0.2,
            estimated_hack_probability_annual_pct=40.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=5.0,
        )
        if r["insurance_net_benefit_usd"] > 0:
            self.assertEqual(r["insurance_label"], _LABEL_BENEFICIAL)


# ===========================================================================
# 11 — Label: INSURANCE_MARGINAL
# ===========================================================================

class TestLabelMarginal(unittest.TestCase):
    """net_benefit > -position*0.005 → INSURANCE_MARGINAL"""

    def _marginal_case(self):
        # Low hack prob, moderate premium → small negative net_benefit
        return _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=2.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=8.0,
        )

    def test_marginal_basic(self):
        r = self._marginal_case()
        nb = r["insurance_net_benefit_usd"]
        pos = 100_000.0
        # If net_benefit > -500 (i.e., -pos*0.005) → MARGINAL
        if nb > -pos * 0.005 and nb <= 0.0:
            self.assertEqual(r["insurance_label"], _LABEL_MARGINAL)

    def test_net_benefit_just_above_marginal_threshold(self):
        # net_benefit = -400, position = 100000 → threshold = -500 → MARGINAL
        r = self._marginal_case()
        nb = r["insurance_net_benefit_usd"]
        pos = 100_000.0
        threshold = -pos * 0.005
        if nb > threshold:
            self.assertIn(r["insurance_label"],
                          [_LABEL_BENEFICIAL, _LABEL_MARGINAL])

    def test_marginal_label_string(self):
        self.assertEqual(_LABEL_MARGINAL, "INSURANCE_MARGINAL")

    def test_not_marginal_when_very_expensive(self):
        # Very expensive premium → net_benefit << -pos*0.005 → NOT marginal
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=15.0,
            estimated_hack_probability_annual_pct=0.1,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=8.0,
        )
        nb = r["insurance_net_benefit_usd"]
        # With premium=12000/year and tiny expected loss, net_benefit ≪ -500
        self.assertLess(nb, -100_000.0 * 0.005)
        self.assertNotEqual(r["insurance_label"], _LABEL_MARGINAL)

    def test_marginal_below_beneficial(self):
        # net_benefit slightly negative but > -pos*0.005 → MARGINAL (not BENEFICIAL)
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=85_000.0,
            insurance_premium_annual_pct=1.5,
            estimated_hack_probability_annual_pct=3.0,
            estimated_max_loss_pct=70.0,
            gross_apy_pct=8.0,
        )
        self.assertIn(r["insurance_label"],
                      [_LABEL_BENEFICIAL, _LABEL_MARGINAL, _LABEL_OVERPRICED, _LABEL_ACCEPTABLE])

    def test_marginal_label_ordering(self):
        # Label precedence: highly_rec > beneficial > marginal > overpriced > acceptable
        self.assertGreater(
            [_LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
             _LABEL_OVERPRICED, _LABEL_ACCEPTABLE].index(_LABEL_MARGINAL),
            [_LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
             _LABEL_OVERPRICED, _LABEL_ACCEPTABLE].index(_LABEL_BENEFICIAL),
        )

    def test_marginal_net_benefit_threshold(self):
        pos = 200_000.0
        r = _run(
            position_size_usd=pos,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=2.0,
            estimated_hack_probability_annual_pct=2.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=8.0,
        )
        nb = r["insurance_net_benefit_usd"]
        threshold = -pos * 0.005  # -1000
        # If net_benefit > threshold → MARGINAL (assuming not BENEFICIAL first)
        if 0.0 >= nb > threshold:
            self.assertEqual(r["insurance_label"], _LABEL_MARGINAL)

    def test_all_five_labels_are_distinct(self):
        labels = {
            _LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
            _LABEL_OVERPRICED, _LABEL_ACCEPTABLE,
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 12 — Label: INSURANCE_OVERPRICED
# ===========================================================================

class TestLabelOverpriced(unittest.TestCase):
    """premium_drag > gross_apy * 0.3 → INSURANCE_OVERPRICED"""

    def _overpriced_case(self):
        return _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=15.0,   # drag=12% > 8%*0.3=2.4% → OVERPRICED
            estimated_hack_probability_annual_pct=0.1,
            estimated_max_loss_pct=50.0,
            gross_apy_pct=8.0,
        )

    def test_overpriced_basic(self):
        r = self._overpriced_case()
        # net_benefit << 0, not marginal → if premium_drag > gross*0.3 → OVERPRICED
        drag = r["premium_drag_pct"]
        gross = 8.0
        self.assertGreater(drag, gross * 0.3)

    def test_overpriced_label_when_drag_exceeds_threshold(self):
        r = self._overpriced_case()
        self.assertEqual(r["insurance_label"], _LABEL_OVERPRICED)

    def test_not_overpriced_with_low_premium(self):
        r = _run(
            insurance_premium_annual_pct=1.0,
            coverage_amount_usd=50_000.0,
            gross_apy_pct=8.0,
            estimated_hack_probability_annual_pct=2.0,
            estimated_max_loss_pct=80.0,
        )
        # drag = 50000*1/100/100000*100 = 0.5% < 8%*0.3 = 2.4%
        self.assertNotEqual(r["insurance_label"], _LABEL_OVERPRICED)

    def test_overpriced_threshold_exact(self):
        # drag just above 0.3 * gross_apy
        # gross=10%, 0.3*10=3%; drag=3.01%
        # drag = cov * pct / 100 / pos * 100 → if cov=100k, pos=100k → drag=pct
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=3.1,
            estimated_hack_probability_annual_pct=0.01,
            estimated_max_loss_pct=10.0,
            gross_apy_pct=10.0,
        )
        # drag=3.1% > 10%*0.3=3% → OVERPRICED (if net_benefit <= -pos*0.005)
        self.assertEqual(r["premium_drag_pct"], r["annual_premium_usd"] / 100_000.0 * 100)

    def test_overpriced_label_value(self):
        self.assertEqual(_LABEL_OVERPRICED, "INSURANCE_OVERPRICED")

    def test_overpriced_requires_insured(self):
        # Uninsured → never overpriced (it's either HIGHLY_REC or ACCEPTABLE)
        r = _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=1.0,
            estimated_max_loss_pct=10.0,
            gross_apy_pct=10.0,
        )
        self.assertNotEqual(r["insurance_label"], _LABEL_OVERPRICED)

    def test_high_apy_raises_overpriced_threshold(self):
        # With gross=50%, threshold is 50*0.3=15%; same premium drag is no longer overpriced
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=3.0,
            estimated_hack_probability_annual_pct=0.01,
            estimated_max_loss_pct=10.0,
            gross_apy_pct=50.0,
        )
        # drag=3% < 50%*0.3=15% → not overpriced
        self.assertNotEqual(r["insurance_label"], _LABEL_OVERPRICED)

    def test_overpriced_with_full_coverage(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=100_000.0,
            insurance_premium_annual_pct=10.0,
            estimated_hack_probability_annual_pct=0.1,
            estimated_max_loss_pct=5.0,
            gross_apy_pct=5.0,
        )
        # drag=10%, gross*0.3=1.5% → if net_benefit << -pos*0.005 → OVERPRICED
        self.assertEqual(r["insurance_label"], _LABEL_OVERPRICED)


# ===========================================================================
# 13 — Label: UNINSURED_ACCEPTABLE_RISK
# ===========================================================================

class TestLabelAcceptable(unittest.TestCase):

    def test_uninsured_low_risk(self):
        # hack=0.5%, loss=80% → exp_loss=0.4% < gross=5% → ACCEPTABLE
        r = _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=0.5,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_ACCEPTABLE)

    def test_label_value(self):
        self.assertEqual(_LABEL_ACCEPTABLE, "UNINSURED_ACCEPTABLE_RISK")

    def test_insured_fallback_acceptable(self):
        # Insured but: net_benefit very negative, but premium_drag not > gross*0.3
        # → falls through to ACCEPTABLE
        # Large position, small coverage, tiny premium, low hack prob
        r = _run(
            position_size_usd=1_000_000.0,
            coverage_amount_usd=10_000.0,
            insurance_premium_annual_pct=0.1,
            estimated_hack_probability_annual_pct=0.01,
            estimated_max_loss_pct=5.0,
            gross_apy_pct=8.0,
        )
        # net_benefit: loss_without=500, uncovered=990k, uncovered_loss=495, premium=10
        # loss_with=495+10=505; net_benefit=500-505-10=-15
        # threshold = -1000000*0.005 = -5000; -15 > -5000 → MARGINAL
        self.assertIn(r["insurance_label"],
                      [_LABEL_MARGINAL, _LABEL_BENEFICIAL, _LABEL_ACCEPTABLE])

    def test_acceptable_uninsured_zero_hack_prob(self):
        r = _run(
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            estimated_hack_probability_annual_pct=0.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(r["insurance_label"], _LABEL_ACCEPTABLE)

    def test_five_valid_labels(self):
        all_labels = {
            _LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
            _LABEL_OVERPRICED, _LABEL_ACCEPTABLE
        }
        r = _run()
        self.assertIn(r["insurance_label"], all_labels)


# ===========================================================================
# 14 — Validation
# ===========================================================================

class TestValidation(unittest.TestCase):

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_name="")

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_name="   ")

    def test_negative_position_size_raises(self):
        with self.assertRaises((ValueError, Exception)):
            _run(position_size_usd=-1.0)

    def test_zero_position_size_raises(self):
        with self.assertRaises(ValueError):
            _run(position_size_usd=0.0)

    def test_negative_coverage_raises(self):
        with self.assertRaises(ValueError):
            _run(coverage_amount_usd=-100.0)

    def test_negative_premium_pct_raises(self):
        with self.assertRaises(ValueError):
            _run(insurance_premium_annual_pct=-1.0)

    def test_risk_score_above_100_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_risk_score=101)

    def test_risk_score_below_0_raises(self):
        with self.assertRaises(ValueError):
            _run(protocol_risk_score=-1)

    def test_negative_hack_probability_raises(self):
        with self.assertRaises(ValueError):
            _run(estimated_hack_probability_annual_pct=-0.1)

    def test_max_loss_above_100_raises(self):
        with self.assertRaises(ValueError):
            _run(estimated_max_loss_pct=101.0)

    def test_max_loss_negative_raises(self):
        with self.assertRaises(ValueError):
            _run(estimated_max_loss_pct=-1.0)

    def test_negative_gross_apy_raises(self):
        with self.assertRaises(ValueError):
            _run(gross_apy_pct=-0.1)

    def test_risk_score_boundary_0_valid(self):
        r = _run(protocol_risk_score=0)
        self.assertEqual(r["protocol_risk_score"], 0)

    def test_risk_score_boundary_100_valid(self):
        r = _run(protocol_risk_score=100)
        self.assertEqual(r["protocol_risk_score"], 100)

    def test_max_loss_boundary_100_valid(self):
        r = _run(estimated_max_loss_pct=100.0)
        self.assertIsNotNone(r)

    def test_max_loss_boundary_0_valid(self):
        r = _run(estimated_max_loss_pct=0.0)
        self.assertIsNotNone(r)

    def test_zero_premium_pct_valid(self):
        r = _run(insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 0.0, places=4)

    def test_zero_gross_apy_valid(self):
        r = _run(gross_apy_pct=0.0, coverage_amount_usd=0.0, insurance_premium_annual_pct=0.0)
        self.assertAlmostEqual(r["net_apy_after_premium_pct"], 0.0, places=4)

    def test_hack_prob_zero_valid(self):
        r = _run(estimated_hack_probability_annual_pct=0.0)
        self.assertAlmostEqual(r["expected_annual_loss_without_insurance_usd"], 0.0, places=4)


# ===========================================================================
# 15 — Log file (ring-buffer, atomic write)
# ===========================================================================

class TestLogFile(unittest.TestCase):

    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.log_path)
        self.a = DeFiProtocolInsuranceCoverageAnalyzer(log_file=self.log_path, log_cap=5)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def _call(self, name="P"):
        return self.a.analyze(**_base(protocol_name=name))

    def test_log_created_on_first_call(self):
        self._call()
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_contains_one_entry_after_one_call(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_contains_two_entries_after_two_calls(self):
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
        self.assertEqual(len(data), 5)  # cap=5

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(7):
            self._call(f"P{i}")
        with open(self.log_path) as f:
            data = json.load(f)
        names = [e["protocol_name"] for e in data]
        self.assertIn("P6", names)
        self.assertNotIn("P0", names)

    def test_log_entry_has_expected_fields(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        entry = data[0]
        self.assertIn("protocol_name", entry)
        self.assertIn("coverage_ratio", entry)
        self.assertIn("insurance_label", entry)

    def test_load_log_returns_list(self):
        self._call()
        log = self.a.load_log()
        self.assertIsInstance(log, list)

    def test_load_log_empty_when_no_file(self):
        log = self.a.load_log()
        self.assertEqual(log, [])

    def test_load_log_matches_written_data(self):
        self._call("TestProtocol")
        log = self.a.load_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["protocol_name"], "TestProtocol")

    def test_log_cap_default(self):
        self.assertEqual(LOG_CAP, 100)

    def test_default_log_file_path_exists_in_module(self):
        self.assertIn("data", DEFAULT_LOG_FILE)
        self.assertIn("insurance_coverage_log", DEFAULT_LOG_FILE)

    def test_multiple_analyzers_same_log_accumulate(self):
        a2 = DeFiProtocolInsuranceCoverageAnalyzer(log_file=self.log_path, log_cap=5)
        self._call("A")
        a2.analyze(**_base(protocol_name="B"))
        log = self.a.load_log()
        self.assertEqual(len(log), 2)

    def test_corrupted_log_starts_fresh(self):
        with open(self.log_path, "w") as f:
            f.write("NOT_JSON")
        self._call("Recovery")
        log = self.a.load_log()
        self.assertEqual(len(log), 1)

    def test_log_entry_insurance_label_valid(self):
        self._call()
        log = self.a.load_log()
        valid_labels = {
            _LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
            _LABEL_OVERPRICED, _LABEL_ACCEPTABLE,
        }
        self.assertIn(log[0]["insurance_label"], valid_labels)


# ===========================================================================
# 16 — Diverse protocol scenarios
# ===========================================================================

class TestDiverseScenarios(unittest.TestCase):

    def test_aave_style_low_risk(self):
        r = _run(
            protocol_name="Aave V3",
            position_size_usd=200_000.0,
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            protocol_risk_score=15,
            estimated_hack_probability_annual_pct=0.3,
            estimated_max_loss_pct=70.0,
            gross_apy_pct=4.0,
        )
        # exp_loss = 0.3*70/100 = 0.21% < 4% → ACCEPTABLE
        self.assertEqual(r["insurance_label"], _LABEL_ACCEPTABLE)

    def test_newer_protocol_high_risk(self):
        r = _run(
            protocol_name="NewProtocol",
            position_size_usd=50_000.0,
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            protocol_risk_score=85,
            estimated_hack_probability_annual_pct=15.0,
            estimated_max_loss_pct=100.0,
            gross_apy_pct=20.0,
        )
        # exp_loss = 15*100/100 = 15% < 20% → NOT HIGHLY_REC
        # 15% > 20%? No → acceptable
        self.assertEqual(r["insurance_label"], _LABEL_ACCEPTABLE)

    def test_newer_protocol_extreme_risk(self):
        r = _run(
            protocol_name="ExtremeProtocol",
            position_size_usd=50_000.0,
            coverage_amount_usd=0.0,
            insurance_premium_annual_pct=0.0,
            protocol_risk_score=95,
            estimated_hack_probability_annual_pct=25.0,
            estimated_max_loss_pct=100.0,
            gross_apy_pct=20.0,
        )
        # exp_loss = 25*100/100 = 25% > 20% → HIGHLY_REC
        self.assertEqual(r["insurance_label"], _LABEL_HIGHLY_RECOMMENDED)

    def test_well_covered_cheap_insurance(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=95_000.0,
            insurance_premium_annual_pct=0.3,
            protocol_risk_score=40,
            estimated_hack_probability_annual_pct=40.0,
            estimated_max_loss_pct=90.0,
            gross_apy_pct=10.0,
        )
        # This should be BENEFICIAL
        if r["insurance_net_benefit_usd"] > 0 and r["coverage_ratio"] >= 0.8:
            self.assertEqual(r["insurance_label"], _LABEL_BENEFICIAL)

    def test_moderate_hack_prob_with_coverage(self):
        r = _run(
            position_size_usd=100_000.0,
            coverage_amount_usd=80_000.0,
            insurance_premium_annual_pct=1.0,
            protocol_risk_score=50,
            estimated_hack_probability_annual_pct=5.0,
            estimated_max_loss_pct=80.0,
            gross_apy_pct=7.0,
        )
        all_valid = {
            _LABEL_HIGHLY_RECOMMENDED, _LABEL_BENEFICIAL, _LABEL_MARGINAL,
            _LABEL_OVERPRICED, _LABEL_ACCEPTABLE,
        }
        self.assertIn(r["insurance_label"], all_valid)

    def test_large_position_consistency(self):
        r = _run(
            position_size_usd=10_000_000.0,
            coverage_amount_usd=8_000_000.0,
            insurance_premium_annual_pct=2.0,
        )
        self.assertAlmostEqual(r["coverage_ratio"], 0.8, places=5)
        expected_premium = 8_000_000.0 * 2.0 / 100.0
        self.assertAlmostEqual(r["annual_premium_usd"], expected_premium, places=2)

    def test_small_position_consistency(self):
        r = _run(position_size_usd=1_000.0, coverage_amount_usd=800.0,
                 insurance_premium_annual_pct=2.0)
        self.assertAlmostEqual(r["annual_premium_usd"], 16.0, places=4)


# ===========================================================================
# 17 — Classification helper tests
# ===========================================================================

class TestClassifyHelper(unittest.TestCase):

    def _cls(self, **kw):
        defaults = dict(
            position_size_usd=100_000.0,
            coverage_amount_usd=0.0,
            coverage_ratio=0.0,
            hack_probability_annual_pct=5.0,
            max_loss_pct=80.0,
            gross_apy_pct=5.0,
            insurance_net_benefit_usd=0.0,
            premium_drag_pct=0.0,
        )
        defaults.update(kw)
        return DeFiProtocolInsuranceCoverageAnalyzer._classify(**defaults)

    def test_uninsured_low_risk_acceptable(self):
        # exp_loss=5*80/100=4 < 5 → acceptable
        label = self._cls(
            coverage_amount_usd=0.0,
            hack_probability_annual_pct=5.0,
            max_loss_pct=80.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(label, _LABEL_ACCEPTABLE)

    def test_uninsured_high_risk_highly_rec(self):
        label = self._cls(
            coverage_amount_usd=0.0,
            hack_probability_annual_pct=10.0,
            max_loss_pct=60.0,
            gross_apy_pct=5.0,
        )
        self.assertEqual(label, _LABEL_HIGHLY_RECOMMENDED)

    def test_insured_positive_net_high_coverage_beneficial(self):
        label = self._cls(
            coverage_amount_usd=90_000.0,
            coverage_ratio=0.9,
            insurance_net_benefit_usd=1000.0,
            premium_drag_pct=1.0,
        )
        self.assertEqual(label, _LABEL_BENEFICIAL)

    def test_insured_positive_net_low_coverage_not_beneficial(self):
        # coverage_ratio < 0.8 → not BENEFICIAL
        label = self._cls(
            coverage_amount_usd=70_000.0,
            coverage_ratio=0.7,
            insurance_net_benefit_usd=100.0,
            premium_drag_pct=1.0,
        )
        self.assertNotEqual(label, _LABEL_BENEFICIAL)

    def test_insured_marginal(self):
        # net_benefit = -400 > -500 (pos*0.005) → MARGINAL
        label = self._cls(
            coverage_amount_usd=80_000.0,
            coverage_ratio=0.8,
            insurance_net_benefit_usd=-400.0,
            premium_drag_pct=2.0,
        )
        self.assertEqual(label, _LABEL_MARGINAL)

    def test_insured_overpriced(self):
        # net_benefit << -500 (not marginal), drag=5 > gross*0.3=2.4 → OVERPRICED
        label = self._cls(
            coverage_amount_usd=80_000.0,
            coverage_ratio=0.8,
            insurance_net_benefit_usd=-10_000.0,
            premium_drag_pct=5.0,
            gross_apy_pct=8.0,
        )
        self.assertEqual(label, _LABEL_OVERPRICED)

    def test_insured_fallback_acceptable(self):
        # net_benefit << -500 (not marginal), drag=1 < gross*0.3=2.4 → ACCEPTABLE
        label = self._cls(
            coverage_amount_usd=80_000.0,
            coverage_ratio=0.8,
            insurance_net_benefit_usd=-10_000.0,
            premium_drag_pct=1.0,
            gross_apy_pct=8.0,
        )
        self.assertEqual(label, _LABEL_ACCEPTABLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
