#!/usr/bin/env python3
"""`points_farm` accrues ZERO — owner decision 2026-08-16.

WHY (docs/AGGRESSIVE_PANEL_FEEDS.md §3): there is no public feed for "points yield". Points are
not quoted before the conversion ratio is disclosed. The panel nevertheless accrued a flat 6% a
year on the `points_farm` book, every single day, from a literal in feeds.py. That is a fabricated
number in the purest form (invariant 2) — worse than a gap, because a gap fails closed and is
visible while a literal quietly compounds.

The owner's decision is NOT "delete the book": the book stays in the panel, so its risk shape and
its position in the roster remain measurable. Its RETURN is zero until points are actually
distributed — an undistributed point is not income.

Time is an INPUT (no wall clock). No network.

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_points_are_zero.py -q
"""
from __future__ import annotations

# FROZEN-DATE-OK: injected-clock — no wall clock is consulted anywhere in this file. The dates
# are pure fixture keys: build_live_snapshot(as_of=...) injects the day, and
# historical_snapshots(start, end) is bounded by the same literals that key the injected
# series. Nothing here judges freshness, so the calendar cannot move this test.

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import feeds as fd
from spa_core.strategy_lab.aggressive_lab import roster as ro

FEEDS_SRC = Path(fd.__file__)


class TestPointsAccrueZero(unittest.TestCase):
    def test_default_points_apy_is_zero(self):
        self.assertEqual(fd.DEFAULT_POINTS_APY, 0.0)

    def test_history_snapshot_points_key_is_zero(self):
        f = fd.AggressiveFeeds(eth_price_series={"2026-01-01": 3000.0})
        snap = f.historical_snapshots("2026-01-01", "2026-01-01")[0]
        self.assertEqual(snap.defi_apy["points"], 0.0)

    def test_live_snapshot_points_key_is_zero(self):
        f = fd.AggressiveFeeds()
        snap = f.build_live_snapshot(as_of="2026-01-01")
        self.assertEqual(snap.defi_apy["points"], 0.0)

    def test_points_farm_book_accrues_nothing(self):
        """The end-to-end read: the BOOK, not just the feed key. It still exists, still steps,
        and its daily yield is exactly 0."""
        book = ro.build_roster()["points_farm"]
        book.init(100_000.0, {})
        f = fd.AggressiveFeeds(eth_price_series={"2026-01-01": 3000.0})
        snap = f.historical_snapshots("2026-01-01", "2026-01-01")[0]
        self.assertEqual(book._daily_yield_pct(snap), 0.0)

    def test_book_is_still_on_the_panel(self):
        """Zeroing the yield must not silently drop the book — the owner kept it."""
        self.assertIn("points_farm", ro.build_roster())

    def test_no_six_percent_literal_left_in_the_points_accrual_path(self):
        """The literal itself is the defect. A scan, because the next author's easiest mistake is
        to 'restore' the old default. Matches 0.06 / 6.0% style literals in feeds.py."""
        src = FEEDS_SRC.read_text(encoding="utf-8")
        # strip comments/docstrings-free scan is overkill; instead check the assignment forms
        offenders = re.findall(r"^\s*DEFAULT_POINTS_APY\s*=\s*(.+)$", src, flags=re.M)
        self.assertEqual(len(offenders), 1, "exactly one definition expected")
        self.assertTrue(offenders[0].strip().startswith("0.0"),
                        f"points default must be zero, got {offenders[0]!r}")
        code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        self.assertNotIn("0.06", "\n".join(code_lines),
                         "a 0.06 points literal is back in the accrual path")


if __name__ == "__main__":
    unittest.main()
