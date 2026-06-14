"""
Tests for MP-1091 ProtocolDeFiDebtCeilingProximityAnalyzer.

Run with:  python3 -m unittest spa_core.tests.test_protocol_defi_debt_ceiling_proximity_analyzer -v
Target: ≥110 tests, all passing.
Framework: unittest (stdlib only).
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Make sure project root is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.protocol_defi_debt_ceiling_proximity_analyzer import (
    LABEL_AMPLE_CAPACITY,
    LABEL_AT_CEILING,
    LABEL_CEILING_BREACHED,
    LABEL_FILLING_UP,
    LABEL_NEAR_CEILING,
    LOG_RING_CAP,
    ProtocolDeFiDebtCeilingProximityAnalyzer,
    _append_to_log,
)


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------

def make_analyzer(
    current_debt_usd=1_000_000.0,
    debt_ceiling_usd=10_000_000.0,
    current_supply_usd=2_000_000.0,
    supply_cap_usd=20_000_000.0,
    my_position_usd=0.0,
    daily_debt_growth_rate_pct=0.5,
    protocol_name="TestProtocol",
):
    return ProtocolDeFiDebtCeilingProximityAnalyzer(
        current_debt_usd=current_debt_usd,
        debt_ceiling_usd=debt_ceiling_usd,
        current_supply_usd=current_supply_usd,
        supply_cap_usd=supply_cap_usd,
        my_position_usd=my_position_usd,
        daily_debt_growth_rate_pct=daily_debt_growth_rate_pct,
        protocol_name=protocol_name,
    )


# ===========================================================================
# 1. Construction & attribute tests
# ===========================================================================

class TestConstruction(unittest.TestCase):

    def test_stores_current_debt(self):
        a = make_analyzer(current_debt_usd=500_000.0)
        self.assertAlmostEqual(a.current_debt_usd, 500_000.0)

    def test_stores_debt_ceiling(self):
        a = make_analyzer(debt_ceiling_usd=5_000_000.0)
        self.assertAlmostEqual(a.debt_ceiling_usd, 5_000_000.0)

    def test_stores_current_supply(self):
        a = make_analyzer(current_supply_usd=3_000_000.0)
        self.assertAlmostEqual(a.current_supply_usd, 3_000_000.0)

    def test_stores_supply_cap(self):
        a = make_analyzer(supply_cap_usd=15_000_000.0)
        self.assertAlmostEqual(a.supply_cap_usd, 15_000_000.0)

    def test_stores_my_position(self):
        a = make_analyzer(my_position_usd=50_000.0)
        self.assertAlmostEqual(a.my_position_usd, 50_000.0)

    def test_stores_daily_growth_rate(self):
        a = make_analyzer(daily_debt_growth_rate_pct=1.5)
        self.assertAlmostEqual(a.daily_debt_growth_rate_pct, 1.5)

    def test_stores_protocol_name(self):
        a = make_analyzer(protocol_name="AaveV3")
        self.assertEqual(a.protocol_name, "AaveV3")

    def test_current_debt_coerced_to_float(self):
        a = make_analyzer(current_debt_usd=1000)
        self.assertIsInstance(a.current_debt_usd, float)

    def test_debt_ceiling_coerced_to_float(self):
        a = make_analyzer(debt_ceiling_usd=10000)
        self.assertIsInstance(a.debt_ceiling_usd, float)

    def test_my_position_zero_by_default(self):
        a = make_analyzer(my_position_usd=0.0)
        self.assertAlmostEqual(a.my_position_usd, 0.0)

    def test_protocol_name_coerced_to_str(self):
        a = make_analyzer(protocol_name=123)
        self.assertIsInstance(a.protocol_name, str)

    def test_growth_rate_coerced_to_float(self):
        a = make_analyzer(daily_debt_growth_rate_pct=1)
        self.assertIsInstance(a.daily_debt_growth_rate_pct, float)

    def test_zero_debt(self):
        a = make_analyzer(current_debt_usd=0.0)
        self.assertAlmostEqual(a.current_debt_usd, 0.0)

    def test_zero_growth_rate(self):
        a = make_analyzer(daily_debt_growth_rate_pct=0.0)
        self.assertAlmostEqual(a.daily_debt_growth_rate_pct, 0.0)


# ===========================================================================
# 2. Debt utilization
# ===========================================================================

class TestDebtUtilization(unittest.TestCase):

    def test_debt_utilization_formula(self):
        a = make_analyzer(current_debt_usd=4_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 40.0, places=3)

    def test_debt_utilization_zero_debt(self):
        a = make_analyzer(current_debt_usd=0.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 0.0, places=5)

    def test_debt_utilization_at_ceiling(self):
        a = make_analyzer(current_debt_usd=10_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 100.0, places=3)

    def test_debt_utilization_over_ceiling(self):
        a = make_analyzer(current_debt_usd=11_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertGreater(r["debt_utilization_pct"], 100.0)

    def test_debt_utilization_50_pct(self):
        a = make_analyzer(current_debt_usd=5_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 50.0, places=3)

    def test_debt_utilization_zero_ceiling_with_debt(self):
        a = make_analyzer(current_debt_usd=100.0, debt_ceiling_usd=0.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 100.0, places=3)

    def test_debt_utilization_zero_ceiling_zero_debt(self):
        a = make_analyzer(current_debt_usd=0.0, debt_ceiling_usd=0.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 0.0, places=3)

    def test_debt_utilization_is_float(self):
        r = make_analyzer().analyze()
        self.assertIsInstance(r["debt_utilization_pct"], float)

    def test_debt_utilization_small(self):
        a = make_analyzer(current_debt_usd=100.0, debt_ceiling_usd=1_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_utilization_pct"], 0.01, places=4)


# ===========================================================================
# 3. Supply utilization
# ===========================================================================

class TestSupplyUtilization(unittest.TestCase):

    def test_supply_utilization_formula(self):
        a = make_analyzer(current_supply_usd=6_000_000.0, supply_cap_usd=20_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["supply_utilization_pct"], 30.0, places=3)

    def test_supply_utilization_zero_supply(self):
        a = make_analyzer(current_supply_usd=0.0, supply_cap_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["supply_utilization_pct"], 0.0, places=5)

    def test_supply_utilization_at_cap(self):
        a = make_analyzer(current_supply_usd=10_000_000.0, supply_cap_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["supply_utilization_pct"], 100.0, places=3)

    def test_supply_utilization_over_cap(self):
        a = make_analyzer(current_supply_usd=12_000_000.0, supply_cap_usd=10_000_000.0)
        r = a.analyze()
        self.assertGreater(r["supply_utilization_pct"], 100.0)

    def test_supply_utilization_50_pct(self):
        a = make_analyzer(current_supply_usd=5_000_000.0, supply_cap_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["supply_utilization_pct"], 50.0, places=3)

    def test_supply_utilization_zero_cap_with_supply(self):
        a = make_analyzer(current_supply_usd=100.0, supply_cap_usd=0.0)
        r = a.analyze()
        self.assertAlmostEqual(r["supply_utilization_pct"], 100.0, places=3)

    def test_supply_utilization_is_float(self):
        r = make_analyzer().analyze()
        self.assertIsInstance(r["supply_utilization_pct"], float)


# ===========================================================================
# 4. Headroom
# ===========================================================================

class TestHeadroom(unittest.TestCase):

    def test_headroom_formula(self):
        a = make_analyzer(current_debt_usd=3_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["headroom_usd"], 7_000_000.0, places=1)

    def test_headroom_zero_when_at_ceiling(self):
        a = make_analyzer(current_debt_usd=10_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["headroom_usd"], 0.0, places=1)

    def test_headroom_negative_when_breached(self):
        a = make_analyzer(current_debt_usd=11_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertLess(r["headroom_usd"], 0.0)

    def test_headroom_equals_ceiling_when_no_debt(self):
        a = make_analyzer(current_debt_usd=0.0, debt_ceiling_usd=5_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["headroom_usd"], 5_000_000.0, places=1)

    def test_headroom_is_float(self):
        r = make_analyzer().analyze()
        self.assertIsInstance(r["headroom_usd"], float)

    def test_headroom_large_ceiling(self):
        a = make_analyzer(current_debt_usd=1_000.0, debt_ceiling_usd=1_000_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["headroom_usd"], 999_999_000.0, places=0)


# ===========================================================================
# 5. Days to ceiling
# ===========================================================================

class TestDaysToCeiling(unittest.TestCase):

    def test_days_to_ceiling_formula(self):
        # headroom = 9M, debt = 1M, growth = 1%/day → daily_growth = 10k
        # days = 9M / 10k = 900
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=1.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 900.0, places=1)

    def test_days_to_ceiling_zero_growth_is_none(self):
        a = make_analyzer(daily_debt_growth_rate_pct=0.0)
        r = a.analyze()
        self.assertIsNone(r["days_to_debt_ceiling"])

    def test_days_to_ceiling_negative_growth_is_none(self):
        a = make_analyzer(daily_debt_growth_rate_pct=-1.0)
        r = a.analyze()
        self.assertIsNone(r["days_to_debt_ceiling"])

    def test_days_to_ceiling_zero_when_already_breached(self):
        a = make_analyzer(
            current_debt_usd=11_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=1.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 0.0, places=3)

    def test_days_to_ceiling_very_fast_growth(self):
        # headroom = 5M, debt = 1M, growth = 10%/day → daily=100k → 50 days
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=6_000_000.0,
            daily_debt_growth_rate_pct=10.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 50.0, places=1)

    def test_days_to_ceiling_slow_growth(self):
        # headroom = 9M, debt = 1M, growth = 0.01%/day → daily_growth = 100 USD → 90000 days
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=0.01,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 90_000.0, places=0)

    def test_days_to_ceiling_zero_debt_is_none(self):
        a = make_analyzer(
            current_debt_usd=0.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=1.0,
        )
        r = a.analyze()
        # zero debt → daily_growth = 0 → inf → None
        self.assertIsNone(r["days_to_debt_ceiling"])

    def test_days_to_ceiling_numeric_or_none(self):
        for rate in [-1.0, 0.0, 0.5, 1.0, 10.0]:
            a = make_analyzer(daily_debt_growth_rate_pct=rate)
            r = a.analyze()
            val = r["days_to_debt_ceiling"]
            self.assertTrue(val is None or isinstance(val, (int, float)))

    def test_days_to_ceiling_at_exact_ceiling(self):
        # debt == ceiling → headroom = 0 → 0 days
        a = make_analyzer(
            current_debt_usd=10_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=1.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 0.0, places=3)


# ===========================================================================
# 6. Capacity label
# ===========================================================================

class TestCapacityLabel(unittest.TestCase):

    # --- AMPLE_CAPACITY (<50%) ----------------------------------------------

    def test_ample_capacity_low_debt(self):
        # 10 % utilization
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=2_000_000.0,
            supply_cap_usd=20_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AMPLE_CAPACITY)

    def test_ample_capacity_zero_utilization(self):
        a = make_analyzer(
            current_debt_usd=0.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AMPLE_CAPACITY)

    def test_ample_capacity_just_below_50(self):
        a = make_analyzer(
            current_debt_usd=4_999_999.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AMPLE_CAPACITY)

    # --- FILLING_UP (50–75%) ------------------------------------------------

    def test_filling_up_50_pct(self):
        a = make_analyzer(
            current_debt_usd=5_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_FILLING_UP)

    def test_filling_up_60_pct(self):
        a = make_analyzer(
            current_debt_usd=6_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_FILLING_UP)

    def test_filling_up_just_below_75(self):
        a = make_analyzer(
            current_debt_usd=7_499_999.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_FILLING_UP)

    # --- NEAR_CEILING (75–90%) ----------------------------------------------

    def test_near_ceiling_75_pct(self):
        a = make_analyzer(
            current_debt_usd=7_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    def test_near_ceiling_80_pct(self):
        a = make_analyzer(
            current_debt_usd=8_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    def test_near_ceiling_just_below_90(self):
        a = make_analyzer(
            current_debt_usd=8_999_999.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    # --- AT_CEILING (90–99.x%) ----------------------------------------------

    def test_at_ceiling_90_pct(self):
        a = make_analyzer(
            current_debt_usd=9_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AT_CEILING)

    def test_at_ceiling_95_pct(self):
        a = make_analyzer(
            current_debt_usd=9_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AT_CEILING)

    def test_at_ceiling_just_below_100(self):
        a = make_analyzer(
            current_debt_usd=9_999_999.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AT_CEILING)

    # --- CEILING_BREACHED (>=100%) ------------------------------------------

    def test_ceiling_breached_exactly_100(self):
        a = make_analyzer(
            current_debt_usd=10_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_CEILING_BREACHED)

    def test_ceiling_breached_over_100(self):
        a = make_analyzer(
            current_debt_usd=11_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_CEILING_BREACHED)

    def test_ceiling_breached_supply_over_cap(self):
        # Supply breaches cap even if debt is fine
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=11_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_CEILING_BREACHED)

    # --- Label driven by MAX of debt/supply --------------------------------

    def test_label_driven_by_supply_when_higher(self):
        # debt util = 10%, supply util = 80% → NEAR_CEILING from supply
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=8_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    def test_label_driven_by_debt_when_higher(self):
        # debt util = 80%, supply util = 10% → NEAR_CEILING from debt
        a = make_analyzer(
            current_debt_usd=8_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=1_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    def test_all_labels_valid_strings(self):
        valid = {
            LABEL_AMPLE_CAPACITY, LABEL_FILLING_UP, LABEL_NEAR_CEILING,
            LABEL_AT_CEILING, LABEL_CEILING_BREACHED,
        }
        configs = [
            (100_000, 10_000_000, 0, 10_000_000),
            (5_000_000, 10_000_000, 0, 10_000_000),
            (7_500_000, 10_000_000, 0, 10_000_000),
            (9_000_000, 10_000_000, 0, 10_000_000),
            (10_000_000, 10_000_000, 0, 10_000_000),
            (12_000_000, 10_000_000, 0, 10_000_000),
        ]
        for debt, ceiling, supply, cap in configs:
            a = make_analyzer(
                current_debt_usd=debt, debt_ceiling_usd=ceiling,
                current_supply_usd=supply, supply_cap_usd=cap,
            )
            r = a.analyze()
            self.assertIn(r["capacity_label"], valid)


# ===========================================================================
# 7. Capacity risk score
# ===========================================================================

class TestCapacityRiskScore(unittest.TestCase):

    def test_score_in_range_0_100(self):
        configs = [
            (0.0, 10_000_000.0),
            (5_000_000.0, 10_000_000.0),
            (9_500_000.0, 10_000_000.0),
            (10_000_000.0, 10_000_000.0),
            (12_000_000.0, 10_000_000.0),
        ]
        for debt, ceiling in configs:
            a = make_analyzer(current_debt_usd=debt, debt_ceiling_usd=ceiling)
            r = a.analyze()
            self.assertGreaterEqual(r["capacity_risk_score"], 0)
            self.assertLessEqual(r["capacity_risk_score"], 100)

    def test_score_is_integer(self):
        r = make_analyzer().analyze()
        self.assertIsInstance(r["capacity_risk_score"], int)

    def test_score_zero_at_zero_utilization(self):
        a = make_analyzer(current_debt_usd=0.0, current_supply_usd=0.0)
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 0)

    def test_score_100_at_ceiling(self):
        a = make_analyzer(
            current_debt_usd=10_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 100)

    def test_score_100_above_ceiling(self):
        a = make_analyzer(
            current_debt_usd=12_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 100)

    def test_score_increases_with_utilization(self):
        debts = [1_000_000, 3_000_000, 5_000_000, 8_000_000, 10_000_000]
        scores = []
        for d in debts:
            a = make_analyzer(
                current_debt_usd=d,
                debt_ceiling_usd=10_000_000.0,
                current_supply_usd=0.0,
                supply_cap_usd=100_000_000.0,
            )
            scores.append(a.analyze()["capacity_risk_score"])
        for i in range(1, len(scores)):
            self.assertGreaterEqual(scores[i], scores[i - 1])

    def test_score_50_at_50_pct(self):
        a = make_analyzer(
            current_debt_usd=5_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 50)

    def test_score_driven_by_highest_utilization(self):
        # Supply at 80%, debt at 10% → score based on 80%
        a = make_analyzer(
            current_debt_usd=1_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=8_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 80)


# ===========================================================================
# 8. Return dictionary structure
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    REQUIRED_KEYS = [
        "protocol_name",
        "current_debt_usd",
        "debt_ceiling_usd",
        "current_supply_usd",
        "supply_cap_usd",
        "my_position_usd",
        "daily_debt_growth_rate_pct",
        "debt_utilization_pct",
        "supply_utilization_pct",
        "days_to_debt_ceiling",
        "headroom_usd",
        "capacity_risk_score",
        "capacity_label",
        "timestamp_utc",
    ]

    def setUp(self):
        self.result = make_analyzer().analyze()

    def test_all_required_keys_present(self):
        for key in self.REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.result)

    def test_protocol_name_echoed(self):
        a = make_analyzer(protocol_name="Compound")
        r = a.analyze()
        self.assertEqual(r["protocol_name"], "Compound")

    def test_debt_ceiling_echoed(self):
        a = make_analyzer(debt_ceiling_usd=7_500_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["debt_ceiling_usd"], 7_500_000.0, places=1)

    def test_my_position_echoed(self):
        a = make_analyzer(my_position_usd=100_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["my_position_usd"], 100_000.0, places=1)

    def test_timestamp_is_recent(self):
        now = int(time.time())
        r = make_analyzer().analyze()
        self.assertAlmostEqual(r["timestamp_utc"], now, delta=5)

    def test_debt_utilization_is_float(self):
        self.assertIsInstance(self.result["debt_utilization_pct"], float)

    def test_supply_utilization_is_float(self):
        self.assertIsInstance(self.result["supply_utilization_pct"], float)

    def test_headroom_is_float(self):
        self.assertIsInstance(self.result["headroom_usd"], float)

    def test_capacity_risk_score_is_int(self):
        self.assertIsInstance(self.result["capacity_risk_score"], int)

    def test_capacity_label_is_str(self):
        self.assertIsInstance(self.result["capacity_label"], str)

    def test_result_is_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_json_serializable(self):
        r = make_analyzer().analyze()
        try:
            json.dumps(r)
        except (TypeError, ValueError) as e:
            self.fail(f"Result is not JSON-serializable: {e}")

    def test_no_missing_keys(self):
        missing = set(self.REQUIRED_KEYS) - set(self.result.keys())
        self.assertEqual(missing, set())


# ===========================================================================
# 9. Ring-buffer log helpers
# ===========================================================================

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_append_creates_file(self):
        _append_to_log({"x": 1}, self.tmp)
        self.assertTrue(os.path.exists(self.tmp))

    def test_append_valid_json(self):
        _append_to_log({"x": 1}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_append_single_entry(self):
        _append_to_log({"key": "val"}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_append_multiple_entries(self):
        for i in range(5):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(LOG_RING_CAP + 20):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), LOG_RING_CAP)

    def test_ring_buffer_keeps_newest(self):
        for i in range(LOG_RING_CAP + 10):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["i"], LOG_RING_CAP + 9)

    def test_ring_buffer_oldest_dropped(self):
        for i in range(LOG_RING_CAP + 5):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["i"], 5)

    def test_log_cap_constant_is_100(self):
        self.assertEqual(LOG_RING_CAP, 100)

    def test_analyze_and_log_writes_entry(self):
        a = make_analyzer()
        a.analyze_and_log(log_path=self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_analyze_and_log_returns_result(self):
        a = make_analyzer()
        r = a.analyze_and_log(log_path=self.tmp)
        self.assertIn("capacity_label", r)

    def test_log_entry_contains_required_keys(self):
        a = make_analyzer()
        a.analyze_and_log(log_path=self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIn("capacity_label", data[0])
        self.assertIn("headroom_usd", data[0])

    def test_append_recovers_from_corrupt_file(self):
        with open(self.tmp, "w") as fh:
            fh.write("INVALID_JSON{{{{")
        _append_to_log({"recovered": True}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["recovered"], True)

    def test_append_recovers_from_non_list_json(self):
        with open(self.tmp, "w") as fh:
            json.dump({"oops": "not a list"}, fh)
        _append_to_log({"i": 0}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_multiple_analyze_and_log_accumulate(self):
        a = make_analyzer()
        for _ in range(3):
            a.analyze_and_log(log_path=self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)


# ===========================================================================
# 10. Label constants
# ===========================================================================

class TestLabelConstants(unittest.TestCase):

    def test_ample_capacity_constant(self):
        self.assertEqual(LABEL_AMPLE_CAPACITY, "AMPLE_CAPACITY")

    def test_filling_up_constant(self):
        self.assertEqual(LABEL_FILLING_UP, "FILLING_UP")

    def test_near_ceiling_constant(self):
        self.assertEqual(LABEL_NEAR_CEILING, "NEAR_CEILING")

    def test_at_ceiling_constant(self):
        self.assertEqual(LABEL_AT_CEILING, "AT_CEILING")

    def test_ceiling_breached_constant(self):
        self.assertEqual(LABEL_CEILING_BREACHED, "CEILING_BREACHED")

    def test_all_constants_are_strings(self):
        for lbl in [
            LABEL_AMPLE_CAPACITY, LABEL_FILLING_UP, LABEL_NEAR_CEILING,
            LABEL_AT_CEILING, LABEL_CEILING_BREACHED,
        ]:
            self.assertIsInstance(lbl, str)

    def test_all_constants_are_unique(self):
        labels = [
            LABEL_AMPLE_CAPACITY, LABEL_FILLING_UP, LABEL_NEAR_CEILING,
            LABEL_AT_CEILING, LABEL_CEILING_BREACHED,
        ]
        self.assertEqual(len(labels), len(set(labels)))


# ===========================================================================
# 11. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_very_small_debt_ample(self):
        a = make_analyzer(current_debt_usd=1.0, debt_ceiling_usd=1_000_000_000.0)
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AMPLE_CAPACITY)

    def test_equal_debt_and_ceiling_breached(self):
        a = make_analyzer(
            current_debt_usd=100_000.0,
            debt_ceiling_usd=100_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_CEILING_BREACHED)

    def test_large_position_echoed(self):
        a = make_analyzer(my_position_usd=5_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["my_position_usd"], 5_000_000.0, places=1)

    def test_zero_my_position_echoed(self):
        a = make_analyzer(my_position_usd=0.0)
        r = a.analyze()
        self.assertAlmostEqual(r["my_position_usd"], 0.0, places=1)

    def test_analyze_twice_same_result(self):
        a = make_analyzer()
        r1 = a.analyze()
        r2 = a.analyze()
        self.assertAlmostEqual(r1["debt_utilization_pct"], r2["debt_utilization_pct"], places=6)

    def test_protocol_name_with_spaces(self):
        a = make_analyzer(protocol_name="Aave V3 Ethereum")
        r = a.analyze()
        self.assertEqual(r["protocol_name"], "Aave V3 Ethereum")

    def test_very_high_growth_rate_fast_ceiling(self):
        a = make_analyzer(
            current_debt_usd=9_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            daily_debt_growth_rate_pct=100.0,
        )
        r = a.analyze()
        # headroom = 1M, daily_growth = 9M*100%/100 = 9M → days = 1M/9M ≈ 0.1111
        # module rounds to 2 decimal places → 0.11
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 0.11, places=2)

    def test_result_dict_not_empty(self):
        r = make_analyzer().analyze()
        self.assertGreater(len(r), 0)

    def test_headroom_negative_breach(self):
        a = make_analyzer(current_debt_usd=15_000_000.0, debt_ceiling_usd=10_000_000.0)
        r = a.analyze()
        self.assertAlmostEqual(r["headroom_usd"], -5_000_000.0, places=1)

    def test_supply_utilization_independent_of_debt(self):
        a1 = make_analyzer(
            current_debt_usd=1_000_000.0,
            current_supply_usd=9_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        a2 = make_analyzer(
            current_debt_usd=9_000_000.0,
            current_supply_usd=9_000_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r1 = a1.analyze()
        r2 = a2.analyze()
        self.assertAlmostEqual(r1["supply_utilization_pct"], r2["supply_utilization_pct"], places=3)

    def test_score_clipped_at_100_for_breach(self):
        a = make_analyzer(
            current_debt_usd=100_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 100)

    def test_days_to_ceiling_precise(self):
        # headroom=2M, debt=4M, rate=0.5% → daily=20k → 100 days
        a = make_analyzer(
            current_debt_usd=4_000_000.0,
            debt_ceiling_usd=6_000_000.0,
            daily_debt_growth_rate_pct=0.5,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 100.0, places=1)

    def test_different_protocols_independent(self):
        protocols = ["Aave", "Compound", "Morpho", "Euler", "Maple"]
        for p in protocols:
            a = make_analyzer(protocol_name=p)
            r = a.analyze()
            self.assertEqual(r["protocol_name"], p)

    def test_max_utilization_governs_label(self):
        # debt=40%, supply=92% → AT_CEILING (supply dominates)
        a = make_analyzer(
            current_debt_usd=4_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=9_200_000.0,
            supply_cap_usd=10_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AT_CEILING)

    def test_score_90_at_90_pct(self):
        a = make_analyzer(
            current_debt_usd=9_000_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 90)

    def test_score_75_at_75_pct(self):
        a = make_analyzer(
            current_debt_usd=7_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["capacity_risk_score"], 75)


# ===========================================================================
# 12. Scenario tests
# ===========================================================================

class TestScenarios(unittest.TestCase):

    def test_aave_v3_healthy_scenario(self):
        a = make_analyzer(
            current_debt_usd=100_000_000.0,
            debt_ceiling_usd=1_000_000_000.0,
            current_supply_usd=200_000_000.0,
            supply_cap_usd=2_000_000_000.0,
            my_position_usd=50_000.0,
            daily_debt_growth_rate_pct=0.3,
            protocol_name="Aave V3",
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AMPLE_CAPACITY)
        self.assertIsNotNone(r["days_to_debt_ceiling"])

    def test_compound_near_ceiling_scenario(self):
        a = make_analyzer(
            current_debt_usd=850_000_000.0,
            debt_ceiling_usd=1_000_000_000.0,
            current_supply_usd=500_000_000.0,
            supply_cap_usd=1_000_000_000.0,
            daily_debt_growth_rate_pct=0.5,
            protocol_name="Compound V3",
        )
        r = a.analyze()
        # max_util = max(85, 50) = 85 → NEAR_CEILING
        self.assertEqual(r["capacity_label"], LABEL_NEAR_CEILING)

    def test_morpho_at_ceiling_scenario(self):
        a = make_analyzer(
            current_debt_usd=9_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=1_000_000.0,
            supply_cap_usd=20_000_000.0,
            my_position_usd=100_000.0,
            daily_debt_growth_rate_pct=0.1,
            protocol_name="Morpho",
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_AT_CEILING)
        # days to ceiling: headroom=500k, debt=9.5M, rate=0.1% → daily=9.5k → ~52.6 days
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 500_000 / 9500.0, places=0)

    def test_ceiling_breached_scenario(self):
        a = make_analyzer(
            current_debt_usd=10_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
            daily_debt_growth_rate_pct=1.0,
            protocol_name="BorrowedTooMuch",
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_CEILING_BREACHED)
        self.assertAlmostEqual(r["days_to_debt_ceiling"], 0.0, places=3)
        self.assertEqual(r["capacity_risk_score"], 100)

    def test_filling_up_scenario(self):
        a = make_analyzer(
            current_debt_usd=6_500_000.0,
            debt_ceiling_usd=10_000_000.0,
            current_supply_usd=0.0,
            supply_cap_usd=100_000_000.0,
            daily_debt_growth_rate_pct=0.5,
            protocol_name="Euler V2",
        )
        r = a.analyze()
        self.assertEqual(r["capacity_label"], LABEL_FILLING_UP)

    def test_zero_growth_days_none(self):
        a = make_analyzer(daily_debt_growth_rate_pct=0.0)
        r = a.analyze()
        self.assertIsNone(r["days_to_debt_ceiling"])

    def test_large_position_does_not_affect_utilization(self):
        # my_position_usd is informational; doesn't change debt/supply calcs
        a1 = make_analyzer(my_position_usd=0.0)
        a2 = make_analyzer(my_position_usd=5_000_000.0)
        r1 = a1.analyze()
        r2 = a2.analyze()
        self.assertAlmostEqual(
            r1["debt_utilization_pct"], r2["debt_utilization_pct"], places=5
        )
        self.assertAlmostEqual(
            r1["supply_utilization_pct"], r2["supply_utilization_pct"], places=5
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
