"""
Acceptance for registry idea GFC (`scripts/edge_guardian_flagship_causality.py`).

The entry says the registry's flagship table (#1) is causal and therefore survives #94. A
"clean" verdict is the easiest kind of verdict to reach by accident, so every check here is a
POSITIVE CONTROL for a specific way that verdict could be false, and each names its defect:

  · the harness cannot tell a causal overlay from a look-ahead one    → t_sabotage_*
  · it is comparing EQUITY, where one boundary day compounds forever
    and makes identical rules look different (and vice versa)         → t_decision_vs_equity
  · the reproduction check does not actually fail when #1 moves       → t_reproduction_fails_closed
  · `is_impossible_tail` is a rubber stamp that fires on anything     → t_impossible_tail_*
  · the control column is a convention-compatible lookalike rather
    than the function #94 actually indicted                           → t_control_is_the_real_module

Nothing here moves capital, retunes anything, or touches the live track. The fixture is
materialised into a temp directory by the script itself — never into `data/`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_guardian_flagship_causality as gfc  # noqa: E402
import guardian_backtest as gb  # noqa: E402

from spa_core.strategy_lab.aggressive_lab import guardian as g  # noqa: E402

_BOOKS = None


def books():
    """Materialise the documented fixture once. The script's own loader; a temp dir."""
    global _BOOKS
    if _BOOKS is None:
        _BOOKS = gfc.load_fixture_books()
    return _BOOKS


def best_params(book: str):
    return gfc.best_cell(books()[book], gfc.fixture_overlay)[3]


class PublishedTableTest(unittest.TestCase):
    """#1 must still be there for this entry to have anything to re-check."""

    def test_the_published_preemptive_cells_reproduce(self):
        for book, (w_apy, w_mdd, w_cal) in gfc.PUBLISHED_PREEMPTIVE.items():
            with self.subTest(book=book):
                self.assertIn(book, books(), f"{book} vanished from the fixture roster")
                apy, mdd, cal, _ = gfc.best_cell(books()[book], gfc.fixture_overlay)
                self.assertAlmostEqual(apy, w_apy, delta=gfc.REPRO_TOL)
                self.assertAlmostEqual(mdd, w_mdd, delta=gfc.REPRO_TOL)
                if w_cal is not None:
                    self.assertAlmostEqual(cal, w_cal, delta=gfc.REPRO_TOL)

    def test_reproduction_fails_closed_when_a_published_cell_moves(self):
        """POSITIVE CONTROL: the guard must REFUSE, not warn, when #1 no longer reproduces.

        Defect it replays: an entry that re-checks a table which has silently moved underneath
        it, and publishes a verdict about numbers nobody can find. That is the failure mode #92
        caught the registry committing with its own cost convention.
        """
        with self.assertRaises(gfc.ReproductionFailure):
            gfc.check_published("susde_dn", 99.0, 4.5, 1.6)
        with self.assertRaises(gfc.ReproductionFailure):
            gfc.check_published("susde_dn", 7.3, 99.0, 1.6)
        with self.assertRaises(gfc.ReproductionFailure):
            gfc.check_published("susde_dn", None, 4.5, 1.6)

    def test_an_unknown_book_is_not_silently_approved(self):
        """A book with no published cell must pass through without inventing an expectation —
        but it must also not be counted as a reproduced cell anywhere."""
        gfc.check_published("variant_d", 0.0, 0.0, 0.0)  # no published row; must not raise
        self.assertNotIn("variant_d", gfc.PUBLISHED_PREEMPTIVE)


class DecisionComparisonTest(unittest.TestCase):
    """The load-bearing claim, and the reason it is measured on decisions."""

    def test_published_and_causal_disagree_on_exactly_the_boundary_day(self):
        for book, eq in books().items():
            with self.subTest(book=book):
                vm, fr = best_params(book)
                d = gfc.decision_disagreements(
                    eq,
                    gfc.fixture_overlay(eq, vol_mult=vm, derisk_frac=fr),
                    gfc.causal_overlay(eq, vol_mult=vm, derisk_frac=fr))
                self.assertEqual(
                    d, [gfc.LOOKBACK],
                    f"{book}: the published overlay and the causal mirror disagree on days "
                    f"{d}; the entry claims the only disagreement is the boundary index "
                    f"{gfc.LOOKBACK}, where the mirror may act one day earlier")

    def test_sabotaging_the_published_overlay_to_same_bar_spreads_the_disagreement(self):
        """POSITIVE CONTROL: if the published path DID look ahead, this comparison must say so.

        Defect it replays: a causality check that returns 'boundary only' no matter what is
        handed to it — the whole verdict would then be a property of the instrument. Feeding it
        the genuinely same-bar function must move the answer far off the boundary.
        """
        moved = 0
        for book, eq in books().items():
            vm, fr = best_params(book)
            d = gfc.decision_disagreements(
                eq,
                gfc.same_bar_overlay(eq, vol_mult=vm, derisk_frac=fr),
                gfc.causal_overlay(eq, vol_mult=vm, derisk_frac=fr))
            beyond = [i for i in d if i != gfc.LOOKBACK]
            if beyond:
                moved += 1
        self.assertEqual(moved, len(books()),
                         "the same-bar function disagrees with the causal mirror ONLY at the "
                         "boundary on some book — then this comparison cannot detect "
                         "look-ahead at all and the entry's verdict is vacuous")

    def test_decision_and_equity_comparisons_genuinely_differ(self):
        """The methodological point, pinned: equity cannot answer this question.

        Defect it replays: judging 'same rule?' on the equity path. Here the two overlays agree
        on every decision but one, and the equity paths STILL differ by orders of magnitude
        more than float noise — so an equity-based check would have called an identical rule
        different, and the entry's verdict would have been the opposite one.
        """
        for book, eq in books().items():
            with self.subTest(book=book):
                vm, fr = best_params(book)
                a = gfc.fixture_overlay(eq, vol_mult=vm, derisk_frac=fr)
                b = gfc.causal_overlay(eq, vol_mult=vm, derisk_frac=fr)
                n = min(len(a), len(b))
                gap = max(abs(a[i] - b[i]) / (abs(b[i]) or 1.0) for i in range(n))
                self.assertGreater(gap, 1e-6,
                                   "the equity paths are identical, so this test no longer "
                                   "demonstrates why decisions must be compared instead")
                self.assertLess(gap, 1e-2, "the equity gap is far larger than one boundary "
                                           "day can explain — re-examine the claim")

    def test_implied_exposure_recovers_a_known_exposure(self):
        """The instrument itself, on a path whose answer is known by construction."""
        equity = [100.0, 110.0, 99.0, 118.8]
        half = [100.0]
        exposure = 0.5
        for i in range(1, len(equity)):
            r = equity[i] / equity[i - 1] - 1.0
            half.append(half[-1] * (1.0 + r * exposure))
        got = gfc.implied_exposure(equity, half)
        for v in got:
            self.assertIsNotNone(v)
            assert v is not None
            self.assertAlmostEqual(v, exposure, places=9)

    def test_a_flat_day_yields_no_exposure_rather_than_a_fabricated_one(self):
        """Division by a zero return must produce None, not a number.

        Defect it guards: silently inventing an exposure on a day the book did not move, which
        would then be compared against another invented one and could manufacture or hide a
        disagreement.
        """
        self.assertEqual(gfc.implied_exposure([100.0, 100.0], [100.0, 100.0]), [None])


class ControlIsRealTest(unittest.TestCase):
    """The control column must be the indicted function, and it must actually misbehave."""

    def test_control_is_the_real_module_not_a_lookalike(self):
        """`same_bar_overlay` must return exactly what `guardian.apply_guardian_vol` returns.

        Defect it replays: this file's own earlier draft, which used a lag-0 mirror as the
        control. Same convention, different code — their decisions were measured to disagree
        for up to eight days on one book. A control that merely resembles its subject is the
        very confusion (two functions, one name) that this entry is about.
        """
        for book, eq in books().items():
            with self.subTest(book=book):
                vm, fr = best_params(book)
                mine = gfc.same_bar_overlay(eq, vol_mult=vm, derisk_frac=fr)
                real = g.apply_guardian_vol(eq, lookback=gfc.LOOKBACK, vol_mult=vm,
                                            derisk_frac=fr, calm_mult=gfc.CALM_MULT,
                                            roundtrip_cost=0.0)
                self.assertEqual(mine, real)

    def test_the_canonical_module_erases_the_tail_on_every_fixture_book(self):
        """The control has to be able to fail loudly, and here it does.

        This is what the look-ahead is worth on this fixture: not a flattering number, an
        impossible one. If this ever stops holding, the entry's section 3 — and the smoke test
        it hands the tree — must be rewritten, not quietly kept.
        """
        for book, eq in books().items():
            with self.subTest(book=book):
                vm, fr = best_params(book)
                _apy, mdd, _cal = gb._metrics(
                    gfc.same_bar_overlay(eq, vol_mult=vm, derisk_frac=fr))
                self.assertTrue(gfc.is_impossible_tail(mdd),
                                f"{book}: the canonical module reports maxDD {mdd}, which is "
                                f"not the vanishing tail section 3 reports")

    def test_the_causal_column_keeps_a_real_tail(self):
        """REVERSE CONTROL. Without it, 'the tail vanishes' could be a property of the fixture
        rather than of the look-ahead, and the entry would be attributing it to the wrong cause.
        """
        for book, eq in books().items():
            with self.subTest(book=book):
                vm, fr = best_params(book)
                _apy, mdd, _cal = gb._metrics(
                    gfc.causal_overlay(eq, vol_mult=vm, derisk_frac=fr))
                self.assertFalse(gfc.is_impossible_tail(mdd),
                                 f"{book}: the CAUSAL overlay also shows no tail ({mdd}) — the "
                                 f"vanishing drawdown is then not evidence of look-ahead")

    def test_impossible_tail_predicate_in_both_directions(self):
        self.assertTrue(gfc.is_impossible_tail(0.0))
        self.assertTrue(gfc.is_impossible_tail(0.04))
        self.assertFalse(gfc.is_impossible_tail(1.0))
        self.assertFalse(gfc.is_impossible_tail(8.5))
        self.assertFalse(gfc.is_impossible_tail(None))
        self.assertFalse(gfc.is_impossible_tail("n/a"))


class PanelAccountingTest(unittest.TestCase):
    """Every book must be accounted for — compared or explicitly not."""

    def test_the_fixture_roster_is_the_one_hash1_published_on(self):
        for book in gfc.PUBLISHED_PREEMPTIVE:
            self.assertIn(book, books())

    def test_an_empty_fixture_refuses_loudly_instead_of_printing_no_books(self):
        """Defect it guards: an empty panel rendering as 'the guardian has nothing to guard'.

        The tree has paid for this class before — a worktree's `data/` is empty BY CONSTRUCTION,
        and an empty table there reads as a measurement.
        """
        real = gfc.ld.load_all
        gfc.ld.load_all = lambda **kw: {}
        try:
            with self.assertRaises(gfc.ReproductionFailure):
                gfc.load_fixture_books()
        finally:
            gfc.ld.load_all = real


class AdvisoryContractTest(unittest.TestCase):
    """The invariants the standing directive makes non-negotiable."""

    SRC = ROOT / "scripts" / "edge_guardian_flagship_causality.py"

    def test_flags(self):
        self.assertTrue(gfc.IS_ADVISORY)
        self.assertTrue(gfc.OUTSIDE_RISKPOLICY)
        self.assertEqual(gfc.EVIDENCE_LEVEL, "L0")

    def test_never_imports_execution(self):
        """Judged on CODE lines. The header sentence promising not to import it is prose, and a
        substring search over the file would read that promise as its own violation."""
        offenders = [
            ln for ln in self.SRC.read_text().splitlines()
            if ln.lstrip().startswith(("import ", "from ")) and "spa_core.execution" in ln
        ]
        self.assertEqual(offenders, [])

    def test_llm_forbidden_marker_present(self):
        self.assertIn("LLM_FORBIDDEN", self.SRC.read_text())

    def test_nothing_here_writes(self):
        """No write path at all: no atomic_save, no open(..., 'w'), no json.dump to the tree.

        This entry is a re-measurement of a published table. A write of any kind would put it
        in a different category, and the fixture materialiser already has a temp dir of its own.
        """
        src = self.SRC.read_text()
        for forbidden in ("atomic_save", "json.dump", '"w")', "'w')"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
