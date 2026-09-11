"""Guards for the Boundary Dataflow Census (idea #103, ordered by registry entry #100 §7(в)).

Every test here replays a defect this instrument ACTUALLY had while it was being built, in the
order the controls caught them. None is hypothetical, and that is deliberate: a check that has
never seen a real failure is an ornament (`.claude/rules/deployment.md`, "проверка сторожа
сторожей").

The defects, in the order they were measured:

  1. The observer joined its own population — writing the file into `scripts/` as `edge_*.py`
     made #100's census screen 35 modules instead of the published 34.
  2. The calibration control SKIPPED what it could not measure. All six controls came back
     UNMEASURED and the run continued, publishing nine verdicts from an uncalibrated probe.
  3. The tape watched ONE family of operators. The `gtn` family defines its own state
     operators, and the deployed organ (`apply_guardian_vol`) is a third family reached only by
     `from ... import`, which a defining-module patch never sees.
  4. Three day conventions live one apart (returns n, weight history n−1, equity path n+1). An
     exact-halves test missed two of them SILENTLY — as CARRY, the direction that hides.
  5. `len(args[0])` measured the BOOK count for panel operators, not the day count.
  6. The state-carrying probe called arbitrary corpus functions and reached 4 GB RSS.

The suite is hermetic: it never loads the real panel (`data/aggressive_lab` is absent from a
worktree BY CONSTRUCTION, so a test that needed it would have its verdict decided by which tree
it runs in) and never writes anything.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edge_boundary_dataflow_census as bdc  # noqa: E402


FACTS = {"full": 852, "train": 482, "test": 370}


def _tape(decision=(), metric=()):
    tape = bdc.OperatorTape()
    for name, n in decision:
        tape.note("decision", name, n)
    for name, n in metric:
        tape.note("metric", name, n)
    return tape


class TestUnmeasuredIsNeverAVerdict(unittest.TestCase):
    """Defect 2: "could not measure" and "measured, and it is fine" must never share an outcome."""

    def test_a_module_that_did_not_run_is_unmeasured_not_carry(self):
        res = bdc.classify(_tape(), FACTS, ran=False, note="import failed", escaped=False)
        self.assertEqual(res["verdict"], "UNMEASURED")

    def test_a_module_that_ran_but_touched_no_operator_is_unmeasured_not_carry(self):
        # The exact shape that made every control silently "pass" in the first version: the
        # probe was never connected, and the resulting silence looked like a clean bill.
        res = bdc.classify(_tape(), FACTS, ran=True, note="", escaped=False)
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertIn("did not reach", res["reason"])

    def test_carry_requires_a_witness_that_the_probe_reached_the_module(self):
        res = bdc.classify(_tape(metric=[("perf", 852)]), FACTS, ran=True, note="",
                           escaped=False)
        self.assertEqual(res["verdict"], "CARRY")

    def test_calibration_refuses_on_an_unmeasurable_control(self):
        """The control must RAISE, not skip. `pytest.raises(AssertionError)` would miss a skip,
        so the refusal is checked by type explicitly."""
        # The other two control groups are emptied for the duration. Without that, this test
        # passed even when the refusal it names was mutated away — the exception came from the
        # FALSE_POSITIVE branch instead, and the test could not tell the two apart. A scene must
        # violate ONLY its own constraint.
        saved = (bdc.CONTROL_MUST_RESTART, bdc.CONTROL_MUST_NOT_RESTART,
                 bdc.FALSE_POSITIVE_OF_100)
        try:
            bdc.CONTROL_MUST_RESTART = ("edge_module_that_does_not_exist",)
            bdc.CONTROL_MUST_NOT_RESTART = ()
            bdc.FALSE_POSITIVE_OF_100 = ()
            with self.assertRaises(bdc.ControlFailed):
                bdc.section1_calibrate(FACTS, escapees=(), operators={})
        finally:
            (bdc.CONTROL_MUST_RESTART, bdc.CONTROL_MUST_NOT_RESTART,
             bdc.FALSE_POSITIVE_OF_100) = saved


class TestTruncationIsRecognisedInAllThreeDayConventions(unittest.TestCase):
    """Defect 4: the conventions sit one apart, and missing one fails toward CARRY."""

    def test_returns_series_half_is_a_restart(self):
        res = bdc.classify(_tape(decision=[("trailing_drawdown", 370)]), FACTS, True, "", False)
        self.assertEqual(res["verdict"], "RESTART")

    def test_weight_history_half_is_a_restart(self):
        # n−1: `mh._weights` is built over `range(1, len(dates))`.
        res = bdc.classify(_tape(decision=[("_gross_and_turnover", 369)]), FACTS, True, "",
                           False)
        self.assertEqual(res["verdict"], "RESTART")

    def test_equity_path_half_is_a_restart(self):
        # n+1: `_equity` carries the opening 1.0. This is the convention that hid
        # edge_overlay_domain_admissibility — a control #100 DECLARED — at 371 against 370.
        res = bdc.classify(_tape(decision=[("guarded_path", 371)]), FACTS, True, "", False)
        self.assertEqual(res["verdict"], "RESTART")

    def test_a_full_history_equity_path_is_not_a_truncation(self):
        """The other direction, and it must hold: widening by ±1 must not swallow full lengths.

        Without this the guard above would 'pass' by calling everything a RESTART.
        """
        for n in (FACTS["full"] - 1, FACTS["full"], FACTS["full"] + 1):
            res = bdc.classify(_tape(decision=[("guarded_path", n)]), FACTS, True, "", False)
            self.assertEqual(res["verdict"], "CARRY", f"length {n} is a full history")


    def test_a_near_degenerate_boundary_does_not_turn_a_full_history_into_a_half(self):
        """On the real panel (852/482/370) the full-length exclusion is a NO-OP — the widened
        halves and the full lengths do not overlap, so a mutation removing it survived.

        It stops being a no-op the moment a boundary sits within a day of the end, which is a
        legal boundary of the grid (#100 §6 already runs four of them). There, `train + 1`
        collides with `full`, and without the exclusion a FULL-history operator would be read as
        a truncation — a RESTART finding manufactured out of nothing.
        """
        degenerate = {"full": 852, "train": 851, "test": 1}
        res = bdc.classify(_tape(decision=[("guarded_path", 852)]), degenerate, True, "", False)
        self.assertEqual(res["verdict"], "CARRY",
                         "a full-history path must never be read as a boundary half")


class TestStateCarryingProbeMeasuresRatherThanNames(unittest.TestCase):
    """Defect 3/6: the property is measured, and the probe may not run a whole harness."""

    def test_a_stateful_operator_is_detected(self):
        def hwm(returns):
            out, eq, peak = [], 1.0, 1.0
            for r in returns:
                out.append(eq / peak - 1.0)
                eq *= 1.0 + r
                peak = max(peak, eq)
            return out

        self.assertIs(bdc._carries_state(hwm), True)

    def test_a_stateless_operator_is_not_flagged(self):
        self.assertIs(bdc._carries_state(lambda returns: [r * 2 for r in returns]), False)

    def test_an_unprobeable_operator_returns_none_and_is_never_called_stateless(self):
        def needs_more(returns, lookback):
            return [returns[0]] * lookback

        self.assertIsNone(bdc._carries_state(needs_more))

    def test_entrypoint_shaped_names_are_never_probed(self):
        """Defect 6: probing `run_idea80()` runs a harness. The process reached 4 GB before it
        was killed, so the refusal to probe is part of the instrument, not a nicety."""
        for name in ("run_idea80", "main", "section3_oos", "load_clean_panel"):
            node = ast.parse(f"def {name}(returns): pass").body[0]
            self.assertFalse(bdc._probeable_signature(node), name)

    def test_only_a_declared_series_call_is_probeable(self):
        yes = ast.parse("def f(returns, lookback=10): pass").body[0]
        no = ast.parse("def f(config, returns): pass").body[0]
        self.assertTrue(bdc._probeable_signature(yes))
        self.assertFalse(bdc._probeable_signature(no))

    def test_a_panel_operator_is_probeable_with_its_two_required_arguments(self):
        node = ast.parse("def capped_bh(book_rets, live, *, cap, cost): pass").body[0]
        self.assertTrue(bdc._probeable_signature(node))
        self.assertEqual(bdc._probe_kind(node), "panel")
        self.assertEqual(bdc._required_kwonly(node), {"cap": 0.20, "cost": 0.0})


class TestTheObserverIsNotPartOfItsOwnPopulation(unittest.TestCase):
    """Defect 1: caught by this file's own control on its first run."""

    def test_the_mirror_drops_exactly_this_file(self):
        with bdc.corpus_without_self(SCRIPTS) as mirror:
            mirrored = {p.name for p in Path(mirror).glob("edge_*.py")}
        originals = {p.name for p in SCRIPTS.glob("edge_*.py")}
        self.assertEqual(originals - mirrored, {Path(bdc.__file__).name})

    def test_the_mirror_refuses_when_it_cannot_account_for_its_own_removal(self):
        """Run against a corpus that does NOT contain this file and the count must refuse.

        This is the reachable failure of that assertion: the census may legitimately be pointed
        at another tree, and there the observer's absence means the population is not the one
        the verdict is defined against.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "edge_unrelated.py").write_text("x = 1\n", encoding="utf-8")
            with self.assertRaises(bdc.ControlFailed):
                with bdc.corpus_without_self(Path(tmp)):
                    pass

    def test_section0_refuses_on_a_corpus_that_is_not_the_one_100_screened(self):
        """§0 must REFUSE on a foreign corpus, and the refusal is checked by what actually speaks.

        MEASURED, and worth stating plainly: bdc's own population check (`population != 34`) and
        its bucket-size checks survive mutation, and this test is why. `spd.section1_census`
        runs ITS controls before returning, and on any corpus where bdc's counts would differ,
        spd has already refused — so bdc's counts are defence in depth that no reachable input
        can exercise alone. They are kept (the corpus can change while spd's controls still
        pass, e.g. a 35th module that screens correctly) but they are not claimed as tested.
        Asserting a specific message here would only pin which of two guards happens to be
        first, which is not a property worth freezing.
        """
        import tempfile

        import edge_split_protocol_diagnostic as spd

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "edge_unrelated.py").write_text('B = "2025-06-30"\n', encoding="utf-8")
            (Path(tmp) / Path(bdc.__file__).name).symlink_to(Path(bdc.__file__).resolve())
            with self.assertRaises((bdc.ControlFailed, spd.ControlFailed)):
                bdc.section0_controls(Path(tmp))

    def test_the_census_screens_the_population_100_published(self):
        """If this reddens, the corpus moved and #103's numbers must be re-derived — which is
        the point: the remainder is defined against a population, not in the abstract.

        RE-DERIVED 2026-09-11 (cycle `rnd-edge-105`), 34 -> 35 and RE-RUNS 5 -> 6, and the change
        is DELIBERATE under invariant #16 — journal `docs/journal/2026-W37.md` carries it.
        Registry entry #105 added `scripts/edge_downside_parity.py`, which splits TRAIN/TEST by
        an INDEXED slice (`rets[b][:n_train]`, `rets[b][n_train:]`) and re-runs each scheme from
        scratch on the half — so RE-RUNS is where the screen SHOULD put it, and the numbers were
        re-derived by running `spd.section1_census` over the corpus, not adjusted until green.
        The sibling test above anticipated exactly this case in writing ("a 35th module that
        screens correctly"). Note what did NOT move: the 21-module remainder #103's verdict is
        about is unchanged, so no published claim of #103 is disturbed by this edit — the new
        module is a 35th member of the population, not a 22nd member of the remainder.

        What this test must NEVER become is a number nudged to match whatever the corpus happens
        to hold: a new module that screens into RE-RUNS is a new ADDRESS for the #103 order, and
        re-deriving here without saying so would retire that address silently.
        """
        import contextlib
        import io

        import edge_split_protocol_diagnostic as spd

        with bdc.corpus_without_self(SCRIPTS) as mirror:
            with contextlib.redirect_stdout(io.StringIO()):
                census = spd.section1_census(Path(mirror))
        self.assertEqual(census["population"], 35)
        buckets = {k: len(v) for k, v in census["buckets"].items()}
        self.assertEqual(buckets["BOUNDARY USED, BUT NEVER AS A SLICE INDEX"], 21)
        self.assertEqual(buckets["RE-RUNS ON THE SLICE"], 6)
        self.assertIn("edge_downside_parity.py",
                      [Path(m).name for m in census["buckets"]["RE-RUNS ON THE SLICE"]],
                      "the 35th module must be the one that was ADDED, not some other module "
                      "that quietly changed bucket while the totals happened to add up")


class TestDayExtentIsMeasuredNotAssumedFromTheFirstArgument(unittest.TestCase):
    """Defect 5: for a panel operator, `len(args[0])` is the BOOK count."""

    def test_a_dict_of_series_reports_days_not_books(self):
        """Exercises the REAL tape, not a copy of its arithmetic.

        A test that re-implemented `day_extents` inline would pass while the shipped wrapper
        stayed broken — the shape this branch calls "сторож, сверяющий КОПИИ".
        """
        import types

        mod = types.ModuleType("edge_fake_panel_family")
        calls = []

        def capped_bh(book_rets, live):
            calls.append(len(live))
            return [0.0] * len(next(iter(book_rets.values())))

        mod.capped_bh = capped_bh
        sys.modules["edge_fake_panel_family"] = mod
        try:
            tape = bdc.OperatorTape()
            with bdc.taped(tape, {"edge_fake_panel_family": {"capped_bh": "decision"}}):
                books = {f"b{i}": [0.0] * 370 for i in range(8)}
                mod.capped_bh(books, sorted(books))
            self.assertEqual(calls, [8], "the operator itself must still run")
            lengths = tape.lengths("decision")
            self.assertIn(370, lengths, "the DAY count must be recorded")
            # And the verdict that follows from it is the one that matters.
            res = bdc.classify(tape, FACTS, True, "", False)
            self.assertEqual(res["verdict"], "RESTART")
        finally:
            sys.modules.pop("edge_fake_panel_family", None)

    def test_the_day_series_is_found_when_it_is_not_the_first_argument(self):
        """`len(args[0])` survived a mutation because the corpus call this suite used happens to
        put the panel first. The tape's claim is broader — it reads the day extent of EVERY
        argument — and the broader claim is what the corpus needs (`_gross_and_turnover(hist,
        book_rets)`, keyword-passed series), so it is pinned here.
        """
        import types

        mod = types.ModuleType("edge_fake_second_arg")
        mod.overlay = lambda flags, returns: list(returns)
        sys.modules["edge_fake_second_arg"] = mod
        try:
            tape = bdc.OperatorTape()
            with bdc.taped(tape, {"edge_fake_second_arg": {"overlay": "decision"}}):
                mod.overlay([True, False], returns=[0.0] * 370)
            self.assertIn(370, tape.lengths("decision"))
            self.assertEqual(bdc.classify(tape, FACTS, True, "", False)["verdict"], "RESTART")
        finally:
            sys.modules.pop("edge_fake_second_arg", None)

    def test_the_wrapper_restores_the_original_after_the_run(self):
        """A tape that leaked its wrappers would poison every later module's measurement."""
        import types

        mod = types.ModuleType("edge_fake_restore")
        original = lambda returns: list(returns)          # noqa: E731
        mod.trailing_x = original
        sys.modules["edge_fake_restore"] = mod
        try:
            with bdc.taped(bdc.OperatorTape(), {"edge_fake_restore": {"trailing_x": "decision"}}):
                self.assertIsNot(mod.trailing_x, original)
            self.assertIs(mod.trailing_x, original)
        finally:
            sys.modules.pop("edge_fake_restore", None)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
