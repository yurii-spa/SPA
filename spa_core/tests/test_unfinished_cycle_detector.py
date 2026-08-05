"""A cycle that starts and never finishes must say so the same day.

Both holes in the paper track look identical in the audit trail: a
``cycle_start`` and then nothing — no ``allocation_proposal``, no
``risk_verdict``. Across the whole history there are 256 starts against 254
proposals, and the difference is exactly those two days. The cycle died between
starting and allocating, twice.

Nobody saw it. There was no consumer of ``cycle_start`` anywhere in monitoring,
so an unfinished cycle left one line in a log file and silence. The loss only
surfaced the next day, once the bar failed to appear — by which point the day
was gone. This check moves the signal to the same day, while the run's logs are
still around and recovery is still possible.

Both directions are pinned. A detector that only fires would flag all 46 healthy
cycles in the real trail; one that never fires would have passed for the whole
period the track was losing days.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.paper_trading.gap_monitor import check_unfinished_cycles
from spa_core.tests._freshness import now_utc


# The temp dirs are held here for the life of the module: a TemporaryDirectory
# that goes out of scope deletes the file the test is about to read, and a Path
# cannot carry the handle itself (PosixPath has no __dict__).
_KEEPALIVE: list = []


def _trail(events: list) -> Path:
    """Write an audit trail and return its path."""
    tmp = TemporaryDirectory()
    _KEEPALIVE.append(tmp)
    path = Path(tmp.name) / "audit_trail.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return path


def tearDownModule():
    for tmp in _KEEPALIVE:
        tmp.cleanup()
    _KEEPALIVE.clear()


def _ev(kind: str, when) -> dict:
    return {"event_type": kind, "timestamp": when.isoformat(),
            "data": {"cycle_date": when.date().isoformat()}}


class TestDetection(unittest.TestCase):

    def test_the_real_incident_shape_is_caught(self):
        """cycle_start alone, long past the cycle window — the 07-19 shape."""
        now = now_utc()
        dead = now - timedelta(hours=30)
        path = _trail([_ev("cycle_start", dead)])
        res = check_unfinished_cycles(audit_path=path, now=now)
        self.assertTrue(res["checked"])
        self.assertEqual(len(res["unfinished"]), 1)
        self.assertEqual(res["unfinished"][0]["date"], dead.date().isoformat())

    def test_a_complete_cycle_is_not_flagged(self):
        """The direction that keeps it usable — 46 healthy cycles must stay quiet."""
        now = now_utc()
        done = now - timedelta(hours=30)
        path = _trail([
            _ev("cycle_start", done),
            _ev("allocation_proposal", done + timedelta(minutes=2)),
            _ev("risk_verdict", done + timedelta(minutes=3)),
        ])
        self.assertEqual(check_unfinished_cycles(audit_path=path, now=now)["unfinished"], [])

    def test_a_cycle_that_reached_allocation_counts_as_finished(self):
        """Reaching allocation proves the run got past the fatal stretch."""
        now = now_utc()
        done = now - timedelta(hours=30)
        path = _trail([_ev("cycle_start", done),
                       _ev("allocation_proposal", done + timedelta(minutes=2))])
        self.assertEqual(check_unfinished_cycles(audit_path=path, now=now)["unfinished"], [])

    def test_a_cycle_still_within_its_window_is_not_flagged(self):
        """"Still running" must never read as "died" — a false alarm here is worse.

        The signal exists to prompt a recovery run; firing it on a live cycle
        would invite exactly the concurrent run it is meant to prevent.
        """
        now = now_utc()
        path = _trail([_ev("cycle_start", now - timedelta(minutes=20))])
        self.assertEqual(check_unfinished_cycles(audit_path=path, now=now)["unfinished"], [])

    def test_the_window_is_pinned_from_both_sides(self):
        now = now_utc()
        for hours, expected in ((1.0, 0), (9.0, 1)):
            with self.subTest(hours=hours):
                path = _trail([_ev("cycle_start", now - timedelta(hours=hours))])
                res = check_unfinished_cycles(audit_path=path, now=now, max_cycle_hours=6.0)
                self.assertEqual(len(res["unfinished"]), expected)

    def test_recoverability_ages_out(self):
        """Fresh loss = act on it. Month-old loss = a fact of the track."""
        now = now_utc()
        fresh = check_unfinished_cycles(
            audit_path=_trail([_ev("cycle_start", now - timedelta(hours=12))]), now=now)
        old = check_unfinished_cycles(
            audit_path=_trail([_ev("cycle_start", now - timedelta(days=30))]), now=now)
        self.assertTrue(fresh["unfinished"][0]["recoverable"])
        self.assertFalse(old["unfinished"][0]["recoverable"])


class TestHonestFailure(unittest.TestCase):
    """The monitor must distinguish "checked and clean" from "did not look"."""

    def test_missing_trail_reports_unchecked_not_clean(self):
        res = check_unfinished_cycles(audit_path=Path("/nonexistent/audit.jsonl"))
        self.assertFalse(res["checked"], "an absent trail is not evidence of health")
        self.assertEqual(res["unfinished"], [])

    def test_a_corrupt_line_does_not_abort_the_check(self):
        """One bad line must not blind the check to the rest of the file."""
        now = now_utc()
        dead = now - timedelta(hours=30)
        tmp = TemporaryDirectory()
        path = Path(tmp.name) / "audit_trail.jsonl"
        path.write_text("{not json\n" + json.dumps(_ev("cycle_start", dead)) + "\n",
                        encoding="utf-8")
        res = check_unfinished_cycles(audit_path=path, now=now)
        self.assertTrue(res["checked"])
        self.assertEqual(len(res["unfinished"]), 1)
        tmp.cleanup()

    def test_empty_trail_is_checked_and_clean(self):
        res = check_unfinished_cycles(audit_path=_trail([]))
        self.assertTrue(res["checked"])
        self.assertEqual(res["unfinished"], [])
        self.assertEqual(res["cycles_seen"], 0)

    def test_events_without_timestamps_are_skipped_not_fatal(self):
        now = now_utc()
        dead = now - timedelta(hours=30)
        path = _trail([{"event_type": "cycle_start"},
                       _ev("cycle_start", dead)])
        res = check_unfinished_cycles(audit_path=path, now=now)
        self.assertEqual(len(res["unfinished"]), 1)


if __name__ == "__main__":
    unittest.main()
