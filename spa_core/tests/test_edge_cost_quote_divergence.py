"""Acceptance for scripts/edge_cost_quote_divergence.py — registry idea CQD.

Every test is a POSITIVE CONTROL and names, in its docstring, the defect it goes red on.

Four of them replay defects THIS entry hit while it was being written, which is the only
reason to trust the rest:
  · the first run raised `ZeroDivisionError` deep inside a scan on a wiped-out path — ruin
    was not a verdict, it was a crash;
  · a book with NO drawdown (`lp_eth_stable`) was reported as "never beats", i.e. an
    UNDEFINED comparison printed as an unfavourable one;
  · a book the guardian never touches was about to be reported the same way, though there
    the toll is irrelevant by construction;
  · four books with NEGATIVE raw Calmar produced "higher Calmar" numbers that would have
    been quoted as the overlay helping. A shallower path to the same loss is not help.

The panel is read READ-ONLY and panel-bound checks skip LOUDLY when it is absent. Nothing
here moves capital, touches RiskPolicy v1.0, the live track, the fleet or the dashboard.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_cost_quote_divergence as cqd  # noqa: E402
import edge_gross_to_net_toll as gtn  # noqa: E402
import edge_mhfc_backtest as mh  # noqa: E402

from spa_core.strategy_lab.swarm import guardian_forward as gf  # noqa: E402

needs_panel = unittest.skipUnless(
    gtn.PANEL_DIR.exists(),
    f"aggressive-lab panel absent at {gtn.PANEL_DIR} — this tree is not the prod tree; "
    f"set SPA_PANEL_DIR to run the panel-bound checks",
)


class TestTheCensusIsRead(unittest.TestCase):
    def test_the_deployed_toll_comes_from_the_organ_not_from_this_file(self):
        """POSITIVE CONTROL: move the organ's constant, the census must follow.

        Defect it guards: an entry that describes an organ it copied instead of read. The
        whole subject of CQD is numbers that drifted apart while every document still quoted
        the old one; a census with the same disease would be worthless.
        """
        real = gf.GUARDIAN_PARAMS["roundtrip_cost"]
        gf.GUARDIAN_PARAMS["roundtrip_cost"] = 0.0077
        try:
            got = {n: v for n, v, _r, _p in cqd.census()}
            self.assertAlmostEqual(got["guardian_forward roundtrip_cost"], 77.0, places=6)
        finally:
            gf.GUARDIAN_PARAMS["roundtrip_cost"] = real

    def test_the_three_conventions_are_all_on_the_same_axis(self):
        """Gas must stay OUT of the census: dollars per leg is a different dimension.

        Defect it guards: a "spread" computed across incommensurable units, which would make
        the headline number meaningless while looking more dramatic.
        """
        names = [n for n, _v, _r, _p in cqd.census()]
        self.assertFalse([n for n in names if "GAS" in n.upper()])
        self.assertEqual(len(names), 3)

    def test_the_spread_is_computed_not_quoted(self):
        """POSITIVE CONTROL: change a constant, the spread must move.

        Defect it guards: a headline "12×" frozen into prose. The entry's whole claim is
        about numbers that stopped matching their descriptions.
        """
        real = gf.GUARDIAN_PARAMS["roundtrip_cost"]
        gf.GUARDIAN_PARAMS["roundtrip_cost"] = 0.0001  # 1 bp — now the narrowest
        try:
            self.assertAlmostEqual(cqd.convention_spread(), 96.0, places=6)
        finally:
            gf.GUARDIAN_PARAMS["roundtrip_cost"] = real


class TestTheOutcomesThatAreNotNumbers(unittest.TestCase):
    """Five distinct reasons a break-even does not exist. They must not collapse."""

    def _params(self):
        return {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}

    def test_ruin_raises_a_named_exception_and_never_divides_by_zero(self):
        """POSITIVE CONTROL replaying the first run's crash.

        Defect it guards: `ZeroDivisionError` from a wiped-out path, raised deep inside a
        scan where the cause is invisible. #91 already paid for this family once: `mh._apy`
        clips a wipeout to APY 0, so ruin silently outranks a merely losing arm.
        """
        with self.assertRaises(cqd.Ruin):
            cqd._rets([1.0, 0.5, 0.0, 0.0])

    def test_a_book_with_no_drawdown_is_not_reported_as_never_beats(self):
        """POSITIVE CONTROL replaying this entry's second defect, seen on lp_eth_stable.

        Defect it guards: an UNDEFINED comparison (raw Calmar is infinite when maxDD is zero)
        printed as an UNFAVOURABLE one. The overlay was never given a chance to lose; saying
        it lost is a fabricated verdict, and it is exactly the class this tree keeps paying
        for — "not measured" rendered identically to "measured and bad".
        """
        eq = [1.0 * (1.001 ** i) for i in range(400)]  # monotone: no drawdown at all
        verdict, raw, _a0 = cqd.guardian_cstar(eq, **self._params())
        self.assertEqual(verdict, "no DD")
        self.assertNotEqual(verdict, "never beats")

    def test_every_non_numeric_verdict_carries_its_own_reason(self):
        """The five verdicts are five different facts and each must say which.

        Defect it guards: a table that folds "the question does not arise here" into "the
        overlay is not worth its toll". Only the second is a finding.
        """
        self.assertEqual(
            set(cqd.NO_CSTAR),
            {"dead", "never fires", "no DD", "ruin", "never beats"},
        )
        self.assertTrue(all(v and len(v) > 20 for v in cqd.NO_CSTAR.values()))

    def test_a_losing_book_is_not_comparable_however_flattering_its_calmar(self):
        """POSITIVE CONTROL: negative raw Calmar must be excluded from every claim.

        Defect it guards: quoting "guarded Calmar −0.15 → +0.09" as the overlay helping. On a
        book that loses money, a higher Calmar can be a shallower path to the same loss or a
        shrinking denominator; four of the ten books on this panel are in exactly that state
        and every one of them would have been counted.
        """
        self.assertFalse(cqd.comparable(-0.15, -4.6))
        self.assertFalse(cqd.comparable(2.0, -1.0))
        self.assertFalse(cqd.comparable(float("nan"), 5.0))
        self.assertTrue(cqd.comparable(3.88, 74.1))

    def test_a_dead_book_is_absent_and_not_neutral(self):
        """A flat series is missing data, not a null result.

        Defect it guards: four books with no 2026 data reading as "the guardian did nothing",
        which would put an absence and a measurement in the same column.
        """
        self.assertTrue(cqd.is_dead([0.0] * 500))
        self.assertFalse(cqd.is_dead([0.0] * 499 + [0.01]))


class TestTheBreakEvenItself(unittest.TestCase):
    def _params(self):
        return {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}

    def test_the_switch_count_is_differenced_from_the_organ_not_reimplemented(self):
        """POSITIVE CONTROL: a series the guardian cannot fire on must count zero switches.

        Defect it guards: a re-implemented trigger that drifts from the deployed one. The
        entry's whole comparison turns on this number, so it is measured by running the organ
        twice and differencing, never by rewriting its rule.
        """
        eq = [1.0 * (1.0001 ** i) for i in range(400)]  # smooth: no vol spike, no fire
        self.assertEqual(cqd.switches_per_year(eq, 399, **self._params()), 0.0)

    def test_c_star_is_a_scored_rung_and_the_next_one_fails(self):
        """c* must be observed, never interpolated.

        Defect it guards: a bisected midpoint published as a measurement — the branch's
        standing rule since #90 is that an edge quoted is an edge that was scored.
        """
        import random

        rnd = random.Random(20260901)
        rets = [rnd.gauss(0.0009, 0.004) for _ in range(600)]
        rets[300:315] = [-0.05] * 15  # a vol spike the guardian can actually see
        eq = cqd._equity(rets)
        c, raw, _a0 = cqd.guardian_cstar(eq, **self._params())
        if isinstance(c, str):
            self.skipTest(f"this synthetic series yields '{c}', not a break-even")
        from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol

        at = mh._calmar(cqd._rets(apply_guardian_vol(eq, roundtrip_cost=c / 1e4, **self._params())))
        nxt = mh._calmar(cqd._rets(apply_guardian_vol(eq, roundtrip_cost=(c + 1) / 1e4,
                                                      **self._params())))
        self.assertGreater(at, raw)
        self.assertLessEqual(nxt, raw)


class TestAdvisoryContainment(unittest.TestCase):
    def test_flags_are_declared(self):
        self.assertTrue(cqd.IS_ADVISORY)
        self.assertTrue(cqd.OUTSIDE_RISKPOLICY)
        self.assertEqual(cqd.EVIDENCE_LEVEL, "L0")

    def test_the_harness_never_reaches_the_execution_domain(self):
        """Checked by PARSING, not grepping — the header names the domain in prose."""
        import ast as pyast

        src = (ROOT / "scripts" / "edge_cost_quote_divergence.py").read_text()
        names = set()
        for node in pyast.walk(pyast.parse(src)):
            if isinstance(node, pyast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, pyast.ImportFrom) and node.module:
                names.add(node.module)
        self.assertFalse([n for n in names if n.startswith("spa_core.execution")])

    def test_the_harness_only_reads(self):
        """POSITIVE CONTROL against the sharpest hazard of touching a LIVE organ's module:
        this file imports `guardian_forward`, which owns state the fleet writes hourly.

        Defect it guards: a research script that calls the organ's writer while measuring it,
        and thereby stamps a backtest onto a live advisory artefact.
        """
        import ast as pyast

        src = (ROOT / "scripts" / "edge_cost_quote_divergence.py").read_text()
        writes = [n for n in pyast.walk(pyast.parse(src))
                  if isinstance(n, pyast.Call) and isinstance(n.func, pyast.Attribute)
                  and n.func.attr in ("write_text", "write_bytes", "dump", "atomic_save",
                                      "run_once", "main")]
        self.assertEqual(writes, [], "the harness writes or drives something; it must only read")


class TestOnTheRealPanel(unittest.TestCase):
    @needs_panel
    def test_the_entry_runs_and_the_headline_books_keep_their_verdicts(self):
        """The published numbers must be reproducible from the script.

        Defect it guards: an entry whose table cannot be re-derived — the registry's own
        recurring failure, where a number outlives the run that produced it.
        """
        dates, book_rets = gtn.load_real_panel()
        params = {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}
        c_pt, raw_pt, _ = cqd.guardian_cstar(cqd._equity(book_rets["pendle_pt_levered"]), **params)
        c_ss, raw_ss, _ = cqd.guardian_cstar(cqd._equity(book_rets["susde_spot"]), **params)
        self.assertEqual(c_pt, 69)
        self.assertEqual(c_ss, 14)
        # and the deployed toll sits ABOVE susde_spot's break-even — the entry's sharpest cell
        self.assertGreater(cqd.DEPLOYED_BPS, c_ss)


if __name__ == "__main__":
    unittest.main()
