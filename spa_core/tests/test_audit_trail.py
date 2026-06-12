"""Tests for spa_core.audit.audit_trail (MP-310).

Run with: python3 -m pytest spa_core/tests/test_audit_trail.py -v
or:        python3 -m unittest spa_core.tests.test_audit_trail -v

Covers ≥25 test cases:
  - begin_cycle creates valid UUID correlation_id
  - begin_cycle emits cycle_start event
  - record_event links prev_event_id
  - record_event stores all required fields
  - get_cycle_chain returns events in insertion order
  - get_cycle_chain filters by correlation_id (isolation between cycles)
  - export_signed_jsonl creates output file + manifest line with sha256
  - rotation triggered at >10MB
  - fail-safe behaviour when trail directory unavailable
  - unknown event_type accepted with warning
  - empty/missing trail file
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

# Adjust sys.path so the module is importable from the tests directory.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.audit.audit_trail import (
    VALID_EVENT_TYPES,
    begin_cycle,
    export_signed_jsonl,
    get_cycle_chain,
    record_event,
    _cycle_registry,
)


class _TmpDir:
    """Context manager: creates a temp dir and removes it on exit."""

    def __enter__(self) -> str:
        self._d = tempfile.mkdtemp(prefix="spa_audit_test_")
        return self._d

    def __exit__(self, *_) -> None:
        shutil.rmtree(self._d, ignore_errors=True)


# ─── begin_cycle ─────────────────────────────────────────────────────────────

class TestBeginCycle(unittest.TestCase):

    def test_returns_valid_uuid4(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            self.assertIsInstance(cid, str)
            self.assertTrue(len(cid) > 0)
            # Should parse as a UUID4.
            parsed = uuid.UUID(cid, version=4)
            self.assertEqual(str(parsed), cid)

    def test_two_calls_return_distinct_ids(self):
        with _TmpDir() as d:
            cid1 = begin_cycle("2026-06-11", data_dir=d)
            cid2 = begin_cycle("2026-06-12", data_dir=d)
            self.assertNotEqual(cid1, cid2)

    def test_cycle_start_event_emitted(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            chain = get_cycle_chain(cid, data_dir=d)
            self.assertTrue(len(chain) >= 1)
            self.assertEqual(chain[0]["event_type"], "cycle_start")

    def test_cycle_start_carries_cycle_date(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-15", data_dir=d)
            chain = get_cycle_chain(cid, data_dir=d)
            self.assertEqual(chain[0]["data"]["cycle_date"], "2026-06-15")

    def test_cycle_start_has_snapshot_id(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            chain = get_cycle_chain(cid, data_dir=d)
            sid = chain[0]["data"].get("snapshot_id", "")
            self.assertTrue(len(sid) > 0)

    def test_begin_cycle_failsafe_on_bad_dir(self):
        """begin_cycle should return empty string rather than raise on unwritable dir."""
        with patch("spa_core.audit.audit_trail._atomic_append_jsonl", side_effect=OSError("no write")):
            cid = begin_cycle("2026-06-11")
            # fail-safe → empty string returned, no exception raised
            self.assertIsInstance(cid, str)


# ─── record_event ─────────────────────────────────────────────────────────────

class TestRecordEvent(unittest.TestCase):

    def test_record_event_returns_dict_with_required_keys(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "allocation_proposal", {"pools": 3}, data_dir=d)
            for key in ("event_id", "correlation_id", "snapshot_id", "event_type",
                        "timestamp", "data", "prev_event_id"):
                self.assertIn(key, ev, f"Missing key: {key}")

    def test_record_event_links_prev_event_id(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            chain0 = get_cycle_chain(cid, data_dir=d)
            first_id = chain0[0]["event_id"]
            ev2 = record_event(cid, "allocation_proposal", {}, prev_event_id=first_id, data_dir=d)
            self.assertEqual(ev2["prev_event_id"], first_id)

    def test_record_event_default_prev_event_id_is_none(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "risk_verdict", {"approved": True}, data_dir=d)
            # prev_event_id may be None if not passed
            self.assertIsNone(ev.get("prev_event_id"))

    def test_record_event_stores_correct_event_type(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "trade_executed", {"trade_id": "T001"}, data_dir=d)
            self.assertEqual(ev["event_type"], "trade_executed")

    def test_record_event_stores_data_payload(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "trade_blocked", {"reason": "policy"}, data_dir=d)
            self.assertEqual(ev["data"]["reason"], "policy")

    def test_record_event_carries_correlation_id(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "risk_verdict", {}, data_dir=d)
            self.assertEqual(ev["correlation_id"], cid)

    def test_record_event_unknown_type_accepted(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ev = record_event(cid, "custom_unknown_type", {"foo": "bar"}, data_dir=d)
            self.assertNotIn("error", ev)
            self.assertEqual(ev["event_type"], "custom_unknown_type")

    def test_record_event_failsafe(self):
        """record_event must return error dict rather than raise."""
        with patch("spa_core.audit.audit_trail._atomic_append_jsonl", side_effect=OSError("disk full")):
            ev = record_event("fake-cid", "cycle_start", {})
            self.assertIn("error", ev)

    def test_record_event_event_ids_are_unique(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            ids = set()
            for etype in ("allocation_proposal", "risk_verdict", "trade_executed"):
                ev = record_event(cid, etype, {}, data_dir=d)
                ids.add(ev["event_id"])
            self.assertEqual(len(ids), 3)


# ─── get_cycle_chain ──────────────────────────────────────────────────────────

class TestGetCycleChain(unittest.TestCase):

    def test_returns_all_events_for_correlation_id(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            record_event(cid, "allocation_proposal", {}, data_dir=d)
            record_event(cid, "risk_verdict", {}, data_dir=d)
            record_event(cid, "trade_executed", {}, data_dir=d)
            chain = get_cycle_chain(cid, data_dir=d)
            # cycle_start + 3 records = 4
            self.assertEqual(len(chain), 4)

    def test_returns_events_in_insertion_order(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            for etype in ("allocation_proposal", "risk_verdict", "trade_executed"):
                record_event(cid, etype, {}, data_dir=d)
            chain = get_cycle_chain(cid, data_dir=d)
            types = [e["event_type"] for e in chain]
            self.assertEqual(types, ["cycle_start", "allocation_proposal", "risk_verdict", "trade_executed"])

    def test_filters_by_correlation_id(self):
        """Events from a different cycle must not appear in get_cycle_chain."""
        with _TmpDir() as d:
            cid1 = begin_cycle("2026-06-11", data_dir=d)
            cid2 = begin_cycle("2026-06-12", data_dir=d)
            record_event(cid1, "risk_verdict", {"cycle": 1}, data_dir=d)
            record_event(cid2, "risk_verdict", {"cycle": 2}, data_dir=d)
            chain1 = get_cycle_chain(cid1, data_dir=d)
            chain2 = get_cycle_chain(cid2, data_dir=d)
            for ev in chain1:
                self.assertEqual(ev["correlation_id"], cid1)
            for ev in chain2:
                self.assertEqual(ev["correlation_id"], cid2)

    def test_returns_empty_list_for_missing_file(self):
        with _TmpDir() as d:
            chain = get_cycle_chain("non-existent-cid", data_dir=d)
            self.assertEqual(chain, [])

    def test_returns_empty_list_for_unknown_cid(self):
        with _TmpDir() as d:
            begin_cycle("2026-06-11", data_dir=d)
            chain = get_cycle_chain("unknown-cid-xyz", data_dir=d)
            self.assertEqual(chain, [])

    def test_failsafe_on_unreadable_file(self):
        with _TmpDir() as d:
            with patch("spa_core.audit.audit_trail.Path.open", side_effect=OSError("no read")):
                result = get_cycle_chain("any-cid", data_dir=d)
                self.assertEqual(result, [])


# ─── export_signed_jsonl ──────────────────────────────────────────────────────

class TestExportSignedJsonl(unittest.TestCase):

    def test_creates_output_file(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            record_event(cid, "trade_executed", {}, data_dir=d)
            out = os.path.join(d, "export.jsonl")
            digest = export_signed_jsonl(out, data_dir=d)
            self.assertTrue(os.path.exists(out))
            self.assertIsInstance(digest, str)
            self.assertEqual(len(digest), 64)  # sha256 hex = 64 chars

    def test_output_ends_with_manifest_line(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            out = os.path.join(d, "export.jsonl")
            export_signed_jsonl(out, data_dir=d)
            lines = Path(out).read_text(encoding="utf-8").strip().split("\n")
            last = json.loads(lines[-1])
            self.assertEqual(last["event_type"], "manifest")
            self.assertIn("sha256", last)

    def test_manifest_sha256_matches_content(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            record_event(cid, "allocation_proposal", {}, data_dir=d)
            out = os.path.join(d, "export.jsonl")
            returned_digest = export_signed_jsonl(out, data_dir=d)

            # Read the exported file, strip the manifest line, recompute sha256
            content = Path(out).read_bytes()
            lines = content.split(b"\n")
            # Find the manifest line index (it's appended at the end)
            manifest_idx = None
            for i, line in enumerate(lines):
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    obj = json.loads(line_s)
                    if obj.get("event_type") == "manifest":
                        manifest_idx = i
                except Exception:
                    pass
            self.assertIsNotNone(manifest_idx)
            # Content before the manifest should match returned digest
            pre_manifest = b"\n".join(lines[:manifest_idx]) + b"\n"
            expected = hashlib.sha256(pre_manifest).hexdigest()
            self.assertEqual(returned_digest, expected)

    def test_export_empty_trail(self):
        with _TmpDir() as d:
            out = os.path.join(d, "export_empty.jsonl")
            digest = export_signed_jsonl(out, data_dir=d)
            self.assertIsInstance(digest, str)
            # sha256 of empty = known value
            self.assertEqual(digest, hashlib.sha256(b"").hexdigest())

    def test_export_failsafe(self):
        """export_signed_jsonl must return empty string on write error."""
        with _TmpDir() as d:
            with patch("spa_core.audit.audit_trail.tempfile.mkstemp", side_effect=OSError("no disk")):
                result = export_signed_jsonl(os.path.join(d, "x.jsonl"), data_dir=d)
                self.assertEqual(result, "")


# ─── Rotation ─────────────────────────────────────────────────────────────────

class TestRotation(unittest.TestCase):

    def test_rotation_triggered_at_10mb(self):
        """When the JSONL file exceeds MAX_JSONL_BYTES it is rotated to an archive."""
        import spa_core.audit.audit_trail as module

        with _TmpDir() as d:
            trail_path = Path(d) / "audit_trail.jsonl"
            # Write a file that is just over 10 MB.
            trail_path.write_bytes(b"x" * (module.MAX_JSONL_BYTES + 1))
            self.assertTrue(trail_path.exists())
            module._rotate_if_needed(trail_path)
            # Original file should be gone; archive should exist.
            self.assertFalse(trail_path.exists())
            archives = list(Path(d).glob("audit_trail_*.jsonl"))
            self.assertEqual(len(archives), 1)

    def test_no_rotation_below_threshold(self):
        import spa_core.audit.audit_trail as module

        with _TmpDir() as d:
            trail_path = Path(d) / "audit_trail.jsonl"
            trail_path.write_bytes(b"x" * 1024)  # 1 KB — well below threshold
            module._rotate_if_needed(trail_path)
            self.assertTrue(trail_path.exists())  # still there

    def test_rotation_resets_trail_for_new_events(self):
        """After rotation, new events should be written to a fresh file."""
        import spa_core.audit.audit_trail as module

        with _TmpDir() as d:
            trail_path = Path(d) / "audit_trail.jsonl"
            trail_path.write_bytes(b"x" * (module.MAX_JSONL_BYTES + 1))
            cid = begin_cycle("2026-06-11", data_dir=d)
            # New trail file should be created after rotation.
            self.assertTrue(trail_path.exists())
            chain = get_cycle_chain(cid, data_dir=d)
            self.assertGreater(len(chain), 0)


# ─── JSONL integrity ──────────────────────────────────────────────────────────

class TestJsonlIntegrity(unittest.TestCase):

    def test_every_line_is_valid_json(self):
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            for etype in ("allocation_proposal", "risk_verdict", "trade_blocked", "alert_sent"):
                record_event(cid, etype, {"x": 1}, data_dir=d)
            trail = Path(d) / "audit_trail.jsonl"
            for i, line in enumerate(trail.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    self.fail(f"Line {i} is not valid JSON: {e}\n  > {line}")

    def test_no_leftover_tmp_files(self):
        """Atomic write must not leave .tmp files behind on success."""
        with _TmpDir() as d:
            cid = begin_cycle("2026-06-11", data_dir=d)
            record_event(cid, "risk_verdict", {}, data_dir=d)
            tmps = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmps, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
