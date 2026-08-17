#!/usr/bin/env python3
"""A book without a REAL DAILY MARK must be named before anyone measures a cross-section on it.

THE MEASURED DEFECT (card ``agent-idea17-needs-a-panel-with-daily-marks``, cycle #87). Registry
idea #17 asks whether cross-sectional diversification across the ten aggressive books lowers risk.
On the 852-day panel six of the ten books were flat on most days — ``lp_eth_stable`` on 851 of 852
— so the numbers the verdict rested on were arithmetic over constants:

  • maxDD 0.00% and Calmar inf came from books that do not move, not from portfolio quality;
  • mean pairwise correlation 0.072 was largely an artifact (two constant series correlate with
    nothing);
  • equal-weight OOS +6.66% APY looked like an edge while 6 of its 10 legs were near-constants.

The verdict was correctly downgraded to "not proven and not disproven" — and the panel had no way
to say WHICH books it may honestly be computed over. ``killed`` / ``flatline_reason`` (ADR-091 §3)
cannot answer it: both of the real failures are books that are ALIVE. One is a near-constant that
was never killed; the other (``points_farm``) moves EVERY day with ``mtm_source`` null on 100% of
its points — it looks livelier than anything on the panel and its movement comes from nowhere
nameable.

POSITIVE CONTROL. Each of the four failure books below is one of the measured shapes, and each test
asserts the census reports the *reason* rather than a bare pass/fail. ``test_positive_control_...``
reproduces the original accident end to end: a panel of constants that the liveness layer calls
100% alive, and which the census refuses to call cross-section eligible.

Time is an INPUT (``now_iso`` injected); no wall clock is read at module level. No network, no live
data dir — every fixture is written into a fresh tmp dir.

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_daily_mark_census.py -q
"""
# FROZEN-DATE-OK: injected-clock — every fixture date is derived from the single anchor
# datetime.date(2026, 1, 1) via _day(), and the only wall-clock field of the artefact under test
# (scorecard.generated_at) is injected as now_iso=NOW. Both sides are pinned to the same frozen
# anchor, so no assertion here can change when the calendar moves.
from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import loader as ld
from spa_core.strategy_lab.aggressive_lab import scorecard as sc

NOW = "2026-06-30T00:00:00+00:00"
N_DAYS = 40
SOURCE = "realized_backtest_series"


def _day(n: int) -> str:
    return (datetime.date(2026, 1, 1) + datetime.timedelta(days=n)).isoformat()


def _write(root: Path, sid: str, points) -> None:
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / ld.REALIZED_SERIES_NAME).write_text(
        "\n".join(json.dumps(p, sort_keys=True) for p in points) + "\n", encoding="utf-8")


def _pt(i, equity, *, source=SOURCE, killed=False, phase="backtest"):
    return {"date": _day(i), "equity_usd": equity, "phase": phase,
            "killed": killed, "mtm_source": source}


# ── the four measured shapes, as series builders ────────────────────────────────────────────────
def _daily_marked(n=N_DAYS):
    """Repriced every day, every point names its source. The honest shape."""
    eq, out = 100_000.0, []
    for i in range(n):
        eq *= 1.0 + (0.004 if i % 2 else -0.003)
        out.append(_pt(i, round(eq, 4)))
    return out


def _frozen(n=N_DAYS):
    """``lp_eth_stable``: moved on 1 of 39 day-steps (2.6% < 5%), alive the whole time."""
    out = [_pt(0, 100_000.0)]
    out.append(_pt(1, 100_500.0))
    out.extend(_pt(i, 100_500.0) for i in range(2, n))
    return out


def _unsourced_drift(n=N_DAYS):
    """``points_farm``: moves EVERY day, ``mtm_source`` null on every point. Alive, and livelier
    than anything else on the panel."""
    eq, out = 100_000.0, []
    for i in range(n):
        eq *= 1.00016  # the deterministic drift that produced annVol 0.00% with a 6.18% APY
        out.append(_pt(i, round(eq, 4), source=None))
    return out


def _sparse_mark(n=N_DAYS):
    """``lrt_neutral``: a real, sourced, but intermittent mark — repriced on ~10% of day-steps."""
    eq, out = 100_000.0, []
    for i in range(n):
        if i % 10 == 0 and i:
            eq *= 0.995
        out.append(_pt(i, round(eq, 4)))
    return out


def _panel() -> Path:
    root = Path(tempfile.mkdtemp(prefix="aggr_mark_census_"))
    _write(root, "daily_marked", _daily_marked())
    _write(root, "frozen_book", _frozen())
    _write(root, "unsourced_book", _unsourced_drift())
    _write(root, "sparse_book", _sparse_mark())
    return root


def _doc(root: Path) -> dict:
    return sc.build_scorecard(data_dir=root, use_fixture_if_empty=False, write=False, now_iso=NOW)


def _entry(doc: dict, sid: str) -> dict:
    return next(e for e in doc["strategies"] if e["strategy_id"] == sid)


class TestLoaderCarriesMarkProvenance(unittest.TestCase):
    """Lane 1 stamps ``mtm_source`` on every point; the first consumer must not drop it."""

    def setUp(self) -> None:
        self.root = _panel()

    def test_moved_steps_and_sourced_points_are_counted(self):
        s = ld.load_strategy("daily_marked", data_dir=self.root)
        t = s.backtest
        self.assertEqual(t.n_points, N_DAYS)
        self.assertEqual(t.n_steps, N_DAYS - 1)
        self.assertEqual(t.n_moved_steps, N_DAYS - 1, "every day-step moved in this fixture")
        self.assertEqual(t.n_sourced_points, N_DAYS)
        self.assertEqual(t.sourced_share, 1.0)
        self.assertEqual(t.moved_share, 1.0)
        self.assertEqual(t.last_moved_date, _day(N_DAYS - 1))
        self.assertEqual(t.last_sourced_date, _day(N_DAYS - 1))

    def test_null_source_is_not_coerced_into_a_source(self):
        t = ld.load_strategy("unsourced_book", data_dir=self.root).backtest
        self.assertEqual(t.n_sourced_points, 0)
        self.assertEqual(t.sourced_share, 0.0)
        self.assertIsNone(t.last_sourced_date)
        self.assertEqual(t.n_moved_steps, N_DAYS - 1, "it does move — that is what made it fool us")

    def test_empty_string_source_names_nothing(self):
        root = Path(tempfile.mkdtemp(prefix="aggr_mark_empty_"))
        _write(root, "b", [_pt(i, 100.0 + i, source="   ") for i in range(5)])
        self.assertEqual(ld.load_strategy("b", data_dir=root).backtest.n_sourced_points, 0)

    def test_frozen_book_moves_almost_never(self):
        t = ld.load_strategy("frozen_book", data_dir=self.root).backtest
        self.assertEqual(t.n_moved_steps, 1)
        self.assertAlmostEqual(t.moved_share, 1 / (N_DAYS - 1))
        self.assertEqual(t.last_moved_date, _day(1))

    def test_a_single_point_track_makes_no_claim(self):
        """fail-CLOSED: one point is neither 'it moves' nor 'it is frozen'. 0.0 would lie."""
        root = Path(tempfile.mkdtemp(prefix="aggr_mark_one_"))
        _write(root, "b", [_pt(0, 100.0)])
        t = ld.load_strategy("b", data_dir=root).backtest
        self.assertEqual(t.n_steps, 0)
        self.assertIsNone(t.moved_share)

    def test_a_missing_book_makes_no_claim(self):
        t = ld.load_strategy("nope", data_dir=self.root).backtest
        self.assertIsNone(t.moved_share)
        self.assertIsNone(t.sourced_share)

    def test_steps_are_not_measured_across_the_phase_seam(self):
        """forward and backtest are separate series; a step between the last backtest point and the
        first forward point is not a day-step of either."""
        root = Path(tempfile.mkdtemp(prefix="aggr_mark_seam_"))
        _write(root, "b", [_pt(0, 100.0, phase="backtest"), _pt(1, 100.0, phase="backtest"),
                           _pt(2, 900.0, phase="forward"), _pt(3, 900.0, phase="forward")])
        s = ld.load_strategy("b", data_dir=root)
        self.assertEqual(s.backtest.n_moved_steps, 0)
        self.assertEqual(s.forward.n_moved_steps, 0,
                         "the 100 → 900 jump crosses the seam and belongs to neither track")

    def test_point_shape_consumed_by_metrics_is_unchanged(self):
        """The counts live on the Track. Stamping them into each point would change the shape the
        integrity/metrics layers consume."""
        p = ld.load_strategy("daily_marked", data_dir=self.root).backtest.series[0]
        self.assertEqual(set(p.keys()), {"date", "equity_usd"})


class TestCensusNamesTheFailure(unittest.TestCase):
    """Each status must say WHICH way the book fails, not merely that it does."""

    def setUp(self) -> None:
        self.doc = _doc(_panel())

    def test_daily_marked_book_is_eligible(self):
        dm = _entry(self.doc, "daily_marked")["daily_mark"]
        self.assertEqual(dm["mark_status"], "DAILY_MARK")
        self.assertTrue(dm["cross_section_eligible"])

    def test_frozen_book_is_called_frozen_not_unsourced(self):
        """A constant has nothing for a source to explain; the larger fact is that it is constant."""
        dm = _entry(self.doc, "frozen_book")["daily_mark"]
        self.assertEqual(dm["mark_status"], "FROZEN")
        self.assertFalse(dm["cross_section_eligible"])

    def test_unsourced_book_is_called_unsourced_although_it_moves_every_day(self):
        dm = _entry(self.doc, "unsourced_book")["daily_mark"]
        self.assertEqual(dm["mark_status"], "UNSOURCED_DRIFT")
        self.assertEqual(dm["moved_share"], 1.0, "it moves every day — that is the trap")
        self.assertEqual(dm["sourced_share"], 0.0)
        self.assertFalse(dm["cross_section_eligible"])

    def test_sparse_book_is_distinguished_from_a_frozen_one(self):
        dm = _entry(self.doc, "sparse_book")["daily_mark"]
        self.assertEqual(dm["mark_status"], "SPARSE_MARK")
        self.assertGreater(dm["moved_share"], sc.MARK_FROZEN_MOVED_SHARE)
        self.assertLess(dm["moved_share"], sc.MARK_MIN_MOVED_SHARE)
        self.assertFalse(dm["cross_section_eligible"])

    def test_thin_track_refuses_to_judge(self):
        root = Path(tempfile.mkdtemp(prefix="aggr_mark_thin_"))
        _write(root, "thin", [_pt(0, 100.0)])
        dm = _entry(_doc(root), "thin")["daily_mark"]
        self.assertEqual(dm["mark_status"], "INSUFFICIENT_DATA")
        self.assertFalse(dm["cross_section_eligible"])
        self.assertIsNone(dm["moved_share"])

    def test_summary_names_the_eligible_subset(self):
        dm = self.doc["daily_mark_summary"]
        self.assertEqual(dm["n_books"], 4)
        self.assertEqual(dm["n_daily_mark"], 1)
        self.assertEqual(dm["cross_section_eligible_ids"], ["daily_marked"])
        self.assertEqual(dm["by_status"]["FROZEN"], ["frozen_book"])
        self.assertEqual(dm["by_status"]["UNSOURCED_DRIFT"], ["unsourced_book"])
        self.assertEqual(dm["by_status"]["SPARSE_MARK"], ["sparse_book"])

    def test_every_book_gets_a_status_and_the_sets_partition_the_panel(self):
        """The card asks for a recorded answer FOR EACH book — no book may be left unclassified."""
        dm = self.doc["daily_mark_summary"]
        ids = sorted(i for v in dm["by_status"].values() for i in v)
        self.assertEqual(ids, sorted(e["strategy_id"] for e in self.doc["strategies"]))
        self.assertEqual(len(ids), len(set(ids)), "a book lands in exactly one status")

    def test_census_is_rendered_for_a_human(self):
        text = sc.render_table(self.doc)
        self.assertIn("Daily mark:", text)
        self.assertIn("UNSOURCED_DRIFT", text)
        self.assertIn("FROZEN", text)


class TestCensusDoesNotChangeTheRanking(unittest.TestCase):
    """ADR-091 §3's rule, carried forward: the fact is stated, the order is not quietly rewritten."""

    def test_sort_orders_still_contain_every_book(self):
        doc = _doc(_panel())
        for order in doc["sort_orders"].values():
            self.assertEqual(sorted(order),
                             sorted(e["strategy_id"] for e in doc["strategies"]))

    def test_layer_stays_advisory(self):
        doc = _doc(_panel())
        self.assertTrue(doc["is_advisory"])
        self.assertTrue(doc["outside_riskpolicy"])
        self.assertTrue(doc["separate_from_golive_track"])


class TestPositiveControl(unittest.TestCase):
    """The accident itself: a panel the liveness layer calls 100% alive and 100% healthy, whose
    cross-section is nevertheless not measurable. Before this census there was no field on the
    scorecard that went red here — which is exactly how idea #17 got its numbers."""

    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="aggr_mark_poscontrol_"))
        # six near-constants and four honest books — the composition measured on 2026-08-02
        for i in range(6):
            _write(root, f"constant_{i}", _frozen())
        for i in range(4):
            _write(root, f"real_{i}", _daily_marked())
        self.doc = _doc(root)

    def test_liveness_reports_a_perfectly_healthy_panel(self):
        ls = self.doc["liveness_summary"]
        self.assertEqual(ls["n_killed"], 0)
        self.assertEqual(ls["dead_capital_frac"], 0.0)

    def test_but_only_four_of_the_ten_books_may_carry_a_cross_sectional_claim(self):
        dm = self.doc["daily_mark_summary"]
        self.assertEqual(dm["n_books"], 10)
        self.assertEqual(dm["n_daily_mark"], 4)
        self.assertEqual(dm["cross_section_eligible_ids"],
                         ["real_0", "real_1", "real_2", "real_3"])
        self.assertEqual(len(dm["by_status"]["FROZEN"]), 6)

    def test_the_constants_are_the_ones_reporting_zero_drawdown(self):
        """Why the census is needed at all: the six constants report the panel's best risk numbers,
        so a study that does not filter on the mark hands them the win."""
        for i in range(6):
            e = _entry(self.doc, f"constant_{i}")
            self.assertTrue(e["is_alive"], "never killed — liveness sees nothing wrong")
            self.assertEqual(e["daily_mark"]["mark_status"], "FROZEN")


class TestTheStudyThatPublishesIdea17(unittest.TestCase):
    """Card item 3: the panel has ~36 consumers and none of them checked how many books move.
    ``scripts/edge_real_panel_ensemble.py`` is the one that publishes the #17 verdict, so it must
    read the census from the SAME definition — a second copy of the rule would drift."""

    @staticmethod
    def _script():
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "scripts" / "edge_real_panel_ensemble.py"
        spec = importlib.util.spec_from_file_location("erpe_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def setUp(self) -> None:
        self.mod = self._script()
        self.root = _panel()

    def test_census_matches_the_scorecard_book_for_book(self):
        script = self.mod.mark_census(self.root)
        card = {e["strategy_id"]: e["daily_mark"]["mark_status"]
                for e in _doc(self.root)["strategies"]}
        self.assertEqual({b: c["mark_status"] for b, c in script.items()}, card)

    def test_it_names_the_eligible_subset(self):
        self.assertEqual(self.mod.daily_mark_ids(self.root), ["daily_marked"])

    def test_a_cross_section_over_fewer_than_two_books_is_refused(self):
        """fail-CLOSED: the honest subset of the measured panel had 4 books; a panel whose subset
        collapses to one must refuse, not quietly report a 'cross-section' of a single book."""
        panel = {"only_one": {_day(i): 0.001 for i in range(1, 10)},
                 "other": {_day(i): 0.002 for i in range(1, 10)}}
        axis = self.mod.common_axis(panel)
        with self.assertRaises(RuntimeError):
            self.mod.run_idea17(panel, axis, verbose=False, restrict_to=["only_one"])

    def test_restricting_changes_which_books_are_measured(self):
        panel = {b: {_day(i): (0.001 * (k + 1)) for i in range(1, 30)}
                 for k, b in enumerate(("a", "b", "c"))}
        axis = self.mod.common_axis(panel)
        full = self.mod.run_idea17(panel, axis, verbose=False)
        sub = self.mod.run_idea17(panel, axis, verbose=False, restrict_to=["a", "b"])
        self.assertEqual(sorted(full["books"]), ["a", "b", "c"])
        self.assertEqual(sorted(sub["books"]), ["a", "b"])
        self.assertEqual(sub["restricted_to"], ["a", "b"])
        self.assertIsNone(full["restricted_to"], "an unrestricted run must not claim a subset")


if __name__ == "__main__":
    unittest.main(verbosity=2)
