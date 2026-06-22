"""
Tests for MP-1125: DeFiProtocolSupplyCapProximityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_supply_cap_proximity_analyzer -v
Total: >= 120 test methods.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_supply_cap_proximity_analyzer import (
    DeFiProtocolSupplyCapProximityAnalyzer,
    SupplyCapProximityReport,
    MAX_ENTRIES,
    DAYS_SENTINEL_NEVER,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_report(
    current_total_supply_usd: float = 50_000_000.0,
    supply_cap_usd: float = 100_000_000.0,
    intended_deposit_usd: float = 1_000_000.0,
    current_supply_apr_pct: float = 4.0,
    recent_supply_growth_usd_per_day: float = 0.0,
    protocol_name: str = "TestMarket",
) -> SupplyCapProximityReport:
    ana = DeFiProtocolSupplyCapProximityAnalyzer()
    return ana.analyze(
        current_total_supply_usd=current_total_supply_usd,
        supply_cap_usd=supply_cap_usd,
        intended_deposit_usd=intended_deposit_usd,
        current_supply_apr_pct=current_supply_apr_pct,
        recent_supply_growth_usd_per_day=recent_supply_growth_usd_per_day,
        protocol_name=protocol_name,
    )


def make_market(**kwargs) -> dict:
    base = dict(
        current_total_supply_usd=50_000_000.0,
        supply_cap_usd=100_000_000.0,
        intended_deposit_usd=1_000_000.0,
        current_supply_apr_pct=4.0,
        recent_supply_growth_usd_per_day=0.0,
        protocol_name="TestMarket",
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Utilization of cap
# ---------------------------------------------------------------------------

class TestUtilization(unittest.TestCase):

    def test_half_full(self):
        r = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 50.0, places=6)

    def test_quarter_full(self):
        r = make_report(current_total_supply_usd=25.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 25.0, places=6)

    def test_full(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 100.0, places=6)

    def test_over_full(self):
        r = make_report(current_total_supply_usd=120.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 120.0, places=6)

    def test_empty(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 0.0, places=6)


# ---------------------------------------------------------------------------
# 2. Remaining headroom
# ---------------------------------------------------------------------------

class TestHeadroom(unittest.TestCase):

    def test_headroom_basic(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.remaining_headroom_usd, 40.0, places=6)

    def test_headroom_full_zero(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.remaining_headroom_usd, 0.0, places=6)

    def test_headroom_over_full_clamped(self):
        r = make_report(current_total_supply_usd=120.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.remaining_headroom_usd, 0.0, places=6)

    def test_headroom_empty_full_cap(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.remaining_headroom_usd, 100.0, places=6)

    def test_headroom_pct(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.headroom_pct, 40.0, places=6)

    def test_headroom_pct_full(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.headroom_pct, 0.0, places=6)

    def test_headroom_pct_over_full(self):
        r = make_report(current_total_supply_usd=150.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.headroom_pct, 0.0, places=6)


# ---------------------------------------------------------------------------
# 3. Deposit fits
# ---------------------------------------------------------------------------

class TestDepositFits(unittest.TestCase):

    def test_fits_small(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=30.0)
        self.assertTrue(r.deposit_fits)

    def test_fits_exact(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=40.0)
        self.assertTrue(r.deposit_fits)

    def test_does_not_fit(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=50.0)
        self.assertFalse(r.deposit_fits)

    def test_full_cap_does_not_fit(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertFalse(r.deposit_fits)

    def test_zero_deposit_fits(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=0.0)
        self.assertTrue(r.deposit_fits)

    def test_deposit_fits_is_bool(self):
        r = make_report()
        self.assertIsInstance(r.deposit_fits, bool)


# ---------------------------------------------------------------------------
# 4. Fillable pct of deposit
# ---------------------------------------------------------------------------

class TestFillablePct(unittest.TestCase):

    def test_fully_fillable(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=30.0)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 100.0, places=6)

    def test_half_fillable(self):
        r = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                        intended_deposit_usd=40.0)
        # headroom = 20, deposit = 40 -> 50%
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 50.0, places=6)

    def test_capped_at_100(self):
        r = make_report(current_total_supply_usd=10.0, supply_cap_usd=100.0,
                        intended_deposit_usd=5.0)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 100.0, places=6)

    def test_zero_headroom_zero_fillable(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=10.0)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 0.0, places=6)

    def test_zero_deposit_fully_fillable(self):
        r = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                        intended_deposit_usd=0.0)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 100.0, places=6)

    def test_fillable_in_range(self):
        for sup, dep in [(10, 5), (80, 40), (95, 100), (100, 10)]:
            r = make_report(current_total_supply_usd=float(sup), supply_cap_usd=100.0,
                            intended_deposit_usd=float(dep))
            self.assertGreaterEqual(r.fillable_pct_of_deposit, 0.0)
            self.assertLessEqual(r.fillable_pct_of_deposit, 100.0)


# ---------------------------------------------------------------------------
# 5. Days until cap reached
# ---------------------------------------------------------------------------

class TestDaysUntilCap(unittest.TestCase):

    def test_positive_growth(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=2.0)
        # headroom = 10, growth = 2 -> 5 days
        self.assertAlmostEqual(r.days_until_cap_reached, 5.0, places=6)

    def test_zero_growth_sentinel(self):
        r = make_report(recent_supply_growth_usd_per_day=0.0)
        self.assertAlmostEqual(r.days_until_cap_reached, DAYS_SENTINEL_NEVER, places=2)

    def test_negative_growth_sentinel(self):
        r = make_report(recent_supply_growth_usd_per_day=-1000.0)
        self.assertAlmostEqual(r.days_until_cap_reached, DAYS_SENTINEL_NEVER, places=2)

    def test_full_cap_positive_growth_zero_days(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=5.0)
        self.assertAlmostEqual(r.days_until_cap_reached, 0.0, places=6)

    def test_fast_growth_few_days(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=10.0)
        self.assertAlmostEqual(r.days_until_cap_reached, 1.0, places=6)

    def test_sentinel_is_finite(self):
        r = make_report(recent_supply_growth_usd_per_day=0.0)
        self.assertTrue(math.isfinite(r.days_until_cap_reached))


# ---------------------------------------------------------------------------
# 6. Post-deposit utilization
# ---------------------------------------------------------------------------

class TestPostDepositUtilization(unittest.TestCase):

    def test_post_deposit_basic(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=20.0)
        # (60+20)/100 = 80%
        self.assertAlmostEqual(r.post_deposit_utilization_pct, 80.0, places=6)

    def test_post_deposit_capped_at_remaining(self):
        r = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                        intended_deposit_usd=50.0)
        # effective deposit capped at 20 -> (80+20)/100 = 100%
        self.assertAlmostEqual(r.post_deposit_utilization_pct, 100.0, places=6)

    def test_post_deposit_no_deposit(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=0.0)
        self.assertAlmostEqual(r.post_deposit_utilization_pct, 60.0, places=6)

    def test_post_deposit_at_cap(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=10.0)
        self.assertAlmostEqual(r.post_deposit_utilization_pct, 100.0, places=6)

    def test_post_deposit_ge_utilization(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0,
                        intended_deposit_usd=20.0)
        self.assertGreaterEqual(r.post_deposit_utilization_pct, r.utilization_of_cap_pct)


# ---------------------------------------------------------------------------
# 7. Yield compression risk
# ---------------------------------------------------------------------------

class TestYieldCompressionRisk(unittest.TestCase):

    def test_low_util_low_risk(self):
        r = make_report(current_total_supply_usd=10.0, supply_cap_usd=100.0)
        self.assertLess(r.yield_compression_risk_pct, 10.0)

    def test_high_util_high_risk(self):
        r = make_report(current_total_supply_usd=95.0, supply_cap_usd=100.0)
        self.assertGreater(r.yield_compression_risk_pct, 70.0)

    def test_full_cap_max_risk(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.yield_compression_risk_pct, 100.0, places=4)

    def test_empty_zero_risk(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.yield_compression_risk_pct, 0.0, places=4)

    def test_risk_in_range(self):
        for sup in (0, 25, 50, 75, 100):
            r = make_report(current_total_supply_usd=float(sup), supply_cap_usd=100.0)
            self.assertGreaterEqual(r.yield_compression_risk_pct, 0.0)
            self.assertLessEqual(r.yield_compression_risk_pct, 100.0)

    def test_risk_monotone_increasing(self):
        r1 = make_report(current_total_supply_usd=30.0, supply_cap_usd=100.0)
        r2 = make_report(current_total_supply_usd=70.0, supply_cap_usd=100.0)
        self.assertGreater(r2.yield_compression_risk_pct, r1.yield_compression_risk_pct)

    def test_over_full_risk_clamped(self):
        r = make_report(current_total_supply_usd=150.0, supply_cap_usd=100.0)
        self.assertLessEqual(r.yield_compression_risk_pct, 100.0)


# ---------------------------------------------------------------------------
# 8. Cap proximity score
# ---------------------------------------------------------------------------

class TestCapProximityScore(unittest.TestCase):

    def test_score_in_range(self):
        for sup in (0, 25, 50, 75, 95, 100):
            r = make_report(current_total_supply_usd=float(sup), supply_cap_usd=100.0,
                            intended_deposit_usd=1.0)
            self.assertGreaterEqual(r.cap_proximity_score, 0.0)
            self.assertLessEqual(r.cap_proximity_score, 100.0)

    def test_ample_headroom_high_score(self):
        r = make_report(current_total_supply_usd=5.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertGreater(r.cap_proximity_score, 70.0)

    def test_at_cap_low_score(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertLess(r.cap_proximity_score, 30.0)

    def test_deposit_fits_raises_score(self):
        r_fit = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                            intended_deposit_usd=10.0)
        r_nofit = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                              intended_deposit_usd=60.0)
        self.assertGreater(r_fit.cap_proximity_score, r_nofit.cap_proximity_score)

    def test_more_headroom_higher_score(self):
        r1 = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                         intended_deposit_usd=1.0)
        r2 = make_report(current_total_supply_usd=20.0, supply_cap_usd=100.0,
                         intended_deposit_usd=1.0)
        self.assertGreater(r2.cap_proximity_score, r1.cap_proximity_score)


# ---------------------------------------------------------------------------
# 9. Proximity label classification
# ---------------------------------------------------------------------------

class TestProximityLabel(unittest.TestCase):

    def test_ample_headroom(self):
        r = make_report(current_total_supply_usd=30.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "AMPLE_HEADROOM")

    def test_comfortable(self):
        r = make_report(current_total_supply_usd=70.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "COMFORTABLE")

    def test_approaching_cap(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "APPROACHING_CAP")

    def test_near_cap(self):
        r = make_report(current_total_supply_usd=97.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "NEAR_CAP")

    def test_at_cap(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "AT_CAP")

    def test_over_cap_at_cap(self):
        r = make_report(current_total_supply_usd=110.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "AT_CAP")

    def test_boundary_60_comfortable(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "COMFORTABLE")

    def test_boundary_just_below_60_ample(self):
        r = make_report(current_total_supply_usd=59.9, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "AMPLE_HEADROOM")

    def test_boundary_85_approaching(self):
        r = make_report(current_total_supply_usd=85.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "APPROACHING_CAP")

    def test_boundary_95_near(self):
        r = make_report(current_total_supply_usd=95.0, supply_cap_usd=100.0)
        self.assertEqual(r.proximity_label, "NEAR_CAP")

    def test_label_valid_set(self):
        valid = {"AMPLE_HEADROOM", "COMFORTABLE", "APPROACHING_CAP", "NEAR_CAP",
                 "AT_CAP", "UNCAPPED"}
        for sup in (10, 70, 90, 97, 100):
            r = make_report(current_total_supply_usd=float(sup), supply_cap_usd=100.0)
            self.assertIn(r.proximity_label, valid)


# ---------------------------------------------------------------------------
# 10. UNCAPPED path
# ---------------------------------------------------------------------------

class TestUncapped(unittest.TestCase):

    def test_zero_cap_uncapped(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertEqual(r.proximity_label, "UNCAPPED")

    def test_negative_cap_uncapped(self):
        r = make_report(supply_cap_usd=-100.0)
        self.assertEqual(r.proximity_label, "UNCAPPED")

    def test_uncapped_flag(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertIn("UNCAPPED_MARKET", r.flags)

    def test_uncapped_deposit_fits(self):
        r = make_report(supply_cap_usd=0.0, intended_deposit_usd=999_999_999.0)
        self.assertTrue(r.deposit_fits)

    def test_uncapped_max_score(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertAlmostEqual(r.cap_proximity_score, 100.0, places=4)

    def test_uncapped_grade_a(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertEqual(r.grade, "A")

    def test_uncapped_zero_compression_risk(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertAlmostEqual(r.yield_compression_risk_pct, 0.0, places=4)

    def test_uncapped_fillable_100(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 100.0, places=4)

    def test_uncapped_advisory_mentions(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertTrue(any("UNCAPPED" in m for m in r.advisory))

    def test_uncapped_only_uncapped_flag(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertEqual(r.flags, ["UNCAPPED_MARKET"])

    def test_uncapped_days_sentinel(self):
        r = make_report(supply_cap_usd=0.0)
        self.assertAlmostEqual(r.days_until_cap_reached, DAYS_SENTINEL_NEVER, places=2)


# ---------------------------------------------------------------------------
# 11. Grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):

    def test_grade_valid_set(self):
        valid = {"A", "B", "C", "D", "F"}
        for sup in (5, 50, 90, 100):
            r = make_report(current_total_supply_usd=float(sup), supply_cap_usd=100.0,
                            intended_deposit_usd=1.0)
            self.assertIn(r.grade, valid)

    def test_ample_headroom_grade_a(self):
        r = make_report(current_total_supply_usd=5.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertEqual(r.grade, "A")

    def test_at_cap_grade_f(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertEqual(r.grade, "F")

    def test_deposit_blocked_low_grade(self):
        r = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                        intended_deposit_usd=60.0)
        self.assertIn(r.grade, {"D", "F"})

    def test_grade_is_string(self):
        r = make_report()
        self.assertIsInstance(r.grade, str)


# ---------------------------------------------------------------------------
# 12. Flags - AT_CAP / NEAR_CAP
# ---------------------------------------------------------------------------

class TestFlagAtNearCap(unittest.TestCase):

    def test_at_cap_flag(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertIn("AT_CAP", r.flags)

    def test_over_cap_at_cap_flag(self):
        r = make_report(current_total_supply_usd=120.0, supply_cap_usd=100.0)
        self.assertIn("AT_CAP", r.flags)

    def test_near_cap_flag(self):
        r = make_report(current_total_supply_usd=97.0, supply_cap_usd=100.0)
        self.assertIn("NEAR_CAP", r.flags)

    def test_near_cap_at_95(self):
        r = make_report(current_total_supply_usd=95.0, supply_cap_usd=100.0)
        self.assertIn("NEAR_CAP", r.flags)

    def test_at_cap_not_near_cap(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertNotIn("NEAR_CAP", r.flags)

    def test_comfortable_no_at_near(self):
        r = make_report(current_total_supply_usd=70.0, supply_cap_usd=100.0)
        self.assertNotIn("AT_CAP", r.flags)
        self.assertNotIn("NEAR_CAP", r.flags)


# ---------------------------------------------------------------------------
# 13. Flags - AMPLE_HEADROOM
# ---------------------------------------------------------------------------

class TestFlagAmpleHeadroom(unittest.TestCase):

    def test_ample_flag(self):
        r = make_report(current_total_supply_usd=30.0, supply_cap_usd=100.0)
        self.assertIn("AMPLE_HEADROOM", r.flags)

    def test_no_ample_when_high(self):
        r = make_report(current_total_supply_usd=70.0, supply_cap_usd=100.0)
        self.assertNotIn("AMPLE_HEADROOM", r.flags)

    def test_ample_at_zero(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=100.0)
        self.assertIn("AMPLE_HEADROOM", r.flags)

    def test_no_ample_at_60(self):
        r = make_report(current_total_supply_usd=60.0, supply_cap_usd=100.0)
        self.assertNotIn("AMPLE_HEADROOM", r.flags)


# ---------------------------------------------------------------------------
# 14. Flags - DEPOSIT_DOES_NOT_FIT
# ---------------------------------------------------------------------------

class TestFlagDepositDoesNotFit(unittest.TestCase):

    def test_flag_when_too_big(self):
        r = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                        intended_deposit_usd=50.0)
        self.assertIn("DEPOSIT_DOES_NOT_FIT", r.flags)

    def test_no_flag_when_fits(self):
        r = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                        intended_deposit_usd=10.0)
        self.assertNotIn("DEPOSIT_DOES_NOT_FIT", r.flags)

    def test_flag_at_full_cap(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertIn("DEPOSIT_DOES_NOT_FIT", r.flags)

    def test_no_flag_exact_fit(self):
        r = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                        intended_deposit_usd=20.0)
        self.assertNotIn("DEPOSIT_DOES_NOT_FIT", r.flags)


# ---------------------------------------------------------------------------
# 15. Flags - FAST_FILLING / CAP_REACHED_SOON
# ---------------------------------------------------------------------------

class TestFlagFilling(unittest.TestCase):

    def test_fast_filling(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=5.0)
        # days = 2 < 7
        self.assertIn("FAST_FILLING", r.flags)

    def test_cap_reached_soon(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=1.0)
        # days = 10 < 14
        self.assertIn("CAP_REACHED_SOON", r.flags)

    def test_no_filling_flags_slow(self):
        r = make_report(current_total_supply_usd=50.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=0.5)
        # days = 100 -> no flags
        self.assertNotIn("FAST_FILLING", r.flags)
        self.assertNotIn("CAP_REACHED_SOON", r.flags)

    def test_no_filling_flags_zero_growth(self):
        r = make_report(recent_supply_growth_usd_per_day=0.0)
        self.assertNotIn("FAST_FILLING", r.flags)
        self.assertNotIn("CAP_REACHED_SOON", r.flags)

    def test_no_filling_flags_negative_growth(self):
        r = make_report(recent_supply_growth_usd_per_day=-100.0)
        self.assertNotIn("FAST_FILLING", r.flags)
        self.assertNotIn("CAP_REACHED_SOON", r.flags)

    def test_fast_filling_implies_cap_soon(self):
        r = make_report(current_total_supply_usd=90.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=5.0)
        self.assertIn("CAP_REACHED_SOON", r.flags)


# ---------------------------------------------------------------------------
# 16. Flags - HIGH_YIELD_COMPRESSION_RISK
# ---------------------------------------------------------------------------

class TestFlagCompressionRisk(unittest.TestCase):

    def test_high_risk_flag(self):
        r = make_report(current_total_supply_usd=95.0, supply_cap_usd=100.0)
        self.assertIn("HIGH_YIELD_COMPRESSION_RISK", r.flags)

    def test_low_risk_no_flag(self):
        r = make_report(current_total_supply_usd=20.0, supply_cap_usd=100.0)
        self.assertNotIn("HIGH_YIELD_COMPRESSION_RISK", r.flags)

    def test_full_cap_high_risk(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertIn("HIGH_YIELD_COMPRESSION_RISK", r.flags)


# ---------------------------------------------------------------------------
# 17. Flags - SHRINKING_SUPPLY
# ---------------------------------------------------------------------------

class TestFlagShrinking(unittest.TestCase):

    def test_shrinking_flag(self):
        r = make_report(recent_supply_growth_usd_per_day=-100.0)
        self.assertIn("SHRINKING_SUPPLY", r.flags)

    def test_no_shrinking_positive(self):
        r = make_report(recent_supply_growth_usd_per_day=100.0)
        self.assertNotIn("SHRINKING_SUPPLY", r.flags)

    def test_no_shrinking_zero(self):
        r = make_report(recent_supply_growth_usd_per_day=0.0)
        self.assertNotIn("SHRINKING_SUPPLY", r.flags)

    def test_shrinking_no_filling_flags(self):
        r = make_report(current_total_supply_usd=99.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=-50.0)
        self.assertIn("SHRINKING_SUPPLY", r.flags)
        self.assertNotIn("FAST_FILLING", r.flags)


# ---------------------------------------------------------------------------
# 18. INSUFFICIENT_DATA path
# ---------------------------------------------------------------------------

class TestInsufficientData(unittest.TestCase):

    def test_nan_supply_insufficient(self):
        r = make_report(current_total_supply_usd=float("nan"))
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_inf_cap_insufficient(self):
        r = make_report(supply_cap_usd=float("inf"))
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_nan_deposit_insufficient(self):
        r = make_report(intended_deposit_usd=float("nan"))
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_insufficient_grade_f(self):
        r = make_report(current_total_supply_usd=float("nan"))
        self.assertEqual(r.grade, "F")

    def test_insufficient_advisory(self):
        r = make_report(current_total_supply_usd=float("nan"))
        self.assertTrue(any("insufficient" in m.lower() for m in r.advisory))

    def test_insufficient_only_flag(self):
        r = make_report(current_total_supply_usd=float("nan"))
        self.assertEqual(r.flags, ["INSUFFICIENT_DATA"])

    def test_insufficient_score_zero(self):
        r = make_report(current_total_supply_usd=float("nan"))
        self.assertAlmostEqual(r.cap_proximity_score, 0.0, places=4)

    def test_nan_growth_insufficient(self):
        r = make_report(recent_supply_growth_usd_per_day=float("nan"))
        self.assertIn("INSUFFICIENT_DATA", r.flags)


# ---------------------------------------------------------------------------
# 19. Negative input clamping
# ---------------------------------------------------------------------------

class TestNegativeClamping(unittest.TestCase):

    def test_negative_supply_clamped(self):
        r = make_report(current_total_supply_usd=-50.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.current_total_supply_usd, 0.0, places=6)

    def test_negative_deposit_clamped(self):
        r = make_report(intended_deposit_usd=-100.0)
        self.assertAlmostEqual(r.intended_deposit_usd, 0.0, places=6)

    def test_negative_supply_full_headroom(self):
        r = make_report(current_total_supply_usd=-50.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.remaining_headroom_usd, 100.0, places=6)


# ---------------------------------------------------------------------------
# 20. Report field types
# ---------------------------------------------------------------------------

class TestReportFieldTypes(unittest.TestCase):

    def setUp(self):
        self.r = make_report(protocol_name="Aave V3")

    def test_protocol_name_stored(self):
        self.assertEqual(self.r.protocol_name, "Aave V3")

    def test_utilization_is_float(self):
        self.assertIsInstance(self.r.utilization_of_cap_pct, float)

    def test_headroom_is_float(self):
        self.assertIsInstance(self.r.remaining_headroom_usd, float)

    def test_score_is_float(self):
        self.assertIsInstance(self.r.cap_proximity_score, float)

    def test_label_is_str(self):
        self.assertIsInstance(self.r.proximity_label, str)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r.flags, list)

    def test_advisory_is_list(self):
        self.assertIsInstance(self.r.advisory, list)

    def test_advisory_not_empty(self):
        self.assertGreater(len(self.r.advisory), 0)

    def test_generated_at_non_empty(self):
        self.assertGreater(len(self.r.generated_at), 0)

    def test_apr_preserved(self):
        r = make_report(current_supply_apr_pct=5.5)
        self.assertAlmostEqual(r.current_supply_apr_pct, 5.5, places=6)


# ---------------------------------------------------------------------------
# 21. Advisory content
# ---------------------------------------------------------------------------

class TestAdvisoryMessages(unittest.TestCase):

    def test_protocol_name_in_advisory(self):
        r = make_report(protocol_name="MyMkt")
        self.assertTrue(any("MyMkt" in m for m in r.advisory))

    def test_label_in_advisory(self):
        r = make_report(current_total_supply_usd=30.0, supply_cap_usd=100.0)
        self.assertTrue(any("AMPLE_HEADROOM" in m for m in r.advisory))

    def test_at_cap_advisory(self):
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        self.assertTrue(any("blocked" in m.lower() or "FULL" in m for m in r.advisory))

    def test_does_not_fit_advisory(self):
        r = make_report(current_total_supply_usd=80.0, supply_cap_usd=100.0,
                        intended_deposit_usd=50.0)
        self.assertTrue(any("not fit" in m.lower() or "NOT fit" in m for m in r.advisory))

    def test_cap_soon_advisory(self):
        r = make_report(current_total_supply_usd=95.0, supply_cap_usd=100.0,
                        recent_supply_growth_usd_per_day=1.0)
        self.assertTrue(any("days" in m.lower() for m in r.advisory))

    def test_shrinking_advisory(self):
        r = make_report(recent_supply_growth_usd_per_day=-100.0)
        self.assertTrue(any("shrinking" in m.lower() for m in r.advisory))

    def test_compression_advisory(self):
        r = make_report(current_total_supply_usd=96.0, supply_cap_usd=100.0)
        self.assertTrue(any("compression" in m.lower() or "crowded" in m.lower()
                            for m in r.advisory))


# ---------------------------------------------------------------------------
# 22. Persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _temp_file(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        return Path(tmp.name)

    def test_save_creates_file(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertTrue(tf.exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_valid_json(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            with open(tf) as f:
                self.assertIsInstance(json.load(f), list)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_one_entry(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertEqual(len(json.loads(tf.read_text())), 1)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_accumulates(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(7):
                ana.save_report(make_report(), data_file=tf)
            self.assertEqual(len(json.loads(tf.read_text())), 7)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_cap(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(MAX_ENTRIES + 15):
                ana.save_report(make_report(), data_file=tf)
            self.assertEqual(len(json.loads(tf.read_text())), MAX_ENTRIES)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_keeps_recent(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            for i in range(MAX_ENTRIES + 3):
                ana.save_report(make_report(protocol_name=f"M{i}"), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(data[-1]["protocol_name"], f"M{MAX_ENTRIES + 2}")
        finally:
            tf.unlink(missing_ok=True)

    def test_load_missing(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        self.assertEqual(ana.load_history(Path("/nonexistent/x.json")), [])

    def test_load_corrupt(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            tf.write_text("garbage")
            self.assertEqual(ana.load_history(tf), [])
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_keys(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            entry = json.loads(tf.read_text())[0]
            for key in ("timestamp", "protocol_name", "utilization_of_cap_pct",
                        "cap_proximity_score", "proximity_label", "grade",
                        "deposit_fits", "days_until_cap_reached"):
                self.assertIn(key, entry)
        finally:
            tf.unlink(missing_ok=True)

    def test_atomic_no_tmp(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertFalse(tf.with_suffix(".tmp").exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_creates_parent_dirs(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "x" / "y" / "out.json"
            ana.save_report(make_report(), data_file=nested)
            self.assertTrue(nested.exists())

    def test_entry_flags_list(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertIsInstance(json.loads(tf.read_text())[0]["flags"], list)
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_label_matches(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        r = make_report(current_total_supply_usd=100.0, supply_cap_usd=100.0)
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            self.assertEqual(json.loads(tf.read_text())[0]["proximity_label"],
                             r.proximity_label)
        finally:
            tf.unlink(missing_ok=True)

    def test_days_sentinel_serialises(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        r = make_report(recent_supply_growth_usd_per_day=0.0)
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertTrue(math.isfinite(data[0]["days_until_cap_reached"]))
        finally:
            tf.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 23. analyze_portfolio
# ---------------------------------------------------------------------------

class TestPortfolio(unittest.TestCase):

    def setUp(self):
        self.ana = DeFiProtocolSupplyCapProximityAnalyzer()

    def test_empty(self):
        s = self.ana.analyze_portfolio([])
        self.assertEqual(s["count"], 0)

    def test_empty_none_markets(self):
        s = self.ana.analyze_portfolio([])
        self.assertIsNone(s["most_constrained_market"])

    def test_count(self):
        s = self.ana.analyze_portfolio([make_market(), make_market()])
        self.assertEqual(s["count"], 2)

    def test_most_constrained(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=99.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0, protocol_name="Tight"),
            make_market(current_total_supply_usd=10.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0, protocol_name="Loose"),
        ])
        self.assertEqual(s["most_constrained_market"], "Tight")

    def test_least_constrained(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=99.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0, protocol_name="Tight"),
            make_market(current_total_supply_usd=10.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0, protocol_name="Loose"),
        ])
        self.assertEqual(s["least_constrained_market"], "Loose")

    def test_avg_score(self):
        s = self.ana.analyze_portfolio([make_market(), make_market()])
        self.assertIsInstance(s["avg_cap_proximity_score"], float)

    def test_at_cap_count(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=100.0, supply_cap_usd=100.0),
            make_market(current_total_supply_usd=10.0, supply_cap_usd=100.0),
        ])
        self.assertEqual(s["at_cap_count"], 1)

    def test_dont_fit_count(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=99.0, supply_cap_usd=100.0,
                        intended_deposit_usd=50.0),
            make_market(current_total_supply_usd=10.0, supply_cap_usd=100.0,
                        intended_deposit_usd=5.0),
        ])
        self.assertEqual(s["deposits_that_dont_fit_count"], 1)

    def test_zero_at_cap(self):
        s = self.ana.analyze_portfolio([make_market()])
        self.assertEqual(s["at_cap_count"], 0)

    def test_zero_dont_fit(self):
        s = self.ana.analyze_portfolio([make_market(intended_deposit_usd=1.0)])
        self.assertEqual(s["deposits_that_dont_fit_count"], 0)

    def test_portfolio_with_uncapped(self):
        s = self.ana.analyze_portfolio([
            make_market(supply_cap_usd=0.0, protocol_name="Unc"),
            make_market(current_total_supply_usd=99.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0, protocol_name="Tight"),
        ])
        self.assertEqual(s["least_constrained_market"], "Unc")

    def test_portfolio_with_insufficient(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=float("nan")),
            make_market(current_total_supply_usd=10.0, supply_cap_usd=100.0,
                        protocol_name="Good"),
        ])
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["least_constrained_market"], "Good")

    def test_portfolio_all_insufficient(self):
        s = self.ana.analyze_portfolio([
            make_market(current_total_supply_usd=float("nan")),
        ])
        self.assertIsNone(s["most_constrained_market"])


# ---------------------------------------------------------------------------
# 24. Stateless
# ---------------------------------------------------------------------------

class TestStateless(unittest.TestCase):

    def test_two_calls_independent(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        r1 = ana.analyze(10.0, 100.0, 1.0, 4.0, 0.0, "A")
        r2 = ana.analyze(99.0, 100.0, 1.0, 4.0, 0.0, "B")
        self.assertEqual(r1.proximity_label, "AMPLE_HEADROOM")
        self.assertEqual(r2.proximity_label, "NEAR_CAP")

    def test_repeated_same_result(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        r1 = ana.analyze(80.0, 100.0, 10.0, 4.0, 1.0, "X")
        r2 = ana.analyze(80.0, 100.0, 10.0, 4.0, 1.0, "X")
        self.assertEqual(r1.proximity_label, r2.proximity_label)
        self.assertAlmostEqual(r1.cap_proximity_score, r2.cap_proximity_score, places=8)

    def test_apr_does_not_affect_label(self):
        ana = DeFiProtocolSupplyCapProximityAnalyzer()
        r1 = ana.analyze(70.0, 100.0, 1.0, 1.0, 0.0, "P")
        r2 = ana.analyze(70.0, 100.0, 1.0, 99.0, 0.0, "P")
        self.assertEqual(r1.proximity_label, r2.proximity_label)


# ---------------------------------------------------------------------------
# 25. Known scenarios
# ---------------------------------------------------------------------------

class TestKnownScenarios(unittest.TestCase):

    def test_wsteth_near_full(self):
        r = make_report(current_total_supply_usd=88_000_000.0,
                        supply_cap_usd=100_000_000.0,
                        intended_deposit_usd=5_000_000.0,
                        recent_supply_growth_usd_per_day=1_500_000.0,
                        protocol_name="Aave V3 wstETH")
        self.assertEqual(r.proximity_label, "APPROACHING_CAP")
        self.assertTrue(r.deposit_fits)

    def test_fresh_market_ample(self):
        r = make_report(current_total_supply_usd=2_000_000.0,
                        supply_cap_usd=100_000_000.0,
                        intended_deposit_usd=1_000_000.0,
                        protocol_name="New Market")
        self.assertEqual(r.proximity_label, "AMPLE_HEADROOM")
        self.assertEqual(r.grade, "A")

    def test_full_market_blocks(self):
        r = make_report(current_total_supply_usd=100_000_000.0,
                        supply_cap_usd=100_000_000.0,
                        intended_deposit_usd=1_000_000.0)
        self.assertFalse(r.deposit_fits)
        self.assertIn("AT_CAP", r.flags)

    def test_big_deposit_partial_fit(self):
        r = make_report(current_total_supply_usd=95_000_000.0,
                        supply_cap_usd=100_000_000.0,
                        intended_deposit_usd=10_000_000.0)
        self.assertFalse(r.deposit_fits)
        self.assertAlmostEqual(r.fillable_pct_of_deposit, 50.0, places=4)

    def test_shrinking_market_easing(self):
        r = make_report(current_total_supply_usd=99_000_000.0,
                        supply_cap_usd=100_000_000.0,
                        intended_deposit_usd=500_000.0,
                        recent_supply_growth_usd_per_day=-2_000_000.0)
        self.assertIn("SHRINKING_SUPPLY", r.flags)
        self.assertNotIn("CAP_REACHED_SOON", r.flags)


# ---------------------------------------------------------------------------
# 26. Numerical edge cases
# ---------------------------------------------------------------------------

class TestNumericalEdge(unittest.TestCase):

    def test_tiny_cap(self):
        r = make_report(current_total_supply_usd=0.5, supply_cap_usd=1.0,
                        intended_deposit_usd=0.1)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 50.0, places=6)

    def test_huge_cap(self):
        r = make_report(current_total_supply_usd=1e9, supply_cap_usd=1e12,
                        intended_deposit_usd=1e6)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 0.1, places=6)

    def test_supply_exactly_zero(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=100.0)
        self.assertAlmostEqual(r.utilization_of_cap_pct, 0.0, places=6)

    def test_score_clamped_high(self):
        r = make_report(current_total_supply_usd=0.0, supply_cap_usd=1e9,
                        intended_deposit_usd=1.0,
                        recent_supply_growth_usd_per_day=0.0)
        self.assertLessEqual(r.cap_proximity_score, 100.0)

    def test_over_cap_score_low(self):
        r = make_report(current_total_supply_usd=200.0, supply_cap_usd=100.0,
                        intended_deposit_usd=1.0)
        self.assertLessEqual(r.cap_proximity_score, 30.0)


# ---------------------------------------------------------------------------
# 27. Rounding / determinism
# ---------------------------------------------------------------------------

class TestRounding(unittest.TestCase):

    def test_utilization_rounded(self):
        r = make_report(current_total_supply_usd=33.333333333,
                        supply_cap_usd=99.999999999)
        self.assertIsInstance(r.utilization_of_cap_pct, float)

    def test_score_finite(self):
        r = make_report()
        self.assertTrue(math.isfinite(r.cap_proximity_score))

    def test_headroom_rounded(self):
        r = make_report(current_total_supply_usd=12.3456789,
                        supply_cap_usd=100.0)
        self.assertIsInstance(r.remaining_headroom_usd, float)


if __name__ == "__main__":
    unittest.main()
