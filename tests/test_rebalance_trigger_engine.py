"""Tests for RebalanceTriggerEngine.analyze() — BaseAnalytics contract (MP-652).

These tests cover the concrete analyze() implementation added to make the class
instantiable (it was abstract → silently counted as a "failed" module inside the
cycle's analytics pipeline). conftest.py puts the repo root on sys.path.
"""
from __future__ import annotations

import unittest

from spa_core.base import BaseAnalytics
from spa_core.analytics.rebalance_trigger_engine import (
    AllocationSlot,
    RebalanceTriggerEngine,
    _build_demo_slots,
)


class TestInstantiable(unittest.TestCase):
    """The whole point: the class must no longer be abstract."""

    def test_can_instantiate(self):
        # Previously raised TypeError: abstract method 'analyze'.
        engine = RebalanceTriggerEngine()
        self.assertIsInstance(engine, RebalanceTriggerEngine)

    def test_is_baseanalytics_subclass(self):
        self.assertTrue(issubclass(RebalanceTriggerEngine, BaseAnalytics))

    def test_analyze_is_concrete(self):
        self.assertNotIn("analyze", RebalanceTriggerEngine.__abstractmethods__)

    def test_module_name_set(self):
        self.assertEqual(
            RebalanceTriggerEngine.MODULE_NAME, "rebalance_trigger_engine"
        )


class TestAnalyzeEnvelope(unittest.TestCase):
    """analyze() must return the required {module_id, status, timestamp, result}."""

    def setUp(self):
        self.engine = RebalanceTriggerEngine()
        self.out = self.engine.analyze()

    def test_returns_dict(self):
        self.assertIsInstance(self.out, dict)

    def test_has_required_keys(self):
        for key in ("module_id", "status", "timestamp", "result"):
            self.assertIn(key, self.out)

    def test_module_id_value(self):
        self.assertEqual(self.out["module_id"], "rebalance_trigger_engine")

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.out["timestamp"], float)
        self.assertGreater(self.out["timestamp"], 0)

    def test_status_is_valid_urgency(self):
        self.assertIn(self.out["status"], ("IMMEDIATE", "SOON", "NONE"))

    def test_result_is_dict(self):
        self.assertIsInstance(self.out["result"], dict)

    def test_result_core_fields(self):
        for f in (
            "triggered",
            "reason",
            "drifted_slots",
            "apy_changed_slots",
            "max_drift",
            "total_drift",
            "urgency",
            "actions",
            "thresholds",
            "slots_evaluated",
        ):
            self.assertIn(f, self.out["result"])

    def test_thresholds_exposed(self):
        thr = self.out["result"]["thresholds"]
        self.assertIn("drift_threshold", thr)
        self.assertIn("apy_threshold", thr)
        self.assertIn("min_days_between_rebalance", thr)

    def test_slots_evaluated_count(self):
        self.assertEqual(
            self.out["result"]["slots_evaluated"], len(_build_demo_slots())
        )

    def test_status_matches_result_urgency(self):
        self.assertEqual(self.out["status"], self.out["result"]["urgency"])


class TestAnalyzeBehavior(unittest.TestCase):
    def setUp(self):
        self.engine = RebalanceTriggerEngine()

    def test_demo_slots_trigger_drift(self):
        out = self.engine.analyze()
        self.assertTrue(out["result"]["triggered"])
        self.assertEqual(out["result"]["reason"], "ALLOCATION_DRIFT")

    def test_empty_slots_no_trigger(self):
        out = self.engine.analyze(slots=[])
        self.assertFalse(out["result"]["triggered"])
        self.assertEqual(out["result"]["reason"], "NO_SLOTS")
        self.assertEqual(out["status"], "NONE")

    def test_cooldown_short_circuits(self):
        # days_since_last below the 7-day minimum → COOLDOWN.
        slots = [AllocationSlot("a", 0.40, 0.60, 0.03, 0.03, 1)]
        out = self.engine.analyze(slots=slots)
        self.assertFalse(out["result"]["triggered"])
        self.assertTrue(out["result"]["reason"].startswith("COOLDOWN"))

    def test_no_drift_no_trigger(self):
        slots = [AllocationSlot("a", 0.50, 0.50, 0.04, 0.04, 30)]
        out = self.engine.analyze(slots=slots)
        self.assertFalse(out["result"]["triggered"])
        self.assertEqual(out["result"]["reason"], "NO_TRIGGER")

    def test_apy_change_triggers(self):
        slots = [AllocationSlot("a", 0.50, 0.50, 0.08, 0.04, 30)]  # +4% APY
        out = self.engine.analyze(slots=slots)
        self.assertTrue(out["result"]["triggered"])
        self.assertEqual(out["result"]["reason"], "APY_CHANGE")

    def test_drift_and_apy_change(self):
        slots = [AllocationSlot("a", 0.40, 0.60, 0.08, 0.04, 30)]
        out = self.engine.analyze(slots=slots)
        self.assertEqual(out["result"]["reason"], "DRIFT_AND_APY_CHANGE")

    def test_large_drift_is_immediate(self):
        slots = [AllocationSlot("a", 0.20, 0.50, 0.04, 0.04, 30)]  # 30% drift
        out = self.engine.analyze(slots=slots)
        self.assertEqual(out["status"], "IMMEDIATE")

    def test_actions_non_empty(self):
        out = self.engine.analyze()
        self.assertTrue(out["result"]["actions"])

    def test_drifted_slots_listed(self):
        slots = [
            AllocationSlot("drifter", 0.40, 0.60, 0.04, 0.04, 30),
            AllocationSlot("stable", 0.30, 0.30, 0.04, 0.04, 30),
        ]
        out = self.engine.analyze(slots=slots)
        self.assertIn("drifter", out["result"]["drifted_slots"])
        self.assertNotIn("stable", out["result"]["drifted_slots"])

    def test_json_serializable(self):
        import json

        json.dumps(self.engine.analyze())  # must not raise

    def test_max_drift_rounded_float(self):
        out = self.engine.analyze()
        self.assertIsInstance(out["result"]["max_drift"], float)


if __name__ == "__main__":
    unittest.main()
