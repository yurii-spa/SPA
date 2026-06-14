"""
Tests for MP-676: TokenVestingTracker
≥65 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.token_vesting_tracker import (
    MAX_ENTRIES,
    TokenVestingTracker,
    VestingSchedule,
    VestingStatus,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

NOW = 1_700_000_000.0  # fixed "now" for deterministic tests


def _schedule(
    beneficiary_id="inv_001",
    beneficiary_type="INVESTOR",
    total_tokens=1_000_000.0,
    tokens_unlocked=0.0,
    cliff_days=180,
    vest_start_offset_days=-365,   # relative to NOW
    vest_duration_days=1460,
    current_offset_days=0,         # relative to NOW
) -> VestingSchedule:
    return VestingSchedule(
        beneficiary_id=beneficiary_id,
        beneficiary_type=beneficiary_type,
        total_tokens=total_tokens,
        tokens_unlocked=tokens_unlocked,
        cliff_days=cliff_days,
        vest_start_timestamp=NOW + vest_start_offset_days * 86400.0,
        vest_duration_days=vest_duration_days,
        current_timestamp=NOW + current_offset_days * 86400.0,
    )


# ---------------------------------------------------------------------------
# _elapsed_days
# ---------------------------------------------------------------------------

class TestElapsedDays(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_zero_elapsed_at_start(self):
        s = _schedule(vest_start_offset_days=0, current_offset_days=0)
        self.assertAlmostEqual(self.t._elapsed_days(s), 0.0)

    def test_one_day_elapsed(self):
        s = _schedule(vest_start_offset_days=-1, current_offset_days=0)
        self.assertAlmostEqual(self.t._elapsed_days(s), 1.0, places=5)

    def test_365_days_elapsed(self):
        s = _schedule(vest_start_offset_days=-365, current_offset_days=0)
        self.assertAlmostEqual(self.t._elapsed_days(s), 365.0, places=5)

    def test_half_year_elapsed(self):
        s = _schedule(vest_start_offset_days=-180, current_offset_days=0)
        self.assertAlmostEqual(self.t._elapsed_days(s), 180.0, places=5)

    def test_future_start_negative_elapsed(self):
        # vest hasn't started yet
        s = _schedule(vest_start_offset_days=10, current_offset_days=0)
        self.assertAlmostEqual(self.t._elapsed_days(s), -10.0, places=5)

    def test_fractional_days(self):
        s = VestingSchedule(
            beneficiary_id="x",
            beneficiary_type="TEAM",
            total_tokens=1000.0,
            tokens_unlocked=0.0,
            cliff_days=0,
            vest_start_timestamp=NOW - 0.5 * 86400,
            vest_duration_days=100,
            current_timestamp=NOW,
        )
        self.assertAlmostEqual(self.t._elapsed_days(s), 0.5, places=5)


# ---------------------------------------------------------------------------
# _unlockable
# ---------------------------------------------------------------------------

class TestUnlockable(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_before_cliff_zero(self):
        # elapsed 30 days, cliff 180 → 0
        s = _schedule(cliff_days=180, vest_start_offset_days=-30, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 0.0)

    def test_at_cliff_proportional(self):
        # elapsed == cliff == 180, vest_duration 1460
        s = _schedule(cliff_days=180, vest_start_offset_days=-180, vest_duration_days=1460)
        expected = 1_000_000.0 * (180 / 1460)
        self.assertAlmostEqual(self.t._unlockable(s), expected, places=2)

    def test_mid_vest_proportional(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-730, vest_duration_days=1460)
        # 730/1460 = 0.5
        self.assertAlmostEqual(self.t._unlockable(s), 500_000.0, places=2)

    def test_fully_vested_returns_total(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-2000, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 1_000_000.0)

    def test_exactly_at_vest_end(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-1460, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 1_000_000.0)

    def test_cliff_not_yet_passed(self):
        s = _schedule(cliff_days=365, vest_start_offset_days=-100, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 0.0)

    def test_zero_total_tokens(self):
        s = _schedule(total_tokens=0.0, cliff_days=0, vest_start_offset_days=-100,
                      vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 0.0)

    def test_one_day_into_vest_no_cliff(self):
        s = _schedule(total_tokens=1460.0, cliff_days=0,
                      vest_start_offset_days=-1, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._unlockable(s), 1.0, places=5)


# ---------------------------------------------------------------------------
# _days_until_full_vest
# ---------------------------------------------------------------------------

class TestDaysUntilFullVest(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_fully_vested_returns_zero(self):
        s = _schedule(vest_start_offset_days=-2000, vest_duration_days=1460)
        self.assertEqual(self.t._days_until_full_vest(s), 0)

    def test_exactly_at_end_returns_zero(self):
        s = _schedule(vest_start_offset_days=-1460, vest_duration_days=1460)
        self.assertEqual(self.t._days_until_full_vest(s), 0)

    def test_half_way_through(self):
        s = _schedule(vest_start_offset_days=-730, vest_duration_days=1460)
        self.assertEqual(self.t._days_until_full_vest(s), 730)

    def test_just_started(self):
        s = _schedule(vest_start_offset_days=0, vest_duration_days=1460)
        self.assertEqual(self.t._days_until_full_vest(s), 1460)

    def test_one_day_remaining(self):
        s = _schedule(vest_start_offset_days=-1459, vest_duration_days=1460)
        self.assertEqual(self.t._days_until_full_vest(s), 1)

    def test_short_vest(self):
        s = _schedule(vest_start_offset_days=-10, vest_duration_days=30)
        self.assertEqual(self.t._days_until_full_vest(s), 20)


# ---------------------------------------------------------------------------
# _monthly_unlock_rate
# ---------------------------------------------------------------------------

class TestMonthlyUnlockRate(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_fully_vested_returns_zero(self):
        s = _schedule(vest_start_offset_days=-2000, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._monthly_unlock_rate(s), 0.0)

    def test_rate_formula(self):
        # total=1460, duration=1460 → rate = 1460/1460*30 = 30
        s = _schedule(total_tokens=1460.0, vest_start_offset_days=-10,
                      vest_duration_days=1460)
        self.assertAlmostEqual(self.t._monthly_unlock_rate(s), 30.0, places=5)

    def test_partial_vest_not_zero(self):
        s = _schedule(vest_start_offset_days=-365, vest_duration_days=1460)
        rate = self.t._monthly_unlock_rate(s)
        self.assertGreater(rate, 0.0)

    def test_rate_proportional_to_total(self):
        s1 = _schedule(total_tokens=1_000_000.0, vest_start_offset_days=-100,
                       vest_duration_days=1460)
        s2 = _schedule(total_tokens=2_000_000.0, vest_start_offset_days=-100,
                       vest_duration_days=1460)
        self.assertAlmostEqual(
            self.t._monthly_unlock_rate(s2) / self.t._monthly_unlock_rate(s1), 2.0, places=5
        )

    def test_just_at_vest_end_returns_zero(self):
        s = _schedule(vest_start_offset_days=-1460, vest_duration_days=1460)
        self.assertAlmostEqual(self.t._monthly_unlock_rate(s), 0.0)


# ---------------------------------------------------------------------------
# _sell_pressure
# ---------------------------------------------------------------------------

class TestSellPressure(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_team_high_rate_critical(self):
        # ratio > 0.10 AND TEAM → CRITICAL
        result = self.t._sell_pressure("TEAM", 30.0, 110_000.0, 1_000_000.0)
        self.assertEqual(result, "CRITICAL")

    def test_investor_high_rate_critical(self):
        result = self.t._sell_pressure("INVESTOR", 10.0, 200_000.0, 1_000_000.0)
        self.assertEqual(result, "CRITICAL")

    def test_advisor_high_rate_not_critical(self):
        # ratio > 0.10 but not TEAM/INVESTOR → HIGH (ratio > 0.05)
        result = self.t._sell_pressure("ADVISOR", 20.0, 150_000.0, 1_000_000.0)
        self.assertEqual(result, "HIGH")

    def test_community_high_rate_not_critical(self):
        result = self.t._sell_pressure("COMMUNITY", 10.0, 150_000.0, 1_000_000.0)
        self.assertEqual(result, "HIGH")

    def test_team_unlock_over_50_pct_high(self):
        # ratio = 0.03 (not >0.05), type TEAM, unlock_pct > 50 → HIGH
        result = self.t._sell_pressure("TEAM", 60.0, 30_000.0, 1_000_000.0)
        self.assertEqual(result, "HIGH")

    def test_investor_medium_rate(self):
        # ratio = 0.03 → MEDIUM
        result = self.t._sell_pressure("INVESTOR", 10.0, 30_000.0, 1_000_000.0)
        self.assertEqual(result, "MEDIUM")

    def test_community_low_rate_low(self):
        # ratio = 0.005 → LOW
        result = self.t._sell_pressure("COMMUNITY", 5.0, 5_000.0, 1_000_000.0)
        self.assertEqual(result, "LOW")

    def test_ecosystem_low_rate_low(self):
        result = self.t._sell_pressure("ECOSYSTEM", 5.0, 1_000.0, 1_000_000.0)
        self.assertEqual(result, "LOW")

    def test_zero_total_returns_low(self):
        result = self.t._sell_pressure("TEAM", 0.0, 0.0, 0.0)
        self.assertEqual(result, "LOW")

    def test_ratio_exactly_010_not_critical(self):
        # exactly 0.10 is NOT > 0.10 → not CRITICAL; but > 0.05 → HIGH
        result = self.t._sell_pressure("TEAM", 10.0, 100_000.0, 1_000_000.0)
        self.assertEqual(result, "HIGH")

    def test_ratio_above_005_high(self):
        result = self.t._sell_pressure("COMMUNITY", 20.0, 60_000.0, 1_000_000.0)
        self.assertEqual(result, "HIGH")

    def test_ratio_exactly_005_not_high(self):
        # exactly 0.05 is NOT > 0.05 → falls to MEDIUM if > 0.02
        result = self.t._sell_pressure("COMMUNITY", 0.0, 50_000.0, 1_000_000.0)
        self.assertEqual(result, "MEDIUM")


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def _make_known(self):
        """365 days elapsed, cliff 180, vest_duration 1460, total 1M TEAM."""
        return _schedule(
            beneficiary_id="team_lead",
            beneficiary_type="TEAM",
            total_tokens=1_000_000.0,
            cliff_days=180,
            vest_start_offset_days=-365,
            vest_duration_days=1460,
        )

    def test_beneficiary_id(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertEqual(st.beneficiary_id, "team_lead")

    def test_beneficiary_type(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertEqual(st.beneficiary_type, "TEAM")

    def test_tokens_unlocked_proportional(self):
        s = self._make_known()
        st = self.t.get_status(s)
        expected = 1_000_000.0 * (365 / 1460)
        self.assertAlmostEqual(st.tokens_unlocked, expected, places=2)

    def test_tokens_locked_is_complement(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertAlmostEqual(
            st.tokens_unlocked + st.tokens_locked, 1_000_000.0, places=2
        )

    def test_unlock_pct_in_range(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertGreater(st.unlock_pct, 0.0)
        self.assertLess(st.unlock_pct, 100.0)

    def test_not_fully_vested(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertFalse(st.is_fully_vested)

    def test_cliff_already_passed(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertEqual(st.days_until_next_cliff, 0)

    def test_days_until_full_vest_positive(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertGreater(st.days_until_full_vest, 0)

    def test_monthly_rate_positive(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertGreater(st.monthly_unlock_rate, 0.0)

    def test_sell_pressure_not_empty(self):
        s = self._make_known()
        st = self.t.get_status(s)
        self.assertIn(st.sell_pressure, {"LOW", "MEDIUM", "HIGH", "CRITICAL"})

    def test_fully_vested_status(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-2000, vest_duration_days=1460)
        st = self.t.get_status(s)
        self.assertTrue(st.is_fully_vested)
        self.assertAlmostEqual(st.tokens_locked, 0.0, places=2)
        self.assertAlmostEqual(st.tokens_unlocked, 1_000_000.0, places=2)
        self.assertAlmostEqual(st.monthly_unlock_rate, 0.0)
        self.assertEqual(st.days_until_full_vest, 0)

    def test_before_cliff_tokens_unlocked_zero(self):
        # elapsed 30 days, cliff 180
        s = _schedule(cliff_days=180, vest_start_offset_days=-30, vest_duration_days=1460)
        st = self.t.get_status(s)
        self.assertAlmostEqual(st.tokens_unlocked, 0.0)
        self.assertGreater(st.days_until_next_cliff, 0)

    def test_before_cliff_days_until_cliff_correct(self):
        s = _schedule(cliff_days=180, vest_start_offset_days=-30, vest_duration_days=1460)
        st = self.t.get_status(s)
        self.assertEqual(st.days_until_next_cliff, 150)

    def test_fully_vested_sell_pressure_low(self):
        # monthly_rate is 0 → ratio 0 → LOW
        s = _schedule(cliff_days=0, vest_start_offset_days=-2000, vest_duration_days=1460)
        st = self.t.get_status(s)
        self.assertEqual(st.sell_pressure, "LOW")

    def test_unlock_pct_100_when_fully_vested(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-2000, vest_duration_days=1460)
        st = self.t.get_status(s)
        self.assertAlmostEqual(st.unlock_pct, 100.0, places=2)


# ---------------------------------------------------------------------------
# get_aggregate_unlock
# ---------------------------------------------------------------------------

class TestGetAggregateUnlock(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_empty_list_returns_zero(self):
        self.assertAlmostEqual(self.t.get_aggregate_unlock([], 30), 0.0)

    def test_single_mid_vest(self):
        # total=1460, duration=1460, elapsed=0 → in 30 days unlocks 30 tokens
        s = _schedule(total_tokens=1460.0, cliff_days=0,
                      vest_start_offset_days=0, vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s], 30)
        self.assertAlmostEqual(result, 30.0, places=5)

    def test_fully_vested_no_new_unlock(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-2000, vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s], 90)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_two_schedules_sum(self):
        s1 = _schedule(total_tokens=1460.0, cliff_days=0,
                       vest_start_offset_days=0, vest_duration_days=1460)
        s2 = _schedule(total_tokens=1460.0, cliff_days=0,
                       vest_start_offset_days=0, vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s1, s2], 30)
        self.assertAlmostEqual(result, 60.0, places=5)

    def test_before_cliff_horizon_within_cliff(self):
        # cliff 180, elapsed 0, horizon 30 → cliff won't be reached → 0
        s = _schedule(cliff_days=180, vest_start_offset_days=0, vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s], 30)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_before_cliff_horizon_past_cliff(self):
        # cliff 180, elapsed 0, horizon 200 → cliff passed in future → some unlock
        s = _schedule(total_tokens=1460.0, cliff_days=180, vest_start_offset_days=0,
                      vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s], 200)
        self.assertGreater(result, 0.0)

    def test_zero_horizon_returns_zero(self):
        s = _schedule(cliff_days=0, vest_start_offset_days=-100, vest_duration_days=1460)
        result = self.t.get_aggregate_unlock([s], 0)
        self.assertAlmostEqual(result, 0.0, places=5)


# ---------------------------------------------------------------------------
# upcoming_cliffs
# ---------------------------------------------------------------------------

class TestUpcomingCliffs(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()

    def test_empty_list(self):
        self.assertEqual(self.t.upcoming_cliffs([], 30), [])

    def test_cliff_already_passed_excluded(self):
        s = _schedule(cliff_days=180, vest_start_offset_days=-365, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s], 30)
        self.assertEqual(result, [])

    def test_cliff_within_window_included(self):
        # elapsed 150, cliff 180 → days_to_cliff = 30 → within 30 ✓
        s = _schedule(cliff_days=180, vest_start_offset_days=-150, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s], 30)
        self.assertEqual(len(result), 1)

    def test_cliff_just_outside_window_excluded(self):
        # elapsed 100, cliff 180 → days_to_cliff = 80 → NOT within 30
        s = _schedule(cliff_days=180, vest_start_offset_days=-100, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s], 30)
        self.assertEqual(result, [])

    def test_multiple_schedules_mixed(self):
        s_inside = _schedule(beneficiary_id="a", cliff_days=180,
                             vest_start_offset_days=-160, vest_duration_days=1460)
        s_outside = _schedule(beneficiary_id="b", cliff_days=180,
                              vest_start_offset_days=-50, vest_duration_days=1460)
        s_passed = _schedule(beneficiary_id="c", cliff_days=180,
                             vest_start_offset_days=-200, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s_inside, s_outside, s_passed], 30)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].beneficiary_id, "a")

    def test_cliff_exactly_at_window_boundary_included(self):
        # days_to_cliff exactly == within_days
        s = _schedule(cliff_days=180, vest_start_offset_days=-150, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s], 30)
        self.assertEqual(len(result), 1)

    def test_cliff_zero_not_upcoming(self):
        # cliff_days=0, so cliff passed immediately at vest start
        s = _schedule(cliff_days=0, vest_start_offset_days=-10, vest_duration_days=1460)
        result = self.t.upcoming_cliffs([s], 30)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.t = TokenVestingTracker()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "vesting_test.json"

    def _make_status(self, bid="inv_001") -> VestingStatus:
        return VestingStatus(
            beneficiary_id=bid,
            beneficiary_type="INVESTOR",
            tokens_unlocked=250_000.0,
            tokens_locked=750_000.0,
            unlock_pct=25.0,
            days_until_next_cliff=0,
            days_until_full_vest=1095,
            monthly_unlock_rate=20_547.9,
            sell_pressure="LOW",
            is_fully_vested=False,
        )

    def test_load_history_missing_returns_empty(self):
        self.assertEqual(self.t.load_history(self.data_file), [])

    def test_save_creates_file(self):
        self.t.save_results([self._make_status()], self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_and_load_roundtrip(self):
        self.t.save_results([self._make_status()], self.data_file)
        history = self.t.load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["beneficiary_id"], "inv_001")

    def test_ring_buffer_capped_at_max_entries(self):
        # Save MAX_ENTRIES + 5 entries
        for i in range(MAX_ENTRIES + 5):
            self.t.save_results([self._make_status(bid=f"b{i}")], self.data_file)
        history = self.t.load_history(self.data_file)
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.t.save_results([self._make_status()], self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_corrupt_file_returns_empty(self):
        self.data_file.write_text("not valid json")
        self.assertEqual(self.t.load_history(self.data_file), [])

    def test_save_empty_list(self):
        self.t.save_results([], self.data_file)
        history = self.t.load_history(self.data_file)
        self.assertEqual(history, [])

    def test_accumulation_across_calls(self):
        self.t.save_results([self._make_status("a")], self.data_file)
        self.t.save_results([self._make_status("b")], self.data_file)
        history = self.t.load_history(self.data_file)
        self.assertEqual(len(history), 2)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            self.t.save_results([self._make_status(bid=f"b{i}")], self.data_file)
        history = self.t.load_history(self.data_file)
        # last entry should be the very last one saved
        self.assertEqual(history[-1]["beneficiary_id"], f"b{MAX_ENTRIES + 2}")

    def test_status_fields_in_saved_json(self):
        st = self._make_status()
        self.t.save_results([st], self.data_file)
        history = self.t.load_history(self.data_file)
        entry = history[0]
        self.assertIn("timestamp", entry)
        self.assertIn("beneficiary_id", entry)
        self.assertIn("sell_pressure", entry)
        self.assertIn("is_fully_vested", entry)
        self.assertIn("monthly_unlock_rate", entry)

    def test_save_multiple_statuses(self):
        statuses = [self._make_status(bid=f"x{i}") for i in range(5)]
        self.t.save_results(statuses, self.data_file)
        history = self.t.load_history(self.data_file)
        self.assertEqual(len(history), 5)


if __name__ == "__main__":
    unittest.main()
