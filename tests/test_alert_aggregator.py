#!/usr/bin/env python3
"""
tests/test_alert_aggregator.py — MP-1494 (Sprint v11.10)

Unit tests for spa_core/alerts/alert_aggregator.py
25 tests, pure stdlib, offline.

Groups:
    A. Module structure / constants          (4 tests)
    B. _dedup_key                            (4 tests)
    C. _is_throttled                         (5 tests)
    D. submit() approval logic               (5 tests)
    E. submit() suppression / stats          (4 tests)
    F. Persistence + clear_history           (3 tests)
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
import tempfile
import unittest

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from spa_core.alerts.alert_aggregator import (  # noqa: E402
    AlertAggregator,
    THROTTLE_MINUTES,
)


def _make_agg(tmp_path: pathlib.Path) -> AlertAggregator:
    return AlertAggregator(base_dir=str(tmp_path))


def _alert(
    alert_type: str = "apy_drift",
    strategy: str = "S0",
    severity: str = "MEDIUM",
) -> dict:
    return {"type": alert_type, "strategy": strategy, "severity": severity}


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Module structure / constants
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleStructure(unittest.TestCase):

    def test_A1_throttle_minutes_dict_has_four_levels(self):
        self.assertIn("CRITICAL", THROTTLE_MINUTES)
        self.assertIn("HIGH", THROTTLE_MINUTES)
        self.assertIn("MEDIUM", THROTTLE_MINUTES)
        self.assertIn("LOW", THROTTLE_MINUTES)

    def test_A2_critical_is_zero(self):
        self.assertEqual(THROTTLE_MINUTES["CRITICAL"], 0)

    def test_A3_inherits_base_analytics(self):
        from spa_core.base import BaseAnalytics
        self.assertTrue(issubclass(AlertAggregator, BaseAnalytics))

    def test_A4_output_path_defined(self):
        self.assertIn("alert_aggregator", AlertAggregator.OUTPUT_PATH)


# ═══════════════════════════════════════════════════════════════════════════
# Group B — _dedup_key
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupKey(unittest.TestCase):

    def test_B1_key_format_type_strategy_severity(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            key = agg._dedup_key({"type": "apy_drift", "strategy": "S0", "severity": "HIGH"})
            self.assertEqual(key, "apy_drift:S0:HIGH")

    def test_B2_default_type_is_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            key = agg._dedup_key({"strategy": "S1", "severity": "LOW"})
            self.assertTrue(key.startswith("alert:"))

    def test_B3_default_strategy_is_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            key = agg._dedup_key({"type": "risk", "severity": "MEDIUM"})
            self.assertIn("system", key)

    def test_B4_same_alert_produces_same_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            a = {"type": "x", "strategy": "S2", "severity": "HIGH"}
            self.assertEqual(agg._dedup_key(a), agg._dedup_key(a))


# ═══════════════════════════════════════════════════════════════════════════
# Group C — _is_throttled
# ═══════════════════════════════════════════════════════════════════════════

class TestIsThrottled(unittest.TestCase):

    def test_C1_not_throttled_when_no_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            self.assertFalse(agg._is_throttled("new:key:MEDIUM", "MEDIUM"))

    def test_C2_critical_never_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            # Record a recent send
            agg._data["sent"]["x:S0:CRITICAL"] = datetime.datetime.utcnow().isoformat()
            # Still should NOT be throttled (CRITICAL window = 0)
            self.assertFalse(agg._is_throttled("x:S0:CRITICAL", "CRITICAL"))

    def test_C3_high_throttled_within_60_min(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg._data["sent"]["x:S0:HIGH"] = datetime.datetime.utcnow().isoformat()
            self.assertTrue(agg._is_throttled("x:S0:HIGH", "HIGH"))

    def test_C4_high_not_throttled_after_60_min(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            past = (datetime.datetime.utcnow() - datetime.timedelta(minutes=61)).isoformat()
            agg._data["sent"]["x:S0:HIGH"] = past
            self.assertFalse(agg._is_throttled("x:S0:HIGH", "HIGH"))

    def test_C5_corrupted_timestamp_not_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg._data["sent"]["x:S0:MEDIUM"] = "not-a-date"
            self.assertFalse(agg._is_throttled("x:S0:MEDIUM", "MEDIUM"))


# ═══════════════════════════════════════════════════════════════════════════
# Group D — submit() approval logic
# ═══════════════════════════════════════════════════════════════════════════

class TestSubmitApproval(unittest.TestCase):

    def test_D1_first_submit_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            result = agg.submit(_alert())
            self.assertTrue(result)

    def test_D2_second_submit_within_throttle_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(severity="MEDIUM"))
            result = agg.submit(_alert(severity="MEDIUM"))
            self.assertFalse(result)

    def test_D3_critical_always_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(severity="CRITICAL"))
            result = agg.submit(_alert(severity="CRITICAL"))
            self.assertTrue(result)

    def test_D4_different_strategies_not_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(strategy="S0", severity="HIGH"))
            result = agg.submit(_alert(strategy="S1", severity="HIGH"))
            self.assertTrue(result)

    def test_D5_records_sent_key_after_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            a = _alert(alert_type="risk", strategy="S5", severity="LOW")
            agg.submit(a)
            key = agg._dedup_key(a)
            self.assertIn(key, agg._data["sent"])


# ═══════════════════════════════════════════════════════════════════════════
# Group E — submit() suppression / stats
# ═══════════════════════════════════════════════════════════════════════════

class TestSubmitSuppression(unittest.TestCase):

    def test_E1_suppressed_count_increments_on_throttle(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(severity="HIGH"))  # approved
            agg.submit(_alert(severity="HIGH"))  # suppressed
            self.assertEqual(agg._data["suppressed_count"], 1)

    def test_E2_total_sent_increments_on_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(strategy="S0"))
            agg.submit(_alert(strategy="S1"))
            self.assertEqual(agg._data["total_sent"], 2)

    def test_E3_get_stats_returns_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            stats = agg.get_stats()
            self.assertIn("suppressed_count", stats)
            self.assertIn("total_sent", stats)
            self.assertIn("tracked_keys", stats)

    def test_E4_tracked_keys_count_after_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(strategy="S0", severity="LOW"))
            agg.submit(_alert(strategy="S1", severity="LOW"))
            stats = agg.get_stats()
            self.assertEqual(stats["tracked_keys"], 2)


# ═══════════════════════════════════════════════════════════════════════════
# Group F — Persistence + clear_history
# ═══════════════════════════════════════════════════════════════════════════

class TestPersistence(unittest.TestCase):

    def test_F1_state_persisted_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            agg = _make_agg(tp)
            agg.submit(_alert(strategy="S0"))
            out = tp / AlertAggregator.OUTPUT_PATH
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text())
            self.assertIn("sent", loaded)

    def test_F2_new_instance_loads_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            agg1 = _make_agg(tp)
            agg1.submit(_alert(strategy="SA", severity="HIGH"))

            # New instance in the same directory should load the same state
            agg2 = _make_agg(tp)
            key = agg1._dedup_key(_alert(strategy="SA", severity="HIGH"))
            self.assertIn(key, agg2._data["sent"])

    def test_F3_clear_history_resets_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            agg = _make_agg(pathlib.Path(tmp))
            agg.submit(_alert(strategy="S0"))
            agg.clear_history()
            self.assertEqual(agg._data["sent"], {})
            self.assertEqual(agg._data["suppressed_count"], 0)
            # After clear, submit should be approved again
            result = agg.submit(_alert(strategy="S0"))
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
