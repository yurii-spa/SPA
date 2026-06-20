"""
Tests for MP-1113  ProtocolDeFiProtocolVersionMigrationRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_protocol_version_migration_risk_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

# Ensure repo root is on path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_defi_protocol_version_migration_risk_analyzer import (
    ProtocolDeFiProtocolVersionMigrationRiskAnalyzer,
    _compute_maturity_score,
    _compute_payback_days,
    _compute_net_gain,
    _recommend,
    _atomic_log,
    _LOG_CAP,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helper: minimal valid data dict
# ---------------------------------------------------------------------------

def _data(
    old_version_apy_pct=4.0,
    new_version_apy_pct=6.5,
    migration_cost_usd=200.0,
    new_version_audit_count=3,
    new_version_age_days=400,
    new_version_tvl_usd=80_000_000.0,
    old_version_tvl_usd=200_000_000.0,
    position_size_usd=50_000.0,
    holding_days=180,
    protocol_name="TestDEX",
):
    return {
        "old_version_apy_pct": old_version_apy_pct,
        "new_version_apy_pct": new_version_apy_pct,
        "migration_cost_usd": migration_cost_usd,
        "new_version_audit_count": new_version_audit_count,
        "new_version_age_days": new_version_age_days,
        "new_version_tvl_usd": new_version_tvl_usd,
        "old_version_tvl_usd": old_version_tvl_usd,
        "position_size_usd": position_size_usd,
        "holding_days": holding_days,
        "protocol_name": protocol_name,
    }


# ===========================================================================
# 1. Helpers — _compute_maturity_score
# ===========================================================================

class TestComputeMaturityScore(unittest.TestCase):

    def test_zero_everything_gives_zero(self):
        self.assertEqual(_compute_maturity_score(0, 0.0, 0), 0)

    def test_max_everything_gives_100(self):
        # age=365 → 40, tvl=100M → 30, audits=3 → 30 = 100
        self.assertEqual(_compute_maturity_score(365, 100_000_000.0, 3), 100)

    def test_over_max_clamps_to_100(self):
        self.assertEqual(_compute_maturity_score(1000, 500_000_000.0, 10), 100)

    def test_age_half_year_gives_20_pts(self):
        # 182/365 * 40 ≈ 19.9 → rounds to 20
        score = _compute_maturity_score(182, 0.0, 0)
        self.assertAlmostEqual(score, round(182 / 365 * 40), delta=1)

    def test_age_full_year_gives_40_pts(self):
        # Just age component
        score = _compute_maturity_score(365, 0.0, 0)
        self.assertEqual(score, 40)

    def test_age_over_year_capped_at_40(self):
        score = _compute_maturity_score(730, 0.0, 0)
        self.assertEqual(score, 40)

    def test_tvl_zero_gives_zero_tvl_pts(self):
        score = _compute_maturity_score(0, 0.0, 0)
        self.assertEqual(score, 0)

    def test_tvl_100m_gives_30_pts(self):
        # Only TVL component
        score = _compute_maturity_score(0, 100_000_000.0, 0)
        self.assertEqual(score, 30)

    def test_tvl_50m_gives_15_pts(self):
        # 50M/100M * 30 = 15
        score = _compute_maturity_score(0, 50_000_000.0, 0)
        self.assertEqual(score, 15)

    def test_tvl_over_100m_capped_at_30(self):
        score = _compute_maturity_score(0, 500_000_000.0, 0)
        self.assertEqual(score, 30)

    def test_audit_zero_gives_zero_audit_pts(self):
        score = _compute_maturity_score(0, 0.0, 0)
        self.assertEqual(score, 0)

    def test_audit_one_gives_10_pts(self):
        score = _compute_maturity_score(0, 0.0, 1)
        self.assertEqual(score, 10)

    def test_audit_two_gives_20_pts(self):
        score = _compute_maturity_score(0, 0.0, 2)
        self.assertEqual(score, 20)

    def test_audit_three_gives_30_pts(self):
        score = _compute_maturity_score(0, 0.0, 3)
        self.assertEqual(score, 30)

    def test_audit_four_capped_at_30(self):
        score = _compute_maturity_score(0, 0.0, 4)
        self.assertEqual(score, 30)

    def test_score_is_int(self):
        score = _compute_maturity_score(200, 50_000_000.0, 2)
        self.assertIsInstance(score, int)

    def test_combined_components(self):
        # age=180 days → min(40, round(180/365*40)) = min(40,20) = 20
        # tvl=50M → min(30, round(50M/100M*30)) = min(30,15) = 15
        # audits=2 → min(30, 20) = 20
        # total = 55
        score = _compute_maturity_score(180, 50_000_000.0, 2)
        expected = min(100, round(180/365*40) + round(50_000_000/100_000_000*30) + min(30, 2*10))
        self.assertEqual(score, expected)

    def test_negative_age_clamped(self):
        score = _compute_maturity_score(-100, 0.0, 0)
        self.assertEqual(score, 0)

    def test_negative_tvl_clamped(self):
        score = _compute_maturity_score(0, -1_000_000.0, 0)
        self.assertEqual(score, 0)

    def test_negative_audits_clamped(self):
        score = _compute_maturity_score(0, 0.0, -5)
        self.assertEqual(score, 0)


# ===========================================================================
# 2. Helpers — _compute_payback_days
# ===========================================================================

class TestComputePaybackDays(unittest.TestCase):

    def test_positive_improvement_and_position(self):
        # daily_gain = 50000 * 2.5/100/365 = 3.4247
        # payback = 100 / 3.4247 ≈ 29.2
        result = _compute_payback_days(100.0, 50_000.0, 2.5)
        expected = 100.0 / (50_000.0 * 2.5 / 100.0 / 365.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_zero_improvement_gives_inf(self):
        result = _compute_payback_days(100.0, 50_000.0, 0.0)
        self.assertTrue(math.isinf(result))

    def test_negative_improvement_gives_inf(self):
        result = _compute_payback_days(100.0, 50_000.0, -1.0)
        self.assertTrue(math.isinf(result))

    def test_zero_position_gives_inf(self):
        result = _compute_payback_days(100.0, 0.0, 2.0)
        self.assertTrue(math.isinf(result))

    def test_zero_migration_cost_gives_zero_payback(self):
        result = _compute_payback_days(0.0, 50_000.0, 2.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_large_cost_long_payback(self):
        result = _compute_payback_days(1_000_000.0, 100_000.0, 1.0)
        # daily_gain = 100000 * 0.01 / 365 = 2.7397
        # payback = 1M / 2.74 ≈ 365000
        expected = 1_000_000.0 / (100_000.0 * 1.0 / 100.0 / 365.0)
        self.assertAlmostEqual(result, expected, places=2)

    def test_payback_proportional_to_cost(self):
        p1 = _compute_payback_days(100.0, 50_000.0, 2.0)
        p2 = _compute_payback_days(200.0, 50_000.0, 2.0)
        self.assertAlmostEqual(p2, 2 * p1, places=6)

    def test_payback_inversely_proportional_to_position(self):
        p1 = _compute_payback_days(100.0, 50_000.0, 2.0)
        p2 = _compute_payback_days(100.0, 100_000.0, 2.0)
        self.assertAlmostEqual(p2, p1 / 2, places=6)


# ===========================================================================
# 3. Helpers — _compute_net_gain
# ===========================================================================

class TestComputeNetGain(unittest.TestCase):

    def test_basic_net_gain(self):
        # 50000 * 2.5/100/365 * 180 - 200 = 616.44 - 200 = 416.44
        result = _compute_net_gain(50_000.0, 2.5, 180, 200.0)
        expected = 50_000.0 * 2.5 / 100.0 / 365.0 * 180 - 200.0
        self.assertAlmostEqual(result, expected, places=4)

    def test_negative_net_gain_when_cost_exceeds_gain(self):
        result = _compute_net_gain(1_000.0, 0.5, 10, 500.0)
        self.assertLess(result, 0.0)

    def test_zero_apy_improvement_minus_cost(self):
        result = _compute_net_gain(50_000.0, 0.0, 180, 200.0)
        self.assertAlmostEqual(result, -200.0, places=6)

    def test_negative_apy_improvement(self):
        result = _compute_net_gain(50_000.0, -2.0, 180, 100.0)
        self.assertLess(result, 0.0)

    def test_zero_cost_net_gain_equals_gross(self):
        gross = 50_000.0 * 2.5 / 100.0 / 365.0 * 180
        result = _compute_net_gain(50_000.0, 2.5, 180, 0.0)
        self.assertAlmostEqual(result, gross, places=4)

    def test_zero_holding_days_only_subtracts_cost(self):
        result = _compute_net_gain(50_000.0, 5.0, 0, 300.0)
        self.assertAlmostEqual(result, -300.0, places=6)

    def test_net_gain_increases_with_holding_days(self):
        g1 = _compute_net_gain(50_000.0, 2.0, 30, 100.0)
        g2 = _compute_net_gain(50_000.0, 2.0, 365, 100.0)
        self.assertLess(g1, g2)

    def test_net_gain_scales_with_position_size(self):
        g1 = _compute_net_gain(10_000.0, 5.0, 365, 0.0)
        g2 = _compute_net_gain(20_000.0, 5.0, 365, 0.0)
        self.assertAlmostEqual(g2, 2 * g1, places=4)


# ===========================================================================
# 4. Helpers — _recommend
# ===========================================================================

class TestRecommend(unittest.TestCase):

    def test_stay_old_when_no_improvement(self):
        self.assertEqual(_recommend(-1.0, 100.0, 80, 10.0, 90), "STAY_OLD_VERSION")

    def test_stay_old_when_zero_improvement(self):
        self.assertEqual(_recommend(0.0, 0.0, 80, 0.0, 90), "STAY_OLD_VERSION")

    def test_migrate_now(self):
        # net>0, maturity>=70, payback < holding/2
        self.assertEqual(_recommend(2.5, 500.0, 75, 30.0, 180), "MIGRATE_NOW")

    def test_migrate_now_exactly_at_maturity_70(self):
        self.assertEqual(_recommend(2.5, 500.0, 70, 40.0, 180), "MIGRATE_NOW")

    def test_migrate_soon_maturity_50_60(self):
        # net>0, maturity=60, payback>=half → MIGRATE_SOON
        self.assertEqual(_recommend(2.5, 200.0, 60, 100.0, 180), "MIGRATE_SOON")

    def test_migrate_soon_maturity_exactly_50(self):
        self.assertEqual(_recommend(2.5, 200.0, 50, 100.0, 180), "MIGRATE_SOON")

    def test_wait_for_maturity_low_score(self):
        # net>0, maturity<50
        self.assertEqual(_recommend(2.5, 200.0, 40, 30.0, 180), "WAIT_FOR_MATURITY")

    def test_not_worth_it_net_negative_apy_positive(self):
        self.assertEqual(_recommend(1.0, -50.0, 80, 300.0, 180), "NOT_WORTH_IT")

    def test_not_worth_it_zero_net_apy_positive(self):
        self.assertEqual(_recommend(1.0, 0.0, 80, 200.0, 180), "NOT_WORTH_IT")

    def test_migrate_now_short_payback_fraction_of_holding(self):
        # payback = 10 days, holding = 180 → holding/2 = 90 → payback < 90 → MIGRATE_NOW
        self.assertEqual(_recommend(3.0, 1000.0, 80, 10.0, 180), "MIGRATE_NOW")

    def test_no_migrate_now_when_payback_exceeds_half_holding(self):
        # payback > holding/2 → cannot be MIGRATE_NOW, falls to MIGRATE_SOON if maturity ≥ 50
        result = _recommend(2.0, 500.0, 75, 100.0, 180)  # payback=100, half=90
        self.assertEqual(result, "MIGRATE_SOON")


# ===========================================================================
# 5. Instantiation and structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        r = a.analyze(_data(), NO_LOG)
        self.assertIsInstance(r, dict)

    def test_required_keys_present(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        r = a.analyze(_data(), NO_LOG)
        expected_keys = [
            "protocol_name",
            "old_version_apy_pct",
            "new_version_apy_pct",
            "apy_improvement_pct",
            "migration_cost_usd",
            "new_version_audit_count",
            "new_version_age_days",
            "new_version_tvl_usd",
            "old_version_tvl_usd",
            "position_size_usd",
            "holding_days",
            "migration_payback_days",
            "net_gain_usd",
            "new_version_maturity_score",
            "migration_recommendation",
            "timestamp",
        ]
        for key in expected_keys:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_timestamp_is_float(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        r = a.analyze(_data(), NO_LOG)
        self.assertIsInstance(r["timestamp"], float)

    def test_protocol_name_stored(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        r = a.analyze(_data(protocol_name="Curve"), NO_LOG)
        self.assertEqual(r["protocol_name"], "Curve")


# ===========================================================================
# 6. APY improvement
# ===========================================================================

class TestAPYImprovement(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_positive_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=4.0, new_version_apy_pct=7.0), NO_LOG)
        self.assertAlmostEqual(r["apy_improvement_pct"], 3.0, places=5)

    def test_negative_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=7.0, new_version_apy_pct=4.0), NO_LOG)
        self.assertAlmostEqual(r["apy_improvement_pct"], -3.0, places=5)

    def test_zero_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=5.0, new_version_apy_pct=5.0), NO_LOG)
        self.assertAlmostEqual(r["apy_improvement_pct"], 0.0, places=5)

    def test_improvement_stored_in_output(self):
        r = self.a.analyze(_data(old_version_apy_pct=3.5, new_version_apy_pct=6.0), NO_LOG)
        self.assertAlmostEqual(r["apy_improvement_pct"], 2.5, places=5)

    def test_old_apy_stored(self):
        r = self.a.analyze(_data(old_version_apy_pct=4.5), NO_LOG)
        self.assertAlmostEqual(r["old_version_apy_pct"], 4.5, places=5)

    def test_new_apy_stored(self):
        r = self.a.analyze(_data(new_version_apy_pct=9.0), NO_LOG)
        self.assertAlmostEqual(r["new_version_apy_pct"], 9.0, places=5)


# ===========================================================================
# 7. Payback days
# ===========================================================================

class TestPaybackDays(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_payback_positive_improvement(self):
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0,
            new_version_apy_pct=6.5,
            migration_cost_usd=200.0,
            position_size_usd=50_000.0,
        ), NO_LOG)
        improvement = 2.5
        daily_gain = 50_000.0 * improvement / 100.0 / 365.0
        expected = 200.0 / daily_gain
        self.assertAlmostEqual(r["migration_payback_days"], expected, places=2)

    def test_payback_none_when_no_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=7.0, new_version_apy_pct=4.0), NO_LOG)
        self.assertIsNone(r["migration_payback_days"])

    def test_payback_none_when_zero_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=5.0, new_version_apy_pct=5.0), NO_LOG)
        self.assertIsNone(r["migration_payback_days"])

    def test_payback_short_with_large_position(self):
        r = self.a.analyze(_data(
            position_size_usd=1_000_000.0,
            migration_cost_usd=100.0,
            old_version_apy_pct=4.0,
            new_version_apy_pct=5.0,
        ), NO_LOG)
        self.assertLess(r["migration_payback_days"], 10.0)

    def test_payback_long_with_small_improvement(self):
        r = self.a.analyze(_data(
            position_size_usd=1_000.0,
            migration_cost_usd=5_000.0,
            old_version_apy_pct=4.0,
            new_version_apy_pct=4.1,
        ), NO_LOG)
        self.assertGreater(r["migration_payback_days"], 365.0)


# ===========================================================================
# 8. Net gain
# ===========================================================================

class TestNetGain(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_net_gain_positive_scenario(self):
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0,
            new_version_apy_pct=6.5,
            position_size_usd=50_000.0,
            holding_days=365,
            migration_cost_usd=100.0,
        ), NO_LOG)
        expected = 50_000.0 * 2.5 / 100.0 / 365.0 * 365 - 100.0
        self.assertAlmostEqual(r["net_gain_usd"], expected, places=2)

    def test_net_gain_negative_when_cost_high(self):
        r = self.a.analyze(_data(
            position_size_usd=1_000.0,
            holding_days=1,
            migration_cost_usd=10_000.0,
            old_version_apy_pct=4.0,
            new_version_apy_pct=6.0,
        ), NO_LOG)
        self.assertLess(r["net_gain_usd"], 0.0)

    def test_net_gain_zero_when_no_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=5.0, new_version_apy_pct=5.0, migration_cost_usd=0.0), NO_LOG)
        self.assertAlmostEqual(r["net_gain_usd"], 0.0, places=6)

    def test_net_gain_increases_with_holding_days(self):
        r30 = self.a.analyze(_data(holding_days=30), NO_LOG)
        r365 = self.a.analyze(_data(holding_days=365), NO_LOG)
        self.assertLess(r30["net_gain_usd"], r365["net_gain_usd"])

    def test_net_gain_negative_only_cost_no_hold(self):
        r = self.a.analyze(_data(holding_days=0, migration_cost_usd=500.0), NO_LOG)
        self.assertAlmostEqual(r["net_gain_usd"], -500.0, places=4)


# ===========================================================================
# 9. Maturity score
# ===========================================================================

class TestMaturityScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_maturity_score_is_int(self):
        r = self.a.analyze(_data(), NO_LOG)
        self.assertIsInstance(r["new_version_maturity_score"], int)

    def test_maturity_score_0_to_100(self):
        r = self.a.analyze(_data(), NO_LOG)
        self.assertGreaterEqual(r["new_version_maturity_score"], 0)
        self.assertLessEqual(r["new_version_maturity_score"], 100)

    def test_high_maturity_with_mature_protocol(self):
        r = self.a.analyze(_data(
            new_version_age_days=500,
            new_version_tvl_usd=200_000_000.0,
            new_version_audit_count=5,
        ), NO_LOG)
        self.assertEqual(r["new_version_maturity_score"], 100)

    def test_low_maturity_new_unaudited_protocol(self):
        r = self.a.analyze(_data(
            new_version_age_days=7,
            new_version_tvl_usd=100_000.0,
            new_version_audit_count=0,
        ), NO_LOG)
        self.assertLess(r["new_version_maturity_score"], 30)

    def test_maturity_increases_with_age(self):
        r_new = self.a.analyze(_data(new_version_age_days=30), NO_LOG)
        r_old = self.a.analyze(_data(new_version_age_days=365), NO_LOG)
        self.assertLessEqual(r_new["new_version_maturity_score"], r_old["new_version_maturity_score"])

    def test_maturity_increases_with_tvl(self):
        r_small = self.a.analyze(_data(new_version_tvl_usd=1_000_000.0), NO_LOG)
        r_large = self.a.analyze(_data(new_version_tvl_usd=100_000_000.0), NO_LOG)
        self.assertLessEqual(r_small["new_version_maturity_score"], r_large["new_version_maturity_score"])

    def test_maturity_increases_with_audits(self):
        r0 = self.a.analyze(_data(new_version_audit_count=0), NO_LOG)
        r3 = self.a.analyze(_data(new_version_audit_count=3), NO_LOG)
        self.assertLessEqual(r0["new_version_maturity_score"], r3["new_version_maturity_score"])


# ===========================================================================
# 10. Recommendation labels
# ===========================================================================

class TestRecommendationLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def _valid_labels(self):
        return {
            "MIGRATE_NOW",
            "MIGRATE_SOON",
            "WAIT_FOR_MATURITY",
            "STAY_OLD_VERSION",
            "NOT_WORTH_IT",
        }

    def test_recommendation_is_valid_string(self):
        r = self.a.analyze(_data(), NO_LOG)
        self.assertIn(r["migration_recommendation"], self._valid_labels())

    def test_stay_old_when_new_worse(self):
        r = self.a.analyze(_data(old_version_apy_pct=8.0, new_version_apy_pct=5.0), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "STAY_OLD_VERSION")

    def test_stay_old_when_equal_apy(self):
        r = self.a.analyze(_data(old_version_apy_pct=5.0, new_version_apy_pct=5.0), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "STAY_OLD_VERSION")

    def test_migrate_now_ideal_conditions(self):
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0,
            new_version_apy_pct=8.0,
            migration_cost_usd=50.0,
            new_version_audit_count=5,
            new_version_age_days=730,
            new_version_tvl_usd=300_000_000.0,
            position_size_usd=1_000_000.0,
            holding_days=365,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "MIGRATE_NOW")

    def test_not_worth_it_tiny_hold(self):
        # Even with positive APY, 1-day hold with $500 cost → negative net gain
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0,
            new_version_apy_pct=6.0,
            migration_cost_usd=5_000.0,
            position_size_usd=1_000.0,
            holding_days=1,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "NOT_WORTH_IT")

    def test_wait_for_maturity_new_unproven(self):
        # Positive net gain but low maturity
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0,
            new_version_apy_pct=8.0,
            migration_cost_usd=10.0,
            new_version_audit_count=0,
            new_version_age_days=10,
            new_version_tvl_usd=500_000.0,
            position_size_usd=100_000.0,
            holding_days=365,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "WAIT_FOR_MATURITY")

    def test_recommendation_in_valid_set_all_scenarios(self):
        scenarios = [
            _data(old_version_apy_pct=4.0, new_version_apy_pct=8.0, holding_days=365),
            _data(old_version_apy_pct=8.0, new_version_apy_pct=4.0),
            _data(migration_cost_usd=100_000.0, holding_days=1),
            _data(new_version_audit_count=0, new_version_age_days=5),
        ]
        for s in scenarios:
            r = self.a.analyze(s, NO_LOG)
            self.assertIn(r["migration_recommendation"], self._valid_labels())


# ===========================================================================
# 11. Input guards / edge cases
# ===========================================================================

class TestInputGuards(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_empty_dict_uses_defaults(self):
        r = self.a.analyze({}, NO_LOG)
        self.assertIn("migration_recommendation", r)

    def test_missing_protocol_name_defaults_unknown(self):
        d = _data()
        del d["protocol_name"]
        r = self.a.analyze(d, NO_LOG)
        self.assertEqual(r["protocol_name"], "unknown")

    def test_negative_migration_cost_clamped_to_zero(self):
        r = self.a.analyze(_data(migration_cost_usd=-500.0), NO_LOG)
        self.assertGreaterEqual(r["migration_cost_usd"], 0.0)

    def test_negative_position_size_clamped(self):
        r = self.a.analyze(_data(position_size_usd=-10_000.0), NO_LOG)
        self.assertGreaterEqual(r["position_size_usd"], 0.0)

    def test_negative_holding_days_clamped(self):
        r = self.a.analyze(_data(holding_days=-30), NO_LOG)
        self.assertGreaterEqual(r["holding_days"], 0)

    def test_negative_tvl_clamped(self):
        r = self.a.analyze(_data(new_version_tvl_usd=-1_000_000.0), NO_LOG)
        self.assertGreaterEqual(r["new_version_tvl_usd"], 0.0)

    def test_negative_audit_count_clamped(self):
        r = self.a.analyze(_data(new_version_audit_count=-2), NO_LOG)
        self.assertGreaterEqual(r["new_version_audit_count"], 0)

    def test_negative_age_clamped(self):
        r = self.a.analyze(_data(new_version_age_days=-10), NO_LOG)
        self.assertGreaterEqual(r["new_version_age_days"], 0)

    def test_zero_position_payback_is_none(self):
        r = self.a.analyze(_data(position_size_usd=0.0, new_version_apy_pct=8.0), NO_LOG)
        self.assertIsNone(r["migration_payback_days"])

    def test_very_large_tvl_maturity_capped(self):
        r = self.a.analyze(_data(new_version_tvl_usd=1e15), NO_LOG)
        self.assertLessEqual(r["new_version_maturity_score"], 100)

    def test_string_coercion_apy(self):
        d = _data()
        d["new_version_apy_pct"] = "7.5"
        r = self.a.analyze(d, NO_LOG)
        self.assertAlmostEqual(r["new_version_apy_pct"], 7.5, places=5)

    def test_string_coercion_holding_days(self):
        d = _data()
        d["holding_days"] = "90"
        r = self.a.analyze(d, NO_LOG)
        self.assertEqual(r["holding_days"], 90)


# ===========================================================================
# 12. Log file — _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "migration_log.json")
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends_entries(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "migration_log.json")
            _atomic_log(path, {"n": 1})
            _atomic_log(path, {"n": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[1]["n"], 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "migration_log.json")
            for i in range(_LOG_CAP + 15):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), _LOG_CAP)
            self.assertEqual(data[-1]["i"], _LOG_CAP + 14)

    def test_log_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "migration_log.json")
            _atomic_log(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_recovers_from_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "migration_log.json")
            with open(path, "w") as f:
                f.write("CORRUPT")
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["ok"])

    def test_log_written_by_analyze(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "mig_log.json")
            a.analyze(_data(), {"write_log": True, "log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertIn("protocol_name", data[0])

    def test_no_log_skips_write(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "nolog.json")
            a.analyze(_data(), {"write_log": False, "log_path": log_path})
            self.assertFalse(os.path.exists(log_path))

    def test_log_entry_fields(self):
        a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "mig_log.json")
            a.analyze(_data(protocol_name="UniV3"), {"write_log": True, "log_path": log_path})
            with open(log_path) as f:
                entry = json.load(f)[0]
            for field in ["timestamp", "protocol_name", "apy_improvement_pct", "migration_recommendation"]:
                self.assertIn(field, entry)


# ===========================================================================
# 13. Batch mode
# ===========================================================================

class TestBatchMode(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_batch_returns_dict(self):
        out = self.a.analyze_batch([_data(), _data()], NO_LOG)
        self.assertIsInstance(out, dict)

    def test_batch_top_level_keys(self):
        out = self.a.analyze_batch([_data()], NO_LOG)
        for k in ("results", "summary", "timestamp"):
            self.assertIn(k, out)

    def test_batch_results_length(self):
        out = self.a.analyze_batch([_data(), _data(), _data()], NO_LOG)
        self.assertEqual(len(out["results"]), 3)

    def test_batch_empty_list(self):
        out = self.a.analyze_batch([], NO_LOG)
        self.assertEqual(out["summary"]["count"], 0)

    def test_batch_raises_on_non_list(self):
        with self.assertRaises(TypeError):
            self.a.analyze_batch("not a list", NO_LOG)

    def test_batch_summary_count(self):
        out = self.a.analyze_batch([_data(), _data()], NO_LOG)
        self.assertEqual(out["summary"]["count"], 2)

    def test_batch_summary_keys(self):
        out = self.a.analyze_batch([_data()], NO_LOG)
        summary_keys = [
            "count", "migrate_now_count", "migrate_soon_count",
            "not_worth_it_count", "stay_old_count", "wait_maturity_count",
            "avg_apy_improvement_pct", "total_net_gain_usd", "avg_maturity_score",
        ]
        for k in summary_keys:
            self.assertIn(k, out["summary"])

    def test_batch_stay_old_counted(self):
        old_worse = _data(old_version_apy_pct=8.0, new_version_apy_pct=5.0)
        good = _data()
        out = self.a.analyze_batch([old_worse, good], NO_LOG)
        self.assertGreaterEqual(out["summary"]["stay_old_count"], 1)

    def test_batch_avg_apy_improvement(self):
        d1 = _data(old_version_apy_pct=4.0, new_version_apy_pct=6.0)   # +2.0
        d2 = _data(old_version_apy_pct=4.0, new_version_apy_pct=8.0)   # +4.0
        out = self.a.analyze_batch([d1, d2], NO_LOG)
        self.assertAlmostEqual(out["summary"]["avg_apy_improvement_pct"], 3.0, places=4)

    def test_batch_total_net_gain(self):
        out = self.a.analyze_batch([_data(), _data()], NO_LOG)
        total = sum(r["net_gain_usd"] for r in out["results"])
        self.assertAlmostEqual(out["summary"]["total_net_gain_usd"], total, places=4)

    def test_batch_timestamp_is_float(self):
        out = self.a.analyze_batch([_data()], NO_LOG)
        self.assertIsInstance(out["timestamp"], float)


# ===========================================================================
# 14. Internal consistency
# ===========================================================================

class TestInternalConsistency(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_apy_improvement_consistent_with_inputs(self):
        old, new = 3.7, 6.2
        r = self.a.analyze(_data(old_version_apy_pct=old, new_version_apy_pct=new), NO_LOG)
        self.assertAlmostEqual(r["apy_improvement_pct"], new - old, places=5)

    def test_maturity_score_in_range(self):
        for age in [0, 30, 180, 365, 730]:
            r = self.a.analyze(_data(new_version_age_days=age), NO_LOG)
            self.assertGreaterEqual(r["new_version_maturity_score"], 0)
            self.assertLessEqual(r["new_version_maturity_score"], 100)

    def test_recommendation_stay_old_implies_apy_no_improvement(self):
        r = self.a.analyze(_data(old_version_apy_pct=8.0, new_version_apy_pct=3.0), NO_LOG)
        if r["migration_recommendation"] == "STAY_OLD_VERSION":
            self.assertLessEqual(r["apy_improvement_pct"], 0.0)

    def test_migrate_now_implies_positive_net_gain(self):
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0, new_version_apy_pct=10.0,
            migration_cost_usd=10.0, position_size_usd=500_000.0,
            new_version_age_days=500, new_version_tvl_usd=200_000_000.0,
            new_version_audit_count=5, holding_days=365,
        ), NO_LOG)
        if r["migration_recommendation"] == "MIGRATE_NOW":
            self.assertGreater(r["net_gain_usd"], 0.0)

    def test_not_worth_it_implies_net_gain_le_zero(self):
        r = self.a.analyze(_data(
            old_version_apy_pct=4.0, new_version_apy_pct=4.1,
            migration_cost_usd=10_000.0, position_size_usd=1_000.0,
            holding_days=5,
        ), NO_LOG)
        if r["migration_recommendation"] == "NOT_WORTH_IT":
            self.assertLessEqual(r["net_gain_usd"], 0.0)

    def test_payback_none_iff_apy_improvement_le_zero(self):
        r_neg = self.a.analyze(_data(old_version_apy_pct=8.0, new_version_apy_pct=5.0), NO_LOG)
        self.assertIsNone(r_neg["migration_payback_days"])
        r_pos = self.a.analyze(_data(old_version_apy_pct=4.0, new_version_apy_pct=8.0, migration_cost_usd=1.0), NO_LOG)
        self.assertIsNotNone(r_pos["migration_payback_days"])


# ===========================================================================
# 15. Scenario tests
# ===========================================================================

class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()

    def test_uniswap_v2_to_v3_mature(self):
        """Classic V2→V3 migration: V3 is well-established, better fees."""
        r = self.a.analyze(_data(
            protocol_name="Uniswap",
            old_version_apy_pct=5.0,
            new_version_apy_pct=8.0,
            migration_cost_usd=50.0,
            new_version_audit_count=5,
            new_version_age_days=900,
            new_version_tvl_usd=3_000_000_000.0,
            position_size_usd=100_000.0,
            holding_days=180,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "MIGRATE_NOW")

    def test_aave_v2_to_v3_just_launched(self):
        """V3 just launched, barely any TVL, only 1 audit → WAIT_FOR_MATURITY."""
        r = self.a.analyze(_data(
            protocol_name="Aave",
            old_version_apy_pct=4.0,
            new_version_apy_pct=6.0,
            migration_cost_usd=30.0,
            new_version_audit_count=1,
            new_version_age_days=14,
            new_version_tvl_usd=500_000.0,
            position_size_usd=50_000.0,
            holding_days=180,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "WAIT_FOR_MATURITY")

    def test_curve_old_to_new_gauge_negative_improvement(self):
        """New gauge actually has lower emissions → STAY_OLD_VERSION."""
        r = self.a.analyze(_data(
            protocol_name="Curve",
            old_version_apy_pct=12.0,
            new_version_apy_pct=9.0,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "STAY_OLD_VERSION")

    def test_very_short_hold_high_cost_not_worth_it(self):
        r = self.a.analyze(_data(
            holding_days=3,
            migration_cost_usd=2_000.0,
            position_size_usd=10_000.0,
            old_version_apy_pct=4.0,
            new_version_apy_pct=10.0,
        ), NO_LOG)
        self.assertEqual(r["migration_recommendation"], "NOT_WORTH_IT")

    def test_large_position_quick_payback_migrate_soon_or_now(self):
        r = self.a.analyze(_data(
            position_size_usd=5_000_000.0,
            migration_cost_usd=500.0,
            old_version_apy_pct=4.0,
            new_version_apy_pct=7.0,
            holding_days=365,
            new_version_audit_count=2,
            new_version_age_days=200,
            new_version_tvl_usd=50_000_000.0,
        ), NO_LOG)
        self.assertIn(r["migration_recommendation"], {"MIGRATE_NOW", "MIGRATE_SOON"})


if __name__ == "__main__":
    unittest.main()
