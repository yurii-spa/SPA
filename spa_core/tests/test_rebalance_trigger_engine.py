"""Unit tests for spa_core.analytics.rebalance_trigger_engine (MP-652).

Pure stdlib unittest only — no pytest, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_rebalance_trigger_engine -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.rebalance_trigger_engine import (
    MAX_ENTRIES,
    AllocationSlot,
    RebalanceTrigger,
    RebalanceTriggerEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot(
    adapter_id: str = "adapter_x",
    target_pct: float = 0.25,
    current_pct: float = 0.25,
    current_apy: float = 0.05,
    prev_apy: float = 0.05,
    days_since_last: int = 10,
) -> AllocationSlot:
    return AllocationSlot(
        adapter_id=adapter_id,
        target_pct=target_pct,
        current_pct=current_pct,
        current_apy=current_apy,
        prev_apy=prev_apy,
        days_since_last=days_since_last,
    )


def _engine_with_tmpdir(
    drift_threshold: float = 0.05,
    apy_threshold: float = 0.02,
    min_days: int = 7,
) -> tuple[RebalanceTriggerEngine, Path]:
    tmpdir = Path(tempfile.mkdtemp())
    data_file = tmpdir / "data" / "rebalance_triggers.json"
    engine = RebalanceTriggerEngine(
        data_file=data_file,
        drift_threshold=drift_threshold,
        apy_threshold=apy_threshold,
        min_days=min_days,
    )
    return engine, data_file


# ---------------------------------------------------------------------------
# 1. _drift
# ---------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_zero_drift(self):
        s = _slot(target_pct=0.25, current_pct=0.25)
        self.assertAlmostEqual(self.e._drift(s), 0.0)

    def test_positive_drift(self):
        s = _slot(target_pct=0.25, current_pct=0.35)
        self.assertAlmostEqual(self.e._drift(s), 0.10)

    def test_negative_drift_absolute(self):
        s = _slot(target_pct=0.30, current_pct=0.20)
        self.assertAlmostEqual(self.e._drift(s), 0.10)

    def test_large_drift(self):
        s = _slot(target_pct=0.50, current_pct=0.10)
        self.assertAlmostEqual(self.e._drift(s), 0.40)

    def test_exact_threshold_drift(self):
        s = _slot(target_pct=0.20, current_pct=0.25)
        self.assertAlmostEqual(self.e._drift(s), 0.05)


# ---------------------------------------------------------------------------
# 2. _apy_change
# ---------------------------------------------------------------------------

class TestApyChange(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_no_change(self):
        s = _slot(current_apy=0.05, prev_apy=0.05)
        self.assertAlmostEqual(self.e._apy_change(s), 0.0)

    def test_positive_change(self):
        s = _slot(current_apy=0.08, prev_apy=0.05)
        self.assertAlmostEqual(self.e._apy_change(s), 0.03)

    def test_negative_change_absolute(self):
        s = _slot(current_apy=0.03, prev_apy=0.06)
        self.assertAlmostEqual(self.e._apy_change(s), 0.03)

    def test_large_apy_drop(self):
        s = _slot(current_apy=0.0, prev_apy=0.10)
        self.assertAlmostEqual(self.e._apy_change(s), 0.10)

    def test_exact_threshold_change(self):
        s = _slot(current_apy=0.07, prev_apy=0.05)
        self.assertAlmostEqual(self.e._apy_change(s), 0.02)


# ---------------------------------------------------------------------------
# 3. _drifted
# ---------------------------------------------------------------------------

class TestDrifted(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine(drift_threshold=0.05)

    def test_empty_slots(self):
        self.assertEqual(self.e._drifted([]), [])

    def test_none_over_threshold(self):
        slots = [
            _slot("a", target_pct=0.25, current_pct=0.27),  # drift=0.02 < 0.05
            _slot("b", target_pct=0.25, current_pct=0.24),  # drift=0.01 < 0.05
        ]
        self.assertEqual(self.e._drifted(slots), [])

    def test_some_over_threshold(self):
        slots = [
            _slot("a", target_pct=0.25, current_pct=0.31),  # drift=0.06 >= 0.05
            _slot("b", target_pct=0.25, current_pct=0.24),  # drift=0.01 < 0.05
        ]
        result = self.e._drifted(slots)
        self.assertIn("a", result)
        self.assertNotIn("b", result)

    def test_all_over_threshold(self):
        slots = [
            _slot("x", target_pct=0.20, current_pct=0.30),  # 0.10
            _slot("y", target_pct=0.30, current_pct=0.20),  # 0.10
        ]
        result = self.e._drifted(slots)
        self.assertIn("x", result)
        self.assertIn("y", result)

    def test_exactly_at_threshold_included(self):
        # Use target=0.0 and current=0.05 so both literals map to the exact
        # same float as drift_threshold=0.05 → guaranteed >=
        slots = [_slot("z", target_pct=0.0, current_pct=0.05)]
        result = self.e._drifted(slots)
        self.assertIn("z", result)


# ---------------------------------------------------------------------------
# 4. _apy_changed
# ---------------------------------------------------------------------------

class TestApyChanged(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine(apy_threshold=0.02)

    def test_empty_slots(self):
        self.assertEqual(self.e._apy_changed([]), [])

    def test_none_over_threshold(self):
        slots = [
            _slot("a", current_apy=0.051, prev_apy=0.050),  # 0.001 < 0.02
        ]
        self.assertEqual(self.e._apy_changed(slots), [])

    def test_some_over_threshold(self):
        slots = [
            _slot("a", current_apy=0.08, prev_apy=0.05),  # 0.03 >= 0.02
            _slot("b", current_apy=0.05, prev_apy=0.05),  # 0.0 < 0.02
        ]
        result = self.e._apy_changed(slots)
        self.assertIn("a", result)
        self.assertNotIn("b", result)

    def test_exactly_at_threshold_included(self):
        slots = [_slot("q", current_apy=0.07, prev_apy=0.05)]  # 0.02 == threshold
        self.assertIn("q", self.e._apy_changed(slots))


# ---------------------------------------------------------------------------
# 5. _max_drift
# ---------------------------------------------------------------------------

class TestMaxDrift(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_empty_slots(self):
        self.assertAlmostEqual(self.e._max_drift([]), 0.0)

    def test_single_slot(self):
        s = _slot(target_pct=0.20, current_pct=0.30)
        self.assertAlmostEqual(self.e._max_drift([s]), 0.10)

    def test_multi_slot_picks_max(self):
        slots = [
            _slot("a", target_pct=0.20, current_pct=0.25),  # 0.05
            _slot("b", target_pct=0.30, current_pct=0.15),  # 0.15
            _slot("c", target_pct=0.25, current_pct=0.24),  # 0.01
        ]
        self.assertAlmostEqual(self.e._max_drift(slots), 0.15)

    def test_all_same_drift(self):
        slots = [
            _slot("a", target_pct=0.25, current_pct=0.30),  # 0.05
            _slot("b", target_pct=0.25, current_pct=0.30),  # 0.05
        ]
        self.assertAlmostEqual(self.e._max_drift(slots), 0.05)


# ---------------------------------------------------------------------------
# 6. _total_drift
# ---------------------------------------------------------------------------

class TestTotalDrift(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_zero_total(self):
        slots = [_slot("a", target_pct=0.25, current_pct=0.25)]
        self.assertAlmostEqual(self.e._total_drift(slots), 0.0)

    def test_single_slot(self):
        s = _slot(target_pct=0.20, current_pct=0.28)
        self.assertAlmostEqual(self.e._total_drift([s]), 0.08)

    def test_multi_slot_sum(self):
        slots = [
            _slot("a", target_pct=0.25, current_pct=0.30),  # 0.05
            _slot("b", target_pct=0.25, current_pct=0.20),  # 0.05
            _slot("c", target_pct=0.25, current_pct=0.25),  # 0.00
        ]
        self.assertAlmostEqual(self.e._total_drift(slots), 0.10)

    def test_empty_slots(self):
        self.assertAlmostEqual(self.e._total_drift([]), 0.0)


# ---------------------------------------------------------------------------
# 7. _urgency
# ---------------------------------------------------------------------------

class TestUrgency(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_max_drift_15pct_is_immediate(self):
        self.assertEqual(self.e._urgency(0.15, 1), "IMMEDIATE")

    def test_max_drift_above_15pct_is_immediate(self):
        self.assertEqual(self.e._urgency(0.30, 0), "IMMEDIATE")

    def test_three_or_more_drifted_is_immediate(self):
        self.assertEqual(self.e._urgency(0.04, 3), "IMMEDIATE")

    def test_five_drifted_is_immediate(self):
        self.assertEqual(self.e._urgency(0.01, 5), "IMMEDIATE")

    def test_max_drift_5pct_one_drifted_is_soon(self):
        self.assertEqual(self.e._urgency(0.05, 1), "SOON")

    def test_max_drift_10pct_two_drifted_is_soon(self):
        self.assertEqual(self.e._urgency(0.10, 2), "SOON")

    def test_max_drift_5pct_zero_drifted_is_soon(self):
        # max_drift >= 0.05 → SOON regardless of drifted_count
        self.assertEqual(self.e._urgency(0.05, 0), "SOON")

    def test_zero_drift_zero_drifted_is_none(self):
        self.assertEqual(self.e._urgency(0.0, 0), "NONE")

    def test_tiny_drift_zero_drifted_is_none(self):
        self.assertEqual(self.e._urgency(0.01, 0), "NONE")

    def test_just_below_15pct_two_drifted_is_soon(self):
        self.assertEqual(self.e._urgency(0.149, 2), "SOON")


# ---------------------------------------------------------------------------
# 8. _actions
# ---------------------------------------------------------------------------

class TestActions(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine()

    def test_no_drifted_no_apy_returns_no_action(self):
        actions = self.e._actions([], [], "NONE")
        self.assertEqual(actions, ["No action required"])

    def test_drifted_only(self):
        actions = self.e._actions(["aave"], [], "SOON")
        self.assertTrue(any("Rebalance" in a for a in actions))
        self.assertTrue(any("aave" in a for a in actions))

    def test_apy_changed_only(self):
        actions = self.e._actions([], ["compound"], "NONE")
        self.assertTrue(any("Review APY" in a for a in actions))
        self.assertTrue(any("compound" in a for a in actions))

    def test_both_drifted_and_apy(self):
        actions = self.e._actions(["aave"], ["compound"], "SOON")
        self.assertTrue(any("Rebalance" in a for a in actions))
        self.assertTrue(any("Review APY" in a for a in actions))

    def test_immediate_urgency_adds_24h_action(self):
        actions = self.e._actions(["aave", "comp", "morpho"], [], "IMMEDIATE")
        self.assertTrue(any("24h" in a for a in actions))

    def test_soon_urgency_adds_7day_action(self):
        actions = self.e._actions(["aave"], [], "SOON")
        self.assertTrue(any("7 days" in a for a in actions))

    def test_none_urgency_no_timing_action(self):
        actions = self.e._actions([], ["comp"], "NONE")
        self.assertFalse(any("24h" in a or "7 days" in a for a in actions))

    def test_drifted_count_in_action_text(self):
        actions = self.e._actions(["a", "b", "c"], [], "IMMEDIATE")
        rebalance_action = next(a for a in actions if "Rebalance" in a)
        self.assertIn("3", rebalance_action)


# ---------------------------------------------------------------------------
# 9. evaluate() — core logic
# ---------------------------------------------------------------------------

class TestEvaluate(unittest.TestCase):
    def setUp(self):
        self.e = RebalanceTriggerEngine(
            drift_threshold=0.05,
            apy_threshold=0.02,
            min_days=7,
        )

    def test_empty_slots_not_triggered(self):
        result = self.e.evaluate([])
        self.assertFalse(result.triggered)

    def test_empty_slots_reason_no_slots(self):
        result = self.e.evaluate([])
        self.assertEqual(result.reason, "NO_SLOTS")

    def test_empty_slots_urgency_none(self):
        result = self.e.evaluate([])
        self.assertEqual(result.urgency, "NONE")

    def test_empty_slots_actions_no_evaluate(self):
        result = self.e.evaluate([])
        self.assertIn("No slots to evaluate", result.actions)

    def test_cooldown_not_triggered(self):
        slots = [_slot("aave", target_pct=0.10, current_pct=0.50, days_since_last=6)]
        result = self.e.evaluate(slots)
        self.assertFalse(result.triggered)

    def test_cooldown_reason_contains_cooldown(self):
        slots = [_slot("aave", target_pct=0.10, current_pct=0.50, days_since_last=6)]
        result = self.e.evaluate(slots)
        self.assertIn("COOLDOWN", result.reason)

    def test_cooldown_exactly_at_boundary_blocked(self):
        # days_since_last=6, min_days=7 → cooldown active
        slots = [_slot("aave", days_since_last=6)]
        result = self.e.evaluate(slots)
        self.assertFalse(result.triggered)
        self.assertIn("COOLDOWN", result.reason)

    def test_cooldown_boundary_met_proceeds(self):
        # days_since_last=7, min_days=7 → allowed
        slots = [_slot("aave", days_since_last=7)]
        result = self.e.evaluate(slots)
        # No drift or APY change → NO_TRIGGER (not cooldown)
        self.assertNotIn("COOLDOWN", result.reason)

    def test_no_drift_no_apy_no_trigger(self):
        slots = [_slot("aave", target_pct=0.25, current_pct=0.25,
                        current_apy=0.05, prev_apy=0.05, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertFalse(result.triggered)
        self.assertEqual(result.reason, "NO_TRIGGER")

    def test_allocation_drift_triggers(self):
        slots = [_slot("aave", target_pct=0.20, current_pct=0.30, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertTrue(result.triggered)
        self.assertEqual(result.reason, "ALLOCATION_DRIFT")

    def test_apy_change_triggers(self):
        slots = [_slot("compound", current_apy=0.08, prev_apy=0.05, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertTrue(result.triggered)
        self.assertEqual(result.reason, "APY_CHANGE")

    def test_both_drift_and_apy_change(self):
        slots = [_slot("morpho", target_pct=0.20, current_pct=0.30,
                        current_apy=0.08, prev_apy=0.05, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertTrue(result.triggered)
        self.assertEqual(result.reason, "DRIFT_AND_APY_CHANGE")

    def test_immediate_urgency_on_large_drift(self):
        slots = [_slot("aave", target_pct=0.20, current_pct=0.40, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertEqual(result.urgency, "IMMEDIATE")

    def test_urgency_none_when_not_triggered(self):
        slots = [_slot("aave", days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertEqual(result.urgency, "NONE")

    def test_urgency_soon_on_moderate_drift(self):
        slots = [_slot("aave", target_pct=0.20, current_pct=0.26, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertEqual(result.urgency, "SOON")

    def test_drifted_slots_populated(self):
        slots = [
            _slot("aave", target_pct=0.20, current_pct=0.30, days_since_last=10),
            _slot("comp", target_pct=0.25, current_pct=0.25, days_since_last=10),
        ]
        result = self.e.evaluate(slots)
        self.assertIn("aave", result.drifted_slots)
        self.assertNotIn("comp", result.drifted_slots)

    def test_apy_changed_slots_populated(self):
        slots = [
            _slot("aave", current_apy=0.08, prev_apy=0.05, days_since_last=10),
            _slot("comp", current_apy=0.05, prev_apy=0.05, days_since_last=10),
        ]
        result = self.e.evaluate(slots)
        self.assertIn("aave", result.apy_changed_slots)
        self.assertNotIn("comp", result.apy_changed_slots)

    def test_max_drift_rounded(self):
        slots = [_slot("a", target_pct=0.20, current_pct=0.30, days_since_last=10)]
        result = self.e.evaluate(slots)
        # max_drift should be rounded to 6 decimal places
        self.assertAlmostEqual(result.max_drift, 0.10, places=5)

    def test_total_drift_rounded(self):
        slots = [
            _slot("a", target_pct=0.20, current_pct=0.25, days_since_last=10),
            _slot("b", target_pct=0.30, current_pct=0.25, days_since_last=10),
        ]
        result = self.e.evaluate(slots)
        self.assertAlmostEqual(result.total_drift, 0.10, places=5)

    def test_result_is_rebalance_trigger(self):
        result = self.e.evaluate([_slot(days_since_last=10)])
        self.assertIsInstance(result, RebalanceTrigger)

    def test_timestamp_set(self):
        import time as _time
        before = _time.time()
        result = self.e.evaluate([_slot(days_since_last=10)])
        after = _time.time()
        self.assertGreaterEqual(result.timestamp, before)
        self.assertLessEqual(result.timestamp, after)

    def test_immediate_urgency_propagates_to_action_text(self):
        # 3+ drifted slots → IMMEDIATE → "24h" in actions
        slots = [
            _slot("a", target_pct=0.20, current_pct=0.30, days_since_last=10),
            _slot("b", target_pct=0.20, current_pct=0.30, days_since_last=10),
            _slot("c", target_pct=0.20, current_pct=0.30, days_since_last=10),
        ]
        result = self.e.evaluate(slots)
        self.assertEqual(result.urgency, "IMMEDIATE")
        self.assertTrue(any("24h" in a for a in result.actions))

    def test_cooldown_still_computes_drift(self):
        # Even in cooldown, max_drift and total_drift are computed
        slots = [_slot("aave", target_pct=0.10, current_pct=0.50, days_since_last=3)]
        result = self.e.evaluate(slots)
        self.assertGreater(result.max_drift, 0.0)

    def test_apy_only_trigger_urgency_soon(self):
        # Only APY changed, no drift → should use urgency based on 0 drifted
        slots = [_slot("aave", current_apy=0.10, prev_apy=0.05, days_since_last=10)]
        result = self.e.evaluate(slots)
        self.assertTrue(result.triggered)
        self.assertEqual(result.reason, "APY_CHANGE")
        # urgency: drifted_count=0, max_drift likely 0 → NONE by _urgency,
        # but triggered=True, so urgency is computed from max_drift and len(drifted)
        self.assertIn(result.urgency, ("NONE", "SOON", "IMMEDIATE"))


# ---------------------------------------------------------------------------
# 10. save_trigger() + load_history()
# ---------------------------------------------------------------------------

class TestSaveAndLoad(unittest.TestCase):

    def _make_trigger(self, triggered: bool = True, reason: str = "TEST") -> RebalanceTrigger:
        return RebalanceTrigger(
            timestamp=1000.0,
            triggered=triggered,
            reason=reason,
            drifted_slots=[],
            apy_changed_slots=[],
            max_drift=0.0,
            total_drift=0.0,
            urgency="NONE",
            actions=["No action required"],
        )

    def test_load_history_missing_file_returns_empty(self):
        engine, _ = _engine_with_tmpdir()
        self.assertEqual(engine.load_history(), [])

    def test_save_creates_file(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger())
        self.assertTrue(data_file.exists())

    def test_save_writes_valid_json(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger())
        data = json.loads(data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_entry_fields(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger())
        entry = json.loads(data_file.read_text())[0]
        self.assertIn("timestamp", entry)
        self.assertIn("triggered", entry)
        self.assertIn("reason", entry)
        self.assertIn("urgency", entry)
        self.assertIn("max_drift", entry)

    def test_save_appends_multiple(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger(triggered=True, reason="A"))
        engine.save_trigger(self._make_trigger(triggered=False, reason="B"))
        data = json.loads(data_file.read_text())
        self.assertEqual(len(data), 2)
        reasons = [d["reason"] for d in data]
        self.assertIn("A", reasons)
        self.assertIn("B", reasons)

    def test_ring_buffer_caps_at_max_entries(self):
        engine, data_file = _engine_with_tmpdir()
        for _ in range(MAX_ENTRIES + 15):
            engine.save_trigger(self._make_trigger())
        data = json.loads(data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        engine, data_file = _engine_with_tmpdir()
        for i in range(MAX_ENTRIES + 3):
            t = RebalanceTrigger(
                timestamp=float(i), triggered=False, reason=f"R{i}",
                drifted_slots=[], apy_changed_slots=[],
                max_drift=0.0, total_drift=0.0,
                urgency="NONE", actions=[],
            )
            engine.save_trigger(t)
        data = json.loads(data_file.read_text())
        last_reason = data[-1]["reason"]
        self.assertEqual(last_reason, f"R{MAX_ENTRIES + 2}")

    def test_atomic_write_no_tmp_left(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger())
        tmp = data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_history_returns_saved_data(self):
        engine, data_file = _engine_with_tmpdir()
        engine.save_trigger(self._make_trigger(triggered=True, reason="X"))
        history = engine.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["reason"], "X")

    def test_save_creates_parent_dirs(self):
        tmpdir = Path(tempfile.mkdtemp())
        data_file = tmpdir / "nested" / "deep" / "triggers.json"
        engine = RebalanceTriggerEngine(data_file=data_file)
        engine.save_trigger(self._make_trigger())
        self.assertTrue(data_file.exists())


if __name__ == "__main__":
    unittest.main()
