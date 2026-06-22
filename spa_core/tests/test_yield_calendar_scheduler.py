"""
MP-833 YieldCalendarScheduler — unit tests (≥65)
Run: python3 -m unittest spa_core/tests/test_yield_calendar_scheduler.py -v
"""

import json
import os
import tempfile
import unittest
from datetime import date, timedelta

from spa_core.analytics.yield_calendar_scheduler import (
    analyze,
    log_result,
    _parse_date,
    _days_until,
    _urgency,
    _impact_label,
    _action_recommended,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_str():
    return date.today().isoformat()


def _offset(days: int, today: str = None) -> str:
    base = date.fromisoformat(today) if today else date.today()
    return (base + timedelta(days=days)).isoformat()


def _event(protocol="Proto", event_type="EPOCH_END", days_offset=10,
           impact_pct=2.0, usd=10000.0, desc="desc", today=None):
    return {
        "protocol": protocol,
        "event_type": event_type,
        "event_date": _offset(days_offset, today),
        "expected_impact_pct": impact_pct,
        "usd_value_affected": usd,
        "description": desc,
    }


TODAY = "2026-07-01"


# ---------------------------------------------------------------------------
# Unit tests: _parse_date
# ---------------------------------------------------------------------------

class TestParseDate(unittest.TestCase):
    def test_basic_parse(self):
        d = _parse_date("2026-07-01")
        self.assertEqual(d.year, 2026)
        self.assertEqual(d.month, 7)
        self.assertEqual(d.day, 1)

    def test_returns_date_object(self):
        d = _parse_date("2000-01-01")
        self.assertIsInstance(d, date)

    def test_end_of_year(self):
        d = _parse_date("2026-12-31")
        self.assertEqual(d.month, 12)
        self.assertEqual(d.day, 31)


# ---------------------------------------------------------------------------
# Unit tests: _days_until
# ---------------------------------------------------------------------------

class TestDaysUntil(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 7, 1)

    def test_future_event(self):
        ev = date(2026, 7, 11)
        self.assertEqual(_days_until(ev, self.today), 10)

    def test_past_event(self):
        ev = date(2026, 6, 21)
        self.assertEqual(_days_until(ev, self.today), -10)

    def test_same_day(self):
        self.assertEqual(_days_until(self.today, self.today), 0)

    def test_one_day_future(self):
        self.assertEqual(_days_until(date(2026, 7, 2), self.today), 1)

    def test_one_day_past(self):
        self.assertEqual(_days_until(date(2026, 6, 30), self.today), -1)


# ---------------------------------------------------------------------------
# Unit tests: _urgency
# ---------------------------------------------------------------------------

class TestUrgency(unittest.TestCase):
    def test_past(self):
        self.assertEqual(_urgency(-1, 14, 90), "PAST")

    def test_past_further(self):
        self.assertEqual(_urgency(-30, 14, 90), "PAST")

    def test_urgent_zero(self):
        self.assertEqual(_urgency(0, 14, 90), "URGENT")

    def test_urgent_at_critical(self):
        self.assertEqual(_urgency(14, 14, 90), "URGENT")

    def test_urgent_middle(self):
        self.assertEqual(_urgency(7, 14, 90), "URGENT")

    def test_upcoming_just_after_critical(self):
        self.assertEqual(_urgency(15, 14, 90), "UPCOMING")

    def test_upcoming_middle(self):
        self.assertEqual(_urgency(50, 14, 90), "UPCOMING")

    def test_upcoming_at_horizon(self):
        self.assertEqual(_urgency(90, 14, 90), "UPCOMING")

    def test_distant_just_over_horizon(self):
        self.assertEqual(_urgency(91, 14, 90), "DISTANT")

    def test_distant_far(self):
        self.assertEqual(_urgency(365, 14, 90), "DISTANT")

    def test_custom_critical(self):
        self.assertEqual(_urgency(5, 7, 30), "URGENT")

    def test_custom_critical_boundary(self):
        self.assertEqual(_urgency(8, 7, 30), "UPCOMING")

    def test_custom_horizon_boundary(self):
        self.assertEqual(_urgency(30, 7, 30), "UPCOMING")

    def test_custom_horizon_over(self):
        self.assertEqual(_urgency(31, 7, 30), "DISTANT")


# ---------------------------------------------------------------------------
# Unit tests: _impact_label
# ---------------------------------------------------------------------------

class TestImpactLabel(unittest.TestCase):
    def test_major_positive_exact(self):
        self.assertEqual(_impact_label(5.0), "MAJOR_POSITIVE")

    def test_major_positive_above(self):
        self.assertEqual(_impact_label(10.0), "MAJOR_POSITIVE")

    def test_minor_positive(self):
        self.assertEqual(_impact_label(0.1), "MINOR_POSITIVE")

    def test_minor_positive_near_major(self):
        self.assertEqual(_impact_label(4.99), "MINOR_POSITIVE")

    def test_neutral(self):
        self.assertEqual(_impact_label(0.0), "NEUTRAL")

    def test_minor_negative(self):
        self.assertEqual(_impact_label(-0.5), "MINOR_NEGATIVE")

    def test_minor_negative_near_major(self):
        self.assertEqual(_impact_label(-4.99), "MINOR_NEGATIVE")

    def test_major_negative_exact(self):
        self.assertEqual(_impact_label(-5.0), "MAJOR_NEGATIVE")

    def test_major_negative_below(self):
        self.assertEqual(_impact_label(-10.0), "MAJOR_NEGATIVE")


# ---------------------------------------------------------------------------
# Unit tests: _action_recommended
# ---------------------------------------------------------------------------

class TestActionRecommended(unittest.TestCase):
    def test_major_positive_urgent(self):
        r = _action_recommended("EPOCH_END", "URGENT", "MAJOR_POSITIVE", "2026-07-10")
        self.assertIn("Prepare to capture yield boost", r)
        self.assertIn("2026-07-10", r)

    def test_major_positive_upcoming(self):
        r = _action_recommended("EPOCH_END", "UPCOMING", "MAJOR_POSITIVE", "2026-08-01")
        self.assertIn("Monitor and plan position increase", r)

    def test_major_negative_urgent(self):
        r = _action_recommended("EMISSION_CHANGE", "URGENT", "MAJOR_NEGATIVE", "2026-07-05")
        self.assertIn("Consider exit or hedge", r)

    def test_major_negative_upcoming(self):
        r = _action_recommended("EMISSION_CHANGE", "UPCOMING", "MAJOR_NEGATIVE", "2026-09-01")
        self.assertIn("significant yield drop expected", r)

    def test_token_unlock_urgent(self):
        r = _action_recommended("TOKEN_UNLOCK", "URGENT", "MINOR_NEGATIVE", "2026-07-08")
        self.assertIn("token price impact from unlock", r)

    def test_token_unlock_upcoming(self):
        r = _action_recommended("TOKEN_UNLOCK", "UPCOMING", "NEUTRAL", "2026-08-15")
        self.assertIn("token price impact from unlock", r)

    def test_vesting_cliff_urgent(self):
        r = _action_recommended("VESTING_CLIFF", "URGENT", "NEUTRAL", "2026-07-06")
        self.assertIn("selling pressure at cliff", r)

    def test_vesting_cliff_upcoming(self):
        r = _action_recommended("VESTING_CLIFF", "UPCOMING", "MINOR_NEGATIVE", "2026-08-20")
        self.assertIn("selling pressure at cliff", r)

    def test_past(self):
        r = _action_recommended("EPOCH_END", "PAST", "MINOR_POSITIVE", "2026-06-01")
        self.assertIn("already occurred", r)

    def test_default_monitor(self):
        r = _action_recommended("REWARD_DISTRIBUTION", "DISTANT", "MINOR_POSITIVE", "2026-12-01")
        self.assertIn("Monitor event scheduled for", r)
        self.assertIn("2026-12-01", r)


# ---------------------------------------------------------------------------
# Tests: analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([], {"today": TODAY})

    def test_events_empty(self):
        self.assertEqual(self.result["events"], [])

    def test_urgent_count_zero(self):
        self.assertEqual(self.result["urgent_count"], 0)

    def test_upcoming_count_zero(self):
        self.assertEqual(self.result["upcoming_count"], 0)

    def test_next_event_none(self):
        self.assertIsNone(self.result["next_event"])

    def test_highest_impact_none(self):
        self.assertIsNone(self.result["highest_impact_event"])

    def test_usd_at_risk_zero(self):
        self.assertEqual(self.result["total_usd_at_risk"], 0.0)

    def test_usd_opportunity_zero(self):
        self.assertEqual(self.result["total_usd_opportunity"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)


# ---------------------------------------------------------------------------
# Tests: analyze() — single event
# ---------------------------------------------------------------------------

class TestAnalyzeSingleEvent(unittest.TestCase):
    def setUp(self):
        ev = _event(days_offset=5, impact_pct=6.0, usd=50000.0, today=TODAY)
        self.result = analyze([ev], {"today": TODAY})

    def test_one_event(self):
        self.assertEqual(len(self.result["events"]), 1)

    def test_urgency_urgent(self):
        self.assertEqual(self.result["events"][0]["urgency"], "URGENT")

    def test_days_until_five(self):
        self.assertEqual(self.result["events"][0]["days_until"], 5)

    def test_not_past(self):
        self.assertFalse(self.result["events"][0]["is_past"])

    def test_impact_major_positive(self):
        self.assertEqual(self.result["events"][0]["impact_label"], "MAJOR_POSITIVE")

    def test_urgent_count(self):
        self.assertEqual(self.result["urgent_count"], 1)

    def test_upcoming_count_zero(self):
        self.assertEqual(self.result["upcoming_count"], 0)

    def test_next_event_is_this_event(self):
        self.assertIsNotNone(self.result["next_event"])
        self.assertEqual(self.result["next_event"]["days_until"], 5)

    def test_usd_opportunity(self):
        self.assertEqual(self.result["total_usd_opportunity"], 50000.0)

    def test_usd_at_risk_zero(self):
        self.assertEqual(self.result["total_usd_at_risk"], 0.0)

    def test_action_contains_date(self):
        self.assertIn(_offset(5, TODAY), self.result["events"][0]["action_recommended"])


# ---------------------------------------------------------------------------
# Tests: analyze() — mixed events
# ---------------------------------------------------------------------------

class TestAnalyzeMixed(unittest.TestCase):
    def setUp(self):
        events = [
            _event("Aave", "EPOCH_END",        days_offset=7,   impact_pct=6.0,  usd=40000, today=TODAY),
            _event("Compound", "TOKEN_UNLOCK",  days_offset=30,  impact_pct=-3.0, usd=20000, today=TODAY),
            _event("Morpho", "EMISSION_CHANGE", days_offset=120, impact_pct=-8.0, usd=30000, today=TODAY),
            _event("Yearn", "VESTING_CLIFF",    days_offset=-5,  impact_pct=1.0,  usd=5000,  today=TODAY),
        ]
        self.result = analyze(events, {"today": TODAY})

    def test_event_count(self):
        self.assertEqual(len(self.result["events"]), 4)

    def test_sorted_by_days_until(self):
        days = [e["days_until"] for e in self.result["events"]]
        self.assertEqual(days, sorted(days))

    def test_past_event_detected(self):
        past = [e for e in self.result["events"] if e["is_past"]]
        self.assertEqual(len(past), 1)
        self.assertEqual(past[0]["protocol"], "Yearn")

    def test_urgent_count(self):
        self.assertEqual(self.result["urgent_count"], 1)

    def test_upcoming_count(self):
        self.assertEqual(self.result["upcoming_count"], 1)

    def test_distant_count(self):
        distant = [e for e in self.result["events"] if e["urgency"] == "DISTANT"]
        self.assertEqual(len(distant), 1)

    def test_next_event_is_soonest_future(self):
        ne = self.result["next_event"]
        self.assertIsNotNone(ne)
        self.assertEqual(ne["protocol"], "Aave")
        self.assertEqual(ne["days_until"], 7)

    def test_highest_impact_event(self):
        hi = self.result["highest_impact_event"]
        self.assertIsNotNone(hi)
        # abs(-8.0) is highest
        self.assertEqual(hi["protocol"], "Morpho")

    def test_usd_at_risk_includes_negatives(self):
        # Compound (-3, 20000) + Morpho (-8, 30000) = 50000
        self.assertAlmostEqual(self.result["total_usd_at_risk"], 50000.0)

    def test_usd_opportunity_includes_positives(self):
        # Aave (6.0, 40000) + Yearn (1.0, 5000) = 45000
        self.assertAlmostEqual(self.result["total_usd_opportunity"], 45000.0)

    def test_all_urgency_values_present(self):
        urgencies = {e["urgency"] for e in self.result["events"]}
        self.assertIn("PAST", urgencies)
        self.assertIn("URGENT", urgencies)
        self.assertIn("UPCOMING", urgencies)
        self.assertIn("DISTANT", urgencies)


# ---------------------------------------------------------------------------
# Tests: analyze() — urgency boundaries
# ---------------------------------------------------------------------------

class TestUrgencyBoundaries(unittest.TestCase):
    def _analyze_one(self, days_offset, critical=14, horizon=90):
        ev = _event(days_offset=days_offset, today=TODAY)
        r = analyze([ev], {"today": TODAY, "critical_days": critical, "horizon_days": horizon})
        return r["events"][0]

    def test_day_zero_is_urgent(self):
        e = self._analyze_one(0)
        self.assertEqual(e["urgency"], "URGENT")

    def test_day_critical_is_urgent(self):
        e = self._analyze_one(14)
        self.assertEqual(e["urgency"], "URGENT")

    def test_day_critical_plus_one_is_upcoming(self):
        e = self._analyze_one(15)
        self.assertEqual(e["urgency"], "UPCOMING")

    def test_day_horizon_is_upcoming(self):
        e = self._analyze_one(90)
        self.assertEqual(e["urgency"], "UPCOMING")

    def test_day_horizon_plus_one_is_distant(self):
        e = self._analyze_one(91)
        self.assertEqual(e["urgency"], "DISTANT")

    def test_negative_one_is_past(self):
        e = self._analyze_one(-1)
        self.assertEqual(e["urgency"], "PAST")
        self.assertTrue(e["is_past"])

    def test_custom_critical_days(self):
        e = self._analyze_one(5, critical=7, horizon=30)
        self.assertEqual(e["urgency"], "URGENT")

    def test_custom_horizon_days(self):
        e = self._analyze_one(25, critical=7, horizon=30)
        self.assertEqual(e["urgency"], "UPCOMING")


# ---------------------------------------------------------------------------
# Tests: analyze() — impact labels
# ---------------------------------------------------------------------------

class TestImpactLabels(unittest.TestCase):
    def _label(self, pct):
        ev = _event(impact_pct=pct, days_offset=10, today=TODAY)
        r = analyze([ev], {"today": TODAY})
        return r["events"][0]["impact_label"]

    def test_exact_5_major_positive(self):
        self.assertEqual(self._label(5.0), "MAJOR_POSITIVE")

    def test_above_5_major_positive(self):
        self.assertEqual(self._label(20.0), "MAJOR_POSITIVE")

    def test_just_below_5_minor_positive(self):
        self.assertEqual(self._label(4.99), "MINOR_POSITIVE")

    def test_tiny_positive_minor(self):
        self.assertEqual(self._label(0.01), "MINOR_POSITIVE")

    def test_zero_neutral(self):
        self.assertEqual(self._label(0.0), "NEUTRAL")

    def test_tiny_negative_minor(self):
        self.assertEqual(self._label(-0.01), "MINOR_NEGATIVE")

    def test_just_above_minus5_minor_negative(self):
        self.assertEqual(self._label(-4.99), "MINOR_NEGATIVE")

    def test_exact_minus5_major_negative(self):
        self.assertEqual(self._label(-5.0), "MAJOR_NEGATIVE")

    def test_below_minus5_major_negative(self):
        self.assertEqual(self._label(-15.0), "MAJOR_NEGATIVE")


# ---------------------------------------------------------------------------
# Tests: analyze() — action_recommended
# ---------------------------------------------------------------------------

class TestActionRecommendedIntegration(unittest.TestCase):
    def _action(self, event_type="EPOCH_END", days_offset=5, impact_pct=6.0):
        ev = _event(event_type=event_type, days_offset=days_offset, impact_pct=impact_pct, today=TODAY)
        r = analyze([ev], {"today": TODAY})
        return r["events"][0]["action_recommended"]

    def test_major_positive_urgent_action(self):
        a = self._action("EPOCH_END", 5, 6.0)
        self.assertIn("Prepare to capture yield boost", a)

    def test_major_positive_upcoming_action(self):
        a = self._action("EPOCH_END", 20, 6.0)
        self.assertIn("Monitor and plan position increase", a)

    def test_major_negative_urgent_action(self):
        a = self._action("EMISSION_CHANGE", 5, -8.0)
        self.assertIn("Consider exit or hedge", a)

    def test_major_negative_upcoming_action(self):
        a = self._action("EMISSION_CHANGE", 20, -8.0)
        self.assertIn("significant yield drop expected", a)

    def test_token_unlock_urgent_action(self):
        a = self._action("TOKEN_UNLOCK", 5, -2.0)
        self.assertIn("token price impact from unlock", a)

    def test_vesting_cliff_upcoming_action(self):
        a = self._action("VESTING_CLIFF", 20, 0.0)
        self.assertIn("selling pressure at cliff", a)

    def test_past_event_action(self):
        a = self._action("EPOCH_END", -5, 2.0)
        self.assertIn("already occurred", a)

    def test_distant_default_action(self):
        a = self._action("REWARD_DISTRIBUTION", 100, 1.0)
        self.assertIn("Monitor event scheduled for", a)


# ---------------------------------------------------------------------------
# Tests: analyze() — config defaults
# ---------------------------------------------------------------------------

class TestConfigDefaults(unittest.TestCase):
    def test_no_config_runs_without_error(self):
        ev = _event(days_offset=5)
        r = analyze([ev])
        self.assertIn("events", r)
        self.assertEqual(len(r["events"]), 1)

    def test_default_horizon_90(self):
        # Day 89 → UPCOMING, Day 91 → DISTANT
        ev89 = _event(days_offset=89, today=TODAY)
        ev91 = _event(days_offset=91, today=TODAY)
        r = analyze([ev89, ev91], {"today": TODAY})
        urgencies = {e["days_until"]: e["urgency"] for e in r["events"]}
        self.assertEqual(urgencies[89], "UPCOMING")
        self.assertEqual(urgencies[91], "DISTANT")

    def test_default_critical_14(self):
        ev14 = _event(days_offset=14, today=TODAY)
        ev15 = _event(days_offset=15, today=TODAY)
        r = analyze([ev14, ev15], {"today": TODAY})
        urgencies = {e["days_until"]: e["urgency"] for e in r["events"]}
        self.assertEqual(urgencies[14], "URGENT")
        self.assertEqual(urgencies[15], "UPCOMING")


# ---------------------------------------------------------------------------
# Tests: analyze() — next_event and highest_impact_event
# ---------------------------------------------------------------------------

class TestNextAndHighestEvent(unittest.TestCase):
    def test_next_event_skips_past(self):
        events = [
            _event(days_offset=-10, impact_pct=10.0, today=TODAY),
            _event(days_offset=3,   impact_pct=1.0,  today=TODAY),
            _event(days_offset=20,  impact_pct=2.0,  today=TODAY),
        ]
        r = analyze(events, {"today": TODAY})
        self.assertEqual(r["next_event"]["days_until"], 3)

    def test_next_event_all_past_is_none(self):
        events = [_event(days_offset=-5, today=TODAY), _event(days_offset=-1, today=TODAY)]
        r = analyze(events, {"today": TODAY})
        self.assertIsNone(r["next_event"])

    def test_highest_impact_picks_max_abs(self):
        events = [
            _event(days_offset=10, impact_pct=3.0,  today=TODAY),
            _event(days_offset=20, impact_pct=-7.0, today=TODAY),
            _event(days_offset=30, impact_pct=4.0,  today=TODAY),
        ]
        r = analyze(events, {"today": TODAY})
        # abs(-7.0)=7 is highest
        self.assertEqual(r["highest_impact_event"]["expected_impact_pct"], -7.0)

    def test_highest_impact_single_event(self):
        ev = _event(days_offset=5, impact_pct=2.5, today=TODAY)
        r = analyze([ev], {"today": TODAY})
        self.assertEqual(r["highest_impact_event"]["expected_impact_pct"], 2.5)


# ---------------------------------------------------------------------------
# Tests: analyze() — output fields completeness
# ---------------------------------------------------------------------------

class TestOutputFieldsCompleteness(unittest.TestCase):
    def setUp(self):
        ev = _event(days_offset=5, today=TODAY)
        self.result = analyze([ev], {"today": TODAY})
        self.event = self.result["events"][0]

    def test_top_level_keys(self):
        expected = {
            "events", "urgent_count", "upcoming_count", "next_event",
            "highest_impact_event", "total_usd_at_risk", "total_usd_opportunity", "timestamp"
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_event_keys(self):
        expected = {
            "protocol", "event_type", "event_date", "days_until", "is_past",
            "urgency", "expected_impact_pct", "usd_value_affected",
            "impact_label", "description", "action_recommended"
        }
        self.assertEqual(set(self.event.keys()), expected)

    def test_event_types_preserved(self):
        self.assertIsInstance(self.event["days_until"], int)
        self.assertIsInstance(self.event["is_past"], bool)
        self.assertIsInstance(self.event["expected_impact_pct"], float)
        self.assertIsInstance(self.event["usd_value_affected"], float)

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)
        self.assertGreater(self.result["timestamp"], 0)


# ---------------------------------------------------------------------------
# Tests: log_result() — ring-buffer and atomic write
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_result(self):
        return analyze([_event(days_offset=5, today=TODAY)], {"today": TODAY})

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "yield_calendar_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_calendar_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_first_entry_has_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_calendar_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "urgent_count", "upcoming_count",
                    "total_usd_at_risk", "total_usd_opportunity", "event_count"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_calendar_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_calendar_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["urgent_count"] = i  # unique marker
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_calendar_log.json")) as f:
            data = json.load(f)
        # Latest entry should have urgent_count = 104
        self.assertEqual(data[-1]["urgent_count"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".yield_calendar_log_") and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_existing_non_list_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "yield_calendar_log.json")
        with open(log_path, "w") as f:
            f.write("{}")  # corrupt / wrong type
        # Should not raise
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# Tests: analyze() — USD sums
# ---------------------------------------------------------------------------

class TestUsdSums(unittest.TestCase):
    def test_all_positive_impact(self):
        events = [_event(days_offset=i + 1, impact_pct=2.0, usd=1000.0, today=TODAY) for i in range(3)]
        r = analyze(events, {"today": TODAY})
        self.assertAlmostEqual(r["total_usd_opportunity"], 3000.0)
        self.assertAlmostEqual(r["total_usd_at_risk"], 0.0)

    def test_all_negative_impact(self):
        events = [_event(days_offset=i + 1, impact_pct=-2.0, usd=1000.0, today=TODAY) for i in range(3)]
        r = analyze(events, {"today": TODAY})
        self.assertAlmostEqual(r["total_usd_at_risk"], 3000.0)
        self.assertAlmostEqual(r["total_usd_opportunity"], 0.0)

    def test_neutral_not_counted(self):
        ev = _event(days_offset=5, impact_pct=0.0, usd=5000.0, today=TODAY)
        r = analyze([ev], {"today": TODAY})
        self.assertAlmostEqual(r["total_usd_at_risk"], 0.0)
        self.assertAlmostEqual(r["total_usd_opportunity"], 0.0)

    def test_past_events_included_in_sums(self):
        # Past events with negative impact still count toward at-risk
        ev = _event(days_offset=-5, impact_pct=-3.0, usd=10000.0, today=TODAY)
        r = analyze([ev], {"today": TODAY})
        self.assertAlmostEqual(r["total_usd_at_risk"], 10000.0)


# ---------------------------------------------------------------------------
# Tests: analyze() — sorting
# ---------------------------------------------------------------------------

class TestSorting(unittest.TestCase):
    def test_events_sorted_ascending(self):
        days_offsets = [50, -3, 10, 100, 0, -10, 30]
        events = [_event(days_offset=d, today=TODAY) for d in days_offsets]
        r = analyze(events, {"today": TODAY})
        days = [e["days_until"] for e in r["events"]]
        self.assertEqual(days, sorted(days))

    def test_past_events_come_first(self):
        events = [
            _event(days_offset=10, today=TODAY),
            _event(days_offset=-5, today=TODAY),
        ]
        r = analyze(events, {"today": TODAY})
        self.assertEqual(r["events"][0]["days_until"], -5)


# ---------------------------------------------------------------------------
# Tests: all valid event types
# ---------------------------------------------------------------------------

class TestEventTypes(unittest.TestCase):
    def test_all_event_types_accepted(self):
        for et in ("EPOCH_END", "TOKEN_UNLOCK", "VESTING_CLIFF", "EMISSION_CHANGE", "REWARD_DISTRIBUTION"):
            ev = _event(event_type=et, days_offset=5, today=TODAY)
            r = analyze([ev], {"today": TODAY})
            self.assertEqual(r["events"][0]["event_type"], et)


if __name__ == "__main__":
    unittest.main(verbosity=2)
