"""
tests/test_paper_day_counter.py

MP-1356 (v9.72) — 35 unit tests for PaperDayCounter.

Compatible with stdlib unittest:
    python3 -m unittest tests/test_paper_day_counter.py -v

Also compatible with pytest.

Test sections:
  1.  Instantiation                                      (3 tests)
  2.  not_started() / load_state()                       (5 tests)
  3.  days_elapsed()                                     (5 tests)
  4.  evidence_accumulated()                             (4 tests)
  5.  evidence_progress_pct()                            (4 tests)
  6.  eta_live()                                         (5 tests)
  7.  milestones_status()                                (5 tests)
  8.  render()                                           (2 tests)
  9.  to_dict()                                          (2 tests)

Total: 35 tests
"""

import json
import os
import sys
import unittest
import tempfile
from datetime import date
from pathlib import Path

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.paper_day_counter import PaperDayCounter


# ── Helpers ───────────────────────────────────────────────────────────────────

_TODAY = date(2026, 6, 20)
_START = date(2026, 6, 20)  # same day → day 1


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_counter(
    tmp: Path,
    *,
    start_date: str | None = None,
    status: str = "running",
    total_points: float | None = None,
    evidence_days: list | None = None,
    today: date = _TODAY,
) -> PaperDayCounter:
    """Create a PaperDayCounter backed by files in tmp."""
    state_path = tmp / "data" / "paper" / "paper_state.json"
    evidence_path = tmp / "data" / "paper" / "evidence_v2.json"

    if start_date is not None:
        _write(state_path, {"start_date": start_date, "day": 0, "status": status})

    if total_points is not None or evidence_days is not None:
        ev: dict = {"schema_version": "2.0"}
        if total_points is not None:
            ev["total_points"] = total_points
        if evidence_days is not None:
            ev["days"] = evidence_days
        else:
            ev["days"] = []
        _write(evidence_path, ev)

    return PaperDayCounter(
        paper_state_path=str(state_path),
        evidence_path=str(evidence_path),
        today=today,
    )


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):
    """Section 1 — Instantiation (3 tests)"""

    def test_default_instantiation(self):
        """PaperDayCounter() can be created with no arguments."""
        c = PaperDayCounter()
        self.assertIsInstance(c, PaperDayCounter)

    def test_custom_state_path(self):
        """Custom paper_state_path is stored on instance."""
        c = PaperDayCounter(paper_state_path="/tmp/paper_state.json")
        self.assertIn("paper_state.json", str(c.paper_state_path))

    def test_evidence_required_class_constant(self):
        """EVIDENCE_REQUIRED class constant equals 30.0."""
        self.assertEqual(PaperDayCounter.EVIDENCE_REQUIRED, 30.0)


class TestNotStarted(unittest.TestCase):
    """Section 2 — not_started() / load_state() (5 tests)"""

    def test_not_started_when_no_state_file(self):
        """not_started() is True when paper_state.json does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertTrue(c.not_started())

    def test_load_state_returns_none_when_missing(self):
        """load_state() returns None when paper_state.json is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertIsNone(c.load_state())

    def test_not_started_false_when_state_present(self):
        """not_started() is False when a valid paper_state.json exists."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20")
            self.assertFalse(c.not_started())

    def test_load_state_returns_dict(self):
        """load_state() returns a dict when paper_state.json is valid."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20")
            state = c.load_state()
            self.assertIsInstance(state, dict)

    def test_not_started_when_state_missing_start_date(self):
        """not_started() is True when paper_state.json has no start_date field."""
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "data" / "paper" / "paper_state.json"
            _write(state_path, {"status": "running"})
            c = PaperDayCounter(
                paper_state_path=str(state_path),
                evidence_path=str(Path(tmp) / "data" / "paper" / "ev.json"),
                today=_TODAY,
            )
            self.assertTrue(c.not_started())


class TestDaysElapsed(unittest.TestCase):
    """Section 3 — days_elapsed() (5 tests)"""

    def test_zero_when_not_started(self):
        """days_elapsed() returns 0 when not started."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertEqual(c.days_elapsed(), 0)

    def test_one_on_start_date(self):
        """days_elapsed() returns 1 on the same day as start_date."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", today=date(2026, 6, 20))
            self.assertEqual(c.days_elapsed(), 1)

    def test_ten_after_nine_days(self):
        """days_elapsed() returns 10 when 9 calendar days have passed."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(
                Path(tmp),
                start_date="2026-06-20",
                today=date(2026, 6, 29),
            )
            self.assertEqual(c.days_elapsed(), 10)

    def test_thirty_after_twenty_nine_days(self):
        """days_elapsed() returns 30 on day 30 of the paper period."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(
                Path(tmp),
                start_date="2026-06-20",
                today=date(2026, 7, 19),
            )
            self.assertEqual(c.days_elapsed(), 30)

    def test_returns_int(self):
        """days_elapsed() always returns an int."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20")
            self.assertIsInstance(c.days_elapsed(), int)


class TestEvidenceAccumulated(unittest.TestCase):
    """Section 4 — evidence_accumulated() (4 tests)"""

    def test_zero_when_no_evidence_file(self):
        """evidence_accumulated() returns 0.0 when evidence file is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertEqual(c.evidence_accumulated(), 0.0)

    def test_reads_total_points_from_evidence_file(self):
        """evidence_accumulated() reads total_points from evidence_v2.json."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=7.5)
            self.assertAlmostEqual(c.evidence_accumulated(), 7.5)

    def test_returns_float(self):
        """evidence_accumulated() returns a float."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertIsInstance(c.evidence_accumulated(), float)

    def test_zero_when_evidence_file_malformed(self):
        """evidence_accumulated() returns 0.0 when evidence file is malformed JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            ev_path = Path(tmp) / "data" / "paper" / "evidence_v2.json"
            ev_path.parent.mkdir(parents=True, exist_ok=True)
            ev_path.write_text("not valid json{{{", encoding="utf-8")
            c = PaperDayCounter(
                paper_state_path=str(Path(tmp) / "data" / "paper" / "paper_state.json"),
                evidence_path=str(ev_path),
                today=_TODAY,
            )
            self.assertEqual(c.evidence_accumulated(), 0.0)


class TestEvidenceProgressPct(unittest.TestCase):
    """Section 5 — evidence_progress_pct() (4 tests)"""

    def test_zero_when_no_evidence(self):
        """evidence_progress_pct() returns 0.0 when no evidence accumulated."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertEqual(c.evidence_progress_pct(), 0.0)

    def test_one_hundred_when_required_met(self):
        """evidence_progress_pct() returns 100.0 when 30+ pts accumulated."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=30.0)
            self.assertAlmostEqual(c.evidence_progress_pct(), 100.0)

    def test_capped_at_one_hundred(self):
        """evidence_progress_pct() is capped at 100.0 even if pts > 30."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=45.0)
            self.assertAlmostEqual(c.evidence_progress_pct(), 100.0)

    def test_proportional_at_halfway(self):
        """evidence_progress_pct() returns ~50.0 at 15 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=15.0)
            self.assertAlmostEqual(c.evidence_progress_pct(), 50.0)


class TestEtaLive(unittest.TestCase):
    """Section 6 — eta_live() (5 tests)"""

    def test_none_when_not_started(self):
        """eta_live() returns None when paper trading hasn't started."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            self.assertIsNone(c.eta_live())

    def test_returns_string_when_started(self):
        """eta_live() returns an ISO date string when started."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", today=date(2026, 6, 20))
            eta = c.eta_live()
            self.assertIsInstance(eta, str)

    def test_eta_not_in_past(self):
        """eta_live() must not return a date in the past when evidence is < 30 pts."""
        with tempfile.TemporaryDirectory() as tmp:
            today = date(2026, 6, 20)
            c = _make_counter(Path(tmp), start_date="2026-06-20", today=today)
            eta = c.eta_live()
            if eta:
                eta_date = date.fromisoformat(eta)
                self.assertGreaterEqual(eta_date, today)

    def test_eta_is_today_when_evidence_already_met(self):
        """eta_live() returns today's date when 30+ pts already accumulated."""
        with tempfile.TemporaryDirectory() as tmp:
            today = date(2026, 7, 28)
            c = _make_counter(
                Path(tmp),
                start_date="2026-06-20",
                total_points=30.0,
                today=today,
            )
            eta = c.eta_live()
            self.assertEqual(eta, today.isoformat())

    def test_eta_iso_format(self):
        """eta_live() output is a valid ISO-format date (YYYY-MM-DD)."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", today=date(2026, 6, 20))
            eta = c.eta_live()
            if eta is not None:
                parsed = date.fromisoformat(eta)
                self.assertIsInstance(parsed, date)


class TestMilestonesStatus(unittest.TestCase):
    """Section 7 — milestones_status() (5 tests)"""

    def test_returns_six_milestones(self):
        """milestones_status() returns exactly 6 entries."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            milestones = c.milestones_status()
            self.assertEqual(len(milestones), 6)

    def test_milestone_keys(self):
        """Each milestone dict has required keys: pts, label, achieved, eta_date."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            for m in c.milestones_status():
                self.assertIn("pts", m)
                self.assertIn("label", m)
                self.assertIn("achieved", m)
                self.assertIn("eta_date", m)

    def test_none_achieved_when_zero_pts(self):
        """No milestones are achieved when evidence_accumulated = 0."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            for m in c.milestones_status():
                self.assertFalse(m["achieved"])

    def test_first_milestone_achieved_at_5pts(self):
        """First milestone (5.0 pts) is achieved when accumulated >= 5.0."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=5.0)
            ms = c.milestones_status()
            self.assertTrue(ms[0]["achieved"])
            self.assertFalse(ms[1]["achieved"])

    def test_all_achieved_at_30pts(self):
        """All milestones are achieved when accumulated >= 30.0."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20", total_points=30.0)
            for m in c.milestones_status():
                self.assertTrue(m["achieved"])


class TestRender(unittest.TestCase):
    """Section 8 — render() (2 tests)"""

    def test_render_contains_evidence_when_started(self):
        """render() output contains 'Evidence' when paper trading is running."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20")
            output = c.render()
            self.assertIn("Evidence", output)

    def test_render_contains_points_when_started(self):
        """render() output contains 'pts' (points) when paper trading is running."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp), start_date="2026-06-20")
            output = c.render()
            self.assertIn("pts", output)


class TestToDict(unittest.TestCase):
    """Section 9 — to_dict() (2 tests)"""

    def test_contains_days_elapsed_key(self):
        """to_dict() result contains 'days_elapsed' key."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            d = c.to_dict()
            self.assertIn("days_elapsed", d)

    def test_contains_evidence_accumulated_key(self):
        """to_dict() result contains 'evidence_accumulated' key."""
        with tempfile.TemporaryDirectory() as tmp:
            c = _make_counter(Path(tmp))
            d = c.to_dict()
            self.assertIn("evidence_accumulated", d)


if __name__ == "__main__":
    unittest.main()
