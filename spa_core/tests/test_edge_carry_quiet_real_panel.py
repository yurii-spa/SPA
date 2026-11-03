"""Controls for registry #151 CQR — CARRY-3+cash vs QUIET-N on the REAL panel.

Every test is a positive control: it either pins an invariant of the instrument, or it breaks
ONE named wire and confirms the instrument notices. None asserts on a printed substring
(ADR-333) — each calls the real internal functions of
`scripts/edge_carry_quiet_real_panel.py` on a deterministic synthetic panel built in a
tmpdir. The real panel (`data/aggressive_lab/`) is gitignored and exists only on the owner's
Mac, so a test that read it would answer "is the owner's disk present" rather than "is the
instrument correct".

Nothing is written outside the tmpdir: no test here touches git-tracked `data/` (ADR-903).

# FROZEN-DATE-OK: synthetic-axis — every date on these scenes is a literal anchor of the
# scene itself (_DAY0 below), and NO module on this path reads a clock: there is no `.now()`,
# `.today()`, `.utcnow()`, `time.time()` or `time.monotonic()` in
# `scripts/edge_carry_quiet_real_panel.py`, in `scripts/edge_real_panel_ensemble.py`, in
# `scripts/edge_measurable_population.py`, or here. The instrument takes no `now` argument
# because it has nothing to pass one to, so no verdict can change because the calendar moved.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import sys
import tempfile
import unittest
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_carry_quiet_real_panel.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("cqr_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cqr_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


CQR = _load()

#: the scene's own epoch. A literal anchor, not a clock read (see FROZEN-DATE-OK above).
_DAY0 = datetime.date(2024, 3, 6)
#: long enough to clear the loader's 60-point floor and the seam's 60-a-side floor
_N_DAYS = 400
#: the scene's seam, placed so both sides clear the 60-day floor
_SEAM = (_DAY0 + datetime.timedelta(days=199)).isoformat()


def _write_book(panel: Path, name: str, rets, *, phase: str = "backtest",
                start: datetime.date = _DAY0) -> None:
    """One book's realized_series.jsonl. equity_usd is the authoritative mark (loader's rule)."""
    d = panel / name
    d.mkdir(parents=True, exist_ok=True)
    eq = 100_000.0
    lines = [json.dumps({"date": start.isoformat(), "as_of": start.isoformat(),
                         "equity_usd": eq, "phase": phase})]
    for i, r in enumerate(rets, start=1):
        eq *= (1.0 + r)
        day = (start + datetime.timedelta(days=i)).isoformat()
        lines.append(json.dumps({"date": day, "as_of": day,
                                 "equity_usd": eq, "phase": phase}))
    (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


def _flat(n=_N_DAYS):
    return [0.0] * n


def _steady(daily, n=_N_DAYS):
    return [daily] * n


def _with_crash(daily, crash, at, n=_N_DAYS):
    out = [daily] * n
    out[at] = crash
    return out


def _panel_of(books: dict, tmp: Path) -> Path:
    panel = tmp / "panel"
    for name, rets in books.items():
        _write_book(panel, name, rets)
    return panel


def _ten_books(*, carry_wins: bool) -> dict:
    """A ten-book scene with the real panel's SHAPE but a chosen winner.

    The shape that matters is the one the real panel has: the books QUIET-N selects are NOT
    the books CARRY-3 selects. So the quiet pair is given a strictly SMALLER TRAIN drawdown
    than the carry trio (zero vs a sub-toll dip), while the carry trio keeps the highest TRAIN
    APY. Without that separation the alphabetical tie-break hands QUIET-N the carry books
    themselves and the two arms become the same portfolio — a scene that cannot test anything.

    `carry_wins` decides what happens AFTER the seam, and only after it: either the carry
    ranking keeps paying while the quiet pair takes a dip (carry wins), or the carry trio
    reverses (quiet wins). Both TRAIN halves are byte-identical, so a selector that peeked at
    TEST would be caught by `test_identical_train_identical_picks_despite_opposite_test`.
    """
    seam_i = 199
    tail = _N_DAYS - seam_i
    books = {
        # loud on TRAIN, and deliberately the HIGHEST daily carry on the panel: by TRAIN APY
        # alone it would be picked first, so the only thing keeping it out of CARRY-3 is the
        # directional exclusion itself. Mutation M9 ("let the directional book in") survived a
        # scene where this book was simply the worst earner — the test passed for the wrong
        # reason. It has a 25 % crash, so QUIET still ranks it last.
        "eth_directional": _with_crash(0.0030, -0.25, 40),
        "loud_a": _with_crash(0.0002, -0.20, 50),
        "loud_b": _with_crash(0.0002, -0.18, 60),
        "loud_c": _with_crash(0.0001, -0.15, 70),
        "loud_d": _with_crash(0.0001, -0.12, 80),
        # the quiet pair: ZERO TRAIN drawdown, modest carry ⇒ QUIET-2 picks exactly these
        "quiet_a": _steady(0.00005),
        "quiet_b": _steady(0.00008),
        # the carry trio: highest TRAIN APY among NON-directional books, but a sub-toll TRAIN
        # dip ⇒ QUIET ranks them AFTER the quiet pair. The dip is 0.3 %, below the 96 bp toll,
        # so it is "unmeasured" too — the real panel's situation, not a convenience.
        # NAMES SORT LAST ON PURPOSE: with names like "carry_*" the alphabetical first three
        # and the top-three-by-TRAIN-APY were the SAME SET, so mutation M8 ("pick by name
        # instead of by APY") survived — the scene could not tell the two rules apart.
        "zeta_carry": _with_crash(0.0010, -0.003, 30),
        "yankee_carry": _with_crash(0.0008, -0.003, 31),
        "xray_carry": _with_crash(0.0006, -0.003, 32),
    }
    if carry_wins:
        # the quiet pair takes a dip AFTER the seam — a book quiet in TRAIN that moves in TEST,
        # which is exactly the failure mode #150 named on the fixture's lrt_carry.
        for b in ("quiet_a", "quiet_b"):
            books[b] = books[b][:seam_i] + [-0.03] + [books[b][0]] * (tail - 1)
    else:
        # the carry ranking reverses after the seam
        for b, daily in (("zeta_carry", -0.0012), ("yankee_carry", -0.0010),
                         ("xray_carry", -0.0008)):
            books[b] = books[b][:seam_i] + [daily] * tail
    return books


class TestPanelLoadingFailsClosed(unittest.TestCase):
    def test_missing_panel_dir_is_unmeasured_not_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(CQR.PanelUnmeasured):
                CQR.load_axis(Path(td) / "does-not-exist")

    def test_cli_returns_2_on_unreadable_panel(self):
        """Third outcome (inv. #17): a gate it could not read exits NON-zero, never 0."""
        with tempfile.TemporaryDirectory() as td:
            rc = CQR.main(["--panel-dir", str(Path(td) / "nope")])
        self.assertEqual(rc, 2)

    def test_panel_with_too_short_axis_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of({"a": _flat(80), "b": _flat(80)}, Path(td))
            with self.assertRaises(CQR.PanelUnmeasured):
                CQR.load_axis(panel)

    def test_seam_that_starves_one_side_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of(_ten_books(carry_wins=True), Path(td))
            axis, _, _ = CQR.load_axis(panel)
            with self.assertRaises(CQR.PanelUnmeasured):
                CQR.seam_index(axis, axis[5])


class TestUnmeasuredIsNotZero(unittest.TestCase):
    """Inv. #17 at the place QUIET-N actually reads: a frozen book is not a quiet book."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        tmp = Path(self.td.name)
        panel = _panel_of({
            "frozen": _flat(),                      # never moved: drawdown NOT MEASURED
            "moved_no_loss": _steady(0.0003),       # moved daily, never lost: measured, == 0
            "loud": _with_crash(0.0002, -0.20, 50),
            "other": _steady(0.0001),
        }, tmp)
        self.axis, self.rets, self.books = CQR.load_axis(panel)
        self.hi = CQR.seam_index(self.axis, _SEAM)
        self.stats = CQR.book_stats(self.rets, self.books, lo=0, hi=self.hi)

    def tearDown(self):
        self.td.cleanup()

    def test_frozen_and_never_lost_have_the_same_maxdd(self):
        """The premise of the whole test: the NUMBER cannot tell them apart."""
        self.assertAlmostEqual(self.stats["frozen"]["maxdd"], 0.0, places=12)
        self.assertAlmostEqual(self.stats["moved_no_loss"]["maxdd"], 0.0, places=12)

    def test_but_the_instrument_does_tell_them_apart(self):
        self.assertEqual(self.stats["frozen"]["moves"], 0)
        self.assertEqual(self.stats["frozen"]["unmeasured"], "never moved")
        self.assertGreater(self.stats["moved_no_loss"]["moves"], 0)
        self.assertEqual(self.stats["moved_no_loss"]["unmeasured"], "maxDD below toll")

    def test_measurable_only_above_the_toll(self):
        self.assertTrue(self.stats["loud"]["measurable"])
        self.assertFalse(self.stats["frozen"]["measurable"])
        self.assertFalse(self.stats["moved_no_loss"]["measurable"])
        self.assertIsNone(self.stats["loud"]["unmeasured"])


class TestSelectorsAreTrainOnly(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        tmp = Path(self.td.name)
        self.panel_a = _panel_of(_ten_books(carry_wins=True), tmp / "a")
        self.panel_b = _panel_of(_ten_books(carry_wins=False), tmp / "b")

    def tearDown(self):
        self.td.cleanup()

    def _picks(self, panel):
        axis, rets, books = CQR.load_axis(panel)
        hi = CQR.seam_index(axis, _SEAM)
        train = CQR.book_stats(rets, books, lo=0, hi=hi)
        return (CQR.carry_pick(train, books),
                CQR.quiet_pick(train, books, n=4))

    def test_identical_train_identical_picks_despite_opposite_test(self):
        """The two scenes differ ONLY after the seam. A look-ahead selector would notice."""
        self.assertEqual(self._picks(self.panel_a), self._picks(self.panel_b))

    def test_carry_pick_excludes_the_directional_book(self):
        """And the exclusion is LOAD-BEARING: that book has the panel's highest TRAIN APY."""
        axis, rets, books = CQR.load_axis(self.panel_a)
        hi = CQR.seam_index(axis, _SEAM)
        train = CQR.book_stats(rets, books, lo=0, hi=hi)
        self.assertIn("eth_directional", books)
        by_apy = sorted(books, key=lambda b: -train[b]["apy"])
        self.assertEqual(by_apy[0], "eth_directional",
                         "scene is useless unless the directional book would otherwise win")
        self.assertNotIn("eth_directional", CQR.carry_pick(train, books))

    def test_carry_pick_follows_train_apy_not_the_book_name(self):
        """Mutation M8 killed here: alphabetical order and APY order give DIFFERENT sets."""
        axis, rets, books = CQR.load_axis(self.panel_a)
        hi = CQR.seam_index(axis, _SEAM)
        train = CQR.book_stats(rets, books, lo=0, hi=hi)
        pool = [b for b in books if b not in set(CQR.DIRECTIONAL)]
        alphabetical = sorted(pool)[:CQR.CARRY_N]
        picked = CQR.carry_pick(train, books)
        self.assertNotEqual(set(alphabetical), set(picked))
        self.assertEqual(set(picked), set(sorted(pool, key=lambda b: -train[b]["apy"])[:3]))

    def test_quiet_pick_keeps_the_directional_book_eligible_as_a_foil(self):
        """#150's convention: QUIET sorts over ALL books; the directional one lands last."""
        axis, rets, books = CQR.load_axis(self.panel_a)
        hi = CQR.seam_index(axis, _SEAM)
        train = CQR.book_stats(rets, books, lo=0, hi=hi)
        order = CQR.quiet_pick(train, books, n=len(books))
        self.assertEqual(len(order), len(books))
        self.assertIn("eth_directional", order)
        self.assertEqual(order[-1], "eth_directional")

    def test_tie_break_is_alphabetical_and_declared(self):
        """The real panel has an exact 0.0000 tie, so the tie-break is load-bearing."""
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of({
                "zz_tied": _flat(), "aa_tied": _flat(), "mm_tied": _flat(),
                "loud": _with_crash(0.0002, -0.20, 50),
            }, Path(td))
            axis, rets, books = CQR.load_axis(panel)
            hi = CQR.seam_index(axis, _SEAM)
            train = CQR.book_stats(rets, books, lo=0, hi=hi)
            # books are handed in REVERSED order on purpose: Python's sort is stable, so with
            # an already-alphabetical input a key of (maxdd,) alone would look correct.
            # Mutation M10 ("drop the name from the key") survived exactly that scene.
            self.assertEqual(CQR.quiet_pick(train, sorted(books, reverse=True), n=3),
                             ["aa_tied", "mm_tied", "zz_tied"])
            self.assertEqual(CQR.quiet_pick(train, books, n=3),
                             ["aa_tied", "mm_tied", "zz_tied"])

    def test_measured_only_pool_excludes_books_below_the_toll(self):
        axis, rets, books = CQR.load_axis(self.panel_a)
        hi = CQR.seam_index(axis, _SEAM)
        train = CQR.book_stats(rets, books, lo=0, hi=hi)
        picked = CQR.quiet_pick(train, books, n=3, measured_only=True)
        for b in picked:
            self.assertTrue(train[b]["measurable"], f"{b} is below the toll")

    def test_measured_only_refuses_when_too_few_books_ever_lost(self):
        """Refusal with a reason, not a silent fallback to the unmeasured pool."""
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of({"q1": _steady(0.0001), "q2": _steady(0.0002),
                               "q3": _flat(), "q4": _steady(0.00005)}, Path(td))
            axis, rets, books = CQR.load_axis(panel)
            hi = CQR.seam_index(axis, _SEAM)
            train = CQR.book_stats(rets, books, lo=0, hi=hi)
            with self.assertRaises(CQR.PanelUnmeasured):
                CQR.quiet_pick(train, books, n=3, measured_only=True)


class TestArmAccounting(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        tmp = Path(self.td.name)
        self.panel = _panel_of(_ten_books(carry_wins=True), tmp)
        self.axis, self.rets, self.books = CQR.load_axis(self.panel)
        self.hi = CQR.seam_index(self.axis, _SEAM)

    def tearDown(self):
        self.td.cleanup()

    def test_cash_pays_exactly_zero_so_deployed_scales_the_return(self):
        """A research arm that pays itself a floor rate compares against an invented benchmark."""
        full = CQR.run_arm(self.rets, ["zeta_carry"], lo=self.hi, hi=len(self.axis),
                           deployed=1.0)
        half = CQR.run_arm(self.rets, ["zeta_carry"], lo=self.hi, hi=len(self.axis),
                           deployed=0.5)
        self.assertLess(half["apy"], full["apy"])
        self.assertLess(half["maxdd"], full["maxdd"] + 1e-12)
        self.assertAlmostEqual(half["deployed"], 0.5, places=12)

    def test_toll_is_charged_once_and_on_the_deployed_fraction(self):
        t = CQR.toll()
        paid = CQR.run_arm(self.rets, ["quiet_a"], lo=self.hi, hi=len(self.axis),
                           deployed=0.75)
        free = CQR.pop().arm(self.rets, {"quiet_a": 1.0}, lo=self.hi, hi=len(self.axis),
                             roundtrip=0.0, deployed=0.75)
        # exactly one day-one charge of t*deployed separates them
        self.assertGreater(free["apy"], paid["apy"])
        self.assertAlmostEqual(CQR.CASH_FRACTION, 0.25, places=12)
        self.assertGreater(t, 0.0)

    def test_calmar_is_refused_below_the_toll_not_printed_as_a_number(self):
        """A smooth-carry arm's only drawdown IS the day-one toll ⇒ denominator degenerate.

        Built on its own scene rather than the ten-book one: there the carry trio's TEST
        drawdown depends on which way that scene was told to resolve, and a control must not
        depend on the thing it is controlling for.
        """
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of({"smooth_a": _steady(0.0003), "smooth_b": _steady(0.0002),
                               "smooth_c": _steady(0.0001), "loud": _with_crash(0.0002, -0.2, 50)},
                              Path(td))
            axis, rets, books = CQR.load_axis(panel)
            hi = CQR.seam_index(axis, _SEAM)
            smooth = CQR.run_arm(rets, ["smooth_a", "smooth_b"], lo=hi, hi=len(axis))
        self.assertLessEqual(smooth["maxdd"], CQR.toll())
        self.assertTrue(smooth["calmar_refused"])
        self.assertEqual(CQR._cal(smooth), "ОТКАЗАН")

    def test_calmar_is_a_number_when_the_denominator_is_measurable(self):
        loud = CQR.run_arm(self.rets, ["loud_a"], lo=0, hi=self.hi)
        self.assertGreater(loud["maxdd"], CQR.toll())
        self.assertFalse(loud["calmar_refused"])
        self.assertNotEqual(CQR._cal(loud), "ОТКАЗАН")

    def test_empty_subset_is_refused(self):
        with self.assertRaises(CQR.PanelUnmeasured):
            CQR.run_arm(self.rets, [], lo=self.hi, hi=len(self.axis))


class TestPlaceboIsExhaustive(unittest.TestCase):
    def test_population_is_every_subset_not_a_sample(self):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of(_ten_books(carry_wins=True), Path(td))
            axis, rets, books = CQR.load_axis(panel)
            hi = CQR.seam_index(axis, _SEAM)
            pl = CQR.placebo_exhaustive(rets, books, lo=hi, hi=len(axis))
            n_nondir = len(books) - len(CQR.DIRECTIONAL)
            self.assertEqual(pl["n_subsets"], len(list(combinations(range(n_nondir), 3))))
            self.assertEqual(pl["n_subsets"], len(pl["apys"]))

    def test_percentile_of_the_best_is_the_top_of_the_population(self):
        self.assertEqual(CQR.percentile_of([1.0, 2.0, 3.0, 4.0], 5.0), 100.0)
        self.assertEqual(CQR.percentile_of([1.0, 2.0, 3.0, 4.0], 0.0), 0.0)

    def test_empty_placebo_population_has_no_percentile(self):
        with self.assertRaises(CQR.PanelUnmeasured):
            CQR.percentile_of([], 1.0)

    def test_tiny_universe_is_refused_rather_than_called_a_placebo(self):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of({"eth_directional": _flat(), "a": _steady(0.0001),
                               "b": _steady(0.0002), "c": _steady(0.0003)}, Path(td))
            axis, rets, books = CQR.load_axis(panel)
            hi = CQR.seam_index(axis, _SEAM)
            with self.assertRaises(CQR.PanelUnmeasured):
                CQR.placebo_exhaustive(rets, books, lo=hi, hi=len(axis))


class TestVerdictFollowsTheDataBothWays(unittest.TestCase):
    """The controls that matter: the comparison is COMPUTED, not written down.

    Two scenes with IDENTICAL TRAIN halves and opposite TEST halves must produce opposite
    verdicts from the same instrument. A hardcoded conclusion passes one and fails the other.
    """

    def _seam(self, carry_wins):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of(_ten_books(carry_wins=carry_wins), Path(td))
            axis, rets, books = CQR.load_axis(panel)
            return CQR.seam_report(axis, rets, books, _SEAM)

    def test_carry_dominates_when_the_train_ranking_keeps_paying(self):
        s = self._seam(carry_wins=True)
        self.assertTrue(s["carry_dominates"])
        self.assertLess(s["d_apy"], 0.0)   # QUIET minus CARRY < 0 ⇒ CARRY earned more

    def test_carry_does_not_dominate_when_the_ranking_reverses(self):
        s = self._seam(carry_wins=False)
        self.assertFalse(s["carry_dominates"])
        self.assertGreater(s["d_apy"], 0.0)

    def test_within_toll_is_measured_against_the_canonical_toll(self):
        for carry_wins in (True, False):
            s = self._seam(carry_wins)
            self.assertEqual(s["within_toll"], abs(s["d_apy"]) <= CQR.toll())
            self.assertAlmostEqual(s["toll"], CQR.toll(), places=12)

    def test_within_toll_is_reached_in_BOTH_directions_on_a_swept_scene(self):
        """The acceptance flag of order #150 must be able to say True as well as False.

        Mutation M14 ("hardcode within_toll = False") survived while both scenes above sat far
        outside the toll: the equality in the previous test was then vacuous in one direction.
        The knob swept here is the QUIET pair's own carry rate, with no TEST dip, because that
        is the quantity that moves QUIET-4's average toward CARRY-3+cash's 75 %-deployed
        average — the two arms cross near 5 bp/day, where the gap falls inside the 96 bp toll.
        The sweep stops below the rate at which the quiet pair would enter CARRY-3 itself: a
        scene that changed BOTH arms' composition would be sweeping two things at once.
        """
        seen = set()
        for quiet_daily in (0.00005, 0.00020, 0.00035, 0.00045, 0.00050, 0.00055):
            books = _ten_books(carry_wins=True)
            books["quiet_a"] = _steady(quiet_daily)
            books["quiet_b"] = _steady(quiet_daily)
            with tempfile.TemporaryDirectory() as td:
                panel = _panel_of(books, Path(td))
                axis, rets, bk = CQR.load_axis(panel)
                s = CQR.seam_report(axis, rets, bk, _SEAM)
            self.assertEqual(s["carry3"], ["zeta_carry", "yankee_carry", "xray_carry"],
                             "sweep must not change which books CARRY-3 selects")
            self.assertEqual(s["within_toll"], abs(s["d_apy"]) <= CQR.toll())
            seen.add(s["within_toll"])
        self.assertEqual(seen, {True, False},
                         f"sweep never reached both sides of the toll: {seen}")

    def test_report_carries_both_seams_and_names_the_panel(self):
        with tempfile.TemporaryDirectory() as td:
            panel = _panel_of(_ten_books(carry_wins=True), Path(td))
            axis, _, _ = CQR.load_axis(panel)
            late = (_DAY0 + datetime.timedelta(days=299)).isoformat()
            rep = CQR.report(panel, seams=(_SEAM, late))
            self.assertEqual(len(rep["seams"]), 2)
            self.assertEqual(rep["panel_dir"], str(panel))
            self.assertEqual(rep["axis_days"], len(axis))
            # printing must not raise on a real report
            CQR.print_report(rep)

    def test_composition_counts_unmeasured_books_inside_quiet(self):
        s = self._seam(carry_wins=True)
        for n in CQR.QUIET_NS:
            c = s["composition"][n]
            self.assertEqual(len(c["books"]), n)
            self.assertLessEqual(c["n_unmeasured"], n)
            self.assertLessEqual(c["n_never_moved"], c["n_unmeasured"])


class TestDeclaredConstantsAreNotDrifting(unittest.TestCase):
    def test_seams_and_toll_match_the_registry_harness(self):
        self.assertEqual(CQR.SEAMS, ("2025-06-30", "2026-01-01"))
        self.assertAlmostEqual(CQR.toll(), CQR.ens().PLB_ROUNDTRIP, places=12)
        self.assertEqual(CQR.DIRECTIONAL, ("eth_directional",))
        self.assertEqual(CQR.CARRY_N, 3)
        self.assertEqual(CQR.QUIET_NS, (2, 3, 4))

    def test_advisory_flags_are_set(self):
        self.assertTrue(CQR.IS_ADVISORY)
        self.assertTrue(CQR.OUTSIDE_RISKPOLICY)


if __name__ == "__main__":
    unittest.main()
