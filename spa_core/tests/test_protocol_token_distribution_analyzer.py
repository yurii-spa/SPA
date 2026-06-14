"""
Tests for MP-975 ProtocolTokenDistributionAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_token_distribution_analyzer -v
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_token_distribution_analyzer import (
    ProtocolTokenDistributionAnalyzer,
    _gini_coefficient,
    _upcoming_unlock_6m,
    _atomic_write,
)


# ── Allocation helper ─────────────────────────────────────────────────────────

def _alloc(
    category="community",
    pct_total=20.0,
    vesting_months=24,
    cliff_months=0,
    already_vested_pct=0.0,
):
    return {
        "category": category,
        "pct_total": pct_total,
        "vesting_months": vesting_months,
        "cliff_months": cliff_months,
        "already_vested_pct": already_vested_pct,
    }


def _token(
    name="TokenA",
    protocol="ProtocolA",
    token_age_months=12,
    allocations=None,
    total_supply=1_000_000_000,
    circulating_supply=200_000_000,
):
    if allocations is None:
        allocations = [
            _alloc("team", 20.0, 48, 12, 25.0),
            _alloc("investors", 15.0, 36, 12, 33.0),
            _alloc("community", 40.0, 0, 0, 100.0),
            _alloc("treasury", 15.0, 0, 0, 100.0),
            _alloc("ecosystem", 10.0, 24, 0, 50.0),
        ]
    return {
        "name": name,
        "protocol": protocol,
        "token_age_months": token_age_months,
        "allocations": allocations,
        "total_supply": total_supply,
        "circulating_supply": circulating_supply,
    }


# ── Gini coefficient tests ─────────────────────────────────────────────────────

class TestGiniCoefficient(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_gini_coefficient([]), 0.0)

    def test_single_value_returns_zero(self):
        self.assertEqual(_gini_coefficient([50.0]), 0.0)

    def test_equal_values_returns_zero(self):
        result = _gini_coefficient([25.0, 25.0, 25.0, 25.0])
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_perfect_inequality_returns_near_one(self):
        # One category has everything
        result = _gini_coefficient([100.0, 0.0, 0.0, 0.0])
        self.assertGreater(result, 0.6)

    def test_moderate_inequality(self):
        result = _gini_coefficient([50.0, 30.0, 15.0, 5.0])
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_two_equal_returns_zero(self):
        result = _gini_coefficient([30.0, 30.0])
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_all_zeros_returns_zero(self):
        result = _gini_coefficient([0.0, 0.0, 0.0])
        self.assertEqual(result, 0.0)

    def test_more_unequal_higher_gini(self):
        equal = _gini_coefficient([25.0, 25.0, 25.0, 25.0])
        unequal = _gini_coefficient([80.0, 10.0, 5.0, 5.0])
        self.assertGreater(unequal, equal)


# ── Upcoming unlock tests ─────────────────────────────────────────────────────

class TestUpcomingUnlock6m(unittest.TestCase):

    def test_fully_vested_returns_zero(self):
        alloc = _alloc("team", 20.0, 24, 0, 100.0)
        self.assertEqual(_upcoming_unlock_6m(alloc, 12), 0.0)

    def test_no_vesting_schedule_returns_zero(self):
        alloc = _alloc("community", 40.0, 0, 0, 0.0)
        self.assertEqual(_upcoming_unlock_6m(alloc, 0), 0.0)

    def test_cliff_beyond_window_returns_zero(self):
        # Token age = 0, cliff at 12 months, window = 6 months
        alloc = _alloc("team", 20.0, 48, 12, 0.0)
        self.assertEqual(_upcoming_unlock_6m(alloc, 0), 0.0)

    def test_cliff_within_window(self):
        # Token age = 0, cliff at 3 months → cliff within 6-month window
        alloc = _alloc("team", 20.0, 24, 3, 0.0)
        result = _upcoming_unlock_6m(alloc, 0)
        self.assertGreater(result, 0.0)

    def test_past_cliff_linear_vesting(self):
        # Token age = 12, cliff = 6, vesting = 24 → well past cliff
        alloc = _alloc("team", 20.0, 24, 6, 50.0)
        result = _upcoming_unlock_6m(alloc, 12)
        self.assertGreater(result, 0.0)

    def test_zero_pct_total_returns_zero(self):
        alloc = _alloc("team", 0.0, 24, 0, 0.0)
        self.assertEqual(_upcoming_unlock_6m(alloc, 12), 0.0)

    def test_vesting_already_ended_returns_zero(self):
        # Token age > vesting months
        alloc = _alloc("team", 20.0, 12, 0, 50.0)
        result = _upcoming_unlock_6m(alloc, 24)  # age > vesting → no more
        self.assertEqual(result, 0.0)

    def test_unlock_proportional_to_window(self):
        # With linear vesting, 6-month window should unlock 6/remaining ratio
        alloc = _alloc("team", 100.0, 24, 0, 0.0)
        # At age=0, 24 months remaining, rate = 100/24 per month
        result = _upcoming_unlock_6m(alloc, 0)
        expected = 6 * (100.0 / 24.0)
        self.assertAlmostEqual(result, expected, places=4)


# ── Integration tests (ProtocolTokenDistributionAnalyzer.analyze) ─────────────

class TestAnalyzeIntegration(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolTokenDistributionAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"data_dir": self.tmp, "write_log": False}

    # ── Output structure ──────────────────────────────────────────────────────

    def test_empty_tokens_returns_empty_list(self):
        result = self.analyzer.analyze([], self.cfg)
        self.assertEqual(result["tokens"], [])

    def test_output_has_timestamp(self):
        result = self.analyzer.analyze([], self.cfg)
        self.assertIn("timestamp", result)
        self.assertTrue(result["timestamp"].endswith("Z"))

    def test_output_has_tokens_key(self):
        result = self.analyzer.analyze([_token()], self.cfg)
        self.assertIn("tokens", result)

    def test_output_has_aggregates_key(self):
        result = self.analyzer.analyze([_token()], self.cfg)
        self.assertIn("aggregates", result)

    def test_token_result_has_required_fields(self):
        result = self.analyzer.analyze([_token()], self.cfg)
        t = result["tokens"][0]
        for field in [
            "name", "protocol", "team_plus_investor_pct", "community_pct",
            "insider_lock_remaining_months", "gini_coefficient",
            "upcoming_unlock_6m_pct", "distribution_label", "flags"
        ]:
            self.assertIn(field, t, f"Missing field: {field}")

    def test_aggregates_has_required_fields(self):
        result = self.analyzer.analyze([_token()], self.cfg)
        agg = result["aggregates"]
        for field in [
            "most_community_aligned", "most_insider_heavy",
            "average_community_pct", "community_first_count", "insider_dominated_count"
        ]:
            self.assertIn(field, agg, f"Missing aggregate field: {field}")

    # ── Category pct calculations ─────────────────────────────────────────────

    def test_team_plus_investor_pct(self):
        allocs = [_alloc("team", 20.0), _alloc("investors", 15.0), _alloc("community", 65.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["team_plus_investor_pct"], 35.0, places=4)

    def test_team_only_pct(self):
        allocs = [_alloc("team", 30.0), _alloc("community", 70.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["team_plus_investor_pct"], 30.0, places=4)

    def test_investors_only_pct(self):
        allocs = [_alloc("investors", 25.0), _alloc("community", 75.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["team_plus_investor_pct"], 25.0, places=4)

    def test_community_pct_includes_ecosystem_public_sale(self):
        allocs = [
            _alloc("community", 20.0),
            _alloc("ecosystem", 15.0),
            _alloc("public_sale", 10.0),
            _alloc("team", 55.0),
        ]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["community_pct"], 45.0, places=4)

    def test_community_pct_ecosystem_only(self):
        allocs = [_alloc("ecosystem", 30.0), _alloc("team", 70.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["community_pct"], 30.0, places=4)

    def test_community_pct_public_sale_only(self):
        allocs = [_alloc("public_sale", 40.0), _alloc("team", 60.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["community_pct"], 40.0, places=4)

    def test_treasury_not_counted_in_community(self):
        allocs = [_alloc("treasury", 30.0), _alloc("community", 20.0), _alloc("team", 50.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["community_pct"], 20.0, places=4)

    def test_liquidity_not_counted_in_community(self):
        allocs = [_alloc("liquidity", 30.0), _alloc("community", 20.0), _alloc("team", 50.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["community_pct"], 20.0, places=4)

    def test_zero_team_investor(self):
        allocs = [_alloc("community", 100.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["team_plus_investor_pct"], 0.0, places=4)

    # ── Insider lock remaining ────────────────────────────────────────────────

    def test_insider_lock_remaining_team(self):
        # vesting=24, already_vested=50% → remaining = 24 * 0.5 = 12
        allocs = [_alloc("team", 20.0, 24, 0, 50.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 12.0, places=4)

    def test_insider_lock_remaining_investor(self):
        # vesting=36, already_vested=0% → remaining = 36
        allocs = [_alloc("investors", 15.0, 36, 0, 0.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 36.0, places=4)

    def test_insider_lock_fully_vested_is_zero(self):
        allocs = [_alloc("team", 20.0, 24, 0, 100.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 0.0, places=4)

    def test_insider_lock_takes_max_across_allocs(self):
        # team: 24 months remaining, investors: 36 months remaining
        allocs = [
            _alloc("team", 20.0, 24, 0, 0.0),
            _alloc("investors", 15.0, 36, 0, 0.0),
        ]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 36.0, places=4)

    def test_insider_lock_zero_when_no_team_investor(self):
        allocs = [_alloc("community", 100.0, 0, 0, 100.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 0.0, places=4)

    def test_insider_lock_partial_vesting(self):
        # vesting=48, already_vested=25% → remaining = 48 * 0.75 = 36
        allocs = [_alloc("team", 20.0, 48, 0, 25.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["insider_lock_remaining_months"], 36.0, places=4)

    # ── Gini coefficient ──────────────────────────────────────────────────────

    def test_gini_equal_allocs_near_zero(self):
        allocs = [_alloc("community", 25.0), _alloc("team", 25.0),
                  _alloc("investors", 25.0), _alloc("treasury", 25.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["gini_coefficient"], 0.0, places=4)

    def test_gini_concentrated_high(self):
        allocs = [_alloc("team", 95.0), _alloc("community", 5.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertGreater(result["tokens"][0]["gini_coefficient"], 0.3)

    def test_gini_single_alloc_is_zero(self):
        allocs = [_alloc("community", 100.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["gini_coefficient"], 0.0, places=4)

    def test_gini_no_allocs_is_zero(self):
        t = _token(allocations=[])
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["gini_coefficient"], 0.0, places=4)

    # ── Distribution labels ───────────────────────────────────────────────────

    def test_label_community_first(self):
        allocs = [_alloc("community", 65.0), _alloc("team", 35.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "COMMUNITY_FIRST")

    def test_label_community_first_exactly_60_not_triggered(self):
        # community > 60, so exactly 60 is NOT community first
        allocs = [_alloc("community", 60.0), _alloc("team", 40.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotEqual(result["tokens"][0]["distribution_label"], "COMMUNITY_FIRST")

    def test_label_insider_dominated(self):
        allocs = [_alloc("team", 40.0), _alloc("investors", 25.0), _alloc("community", 35.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "INSIDER_DOMINATED")

    def test_label_insider_dominated_exactly_60_not_triggered(self):
        allocs = [_alloc("team", 30.0), _alloc("investors", 30.0), _alloc("community", 40.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotEqual(result["tokens"][0]["distribution_label"], "INSIDER_DOMINATED")

    def test_label_investor_heavy(self):
        allocs = [_alloc("investors", 35.0), _alloc("community", 50.0), _alloc("team", 15.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "INVESTOR_HEAVY")

    def test_label_investor_heavy_exactly_30_not_triggered(self):
        allocs = [_alloc("investors", 30.0), _alloc("community", 55.0), _alloc("team", 15.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotEqual(result["tokens"][0]["distribution_label"], "INVESTOR_HEAVY")

    def test_label_team_heavy(self):
        allocs = [_alloc("team", 30.0), _alloc("community", 55.0), _alloc("investors", 15.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "TEAM_HEAVY")

    def test_label_team_heavy_exactly_25_not_triggered(self):
        allocs = [_alloc("team", 25.0), _alloc("community", 60.0), _alloc("investors", 15.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        # community = 60 → not > 60 either, team = 25 → not > 25
        # investors = 15 → not > 30
        self.assertEqual(result["tokens"][0]["distribution_label"], "BALANCED")

    def test_label_balanced(self):
        allocs = [
            _alloc("team", 20.0), _alloc("investors", 15.0),
            _alloc("community", 40.0), _alloc("treasury", 25.0)
        ]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "BALANCED")

    def test_community_first_takes_priority_over_investor_heavy(self):
        # community > 60 AND investors > 30 → COMMUNITY_FIRST wins
        allocs = [_alloc("community", 65.0), _alloc("investors", 35.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["distribution_label"], "COMMUNITY_FIRST")

    # ── Flags ─────────────────────────────────────────────────────────────────

    def test_flag_high_insider_pct(self):
        allocs = [_alloc("team", 30.0), _alloc("investors", 25.0), _alloc("community", 45.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("HIGH_INSIDER_PCT", result["tokens"][0]["flags"])

    def test_flag_high_insider_pct_exactly_50_not_flagged(self):
        allocs = [_alloc("team", 25.0), _alloc("investors", 25.0), _alloc("community", 50.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("HIGH_INSIDER_PCT", result["tokens"][0]["flags"])

    def test_flag_high_insider_pct_not_set_when_low(self):
        allocs = [_alloc("team", 10.0), _alloc("investors", 10.0), _alloc("community", 80.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("HIGH_INSIDER_PCT", result["tokens"][0]["flags"])

    def test_flag_imminent_large_unlock(self):
        # Large unlock: community 100% of supply, 0% vested, 12-month vesting
        # At age 0, unlock in 6 months = 6/12 * 100 = 50%
        allocs = [_alloc("community", 100.0, 12, 0, 0.0)]
        t = _token(allocations=allocs, token_age_months=0)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("IMMINENT_LARGE_UNLOCK", result["tokens"][0]["flags"])

    def test_flag_imminent_large_unlock_not_triggered(self):
        # Small unlock: 5% of supply, 60-month vesting, already 50% vested
        # remaining = 5 * 0.5 = 2.5; in 6m of 30-month remaining: 6/30 * 2.5 = 0.5%
        allocs = [_alloc("community", 5.0, 60, 0, 50.0)]
        t = _token(allocations=allocs, token_age_months=0)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("IMMINENT_LARGE_UNLOCK", result["tokens"][0]["flags"])

    def test_flag_vesting_complete_all_100(self):
        allocs = [
            _alloc("team", 20.0, 24, 0, 100.0),
            _alloc("community", 80.0, 0, 0, 100.0),
        ]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("VESTING_COMPLETE", result["tokens"][0]["flags"])

    def test_flag_vesting_complete_not_set_when_partial(self):
        allocs = [
            _alloc("team", 20.0, 24, 0, 50.0),   # not fully vested
            _alloc("community", 80.0, 0, 0, 100.0),
        ]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("VESTING_COMPLETE", result["tokens"][0]["flags"])

    def test_flag_vesting_complete_empty_allocs_not_set(self):
        t = _token(allocations=[])
        result = self.analyzer.analyze([t], self.cfg)
        # No allocations → len==0, condition is False
        self.assertNotIn("VESTING_COMPLETE", result["tokens"][0]["flags"])

    def test_flag_fair_launch_no_team_investor(self):
        allocs = [_alloc("community", 70.0), _alloc("treasury", 30.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("FAIR_LAUNCH", result["tokens"][0]["flags"])

    def test_flag_fair_launch_not_set_when_team_exists(self):
        allocs = [_alloc("team", 1.0), _alloc("community", 99.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("FAIR_LAUNCH", result["tokens"][0]["flags"])

    def test_flag_fair_launch_not_set_when_investor_exists(self):
        allocs = [_alloc("investors", 0.1), _alloc("community", 99.9)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("FAIR_LAUNCH", result["tokens"][0]["flags"])

    def test_flag_long_vesting_above_48(self):
        allocs = [_alloc("team", 20.0, 60, 0, 0.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("LONG_VESTING", result["tokens"][0]["flags"])

    def test_flag_long_vesting_exactly_48_not_triggered(self):
        allocs = [_alloc("team", 20.0, 48, 0, 0.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("LONG_VESTING", result["tokens"][0]["flags"])

    def test_flag_long_vesting_not_set_when_short(self):
        allocs = [_alloc("team", 20.0, 24, 0, 0.0)]
        t = _token(allocations=allocs)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertNotIn("LONG_VESTING", result["tokens"][0]["flags"])

    def test_multiple_flags_can_coexist(self):
        allocs = [
            _alloc("team", 35.0, 60, 0, 0.0),    # LONG_VESTING + HIGH_INSIDER
            _alloc("investors", 20.0, 36, 0, 0.0),
            _alloc("community", 45.0, 0, 0, 100.0),
        ]
        t = _token(allocations=allocs, token_age_months=0)
        result = self.analyzer.analyze([t], self.cfg)
        flags = result["tokens"][0]["flags"]
        self.assertIn("HIGH_INSIDER_PCT", flags)
        self.assertIn("LONG_VESTING", flags)

    def test_no_flags_when_none_triggered(self):
        allocs = [
            _alloc("team", 15.0, 24, 0, 100.0),
            _alloc("investors", 10.0, 24, 0, 100.0),
            _alloc("community", 75.0, 0, 0, 100.0),
        ]
        t = _token(allocations=allocs, token_age_months=30)
        result = self.analyzer.analyze([t], self.cfg)
        # team+investor = 25 (not > 50), vesting complete, no large unlock
        flags = result["tokens"][0]["flags"]
        self.assertNotIn("HIGH_INSIDER_PCT", flags)
        self.assertNotIn("IMMINENT_LARGE_UNLOCK", flags)

    # ── Aggregates ────────────────────────────────────────────────────────────

    def test_aggregates_empty(self):
        result = self.analyzer.analyze([], self.cfg)
        agg = result["aggregates"]
        self.assertIsNone(agg["most_community_aligned"])
        self.assertIsNone(agg["most_insider_heavy"])
        self.assertEqual(agg["average_community_pct"], 0.0)
        self.assertEqual(agg["community_first_count"], 0)
        self.assertEqual(agg["insider_dominated_count"], 0)

    def test_aggregates_single_token(self):
        t = _token(name="OnlyToken")
        result = self.analyzer.analyze([t], self.cfg)
        agg = result["aggregates"]
        self.assertEqual(agg["most_community_aligned"], "OnlyToken")
        self.assertEqual(agg["most_insider_heavy"], "OnlyToken")

    def test_aggregates_most_community_aligned(self):
        t1 = _token(name="HighCommunity", allocations=[_alloc("community", 80.0), _alloc("team", 20.0)])
        t2 = _token(name="LowCommunity", allocations=[_alloc("community", 20.0), _alloc("team", 80.0)])
        result = self.analyzer.analyze([t1, t2], self.cfg)
        self.assertEqual(result["aggregates"]["most_community_aligned"], "HighCommunity")

    def test_aggregates_most_insider_heavy(self):
        t1 = _token(name="HighInsider", allocations=[_alloc("team", 60.0), _alloc("community", 40.0)])
        t2 = _token(name="LowInsider", allocations=[_alloc("team", 10.0), _alloc("community", 90.0)])
        result = self.analyzer.analyze([t1, t2], self.cfg)
        self.assertEqual(result["aggregates"]["most_insider_heavy"], "HighInsider")

    def test_aggregates_average_community_pct(self):
        t1 = _token(name="A", allocations=[_alloc("community", 60.0), _alloc("team", 40.0)])
        t2 = _token(name="B", allocations=[_alloc("community", 40.0), _alloc("team", 60.0)])
        result = self.analyzer.analyze([t1, t2], self.cfg)
        self.assertAlmostEqual(result["aggregates"]["average_community_pct"], 50.0, places=4)

    def test_aggregates_community_first_count(self):
        t1 = _token(name="A", allocations=[_alloc("community", 65.0), _alloc("team", 35.0)])
        t2 = _token(name="B", allocations=[_alloc("community", 70.0), _alloc("team", 30.0)])
        t3 = _token(name="C", allocations=[_alloc("community", 30.0), _alloc("team", 70.0)])
        result = self.analyzer.analyze([t1, t2, t3], self.cfg)
        self.assertEqual(result["aggregates"]["community_first_count"], 2)

    def test_aggregates_insider_dominated_count(self):
        t1 = _token(name="A", allocations=[_alloc("team", 40.0), _alloc("investors", 25.0), _alloc("community", 35.0)])
        t2 = _token(name="B", allocations=[_alloc("community", 100.0)])
        result = self.analyzer.analyze([t1, t2], self.cfg)
        self.assertEqual(result["aggregates"]["insider_dominated_count"], 1)

    def test_aggregates_all_community_first(self):
        tokens = [
            _token(name=f"T{i}", allocations=[_alloc("community", 70.0), _alloc("team", 30.0)])
            for i in range(3)
        ]
        result = self.analyzer.analyze(tokens, self.cfg)
        self.assertEqual(result["aggregates"]["community_first_count"], 3)

    def test_aggregates_all_insider_dominated(self):
        tokens = [
            _token(name=f"T{i}", allocations=[_alloc("team", 40.0), _alloc("investors", 25.0), _alloc("community", 35.0)])
            for i in range(3)
        ]
        result = self.analyzer.analyze(tokens, self.cfg)
        self.assertEqual(result["aggregates"]["insider_dominated_count"], 3)

    # ── Name/protocol preservation ────────────────────────────────────────────

    def test_name_preserved(self):
        t = _token(name="SpecialToken")
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["name"], "SpecialToken")

    def test_protocol_name_preserved(self):
        t = _token(protocol="MyProtocol")
        result = self.analyzer.analyze([t], self.cfg)
        self.assertEqual(result["tokens"][0]["protocol"], "MyProtocol")

    # ── Log writing ───────────────────────────────────────────────────────────

    def test_write_log_false_no_file(self):
        cfg = {"data_dir": self.tmp, "write_log": False}
        self.analyzer.analyze([_token()], cfg)
        log_path = os.path.join(self.tmp, "token_distribution_log.json")
        self.assertFalse(os.path.exists(log_path))

    def test_write_log_true_creates_file(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.analyzer.analyze([_token()], cfg)
        log_path = os.path.join(self.tmp, "token_distribution_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_array(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.analyzer.analyze([_token()], cfg)
        log_path = os.path.join(self.tmp, "token_distribution_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_appends_entries(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.analyzer.analyze([_token()], cfg)
        self.analyzer.analyze([_token()], cfg)
        log_path = os.path.join(self.tmp, "token_distribution_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_log_ring_buffer_caps_entries(self):
        cfg = {"data_dir": self.tmp, "write_log": True, "log_cap": 3}
        for _ in range(5):
            self.analyzer.analyze([_token()], cfg)
        log_path = os.path.join(self.tmp, "token_distribution_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_atomic_write_produces_correct_file(self):
        path = os.path.join(self.tmp, "test_atomic.json")
        _atomic_write(path, {"hello": "world"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, {"hello": "world"})

    def test_no_tmp_file_remains_after_atomic_write(self):
        path = os.path.join(self.tmp, "test_no_tmp.json")
        _atomic_write(path, [])
        self.assertFalse(os.path.exists(path + ".tmp"))

    # ── Config defaults ───────────────────────────────────────────────────────

    def test_config_none_defaults_applied(self):
        # Pass explicit cfg to avoid writing to cwd
        result = self.analyzer.analyze([_token()], self.cfg)
        self.assertIn("tokens", result)

    def test_missing_token_age_defaults_to_zero(self):
        t = {
            "name": "MinToken",
            "protocol": "MinProto",
            "allocations": [_alloc("community", 100.0, 0, 0, 100.0)],
        }
        result = self.analyzer.analyze([t], self.cfg)
        self.assertIn("distribution_label", result["tokens"][0])

    def test_empty_allocations_handled(self):
        t = _token(allocations=[])
        result = self.analyzer.analyze([t], self.cfg)
        r = result["tokens"][0]
        self.assertAlmostEqual(r["team_plus_investor_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["community_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["gini_coefficient"], 0.0, places=4)
        self.assertAlmostEqual(r["upcoming_unlock_6m_pct"], 0.0, places=4)

    # ── Upcoming unlock integration ───────────────────────────────────────────

    def test_upcoming_unlock_zero_for_fully_vested(self):
        allocs = [_alloc("community", 100.0, 24, 0, 100.0)]
        t = _token(allocations=allocs, token_age_months=12)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertAlmostEqual(result["tokens"][0]["upcoming_unlock_6m_pct"], 0.0, places=4)

    def test_upcoming_unlock_nonzero_for_active_vesting(self):
        allocs = [_alloc("community", 100.0, 24, 0, 0.0)]
        t = _token(allocations=allocs, token_age_months=0)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertGreater(result["tokens"][0]["upcoming_unlock_6m_pct"], 0.0)

    def test_upcoming_unlock_capped_at_100(self):
        allocs = [_alloc("community", 100.0, 1, 0, 0.0)]
        t = _token(allocations=allocs, token_age_months=0)
        result = self.analyzer.analyze([t], self.cfg)
        self.assertLessEqual(result["tokens"][0]["upcoming_unlock_6m_pct"], 100.0)

    def test_multiple_tokens(self):
        tokens = [_token(name=f"Token{i}") for i in range(4)]
        result = self.analyzer.analyze(tokens, self.cfg)
        self.assertEqual(len(result["tokens"]), 4)


if __name__ == "__main__":
    unittest.main()
