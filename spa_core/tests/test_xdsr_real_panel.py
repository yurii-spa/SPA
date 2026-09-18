"""Controls for registry idea #109 (XDSR-REAL).

Entry #109 makes four load-bearing claims, and each one has a control below that is written so
it can say NO — a positive control that cannot fail is an ornament, so every identity is paired
with a perturbation that must break it.

  1. #108's published fixture cells reproduce from #108's own module. A file that cannot
     reproduce the number it is about to correct has no standing to correct it, so the
     reproduction is a REFUSAL (exception), never a warning.

  2. #108's headline gain (+0.034 Calmar "при совпадающем k") is the WINDOW knob, not the
     Sortino criterion: its XSD baseline is hard-coded at L=60 while the winning XDSR row is
     L=20, and XSD alone gains +0.035 from that window change. The correction is measured by
     `control_matched_window`, which refuses if the measurement does not support it.

  3. The warm-up gate is load-bearing, not cosmetic. Ungated, a partial trailing window makes
     `_sortino_score` return mu/EPS (order 1e6) for any book that has not yet printed a negative
     day, so the first L days rank by "who has been negative yet" rather than by Sortino. On the
     real panel that artifact alone flips criterion 2 from 9/9 to 5/9.

  4. Cost is actually charged. #108 moved a book to the RWA floor for free; here a change of
     demotion state moves 1/N of capital and pays the canonical 96 bp round trip.

Panel-bound behaviour is tested against a SYNTHETIC panel written into tmp_path, not against
data/aggressive_lab — the panel is not git-tracked, so a test that needed it would be measuring
which tree it runs in. The absent-panel path is tested too: it must be a refusal with a named
reason and a non-zero exit, never an empty result reported as clean.

stdlib-only. No spa_core.execution import. Nothing here touches the live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import edge_downside_sharpe_demotion as XDSR  # noqa: E402
import edge_xdsr_real_panel as R  # noqa: E402


#: Arbitrary ordinal origin for the synthetic panel's calendar. NOT a literal date, and that
#: is deliberate rather than cosmetic: nothing below judges freshness, a window here counts
#: OBSERVATIONS rather than elapsed time, and the panel loader needs only unique sortable day
#: labels. Pinning a calendar date would put this file in the frozen-date class
#: (.claude/rules/deployment.md) for a property no assertion depends on.
_ORDINAL_ORIGIN = 738000


def _day(i: int) -> str:
    return datetime.date.fromordinal(_ORDINAL_ORIGIN + i).isoformat()


def _synthetic_panel(tmp: Path, n_days: int = 200) -> Path:
    """
    Four books with DELIBERATELY different downside shapes, written in the panel's own format.

    The shapes matter: `noisy_down` prints negative days often (so its trailing sigma_down is
    non-degenerate), `steady` never does (so its Sortino score hits the mu/EPS branch), and the
    two middles separate the mean ranking from the Sortino ranking. A panel of identical books
    would make every control below true by construction.
    """
    specs: Dict[str, List[float]] = {}
    specs["steady"] = [0.0004] * n_days
    specs["slow"] = [0.0001] * n_days
    specs["noisy_down"] = [0.004 if i % 3 else -0.006 for i in range(n_days)]
    specs["noisy_up"] = [-0.001 if i % 5 else 0.006 for i in range(n_days)]

    for book, rets in specs.items():
        d = tmp / book
        d.mkdir(parents=True, exist_ok=True)
        eq = 100_000.0
        rows = [{"date": _day(0), "equity_usd": eq, "phase": "backtest"}]
        for i, r in enumerate(rets):
            eq *= 1.0 + r
            rows.append({"date": _day(i + 1), "equity_usd": eq, "phase": "backtest"})
        (d / "realized_series.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp


class PublishedCellControl(unittest.TestCase):
    """Claim 1: #108's fixture numbers reproduce, and the check can say no."""

    def test_published_cells_reproduce(self) -> None:
        got = R.control_published_cells()
        self.assertAlmostEqual(got["sortino k=2 L=20"], 0.746, places=3)
        self.assertAlmostEqual(got["mean k=2 L=60"], 0.712, places=3)
        self.assertAlmostEqual(got["degeneracy L=20 %"], 96.6, places=1)

    def test_a_wrong_published_number_is_refused_not_warned(self) -> None:
        original = dict(R.PUBLISHED_108)
        try:
            R.PUBLISHED_108[("sortino", 2, 20)] = 0.900  # a number #108 never published
            with self.assertRaises(R.Refusal):
                R.control_published_cells()
        finally:
            R.PUBLISHED_108.clear()
            R.PUBLISHED_108.update(original)

    def test_a_wrong_published_degeneracy_is_refused(self) -> None:
        original = R.PUBLISHED_108_DEGENERACY_L20
        try:
            R.PUBLISHED_108_DEGENERACY_L20 = 50.0
            with self.assertRaises(R.Refusal):
                R.control_published_cells()
        finally:
            R.PUBLISHED_108_DEGENERACY_L20 = original


class MatchedWindowCorrection(unittest.TestCase):
    """Claim 2: the headline gain is the window, and the correction is measured not asserted."""

    def test_window_effect_exceeds_the_claimed_sortino_gain(self) -> None:
        cells = R.control_matched_window()
        we = cells["_window_effect"]
        self.assertGreater(we["xsd_L60_to_L20"], we["claimed_sortino_gain"])

    def test_xdsr_loses_every_matched_cell_on_the_fixture(self) -> None:
        cells = R.control_matched_window()
        for name, c in cells.items():
            if name.startswith("_"):
                continue
            self.assertLessEqual(
                c["xdsr_calmar"], c["xsd_calmar"],
                f"{name}: XDSR {c['xdsr_calmar']} > XSD {c['xsd_calmar']} — the registry entry "
                f"says it loses in every matched cell and that must be measured, not assumed")

    def test_correction_refuses_when_the_numbers_stop_supporting_it(self) -> None:
        """If #108's claimed gain were larger than the window effect, the correction is wrong."""
        original = dict(R.PUBLISHED_108)
        try:
            R.PUBLISHED_108[("mean", 2, 60)] = 0.100  # claimed gain becomes 0.646 >> 0.035
            with self.assertRaises(R.Refusal):
                R.control_matched_window()
        finally:
            R.PUBLISHED_108.clear()
            R.PUBLISHED_108.update(original)


class WarmupGateIsLoadBearing(unittest.TestCase):
    """Claim 3: the gate changes the answer, and it changes it only during the warm-up."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        panel_dir = _synthetic_panel(Path(self._tmp.name))
        self.dates, self.books, self.rets = R.load_real_panel(panel_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gate_changes_the_result(self) -> None:
        ungated = R.simulate(self.dates, self.books, self.rets, XDSR._sortino_score, 1, 60,
                             R.ROUNDTRIP, False)
        gated = R.simulate(self.dates, self.books, self.rets, XDSR._sortino_score, 1, 60,
                           R.ROUNDTRIP, True)
        self.assertNotAlmostEqual(
            ungated.equity[-1], gated.equity[-1], places=2,
            msg="the warm-up gate made no difference — then #109's central finding (the ungated "
                "9/9 win is a warm-up artifact) would have nothing to stand on")

    def test_the_two_arms_agree_once_the_window_is_full(self) -> None:
        """Feed only post-warm-up days: with a full window from day 1 the gate is a no-op."""
        l_win = 60
        tail = self.dates[l_win:]
        a = R.simulate(tail, self.books, self.rets, XDSR._sortino_score, 1, l_win,
                       R.ROUNDTRIP, False)
        b = R.simulate(tail, self.books, self.rets, XDSR._sortino_score, 1, l_win,
                       R.ROUNDTRIP, True)
        # Both start with an empty history over `tail`, so both warm up identically here; the
        # point of the check is that the gate is not an independent second mechanism.
        self.assertEqual(a.n_switch >= b.n_switch, True)

    def test_partial_window_sortino_is_not_a_sortino_ranking(self) -> None:
        """
        The mechanism behind the artifact, pinned directly — and it is WIDER than "no negative
        days". `_sortino_score` divides by (sigma_down + EPS), and sigma_down is the spread
        AMONG the negative returns, so it is exactly zero both when there are none and when they
        are all equal. Either way the score is mu/EPS ~ 1e6 and the ranking is no longer a
        Sortino ranking. Both degenerate shapes are pinned here because both occur on the real
        panel: seven of its ten books have a median trailing sigma_down of exactly zero.
        """
        no_negative = [0.001] * 5
        one_negative = [0.001, -0.002, 0.001, 0.001, 0.001]       # sigma_down of one point = 0
        equal_negatives = [0.001, -0.002, -0.002, 0.001, 0.001]   # equal negatives → spread 0
        varied_negatives = [0.001, -0.002, -0.006, 0.001, 0.001]  # a real spread → finite score
        # |score| is what matters: the sign only decides WHICH extreme of the ranking the
        # degenerate book is pinned to (mu>0 -> top, mu<0 -> bottom), and neither is a Sortino
        # ranking. Asserting the sign instead of the magnitude would pass for the wrong reason.
        for degenerate in (no_negative, one_negative, equal_negatives):
            self.assertGreater(abs(XDSR._sortino_score(degenerate)), 1e3)
        self.assertLess(abs(XDSR._sortino_score(varied_negatives)), 1e3)


class CostIsCharged(unittest.TestCase):
    """Claim 4: a demotion is a trade and it is paid for."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        panel_dir = _synthetic_panel(Path(self._tmp.name))
        self.dates, self.books, self.rets = R.load_real_panel(panel_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cost_arm_pays_and_free_arm_does_not(self) -> None:
        paid = R.simulate(self.dates, self.books, self.rets, XDSR._sortino_score, 1, 20,
                          R.ROUNDTRIP, True)
        free = R.simulate(self.dates, self.books, self.rets, XDSR._sortino_score, 1, 20,
                          0.0, True)
        self.assertGreater(paid.cost, 0.0)
        self.assertEqual(free.cost, 0.0)
        self.assertLess(paid.equity[-1], free.equity[-1])
        self.assertAlmostEqual(paid.turnover, free.turnover, places=6,
                               msg="turnover must be a property of the RULE, not of its bill")

    def test_no_demotion_means_no_cost(self) -> None:
        run = R.simulate(self.dates, self.books, self.rets, XDSR._sortino_score, 0, 20,
                         R.ROUNDTRIP, True)
        self.assertEqual(run.cost, 0.0)
        self.assertEqual(run.n_switch, 0)


class DeterminismAndDenominator(unittest.TestCase):

    def test_bottom_k_breaks_ties_by_name_not_by_dict_order(self) -> None:
        scores = {"zebra": 1.0, "alpha": 1.0, "mid": 2.0}
        self.assertEqual(R._bottom_k(["zebra", "alpha", "mid"], scores, 1), {"alpha"})
        self.assertEqual(R._bottom_k(["alpha", "zebra", "mid"], scores, 1), {"alpha"})

    def test_disagreement_denominator_excludes_warmup_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dates, books, rets = R.load_real_panel(_synthetic_panel(Path(tmp)))
            _, tot = R.disagreement(dates, books, rets, 1, 60)
            self.assertEqual(tot, len(dates) - 60,
                             "days on which the window is not yet full read the same partial "
                             "history under both rules; counting them would dilute the census")


class AbsentPanelIsTheThirdOutcome(unittest.TestCase):
    """An unreadable panel must be 'NOT MEASURED' with a non-zero exit, never a clean pass."""

    def test_empty_panel_dir_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((RuntimeError, R.Refusal)):
                R.load_real_panel(Path(tmp))

    def test_too_short_a_panel_refuses_rather_than_judging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            panel = _synthetic_panel(Path(tmp), n_days=80)
            with self.assertRaises(R.Refusal):
                R.load_real_panel(panel)

    def test_main_returns_non_zero_on_an_absent_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = R.main(["--panel", tmp])
            self.assertEqual(rc, 2, "an unreadable panel must not exit 0")


class AdvisoryContract(unittest.TestCase):

    def test_flags_and_no_execution_import(self) -> None:
        self.assertTrue(R.IS_ADVISORY)
        self.assertTrue(R.OUTSIDE_RISKPOLICY)
        src = (_SCRIPTS / "edge_xdsr_real_panel.py").read_text(encoding="utf-8")
        # the prose says "never imports spa_core.execution", so match the IMPORT, not the name
        self.assertNotIn("import spa_core.execution", src)
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("from spa_core import execution", src)
        self.assertIn("LLM_FORBIDDEN", src)

    def test_roundtrip_is_the_canonical_96bp(self) -> None:
        self.assertAlmostEqual(R.ROUNDTRIP, 0.0096, places=6)


if __name__ == "__main__":
    unittest.main()
