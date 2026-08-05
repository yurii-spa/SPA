"""Gap monitor: a one-day hole is a hole.

Positive control for a real incident. The paper track lost two days —
**2026-07-19 and 2026-07-27** — and the monitor whose entire job is finding
gaps reported ``has_gaps: false``, ``day_gaps: []`` for the whole time. Both
holes sit inside its own window, and the go-live gate counts evidenced days, so
each one quietly pushed the launch back with no signal anywhere.

The cause was a threshold, not a bug in the arithmetic: gaps counted only when
more than three calendar days were missing, justified as "doesn't fit a weekend
skip". That reasoning is imported from markets with trading hours. This track
runs every day at 06:00 UTC and its weekends are populated — 2026-07-19 was a
Sunday whose Saturday and Monday neighbours are both present. So any hole of
one to three days was invisible by construction, and both real holes were
exactly one day.

``test_the_two_real_holes_are_found`` is the positive control: it replays the
actual shape of the incident and fails against the old threshold. A check that
has never seen the failure it exists to catch is decoration.
"""
# FROZEN-DATE-OK: 2026-07-19 and 2026-07-27 ARE the subject of this file — they
# are the days the track actually lost, and the positive control replays that
# exact incident. Substituting relative timestamps would test a different,
# hypothetical hole and would no longer fail against the threshold that let the
# real one through. The age-window tests below deliberately use relative dates
# instead, because there the calendar is incidental.
from __future__ import annotations

import unittest
from datetime import date, timedelta

from spa_core.paper_trading.gap_monitor import _GAP_ACTIONABLE_DAYS, check_day_gaps


def _bar(d: date) -> dict:
    """An evidenced daily bar — the shape check_day_gaps accepts as real."""
    return {
        "date": d.isoformat(),
        "evidenced": True,
        "is_demo": False,
        "source": "cycle_runner",
        "snapshots": 1,
        "equity": 100_000.0,
    }


def _run(days: list[date]) -> dict:
    return check_day_gaps([_bar(d) for d in days])


def _span(start: str, end: str, skip: tuple = ()) -> list[date]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out, cur = [], a
    while cur <= b:
        if cur.isoformat() not in skip:
            out.append(cur)
        cur += timedelta(days=1)
    return out


class TestInteriorHoles(unittest.TestCase):

    def test_the_two_real_holes_are_found(self):
        """The incident itself: 2026-07-19 and 2026-07-27, one day each.

        Fails against the previous ``delta > 3`` threshold, which is the point.
        """
        res = _run(_span("2026-07-10", "2026-08-01", skip=("2026-07-19", "2026-07-27")))
        self.assertTrue(res["has_gaps"], "two missing days must not report as 'no gaps'")
        self.assertEqual(len(res["day_gaps"]), 2)
        self.assertEqual(res["days_missed_total"], 2)
        self.assertEqual(
            [(g["from"], g["to"]) for g in res["day_gaps"]],
            [("2026-07-18", "2026-07-20"), ("2026-07-26", "2026-07-28")],
        )

    def test_a_single_missing_day_is_a_gap(self):
        res = _run(_span("2026-07-01", "2026-07-10", skip=("2026-07-05",)))
        self.assertTrue(res["has_gaps"])
        self.assertEqual(res["day_gaps"][0]["days_missed"], 1)

    def test_a_weekend_is_not_special(self):
        """A Sunday hole counts. The track has no trading hours.

        2026-07-19 is a Sunday; the old threshold existed to excuse exactly this.
        """
        res = _run(_span("2026-07-17", "2026-07-21", skip=("2026-07-19",)))
        self.assertTrue(res["has_gaps"], "a Sunday is an ordinary day for a 24/7 track")

    def test_an_unbroken_run_reports_no_gaps(self):
        """The other direction — otherwise "always report a gap" would pass."""
        res = _run(_span("2026-07-01", "2026-07-20"))
        self.assertFalse(res["has_gaps"])
        self.assertEqual(res["day_gaps"], [])
        self.assertEqual(res["days_missed_total"], 0)
        self.assertEqual(res["days_count"], 20)

    def test_multi_day_hole_counts_every_day(self):
        res = _run(_span("2026-07-01", "2026-07-10",
                         skip=("2026-07-04", "2026-07-05", "2026-07-06")))
        self.assertEqual(res["day_gaps"][0]["days_missed"], 3)
        self.assertEqual(res["days_missed_total"], 3)

    def test_days_count_reports_what_exists_not_the_calendar(self):
        """``days_count`` must never be inflated to hide the loss."""
        res = _run(_span("2026-07-01", "2026-07-10", skip=("2026-07-05",)))
        self.assertEqual(res["days_count"], 9)
        self.assertEqual(res["days_missed_total"], 1)


class TestActionability(unittest.TestCase):
    """Old holes stay in the report; only fresh ones stay actionable."""

    def test_a_fresh_hole_is_actionable(self):
        today = date.today()
        days = [today - timedelta(days=n) for n in (5, 4, 2, 1, 0)]  # missing -3
        res = _run(sorted(days))
        self.assertTrue(res["has_gaps"])
        self.assertEqual(len(res["active_gaps"]), 1,
                         "a hole from a few days ago can still be recovered")

    def test_an_old_hole_is_reported_but_not_active(self):
        """A month-old hole is a fact of the track, not an open incident.

        It must stay visible — hiding it is how the track lost days silently in
        the first place — but a permanently unclearable alarm stops being read.
        """
        res = _run(_span("2026-07-10", "2026-08-01", skip=("2026-07-19",)))
        self.assertTrue(res["has_gaps"])
        self.assertEqual(len(res["day_gaps"]), 1, "old holes must stay in the report")
        self.assertEqual(res["active_gaps"], [], "…but not as an actionable incident")

    def test_age_boundary_is_pinned_from_both_sides(self):
        """One hole, aged deliberately — the run is otherwise unbroken to today.

        The days must stay contiguous around the hole: a sparse set would open a
        SECOND, fresh gap next to it, and the assertion would then be reading
        that one instead of the aged hole under test.
        """
        today = date.today()
        for age, expected in ((_GAP_ACTIONABLE_DAYS - 1, True),
                              (_GAP_ACTIONABLE_DAYS + 5, False)):
            with self.subTest(age=age):
                hole = today - timedelta(days=age)
                days = [today - timedelta(days=n) for n in range(age + 4, -1, -1)
                        if (today - timedelta(days=n)) != hole]
                res = _run(days)
                self.assertEqual(len(res["day_gaps"]), 1, "fixture must hold exactly one hole")
                self.assertEqual(res["day_gaps"][0]["actionable"], expected)


class TestEmptyAndDegenerate(unittest.TestCase):

    def test_no_entries_is_not_a_gap_claim(self):
        res = check_day_gaps([])
        self.assertFalse(res["has_gaps"])
        self.assertEqual(res["days_count"], 0)

    def test_single_day_has_no_interior(self):
        res = _run([date.fromisoformat("2026-07-01")])
        self.assertFalse(res["has_gaps"])
        self.assertEqual(res["days_count"], 1)

    def test_non_evidenced_bars_do_not_fill_a_hole(self):
        """Backfill must not paper over a missing day.

        The hole is missing EVIDENCE, so a reconstructed bar closing it would
        restate the go-live count on something no cycle produced.
        """
        bars = [_bar(d) for d in _span("2026-07-01", "2026-07-10", skip=("2026-07-05",))]
        bars.append({"date": "2026-07-05", "evidenced": False, "is_demo": False,
                     "source": "backfill", "snapshots": 1, "equity": 100_000.0})
        res = check_day_gaps(bars)
        self.assertTrue(res["has_gaps"], "a backfill bar must not close an evidenced gap")
        self.assertEqual(res["days_count"], 9)


if __name__ == "__main__":
    unittest.main()
