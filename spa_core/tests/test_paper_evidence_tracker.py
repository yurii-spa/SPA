"""MP-416: regression tests for the daily paper-trading EVIDENCE record.

Two surfaces, both previously untested on origin:

1. ``spa_core.paper_trading.cycle_reporting._honest_apy_pct`` /
   ``_record_paper_evidence`` — the live daily-cycle writer of the git-tracked
   evidence artefact ``data/paper_evidence.json``.

   **The bug these tests pin (found 2026-07-29, autonomous cycle #30).** The
   call site used to read::

       _et_apy = (result.apy_today_pct
                  if isinstance(result.apy_today_pct, (int, float))
                  and result.apy_today_pct > 0
                  else 10.115)

   ``10.115`` is ``s7_pendle_yt_aggressive.WEIGHTED_APY`` — a **backtest**
   scenario number. So any day whose real APY was ``0.0`` (100 %-cash), negative
   (a real loss) or unavailable was written into the evidence file as
   ``apy_pct: 10.115``. Confirmed on live data: 2026-07-28 and 2026-07-29 (the
   forced all-cash days after the RTMR incident, real APY 0.00 %) are recorded
   at 10.115 %. That is a modelled number published as live evidence —
   invariant #8 — and a fabrication where the system must refuse — invariant #2.

   The contract now: a finite real measurement is recorded VERBATIM (including
   an honest ``0.0`` and negatives); anything unknown (``None``, missing field,
   ``bool``, ``NaN``/``inf``, str) is REFUSED — the day is simply not recorded,
   and no substitute number is invented.

2. ``spa_core.paper_trading.paper_evidence_tracker.PaperEvidenceTracker`` — the
   accumulator itself (0 dedicated tests on origin). Its day set feeds the
   published evidence-day count (``alerts/daily_evidence_report``,
   ``analytics/golive_readiness_report``), so silent breakage here is an
   honesty defect, not just a crash.

Hermetic: every path is under ``tmp_path``/``TemporaryDirectory``. The live
``data/`` tree — including the go-live track — is never read or written.

Run::

    python3 -m unittest discover -s spa_core/tests -p "test_paper_evidence_tracker.py" -v
"""
from __future__ import annotations

import inspect
import json
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from spa_core.paper_trading import cycle_reporting
from spa_core.paper_trading.cycle_reporting import (
    _honest_apy_pct,
    _record_paper_evidence,
)
from spa_core.paper_trading import paper_evidence_tracker as pet_mod
from spa_core.paper_trading.paper_evidence_tracker import (
    BASE_CAPITAL,
    MIN_APY_PCT,
    MIN_DAYS_REQUIRED,
    MIN_SHARPE,
    MIN_SHARPE_DAYS,
    PaperEvidenceTracker,
)

# The backtest literal that must never again be written into live evidence.
_BACKTEST_APY_LITERAL = 10.115


def _result(apy, equity: float = 100_000.0) -> SimpleNamespace:
    """Minimal stand-in for ``CycleResult`` (only the two fields used)."""
    return SimpleNamespace(apy_today_pct=apy, current_equity=equity)


def _days(path: Path) -> list:
    return json.loads(path.read_text())["days"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. _honest_apy_pct — the honest/unknown decision
# ─────────────────────────────────────────────────────────────────────────────


class TestEvidenceApyPct(unittest.TestCase):
    """Truth table of the record-or-refuse decision."""

    def test_positive_apy_recorded_verbatim(self):
        self.assertEqual(_honest_apy_pct(3.9431), 3.9431)

    def test_zero_apy_is_a_real_measurement_not_unknown(self):
        """A 100 %-cash portfolio really does earn 0 % — record it, don't refuse.

        This is the exact live case (2026-07-28/29) that used to be rewritten
        into the 10.115 % backtest number.
        """
        self.assertEqual(_honest_apy_pct(0.0), 0.0)
        self.assertEqual(_honest_apy_pct(0), 0.0)

    def test_negative_apy_recorded_verbatim(self):
        """A losing day must be published as a loss, never flipped positive."""
        self.assertEqual(_honest_apy_pct(-2.5), -2.5)

    def test_int_is_coerced_to_float(self):
        value = _honest_apy_pct(4)
        self.assertIsInstance(value, float)
        self.assertEqual(value, 4.0)

    def test_none_is_unknown(self):
        self.assertIsNone(_honest_apy_pct(None))

    def test_string_is_unknown(self):
        self.assertIsNone(_honest_apy_pct("3.94"))

    def test_bool_is_unknown_not_one_percent(self):
        """``isinstance(True, int)`` is True — bool must not become apy=1.0."""
        self.assertIsNone(_honest_apy_pct(True))
        self.assertIsNone(_honest_apy_pct(False))

    def test_nan_and_inf_are_unknown(self):
        """NaN/inf are finite-looking floats that would also break JSON."""
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                self.assertIsNone(_honest_apy_pct(bad))


# ─────────────────────────────────────────────────────────────────────────────
# 2. _record_paper_evidence — end-to-end against a tmp data dir
# ─────────────────────────────────────────────────────────────────────────────


class TestRecordPaperEvidence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ddir = Path(self._tmp.name)
        self.evidence = self.ddir / "paper_evidence.json"
        self.now = _FakeNow(date(2026, 7, 29))

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, apy, equity: float = 100_628.61):
        _record_paper_evidence(
            ddir=self.ddir,
            result=_result(apy, equity),
            now_dt=self.now,
            today="2026-07-29",
        )

    def test_zero_apy_day_is_recorded_as_zero_not_as_backtest_number(self):
        """RED before the fix: this file used to contain apy_pct == 10.115."""
        self._run(0.0)
        entries = _days(self.evidence)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["apy_pct"], 0.0)
        self.assertNotEqual(entries[0]["apy_pct"], _BACKTEST_APY_LITERAL)

    def test_negative_apy_day_is_recorded_as_a_loss(self):
        """RED before the fix: a −2.5 % day was published as +10.115 %."""
        self._run(-2.5)
        self.assertEqual(_days(self.evidence)[0]["apy_pct"], -2.5)

    def test_positive_apy_day_unchanged_by_the_fix(self):
        self._run(3.9431)
        self.assertEqual(_days(self.evidence)[0]["apy_pct"], 3.9431)

    def test_unknown_apy_writes_nothing_at_all(self):
        """Refusal is a gap, not a guess — the file is not even created."""
        self._run(None)
        self.assertFalse(self.evidence.exists())

    def test_unknown_apy_leaves_existing_evidence_untouched(self):
        self._run(3.9431)
        before = self.evidence.read_bytes()
        self._run(None)
        self.assertEqual(self.evidence.read_bytes(), before)

    def test_missing_field_is_unknown_not_fabricated(self):
        _record_paper_evidence(
            ddir=self.ddir,
            result=SimpleNamespace(current_equity=100_000.0),  # no apy_today_pct
            now_dt=self.now,
            today="2026-07-29",
        )
        self.assertFalse(self.evidence.exists())

    def test_nan_apy_writes_nothing(self):
        """NaN would also serialise as invalid JSON — refuse before writing."""
        self._run(float("nan"))
        self.assertFalse(self.evidence.exists())

    def test_refusal_is_logged_with_the_raw_value(self):
        with self.assertLogs("spa.cycle_runner", level="WARNING") as captured:
            self._run(None)
        joined = "\n".join(captured.output)
        self.assertIn("NOT recorded", joined)
        self.assertIn("2026-07-29", joined)

    def test_never_raises_on_a_broken_result(self):
        """Evidence tracking must never crash the cycle (fail-safe contract)."""
        broken = SimpleNamespace(apy_today_pct=3.0)  # no current_equity
        with self.assertLogs("spa.cycle_runner", level="WARNING"):
            _record_paper_evidence(
                ddir=self.ddir, result=broken, now_dt=self.now, today="2026-07-29"
            )

    def test_never_raises_when_the_data_dir_is_unwritable(self):
        blocked = self.ddir / "nope.json"
        blocked.write_text("{}")  # a FILE where a directory is expected
        with self.assertLogs("spa.cycle_runner", level="WARNING"):
            _record_paper_evidence(
                ddir=blocked,
                result=_result(3.0),
                now_dt=self.now,
                today="2026-07-29",
            )

    def test_no_tmp_file_left_behind(self):
        self._run(0.0)
        self.assertEqual(list(self.ddir.glob("*.tmp")), [])

    def test_entry_carries_the_cycle_provenance(self):
        self._run(0.0)
        entry = _days(self.evidence)[0]
        self.assertEqual(entry["date"], "2026-07-29")
        self.assertEqual(entry["strategy_id"], "S7")
        self.assertIn("auto-recorded", entry["notes"])

    def test_source_has_no_backtest_apy_fallback(self):
        """Static guard: nobody re-introduces a modelled default APY here.

        Pins the *class* of defect, not just this literal — the evidence writer
        must contain no numeric fallback for an unavailable APY.
        """
        src = inspect.getsource(cycle_reporting._record_paper_evidence)
        self.assertNotIn("10.115", src)
        self.assertNotRegex(src, r"else\s+\d+\.\d+")


class _FakeNow:
    """Stand-in for the cycle's ``datetime`` (only ``.date()`` is used)."""

    def __init__(self, day: date):
        self._day = day

    def date(self) -> date:
        return self._day


# ─────────────────────────────────────────────────────────────────────────────
# 2b. _record_apy_milestone — the SECOND copy of the same fabrication
# ─────────────────────────────────────────────────────────────────────────────


class TestRecordApyMilestone(unittest.TestCase):
    """MP-512 wrote the same ``else 10.115`` into ``data/apy_milestone_log.json``.

    Worse blast radius than the evidence file: 10.115 ≥ the 10 % "Target mid"
    rung, so a forced all-cash day used to *trip a milestone the portfolio never
    reached*, and that log feeds the owner's weekly evidence report.

    ``ApyMilestoneTracker`` defaults to the REPO-ROOT ``data/`` directory, so it
    is mocked here — these tests must never write to the live log.
    """

    def _run(self, apy, strategy=None):
        recorded = []

        class _FakeTracker:
            def __init__(self, *a, **kw):
                pass

            def record_day(self, date_iso, apy_pct, strategy_id="tournament_winner"):
                recorded.append((date_iso, apy_pct, strategy_id))
                return {}

        result = SimpleNamespace(apy_today_pct=apy)
        if strategy is not None:
            result.best_strategy_id = strategy
        with patch(
            "spa_core.analytics.apy_milestone_tracker.ApyMilestoneTracker",
            _FakeTracker,
        ):
            cycle_reporting._record_apy_milestone(result=result, today="2026-07-29")
        return recorded

    def test_zero_apy_is_logged_as_zero_not_as_a_milestone_beat(self):
        """RED before the fix: an all-cash day logged 10.115 % → tripped level 3."""
        self.assertEqual(self._run(0.0), [("2026-07-29", 0.0, "s7_pendle_yt")])

    def test_negative_apy_is_logged_as_a_loss(self):
        self.assertEqual(self._run(-1.25)[0][1], -1.25)

    def test_positive_apy_unchanged_by_the_fix(self):
        self.assertEqual(self._run(7.7064)[0][1], 7.7064)

    def test_unknown_apy_records_nothing(self):
        self.assertEqual(self._run(None), [])

    def test_nan_apy_records_nothing(self):
        self.assertEqual(self._run(float("nan")), [])

    def test_refusal_never_constructs_the_tracker(self):
        """The live-rooted tracker must not even be instantiated on a refusal."""
        result = SimpleNamespace(apy_today_pct=None)
        with patch(
            "spa_core.analytics.apy_milestone_tracker.ApyMilestoneTracker"
        ) as klass:
            with self.assertLogs("spa.cycle_runner", level="WARNING"):
                cycle_reporting._record_apy_milestone(result=result, today="2026-07-29")
        klass.assert_not_called()

    def test_strategy_id_is_used_when_present(self):
        self.assertEqual(self._run(5.0, strategy="S11")[0][2], "S11")

    def test_strategy_id_falls_back_when_absent_or_empty(self):
        self.assertEqual(self._run(5.0)[0][2], "s7_pendle_yt")
        self.assertEqual(self._run(5.0, strategy="")[0][2], "s7_pendle_yt")

    def test_never_raises_when_the_tracker_blows_up(self):
        def _boom(*a, **kw):
            raise RuntimeError("disk on fire")

        with patch(
            "spa_core.analytics.apy_milestone_tracker.ApyMilestoneTracker", _boom
        ):
            with self.assertLogs("spa.cycle_runner", level="WARNING"):
                cycle_reporting._record_apy_milestone(
                    result=SimpleNamespace(apy_today_pct=5.0), today="2026-07-29"
                )

    def test_source_has_no_backtest_apy_fallback(self):
        src = inspect.getsource(cycle_reporting._record_apy_milestone)
        self.assertNotIn("10.115", src)
        self.assertNotRegex(src, r"else\s+\d+\.\d+")


class TestNoFabricatedApyAnywhereInTheCycleTail(unittest.TestCase):
    """Repo-level guard for the whole defect class, not just the two call sites."""

    def test_cycle_reporting_contains_no_backtest_apy_literal(self):
        src = Path(cycle_reporting.__file__).read_text()
        self.assertNotIn("10.115", src)


# ─────────────────────────────────────────────────────────────────────────────
# 3. PaperEvidenceTracker — the accumulator (0 tests on origin)
# ─────────────────────────────────────────────────────────────────────────────


class _TrackerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.path = self.tmp / "paper_evidence.json"

    def tearDown(self):
        self._tmp.cleanup()

    def tracker(self) -> PaperEvidenceTracker:
        return PaperEvidenceTracker(str(self.path))

    def fill(self, tracker, equities, start=date(2026, 6, 12), apy=4.0):
        for i, eq in enumerate(equities):
            tracker.record_day(start + timedelta(days=i), apy, eq)


class TestTrackerRecording(_TrackerCase):
    def test_first_day_return_is_measured_against_base_capital(self):
        t = self.tracker()
        entry = t.record_day(date(2026, 6, 12), 4.0, BASE_CAPITAL * 1.01)
        self.assertAlmostEqual(entry["day_return_pct"], 1.0, places=6)

    def test_second_day_return_is_measured_against_the_previous_day(self):
        t = self.tracker()
        t.record_day(date(2026, 6, 12), 4.0, 100_000.0)
        entry = t.record_day(date(2026, 6, 13), 4.0, 101_000.0)
        self.assertAlmostEqual(entry["day_return_pct"], 1.0, places=6)

    def test_duplicate_date_is_idempotent_and_does_not_double_count(self):
        t = self.tracker()
        first = t.record_day(date(2026, 6, 12), 4.0, 100_100.0)
        again = t.record_day(date(2026, 6, 12), 99.0, 200_000.0)
        self.assertEqual(again, first)
        self.assertEqual(t.get_days_elapsed(), 1)
        self.assertEqual(t.get_strategy_stats()["S7"]["day_count"], 1)

    def test_zero_apy_is_storable(self):
        """The honest all-cash day must survive the round-trip as 0.0."""
        t = self.tracker()
        t.record_day(date(2026, 7, 29), 0.0, 100_628.61)
        self.assertEqual(_days(self.path)[0]["apy_pct"], 0.0)

    def test_record_persists_immediately(self):
        self.tracker().record_day(date(2026, 6, 12), 4.0, 100_000.0)
        self.assertEqual(len(_days(self.path)), 1)

    def test_state_survives_a_reload(self):
        self.tracker().record_day(date(2026, 6, 12), 4.0, 100_500.0)
        reloaded = self.tracker()
        self.assertEqual(reloaded.get_days_elapsed(), 1)
        self.assertEqual(reloaded.get_latest_equity(), 100_500.0)

    def test_per_strategy_stats_accumulate(self):
        t = self.tracker()
        t.record_day(date(2026, 6, 12), 4.0, 100_000.0, strategy_id="A")
        t.record_day(date(2026, 6, 13), 6.0, 100_100.0, strategy_id="A")
        t.record_day(date(2026, 6, 14), 5.0, 100_200.0, strategy_id="B")
        stats = t.get_strategy_stats()
        self.assertEqual(stats["A"]["day_count"], 2)
        self.assertAlmostEqual(stats["A"]["total_apy"], 10.0)
        self.assertEqual(stats["A"]["first_date"], "2026-06-12")
        self.assertEqual(stats["A"]["last_date"], "2026-06-13")
        self.assertEqual(stats["B"]["day_count"], 1)

    def test_missing_file_starts_from_an_empty_state(self):
        t = self.tracker()
        self.assertEqual(t.get_days_elapsed(), 0)
        self.assertEqual(t.get_latest_equity(), BASE_CAPITAL)

    def test_corrupt_file_does_not_crash_the_tracker(self):
        self.path.write_text("{ not json")
        self.assertEqual(self.tracker().get_days_elapsed(), 0)

    def test_days_list_is_a_copy(self):
        t = self.tracker()
        t.record_day(date(2026, 6, 12), 4.0, 100_000.0)
        t.get_days_list().clear()
        self.assertEqual(t.get_days_elapsed(), 1)


class TestTrackerMetrics(_TrackerCase):
    def test_avg_apy_over_recorded_days(self):
        t = self.tracker()
        for i, apy in enumerate((3.0, 5.0, 7.0)):
            t.record_day(date(2026, 6, 12) + timedelta(days=i), apy, 100_000.0)
        self.assertAlmostEqual(t.get_avg_apy(), 5.0)

    def test_avg_apy_of_empty_track_is_zero(self):
        self.assertEqual(self.tracker().get_avg_apy(), 0.0)

    def test_max_drawdown_is_peak_to_trough(self):
        t = self.tracker()
        self.fill(t, [100_000.0, 110_000.0, 99_000.0])
        self.assertAlmostEqual(t.get_max_drawdown(), -10.0, places=6)

    def test_max_drawdown_of_a_monotonic_curve_is_zero(self):
        t = self.tracker()
        self.fill(t, [100_000.0, 100_100.0, 100_200.0])
        self.assertEqual(t.get_max_drawdown(), 0.0)

    def test_max_drawdown_peak_starts_at_base_capital(self):
        """A track that only ever loses is still measured against the seed."""
        t = self.tracker()
        self.fill(t, [95_000.0])
        self.assertAlmostEqual(t.get_max_drawdown(), -5.0, places=6)

    def test_max_drawdown_of_empty_track_is_zero(self):
        self.assertEqual(self.tracker().get_max_drawdown(), 0.0)

    def test_sharpe_needs_at_least_two_days(self):
        t = self.tracker()
        self.assertEqual(t.get_sharpe_ratio(), 0.0)
        t.record_day(date(2026, 6, 12), 4.0, 100_100.0)
        self.assertEqual(t.get_sharpe_ratio(), 0.0)

    def test_sharpe_of_a_flat_track_is_zero_not_infinite(self):
        """Zero variance must not divide by zero (all-cash days do exactly this)."""
        t = self.tracker()
        self.fill(t, [100_000.0, 100_000.0, 100_000.0])
        self.assertEqual(t.get_sharpe_ratio(), 0.0)

    def test_sharpe_is_positive_for_a_steadily_growing_track(self):
        t = self.tracker()
        self.fill(t, [100_100.0, 100_180.0, 100_290.0, 100_360.0])
        self.assertGreater(t.get_sharpe_ratio(), 0.0)

    def test_total_return_is_relative_to_base_capital(self):
        t = self.tracker()
        self.fill(t, [101_000.0])
        self.assertAlmostEqual(t.get_total_return_pct(), 1.0, places=6)

    def test_total_return_of_empty_track_is_zero(self):
        self.assertEqual(self.tracker().get_total_return_pct(), 0.0)


class TestTrackerGoliveStatus(_TrackerCase):
    def test_empty_track_is_not_ready(self):
        """No data ⇒ never ready, and ``min_days`` is always among the blockers.

        (An empty track trivially *passes* ``max_drawdown`` — 0.0 ≥ −5 % — but
        that can never produce a false READY, because ``min_days`` and
        ``avg_apy`` both block. Pinned so the day-count gate stays load-bearing.)
        """
        status = self.tracker().get_golive_status()
        self.assertFalse(status["ready_for_golive"])
        self.assertEqual(status["days_elapsed"], 0)
        self.assertEqual(status["days_remaining"], MIN_DAYS_REQUIRED)
        self.assertIn("min_days", status["blockers"])
        self.assertIn("avg_apy", status["blockers"])

    def test_days_remaining_never_goes_negative(self):
        t = self.tracker()
        self.fill(t, [100_000.0 + i for i in range(MIN_DAYS_REQUIRED + 5)])
        self.assertEqual(t.get_golive_status()["days_remaining"], 0)

    def test_sharpe_check_fails_below_the_minimum_day_count(self):
        """Even a great Sharpe must not pass before the window is long enough."""
        t = self.tracker()
        self.fill(t, [100_000.0 + 100 * (i + 1) for i in range(3)])
        checks = t.get_golive_status()["checks"]
        self.assertLess(3, MIN_SHARPE_DAYS)
        self.assertFalse(checks["sharpe"]["pass"])

    def test_apy_check_is_a_floor(self):
        t = self.tracker()
        self.fill(t, [100_000.0], apy=MIN_APY_PCT - 0.01)
        self.assertFalse(t.get_golive_status()["checks"]["avg_apy"]["pass"])
        t2 = PaperEvidenceTracker(str(self.tmp / "b.json"))
        t2.record_day(date(2026, 6, 12), MIN_APY_PCT, 100_000.0)
        self.assertTrue(t2.get_golive_status()["checks"]["avg_apy"]["pass"])

    def test_drawdown_check_fails_past_the_kill_switch_threshold(self):
        t = self.tracker()
        self.fill(t, [100_000.0, 94_000.0])  # −6 %
        self.assertFalse(t.get_golive_status()["checks"]["max_drawdown"]["pass"])

    def test_counts_and_blockers_agree(self):
        t = self.tracker()
        self.fill(t, [100_000.0])
        status = t.get_golive_status()
        passed = sum(1 for c in status["checks"].values() if c["pass"])
        self.assertEqual(status["checks_passed"], passed)
        self.assertEqual(
            len(status["blockers"]), status["checks_total"] - status["checks_passed"]
        )

    def test_required_constants_are_reported_verbatim(self):
        checks = self.tracker().get_golive_status()["checks"]
        self.assertEqual(checks["min_days"]["required"], MIN_DAYS_REQUIRED)
        self.assertEqual(checks["avg_apy"]["required"], MIN_APY_PCT)
        self.assertEqual(checks["sharpe"]["required"], MIN_SHARPE)


class TestGoliveTargetSourceOfTruth(_TrackerCase):
    """The target date must track the go-live checker, never drift from it."""

    def test_target_comes_from_golive_status_file(self):
        gl = self.tmp / "golive_status.json"
        gl.write_text(json.dumps({"target_date": "2026-08-15"}))
        with patch.object(pet_mod, "GOLIVE_STATUS_FILE", str(gl)):
            self.assertEqual(pet_mod._golive_target_iso(), "2026-08-15")

    def test_missing_file_falls_back_to_the_committed_literal(self):
        with patch.object(pet_mod, "GOLIVE_STATUS_FILE", str(self.tmp / "gone.json")):
            self.assertEqual(
                pet_mod._golive_target_iso(), pet_mod.GOLIVE_TARGET_DATE.isoformat()
            )

    def test_corrupt_file_falls_back_instead_of_raising(self):
        gl = self.tmp / "golive_status.json"
        gl.write_text("{ broken")
        with patch.object(pet_mod, "GOLIVE_STATUS_FILE", str(gl)):
            self.assertEqual(
                pet_mod._golive_target_iso(), pet_mod.GOLIVE_TARGET_DATE.isoformat()
            )

    def test_unparseable_target_does_not_crash_the_status(self):
        gl = self.tmp / "golive_status.json"
        gl.write_text(json.dumps({"target_date": "not-a-date"}))
        with patch.object(pet_mod, "GOLIVE_STATUS_FILE", str(gl)):
            status = self.tracker().get_golive_status()
        self.assertEqual(status["golive_target"], pet_mod.GOLIVE_TARGET_DATE.isoformat())
        self.assertRegex(status["golive_target"], r"^\d{4}-\d{2}-\d{2}$")


class TestTrackerExport(_TrackerCase):
    def test_export_writes_the_status_and_returns_it(self):
        t = self.tracker()
        t.record_day(date(2026, 6, 12), 4.0, 100_100.0)
        out = self.tmp / "summary.json"
        status = t.export_summary(str(out))
        self.assertEqual(json.loads(out.read_text()), status)

    def test_export_creates_missing_parent_directories(self):
        out = self.tmp / "nested" / "deep" / "summary.json"
        self.tracker().export_summary(str(out))
        self.assertTrue(out.exists())

    def test_export_leaves_no_tmp_files(self):
        out = self.tmp / "summary.json"
        self.tracker().export_summary(str(out))
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_export_is_valid_json_even_for_an_empty_track(self):
        out = self.tmp / "summary.json"
        self.tracker().export_summary(str(out))
        doc = json.loads(out.read_text())
        self.assertFalse(doc["ready_for_golive"])
        self.assertEqual(doc["days_elapsed"], 0)


class TestNoLiveDataTouched(unittest.TestCase):
    """Guard: this test module must never name the live track/evidence paths."""

    def test_module_source_uses_no_live_data_paths(self):
        src = Path(__file__).read_text()
        body = "\n".join(
            line for line in src.splitlines() if not line.lstrip().startswith("#")
        )
        # Only inside docstrings/prose may 'data/' appear; no code path builds one.
        self.assertIsNone(
            re.search(r"""(?<!['"])Path\(\s*['"]data/""", body),
            "test must not open live data/ files",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
