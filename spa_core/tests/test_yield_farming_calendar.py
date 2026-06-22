"""
Tests for MP-725: YieldFarmingCalendar
≥65 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_yield_farming_calendar -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_farming_calendar import (
    FarmingSchedule,
    MAX_ENTRIES,
    YieldFarmingCalendar,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_schedule(
    protocol="Aave",
    pool="USDC",
    current_apy=5.0,
    emission_start="2026-01-01",
    emission_end="",
    reward_token="AAVE",
    boost_multiplier=1.0,
    boost_expiry="",
    lock_expiry="",
    vesting_end="",
) -> FarmingSchedule:
    return FarmingSchedule(
        protocol=protocol,
        pool=pool,
        current_apy=current_apy,
        emission_start_iso=emission_start,
        emission_end_iso=emission_end,
        reward_token=reward_token,
        boost_multiplier=boost_multiplier,
        boost_expiry_iso=boost_expiry,
        lock_expiry_iso=lock_expiry,
        vesting_end_iso=vesting_end,
    )


TODAY = "2026-06-13"


class _WithTmpFile(unittest.TestCase):
    """Routes the calendar to a temp file."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.data_file = Path(self.tmp.name)
        self.cal = YieldFarmingCalendar(data_file=self.data_file)

    def tearDown(self):
        for p in [self.data_file, self.data_file.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()


# ===========================================================================
# 1. days_between
# ===========================================================================

class TestDaysBetween(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_same_day_is_zero(self):
        self.assertEqual(self.cal.days_between("2026-06-13", "2026-06-13"), 0)

    def test_seven_days_later(self):
        self.assertEqual(self.cal.days_between("2026-06-13", "2026-06-20"), 7)

    def test_negative_days_backward(self):
        self.assertEqual(self.cal.days_between("2026-06-20", "2026-06-13"), -7)

    def test_cross_month(self):
        self.assertEqual(self.cal.days_between("2026-06-28", "2026-07-05"), 7)

    def test_cross_year(self):
        self.assertEqual(self.cal.days_between("2026-12-31", "2027-01-01"), 1)

    def test_one_day(self):
        self.assertEqual(self.cal.days_between("2026-06-13", "2026-06-14"), 1)

    def test_30_days(self):
        self.assertEqual(self.cal.days_between("2026-06-01", "2026-07-01"), 30)


# ===========================================================================
# 2. classify_impact
# ===========================================================================

class TestClassifyImpact(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_2_days_is_critical(self):
        self.assertEqual(self.cal.classify_impact(2, -5.0), "CRITICAL")

    def test_3_days_is_critical(self):
        self.assertEqual(self.cal.classify_impact(3, -5.0), "CRITICAL")

    def test_4_days_is_high(self):
        self.assertEqual(self.cal.classify_impact(4, -5.0), "HIGH")

    def test_10_days_is_high(self):
        self.assertEqual(self.cal.classify_impact(10, -5.0), "HIGH")

    def test_14_days_is_high(self):
        self.assertEqual(self.cal.classify_impact(14, -5.0), "HIGH")

    def test_15_days_is_medium(self):
        self.assertEqual(self.cal.classify_impact(15, -5.0), "MEDIUM")

    def test_25_days_is_medium(self):
        self.assertEqual(self.cal.classify_impact(25, -5.0), "MEDIUM")

    def test_30_days_is_medium(self):
        self.assertEqual(self.cal.classify_impact(30, -5.0), "MEDIUM")

    def test_31_days_is_low(self):
        self.assertEqual(self.cal.classify_impact(31, -5.0), "LOW")

    def test_60_days_is_low(self):
        self.assertEqual(self.cal.classify_impact(60, -5.0), "LOW")

    def test_zero_days_is_critical(self):
        self.assertEqual(self.cal.classify_impact(0, -5.0), "CRITICAL")


# ===========================================================================
# 3. build_events — EMISSION_END
# ===========================================================================

class TestBuildEventsEmissionEnd(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_emission_end_5_days_away(self):
        s = make_schedule(current_apy=10.0, emission_end="2026-06-18")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertIn("EMISSION_END", types)

    def test_emission_end_days_until_correct(self):
        s = make_schedule(current_apy=10.0, emission_end="2026-06-18")
        events = self.cal.build_events(s, TODAY)
        ee = next(e for e in events if e.event_type == "EMISSION_END")
        self.assertEqual(ee.days_until, 5)

    def test_emission_end_apy_impact_70_pct(self):
        s = make_schedule(current_apy=10.0, emission_end="2026-06-18")
        events = self.cal.build_events(s, TODAY)
        ee = next(e for e in events if e.event_type == "EMISSION_END")
        self.assertAlmostEqual(ee.apy_impact_pct, -7.0, places=4)

    def test_emission_end_in_past_not_included(self):
        s = make_schedule(current_apy=10.0, emission_end="2026-06-10")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("EMISSION_END", types)

    def test_no_emission_end_no_event(self):
        s = make_schedule(emission_end="")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("EMISSION_END", types)

    def test_emission_end_impact_classified_correctly(self):
        # 2 days away → CRITICAL
        s = make_schedule(current_apy=10.0, emission_end="2026-06-15")
        events = self.cal.build_events(s, TODAY)
        ee = next(e for e in events if e.event_type == "EMISSION_END")
        self.assertEqual(ee.impact, "CRITICAL")


# ===========================================================================
# 4. build_events — REWARD_BOOST_EXPIRY
# ===========================================================================

class TestBuildEventsBoostExpiry(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_boost_expiry_20_days_away(self):
        s = make_schedule(
            current_apy=10.0,
            boost_multiplier=2.0,
            boost_expiry="2026-07-03",
        )
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertIn("REWARD_BOOST_EXPIRY", types)

    def test_boost_expiry_days_until_correct(self):
        s = make_schedule(
            current_apy=10.0,
            boost_multiplier=2.0,
            boost_expiry="2026-07-03",
        )
        events = self.cal.build_events(s, TODAY)
        be = next(e for e in events if e.event_type == "REWARD_BOOST_EXPIRY")
        self.assertEqual(be.days_until, 20)

    def test_boost_expiry_apy_impact_with_2x(self):
        # boost=2.0 → impact = -current_apy*(1-1/2) = -5.0
        s = make_schedule(current_apy=10.0, boost_multiplier=2.0, boost_expiry="2026-07-03")
        events = self.cal.build_events(s, TODAY)
        be = next(e for e in events if e.event_type == "REWARD_BOOST_EXPIRY")
        self.assertAlmostEqual(be.apy_impact_pct, -5.0, places=4)

    def test_boost_expiry_in_past_not_included(self):
        s = make_schedule(
            current_apy=10.0,
            boost_multiplier=2.0,
            boost_expiry="2026-06-10",
        )
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("REWARD_BOOST_EXPIRY", types)

    def test_no_boost_expiry_no_event(self):
        s = make_schedule(boost_expiry="")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("REWARD_BOOST_EXPIRY", types)

    def test_boost_expiry_apy_impact_no_boost(self):
        # boost=1.0 → max(1,1)=1 → impact = -(1-1/1)*apy = 0
        s = make_schedule(current_apy=10.0, boost_multiplier=1.0, boost_expiry="2026-07-03")
        events = self.cal.build_events(s, TODAY)
        be = next(e for e in events if e.event_type == "REWARD_BOOST_EXPIRY")
        self.assertAlmostEqual(be.apy_impact_pct, 0.0, places=4)


# ===========================================================================
# 5. build_events — LOCK_EXPIRY
# ===========================================================================

class TestBuildEventsLockExpiry(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_lock_expiry_included(self):
        s = make_schedule(lock_expiry="2026-06-20")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertIn("LOCK_EXPIRY", types)

    def test_lock_expiry_apy_impact_is_zero(self):
        s = make_schedule(lock_expiry="2026-06-20")
        events = self.cal.build_events(s, TODAY)
        le = next(e for e in events if e.event_type == "LOCK_EXPIRY")
        self.assertEqual(le.apy_impact_pct, 0.0)

    def test_lock_expiry_impact_always_low(self):
        s = make_schedule(lock_expiry="2026-06-20")
        events = self.cal.build_events(s, TODAY)
        le = next(e for e in events if e.event_type == "LOCK_EXPIRY")
        self.assertEqual(le.impact, "LOW")

    def test_lock_expiry_past_not_included(self):
        s = make_schedule(lock_expiry="2026-06-10")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("LOCK_EXPIRY", types)


# ===========================================================================
# 6. build_events — VESTING_COMPLETE
# ===========================================================================

class TestBuildEventsVestingComplete(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_vesting_complete_included(self):
        s = make_schedule(current_apy=10.0, vesting_end="2026-07-13")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertIn("VESTING_COMPLETE", types)

    def test_vesting_complete_apy_positive(self):
        # apy_impact = current_apy * 0.1 = 1.0
        s = make_schedule(current_apy=10.0, vesting_end="2026-07-13")
        events = self.cal.build_events(s, TODAY)
        vc = next(e for e in events if e.event_type == "VESTING_COMPLETE")
        self.assertAlmostEqual(vc.apy_impact_pct, 1.0, places=4)

    def test_vesting_complete_past_not_included(self):
        s = make_schedule(current_apy=10.0, vesting_end="2026-06-10")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("VESTING_COMPLETE", types)

    def test_vesting_complete_no_date_no_event(self):
        s = make_schedule(vesting_end="")
        events = self.cal.build_events(s, TODAY)
        types = [e.event_type for e in events]
        self.assertNotIn("VESTING_COMPLETE", types)


# ===========================================================================
# 7. events sorted by days_until
# ===========================================================================

class TestEventSorting(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_events_sorted_ascending(self):
        # emission_end in 10 days, boost_expiry in 3 days
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-23",
            boost_multiplier=2.0,
            boost_expiry="2026-06-16",
        )
        report = self.cal.analyze([s], TODAY)
        days = [e.days_until for e in report.events]
        self.assertEqual(days, sorted(days))

    def test_multiple_schedules_sorted_globally(self):
        s1 = make_schedule(protocol="A", emission_end="2026-06-20")
        s2 = make_schedule(protocol="B", emission_end="2026-06-16")
        report = self.cal.analyze([s1, s2], TODAY)
        days = [e.days_until for e in report.events]
        self.assertEqual(days, sorted(days))


# ===========================================================================
# 8. events_within_7d / events_within_30d
# ===========================================================================

class TestEventFiltering(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_event_within_7d(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-06-16")  # 3 days
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(len(report.events_within_7d), 1)

    def test_event_not_within_7d(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-06-28")  # 15 days
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(len(report.events_within_7d), 0)

    def test_event_within_30d(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-07-05")  # 22 days
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(len(report.events_within_30d), 1)

    def test_event_not_within_30d(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-08-01")  # > 30 days
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(len(report.events_within_30d), 0)

    def test_7d_is_subset_of_30d(self):
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-16",    # 3 days
            boost_expiry="2026-06-28",    # 15 days
            boost_multiplier=2.0,
        )
        report = self.cal.analyze([s], TODAY)
        self.assertLessEqual(len(report.events_within_7d), len(report.events_within_30d))


# ===========================================================================
# 9. total_at_risk_apy
# ===========================================================================

class TestTotalAtRiskAPY(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_total_at_risk_apy_sums_absolute_values(self):
        # emission_end in 10 days (within 30d) → impact = -3.5
        s = make_schedule(current_apy=5.0, emission_end="2026-06-23")  # 10 days
        report = self.cal.analyze([s], TODAY)
        # only emission_end event; |apy_impact| = 5*0.7 = 3.5
        self.assertAlmostEqual(report.total_at_risk_apy, 3.5, places=4)

    def test_total_at_risk_apy_excludes_beyond_30d(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-08-01")  # > 30 days
        report = self.cal.analyze([s], TODAY)
        self.assertAlmostEqual(report.total_at_risk_apy, 0.0, places=4)

    def test_total_at_risk_apy_sums_multiple_events(self):
        # Two events within 30d
        s = make_schedule(
            current_apy=10.0,
            emission_end="2026-06-23",       # 10 days → impact=-7
            boost_multiplier=2.0,
            boost_expiry="2026-06-20",       # 7 days → impact=-5
        )
        report = self.cal.analyze([s], TODAY)
        # total = 7 + 5 = 12
        self.assertAlmostEqual(report.total_at_risk_apy, 12.0, places=4)

    def test_total_at_risk_apy_includes_vesting_positive(self):
        # VESTING_COMPLETE within 30d adds positive APY (included as abs)
        s = make_schedule(current_apy=10.0, vesting_end="2026-06-23")  # 10 days
        report = self.cal.analyze([s], TODAY)
        # |+1.0| = 1.0
        self.assertAlmostEqual(report.total_at_risk_apy, 1.0, places=4)


# ===========================================================================
# 10. highest_urgency
# ===========================================================================

class TestHighestUrgency(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_critical_beats_high(self):
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-14",   # 1 day → CRITICAL
            lock_expiry="2026-06-27",    # 14 days → HIGH
        )
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(report.highest_urgency, "CRITICAL")

    def test_high_beats_medium(self):
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-20",   # 7 days → HIGH
            lock_expiry="2026-07-03",    # 20 days → MEDIUM
        )
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(report.highest_urgency, "HIGH")

    def test_medium_beats_low(self):
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-28",   # 15 days → MEDIUM
            lock_expiry="2026-08-01",    # > 30 days → LOW
        )
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(report.highest_urgency, "MEDIUM")

    def test_no_events_is_none_urgency(self):
        report = self.cal.analyze([], TODAY)
        self.assertEqual(report.highest_urgency, "NONE")

    def test_only_low_urgency_events(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-08-01")  # > 30 days
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(report.highest_urgency, "LOW")


# ===========================================================================
# 11. recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_critical_event_triggers_review_recommendation(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-06-14")  # 1 day → CRITICAL
        report = self.cal.analyze([s], TODAY)
        self.assertTrue(any("CRITICAL" in r for r in report.recommendations))

    def test_high_at_risk_apy_triggers_significant_risk_recommendation(self):
        # Need total_at_risk > 5 within 30d
        s = make_schedule(current_apy=10.0, emission_end="2026-06-23")  # 10 days → -7 impact
        report = self.cal.analyze([s], TODAY)
        self.assertTrue(any("Significant APY risk" in r for r in report.recommendations))

    def test_events_within_7d_triggers_repositioning_recommendation(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-06-16")  # 3 days
        report = self.cal.analyze([s], TODAY)
        self.assertTrue(any("repositioning" in r for r in report.recommendations))

    def test_no_events_no_recommendations(self):
        report = self.cal.analyze([], TODAY)
        self.assertEqual(report.recommendations, [])

    def test_far_future_event_no_repositioning_recommendation(self):
        s = make_schedule(current_apy=1.0, emission_end="2026-08-01")  # > 30 days, low impact
        report = self.cal.analyze([s], TODAY)
        self.assertFalse(any("repositioning" in r for r in report.recommendations))


# ===========================================================================
# 12. next_event
# ===========================================================================

class TestNextEvent(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_next_event_returns_closest(self):
        s = make_schedule(
            current_apy=5.0,
            emission_end="2026-06-23",       # 10 days
            boost_expiry="2026-06-16",       # 3 days
            boost_multiplier=2.0,
        )
        report = self.cal.analyze([s], TODAY)
        ne = self.cal.next_event(report)
        self.assertIsNotNone(ne)
        self.assertEqual(ne.days_until, 3)

    def test_next_event_none_when_empty(self):
        report = self.cal.analyze([], TODAY)
        self.assertIsNone(self.cal.next_event(report))

    def test_next_event_type_correct(self):
        s = make_schedule(current_apy=5.0, emission_end="2026-06-16")  # 3 days
        report = self.cal.analyze([s], TODAY)
        ne = self.cal.next_event(report)
        self.assertEqual(ne.event_type, "EMISSION_END")

    def test_next_event_single_schedule(self):
        s = make_schedule(current_apy=5.0, lock_expiry="2026-06-20")  # 7 days
        report = self.cal.analyze([s], TODAY)
        ne = self.cal.next_event(report)
        self.assertEqual(ne.days_until, 7)


# ===========================================================================
# 13. edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.cal = YieldFarmingCalendar()

    def test_no_schedules_empty_events(self):
        report = self.cal.analyze([], TODAY)
        self.assertEqual(report.events, [])

    def test_all_past_dates_no_events(self):
        s = make_schedule(
            emission_end="2026-06-01",
            boost_expiry="2026-06-01",
            boost_multiplier=2.0,
            lock_expiry="2026-06-01",
            vesting_end="2026-06-01",
        )
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(report.events, [])

    def test_today_date_included(self):
        # Event on exactly today → days_until = 0 → included
        s = make_schedule(current_apy=5.0, emission_end=TODAY)
        report = self.cal.analyze([s], TODAY)
        self.assertEqual(len([e for e in report.events if e.event_type == "EMISSION_END"]), 1)

    def test_today_event_days_until_zero(self):
        s = make_schedule(current_apy=5.0, emission_end=TODAY)
        report = self.cal.analyze([s], TODAY)
        ee = next(e for e in report.events if e.event_type == "EMISSION_END")
        self.assertEqual(ee.days_until, 0)

    def test_report_contains_all_schedules(self):
        schedules = [make_schedule(protocol=f"P{i}") for i in range(3)]
        report = self.cal.analyze(schedules, TODAY)
        self.assertEqual(len(report.schedules), 3)

    def test_report_today_iso_preserved(self):
        report = self.cal.analyze([], TODAY)
        self.assertEqual(report.today_iso, TODAY)


# ===========================================================================
# 14. save / load round-trip
# ===========================================================================

class TestSaveLoad(_WithTmpFile):

    def test_save_creates_file(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        self.assertTrue(self.data_file.exists())

    def test_saved_to_field_set(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        self.assertEqual(report.saved_to, str(self.data_file))

    def test_load_returns_list(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        history = self.cal.load_history()
        self.assertIsInstance(history, list)

    def test_save_one_load_one(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        history = self.cal.load_history()
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            self.cal.save_results(self.cal.analyze([], TODAY))
        history = self.cal.load_history()
        self.assertEqual(len(history), 5)

    def test_load_without_file_returns_empty(self):
        history = self.cal.load_history()
        self.assertEqual(history, [])

    def test_saved_entry_contains_expected_fields(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        entry = self.cal.load_history()[0]
        self.assertIn("today_iso", entry)
        self.assertIn("highest_urgency", entry)
        self.assertIn("total_at_risk_apy", entry)
        self.assertIn("timestamp", entry)

    def test_json_is_valid(self):
        report = self.cal.analyze([], TODAY)
        self.cal.save_results(report)
        raw = self.data_file.read_text()
        data = json.loads(raw)
        self.assertIsInstance(data, list)


# ===========================================================================
# 15. ring-buffer cap at 100
# ===========================================================================

class TestRingBuffer(_WithTmpFile):

    def test_ring_buffer_cap_enforced(self):
        for _ in range(MAX_ENTRIES + 20):
            self.cal.save_results(self.cal.analyze([], TODAY))
        history = self.cal.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_exactly_max_entries(self):
        for _ in range(MAX_ENTRIES + 10):
            self.cal.save_results(self.cal.analyze([], TODAY))
        history = self.cal.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
