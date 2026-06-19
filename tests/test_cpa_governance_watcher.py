"""
tests/test_cpa_governance_watcher.py

40 tests for spa_core.governance.cpa_governance_watcher
(MP-1343, Sprint v9.59)

Coverage:
  - CPAEvent creation, serialisation, from_dict round-trip
  - CPAGovernanceWatcher.emit() — appends event atomically
  - Ring-buffer cap=1000 enforced
  - recent_events(n) returns ≤ n events, newest-last order
  - events_by_type() filters correctly
  - summary() fields: total_events, by_type, latest, owner_has_signed,
                      paper_has_started, sources_promoted_count
  - All 6 factory methods produce correct event_type and details
  - Invalid event_type raises ValueError
  - Concurrent / repeated emit accumulates correctly
  - Empty-log edge cases

Run:
    python3 -m unittest tests/test_cpa_governance_watcher.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.governance.cpa_governance_watcher import (
    CPA_EVENT_TYPES,
    RING_BUFFER_CAP,
    CPAEvent,
    CPAGovernanceWatcher,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_watcher(tmpdir: str) -> CPAGovernanceWatcher:
    return CPAGovernanceWatcher(base_dir=tmpdir)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CPAEvent — basic construction & validation
# ══════════════════════════════════════════════════════════════════════════════


class TestCPAEventConstruction(unittest.TestCase):

    def test_valid_event_type_accepted(self):
        """Every type in CPA_EVENT_TYPES should be accepted."""
        for et in CPA_EVENT_TYPES:
            e = CPAEvent(event_type=et, details={})
            self.assertEqual(e.event_type, et)

    def test_invalid_event_type_raises_value_error(self):
        """Unknown event_type must raise ValueError."""
        with self.assertRaises(ValueError):
            CPAEvent(event_type="UNKNOWN_TYPE", details={})

    def test_details_stored_as_copy(self):
        """details dict is stored as a copy — mutations don't affect the event."""
        d = {"key": "value"}
        e = CPAEvent(event_type="CPA_GATE_CHANGE", details=d)
        d["key"] = "mutated"
        self.assertEqual(e.details["key"], "value")

    def test_timestamp_auto_assigned(self):
        """timestamp is auto-set when not provided."""
        e = CPAEvent(event_type="PAPER_STARTED", details={})
        self.assertIsNotNone(e.timestamp)
        self.assertIsInstance(e.timestamp, str)
        self.assertGreater(len(e.timestamp), 10)

    def test_custom_timestamp_preserved(self):
        """Explicitly provided timestamp is preserved unchanged."""
        ts = "2026-01-01T00:00:00+00:00"
        e = CPAEvent(event_type="PAPER_STARTED", details={}, timestamp=ts)
        self.assertEqual(e.timestamp, ts)


# ══════════════════════════════════════════════════════════════════════════════
# 2. CPAEvent — serialisation round-trip
# ══════════════════════════════════════════════════════════════════════════════


class TestCPAEventSerialization(unittest.TestCase):

    def setUp(self):
        self.ts = "2026-06-19T10:00:00+00:00"
        self.original = CPAEvent(
            event_type="SOURCE_PROMOTED",
            details={"source_id": "aave_v3", "to_state": "CLEAN_INCLUDED"},
            timestamp=self.ts,
        )

    def test_to_dict_has_required_keys(self):
        d = self.original.to_dict()
        self.assertIn("event_type", d)
        self.assertIn("timestamp", d)
        self.assertIn("details", d)

    def test_to_dict_values_correct(self):
        d = self.original.to_dict()
        self.assertEqual(d["event_type"], "SOURCE_PROMOTED")
        self.assertEqual(d["timestamp"], self.ts)
        self.assertEqual(d["details"]["source_id"], "aave_v3")

    def test_from_dict_reconstructs_correctly(self):
        d = self.original.to_dict()
        restored = CPAEvent.from_dict(d)
        self.assertEqual(restored.event_type, self.original.event_type)
        self.assertEqual(restored.timestamp, self.original.timestamp)
        self.assertEqual(restored.details, self.original.details)

    def test_from_dict_round_trip_equality(self):
        restored = CPAEvent.from_dict(self.original.to_dict())
        self.assertEqual(restored, self.original)

    def test_to_dict_is_json_serialisable(self):
        """to_dict() output must be JSON-safe."""
        d = self.original.to_dict()
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)
        round_tripped = json.loads(serialised)
        self.assertEqual(round_tripped["event_type"], "SOURCE_PROMOTED")


# ══════════════════════════════════════════════════════════════════════════════
# 3. CPAGovernanceWatcher — emit() basic behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestCPAGovernanceWatcherEmit(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_emit_creates_log_file(self):
        """emit() must create the log file if it doesn't exist."""
        e = CPAEvent("PAPER_STARTED", {"start_date": "2026-06-10"})
        self.watcher.emit(e)
        log_path = Path(self.tmpdir) / CPAGovernanceWatcher.LOG_PATH
        self.assertTrue(log_path.exists())

    def test_emit_appends_event(self):
        """After one emit, all_events() returns exactly 1 event."""
        e = CPAEvent("PAPER_STARTED", {"start_date": "2026-06-10"})
        self.watcher.emit(e)
        events = self.watcher.all_events()
        self.assertEqual(len(events), 1)

    def test_emit_multiple_events_accumulates(self):
        """Multiple emits accumulate correctly."""
        for i in range(5):
            self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {
                "gate_name": f"gate_{i}",
                "old_status": "FAIL",
                "new_status": "PASS",
            }))
        events = self.watcher.all_events()
        self.assertEqual(len(events), 5)

    def test_emit_preserves_event_type(self):
        """Emitted event_type is correctly stored."""
        e = CPAEvent("OWNER_ACCEPTANCE", {"owner": "Yurii"})
        self.watcher.emit(e)
        stored = self.watcher.all_events()[0]
        self.assertEqual(stored["event_type"], "OWNER_ACCEPTANCE")

    def test_emit_preserves_details(self):
        """Emitted details dict is correctly stored."""
        e = CPAEvent("SOURCE_PROMOTED", {"source_id": "compound_v3", "to_state": "CLEAN_INCLUDED"})
        self.watcher.emit(e)
        stored = self.watcher.all_events()[0]
        self.assertEqual(stored["details"]["source_id"], "compound_v3")

    def test_emit_log_is_valid_json(self):
        """The log file on disk must be valid JSON after emit."""
        self.watcher.emit(CPAEvent("PAPER_STARTED", {}))
        log_path = Path(self.tmpdir) / CPAGovernanceWatcher.LOG_PATH
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("events", data)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Ring-buffer cap
# ══════════════════════════════════════════════════════════════════════════════


class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ring_buffer_cap_1000_respected(self):
        """Log must never exceed RING_BUFFER_CAP events."""
        for i in range(RING_BUFFER_CAP + 50):
            self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {"i": i,
                "gate_name": "g", "old_status": "FAIL", "new_status": "PASS"}))
        events = self.watcher.all_events()
        self.assertLessEqual(len(events), RING_BUFFER_CAP)

    def test_ring_buffer_drops_oldest(self):
        """When cap is exceeded, oldest events are dropped (newest retained)."""
        # Emit cap+10 events, last one with unique marker
        for i in range(RING_BUFFER_CAP + 10):
            self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {
                "seq": i,
                "gate_name": "g",
                "old_status": "FAIL",
                "new_status": "PASS",
            }))
        events = self.watcher.all_events()
        # The newest event must be present
        self.assertEqual(events[-1]["details"]["seq"], RING_BUFFER_CAP + 9)

    def test_ring_buffer_does_not_drop_below_cap(self):
        """Exactly CAP events should all be retained."""
        for i in range(RING_BUFFER_CAP):
            self.watcher.emit(CPAEvent("PAPER_STARTED", {"i": i}))
        events = self.watcher.all_events()
        self.assertEqual(len(events), RING_BUFFER_CAP)


# ══════════════════════════════════════════════════════════════════════════════
# 5. recent_events()
# ══════════════════════════════════════════════════════════════════════════════


class TestRecentEvents(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_recent_events_returns_at_most_n(self):
        """recent_events(5) returns at most 5 events."""
        for i in range(20):
            self.watcher.emit(CPAEvent("PAPER_STARTED", {"i": i}))
        recent = self.watcher.recent_events(5)
        self.assertLessEqual(len(recent), 5)
        self.assertEqual(len(recent), 5)

    def test_recent_events_are_newest(self):
        """recent_events(3) returns the 3 most recently emitted events."""
        for i in range(10):
            self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {
                "seq": i, "gate_name": "g",
                "old_status": "FAIL", "new_status": "PASS",
            }))
        recent = self.watcher.recent_events(3)
        seqs = [e["details"]["seq"] for e in recent]
        self.assertEqual(seqs, [7, 8, 9])

    def test_recent_events_empty_log(self):
        """recent_events() on empty log returns []."""
        self.assertEqual(self.watcher.recent_events(10), [])

    def test_recent_events_fewer_than_n_available(self):
        """If fewer than n events exist, returns all available."""
        self.watcher.emit(CPAEvent("PAPER_STARTED", {}))
        recent = self.watcher.recent_events(20)
        self.assertEqual(len(recent), 1)

    def test_recent_events_default_n_20(self):
        """recent_events() with default n returns ≤ 20 events."""
        for i in range(30):
            self.watcher.emit(CPAEvent("PAPER_STARTED", {"i": i}))
        recent = self.watcher.recent_events()
        self.assertEqual(len(recent), 20)


# ══════════════════════════════════════════════════════════════════════════════
# 6. events_by_type()
# ══════════════════════════════════════════════════════════════════════════════


class TestEventsByType(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _populate(self):
        self.watcher.emit(CPAEvent("SOURCE_PROMOTED", {"source_id": "aave_v3", "to_state": "CLEAN_INCLUDED"}))
        self.watcher.emit(CPAEvent("SOURCE_PROMOTED", {"source_id": "compound_v3", "to_state": "CLEAN_INCLUDED"}))
        self.watcher.emit(CPAEvent("OWNER_ACCEPTANCE", {"owner": "Yurii"}))
        self.watcher.emit(CPAEvent("PAPER_STARTED", {"start_date": "2026-06-10"}))

    def test_events_by_type_source_promoted_count(self):
        """events_by_type('SOURCE_PROMOTED') returns 2 events."""
        self._populate()
        results = self.watcher.events_by_type("SOURCE_PROMOTED")
        self.assertEqual(len(results), 2)

    def test_events_by_type_owner_acceptance_count(self):
        self._populate()
        results = self.watcher.events_by_type("OWNER_ACCEPTANCE")
        self.assertEqual(len(results), 1)

    def test_events_by_type_excludes_other_types(self):
        """events_by_type returns only matching type."""
        self._populate()
        results = self.watcher.events_by_type("SOURCE_PROMOTED")
        for e in results:
            self.assertEqual(e["event_type"], "SOURCE_PROMOTED")

    def test_events_by_type_unknown_returns_empty(self):
        self._populate()
        results = self.watcher.events_by_type("NONEXISTENT")
        self.assertEqual(results, [])

    def test_events_by_type_empty_log(self):
        results = self.watcher.events_by_type("PAPER_STARTED")
        self.assertEqual(results, [])


# ══════════════════════════════════════════════════════════════════════════════
# 7. summary()
# ══════════════════════════════════════════════════════════════════════════════


class TestSummary(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_summary_empty_log(self):
        """summary() on empty log has correct zero-state."""
        s = self.watcher.summary()
        self.assertEqual(s["total_events"], 0)
        self.assertIsNone(s["latest"])
        self.assertFalse(s["owner_has_signed"])
        self.assertFalse(s["paper_has_started"])
        self.assertEqual(s["sources_promoted_count"], 0)

    def test_summary_owner_has_signed_false_initially(self):
        s = self.watcher.summary()
        self.assertFalse(s["owner_has_signed"])

    def test_summary_owner_has_signed_true_after_emit(self):
        """owner_has_signed = True after emitting OWNER_ACCEPTANCE."""
        self.watcher.emit(CPAEvent("OWNER_ACCEPTANCE", {"owner": "Yurii"}))
        s = self.watcher.summary()
        self.assertTrue(s["owner_has_signed"])

    def test_summary_paper_has_started_false_initially(self):
        s = self.watcher.summary()
        self.assertFalse(s["paper_has_started"])

    def test_summary_paper_has_started_true_after_emit(self):
        """paper_has_started = True after emitting PAPER_STARTED."""
        self.watcher.emit(CPAEvent("PAPER_STARTED", {"start_date": "2026-06-10"}))
        s = self.watcher.summary()
        self.assertTrue(s["paper_has_started"])

    def test_summary_sources_promoted_count(self):
        """sources_promoted_count equals number of SOURCE_PROMOTED events."""
        self.watcher.emit(CPAEvent("SOURCE_PROMOTED", {"source_id": "a", "to_state": "CLEAN_INCLUDED"}))
        self.watcher.emit(CPAEvent("SOURCE_PROMOTED", {"source_id": "b", "to_state": "CLEAN_INCLUDED"}))
        s = self.watcher.summary()
        self.assertEqual(s["sources_promoted_count"], 2)

    def test_summary_total_events_counts_all(self):
        for et in CPA_EVENT_TYPES[:3]:
            self.watcher.emit(CPAEvent(et, {}))
        s = self.watcher.summary()
        self.assertEqual(s["total_events"], 3)

    def test_summary_latest_is_last_emitted(self):
        self.watcher.emit(CPAEvent("PAPER_STARTED", {"start_date": "2026-06-10"}))
        self.watcher.emit(CPAEvent("OWNER_ACCEPTANCE", {"owner": "Yurii"}))
        s = self.watcher.summary()
        self.assertEqual(s["latest"]["event_type"], "OWNER_ACCEPTANCE")

    def test_summary_by_type_contains_all_event_types(self):
        s = self.watcher.summary()
        for et in CPA_EVENT_TYPES:
            self.assertIn(et, s["by_type"])

    def test_summary_by_type_counts_correctly(self):
        self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {
            "gate_name": "g", "old_status": "FAIL", "new_status": "PASS"}))
        self.watcher.emit(CPAEvent("CPA_GATE_CHANGE", {
            "gate_name": "g2", "old_status": "PASS", "new_status": "FAIL"}))
        s = self.watcher.summary()
        self.assertEqual(s["by_type"]["CPA_GATE_CHANGE"], 2)


# ══════════════════════════════════════════════════════════════════════════════
# 8. Factory methods
# ══════════════════════════════════════════════════════════════════════════════


class TestFactoryMethods(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.watcher = _make_watcher(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_change_event_type(self):
        e = self.watcher.gate_change_event("collateral_gate", "FAIL", "PASS")
        self.assertEqual(e.event_type, "CPA_GATE_CHANGE")

    def test_gate_change_event_details(self):
        e = self.watcher.gate_change_event("collateral_gate", "FAIL", "PASS")
        self.assertEqual(e.details["gate_name"], "collateral_gate")
        self.assertEqual(e.details["old_status"], "FAIL")
        self.assertEqual(e.details["new_status"], "PASS")

    def test_source_promoted_event_type(self):
        e = self.watcher.source_promoted_event("aave_v3", "CLEAN_INCLUDED")
        self.assertEqual(e.event_type, "SOURCE_PROMOTED")

    def test_source_promoted_event_details(self):
        e = self.watcher.source_promoted_event("aave_v3", "CLEAN_INCLUDED")
        self.assertEqual(e.details["source_id"], "aave_v3")
        self.assertEqual(e.details["to_state"], "CLEAN_INCLUDED")

    def test_owner_acceptance_event_type(self):
        e = self.watcher.owner_acceptance_event("Yurii")
        self.assertEqual(e.event_type, "OWNER_ACCEPTANCE")

    def test_owner_acceptance_event_details(self):
        e = self.watcher.owner_acceptance_event("Yurii")
        self.assertEqual(e.details["owner"], "Yurii")

    def test_evidence_milestone_event_type(self):
        e = self.watcher.evidence_milestone_event(10.5, 10)
        self.assertEqual(e.event_type, "PAPER_EVIDENCE_MILESTONE")

    def test_evidence_milestone_event_details(self):
        e = self.watcher.evidence_milestone_event(10.5, 10)
        self.assertEqual(e.details["evidence_points"], 10.5)
        self.assertEqual(e.details["milestone"], 10)

    def test_all_factories_produce_valid_events(self):
        """All factory events can be emitted and read back without error."""
        events = [
            self.watcher.gate_change_event("g", "FAIL", "PASS"),
            self.watcher.source_promoted_event("src1", "CLEAN_INCLUDED"),
            self.watcher.owner_acceptance_event("Owner"),
            self.watcher.evidence_milestone_event(20.0, 20),
            self.watcher.research_suspended_event("RS-001", "bear market", "bear"),
            self.watcher.paper_started_event("2026-06-10", "Owner"),
        ]
        for ev in events:
            self.watcher.emit(ev)
        stored = self.watcher.all_events()
        self.assertEqual(len(stored), 6)

    def test_factory_events_round_trip(self):
        """Factory-produced event survives to_dict / from_dict round-trip."""
        e = self.watcher.gate_change_event("g", "FAIL", "PASS")
        restored = CPAEvent.from_dict(e.to_dict())
        self.assertEqual(restored, e)


if __name__ == "__main__":
    unittest.main()
