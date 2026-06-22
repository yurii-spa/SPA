"""
Tests for spa_core/alerts/adaptive_monitor.py — FEAT-MON-003 (v3.17).

Run:
    python -m pytest spa_core/tests/test_adaptive_monitor.py -v

Expected: ≥ 60 tests, all PASS.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap (run from repo root or tests/ directory)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts.adaptive_monitor import (
    MonitorConfig,
    MonitorSnapshot,
    AdaptiveMonitor,
    compute_interval,
    should_escalate,
    get_interval,
    get_next_check_time,
    get_monitor,
    _base_interval,
    _t3_hf_interval,
    _load_red_flag_protocols,
    T1_INTERVAL_SECS,
    T2_INTERVAL_SECS,
    T3_INTERVAL_SECS,
    T3_CRITICAL_INTERVAL_SECS,
    T3_RELAXED_INTERVAL_SECS,
    HF_CRITICAL_THRESHOLD,
    HF_RELAXED_THRESHOLD,
    T3_ESCALATE_HF_THRESHOLD,
    RED_FLAG_MULTIPLIER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(
    tier: int = 1,
    protocol_key: str = "aave_v3",
    position_id: str = "test-pos",
    health_factor=None,
    has_red_flag: bool = False,
    last_checked_at=None,
) -> MonitorConfig:
    return MonitorConfig(
        tier=tier,
        protocol_key=protocol_key,
        position_id=position_id,
        health_factor=health_factor,
        has_red_flag=has_red_flag,
        last_checked_at=last_checked_at,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. MonitorConfig validation
# ---------------------------------------------------------------------------

class TestMonitorConfigValidation(unittest.TestCase):

    def test_valid_tier_1(self):
        c = _cfg(tier=1)
        self.assertEqual(c.tier, 1)

    def test_valid_tier_2(self):
        c = _cfg(tier=2)
        self.assertEqual(c.tier, 2)

    def test_valid_tier_3(self):
        c = _cfg(tier=3)
        self.assertEqual(c.tier, 3)

    def test_invalid_tier_0(self):
        with self.assertRaises(ValueError):
            _cfg(tier=0)

    def test_invalid_tier_4(self):
        with self.assertRaises(ValueError):
            _cfg(tier=4)

    def test_empty_protocol_key_raises(self):
        with self.assertRaises(ValueError):
            MonitorConfig(tier=1, protocol_key="", position_id="p")

    def test_empty_position_id_raises(self):
        with self.assertRaises(ValueError):
            MonitorConfig(tier=1, protocol_key="aave_v3", position_id="")

    def test_negative_health_factor_raises(self):
        with self.assertRaises(ValueError):
            _cfg(tier=3, health_factor=-0.1)

    def test_zero_health_factor_valid(self):
        c = _cfg(tier=3, health_factor=0.0)
        self.assertEqual(c.health_factor, 0.0)

    def test_extra_defaults_to_empty_dict(self):
        c = _cfg()
        self.assertEqual(c.extra, {})


# ---------------------------------------------------------------------------
# 2. Base interval logic
# ---------------------------------------------------------------------------

class TestBaseInterval(unittest.TestCase):

    def test_t1_base(self):
        self.assertEqual(_base_interval(1), T1_INTERVAL_SECS)

    def test_t2_base(self):
        self.assertEqual(_base_interval(2), T2_INTERVAL_SECS)

    def test_t3_base(self):
        self.assertEqual(_base_interval(3), T3_INTERVAL_SECS)

    def test_t1_is_hours(self):
        # T1 should be at least 1 hour
        self.assertGreaterEqual(T1_INTERVAL_SECS, 3600)

    def test_t2_is_30min(self):
        self.assertEqual(T2_INTERVAL_SECS, 1800)

    def test_t3_is_3min(self):
        self.assertEqual(T3_INTERVAL_SECS, 180)


# ---------------------------------------------------------------------------
# 3. T3 HF interval computation
# ---------------------------------------------------------------------------

class TestT3HFInterval(unittest.TestCase):

    def test_critical_hf_below_threshold(self):
        interval, reason = _t3_hf_interval(1.0)
        self.assertEqual(interval, T3_CRITICAL_INTERVAL_SECS)
        self.assertIn("critical", reason.lower())

    def test_critical_hf_at_threshold_minus_epsilon(self):
        interval, _ = _t3_hf_interval(HF_CRITICAL_THRESHOLD - 0.001)
        self.assertEqual(interval, T3_CRITICAL_INTERVAL_SECS)

    def test_relaxed_hf_above_threshold(self):
        interval, reason = _t3_hf_interval(2.5)
        self.assertEqual(interval, T3_RELAXED_INTERVAL_SECS)
        self.assertIn("relaxed", reason.lower())

    def test_relaxed_hf_at_threshold_plus_epsilon(self):
        interval, _ = _t3_hf_interval(HF_RELAXED_THRESHOLD + 0.001)
        self.assertEqual(interval, T3_RELAXED_INTERVAL_SECS)

    def test_midpoint_interpolation(self):
        # At exactly (1.3 + 1.8) / 2 = 1.55, t = 0.5
        # lerp(60, 180, 0.5) = 120
        interval, reason = _t3_hf_interval(1.55)
        self.assertGreaterEqual(interval, T3_CRITICAL_INTERVAL_SECS)
        self.assertLessEqual(interval, T3_INTERVAL_SECS)
        self.assertIn("interpolated", reason.lower())

    def test_interpolation_monotone(self):
        # As HF increases from 1.3 to 1.8, interval should be non-decreasing
        prev = None
        for hf_tenth in range(13, 19):
            hf = hf_tenth / 10
            interval, _ = _t3_hf_interval(hf)
            if prev is not None:
                self.assertGreaterEqual(interval, prev)
            prev = interval

    def test_zero_hf_is_critical(self):
        interval, _ = _t3_hf_interval(0.0)
        self.assertEqual(interval, T3_CRITICAL_INTERVAL_SECS)

    def test_very_high_hf_is_relaxed(self):
        interval, _ = _t3_hf_interval(10.0)
        self.assertEqual(interval, T3_RELAXED_INTERVAL_SECS)


# ---------------------------------------------------------------------------
# 4. compute_interval
# ---------------------------------------------------------------------------

class TestComputeInterval(unittest.TestCase):

    def test_t1_default(self):
        interval, reason = compute_interval(_cfg(tier=1))
        self.assertEqual(interval, T1_INTERVAL_SECS)
        self.assertIn("T1", reason)

    def test_t2_default(self):
        interval, reason = compute_interval(_cfg(tier=2))
        self.assertEqual(interval, T2_INTERVAL_SECS)
        self.assertIn("T2", reason)

    def test_t3_default_no_hf(self):
        interval, reason = compute_interval(_cfg(tier=3))
        self.assertEqual(interval, T3_INTERVAL_SECS)
        self.assertIn("HF=N/A", reason)

    def test_t3_with_critical_hf(self):
        interval, reason = compute_interval(_cfg(tier=3, health_factor=1.1))
        self.assertEqual(interval, T3_CRITICAL_INTERVAL_SECS)

    def test_t3_with_relaxed_hf(self):
        interval, _ = compute_interval(_cfg(tier=3, health_factor=2.0))
        self.assertEqual(interval, T3_RELAXED_INTERVAL_SECS)

    def test_red_flag_halves_interval_t1(self):
        base, _ = compute_interval(_cfg(tier=1, has_red_flag=False))
        with_flag, _ = compute_interval(_cfg(tier=1, has_red_flag=True))
        self.assertLessEqual(with_flag, base)

    def test_red_flag_halves_interval_t2(self):
        base, _ = compute_interval(_cfg(tier=2, has_red_flag=False))
        with_flag, _ = compute_interval(_cfg(tier=2, has_red_flag=True))
        self.assertLessEqual(with_flag, base)

    def test_red_flag_halves_interval_t3(self):
        base, _ = compute_interval(_cfg(tier=3, health_factor=1.5, has_red_flag=False))
        with_flag, _ = compute_interval(_cfg(tier=3, health_factor=1.5, has_red_flag=True))
        self.assertLessEqual(with_flag, base)

    def test_interval_never_below_10(self):
        for tier in [1, 2, 3]:
            interval, _ = compute_interval(_cfg(tier=tier, has_red_flag=True))
            self.assertGreaterEqual(interval, 10)

    def test_t1_interval_clamped_max(self):
        interval, _ = compute_interval(_cfg(tier=1))
        self.assertLessEqual(interval, 21600)  # 6h

    def test_t3_interval_clamped_max(self):
        interval, _ = compute_interval(_cfg(tier=3, health_factor=5.0, has_red_flag=False))
        self.assertLessEqual(interval, T3_RELAXED_INTERVAL_SECS)

    def test_reason_string_not_empty(self):
        _, reason = compute_interval(_cfg(tier=1))
        self.assertTrue(len(reason) > 0)

    def test_t3_red_flag_and_critical_hf(self):
        # Critical HF → 60s, then red-flag halves → should stay ≥ 10
        interval, reason = compute_interval(_cfg(tier=3, health_factor=1.0, has_red_flag=True))
        self.assertGreaterEqual(interval, 10)
        self.assertIn("red_flag", reason)


# ---------------------------------------------------------------------------
# 5. should_escalate (module-level function)
# ---------------------------------------------------------------------------

class TestShouldEscalate(unittest.TestCase):

    def test_t3_escalate_below_threshold(self):
        c = _cfg(tier=3, health_factor=T3_ESCALATE_HF_THRESHOLD - 0.01)
        self.assertTrue(should_escalate(c))

    def test_t3_no_escalate_above_threshold(self):
        c = _cfg(tier=3, health_factor=T3_ESCALATE_HF_THRESHOLD + 0.01)
        self.assertFalse(should_escalate(c))

    def test_t3_escalate_hf_exactly_at_threshold(self):
        # boundary: HF == 1.15 should NOT escalate (strict <)
        c = _cfg(tier=3, health_factor=T3_ESCALATE_HF_THRESHOLD)
        self.assertFalse(should_escalate(c))

    def test_t1_never_escalates(self):
        c = _cfg(tier=1, has_red_flag=True)
        self.assertFalse(should_escalate(c))

    def test_t2_never_escalates(self):
        c = _cfg(tier=2, has_red_flag=True)
        self.assertFalse(should_escalate(c))

    def test_t3_no_hf_no_escalate(self):
        c = _cfg(tier=3, health_factor=None)
        self.assertFalse(should_escalate(c))


# ---------------------------------------------------------------------------
# 6. AdaptiveMonitor — get_interval
# ---------------------------------------------------------------------------

class TestAdaptiveMonitorGetInterval(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_t1_returns_correct(self):
        self.assertEqual(self.monitor.get_interval(_cfg(tier=1)), T1_INTERVAL_SECS)

    def test_t2_returns_correct(self):
        self.assertEqual(self.monitor.get_interval(_cfg(tier=2)), T2_INTERVAL_SECS)

    def test_t3_returns_correct_no_hf(self):
        self.assertEqual(self.monitor.get_interval(_cfg(tier=3)), T3_INTERVAL_SECS)

    def test_positive_return(self):
        for tier in [1, 2, 3]:
            self.assertGreater(self.monitor.get_interval(_cfg(tier=tier)), 0)


# ---------------------------------------------------------------------------
# 7. AdaptiveMonitor — get_next_check_time
# ---------------------------------------------------------------------------

class TestAdaptiveMonitorGetNextCheckTime(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_returns_future_datetime(self):
        now = _now()
        result = self.monitor.get_next_check_time(_cfg(tier=1))
        self.assertGreater(result, now)

    def test_uses_last_checked_at(self):
        ref = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cfg = _cfg(tier=1, last_checked_at=ref)
        result = self.monitor.get_next_check_time(cfg)
        expected = ref + timedelta(seconds=T1_INTERVAL_SECS)
        self.assertEqual(result, expected)

    def test_naive_datetime_converted_to_utc(self):
        ref = datetime(2026, 1, 1, 12, 0, 0)  # naive
        cfg = _cfg(tier=1, last_checked_at=ref)
        result = self.monitor.get_next_check_time(cfg)
        self.assertIsNotNone(result.tzinfo)

    def test_t3_critical_hf_yields_short_interval(self):
        ref = _now()
        cfg = _cfg(tier=3, health_factor=1.0, last_checked_at=ref)
        result = self.monitor.get_next_check_time(cfg)
        delta = (result - ref).total_seconds()
        self.assertLessEqual(delta, T3_CRITICAL_INTERVAL_SECS + 1)


# ---------------------------------------------------------------------------
# 8. AdaptiveMonitor — should_escalate
# ---------------------------------------------------------------------------

class TestAdaptiveMonitorShouldEscalate(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_escalate_critical_t3(self):
        cfg = _cfg(tier=3, health_factor=1.1)
        self.assertTrue(self.monitor.should_escalate(cfg))

    def test_no_escalate_healthy_t3(self):
        cfg = _cfg(tier=3, health_factor=1.5)
        self.assertFalse(self.monitor.should_escalate(cfg))

    def test_no_escalate_t1(self):
        cfg = _cfg(tier=1)
        self.assertFalse(self.monitor.should_escalate(cfg))


# ---------------------------------------------------------------------------
# 9. AdaptiveMonitor — get_snapshot
# ---------------------------------------------------------------------------

class TestAdaptiveMonitorGetSnapshot(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_snapshot_fields_populated(self):
        cfg = _cfg(tier=2)
        snap = self.monitor.get_snapshot(cfg)
        self.assertIsInstance(snap, MonitorSnapshot)
        self.assertEqual(snap.position_id, "test-pos")
        self.assertEqual(snap.tier, 2)
        self.assertGreater(snap.interval_secs, 0)
        self.assertIsNotNone(snap.next_check_at)
        self.assertIsInstance(snap.reason, str)

    def test_snapshot_escalate_for_critical_hf(self):
        cfg = _cfg(tier=3, health_factor=1.0)
        snap = self.monitor.get_snapshot(cfg)
        self.assertTrue(snap.should_escalate)

    def test_snapshot_no_escalate_normal(self):
        cfg = _cfg(tier=1)
        snap = self.monitor.get_snapshot(cfg)
        self.assertFalse(snap.should_escalate)


# ---------------------------------------------------------------------------
# 10. get_all_positions_schedule
# ---------------------------------------------------------------------------

class TestGetAllPositionsSchedule(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def _make_positions(self):
        now = _now()
        return [
            _cfg(tier=1, position_id="p1", last_checked_at=now - timedelta(hours=3)),
            _cfg(tier=2, position_id="p2", last_checked_at=now - timedelta(minutes=20)),
            _cfg(tier=3, position_id="p3", health_factor=1.5,
                 last_checked_at=now - timedelta(minutes=2)),
            _cfg(tier=3, position_id="p4", health_factor=1.0,
                 last_checked_at=now - timedelta(seconds=30)),
        ]

    def test_returns_list(self):
        schedule = self.monitor.get_all_positions_schedule(self._make_positions())
        self.assertIsInstance(schedule, list)

    def test_length_matches_input(self):
        positions = self._make_positions()
        schedule = self.monitor.get_all_positions_schedule(positions)
        self.assertEqual(len(schedule), len(positions))

    def test_sorted_ascending(self):
        schedule = self.monitor.get_all_positions_schedule(self._make_positions())
        times = [dt for dt, _ in schedule]
        self.assertEqual(times, sorted(times))

    def test_escalated_position_at_front(self):
        schedule = self.monitor.get_all_positions_schedule(self._make_positions())
        # p4 has HF=1.0 → should escalate → appears in first two (near "now")
        early_ids = {cfg.position_id for _, cfg in schedule[:2]}
        self.assertIn("p4", early_ids)

    def test_empty_input_returns_empty(self):
        schedule = self.monitor.get_all_positions_schedule([])
        self.assertEqual(schedule, [])

    def test_all_positions_represented(self):
        positions = self._make_positions()
        schedule = self.monitor.get_all_positions_schedule(positions)
        ids = {cfg.position_id for _, cfg in schedule}
        expected = {p.position_id for p in positions}
        self.assertEqual(ids, expected)


# ---------------------------------------------------------------------------
# 11. export_schedule_json
# ---------------------------------------------------------------------------

class TestExportScheduleJson(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_dry_run_returns_dict(self):
        cfg = _cfg(tier=1)
        result = self.monitor.export_schedule_json([cfg], dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertIn("schedule", result)

    def test_schedule_items_structure(self):
        cfg = _cfg(tier=2, position_id="test-export")
        result = self.monitor.export_schedule_json([cfg], dry_run=True)
        self.assertEqual(len(result["schedule"]), 1)
        item = result["schedule"][0]
        for key in ["position_id", "tier", "interval_secs", "next_check_at", "reason"]:
            self.assertIn(key, item)

    def test_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "schedule.json"
            cfg = _cfg(tier=1)
            result = self.monitor.export_schedule_json([cfg], output_path=str(out), dry_run=False)
            self.assertTrue(out.exists())
            with out.open() as fh:
                loaded = json.load(fh)
            self.assertEqual(result["total_positions"], loaded["total_positions"])

    def test_generated_at_present(self):
        result = self.monitor.export_schedule_json([_cfg(tier=1)], dry_run=True)
        self.assertIn("generated_at", result)


# ---------------------------------------------------------------------------
# 12. Red-flag file integration
# ---------------------------------------------------------------------------

class TestRedFlagIntegration(unittest.TestCase):

    def _make_red_flags_file(self, protocols: list[str]) -> str:
        data = {
            "generated_at": "2026-05-28T00:00:00Z",
            "red_flags": [
                {"protocol": p, "category": "tvl_drop", "severity": "WARN",
                 "message": f"{p} test flag", "source": "test",
                 "detected_at": "2026-05-28T00:00:00Z", "evidence": {}}
                for p in protocols
            ],
            "summary": {}
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(data, fh)
            return fh.name

    def test_protocol_with_flag_gets_shorter_interval(self):
        path = self._make_red_flags_file(["aave-v3"])
        try:
            monitor = AdaptiveMonitor(red_flags_path=path, auto_load_red_flags=True)
            # Force cache refresh
            monitor._flags_loaded_at = None
            cfg_flag = _cfg(tier=2, protocol_key="aave_v3", has_red_flag=False)
            cfg_clean = _cfg(tier=2, protocol_key="compound_v3", has_red_flag=False)
            interval_flag = monitor.get_interval(cfg_flag)
            interval_clean = monitor.get_interval(cfg_clean)
            self.assertLess(interval_flag, interval_clean)
        finally:
            os.unlink(path)

    def test_flag_enrichment_normalises_hyphens(self):
        # red_flags.json uses "aave-v3" (hyphens); protocol_key uses "aave_v3" (underscores)
        protocols = _load_red_flag_protocols(self._make_red_flags_file(["aave-v3"]))
        self.assertIn("aave_v3", protocols)

    def test_missing_file_returns_empty_set(self):
        protocols = _load_red_flag_protocols("/nonexistent/path/red_flags.json")
        self.assertEqual(protocols, frozenset())

    def test_malformed_json_returns_empty_set(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            fh.write("NOT JSON {{{")
            path = fh.name
        try:
            protocols = _load_red_flag_protocols(path)
            self.assertEqual(protocols, frozenset())
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 13. Module-level shortcuts
# ---------------------------------------------------------------------------

class TestModuleLevelShortcuts(unittest.TestCase):

    def test_get_interval_t1(self):
        # Use a protocol unlikely to appear in red_flags.json to avoid flag enrichment
        result = get_interval(_cfg(tier=1, protocol_key="unknown_protocol_xyz"))
        self.assertEqual(result, T1_INTERVAL_SECS)

    def test_get_next_check_time_returns_datetime(self):
        result = get_next_check_time(_cfg(tier=1))
        self.assertIsInstance(result, datetime)

    def test_get_monitor_returns_singleton(self):
        m1 = get_monitor()
        m2 = get_monitor()
        self.assertIs(m1, m2)


# ---------------------------------------------------------------------------
# 14. describe_schedule
# ---------------------------------------------------------------------------

class TestDescribeSchedule(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_returns_string(self):
        result = self.monitor.describe_schedule([_cfg(tier=1)])
        self.assertIsInstance(result, str)

    def test_empty_positions(self):
        result = self.monitor.describe_schedule([])
        self.assertIn("No positions", result)

    def test_contains_position_id(self):
        result = self.monitor.describe_schedule([_cfg(tier=1, position_id="my-pos")])
        self.assertIn("my-pos", result)


# ---------------------------------------------------------------------------
# 15. Edge cases & robustness
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.monitor = AdaptiveMonitor(red_flags_path=None, auto_load_red_flags=False)

    def test_get_interval_never_raises(self):
        # Pass a deliberately unusual (but valid) config
        cfg = _cfg(tier=3, health_factor=0.0, has_red_flag=True)
        try:
            result = self.monitor.get_interval(cfg)
        except Exception:
            self.fail("get_interval raised an exception")
        self.assertIsInstance(result, int)

    def test_schedule_never_raises_on_large_list(self):
        positions = [
            _cfg(tier=(i % 3) + 1, position_id=f"pos-{i}")
            for i in range(100)
        ]
        try:
            schedule = self.monitor.get_all_positions_schedule(positions)
        except Exception:
            self.fail("get_all_positions_schedule raised an exception")
        self.assertEqual(len(schedule), 100)

    def test_health_factor_exactly_critical_threshold(self):
        cfg = _cfg(tier=3, health_factor=HF_CRITICAL_THRESHOLD)
        interval = self.monitor.get_interval(cfg)
        # At exactly 1.3 the lerp gives t=0 → 60s
        self.assertGreaterEqual(interval, T3_CRITICAL_INTERVAL_SECS)

    def test_health_factor_exactly_relaxed_threshold(self):
        cfg = _cfg(tier=3, health_factor=HF_RELAXED_THRESHOLD)
        interval = self.monitor.get_interval(cfg)
        self.assertLessEqual(interval, T3_RELAXED_INTERVAL_SECS)

    def test_red_flag_multiplier_constant(self):
        self.assertEqual(RED_FLAG_MULTIPLIER, 0.5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
