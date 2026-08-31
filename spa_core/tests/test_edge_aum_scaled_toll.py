"""Acceptance for scripts/edge_aum_scaled_toll.py — registry idea AST (AUM-Scaled Toll).

Every test here is a POSITIVE CONTROL: it fails if a specific, nameable defect is put back.
A check that has never seen a real breakage is an ornament, so each one below carries the
defect it was written against in its docstring.

The panel is read READ-ONLY. Nothing here moves capital, touches RiskPolicy v1.0, the live
track, the fleet or the dashboard.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_aum_scaled_toll as ast  # noqa: E402
import edge_cost_signal_separation as css  # noqa: E402
import edge_gross_to_net_toll as gtn  # noqa: E402
import edge_mhfc_backtest as mh  # noqa: E402

PANEL_DIR = gtn.PANEL_DIR


def _panel_available() -> bool:
    return PANEL_DIR.exists()


needs_panel = unittest.skipUnless(
    _panel_available(),
    f"aggressive-lab panel absent at {PANEL_DIR} — this tree is not the prod tree; "
    f"set SPA_PANEL_DIR to run the panel-bound checks",
)


class TestInvoiceAlgebra(unittest.TestCase):
    """The cost model itself, with no panel involved."""

    def test_infinite_depth_charges_exactly_zero_impact(self):
        """The frictionless limit must be EXACTLY zero, not merely small.

        Defect it guards: a `1/(R+q)` written without an inf branch returns a denormal
        instead of 0.0, and the reduction to #80's published invoice stops being exact —
        which is how a harness silently starts disagreeing with the entry it cites.
        """
        day = {"eth": 0.4, "susde": 0.1}
        self.assertEqual(ast.impact_fraction(day, 1e6, float("inf")), 0.0)

    def test_constant_product_fill_is_the_textbook_one(self):
        """q = R must cost exactly q/2 dollars: slippage q/(q+R) = 1/2.

        Defect it guards: the small-q approximation q**2/R silently substituted for the
        exact q**2/(R+q). At q=R the two differ by a factor of two, and every cell above
        $10M would then overstate the toll without any test noticing.
        """
        aum, depth = 1e6, 5e5
        day = {"eth": 0.5}  # q = 0.5 * 1e6 = 5e5 = depth
        got = ast.impact_fraction(day, aum, depth) * aum
        self.assertAlmostEqual(got, 5e5 / 2.0, places=6)

    def test_impact_is_linear_in_capital_in_the_small_trade_regime(self):
        """10x the capital, 10x the drag — the CEILING side of the window.

        Defect it guards: dividing by AUM twice (or not at all). Either way the ceiling
        moves by decades and the table still looks plausible.
        """
        day = {"eth": 0.01}
        depth = 1e12  # far above q, so q**2/(R+q) ~ q**2/R
        a = ast.impact_fraction(day, 1e5, depth)
        b = ast.impact_fraction(day, 1e6, depth)
        self.assertAlmostEqual(b / a, 10.0, places=6)

    def test_gas_drag_scales_exactly_as_one_over_capital(self):
        """Halve the capital, double the gas drag — the FLOOR side of the window.

        Defect it guards: charging gas as a fraction of turnover instead of a fixed number
        of dollars. That is precisely the mistake the whole branch made by never charging
        it at all, and it erases the floor.
        """
        gross = [0.0, 0.0]
        chg = [{}, {"eth": 0.2}]
        tch = [{}, {"eth": 0.2, "stable_debt": 0.1}]
        kw = dict(c_var_bps=0.0, gas_per_leg=10.0, depth=float("inf"))
        hi = ast.aum_net(gross, chg, tch, aum=1e6, **kw)
        lo = ast.aum_net(gross, chg, tch, aum=5e5, **kw)
        self.assertAlmostEqual(hi[1], -20.0 / 1e6, places=12)
        self.assertAlmostEqual(lo[1] / hi[1], 2.0, places=9)

    def test_bundled_gas_is_never_more_expensive_than_per_leg(self):
        """The bracket must be ordered, or it is not a bracket.

        Defect it guards: `bundled_gas` reading the CHARGE table (δ=0, where a debt leg has
        been zeroed away) instead of the touch table, which can make the "optimistic" end
        the dearer one and quietly invert the floor.
        """
        gross = [0.0, 0.0, 0.0, 0.0]
        # day 3 is the case that decides it: under the δ=0 charge table the debt legs are
        # zeroed away, so a day on which ONLY borrowings move has an EMPTY charge vector and
        # a non-empty touch vector. A bundled counter reading the charge table would price
        # that day at zero gas — the day still costs two transactions.
        chg = [{}, {"eth": 0.2}, {"eth": 0.1, "susde": 0.1}, {}]
        tch = [{}, {"eth": 0.2, "eth_debt": 0.2}, {"eth": 0.1, "susde": 0.1},
               {"eth_debt": 0.3, "stable_debt": 0.2}]
        kw = dict(aum=1e5, c_var_bps=0.0, gas_per_leg=5.0, depth=float("inf"))
        per = ast.aum_net(gross, chg, tch, **kw)
        bun = ast.aum_net(gross, chg, tch, bundled_gas=True, **kw)
        for a, b in zip(per, bun):
            self.assertLessEqual(a, b + 1e-15)
        self.assertLess(per[1], bun[1])   # the two-leg day must actually differ
        self.assertAlmostEqual(bun[3], -5.0 / 1e5, places=12)
        self.assertAlmostEqual(per[3], -10.0 / 1e5, places=12)

    def test_fail_closed_on_inputs_that_cannot_mean_anything(self):
        """A zero-depth venue is not a cheaper venue, and zero AUM is not a free desk.

        Defect it guards: a silent `depth or 1e9` style default. Refusal-first is the house
        rule; an impossible input must stop the run, not pick a number.
        """
        with self.assertRaises(ValueError):
            ast.aum_net([0.0], [{}], [{}], aum=0.0, c_var_bps=0.0,
                        gas_per_leg=1.0, depth=1e6)
        with self.assertRaises(ValueError):
            ast.aum_net([0.0], [{}], [{}], aum=1e5, c_var_bps=0.0,
                        gas_per_leg=-1.0, depth=1e6)
        with self.assertRaises(ValueError):
            ast.impact_fraction({"eth": 0.1}, 1e5, 0.0)


class TestRuinDetection(unittest.TestCase):
    def test_the_scoring_function_really_does_clip_a_wipeout_to_zero(self):
        """The hazard `is_ruined` exists for, asserted on the real function.

        If this ever stops being true the ruin marking becomes unnecessary — and the test
        should be the thing that tells us, not a reader's memory. mh._apy returns 0.0 for a
        non-positive compounded path, so a bankrupt arm scores APY 0 and can OUTRANK an arm
        that merely lost money.
        """
        wiped = [-2.0] + [0.0] * 10   # equity goes negative on day 1
        self.assertEqual(mh._apy(wiped), 0.0)

    def test_ruin_is_detected_on_the_path_not_only_at_the_end(self):
        """Defect it guards: testing only the final compounded value. A path that touches
        zero mid-way and is 'rescued' by later positive returns is still a wipeout, and a
        final-value check would call it solvent."""
        self.assertTrue(ast.is_ruined([-1.5, 5.0, 5.0]))
        self.assertTrue(ast.is_ruined([-1.0]))
        self.assertFalse(ast.is_ruined([-0.5, -0.5, -0.5]))


class TestWindowReporting(unittest.TestCase):
    def test_an_empty_window_is_reported_as_empty(self):
        """Defect it guards: `min([])` raising, or worse, an empty window collapsing into
        a single rung and reading as a real capacity band."""
        self.assertEqual(ast.window_edges([(1e3, -1.0), (1e6, -0.2)]), (None, None))

    def test_a_single_positive_rung_is_reported_as_that_rung_twice(self):
        """A one-rung window is a real answer and must not be widened by interpolation."""
        self.assertEqual(
            ast.window_edges([(1e3, -1.0), (1e5, 0.4), (1e7, -2.0)]), (1e5, 1e5)
        )


class TestLegTables(unittest.TestCase):
    def test_the_two_tables_differ_exactly_where_the_entry_says_they_do(self):
        """The documented asymmetry — impact on δ=0 legs, gas on every leg — must be real.

        Defect it guards: both terms accidentally reading the same table. Then either debt
        legs pay AMM impact (they are not swaps) or they cost no gas (they are still
        transactions), and the entry's stated construction is a fiction.
        """
        books = sorted(gtn.RAW_LEGS)
        charge = ast.scoring_legs(books)
        touch = ast.touch_legs(books)
        debt_in_touch = {b for b in books if set(touch[b]) & gtn.DEBT_LEGS}
        self.assertTrue(debt_in_touch, "no book in the roster borrows — table drifted")
        for b in debt_in_touch:
            for leg in gtn.DEBT_LEGS & set(touch[b]):
                self.assertEqual(charge[b].get(leg, 0.0), 0.0)
                self.assertGreater(touch[b][leg], 0.0)

    def test_leg_flow_counts_only_legs_that_actually_moved(self):
        """Wiring check by SHAPE, not by name: a leg present but unchanged must not be
        counted, or every gas figure in the file is inflated by the standing book."""
        hist = [{"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}]
        legs = {"a": {"x": 1.0}, "b": {"y": 1.0}}
        fv = ast.leg_flow_vectors(hist, legs)
        self.assertEqual(fv[0], {})           # day 0 trades nothing
        self.assertEqual(fv[1], {})           # nothing moved
        self.assertEqual(sorted(fv[2]), ["x", "y"])


@needs_panel
class TestAgainstThePanel(unittest.TestCase):
    """The panel-bound claims the registry entry publishes."""

    @classmethod
    def setUpClass(cls):
        cls.dates, cls.book_rets = gtn.load_real_panel()
        cls.built, cls.n_days = ast.build(cls.dates, cls.book_rets)

    def test_frictionless_limit_reproduces_the_published_invoice_cell_for_cell(self):
        """gas=0, depth=inf must equal css._net EXACTLY — that is the bridge to #79-#90.

        Defect it guards: any drift in the turnover accounting between this file and the
        harness it claims to extend. Without this the entry's numbers cannot be compared
        with #90's table at all, and the comparison is the whole point.
        """
        legs = ast.scoring_legs(sorted(self.book_rets))
        for mode, _label in ast.ARMS:
            gross, chg, tch, _ = self.built[mode]
            mine = ast.aum_net(gross, chg, tch, aum=1e6, c_var_bps=ast.CONVENTION_COST,
                               gas_per_leg=0.0, depth=float("inf"))
            hist = css._weight_history(self.book_rets, self.dates, mode)
            theirs = css._net(gross, gtn.leg_turnover(hist, legs), ast.CONVENTION_COST)
            self.assertEqual(len(mine), len(theirs))
            for a, b in zip(mine, theirs):
                self.assertAlmostEqual(a, b, places=15)

    def test_it_reproduces_the_number_idea_90_published(self):
        """h60 at the convention with no size terms is #90's γ=0 cell: dCalmar −1.23.

        A harness that cannot reproduce the published cell of the entry it extends has no
        standing to contradict it.
        """
        g, chg, tch, _ = self.built["h60"]
        eg, ec, et, _ = self.built["eq"]
        kw = dict(aum=1e6, c_var_bps=ast.CONVENTION_COST, gas_per_leg=0.0,
                  depth=float("inf"))
        d = mh._calmar(ast.aum_net(g, chg, tch, **kw)) - \
            mh._calmar(ast.aum_net(eg, ec, et, **kw))
        self.assertAlmostEqual(d, -1.23, places=2)

    def test_the_baseline_pays_nothing_at_any_size(self):
        """Equal-weight must move no leg. Every dCalmar in the entry is 'the active arm's
        whole bill' ONLY because of this, so it is measured, not assumed."""
        _eg, ec, et, ing = self.built["eq"]
        self.assertEqual(ing.tau, 0.0)
        self.assertEqual(ing.legs_touched, 0.0)
        base = None
        for aum in (1e3, 1e9):
            for gas in (0.0, 1e6):
                for depth in (1e6, float("inf")):
                    net = ast.aum_net(self.built["eq"][0], ec, et, aum=aum,
                                      c_var_bps=ast.CONVENTION_COST, gas_per_leg=gas,
                                      depth=depth)
                    c = mh._calmar(net)
                    if base is None:
                        base = c
                    self.assertEqual(c, base)

    def test_the_guard_fires_when_the_baseline_stops_being_free(self):
        """POSITIVE CONTROL for the guard above: sabotage the baseline and it must REFUSE.

        A guard that has never been shown to fire is decoration. Here the fabricated
        history moves one leg on one day — the smallest possible violation.
        """
        with self.assertRaises(RuntimeError):
            ast.assert_baseline_pays_nothing([{}, {"eth": 0.01}], [{}, {"eth": 0.01}])

    def test_gas_of_twelve_dollars_a_leg_ruins_the_pilot_size(self):
        """The entry's sharpest published claim, locked in both directions.

        At $1k the model constant $12/leg is catastrophic while the measured spot
        $0.045/leg leaves the arm in the best cell of the table. If either half of that
        stops being true, the claim must be re-read before it is quoted again.
        """
        g, chg, tch, _ = self.built["h60"]
        eg, ec, et, _ = self.built["eq"]
        base = mh._calmar(ast.aum_net(eg, ec, et, aum=1e3, c_var_bps=0.0,
                                      gas_per_leg=0.0, depth=float("inf")))
        expensive = ast.score_at(g, chg, tch, base, aum=1e3, c_var_bps=0.0,
                                 gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=1e8)
        cheap = ast.score_at(g, chg, tch, base, aum=1e3, c_var_bps=0.0,
                             gas_per_leg=ast.GAS_SPOT_2026_08_30, depth=1e8)
        self.assertLess(expensive.dcalmar, 0.0)
        self.assertGreater(cheap.dcalmar, 0.0)

    def test_the_convention_column_is_empty_at_every_size(self):
        """The entry's decisive NEGATIVE: at c_var=96 no rung of a six-decade ladder is
        positive for any arm. This is the sentence that upholds #90, so it is pinned."""
        eg, ec, et, _ = self.built["eq"]
        for depth in ast.DEPTH_LADDER:
            for gas in (ast.GAS_MODEL_CONSTANT, ast.GAS_SPOT_2026_08_30):
                base = mh._calmar(ast.aum_net(eg, ec, et, aum=1e5,
                                              c_var_bps=ast.CONVENTION_COST,
                                              gas_per_leg=gas, depth=depth))
                for mode, _ in ast.ARMS:
                    g, chg, tch, _ = self.built[mode]
                    for aum in ast.AUM_LADDER:
                        r = ast.score_at(g, chg, tch, base, aum=aum,
                                         c_var_bps=ast.CONVENTION_COST,
                                         gas_per_leg=gas, depth=depth)
                        self.assertLessEqual(
                            r.dcalmar, 0.0,
                            f"{mode} turned positive at A={aum:g}, R={depth:g}, G={gas:g} — "
                            f"the entry's headline negative no longer holds",
                        )

    def test_the_window_exists_and_has_two_edges(self):
        """The entry's positive content: at c_var=0 the h60 window is bounded BELOW as well
        as above. A ladder positive at its lowest rung would mean no floor was found, and
        the entry must not then speak of a window."""
        eg, ec, et, _ = self.built["eq"]
        g, chg, tch, _ = self.built["h60"]
        base = mh._calmar(ast.aum_net(eg, ec, et, aum=1e5, c_var_bps=0.0,
                                      gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=1e8))
        pts = [
            (a, ast.score_at(g, chg, tch, base, aum=a, c_var_bps=0.0,
                             gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=1e8).dcalmar)
            for a in ast.AUM_LADDER
        ]
        lo, hi = ast.window_edges(pts)
        self.assertIsNotNone(lo)
        self.assertGreater(lo, min(ast.AUM_LADDER))   # a real floor was found
        self.assertLess(hi, max(ast.AUM_LADDER))      # a real ceiling was found

    def test_the_window_is_the_same_on_both_halves_of_the_canonical_split(self):
        """The out-of-sample claim. The window is a statement about a COST, so it should
        not move across the split; if it ever does, it is a period artefact and the entry's
        'identical on both halves' line has to be withdrawn."""
        cut = __import__("datetime").date.fromisoformat(ast.SPLIT_DATE)
        k = next((i for i in range(len(self.dates) - 1) if self.dates[i + 1] > cut),
                 len(self.dates) - 1)
        g, chg, tch, _ = self.built["h60"]
        eg, ec, et, _ = self.built["eq"]
        seen = []
        for sl in (slice(0, k), slice(k, None)):
            base = mh._calmar(ast.aum_net(eg[sl], ec[sl], et[sl], aum=1e5, c_var_bps=0.0,
                                          gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=1e8))
            pts = [
                (a, ast.score_at(g[sl], chg[sl], tch[sl], base, aum=a, c_var_bps=0.0,
                                 gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=1e8).dcalmar)
                for a in ast.AUM_LADDER
            ]
            seen.append(ast.window_edges(pts))
        self.assertEqual(seen[0], seen[1])
        self.assertIsNotNone(seen[0][0])

    def test_the_arm_ranking_survives_the_size_axis(self):
        """#90 found the ORDER of arms survives every γ; the entry claims it also survives
        every size. Ruined cells are excluded because there the order is an artefact of the
        APY clip, and including them was the first version's mistake."""
        eg, ec, et, _ = self.built["eq"]
        scored = flips = 0
        for depth in ast.DEPTH_LADDER:
            base = mh._calmar(ast.aum_net(eg, ec, et, aum=1e5,
                                          c_var_bps=ast.CONVENTION_COST,
                                          gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=depth))
            for aum in ast.AUM_LADDER:
                best, bd = None, None
                for mode, _ in ast.ARMS:
                    g, chg, tch, _ = self.built[mode]
                    r = ast.score_at(g, chg, tch, base, aum=aum,
                                     c_var_bps=ast.CONVENTION_COST,
                                     gas_per_leg=ast.GAS_MODEL_CONSTANT, depth=depth)
                    if r.ruined:
                        continue
                    if bd is None or r.dcalmar > bd:
                        best, bd = mode, r.dcalmar
                if best is None:
                    continue
                scored += 1
                if best != "h60":
                    flips += 1
        self.assertGreater(scored, 20)
        self.assertEqual(flips, 0)

    def test_the_run_is_advisory_and_deterministic(self):
        """Two runs of the whole entry must agree exactly, and it must declare itself."""
        self.assertTrue(ast.IS_ADVISORY)
        self.assertTrue(ast.OUTSIDE_RISKPOLICY)
        self.assertEqual(ast.EVIDENCE_LEVEL, "L0")
        first = ast.build(self.dates, self.book_rets)[0]["h60"][3]
        self.assertAlmostEqual(first.tau, self.built["h60"][3].tau, places=15)


if __name__ == "__main__":
    unittest.main()
