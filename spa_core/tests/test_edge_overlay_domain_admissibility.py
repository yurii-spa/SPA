"""Acceptance for scripts/edge_overlay_domain_admissibility.py (registry ideas GSB / ODA / PBA).

Advisory-only research harness. Nothing here touches RiskPolicy v1.0, the kill-switch, the live
track, the fleet or `data/`.

The load-bearing tests in this file are POSITIVE CONTROLS, in the shape the deployment rule
demands: each one reproduces a way the harness could be silently wrong, and each is MUTATED so
it cannot pass vacuously. Three of them matter more than the rest:

  * `test_gated_engine_reproduces_the_deployed_organ` — the whole file measures ODA as a delta
    against the deployed organ. If the mirror drifted from the organ by one line, every delta
    in the registry entry would be a measurement of the drift. Bit-for-bit equality, on every
    real book, at every convention.
  * `test_equivalence_test_is_not_vacuous` — its mutation. A gate that actually gates MUST
    break the equality above; if it does not, the first test proves nothing.
  * `test_causal_variant_equals_the_organs_own_trace_lagged_one_day` — the independent route to
    the same-bar finding, with the error rate it declared in advance (exactly one index per
    book, at the warm-up boundary).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402

from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol  # noqa: E402
from spa_core.strategy_lab.swarm import guardian_forward as gf  # noqa: E402

PARAMS = {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}


def _series(seed: int = 7, n: int = 400) -> list:
    """A deterministic, stdlib-only price path with a real vol regime shift in the middle.

    Not a fixture of a crisis — just a path on which the guardian actually fires, so the tests
    below are not measuring a guardian that never moved.
    """
    x = seed
    eq = [1.0]
    for i in range(n):
        x = (1103515245 * x + 12345) % (1 << 31)
        u = x / (1 << 31) - 0.5
        vol = 0.02 if 150 <= i < 220 else 0.003
        eq.append(eq[-1] * (1.0 + 0.0004 + u * vol))
    return eq


class TestGatedEngineIsTheDeployedOrgan(unittest.TestCase):
    """The baseline of every number in the registry entry."""

    def test_gated_engine_reproduces_the_deployed_organ(self):
        eq = _series()
        for bps in oda.CONVENTIONS_BPS:
            with self.subTest(bps=bps):
                self.assertEqual(
                    oda.guarded_path(eq, None, roundtrip_cost=bps / 1e4, **PARAMS),
                    apply_guardian_vol(eq, roundtrip_cost=bps / 1e4, **PARAMS),
                    "the mirror drifted from the organ it is measured against",
                )

    def test_equivalence_test_is_not_vacuous(self):
        """MUTATION. A gate that gates must break the equality above."""
        eq = _series()
        n = len(eq) - 1
        closed = [False] * n
        self.assertNotEqual(
            oda.guarded_path(eq, closed, roundtrip_cost=0.0015, **PARAMS),
            apply_guardian_vol(eq, roundtrip_cost=0.0015, **PARAMS),
            "a permanently closed gate changed nothing — the equality test proves nothing",
        )

    def test_k_zero_admits_every_day_at_every_convention(self):
        """K=0 is the positive control INSIDE the table: it must BE the organ, not resemble it."""
        eq = _series()
        for bps in oda.CONVENTIONS_BPS:
            adm = oda.oda_admission(eq, 90, 0.0, bps / 1e4)
            self.assertTrue(all(adm), f"K=0 closed the gate at {bps} bps")

    def test_gate_pays_for_its_own_re_entry(self):
        """A gate that closes while the book is de-risked must be CHARGED for the move.

        Free exits are the cheapest way for this whole idea to be an artefact, so the charge is
        pinned NUMERICALLY, not by an inequality. The first version of this test compared a
        tolled run against a free one and passed even when the closure charge was deleted — it
        was measuring that the toll does something at all, which the other moves already
        guarantee. This version isolates the closure:

        the gate is open on EXACTLY ONE day, the day the organ de-risks. That produces exactly
        two exposure changes in the whole run — the de-risk (day D) and the gate-forced
        re-entry (day D+1) — and no others, because on every closed day exposure is already 1.0
        and `prev == exposure`. So the final equity must be the unguarded compound with day D's
        return removed, times (1 − c) SQUARED. One factor short is the deleted charge.
        """
        eq = _series()
        deployed = oda._exposure_trace(eq, None, causal_lag=0, **PARAMS)
        derisk_days = [i for i in range(1, len(deployed))
                       if deployed[i] < 1.0 <= deployed[i - 1]]
        self.assertTrue(derisk_days, "the organ never de-risked — this test would be vacuous")
        d = derisk_days[0]
        n = len(eq) - 1
        adm = [i == d for i in range(n)]

        c = 0.0096
        got = oda.guarded_path(eq, adm, roundtrip_cost=c, **PARAMS)[-1]

        rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]
        expected = 1.0
        for i, r in enumerate(rets):
            if i != d:
                expected *= 1.0 + r
        expected *= (1.0 - c) ** 2

        self.assertAlmostEqual(
            got, expected, 12,
            "the closure charge is missing (or doubled): the gate is handing out free exits")

    def test_the_re_entry_charge_test_is_not_vacuous(self):
        """MUTATION of the test above: at a ZERO toll the two factors vanish and the same
        identity must hold with (1 − 0)**2 — so the assertion above is really pinning the
        charge, not an accident of the path."""
        eq = _series()
        deployed = oda._exposure_trace(eq, None, causal_lag=0, **PARAMS)
        d = [i for i in range(1, len(deployed)) if deployed[i] < 1.0 <= deployed[i - 1]][0]
        n = len(eq) - 1
        adm = [i == d for i in range(n)]
        free = oda.guarded_path(eq, adm, roundtrip_cost=0.0, **PARAMS)[-1]
        tolled = oda.guarded_path(eq, adm, roundtrip_cost=0.0096, **PARAMS)[-1]
        self.assertAlmostEqual(tolled / free, (1.0 - 0.0096) ** 2, 12,
                               "the ratio of tolled to free is not exactly two charges")


class TestSameBarFinding(unittest.TestCase):
    """The instrument audit that the registry entry #94 (GSB) rests on."""

    def test_causal_variant_equals_the_organs_own_trace_lagged_one_day(self):
        """The independent route, with the error rate declared BEFORE the run.

        The organ's vol signal is a pure function of the RAW returns, so if the deployed organ
        is simply one day early, this identity is exact — except at i == lookback, where the
        causal variant makes its first decision and the one-day-later organ has made none.
        A mismatch anywhere else means the two routes disagree about something real.
        """
        eq = _series()
        lb = PARAMS["lookback"]
        _, deployed, _ = gf.vol_guardian_trace(eq, roundtrip_cost=0.0)
        causal = oda._exposure_trace(eq, None, causal_lag=1, **PARAMS)
        bad = [i for i in range(1, len(causal))
               if abs(causal[i] - deployed[i - 1]) > 1e-15]
        self.assertIn(bad, ([], [lb]),
                      f"the two routes disagree away from the warm-up boundary: {bad[:8]}")

    def test_the_identity_test_is_not_vacuous(self):
        """MUTATION. Lag TWO days and the identity must break far from the warm-up index."""
        eq = _series()
        lb = PARAMS["lookback"]
        _, deployed, _ = gf.vol_guardian_trace(eq, roundtrip_cost=0.0)
        causal2 = oda._exposure_trace(eq, None, causal_lag=2, **PARAMS)
        bad = [i for i in range(1, len(causal2))
               if abs(causal2[i] - deployed[i - 1]) > 1e-15]
        self.assertTrue([i for i in bad if i > lb + 1],
                        "a two-day lag matched a one-day lag — the identity test is blind")

    def test_deployed_organ_reacts_within_the_bar_it_trades(self):
        """The finding itself, pinned in BOTH directions on a constructed path.

        A single violent day dropped into a calm series must move the DEPLOYED organ's exposure
        on that very day (that is the same-bar behaviour being reported), and must move the
        CAUSAL variant only from the day after. Pinning only one direction would let a harness
        that never fires at all pass.
        """
        eq = [1.0]
        for _ in range(120):
            eq.append(eq[-1] * 1.0002)
        shock = len(eq) - 1
        eq.append(eq[-1] * 0.60)
        for _ in range(20):
            eq.append(eq[-1] * 1.0002)
        deployed = oda._exposure_trace(eq, None, causal_lag=0, **PARAMS)
        causal = oda._exposure_trace(eq, None, causal_lag=1, **PARAMS)
        self.assertLess(deployed[shock], 1.0,
                        "the deployed organ did NOT react inside the bar — finding not reproduced")
        self.assertEqual(causal[shock], 1.0,
                         "the causal variant peeked at the shock day it was trading")
        self.assertLess(causal[shock + 1], 1.0,
                        "the causal variant never reacted at all — it is not a working control")


class TestTheTwoCopiesOfTheRuleAreBound(unittest.TestCase):
    """`_exposure_trace` and `guarded_path` are two copies of one decision rule.

    Section 0's numbers come from `guarded_path`; section 0b's independent confirmation comes
    from `_exposure_trace`. If the two drifted, 0b would be confirming a finding that 0 never
    measured — a cross-check between copies is blind to exactly that. This binds them.
    """

    def _paths(self, eq, adm, lag):
        got = oda.guarded_path(eq, adm, roundtrip_cost=0.0, causal_lag=lag, **PARAMS)
        trace = oda._exposure_trace(eq, adm, causal_lag=lag, **PARAMS)
        rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]
        built = [eq[0]]
        for i, r in enumerate(rets):
            built.append(built[-1] * (1.0 + r * trace[i]))
        return got, built

    def test_trace_reproduces_the_engine_for_every_lag_and_gate(self):
        eq = _series()
        n = len(eq) - 1
        gates = {
            "always open": None,
            "always shut": [False] * n,
            "open early only": [i < 170 for i in range(n)],
            "drawdown gate": oda.oda_admission(eq, 90, 5.0, 0.0015),
        }
        for lag in (0, 1, 2):
            for name, adm in gates.items():
                with self.subTest(lag=lag, gate=name):
                    got, built = self._paths(eq, adm, lag)
                    self.assertEqual(len(got), len(built))
                    for a, b in zip(got, built):
                        self.assertAlmostEqual(a, b, 12,
                                               "the two copies of the decision rule diverged")

    def test_the_binding_is_not_vacuous(self):
        """MUTATION: a trace from a DIFFERENT lag must not reproduce the engine's path."""
        eq = _series()
        got = oda.guarded_path(eq, None, roundtrip_cost=0.0, causal_lag=0, **PARAMS)
        trace = oda._exposure_trace(eq, None, causal_lag=1, **PARAMS)
        rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]
        built = [eq[0]]
        for i, r in enumerate(rets):
            built.append(built[-1] * (1.0 + r * trace[i]))
        self.assertNotAlmostEqual(got[-1], built[-1], 12,
                                  "lag 0 and lag 1 produced the same path — the bind is blind")


class TestGateSignalIsCausal(unittest.TestCase):
    """`trailing_maxdd` decides day i and may not see day i."""

    def test_trailing_maxdd_cannot_see_the_day_it_gates(self):
        """equity[50] is the crash, so the CRASH DAY is return index 49 — the gate bit that
        governs it is dd[49], and it must still read a flat book."""
        eq = [1.0] * 50 + [0.5] + [0.5] * 10
        dd = oda.trailing_maxdd(eq, 90)
        self.assertAlmostEqual(dd[49], 0.0, 12,
                               "the gate for the crash day saw the crash it was gating")

    def test_trailing_maxdd_must_see_it_the_day_after(self):
        """The other direction. A signal that never sees anything is also 'causal'."""
        eq = [1.0] * 50 + [0.5] + [0.5] * 10
        dd = oda.trailing_maxdd(eq, 90)
        self.assertGreater(dd[50], 0.49, "the gate never noticed a 50 % crash at all")

    def test_window_forgets_beyond_W(self):
        eq = [1.0] * 5 + [0.5] + [1.0] * 200
        dd = oda.trailing_maxdd(eq, 60)
        self.assertGreater(dd[10], 0.4)
        self.assertAlmostEqual(dd[190], 0.0, 12,
                               "a W-day window still remembers a crash 185 days old")

    def test_oracle_mode_is_flagged_by_being_constant(self):
        """ORACLE is LOOK-AHEAD. Its tell is that it cannot vary within a book."""
        eq = _series()
        adm = oda.oda_admission(eq, 90, 5.0, 0.0015, mode="oracle")
        self.assertEqual(len(set(adm)), 1, "the oracle control varied in time — it is not an oracle")

    def test_inverse_is_the_complement_of_direct(self):
        eq = _series()
        d = oda.oda_admission(eq, 90, 5.0, 0.0015, mode="direct")
        i = oda.oda_admission(eq, 90, 5.0, 0.0015, mode="inverse")
        self.assertEqual([not x for x in d], i,
                         "the control is not the complement it claims to be")


class TestPortfolioBenchmark(unittest.TestCase):
    def test_trim_needs_more_than_one_pass_and_gets_it(self):
        """The fixture is chosen so ONE pass leaves the portfolio in breach.

        Six books, cap 20 %. Two sit at 30 %; trimming them releases 20 points into four books
        that together hold 40 %, which lifts a 19 % book to 28.5 % — over the cap. A single-pass
        trim would return a breached vector and call it capped.
        """
        w = {"big1": 0.30, "big2": 0.30, "m": 0.19, "s1": 0.07, "s2": 0.07, "s3": 0.07}
        one_pass = dict(w)
        over = {b: v - 0.20 for b, v in one_pass.items() if v > 0.20}
        excess = sum(over.values())
        under = [b for b in one_pass if one_pass[b] <= 0.20]
        base = sum(one_pass[b] for b in under)
        for b in over:
            one_pass[b] = 0.20
        for b in under:
            one_pass[b] += excess * one_pass[b] / base
        self.assertGreater(max(one_pass.values()), 0.20,
                           "one pass already held the cap — this fixture cannot detect the bug")

        traded = oda.trim_to_cap(w, 0.20)
        self.assertLessEqual(max(w.values()), 0.20 + 1e-12, "trim_to_cap left a breach")
        self.assertAlmostEqual(sum(w.values()), 1.0, 12, "trimming did not conserve capital")
        self.assertGreater(traded, 0.0)

    def test_capped_buy_and_hold_refuses_rather_than_print_a_breach(self):
        """The harness re-checks its own invariant. This asserts the CHECK, not a copy of it."""
        books = {"win": [0.05] * 200}
        for j in range(9):
            books[f"b{j}"] = [0.0001 * (j - 4)] * 200
        live = sorted(books)
        rets = oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015)
        self.assertEqual(len(rets), 200,
                         "the benchmark stopped early — it hit its own breach guard")

    def test_uncapped_drift_would_have_breached_it(self):
        """MUTATION: without the trim, this panel DOES drift past 20 %."""
        books = {"win": [0.05] * 200}
        for j in range(9):
            books[f"b{j}"] = [0.0001 * (j - 4)] * 200
        live = sorted(books)
        w = {b: 1.0 / len(live) for b in live}
        for i in range(200):
            r = sum(w[b] * books[b][i] for b in live)
            for b in live:
                w[b] = w[b] * (1.0 + books[b][i]) / (1.0 + r)
        self.assertGreater(max(w.values()), 0.20,
                           "uncapped buy-and-hold never drifted past the cap — the test is inert")

    def test_refuses_an_infeasible_cap_by_name(self):
        """Fail-CLOSED: 3 books cannot hold 100 % under a 20 % cap — UNDER `prorata`.

        The message is asserted, not just the exception type: the post-trim invariant guard
        also raises ValueError, and a test that accepted either would pass while the
        feasibility check was gone.

        The convention is now named (2026-09-03, ADR-218) instead of being inherited from the
        default. That is not a softening — the refusal it guards is unchanged and still
        asserted by message. It is a correction of what the test was ever entitled to say:
        infeasibility is a property OF THE DESTINATION. Under `cash` this same panel is
        perfectly well defined, and the sibling test below measures what it does instead of
        leaving the branch unexercised.
        """
        books = {b: [0.001] * 50 for b in ("a", "b", "c")}
        with self.assertRaises(ValueError) as ctx:
            oda.capped_buy_and_hold(books, sorted(books), cap=0.20, cost=0.0,
                                    destination="prorata")
        self.assertIn("cannot hold 100", str(ctx.exception))

    def test_cash_holds_a_cap_prorata_calls_infeasible_and_parks_the_rest(self):
        """The mirror of the refusal above, and the reason it had to be named.

        Under `cash` the capital a tight ceiling cannot hold LEAVES the risk book, so the same
        3-book / 20 % panel is feasible. Asserted on the NUMBER, not merely on "it did not
        raise": from day 1 on, 60 % of NAV sits in books returning 0.1 %/day and 40 % is parked
        at 0 %, so the daily return must be 0.0006. A benchmark that quietly kept the money
        invested would show 0.001 instead.

        DAY 0 IS 0.001, AND THAT IS NAMED HERE RATHER THAN FIXED. The harness trims at the END
        of each day, so the opening equal weights are held for one day even when they already
        breach the ceiling. That is the shape #98 measured and published; changing it here
        would silently redo #98's numbers while claiming to implement the owner's decision.
        """
        books = {b: [0.001] * 50 for b in ("a", "b", "c")}
        rets = oda.capped_buy_and_hold(books, sorted(books), cap=0.20, cost=0.0,
                                       destination="cash")
        self.assertEqual(len(rets), 50, "the cash convention stopped early")
        self.assertAlmostEqual(rets[0], 0.001, 9,
                               "day 0 is not the opening equal-weight return — the harness no "
                               "longer trims at the END of the day")
        self.assertAlmostEqual(rets[1], 0.0006, 9,
                               "day 1 return is not 60 % invested — the cash sleeve is not "
                               "diluting NAV, or the trim never left the book")

    def test_section5_reports_both_conventions_and_no_unlabelled_benchmark(self):
        """The defect #98 found, closed AT THE READER'S DOOR rather than in a docstring.

        `capped_bh_20` used to be one key holding one number under an unnamed convention. Two
        registry entries then quoted it as a measurement. The section now returns BOTH
        conventions under names that say which is which, and the bare key must be GONE — a
        reader who gets `capped_bh_20` cannot tell which portfolio it describes, and that is
        the whole failure.
        """
        books = {"win": [0.05] * 300}
        for j in range(9):
            books[f"b{j}"] = [0.0001 * (j - 4)] * 300
        with contextlib.redirect_stdout(io.StringIO()):
            out = oda.section5_pba(books, PARAMS)
        self.assertNotIn("capped_bh_20", out,
                         "an unlabelled benchmark number reached the caller again")
        for dest in (oda.BENCHMARK_CONVENTION, oda.PUBLISHED_CONVENTION):
            self.assertIn(f"capped_bh_20_{dest}", out,
                          f"the {dest!r} column is missing — the owner's decision keeps BOTH")
        self.assertNotEqual(
            out[f"capped_bh_20_{oda.BENCHMARK_CONVENTION}"],
            out[f"capped_bh_20_{oda.PUBLISHED_CONVENTION}"],
            "both columns carry the same numbers — this panel cannot tell the conventions "
            "apart, so the assertions above prove nothing")

    def test_capital_is_conserved_under_both_conventions(self):
        """Books + cash sleeve = 1, every day. The POSITIVE CONTROL of the conservation guard.

        This exists because the guard was added in response to a surviving mutation: the cash
        sleeve was tracked and never read, so removing its NAV dilution changed nothing any
        test could see. `capped_buy_and_hold` now refuses on a broken sum, and this asserts the
        refusal fires — a guard never seen failing is decoration.
        """
        books = {"win": [0.05] * 120}
        for j in range(9):
            books[f"b{j}"] = [0.0001 * (j - 4)] * 120
        live = sorted(books)
        for dest in oda.TRIM_DESTINATIONS:
            self.assertEqual(
                len(oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015,
                                            destination=dest)), 120,
                f"{dest!r} tripped its own conservation guard on a well-formed panel")

        # MUTATION: a trim that pays into the books AND into cash creates capital out of thin
        # air. The guard must catch it; if it does not, it is not checking anything.
        real_trim = oda._trim

        def leaky(w, cap, destination):
            traded, to_cash = real_trim(w, cap, "prorata")
            return traded, to_cash + traded
        oda._trim = leaky
        try:
            with self.assertRaises(ValueError) as ctx:
                oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015, destination="cash")
            self.assertIn("capital is not conserved", str(ctx.exception))
        finally:
            oda._trim = real_trim

    def test_the_benchmark_convention_is_the_owner_decided_one(self):
        """The default IS the decision. ADR-218 (owner option 1, 2026-09-03): the family's bar
        does not force-buy anybody with the proceeds of a forced sale.

        Pinned as a VALUE and as BEHAVIOUR, because either alone is weak: a constant nobody
        reads is decoration, and a behaviour with no named constant is a convention quoted as
        a measurement — the exact defect #98 found.
        """
        self.assertEqual(oda.BENCHMARK_CONVENTION, "cash")
        self.assertEqual(oda.PUBLISHED_CONVENTION, "prorata")
        self.assertIn(oda.BENCHMARK_CONVENTION, oda.TRIM_DESTINATIONS)
        self.assertIn(oda.PUBLISHED_CONVENTION, oda.TRIM_DESTINATIONS)

        books = {"win": [0.05] * 200}
        for j in range(9):
            books[f"b{j}"] = [0.0001 * (j - 4)] * 200
        live = sorted(books)
        default = oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015)
        named = oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015,
                                        destination=oda.BENCHMARK_CONVENTION)
        published = oda.capped_buy_and_hold(books, live, cap=0.20, cost=0.0015,
                                            destination=oda.PUBLISHED_CONVENTION)
        self.assertEqual(default, named, "the default is not BENCHMARK_CONVENTION")
        self.assertNotEqual(default, published,
                            "the two conventions produced the same path — this fixture cannot "
                            "tell them apart and the assertion above proves nothing")


class TestHarnessDiscipline(unittest.TestCase):
    def test_refuses_an_empty_panel_loudly(self):
        """Fail-CLOSED. An empty table must not read as 'the guardian helps nowhere'."""
        original = oda.gtn.load_real_panel
        try:
            oda.gtn.load_real_panel = lambda *a, **k: ([], {})  # type: ignore[assignment]
            self.assertEqual(oda.main([]), 2)
        finally:
            oda.gtn.load_real_panel = original  # type: ignore[assignment]

    def test_refuses_to_write_under_data(self):
        """The research layer never writes into the track's directory."""
        self.assertEqual(oda.main(["--json", str(ROOT / "data" / "nope.json")]), 2)
        self.assertFalse((ROOT / "data" / "nope.json").exists())

    def test_declares_itself_advisory_and_outside_riskpolicy(self):
        self.assertTrue(oda.IS_ADVISORY)
        self.assertTrue(oda.OUTSIDE_RISKPOLICY)
        self.assertEqual(oda.EVIDENCE_LEVEL, "L0")

    def test_does_not_reference_execution_anywhere_in_its_source(self):
        """Read the SOURCE, not `sys.modules`.

        `sys.modules` is ambient: another test file in the same session can import the
        execution package and this check would then fail — or pass — for reasons that have
        nothing to do with this harness. The question is what THIS file imports, and the only
        honest place to ask it is the file.
        """
        for path in (ROOT / "scripts" / "edge_overlay_domain_admissibility.py", Path(__file__)):
            src = path.read_text(encoding="utf-8")
            for line in src.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    self.assertNotIn("spa_core.execution", stripped,
                                     f"{path.name} imports the execution domain")

    def test_deployed_toll_is_read_from_the_organ_not_retyped(self):
        """If someone re-tunes the live organ, this file must move with it or fail loudly."""
        self.assertAlmostEqual(oda.DEPLOYED_BPS,
                               1e4 * gf.GUARDIAN_PARAMS["roundtrip_cost"], places=9)

    def test_comparability_rule_excludes_losing_books_both_ways(self):
        self.assertTrue(oda.comparable(3.0, 10.0))
        self.assertFalse(oda.comparable(-0.4, -26.0))
        self.assertFalse(oda.comparable(2.0, -1.0), "a losing book was called comparable")
        self.assertFalse(oda.comparable(float("nan"), 5.0))

    def test_dead_book_is_an_absence_not_a_null_result(self):
        self.assertTrue(oda.is_dead([0.0] * 100))
        self.assertFalse(oda.is_dead([0.0] * 99 + [1e-6]))


if __name__ == "__main__":
    unittest.main()
