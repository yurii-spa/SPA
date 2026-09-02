"""Acceptance for scripts/edge_trim_proceeds_destination.py (registry ideas TPD / BLO).

Advisory-only research harness. Nothing here touches RiskPolicy v1.0, the kill-switch, the
live track, the fleet or `data/`. Every test builds its own synthetic panel: the real
aggressive-lab panel is ABSENT in a worktree by construction, and a test that skipped itself
there would make "not measured" indistinguishable from "passed".

The load-bearing tests are POSITIVE CONTROLS and each is MUTATED so it cannot pass vacuously:

  * `test_prorata_is_the_deployed_benchmark` — the whole file is a contrast against the
    benchmark #96 published. If the reimplementation drifted by one line, every delta in the
    registry entry would be a measurement of that drift. Bit-for-bit, at every toll convention.
  * `test_identity_is_not_vacuous` — its mutation. A destination that actually redirects money
    MUST break that equality; if it does not, the first test proves nothing and the whole §1
    table is five copies of one portfolio.
  * `test_restart_split_switches_the_dial_off_while_carry_does_not` — the methodological
    finding of the entry, pinned as a PROPERTY rather than left as prose: re-initialising the
    weights at the split boundary makes the ceiling stop binding, which makes all five
    destinations the same portfolio. Mutated in both directions.
  * `test_refuses_rather_than_returning_a_breached_portfolio` — the fail-CLOSED rule inherited
    verbatim from #86: a benchmark that breaches the T2 ceiling is not a benchmark.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402
import edge_trim_proceeds_destination as tpd  # noqa: E402


def _panel(seed: int = 5, n: int = 300, books: int = 6):
    """A deterministic panel on which the 20 % ceiling ACTUALLY BINDS.

    One book compounds much faster than the rest, which is the only condition under which a
    trim ever happens. A panel where nothing is ever trimmed would make every test below pass
    for the wrong reason, so book 0's drift is asserted to produce binding days in
    `test_the_fixture_panel_actually_binds` — the fixture's own positive control.
    """
    x = seed
    out = {}
    for b in range(books):
        rets = []
        for i in range(n):
            x = (1103515245 * x + 12345) % (1 << 31)
            u = x / (1 << 31) - 0.5
            drift = 0.0035 if b == 0 else 0.0002
            rets.append(drift + u * (0.004 if b else 0.002))
        out[f"book{b}"] = rets
    return out


def _live(panel):
    return sorted(panel)


class TestFixture(unittest.TestCase):
    def test_the_fixture_panel_actually_binds(self):
        """If the ceiling never binds, every destination is the same portfolio and this whole
        file would be green while measuring nothing."""
        panel = _panel()
        trace: list = []
        tpd.capped_bh(panel, _live(panel), cap=0.20, cost=0.0015,
                      destination="prorata", trace=trace)
        self.assertGreater(sum(1 for t in trace if t > 0), 50,
                           "fixture panel never breaches the ceiling — tests would be vacuous")


class TestIdentityWithTheDeployedBenchmark(unittest.TestCase):
    """destination=prorata must BE `oda.capped_buy_and_hold`, or §1 contrasts a portfolio #96
    never published."""

    def test_prorata_is_the_deployed_benchmark(self):
        panel = _panel()
        live = _live(panel)
        for bps in tpd.CONVENTIONS_BPS:
            theirs = oda.capped_buy_and_hold(panel, live, cap=0.20, cost=bps / 1e4)
            mine = tpd.capped_bh(panel, live, cap=0.20, cost=bps / 1e4, destination="prorata")
            self.assertEqual(len(theirs), len(mine))
            for i, (a, b) in enumerate(zip(theirs, mine)):
                self.assertEqual(a, b, f"day {i} differs at {bps} bps — not the same benchmark")

    def test_identity_holds_at_several_ceilings(self):
        panel = _panel()
        live = _live(panel)
        for cap in (0.25, 0.33, 0.50):
            theirs = oda.capped_buy_and_hold(panel, live, cap=cap, cost=0.0015)
            mine = tpd.capped_bh(panel, live, cap=cap, cost=0.0015, destination="prorata")
            self.assertEqual(theirs, mine, f"ceiling {cap} differs")

    def test_identity_is_not_vacuous(self):
        """THE MUTATION. A destination that redirects money must BREAK the equality above."""
        panel = _panel()
        live = _live(panel)
        theirs = oda.capped_buy_and_hold(panel, live, cap=0.20, cost=0.0015)
        for dest in ("equal", "to_min", "to_max", "cash"):
            mine = tpd.capped_bh(panel, live, cap=0.20, cost=0.0015, destination=dest)
            self.assertNotEqual(
                theirs, mine,
                f"destination {dest!r} produced the deployed path exactly — either it is a "
                f"no-op or the identity test above proves nothing")


class TestRedistribution(unittest.TestCase):
    def test_reaches_a_fixed_point_when_one_pass_is_not_enough(self):
        """`to_max` hands the whole excess to ONE book, which can push that book over the
        ceiling. A single pass would leave the portfolio silently in breach."""
        w = {"a": 0.60, "b": 0.19, "c": 0.11, "d": 0.05, "e": 0.05}
        traded, cash = tpd.redistribute(w, 0.20, "to_max")
        self.assertLessEqual(max(w.values()), 0.20 + 1e-9)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=12)
        self.assertGreater(traded, 0.0)
        self.assertEqual(cash, 0.0)

    def test_every_destination_conserves_capital(self):
        for dest in tpd.DESTINATIONS:
            w = {"a": 0.55, "b": 0.20, "c": 0.10, "d": 0.10, "e": 0.05}
            traded, cash = tpd.redistribute(w, 0.20, dest)
            self.assertAlmostEqual(sum(w.values()) + cash, 1.0, places=12,
                                   msg=f"{dest} lost or created capital")
            self.assertLessEqual(max(w.values()), 0.20 + 1e-9, f"{dest} left a breach")

    def test_cash_is_the_only_destination_that_leaves_the_risk_book(self):
        w = {"a": 0.60, "b": 0.10, "c": 0.10, "d": 0.10, "e": 0.10}
        _t, cash = tpd.redistribute(dict(w), 0.20, "cash")
        self.assertGreater(cash, 0.0)
        for dest in ("prorata", "equal", "to_min", "to_max"):
            _t2, c2 = tpd.redistribute(dict(w), 0.20, dest)
            self.assertEqual(c2, 0.0, f"{dest} moved capital to cash")

    def test_refuses_rather_than_returning_a_breached_portfolio(self):
        """Fail-CLOSED, inherited verbatim from #86: five books under a 20 % ceiling exactly
        fill the portfolio, so nothing is strictly under the cap to receive a trim."""
        pinned = {"a": 0.30, "b": 0.20, "c": 0.20, "d": 0.20, "e": 0.20}
        with self.assertRaises(tpd.Infeasible):
            tpd.redistribute(pinned, 0.20, "prorata")

    def test_refuses_a_ceiling_that_cannot_hold_the_capital(self):
        panel = _panel(books=4)
        with self.assertRaises(tpd.Infeasible):
            tpd.capped_bh(panel, _live(panel), cap=0.20, cost=0.0015, destination="prorata")

    def test_cash_can_express_the_ceiling_that_redistribution_refuses(self):
        """The refusal above is not a hole in the grid: `cash` holds the remainder, which is
        the honest answer to 'four books cannot fill a 20 % ceiling'."""
        panel = _panel(books=4)
        path = tpd.capped_bh(panel, _live(panel), cap=0.20, cost=0.0015, destination="cash")
        self.assertEqual(len(path), 300)


class TestToll(unittest.TestCase):
    def test_cash_is_charged_one_leg_and_redistribution_two(self):
        """A destination with no buy leg must not be charged for one; and because charging it
        one leg is itself a choice, the two-leg variant must be reachable and must differ."""
        panel = _panel()
        live = _live(panel)
        one = tpd.capped_bh(panel, live, cap=0.20, cost=0.05, destination="cash", cash_legs=1)
        two = tpd.capped_bh(panel, live, cap=0.20, cost=0.05, destination="cash", cash_legs=2)
        self.assertNotEqual(one, two, "the cash_legs dial does nothing")
        self.assertGreater(sum(one), sum(two), "two legs must cost more than one")

    def test_a_zero_toll_and_a_real_toll_differ(self):
        panel = _panel()
        live = _live(panel)
        free = tpd.capped_bh(panel, live, cap=0.20, cost=0.0, destination="prorata")
        paid = tpd.capped_bh(panel, live, cap=0.20, cost=0.05, destination="prorata")
        self.assertGreater(sum(free), sum(paid), "the toll is not being charged at all")


class TestRandomControl(unittest.TestCase):
    def test_is_deterministic_per_seed(self):
        panel = _panel()
        live = _live(panel)
        a = tpd.capped_bh_random(panel, live, cap=0.20, cost=0.0015, seed=11)
        b = tpd.capped_bh_random(panel, live, cap=0.20, cost=0.0015, seed=11)
        self.assertEqual(a, b)

    def test_different_seeds_give_different_paths(self):
        """Otherwise the 'random band' of §2 is one number printed five times, and a finding
        could sit outside a band of width zero for free."""
        panel = _panel()
        live = _live(panel)
        a = tpd.capped_bh_random(panel, live, cap=0.20, cost=0.0015, seed=11)
        b = tpd.capped_bh_random(panel, live, cap=0.20, cost=0.0015, seed=73)
        self.assertNotEqual(a, b)


class TestSplitProtocol(unittest.TestCase):
    """The methodological finding of the entry, pinned as a property.

    A TRAIN/TEST split is neutral for a signal and NOT neutral for a buy-and-hold portfolio:
    restarting the weights at the boundary deletes the drift that the destination acts on. On
    the real panel this made the ceiling bind on ZERO of 370 test days and all five
    destinations score identically — a tie that looks like "the dial does not matter" and is
    actually "the protocol switched the dial off".
    """

    #: Ten books and a late boundary, mirroring the real panel's shape: from an equal 1/10 a
    #: book needs to roughly DOUBLE its relative weight before a 20 % ceiling binds, which
    #: takes longer than the test half. That is exactly the condition the real panel met.
    PANEL_KW = {"n": 400, "books": 10}
    BOUNDARY = 300

    def test_restart_split_switches_the_dial_off_while_carry_does_not(self):
        panel = _panel(**self.PANEL_KW)
        live = _live(panel)
        k = self.BOUNDARY
        restart = {b: panel[b][k:] for b in live}
        restart_paths = {
            d: tpd.capped_bh(restart, live, cap=0.20, cost=0.0015, destination=d)
            for d in tpd.DESTINATIONS}
        carry_paths = {
            d: tpd.capped_bh(panel, live, cap=0.20, cost=0.0015, destination=d)[k:]
            for d in tpd.DESTINATIONS}
        # under RESTART the ceiling has not had time to bind, so the destinations coincide
        for d in tpd.DESTINATIONS:
            self.assertEqual(restart_paths["prorata"], restart_paths[d],
                             f"{d} differs under RESTART — the fixture no longer shows the "
                             f"artefact this test exists to pin")
        # under CARRY at least one destination must separate, or the two protocols are the
        # same test and the finding is not a finding
        self.assertTrue(
            any(carry_paths["prorata"] != carry_paths[d] for d in tpd.DESTINATIONS),
            "no destination separates under CARRY either — the fixture proves nothing")

    def test_binding_count_is_what_separates_the_two_protocols(self):
        """The mechanism of the test above, measured rather than asserted by analogy."""
        panel = _panel(**self.PANEL_KW)
        live = _live(panel)
        k = self.BOUNDARY
        restart = {b: panel[b][k:] for b in live}
        t_restart: list = []
        tpd.capped_bh(restart, live, cap=0.20, cost=0.0015,
                      destination="prorata", trace=t_restart)
        t_carry: list = []
        tpd.capped_bh(panel, live, cap=0.20, cost=0.0015, destination="prorata", trace=t_carry)
        self.assertEqual(sum(1 for t in t_restart if t > 0), 0,
                         "the restarted half already binds — pick a fixture where it does not")
        self.assertGreater(sum(1 for t in t_carry[k:] if t > 0), 0,
                           "the carried path does not bind in the test segment either")


class TestAdvisoryContract(unittest.TestCase):
    def test_module_declares_itself_advisory_and_outside_riskpolicy(self):
        self.assertTrue(tpd.IS_ADVISORY)
        self.assertTrue(tpd.OUTSIDE_RISKPOLICY)
        self.assertEqual(tpd.EVIDENCE_LEVEL, "L0")

    def test_never_reaches_the_execution_domain(self):
        src = (ROOT / "scripts" / "edge_trim_proceeds_destination.py").read_text()
        # the string appears in the docstring as a PROMISE; what must be absent is the import
        for line in src.splitlines():
            head = line.strip()
            if head.startswith("import ") or head.startswith("from "):
                self.assertNotIn("execution", head, f"reaches the execution domain: {head}")
        self.assertNotIn("atomic_save", src, "a research harness must not write state")

    def test_toll_is_read_from_the_deployed_organ_not_retyped(self):
        self.assertEqual(tpd.DEPLOYED_BPS, oda.DEPLOYED_BPS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
