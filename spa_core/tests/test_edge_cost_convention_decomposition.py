"""Acceptance for scripts/edge_cost_convention_decomposition.py — registry idea CVD.

Every test here is a POSITIVE CONTROL: it goes red if a specific, nameable defect is put
back, and each one carries that defect in its docstring. A check that has never seen a real
breakage is an ornament.

Three of them replay defects this very entry nearly shipped:
  · the instrument reader was first written to assert "all three logs are EMPTY". They are
    not. It now DESCRIBES what it read, and `test_content_reader_measures_rather_than_recites`
    is the check that keeps it a reading;
  · `absent` and `0 rows` were about to print alike, which is the older class of defect the
    tree already paid for once (a worktree has no `data/` by construction, and "nothing
    there" is not "nothing happened");
  · the demo-row trace was going to match a remembered string. It reads the producer's
    SOURCE, and the control below proves the difference.

The panel is read READ-ONLY; the panel-bound checks skip LOUDLY when it is absent (a
worktree has no `data/aggressive_lab`). Nothing here moves capital, touches RiskPolicy v1.0,
the live track, the fleet or the dashboard.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_aum_scaled_toll as ast  # noqa: E402
import edge_cost_convention_decomposition as cvd  # noqa: E402
import edge_cost_signal_separation as css  # noqa: E402
import edge_gross_to_net_toll as gtn  # noqa: E402
import edge_turnover_cost_breakeven as tcb  # noqa: E402

PANEL_DIR = gtn.PANEL_DIR

needs_panel = unittest.skipUnless(
    PANEL_DIR.exists(),
    f"aggressive-lab panel absent at {PANEL_DIR} — this tree is not the prod tree; "
    f"set SPA_PANEL_DIR to run the panel-bound checks",
)


class TestTheProvenanceIsMeasured(unittest.TestCase):
    """Section 0 must READ the sources it describes, not recite them."""

    def test_the_two_turnover_definitions_differ_by_exactly_two(self):
        """#10 charges 0.5·Σ|Δw|; #80–#91 charge Σ|Δw| and then apply #10's number to it.

        This is the whole load-bearing claim of the entry: the branch's standing convention
        is applied at TWICE its own definition, so "96" in this harness means 192 in the
        units the 96 was measured in.

        Defect it guards: somebody harmonises one side and not the other, or "fixes" the
        ratio by editing this file. Either way the registry entry's central number stops
        being true and this test is where that surfaces.
        """
        self.assertEqual(cvd.measure_turnover_definition_ratio(), 2.0)

    def test_the_ratio_is_measured_and_not_a_literal_two(self):
        """POSITIVE CONTROL for the test above: sabotage #10's ½ and the ratio must MOVE.

        Defect it guards: the seductive shortcut of `return 2.0` with a comment. A function
        that returns a constant passes the test above forever, including after the two
        definitions are harmonised and the finding has expired.
        """
        real = tcb._replay_with_cost

        def no_half(dates, weights, r_s, r_r, r_w, cost_bps):
            eq, out, prev, n, total = 100_000.0, [100_000.0], tcb.WEIGHTS_CRUISE, 0, 0.0
            for i, d in enumerate(dates):
                w = weights[i]
                if w != prev:
                    total += sum(abs(w[j] - prev[j]) for j in range(3))  # the ½ removed
                    n += 1
                prev = w
                out.append(eq)
            return out, n, total

        tcb._replay_with_cost = no_half
        try:
            self.assertEqual(cvd.measure_turnover_definition_ratio(), 1.0)
        finally:
            tcb._replay_with_cost = real

    def test_the_convention_still_lives_where_the_entry_says_it_lives(self):
        """96 is read from #80's module, not restated here.

        Defect it guards: the entry quoting a number that has since moved in the source —
        the exact failure mode of the convention it is about.
        """
        self.assertEqual(css.CONVENTION_COST, 96)
        self.assertEqual(cvd.CANDIDATES[-1][1], float(css.CONVENTION_COST))

    def test_cost_model_is_read_from_the_module_not_copied_into_this_file(self):
        """POSITIVE CONTROL: move the constant in the module, the reader must follow.

        Defect it guards: a decomposition table that quotes 8 bps from a docstring while
        `cost_model.py` runs on something else. Comparing two copies of a literal is blind
        to precisely the drift the section exists to catch.
        """
        from spa_core.backtesting.tier1 import cost_model as cm

        real = cm.SLIPPAGE_BPS_STABLE
        cm.SLIPPAGE_BPS_STABLE = 4321.0
        try:
            self.assertEqual(cvd.read_tree_cost_model()["slippage_bps_stable"], 4321.0)
        finally:
            cm.SLIPPAGE_BPS_STABLE = real
        self.assertEqual(cvd.read_tree_cost_model()["slippage_bps_stable"], real)

    def test_the_tree_cost_model_has_no_pool_fee_line(self):
        """The claim "the model has no fee line at all" is checked against the module.

        Defect it guards: the entry asserting an absence that somebody has since filled —
        an absence is the easiest thing in a document to leave standing after it is false.
        """
        from spa_core.backtesting.tier1 import cost_model as cm

        names = {n.lower() for n in dir(cm) if n.isupper()}
        self.assertFalse(
            [n for n in names if "fee" in n],
            "cost_model.py now has a fee constant — the CVD entry's §0 must be revisited",
        )


class TestTheInstrumentReaderReads(unittest.TestCase):
    """The three logs named for these costs, described rather than assumed."""

    def _tmp(self, files):
        d = Path(tempfile.mkdtemp())
        for name, payload in files.items():
            (d / name).write_text(json.dumps(payload))
        return d

    def test_absent_is_reported_as_absent_and_never_as_empty(self):
        """A tree with no `data/` must not read like a tree with empty logs.

        Defect it guards: the tree's own recurring class — "not measured" printed
        identically to "measured and found nothing". A worktree has no `data/` BY
        CONSTRUCTION; if that renders as "0 rows", the entry silently claims a reading it
        never took.
        """
        got = cvd.read_instrument_content(Path(tempfile.mkdtemp()))
        for k, v in got.items():
            self.assertIn("absent", v, f"{k} did not say absent")
            self.assertNotIn("0 rows", v)

    def test_present_but_empty_is_reported_as_rows_and_never_as_absent(self):
        """The other side of the same coin, so the two verdicts cannot collapse.

        Defect it guards: an `except` that turns any unreadable state into "absent" and
        thereby hides a log that exists and is empty — a different fact with a different fix.
        """
        d = self._tmp({
            "fee_structure_log.json": [],
            "slippage_impact_log.json": [],
            "gas_cost_breakeven_log.json": [],
        })
        got = cvd.read_instrument_content(d)
        for k, v in got.items():
            self.assertIn("0 rows", v, f"{k} did not say 0 rows")
            self.assertNotIn("absent", v)

    def test_content_reader_measures_rather_than_recites(self):
        """POSITIVE CONTROL replaying THIS entry's own near-miss: the reader was first
        written to claim all three logs were empty. They are not — six rows carry a rate.

        Defect it guards: a section that describes data it did not open. Feed it a rate it
        has never seen and the output must change.
        """
        d = self._tmp({
            "fee_structure_log.json": [
                {"avg_effective_rate": 0.05, "total_revenue_30d": 7.0,
                 "cheapest": "Curve", "most_expensive": "Curve"}],
            "slippage_impact_log.json": [{"total_trades": 9, "order_size_usd": 1000}],
            "gas_cost_breakeven_log.json": [{"name": "real-fill", "flags": []}],
        })
        got = cvd.read_instrument_content(d)
        self.assertIn("0.05", got["fee_structure_log"])
        self.assertIn("Curve", got["fee_structure_log"])
        self.assertIn("1 with a size axis", got["slippage_impact_log"])
        self.assertIn("real-fill", got["gas_cost_breakeven_log"])

    def test_demo_trace_reads_the_producer_source_not_a_remembered_string(self):
        """POSITIVE CONTROL: a row whose name is NOT in the producer's demo must not match.

        Defect it guards: hard-coding the two demo names into the check. That version would
        report "all rows are demos" for a log that had since filled with real fills — the
        finding would outlive its own truth, which is the failure this whole entry is about.
        """
        d = self._tmp({"gas_cost_breakeven_log.json": [
            {"name": "USDC-LP (small, expensive)", "flags": []},
            {"name": "a-name-no-demo-block-contains", "flags": []},
            {"name": "irrelevant", "flags": ["INSUFFICIENT_DATA"]},
        ]})
        usable, hits = cvd.demo_rows_trace_to_producer(d)
        self.assertEqual(usable, 2)
        self.assertEqual(hits, 1)

    def test_demo_trace_refuses_quietly_when_the_producer_is_gone(self):
        """No producer source ⇒ (0, 0), never a confident count.

        Defect it guards: a missing analyser file silently yielding "0 of 0 are demos",
        which reads as "the log is clean" — a fail-OPEN verdict on an unread instrument.
        """
        real = cvd.GAS_ANALYSER
        cvd.GAS_ANALYSER = Path("/nonexistent/analyser.py")
        try:
            d = self._tmp({"gas_cost_breakeven_log.json": [{"name": "x", "flags": []}]})
            self.assertEqual(cvd.demo_rows_trace_to_producer(d), (0, 0))
        finally:
            cvd.GAS_ANALYSER = real


class TestTheCrossingSummary(unittest.TestCase):
    """One number per cell is only honest when the profile crosses once."""

    def test_a_clean_profile_is_single(self):
        self.assertTrue(cvd.single_crossing([True, True, True, False, False]))

    def test_an_all_negative_profile_is_single(self):
        self.assertTrue(cvd.single_crossing([False, False, False]))

    def test_a_profile_that_comes_back_is_not_single(self):
        """POSITIVE CONTROL: dip negative, return positive, go negative — two flips.

        Defect it guards: summarising such a profile as one c* without saying so. The
        highest positive rung would then be quoted as "the affordable toll" when tolls
        BELOW it are unaffordable — a number that is not merely imprecise but backwards.
        """
        self.assertFalse(cvd.single_crossing([True, False, True, False]))

    def test_the_scan_reports_the_flag_it_computes(self):
        """The scan must carry the flag out, not compute and drop it.

        Defect it guards: a `single` field that is always True because nothing ever writes
        it — the classic ornament, green from the day it was added.
        """
        self.assertIn("single", cvd.Crossing.__slots__)


class TestAffordableTollAlgebra(unittest.TestCase):
    """c* on a hand-made series, so the arithmetic is checkable by eye."""

    def _flat(self, n=400):
        """An arm that earns a steady 10 bps/day and turns over 1.0 of book each day."""
        gross = [0.001] * n
        flows = [{"leg": 1.0}] * n
        return gross, flows, flows

    def test_c_star_is_a_scored_rung_with_the_next_rung_losing(self):
        """c* must be positive at c*, non-positive at c*+1 — measured, not interpolated.

        Defect it guards: reporting a bisected midpoint as if it were observed. The branch's
        rule is that a published edge is a rung that was actually scored.
        """
        gross, chg, tch = self._flat()
        x = cvd.affordable_cvar(gross, chg, tch, 0.0, aum=1e9,
                                gas_per_leg=0.0, depth=float("inf"))
        self.assertIsNotNone(x.c_star)
        lo = ast.score_at(gross, chg, tch, 0.0, aum=1e9, c_var_bps=float(x.c_star),
                          gas_per_leg=0.0, depth=float("inf")).dcalmar
        hi = ast.score_at(gross, chg, tch, 0.0, aum=1e9, c_var_bps=float(x.c_star + 1),
                          gas_per_leg=0.0, depth=float("inf")).dcalmar
        self.assertGreater(lo, 0.0)
        self.assertLessEqual(hi, 0.0)

    def test_an_arm_that_loses_for_free_reports_none_and_not_zero(self):
        """`loses at 0` and `c* = 0` are different facts and must not print alike.

        Defect it guards: the collapse of "no fee can save it" into "it can afford a fee of
        zero". The first says the branch is dead at this size; the second says it is exactly
        marginal. An owner reading the table would act differently on each.
        """
        gross = [-0.001] * 300
        flows = [{"leg": 1.0}] * 300
        x = cvd.affordable_cvar(gross, flows, flows, 0.0, aum=1e9,
                                gas_per_leg=0.0, depth=float("inf"))
        self.assertIsNone(x.c_star)
        self.assertEqual(cvd._fmt_c(x), "loses at 0")

    def test_gas_alone_can_close_the_window_with_no_toll_at_all(self):
        """The floor of #91 must still be reachable through this file's scan.

        Defect it guards: a scan that starts at c=0 but forgets to charge the SIZE terms,
        so every cell looks affordable. Same series, same everything, only AUM shrinks —
        and it must flip from affordable to `loses at 0`.
        """
        gross, chg, tch = self._flat()
        big = cvd.affordable_cvar(gross, chg, tch, 0.0, aum=1e9,
                                  gas_per_leg=12.0, depth=float("inf"))
        small = cvd.affordable_cvar(gross, chg, tch, 0.0, aum=1e2,
                                    gas_per_leg=12.0, depth=float("inf"))
        self.assertIsNotNone(big.c_star)
        self.assertIsNone(small.c_star)


class TestTheInvoiceIsStillNinetyOnes(unittest.TestCase):
    """Nothing here may be set beside #91's verdict unless it was scored on #91's invoice."""

    @needs_panel
    def test_the_six_published_anchors_reproduce(self):
        """#91's own section-4 table, re-derived cell for cell.

        Defect it guards: a silent edit anywhere in the imported chain (#79 weights, #80
        turnover, #83 leg table, #91 impact). Every import would still resolve and every
        number would move — which is exactly how two registry entries start describing
        different experiments under one branch heading.
        """
        dates, book_rets = gtn.load_real_panel()
        built, _ = ast.build(dates, book_rets)
        eq_g, eq_c, eq_t, _ = built["eq"]
        import edge_mhfc_backtest as mh

        base = mh._calmar(ast.aum_net(eq_g, eq_c, eq_t, aum=cvd.AUM_LADDER[0],
                                      c_var_bps=0.0, gas_per_leg=ast.GAS_MODEL_CONSTANT,
                                      depth=cvd.DEPTH_LADDER[0]))
        rows = cvd.check_ast_anchors(built, base)
        self.assertEqual(len(rows), len(cvd.AST_PUBLISHED_ANCHORS))
        for _a, _c, _g, _d, published, got in rows:
            self.assertAlmostEqual(published, got, places=2)

    @needs_panel
    def test_a_moved_anchor_refuses_loudly(self):
        """POSITIVE CONTROL: hand the checker an anchor that is wrong on purpose.

        Defect it guards: a comparison that logs a warning and carries on. The branch's rule
        is fail-CLOSED — a harness that cannot prove it is running #91's invoice must not
        publish a table that will be read against #91's verdict.
        """
        dates, book_rets = gtn.load_real_panel()
        built, _ = ast.build(dates, book_rets)
        eq_g, eq_c, eq_t, _ = built["eq"]
        import edge_mhfc_backtest as mh

        base = mh._calmar(ast.aum_net(eq_g, eq_c, eq_t, aum=cvd.AUM_LADDER[0],
                                      c_var_bps=0.0, gas_per_leg=ast.GAS_MODEL_CONSTANT,
                                      depth=cvd.DEPTH_LADDER[0]))
        bogus = (((1e5, 0.0, ast.GAS_MODEL_CONSTANT, 1e8), +99.0),)
        with self.assertRaises(RuntimeError):
            cvd.check_ast_anchors(built, base, bogus)


class TestAdvisoryContainment(unittest.TestCase):
    """The entry is research. It must stay research."""

    def test_flags_are_declared(self):
        self.assertTrue(cvd.IS_ADVISORY)
        self.assertTrue(cvd.OUTSIDE_RISKPOLICY)
        self.assertEqual(cvd.EVIDENCE_LEVEL, "L0")

    def test_the_harness_never_reaches_the_execution_domain(self):
        """Read-only research must not import the execution package.

        Checked by PARSING the module, not by grepping its text. The first version of this
        test grepped, and went red on its own docstring — the entry names
        `spa_core.execution` in prose precisely to say it does not touch it. A guard that
        cannot tell code from the prose about the code will either be disabled or will start
        forbidding honest documentation; both are worse than no guard.

        Defect it guards: an import added for convenience that puts a backtest one call away
        from the money path.
        """
        import ast as pyast

        src = (ROOT / "scripts" / "edge_cost_convention_decomposition.py").read_text()
        tree = pyast.parse(src)
        names = set()
        for node in pyast.walk(tree):
            if isinstance(node, pyast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, pyast.ImportFrom) and node.module:
                names.add(node.module)
        self.assertFalse([n for n in names if n.startswith("spa_core.execution")],
                         f"execution-domain import found: {sorted(names)}")

    def test_the_prose_guard_can_still_tell_code_from_comment(self):
        """POSITIVE CONTROL for the parse above: a REAL import must be caught.

        Defect it guards: a parser walk that silently matches nothing (wrong node type, wrong
        attribute) and therefore passes for any module at all — an ornament that would greet
        the very import it exists to stop.
        """
        import ast as pyast

        tree = pyast.parse("# spa_core.execution in a comment\nfrom spa_core.execution import x\n")
        names = {n.module for n in pyast.walk(tree) if isinstance(n, pyast.ImportFrom) and n.module}
        self.assertIn("spa_core.execution", names)

    def test_the_harness_never_writes_the_live_track(self):
        """The live track file may be NAMED in the header and never opened.

        Defect it guards: the same prose/code confusion in the other direction — a real
        write to `data/equity_curve_daily.json` hidden behind a header that promises not to.
        """
        import ast as pyast

        src = (ROOT / "scripts" / "edge_cost_convention_decomposition.py").read_text()
        tree = pyast.parse(src)
        writes = [n for n in pyast.walk(tree)
                  if isinstance(n, pyast.Call) and isinstance(n.func, pyast.Attribute)
                  and n.func.attr in ("write_text", "write_bytes", "dump", "atomic_save")]
        self.assertEqual(writes, [], "the harness writes something; it must only read")

    def test_the_llm_marker_is_present(self):
        src = (ROOT / "scripts" / "edge_cost_convention_decomposition.py").read_text()
        self.assertIn("LLM_FORBIDDEN", src)


if __name__ == "__main__":
    unittest.main()
