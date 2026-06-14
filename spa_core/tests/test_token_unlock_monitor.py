"""
Tests for MP-781: TokenUnlockMonitor
≥65 unittest tests covering validation, computation, risk levels,
sell pressure scoring, upcoming unlock filtering, high-risk filtering,
atomic write, ring buffer, edge cases, and integration scenarios.
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.token_unlock_monitor import (
    TokenUnlockMonitor,
    monitor as monitor_fn,
    _validate_event,
    _days_until_unlock,
    _sell_pressure_score,
    _risk_level,
    _enrich_event,
    _atomic_write_json,
    _load_log,
    _append_log,
    SECONDS_PER_DAY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0  # fixed reference timestamp for deterministic tests


def _ev(
    protocol="TestProto",
    unlock_days_from_now=60,
    unlock_amount_tokens=1_000_000,
    current_price_usd=1.0,
    circulating_supply=100_000_000,
    category="INVESTOR",
    now=_NOW,
):
    return {
        "protocol": protocol,
        "unlock_date_ts": now + unlock_days_from_now * SECONDS_PER_DAY,
        "unlock_amount_tokens": unlock_amount_tokens,
        "current_price_usd": current_price_usd,
        "circulating_supply": circulating_supply,
        "category": category,
    }


class TempDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# 1. _validate_event
# ===========================================================================

class TestValidateEvent(unittest.TestCase):

    def test_valid_event_passes(self):
        _validate_event(_ev())  # should not raise

    def test_missing_protocol_raises(self):
        ev = _ev()
        del ev["protocol"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_missing_unlock_date_ts_raises(self):
        ev = _ev()
        del ev["unlock_date_ts"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_missing_unlock_amount_raises(self):
        ev = _ev()
        del ev["unlock_amount_tokens"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_missing_price_raises(self):
        ev = _ev()
        del ev["current_price_usd"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_missing_supply_raises(self):
        ev = _ev()
        del ev["circulating_supply"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_missing_category_raises(self):
        ev = _ev()
        del ev["category"]
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_invalid_category_raises(self):
        ev = _ev(category="WHALE")
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_negative_amount_raises(self):
        ev = _ev(unlock_amount_tokens=-1)
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_negative_price_raises(self):
        ev = _ev(current_price_usd=-0.01)
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_zero_supply_raises(self):
        ev = _ev(circulating_supply=0)
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_negative_supply_raises(self):
        ev = _ev(circulating_supply=-1)
        with self.assertRaises(ValueError):
            _validate_event(ev)

    def test_all_valid_categories_pass(self):
        for cat in ("TEAM", "INVESTOR", "ECOSYSTEM", "PUBLIC"):
            _validate_event(_ev(category=cat))  # should not raise

    def test_zero_amount_valid(self):
        ev = _ev(unlock_amount_tokens=0)
        _validate_event(ev)  # should not raise

    def test_zero_price_valid(self):
        ev = _ev(current_price_usd=0.0)
        _validate_event(ev)  # should not raise


# ===========================================================================
# 2. _days_until_unlock
# ===========================================================================

class TestDaysUntilUnlock(unittest.TestCase):

    def test_future_event_positive(self):
        now = _NOW
        unlock = now + 30 * SECONDS_PER_DAY
        self.assertAlmostEqual(_days_until_unlock(unlock, now), 30.0, places=4)

    def test_past_event_negative(self):
        now = _NOW
        unlock = now - 10 * SECONDS_PER_DAY
        self.assertAlmostEqual(_days_until_unlock(unlock, now), -10.0, places=4)

    def test_exact_now_zero(self):
        self.assertAlmostEqual(_days_until_unlock(_NOW, _NOW), 0.0, places=6)

    def test_fractional_days(self):
        now = _NOW
        unlock = now + 1.5 * SECONDS_PER_DAY
        self.assertAlmostEqual(_days_until_unlock(unlock, now), 1.5, places=4)

    def test_uses_time_time_if_no_now_ts(self):
        future = time.time() + 100 * SECONDS_PER_DAY
        result = _days_until_unlock(future)
        self.assertGreater(result, 90)


# ===========================================================================
# 3. _sell_pressure_score
# ===========================================================================

class TestSellPressureScore(unittest.TestCase):

    def test_team_category_scores_higher_than_public(self):
        team_score = _sell_pressure_score(10.0, 30.0, "TEAM")
        pub_score = _sell_pressure_score(10.0, 30.0, "PUBLIC")
        self.assertGreater(team_score, pub_score)

    def test_investor_scores_higher_than_ecosystem(self):
        inv_score = _sell_pressure_score(5.0, 60.0, "INVESTOR")
        eco_score = _sell_pressure_score(5.0, 60.0, "ECOSYSTEM")
        self.assertGreater(inv_score, eco_score)

    def test_score_capped_at_100(self):
        score = _sell_pressure_score(100.0, 0.0, "TEAM")
        self.assertLessEqual(score, 100.0)

    def test_score_non_negative(self):
        score = _sell_pressure_score(0.0, 999.0, "PUBLIC")
        self.assertGreaterEqual(score, 0.0)

    def test_higher_dilution_raises_score(self):
        low_dil = _sell_pressure_score(1.0, 60.0, "INVESTOR")
        high_dil = _sell_pressure_score(15.0, 60.0, "INVESTOR")
        self.assertGreater(high_dil, low_dil)

    def test_closer_unlock_raises_score(self):
        far = _sell_pressure_score(10.0, 365.0, "TEAM")
        near = _sell_pressure_score(10.0, 5.0, "TEAM")
        self.assertGreater(near, far)

    def test_already_unlocked_highest_urgency(self):
        past = _sell_pressure_score(10.0, -1.0, "TEAM")
        future = _sell_pressure_score(10.0, 100.0, "TEAM")
        self.assertGreater(past, future)

    def test_zero_dilution_zero_days_still_produces_score(self):
        score = _sell_pressure_score(0.0, 0.0, "TEAM")
        self.assertGreater(score, 0.0)

    def test_score_is_float(self):
        score = _sell_pressure_score(5.0, 30.0, "INVESTOR")
        self.assertIsInstance(score, float)

    def test_public_short_horizon_still_reasonable(self):
        score = _sell_pressure_score(5.0, 5.0, "PUBLIC")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ===========================================================================
# 4. _risk_level
# ===========================================================================

class TestRiskLevel(unittest.TestCase):

    def test_critical_high_dilution_near(self):
        self.assertEqual(_risk_level(25.0, 20.0), "CRITICAL")

    def test_high_medium_dilution_near(self):
        self.assertEqual(_risk_level(12.0, 25.0), "HIGH")

    def test_high_large_dilution_medium_horizon(self):
        self.assertEqual(_risk_level(22.0, 60.0), "HIGH")

    def test_medium_medium_dilution_medium_horizon(self):
        self.assertEqual(_risk_level(6.0, 45.0), "MEDIUM")

    def test_medium_large_dilution_long_horizon(self):
        self.assertEqual(_risk_level(12.0, 120.0), "MEDIUM")

    def test_low_small_dilution_far_future(self):
        self.assertEqual(_risk_level(1.0, 365.0), "LOW")

    def test_low_zero_dilution(self):
        self.assertEqual(_risk_level(0.0, 365.0), "LOW")

    def test_low_small_dilution_any_horizon(self):
        self.assertEqual(_risk_level(2.0, 500.0), "LOW")

    def test_boundary_critical(self):
        # exactly at 20% dilution, 29 days → CRITICAL
        self.assertEqual(_risk_level(20.1, 29.0), "CRITICAL")

    def test_boundary_not_critical_at_30_days(self):
        # exactly 30 days: spec says < 30 for CRITICAL
        result = _risk_level(25.0, 30.0)
        # at 30 days exactly, CRITICAL threshold not met (< 30)
        self.assertNotEqual(result, "CRITICAL")

    def test_return_type_is_string(self):
        self.assertIsInstance(_risk_level(5.0, 50.0), str)

    def test_valid_return_values(self):
        for dilution, days in [(0.5, 500), (5.0, 60), (11.0, 20), (25.0, 10)]:
            level = _risk_level(dilution, days)
            self.assertIn(level, {"LOW", "MEDIUM", "HIGH", "CRITICAL"})


# ===========================================================================
# 5. _enrich_event
# ===========================================================================

class TestEnrichEvent(unittest.TestCase):

    def test_enriched_has_unlock_value_usd(self):
        ev = _ev(unlock_amount_tokens=1_000_000, current_price_usd=2.0)
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertAlmostEqual(enriched["unlock_value_usd"], 2_000_000.0, places=2)

    def test_enriched_has_dilution_pct(self):
        ev = _ev(unlock_amount_tokens=1_000_000, circulating_supply=10_000_000)
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertAlmostEqual(enriched["dilution_pct"], 10.0, places=4)

    def test_enriched_has_days_until_unlock(self):
        ev = _ev(unlock_days_from_now=30, now=_NOW)
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertAlmostEqual(enriched["days_until_unlock"], 30.0, places=4)

    def test_enriched_has_sell_pressure_score(self):
        ev = _ev()
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertIn("sell_pressure_score", enriched)
        self.assertGreaterEqual(enriched["sell_pressure_score"], 0.0)
        self.assertLessEqual(enriched["sell_pressure_score"], 100.0)

    def test_enriched_has_risk_level(self):
        ev = _ev()
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertIn(enriched["risk_level"], {"LOW", "MEDIUM", "HIGH", "CRITICAL"})

    def test_original_fields_preserved(self):
        ev = _ev(protocol="TestProto")
        enriched = _enrich_event(ev, now_ts=_NOW)
        self.assertEqual(enriched["protocol"], "TestProto")

    def test_invalid_event_raises(self):
        ev = _ev()
        del ev["protocol"]
        with self.assertRaises(ValueError):
            _enrich_event(ev, now_ts=_NOW)


# ===========================================================================
# 6. TokenUnlockMonitor.monitor()
# ===========================================================================

class TestMonitorMethod(unittest.TestCase):

    def setUp(self):
        self.mon = TokenUnlockMonitor()

    def test_empty_events_returns_structure(self):
        result = self.mon.monitor([], now_ts=_NOW)
        self.assertIn("events", result)
        self.assertIn("summary", result)
        self.assertEqual(result["event_count"], 0)

    def test_events_enriched(self):
        result = self.mon.monitor([_ev()], now_ts=_NOW)
        ev = result["events"][0]
        self.assertIn("unlock_value_usd", ev)
        self.assertIn("dilution_pct", ev)
        self.assertIn("days_until_unlock", ev)
        self.assertIn("sell_pressure_score", ev)
        self.assertIn("risk_level", ev)

    def test_events_sorted_by_days_until(self):
        events = [
            _ev(unlock_days_from_now=90, now=_NOW),
            _ev(unlock_days_from_now=10, now=_NOW),
            _ev(unlock_days_from_now=45, now=_NOW),
        ]
        result = self.mon.monitor(events, now_ts=_NOW)
        days = [e["days_until_unlock"] for e in result["events"]]
        self.assertEqual(days, sorted(days))

    def test_event_count_matches(self):
        events = [_ev() for _ in range(5)]
        result = self.mon.monitor(events, now_ts=_NOW)
        self.assertEqual(result["event_count"], 5)

    def test_timestamp_utc_from_now_ts(self):
        result = self.mon.monitor([], now_ts=_NOW)
        self.assertAlmostEqual(result["timestamp_utc"], _NOW, places=1)

    def test_invalid_event_raises(self):
        ev = _ev()
        del ev["category"]
        with self.assertRaises(ValueError):
            self.mon.monitor([ev], now_ts=_NOW)

    def test_multiple_events_processed(self):
        events = [
            _ev(protocol="A", category="TEAM", unlock_days_from_now=20, now=_NOW),
            _ev(protocol="B", category="PUBLIC", unlock_days_from_now=100, now=_NOW),
        ]
        result = self.mon.monitor(events, now_ts=_NOW)
        self.assertEqual(result["event_count"], 2)

    def test_result_stored_in_last_result(self):
        self.mon.monitor([_ev()], now_ts=_NOW)
        self.assertIsNotNone(self.mon._last_result)


# ===========================================================================
# 7. Summary block
# ===========================================================================

class TestSummaryBlock(unittest.TestCase):

    def test_empty_summary_structure(self):
        mon = TokenUnlockMonitor()
        result = mon.monitor([], now_ts=_NOW)
        summary = result["summary"]
        self.assertEqual(summary["total_events"], 0)
        self.assertEqual(summary["total_unlock_value_usd"], 0.0)
        self.assertIsNone(summary["highest_risk_protocol"])

    def test_total_unlock_value_usd_sum(self):
        events = [
            _ev(unlock_amount_tokens=1_000_000, current_price_usd=2.0),
            _ev(unlock_amount_tokens=500_000, current_price_usd=4.0),
        ]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        # 1M*2 + 500k*4 = 2M + 2M = 4M
        self.assertAlmostEqual(result["summary"]["total_unlock_value_usd"], 4_000_000.0, places=2)

    def test_risk_breakdown_counts(self):
        events = [
            _ev(unlock_amount_tokens=25_000_000, circulating_supply=100_000_000,
                category="TEAM", unlock_days_from_now=10, now=_NOW),  # CRITICAL (25% <30d)
            _ev(unlock_amount_tokens=1_000_000, circulating_supply=100_000_000,
                category="PUBLIC", unlock_days_from_now=365, now=_NOW),  # LOW
        ]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        rb = result["summary"]["risk_breakdown"]
        self.assertEqual(rb["CRITICAL"], 1)
        self.assertEqual(rb["LOW"], 1)

    def test_highest_risk_protocol_is_max_score(self):
        events = [
            _ev(protocol="HighRisk", unlock_amount_tokens=30_000_000,
                circulating_supply=100_000_000, category="TEAM",
                unlock_days_from_now=5, now=_NOW),
            _ev(protocol="LowRisk", unlock_amount_tokens=100_000,
                circulating_supply=100_000_000, category="PUBLIC",
                unlock_days_from_now=300, now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        self.assertEqual(result["summary"]["highest_risk_protocol"], "HighRisk")

    def test_avg_sell_pressure_score_is_mean(self):
        events = [_ev(category="TEAM"), _ev(category="PUBLIC")]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        enriched = result["events"]
        expected_avg = sum(e["sell_pressure_score"] for e in enriched) / len(enriched)
        self.assertAlmostEqual(
            result["summary"]["avg_sell_pressure_score"], expected_avg, places=2
        )

    def test_max_sell_pressure_score_is_max(self):
        events = [_ev(category="TEAM"), _ev(category="PUBLIC")]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        enriched = result["events"]
        expected_max = max(e["sell_pressure_score"] for e in enriched)
        self.assertAlmostEqual(
            result["summary"]["max_sell_pressure_score"], expected_max, places=2
        )


# ===========================================================================
# 8. get_upcoming_unlocks()
# ===========================================================================

class TestGetUpcomingUnlocks(unittest.TestCase):

    def test_returns_empty_before_monitor(self):
        mon = TokenUnlockMonitor()
        self.assertEqual(mon.get_upcoming_unlocks(), [])

    def test_filters_within_30_days(self):
        events = [
            _ev(unlock_days_from_now=10, now=_NOW),
            _ev(unlock_days_from_now=60, now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        upcoming = mon.get_upcoming_unlocks(days=30)
        self.assertEqual(len(upcoming), 1)
        self.assertAlmostEqual(upcoming[0]["days_until_unlock"], 10.0, places=1)

    def test_excludes_past_events(self):
        events = [
            _ev(unlock_days_from_now=-5, now=_NOW),  # past
            _ev(unlock_days_from_now=15, now=_NOW),   # future
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        upcoming = mon.get_upcoming_unlocks(days=30)
        self.assertEqual(len(upcoming), 1)

    def test_custom_days_window(self):
        events = [
            _ev(unlock_days_from_now=5, now=_NOW),
            _ev(unlock_days_from_now=50, now=_NOW),
            _ev(unlock_days_from_now=100, now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        self.assertEqual(len(mon.get_upcoming_unlocks(days=60)), 2)
        self.assertEqual(len(mon.get_upcoming_unlocks(days=7)), 1)

    def test_returns_empty_if_all_past(self):
        events = [_ev(unlock_days_from_now=-10, now=_NOW)]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        self.assertEqual(mon.get_upcoming_unlocks(30), [])

    def test_boundary_at_exactly_30_days(self):
        events = [_ev(unlock_days_from_now=30, now=_NOW)]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        upcoming = mon.get_upcoming_unlocks(days=30)
        self.assertEqual(len(upcoming), 1)


# ===========================================================================
# 9. get_high_risk_protocols()
# ===========================================================================

class TestGetHighRiskProtocols(unittest.TestCase):

    def test_returns_empty_before_monitor(self):
        mon = TokenUnlockMonitor()
        self.assertEqual(mon.get_high_risk_protocols(), [])

    def test_returns_only_high_and_critical(self):
        events = [
            # CRITICAL: 25% dilution in 10 days
            _ev(protocol="CritP", unlock_amount_tokens=25_000_000,
                circulating_supply=100_000_000, category="TEAM",
                unlock_days_from_now=10, now=_NOW),
            # LOW: 1% dilution far away
            _ev(protocol="LowP", unlock_amount_tokens=1_000_000,
                circulating_supply=100_000_000, category="PUBLIC",
                unlock_days_from_now=365, now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        hr = mon.get_high_risk_protocols()
        protocols = [e["protocol"] for e in hr]
        self.assertIn("CritP", protocols)
        self.assertNotIn("LowP", protocols)

    def test_sorted_by_sell_pressure_score_desc(self):
        events = [
            _ev(protocol="A", unlock_amount_tokens=25_000_000,
                circulating_supply=100_000_000, category="TEAM",
                unlock_days_from_now=5, now=_NOW),
            _ev(protocol="B", unlock_amount_tokens=12_000_000,
                circulating_supply=100_000_000, category="INVESTOR",
                unlock_days_from_now=20, now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        hr = mon.get_high_risk_protocols()
        if len(hr) >= 2:
            self.assertGreaterEqual(
                hr[0]["sell_pressure_score"], hr[1]["sell_pressure_score"]
            )

    def test_returns_empty_when_all_low(self):
        events = [
            _ev(unlock_amount_tokens=100_000, circulating_supply=100_000_000,
                category="PUBLIC", unlock_days_from_now=365, now=_NOW)
        ]
        mon = TokenUnlockMonitor()
        mon.monitor(events, now_ts=_NOW)
        self.assertEqual(mon.get_high_risk_protocols(), [])


# ===========================================================================
# 10. Atomic write / ring buffer / log I/O
# ===========================================================================

class TestAtomicWriteAndLog(TempDirMixin):

    def test_atomic_write_creates_file(self):
        path = os.path.join(self._tmpdir, "test.json")
        _atomic_write_json(path, [])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_content_is_valid_json(self):
        path = os.path.join(self._tmpdir, "test.json")
        _atomic_write_json(path, {"key": "value", "num": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_atomic_write_creates_directories(self):
        path = os.path.join(self._tmpdir, "a", "b", "c.json")
        _atomic_write_json(path, [])
        self.assertTrue(os.path.exists(path))

    def test_load_log_empty_on_missing_file(self):
        path = os.path.join(self._tmpdir, "no_file.json")
        self.assertEqual(_load_log(path), [])

    def test_load_log_returns_list(self):
        path = os.path.join(self._tmpdir, "log.json")
        _atomic_write_json(path, [{"ts": 1}, {"ts": 2}])
        result = _load_log(path)
        self.assertEqual(len(result), 2)

    def test_load_log_empty_on_corrupt(self):
        path = os.path.join(self._tmpdir, "corrupt.json")
        with open(path, "w") as f:
            f.write("{{{{not_json")
        self.assertEqual(_load_log(path), [])

    def test_append_log_adds_entry(self):
        path = os.path.join(self._tmpdir, "log.json")
        _append_log(path, {"x": 1}, cap=10)
        result = _load_log(path)
        self.assertEqual(len(result), 1)

    def test_append_log_ring_buffer_cap(self):
        path = os.path.join(self._tmpdir, "log.json")
        for i in range(15):
            _append_log(path, {"i": i}, cap=10)
        result = _load_log(path)
        self.assertEqual(len(result), 10)

    def test_append_log_keeps_most_recent(self):
        path = os.path.join(self._tmpdir, "log.json")
        for i in range(12):
            _append_log(path, {"i": i}, cap=10)
        result = _load_log(path)
        vals = [e["i"] for e in result]
        self.assertEqual(vals, list(range(2, 12)))

    def test_write_log_flag_creates_log_file(self):
        mon = TokenUnlockMonitor(data_dir=self._tmpdir)
        mon.monitor([], now_ts=_NOW, write_log=True)
        log_path = os.path.join(self._tmpdir, "token_unlock_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_write_log_false_no_file(self):
        mon = TokenUnlockMonitor(data_dir=self._tmpdir)
        mon.monitor([], now_ts=_NOW, write_log=False)
        log_path = os.path.join(self._tmpdir, "token_unlock_log.json")
        self.assertFalse(os.path.exists(log_path))

    def test_log_entry_has_expected_keys(self):
        mon = TokenUnlockMonitor(data_dir=self._tmpdir)
        mon.monitor([_ev()], now_ts=_NOW, write_log=True)
        log_path = os.path.join(self._tmpdir, "token_unlock_log.json")
        with open(log_path) as f:
            log = json.load(f)
        entry = log[0]
        self.assertIn("timestamp_utc", entry)
        self.assertIn("event_count", entry)
        self.assertIn("summary", entry)

    def test_ring_buffer_capped_at_100_by_default(self):
        mon = TokenUnlockMonitor(data_dir=self._tmpdir)
        for _ in range(105):
            mon.monitor([], now_ts=_NOW, write_log=True)
        log_path = os.path.join(self._tmpdir, "token_unlock_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)


# ===========================================================================
# 11. Module-level monitor() convenience function
# ===========================================================================

class TestModuleLevelMonitor(unittest.TestCase):

    def test_returns_dict(self):
        result = monitor_fn([], now_ts=_NOW)
        self.assertIsInstance(result, dict)

    def test_event_count_correct(self):
        events = [_ev(), _ev()]
        result = monitor_fn(events, now_ts=_NOW)
        self.assertEqual(result["event_count"], 2)

    def test_invalid_event_raises_via_module_fn(self):
        ev = _ev()
        del ev["category"]
        with self.assertRaises(ValueError):
            monitor_fn([ev], now_ts=_NOW)


# ===========================================================================
# 12. Integration / edge-case scenarios
# ===========================================================================

class TestIntegrationScenarios(unittest.TestCase):

    def test_team_unlock_near_is_critical(self):
        ev = _ev(
            unlock_amount_tokens=25_000_000,
            circulating_supply=100_000_000,
            category="TEAM",
            unlock_days_from_now=10,
            now=_NOW,
        )
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        self.assertEqual(result["events"][0]["risk_level"], "CRITICAL")

    def test_ecosystem_unlock_far_is_low(self):
        ev = _ev(
            unlock_amount_tokens=500_000,
            circulating_supply=100_000_000,
            category="ECOSYSTEM",
            unlock_days_from_now=365,
            now=_NOW,
        )
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        self.assertEqual(result["events"][0]["risk_level"], "LOW")

    def test_past_events_have_negative_days(self):
        ev = _ev(unlock_days_from_now=-5, now=_NOW)
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        self.assertLess(result["events"][0]["days_until_unlock"], 0)

    def test_zero_price_gives_zero_unlock_value(self):
        ev = _ev(current_price_usd=0.0)
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        self.assertAlmostEqual(result["events"][0]["unlock_value_usd"], 0.0)

    def test_zero_amount_gives_zero_dilution(self):
        ev = _ev(unlock_amount_tokens=0)
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        self.assertAlmostEqual(result["events"][0]["dilution_pct"], 0.0)

    def test_all_categories_processed_correctly(self):
        events = [
            _ev(category="TEAM", now=_NOW),
            _ev(category="INVESTOR", now=_NOW),
            _ev(category="ECOSYSTEM", now=_NOW),
            _ev(category="PUBLIC", now=_NOW),
        ]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        self.assertEqual(result["event_count"], 4)
        # TEAM should have highest score
        scores = {e["category"]: e["sell_pressure_score"] for e in result["events"]}
        self.assertGreater(scores["TEAM"], scores["PUBLIC"])

    def test_monitor_does_not_mutate_input(self):
        ev = _ev()
        original_keys = set(ev.keys())
        mon = TokenUnlockMonitor()
        mon.monitor([ev], now_ts=_NOW)
        self.assertEqual(set(ev.keys()), original_keys)

    def test_last_result_updated_on_second_call(self):
        mon = TokenUnlockMonitor()
        mon.monitor([], now_ts=_NOW)
        mon.monitor([_ev()], now_ts=_NOW + 1000)
        self.assertEqual(mon._last_result["event_count"], 1)

    def test_dilution_pct_formula(self):
        ev = _ev(unlock_amount_tokens=10_000_000, circulating_supply=50_000_000)
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        expected_dilution = (10_000_000 / 50_000_000) * 100.0
        self.assertAlmostEqual(
            result["events"][0]["dilution_pct"], expected_dilution, places=4
        )

    def test_unlock_value_formula(self):
        ev = _ev(unlock_amount_tokens=2_500_000, current_price_usd=3.50)
        mon = TokenUnlockMonitor()
        result = mon.monitor([ev], now_ts=_NOW)
        expected = 2_500_000 * 3.50
        self.assertAlmostEqual(
            result["events"][0]["unlock_value_usd"], expected, places=2
        )

    def test_sell_pressure_scores_are_finite(self):
        events = [_ev(category=c, now=_NOW) for c in ("TEAM", "INVESTOR", "ECOSYSTEM", "PUBLIC")]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        for ev in result["events"]:
            self.assertTrue(math.isfinite(ev["sell_pressure_score"]))

    def test_large_number_of_events(self):
        events = [_ev(protocol=f"P{i}", now=_NOW) for i in range(50)]
        mon = TokenUnlockMonitor()
        result = mon.monitor(events, now_ts=_NOW)
        self.assertEqual(result["event_count"], 50)
        self.assertEqual(len(result["events"]), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
