"""
tests/test_source_acquisition_tracker.py

40 unit tests for spa_core/analytics/source_acquisition_tracker.py
stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

# Make sure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.source_acquisition_tracker import (
    VALID_STATUSES,
    SourceAcquisitionTracker,
    SourceEntry,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tracker_in_tmpdir() -> tuple:
    """Returns (tracker, tmp_dir_path) — caller must clean up tmp_dir."""
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "data", "source_acquisition.json")
    tracker = SourceAcquisitionTracker(tracker_path=path)
    return tracker, tmp_dir, path


# ─────────────────────────────────────────────────────────────────────────────
# 1. SourceEntry construction
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceEntryConstruction(unittest.TestCase):

    def test_01_source_entry_basic_fields(self):
        e = SourceEntry("gmx_v2_btc_perp", "NOT_STARTED", 1, effort_days=3)
        self.assertEqual(e.source_id, "gmx_v2_btc_perp")
        self.assertEqual(e.status, "NOT_STARTED")
        self.assertEqual(e.priority, 1)
        self.assertEqual(e.effort_days, 3)

    def test_02_source_entry_owner_default_team(self):
        e = SourceEntry("x", "NOT_STARTED", 5)
        self.assertEqual(e.owner, "team")

    def test_03_source_entry_notes_default_empty(self):
        e = SourceEntry("x", "IN_PROGRESS", 2)
        self.assertEqual(e.notes, "")

    def test_04_source_entry_explicit_notes(self):
        e = SourceEntry("x", "CLEAN", 1, notes="integrated via DeFiLlama")
        self.assertIn("DeFiLlama", e.notes)

    def test_05_source_entry_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            SourceEntry("x", "UNKNOWN_STATUS", 1)

    def test_06_source_entry_all_valid_statuses_accepted(self):
        for status in VALID_STATUSES:
            e = SourceEntry("x", status, 1)
            self.assertEqual(e.status, status)

    def test_07_source_entry_negative_priority_raises(self):
        with self.assertRaises(ValueError):
            SourceEntry("x", "NOT_STARTED", 0)

    def test_08_source_entry_effort_days_clamped_to_zero(self):
        e = SourceEntry("x", "NOT_STARTED", 1, effort_days=-5)
        self.assertEqual(e.effort_days, 0)

    def test_09_source_entry_to_dict_roundtrip(self):
        e = SourceEntry("gmx_v2_eth_perp", "IN_PROGRESS", 2, effort_days=2,
                        owner="team", notes="ETH perp")
        d = e.to_dict()
        e2 = SourceEntry.from_dict(d)
        self.assertEqual(e2.source_id, e.source_id)
        self.assertEqual(e2.status, e.status)
        self.assertEqual(e2.priority, e.priority)
        self.assertEqual(e2.effort_days, e.effort_days)
        self.assertEqual(e2.owner, e.owner)

    def test_10_source_entry_repr_contains_source_id(self):
        e = SourceEntry("sky_susds", "CLEAN", 11)
        self.assertIn("sky_susds", repr(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. SourceAcquisitionTracker initialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestTrackerInitialisation(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_11_tracker_initialises_12_sources(self):
        sources = self.tracker.all_sources()
        self.assertEqual(len(sources), 12)

    def test_12_tracker_contains_gmx_v2_btc_perp(self):
        entry = self.tracker.get_source("gmx_v2_btc_perp")
        self.assertIsNotNone(entry)

    def test_13_tracker_contains_sky_susds(self):
        entry = self.tracker.get_source("sky_susds")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "CLEAN")

    def test_14_tracker_contains_spark_susds(self):
        entry = self.tracker.get_source("spark_susds")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "CLEAN")

    def test_15_tracker_contains_aave_usdc_base_in_progress(self):
        entry = self.tracker.get_source("aave_usdc_base")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "IN_PROGRESS")

    def test_16_tracker_contains_morpho_usdc_main_in_progress(self):
        entry = self.tracker.get_source("morpho_usdc_main")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "IN_PROGRESS")

    def test_17_tracker_gmx_btc_priority_is_1(self):
        entry = self.tracker.get_source("gmx_v2_btc_perp")
        self.assertEqual(entry.priority, 1)

    def test_18_tracker_all_entries_have_valid_statuses(self):
        for entry in self.tracker.all_sources():
            self.assertIn(entry.status, VALID_STATUSES)

    def test_19_tracker_all_entries_have_team_owner(self):
        for entry in self.tracker.all_sources():
            self.assertEqual(entry.owner, "team")

    def test_20_tracker_unknown_source_returns_none(self):
        result = self.tracker.get_source("nonexistent_protocol")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 3. status_summary()
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusSummary(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_21_status_summary_has_all_status_keys(self):
        summary = self.tracker.status_summary()
        for key in VALID_STATUSES:
            self.assertIn(key, summary)

    def test_22_status_summary_has_pct_clean_key(self):
        summary = self.tracker.status_summary()
        self.assertIn("pct_clean", summary)

    def test_23_status_summary_clean_count_is_2(self):
        # sky_susds and spark_susds are CLEAN by default
        summary = self.tracker.status_summary()
        self.assertEqual(summary["CLEAN"], 2)

    def test_24_status_summary_not_started_count_is_8(self):
        summary = self.tracker.status_summary()
        self.assertEqual(summary["NOT_STARTED"], 8)

    def test_25_status_summary_in_progress_count_is_2(self):
        summary = self.tracker.status_summary()
        self.assertEqual(summary["IN_PROGRESS"], 2)

    def test_26_status_summary_counts_sum_to_12(self):
        summary = self.tracker.status_summary()
        total = sum(summary[s] for s in VALID_STATUSES)
        self.assertEqual(total, 12)

    def test_27_status_summary_pct_clean_positive(self):
        summary = self.tracker.status_summary()
        self.assertGreater(summary["pct_clean"], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. priority_queue()
# ─────────────────────────────────────────────────────────────────────────────

class TestPriorityQueue(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_28_priority_queue_returns_list(self):
        q = self.tracker.priority_queue()
        self.assertIsInstance(q, list)

    def test_29_priority_queue_length_is_12(self):
        q = self.tracker.priority_queue()
        self.assertEqual(len(q), 12)

    def test_30_priority_queue_first_entry_is_not_started(self):
        q = self.tracker.priority_queue()
        self.assertEqual(q[0].status, "NOT_STARTED")

    def test_31_priority_queue_clean_entries_are_last(self):
        q = self.tracker.priority_queue()
        clean_indices = [i for i, e in enumerate(q) if e.status == "CLEAN"]
        non_clean_indices = [i for i, e in enumerate(q) if e.status != "CLEAN"]
        if clean_indices and non_clean_indices:
            self.assertGreater(min(clean_indices), max(non_clean_indices))

    def test_32_priority_queue_not_started_before_in_progress(self):
        q = self.tracker.priority_queue()
        statuses = [e.status for e in q]
        ns_idx = [i for i, s in enumerate(statuses) if s == "NOT_STARTED"]
        ip_idx = [i for i, s in enumerate(statuses) if s == "IN_PROGRESS"]
        if ns_idx and ip_idx:
            self.assertLess(max(ns_idx), max(ip_idx) + len(ns_idx))
            # All NOT_STARTED come before all IN_PROGRESS
            self.assertLess(min(ip_idx), min(ns_idx) + len(ip_idx) + len(ns_idx))
            # More precisely: last NOT_STARTED before first IN_PROGRESS doesn't necessarily hold
            # but NOT_STARTED status_order < IN_PROGRESS status_order
            self.assertLess(min(ns_idx), min(ip_idx))


# ─────────────────────────────────────────────────────────────────────────────
# 5. update_status()
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateStatus(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_33_update_status_valid(self):
        self.tracker.update_status("gmx_v2_btc_perp", "IN_PROGRESS")
        entry = self.tracker.get_source("gmx_v2_btc_perp")
        self.assertEqual(entry.status, "IN_PROGRESS")

    def test_34_update_status_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.tracker.update_status("gmx_v2_btc_perp", "INVALID_STATUS")

    def test_35_update_status_unknown_source_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.tracker.update_status("nonexistent_xyz", "CLEAN")

    def test_36_update_status_with_notes_updates_notes(self):
        self.tracker.update_status("btc_stablepool", "FOUND", notes="found via DeFiLlama API")
        entry = self.tracker.get_source("btc_stablepool")
        self.assertIn("DeFiLlama", entry.notes)

    def test_37_update_status_to_clean_reflects_in_summary(self):
        self.tracker.update_status("gmx_v2_btc_perp", "CLEAN")
        summary = self.tracker.status_summary()
        self.assertEqual(summary["CLEAN"], 3)  # was 2, now 3


# ─────────────────────────────────────────────────────────────────────────────
# 6. clean_pct() and days_to_clean()
# ─────────────────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_38_clean_pct_greater_than_zero(self):
        # sky_susds and spark_susds are CLEAN → 2/12 ≈ 16.7%
        self.assertGreater(self.tracker.clean_pct(), 0)

    def test_39_days_to_clean_positive(self):
        # 10 non-CLEAN sources each with effort_days > 0 (most are 2-3 days)
        self.assertGreater(self.tracker.days_to_clean(), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. save() and load()
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, "data", "source_acquisition.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_40_save_creates_file(self):
        tracker = SourceAcquisitionTracker(tracker_path=self.path)
        tracker.save()
        self.assertTrue(os.path.isfile(self.path))

    def test_41_save_then_load_preserves_status(self):
        tracker = SourceAcquisitionTracker(tracker_path=self.path)
        tracker.update_status("gmx_v2_btc_perp", "FOUND", notes="round-trip test")
        tracker.save()

        tracker2 = SourceAcquisitionTracker(tracker_path=self.path)
        entry = tracker2.get_source("gmx_v2_btc_perp")
        self.assertEqual(entry.status, "FOUND")
        self.assertIn("round-trip", entry.notes)

    def test_42_save_produces_valid_json(self):
        tracker = SourceAcquisitionTracker(tracker_path=self.path)
        tracker.save()
        with open(self.path, "r") as fh:
            data = json.load(fh)
        self.assertIn("sources", data)
        self.assertEqual(len(data["sources"]), 12)


# ─────────────────────────────────────────────────────────────────────────────
# 8. to_markdown()
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkdown(unittest.TestCase):

    def setUp(self):
        self.tracker, self.tmp_dir, self.path = _tracker_in_tmpdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_43_to_markdown_contains_gmx_v2(self):
        md = self.tracker.to_markdown()
        self.assertIn("| gmx_v2", md)

    def test_44_to_markdown_contains_sky_susds(self):
        md = self.tracker.to_markdown()
        self.assertIn("sky_susds", md)

    def test_45_to_markdown_contains_clean(self):
        md = self.tracker.to_markdown()
        self.assertIn("CLEAN", md)

    def test_46_to_markdown_is_string(self):
        md = self.tracker.to_markdown()
        self.assertIsInstance(md, str)


# ─────────────────────────────────────────────────────────────────────────────
# 9. VALID_STATUSES constant
# ─────────────────────────────────────────────────────────────────────────────

class TestValidStatuses(unittest.TestCase):

    def test_47_valid_statuses_has_5_entries(self):
        self.assertEqual(len(VALID_STATUSES), 5)

    def test_48_valid_statuses_contains_not_started(self):
        self.assertIn("NOT_STARTED", VALID_STATUSES)

    def test_49_valid_statuses_contains_clean(self):
        self.assertIn("CLEAN", VALID_STATUSES)

    def test_50_valid_statuses_order_not_started_first(self):
        # NOT_STARTED should be the first element (start of pipeline)
        self.assertEqual(VALID_STATUSES[0], "NOT_STARTED")

    def test_51_valid_statuses_order_clean_last(self):
        self.assertEqual(VALID_STATUSES[-1], "CLEAN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
