"""Tests for PortfolioSnapshotDiff (MP-609).

Run:
    python3 -m unittest spa_core.tests.test_portfolio_snapshot_diff -v

Covers:
    TestAdapterChange        (12) — change_type values, is_significant, deltas
    TestPortfolioDiff        ( 8) — trend, summary, counts
    TestLoadSnapshots        ( 8) — empty file, one record, ring-buffer cap
    TestGetLastTwo           ( 6) — <2 → ValueError, exact 2, >2 → last two
    TestDiffAdapters         (25) — added/removed/weight/apy/unchanged combos
    TestComputeDiff          (15) — all PortfolioDiff fields
    TestSaveDiff             ( 5) — atomic write, ring-buffer ≤30
    TestFormatTelegramMessage( 6) — ≤1500 chars, contains key strings
Total: 85 tests
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.analytics.portfolio_snapshot_diff import (
    AdapterChange,
    PortfolioDiff,
    PortfolioSnapshotDiff,
    _RING_BUFFER_MAX,
    _OUTPUT_FILENAME,
    _TRACKER_FILENAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(
    adapter_id: str,
    weight_pct: float = 20.0,
    apy_pct: float = 5.0,
) -> dict:
    return {
        "adapter_id": adapter_id,
        "weight_pct": weight_pct,
        "apy_pct": apy_pct,
        "allocated_usd": weight_pct * 1000,
        "daily_yield_usd": 1.0,
        "annual_yield_usd": 365.0,
        "contribution_pct": weight_pct,
    }


def _make_snapshot(
    adapters: list | None = None,
    effective_apy_pct: float = 5.0,
    total_allocated_usd: float = 100_000.0,
    generated_at: str = "2026-06-10T08:00:00+00:00",
) -> dict:
    if adapters is None:
        adapters = []
    return {
        "generated_at": generated_at,
        "effective_apy_pct": effective_apy_pct,
        "total_allocated_usd": total_allocated_usd,
        "contributions": adapters,
    }


def _write_tracker(tmp_dir: str, snapshots: list) -> str:
    """Write a yield_attribution_tracker.json to tmp_dir and return the path."""
    data = {
        "schema_version": "1.0",
        "source": "yield_attribution_tracker",
        "last_updated": "2026-06-10T08:00:00+00:00",
        "latest": snapshots[-1] if snapshots else {},
        "snapshots": snapshots,
    }
    path = os.path.join(tmp_dir, _TRACKER_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _make_differ(tmp_dir: str) -> PortfolioSnapshotDiff:
    return PortfolioSnapshotDiff(data_path=tmp_dir)


# ---------------------------------------------------------------------------
# TestAdapterChange (12)
# ---------------------------------------------------------------------------


class TestAdapterChange(unittest.TestCase):

    def _change(self, **kwargs) -> AdapterChange:
        defaults = dict(
            adapter_key="test",
            change_type="unchanged",
            old_weight_pct=10.0,
            new_weight_pct=10.0,
            old_apy_pct=5.0,
            new_apy_pct=5.0,
            weight_delta=0.0,
            apy_delta=0.0,
            is_significant=False,
        )
        defaults.update(kwargs)
        return AdapterChange(**defaults)

    def test_change_type_added(self):
        c = self._change(change_type="added")
        self.assertEqual(c.change_type, "added")

    def test_change_type_removed(self):
        c = self._change(change_type="removed")
        self.assertEqual(c.change_type, "removed")

    def test_change_type_weight_up(self):
        c = self._change(change_type="weight_up", weight_delta=2.0, is_significant=True)
        self.assertEqual(c.change_type, "weight_up")

    def test_change_type_weight_down(self):
        c = self._change(change_type="weight_down", weight_delta=-2.0, is_significant=True)
        self.assertEqual(c.change_type, "weight_down")

    def test_change_type_apy_up(self):
        c = self._change(change_type="apy_up", apy_delta=0.5, is_significant=True)
        self.assertEqual(c.change_type, "apy_up")

    def test_change_type_apy_down(self):
        c = self._change(change_type="apy_down", apy_delta=-0.5, is_significant=True)
        self.assertEqual(c.change_type, "apy_down")

    def test_change_type_unchanged(self):
        c = self._change(change_type="unchanged")
        self.assertEqual(c.change_type, "unchanged")
        self.assertFalse(c.is_significant)

    def test_is_significant_weight_threshold(self):
        # Exactly at threshold: NOT significant
        c = self._change(weight_delta=1.0, apy_delta=0.0)
        sig = abs(c.weight_delta) > 1.0 or abs(c.apy_delta) > 0.1
        self.assertFalse(sig)

    def test_is_significant_weight_above_threshold(self):
        c = self._change(weight_delta=1.01, apy_delta=0.0, is_significant=True)
        self.assertTrue(c.is_significant)

    def test_is_significant_apy_threshold(self):
        # Exactly at threshold: NOT significant
        c = self._change(weight_delta=0.0, apy_delta=0.1)
        sig = abs(c.weight_delta) > 1.0 or abs(c.apy_delta) > 0.1
        self.assertFalse(sig)

    def test_is_significant_apy_above_threshold(self):
        c = self._change(apy_delta=0.11, is_significant=True)
        self.assertTrue(c.is_significant)

    def test_to_dict_keys(self):
        c = self._change()
        d = c.to_dict()
        for key in ("adapter_key", "change_type", "old_weight_pct", "new_weight_pct",
                    "old_apy_pct", "new_apy_pct", "weight_delta", "apy_delta", "is_significant"):
            self.assertIn(key, d)


# ---------------------------------------------------------------------------
# TestPortfolioDiff (8)
# ---------------------------------------------------------------------------


class TestPortfolioDiff(unittest.TestCase):

    def _diff(self, **kwargs) -> PortfolioDiff:
        defaults = dict(
            generated_at="2026-06-10T09:00:00+00:00",
            snapshot_old_at="2026-06-09T08:00:00+00:00",
            snapshot_new_at="2026-06-10T08:00:00+00:00",
            hours_apart=24.0,
            old_portfolio_apy=5.07,
            new_portfolio_apy=5.22,
            apy_delta=0.15,
            old_allocated_usd=100_000.0,
            new_allocated_usd=100_000.0,
            allocated_delta_usd=0.0,
            trend="IMPROVING",
            summary="APY +0.15% (5.07%→5.22%)",
        )
        defaults.update(kwargs)
        return PortfolioDiff(**defaults)

    def test_trend_improving(self):
        d = self._diff(apy_delta=0.15, trend="IMPROVING")
        self.assertEqual(d.trend, "IMPROVING")

    def test_trend_declining(self):
        d = self._diff(apy_delta=-0.15, trend="DECLINING")
        self.assertEqual(d.trend, "DECLINING")

    def test_trend_stable(self):
        d = self._diff(apy_delta=0.05, trend="STABLE")
        self.assertEqual(d.trend, "STABLE")

    def test_summary_contains_apy_delta(self):
        d = self._diff(summary="APY +0.15% (5.07%→5.22%)")
        self.assertIn("APY", d.summary)

    def test_unchanged_count(self):
        c = AdapterChange("a", "unchanged", 10.0, 10.0, 5.0, 5.0, 0.0, 0.0, False)
        d = self._diff(changes=[c], unchanged_count=1, changed_count=0)
        self.assertEqual(d.unchanged_count, 1)
        self.assertEqual(d.changed_count, 0)

    def test_changed_count(self):
        c = AdapterChange("b", "weight_up", 10.0, 15.0, 5.0, 5.0, 5.0, 0.0, True)
        d = self._diff(changes=[c], changed_count=1, unchanged_count=0)
        self.assertEqual(d.changed_count, 1)

    def test_to_dict_has_all_keys(self):
        d = self._diff()
        dd = d.to_dict()
        for key in ("generated_at", "trend", "apy_delta", "changes",
                    "added_adapters", "removed_adapters", "significant_changes",
                    "total_adapters_old", "total_adapters_new", "summary"):
            self.assertIn(key, dd)

    def test_to_dict_changes_serialized(self):
        c = AdapterChange("x", "apy_up", 5.0, 5.0, 4.0, 4.5, 0.0, 0.5, True)
        d = self._diff(changes=[c])
        dd = d.to_dict()
        self.assertEqual(len(dd["changes"]), 1)
        self.assertEqual(dd["changes"][0]["adapter_key"], "x")


# ---------------------------------------------------------------------------
# TestLoadSnapshots (8)
# ---------------------------------------------------------------------------


class TestLoadSnapshots(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        result = self.differ.load_snapshots()
        self.assertEqual(result, [])

    def test_empty_file_returns_empty(self):
        path = os.path.join(self.tmp, _TRACKER_FILENAME)
        open(path, "w").close()
        result = self.differ.load_snapshots()
        self.assertEqual(result, [])

    def test_invalid_json_returns_empty(self):
        path = os.path.join(self.tmp, _TRACKER_FILENAME)
        with open(path, "w") as f:
            f.write("NOT JSON{{{")
        result = self.differ.load_snapshots()
        self.assertEqual(result, [])

    def test_non_dict_root_returns_empty(self):
        path = os.path.join(self.tmp, _TRACKER_FILENAME)
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        result = self.differ.load_snapshots()
        self.assertEqual(result, [])

    def test_missing_snapshots_key_returns_empty(self):
        path = os.path.join(self.tmp, _TRACKER_FILENAME)
        with open(path, "w") as f:
            json.dump({"schema_version": "1.0"}, f)
        result = self.differ.load_snapshots()
        self.assertEqual(result, [])

    def test_one_snapshot_returns_list_of_one(self):
        snap = _make_snapshot()
        _write_tracker(self.tmp, [snap])
        result = self.differ.load_snapshots()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["effective_apy_pct"], 5.0)

    def test_multiple_snapshots_preserved(self):
        snaps = [_make_snapshot(effective_apy_pct=float(i)) for i in range(5)]
        _write_tracker(self.tmp, snaps)
        result = self.differ.load_snapshots()
        self.assertEqual(len(result), 5)

    def test_more_than_ring_buffer_capped(self):
        # 35 snapshots → only last 30 returned
        snaps = [_make_snapshot(effective_apy_pct=float(i)) for i in range(35)]
        _write_tracker(self.tmp, snaps)
        result = self.differ.load_snapshots()
        self.assertLessEqual(len(result), _RING_BUFFER_MAX)
        # newest (apy=34) should be last
        self.assertEqual(result[-1]["effective_apy_pct"], 34.0)


# ---------------------------------------------------------------------------
# TestGetLastTwo (6)
# ---------------------------------------------------------------------------


class TestGetLastTwo(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_snapshots_raises(self):
        # no tracker file at all
        with self.assertRaises(ValueError):
            self.differ.get_last_two()

    def test_one_snapshot_raises(self):
        _write_tracker(self.tmp, [_make_snapshot()])
        with self.assertRaises(ValueError):
            self.differ.get_last_two()

    def test_exactly_two_returns_both(self):
        s1 = _make_snapshot(effective_apy_pct=4.0)
        s2 = _make_snapshot(effective_apy_pct=5.0)
        _write_tracker(self.tmp, [s1, s2])
        old, new = self.differ.get_last_two()
        self.assertEqual(old["effective_apy_pct"], 4.0)
        self.assertEqual(new["effective_apy_pct"], 5.0)

    def test_three_snapshots_returns_last_two(self):
        snaps = [_make_snapshot(effective_apy_pct=float(i)) for i in (1, 2, 3)]
        _write_tracker(self.tmp, snaps)
        old, new = self.differ.get_last_two()
        self.assertEqual(old["effective_apy_pct"], 2.0)
        self.assertEqual(new["effective_apy_pct"], 3.0)

    def test_returns_tuple_of_two(self):
        snaps = [_make_snapshot() for _ in range(5)]
        _write_tracker(self.tmp, snaps)
        result = self.differ.get_last_two()
        self.assertEqual(len(result), 2)

    def test_error_message_contains_count(self):
        _write_tracker(self.tmp, [_make_snapshot()])
        try:
            self.differ.get_last_two()
            self.fail("Expected ValueError")
        except ValueError as exc:
            self.assertIn("1", str(exc))


# ---------------------------------------------------------------------------
# TestDiffAdapters (25)
# ---------------------------------------------------------------------------


class TestDiffAdapters(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snap(self, adapters):
        return _make_snapshot(adapters=adapters)

    # --- Added ---

    def test_adapter_added_change_type(self):
        old = self._snap([])
        new = self._snap([_make_adapter("alpha", 20.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "added")

    def test_adapter_added_old_weight_is_none(self):
        old = self._snap([])
        new = self._snap([_make_adapter("alpha", 20.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertIsNone(changes[0].old_weight_pct)

    def test_adapter_added_new_weight_populated(self):
        old = self._snap([])
        new = self._snap([_make_adapter("alpha", 20.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].new_weight_pct, 20.0)

    def test_adapter_added_old_apy_is_none(self):
        old = self._snap([])
        new = self._snap([_make_adapter("alpha", 20.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertIsNone(changes[0].old_apy_pct)

    def test_adapter_added_new_apy_populated(self):
        old = self._snap([])
        new = self._snap([_make_adapter("alpha", 20.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].new_apy_pct, 5.0)

    # --- Removed ---

    def test_adapter_removed_change_type(self):
        old = self._snap([_make_adapter("beta", 30.0, 6.0)])
        new = self._snap([])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "removed")

    def test_adapter_removed_new_weight_is_none(self):
        old = self._snap([_make_adapter("beta", 30.0, 6.0)])
        new = self._snap([])
        changes = self.differ.diff_adapters(old, new)
        self.assertIsNone(changes[0].new_weight_pct)

    def test_adapter_removed_old_weight_populated(self):
        old = self._snap([_make_adapter("beta", 30.0, 6.0)])
        new = self._snap([])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].old_weight_pct, 30.0)

    # --- Weight changes ---

    def test_weight_up_change_type(self):
        old = self._snap([_make_adapter("g", 10.0, 5.0)])
        new = self._snap([_make_adapter("g", 15.0, 5.0)])  # +5 > threshold
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "weight_up")

    def test_weight_down_change_type(self):
        old = self._snap([_make_adapter("h", 20.0, 5.0)])
        new = self._snap([_make_adapter("h", 10.0, 5.0)])  # -10 < -threshold
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "weight_down")

    def test_weight_delta_computed_correctly(self):
        old = self._snap([_make_adapter("x", 10.0, 5.0)])
        new = self._snap([_make_adapter("x", 15.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertAlmostEqual(changes[0].weight_delta, 5.0, places=5)

    def test_weight_up_is_significant(self):
        old = self._snap([_make_adapter("y", 10.0, 5.0)])
        new = self._snap([_make_adapter("y", 15.0, 5.0)])  # +5% weight
        changes = self.differ.diff_adapters(old, new)
        self.assertTrue(changes[0].is_significant)

    def test_weight_below_threshold_not_weight_change(self):
        # 0.5% weight change — below 1.0 threshold
        old = self._snap([_make_adapter("z", 10.0, 5.0)])
        new = self._snap([_make_adapter("z", 10.5, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        # should not be weight_up
        self.assertNotIn(changes[0].change_type, ("weight_up", "weight_down"))

    # --- APY changes ---

    def test_apy_up_change_type(self):
        old = self._snap([_make_adapter("m", 10.0, 5.0)])
        new = self._snap([_make_adapter("m", 10.0, 5.5)])  # +0.5 > 0.1 threshold
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "apy_up")

    def test_apy_down_change_type(self):
        old = self._snap([_make_adapter("n", 10.0, 5.0)])
        new = self._snap([_make_adapter("n", 10.0, 4.5)])  # -0.5 < -0.1 threshold
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "apy_down")

    def test_apy_delta_computed_correctly(self):
        old = self._snap([_make_adapter("p", 10.0, 5.0)])
        new = self._snap([_make_adapter("p", 10.0, 5.5)])
        changes = self.differ.diff_adapters(old, new)
        self.assertAlmostEqual(changes[0].apy_delta, 0.5, places=5)

    def test_apy_is_significant(self):
        old = self._snap([_make_adapter("q", 10.0, 5.0)])
        new = self._snap([_make_adapter("q", 10.0, 5.5)])
        changes = self.differ.diff_adapters(old, new)
        self.assertTrue(changes[0].is_significant)

    # --- Unchanged ---

    def test_unchanged_no_movement(self):
        old = self._snap([_make_adapter("r", 10.0, 5.0)])
        new = self._snap([_make_adapter("r", 10.0, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "unchanged")
        self.assertFalse(changes[0].is_significant)

    def test_unchanged_small_weight_delta(self):
        # 0.5% weight change — below threshold
        old = self._snap([_make_adapter("s", 10.0, 5.0)])
        new = self._snap([_make_adapter("s", 10.4, 5.0)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "unchanged")

    def test_unchanged_small_apy_delta(self):
        # 0.05% apy change — below threshold
        old = self._snap([_make_adapter("t", 10.0, 5.0)])
        new = self._snap([_make_adapter("t", 10.0, 5.05)])
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes[0].change_type, "unchanged")

    # --- Multiple adapters ---

    def test_all_old_equals_all_new_all_unchanged(self):
        adapters = [_make_adapter(f"a{i}", float(10+i), 5.0) for i in range(3)]
        old = self._snap(adapters)
        new = self._snap(adapters)
        changes = self.differ.diff_adapters(old, new)
        self.assertTrue(all(c.change_type == "unchanged" for c in changes))

    def test_mix_of_added_removed_changed(self):
        old_adapters = [
            _make_adapter("keep", 40.0, 5.0),
            _make_adapter("remove", 30.0, 4.0),
        ]
        new_adapters = [
            _make_adapter("keep", 55.0, 5.0),   # weight +15 → weight_up
            _make_adapter("add", 20.0, 6.0),     # added
        ]
        old = self._snap(old_adapters)
        new = self._snap(new_adapters)
        changes = self.differ.diff_adapters(old, new)
        types = {c.adapter_key: c.change_type for c in changes}
        self.assertEqual(types["keep"], "weight_up")
        self.assertEqual(types["remove"], "removed")
        self.assertEqual(types["add"], "added")

    def test_weight_takes_priority_over_apy(self):
        # Both weight and APY changed significantly; weight should win
        old = self._snap([_make_adapter("w", 10.0, 5.0)])
        new = self._snap([_make_adapter("w", 15.0, 5.5)])  # +5 weight, +0.5 apy
        changes = self.differ.diff_adapters(old, new)
        # weight_up should take priority
        self.assertIn(changes[0].change_type, ("weight_up", "weight_down"))

    def test_empty_contributions_field(self):
        old = _make_snapshot()  # no adapters → contributions=[]
        new = _make_snapshot()
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes, [])

    def test_missing_contributions_key(self):
        old = {"generated_at": "2026-06-10T08:00:00+00:00", "effective_apy_pct": 5.0}
        new = {"generated_at": "2026-06-11T08:00:00+00:00", "effective_apy_pct": 5.0}
        changes = self.differ.diff_adapters(old, new)
        self.assertEqual(changes, [])


# ---------------------------------------------------------------------------
# TestComputeDiff (15)
# ---------------------------------------------------------------------------


class TestComputeDiff(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _two_snaps(
        self,
        old_apy=5.0, new_apy=5.0,
        old_alloc=100_000.0, new_alloc=100_000.0,
        old_adapters=None, new_adapters=None,
        old_ts="2026-06-10T08:00:00+00:00",
        new_ts="2026-06-11T08:00:00+00:00",
    ):
        old = _make_snapshot(old_adapters or [], old_apy, old_alloc, old_ts)
        new = _make_snapshot(new_adapters or [], new_apy, new_alloc, new_ts)
        return old, new

    def test_apy_delta_positive(self):
        old, new = self._two_snaps(old_apy=5.0, new_apy=5.2)
        diff = self.differ.compute_diff(old, new)
        self.assertAlmostEqual(diff.apy_delta, 0.2, places=4)

    def test_apy_delta_negative(self):
        old, new = self._two_snaps(old_apy=5.2, new_apy=5.0)
        diff = self.differ.compute_diff(old, new)
        self.assertAlmostEqual(diff.apy_delta, -0.2, places=4)

    def test_allocated_delta(self):
        old, new = self._two_snaps(old_alloc=100_000.0, new_alloc=105_000.0)
        diff = self.differ.compute_diff(old, new)
        self.assertAlmostEqual(diff.allocated_delta_usd, 5_000.0, places=1)

    def test_trend_improving(self):
        old, new = self._two_snaps(old_apy=5.0, new_apy=5.2)
        diff = self.differ.compute_diff(old, new)
        self.assertEqual(diff.trend, "IMPROVING")

    def test_trend_declining(self):
        old, new = self._two_snaps(old_apy=5.2, new_apy=5.0)
        diff = self.differ.compute_diff(old, new)
        self.assertEqual(diff.trend, "DECLINING")

    def test_trend_stable(self):
        old, new = self._two_snaps(old_apy=5.0, new_apy=5.05)
        diff = self.differ.compute_diff(old, new)
        self.assertEqual(diff.trend, "STABLE")

    def test_added_adapters_list(self):
        old, new = self._two_snaps(
            new_adapters=[_make_adapter("fresh", 20.0, 5.0)],
        )
        diff = self.differ.compute_diff(old, new)
        self.assertIn("fresh", diff.added_adapters)

    def test_removed_adapters_list(self):
        old, new = self._two_snaps(
            old_adapters=[_make_adapter("gone", 20.0, 5.0)],
        )
        diff = self.differ.compute_diff(old, new)
        self.assertIn("gone", diff.removed_adapters)

    def test_significant_changes_list(self):
        old, new = self._two_snaps(
            old_adapters=[_make_adapter("x", 10.0, 5.0)],
            new_adapters=[_make_adapter("x", 15.0, 5.0)],  # +5% weight
        )
        diff = self.differ.compute_diff(old, new)
        self.assertIn("x", diff.significant_changes)

    def test_hours_apart_computed(self):
        old, new = self._two_snaps(
            old_ts="2026-06-10T08:00:00+00:00",
            new_ts="2026-06-11T08:00:00+00:00",
        )
        diff = self.differ.compute_diff(old, new)
        self.assertAlmostEqual(diff.hours_apart, 24.0, places=1)

    def test_hours_apart_zero_on_same_ts(self):
        ts = "2026-06-10T08:00:00+00:00"
        old, new = self._two_snaps(old_ts=ts, new_ts=ts)
        diff = self.differ.compute_diff(old, new)
        self.assertAlmostEqual(diff.hours_apart, 0.0, places=1)

    def test_snapshot_timestamps_stored(self):
        old, new = self._two_snaps(
            old_ts="2026-06-10T08:00:00+00:00",
            new_ts="2026-06-11T08:00:00+00:00",
        )
        diff = self.differ.compute_diff(old, new)
        self.assertEqual(diff.snapshot_old_at, "2026-06-10T08:00:00+00:00")
        self.assertEqual(diff.snapshot_new_at, "2026-06-11T08:00:00+00:00")

    def test_summary_non_empty(self):
        old, new = self._two_snaps(old_apy=5.0, new_apy=5.2)
        diff = self.differ.compute_diff(old, new)
        self.assertTrue(len(diff.summary) > 0)

    def test_loads_from_disk_when_no_args(self):
        snaps = [
            _make_snapshot(effective_apy_pct=4.0, generated_at="2026-06-10T08:00:00+00:00"),
            _make_snapshot(effective_apy_pct=5.0, generated_at="2026-06-11T08:00:00+00:00"),
        ]
        _write_tracker(self.tmp, snaps)
        diff = self.differ.compute_diff()  # no args
        self.assertAlmostEqual(diff.old_portfolio_apy, 4.0, places=3)
        self.assertAlmostEqual(diff.new_portfolio_apy, 5.0, places=3)

    def test_generated_at_is_utc_iso(self):
        old, new = self._two_snaps()
        diff = self.differ.compute_diff(old, new)
        # Should parse without error
        dt = datetime.fromisoformat(diff.generated_at.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)


# ---------------------------------------------------------------------------
# TestSaveDiff (5)
# ---------------------------------------------------------------------------


class TestSaveDiff(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _simple_diff(self) -> PortfolioDiff:
        old = _make_snapshot(effective_apy_pct=5.0)
        new = _make_snapshot(effective_apy_pct=5.1)
        return self.differ.compute_diff(old, new)

    def test_save_creates_file(self):
        diff = self._simple_diff()
        path = self.differ.save_diff(diff)
        self.assertTrue(os.path.exists(path))

    def test_save_returns_path_string(self):
        diff = self._simple_diff()
        path = self.differ.save_diff(diff)
        self.assertIsInstance(path, str)

    def test_no_tmp_leftover(self):
        diff = self._simple_diff()
        self.differ.save_diff(diff)
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_max_30(self):
        # Write 35 diffs; file should never hold more than 30
        for i in range(35):
            old = _make_snapshot(effective_apy_pct=float(i))
            new = _make_snapshot(effective_apy_pct=float(i + 0.1))
            diff = self.differ.compute_diff(old, new)
            self.differ.save_diff(diff)

        out_path = os.path.join(self.tmp, _OUTPUT_FILENAME)
        with open(out_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["history"]), 30)

    def test_second_save_appends_to_history(self):
        d1 = self._simple_diff()
        self.differ.save_diff(d1)
        d2 = self._simple_diff()
        self.differ.save_diff(d2)
        out_path = os.path.join(self.tmp, _OUTPUT_FILENAME)
        with open(out_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["history"]), 2)


# ---------------------------------------------------------------------------
# TestFormatTelegramMessage (6)
# ---------------------------------------------------------------------------


class TestFormatTelegramMessage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.differ = _make_differ(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _diff(self, old_apy=5.07, new_apy=5.22) -> PortfolioDiff:
        old = _make_snapshot(
            effective_apy_pct=old_apy,
            generated_at="2026-06-10T08:00:00+00:00",
        )
        new = _make_snapshot(
            effective_apy_pct=new_apy,
            generated_at="2026-06-11T08:00:00+00:00",
        )
        return self.differ.compute_diff(old, new)

    def test_message_max_1500_chars(self):
        diff = self._diff()
        msg = self.differ.format_telegram_message(diff)
        self.assertLessEqual(len(msg), 1500)

    def test_message_contains_trend(self):
        diff = self._diff(old_apy=5.0, new_apy=5.2)
        msg = self.differ.format_telegram_message(diff)
        self.assertIn("IMPROVING", msg)

    def test_message_contains_old_apy(self):
        diff = self._diff(old_apy=5.07, new_apy=5.22)
        msg = self.differ.format_telegram_message(diff)
        self.assertIn("5.07", msg)

    def test_message_contains_new_apy(self):
        diff = self._diff(old_apy=5.07, new_apy=5.22)
        msg = self.differ.format_telegram_message(diff)
        self.assertIn("5.22", msg)

    def test_message_declining_trend(self):
        diff = self._diff(old_apy=5.5, new_apy=5.0)
        msg = self.differ.format_telegram_message(diff)
        self.assertIn("DECLINING", msg)

    def test_message_from_disk_when_no_diff(self):
        snaps = [
            _make_snapshot(effective_apy_pct=5.0, generated_at="2026-06-10T08:00:00+00:00"),
            _make_snapshot(effective_apy_pct=5.2, generated_at="2026-06-11T08:00:00+00:00"),
        ]
        _write_tracker(self.tmp, snaps)
        # call without pre-computed diff
        msg = self.differ.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)
        self.assertTrue(len(msg) > 0)


if __name__ == "__main__":
    unittest.main()
