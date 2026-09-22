"""Guards for ideas #111 (BISS-REAL) and #112 (XLS).

Every test here is a positive control for something that was WRONG at least once, either in
#110's fixture-only reasoning or in the first draft of these two harnesses:

  * the simulator must BE #110's mechanism, and the control that says so must itself be able to
    fail (tests 1-2);
  * a "share of the ORACLE ceiling" must refuse by name in three separate situations instead of
    printing a zero (inv. #17);
  * "false positives in calm" has two denominators and they are not interchangeable;
  * a causal rule must take day one of a decline in full — that is the barrier #110 measured, and
    a harness that quietly avoids it would fabricate the whole finding;
  * the lead-time instrument's FIRST version reported "+10 days of lead" for a rule that simply
    never leaves DEFEND. It was measuring duty. ALREADY-IN exists because of that.

No live-data dependency: the real panel is never read here (a test whose verdict depends on
data/ answers a different question every day). The fixture path is deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))

import edge_biss_real_panel as B111  # noqa: E402
import edge_exogenous_leading_switch as XLS  # noqa: E402


def _flat_panel(dates, per_day):
    """One-book panel whose single book has the given daily returns."""
    return {"only": list(per_day)}


class ControlReproduces110(unittest.TestCase):
    def test_simulator_reproduces_every_published_cell(self):
        got = B111.control_reproduces_110()
        self.assertEqual(set(got), {f"{s}/{d:g}" for s, d in B111.PUBLISHED_110})
        for key, (apy, apy_pub, dd, dd_pub, cal, cal_pub) in got.items():
            self.assertLessEqual(abs(apy - apy_pub), B111.CONTROL_TOL, key)
            self.assertLessEqual(abs(dd - dd_pub), B111.CONTROL_TOL, key)
            if cal_pub == float("inf"):
                self.assertEqual(cal, float("inf"), key)
            else:
                self.assertLessEqual(abs(cal - cal_pub), B111.CONTROL_TOL, key)

    def test_the_control_can_actually_fail(self):
        """Positive control of the control: perturb the comparison, the control must REFUSE.

        Without this, a control that compares a number against itself would look identical to a
        control that proves anything — the "ornament" failure mode.
        """
        original = dict(B111.PUBLISHED_110)
        try:
            B111.PUBLISHED_110[("1day", 0.5)] = (99.0, 1.0, 9.0)
            with self.assertRaises(AssertionError):
                B111.control_reproduces_110()
        finally:
            B111.PUBLISHED_110.clear()
            B111.PUBLISHED_110.update(original)
        B111.control_reproduces_110()  # green again: the failure was the perturbation

    def test_the_published_cells_are_sensitive_to_the_MECHANISM_not_only_to_the_table(self):
        """Perturb #110's re-entry rule at the CALL and the fixture cell must move.

        Note for the next reader: the obvious version of this test — assigning
        `B111.N_RECOVER = N + 7` and re-running the control — is INERT. `simulate`'s parameter
        default is bound at definition time, so a module-global override never reaches it and the
        control stays green while looking perturbed. The knob has to be turned at the call.
        """
        dates, rets = B111.BISS._load_daily_rets()
        B111.set_axis(dates)
        pub_apy, _, _ = B111.PUBLISHED_110[("1day", 0.5)]
        same = B111.simulate(dates, rets, B111.BISS.BOOKS, mode="1day", defend_frac=0.5,
                             n_recover=B111.N_RECOVER)
        moved = B111.simulate(dates, rets, B111.BISS.BOOKS, mode="1day", defend_frac=0.5,
                              n_recover=B111.N_RECOVER + 7)
        self.assertLessEqual(abs(same["apy_pct"] - pub_apy), B111.CONTROL_TOL)
        self.assertGreater(abs(moved["apy_pct"] - pub_apy), B111.CONTROL_TOL,
                           "if the mechanism can be changed without moving the cell, the cell "
                           "is not evidence of the mechanism")


class DeclineWindows(unittest.TestCase):
    def setUp(self):
        # 10 flat days, a 5 % three-day decline, then recovery, then flat
        self.rets = [0.0] * 5 + [-0.02, -0.02, -0.01] + [0.03] + [0.0] * 5
        self.dates = [f"2025-01-{i + 1:02d}" for i in range(len(self.rets))]
        B111.set_axis(self.dates)

    def test_one_window_at_shallow_depth_and_none_at_deep(self):
        w2 = B111.decline_windows(self.dates, self.rets, 0.02)
        self.assertEqual(len(w2), 1)
        self.assertEqual(w2[0], (self.dates[5], self.dates[7]))
        self.assertEqual(B111.decline_windows(self.dates, self.rets, 0.10), [])

    def test_window_days_are_taken_from_the_axis_not_from_a_date_range(self):
        B111.set_axis([d for d in self.dates if d != self.dates[6]])  # a hole in the axis
        days = B111.window_days([(self.dates[5], self.dates[7])])
        self.assertNotIn(self.dates[6], days)
        self.assertEqual(sorted(days), [self.dates[5], self.dates[7]])

    def test_still_open_final_decline_is_included(self):
        rets = [0.0] * 5 + [0.02] + [-0.02] * 4
        dates = [f"2025-02-{i + 1:02d}" for i in range(len(rets))]
        B111.set_axis(dates)
        w = B111.decline_windows(dates, rets, 0.02)
        self.assertEqual(len(w), 1, "a decline that never recovers must still be a window")
        self.assertEqual(w[0][1], dates[-1])

    def test_length_mismatch_refuses(self):
        with self.assertRaises(ValueError):
            B111.decline_windows(self.dates, self.rets[:-1], 0.02)


class CeilingRefusals(unittest.TestCase):
    def test_infinite_ceiling_is_refused_by_name(self):
        self.assertIsNone(B111.share_of_ceiling(1.0, 0.5, float("inf")))
        why = B111.ceiling_refusal(0.5, float("inf"))
        self.assertIsNotNone(why)
        self.assertIn("infinite", why)

    def test_non_positive_span_is_refused_by_a_DIFFERENT_name(self):
        self.assertIsNone(B111.share_of_ceiling(1.0, 2.0, 1.5))
        why = B111.ceiling_refusal(2.0, 1.5)
        self.assertIsNotNone(why)
        self.assertIn("does not beat", why)

    def test_a_real_share_is_a_number_and_not_a_refusal(self):
        self.assertIsNone(B111.ceiling_refusal(1.0, 3.0))
        self.assertAlmostEqual(B111.share_of_ceiling(2.0, 1.0, 3.0), 0.5)

    def test_nan_row_does_not_become_zero(self):
        self.assertIsNone(B111.share_of_ceiling(float("nan"), 1.0, 3.0))


class FalsePositiveDenominators(unittest.TestCase):
    def setUp(self):
        self.axis = [f"2025-03-{i + 1:02d}" for i in range(10)]
        self.win = {self.axis[0], self.axis[1]}

    def test_two_denominators_are_not_the_same_number(self):
        defend = {self.axis[0], self.axis[5]}
        f = B111.fp_rates(defend, self.win, self.axis)
        self.assertAlmostEqual(f["fp_of_defend"], 0.5)      # 1 of 2 defend-days was calm
        self.assertAlmostEqual(f["fp_of_calm"], 1.0 / 8.0)  # 1 of 8 calm days was defended
        self.assertNotAlmostEqual(f["fp_of_defend"], f["fp_of_calm"])

    def test_never_defending_is_not_a_zero_rate(self):
        f = B111.fp_rates(set(), self.win, self.axis)
        self.assertIsNone(f["fp_of_defend"], "no defend-day means the rate has no denominator")
        self.assertEqual(f["fp_days"], 0.0)

    def test_recall_is_none_when_there_is_no_window(self):
        self.assertIsNone(B111.fp_rates({self.axis[0]}, set(), self.axis)["recall_of_window"])


class CausalityAndToll(unittest.TestCase):
    def setUp(self):
        # calm, one catastrophic day, calm again
        self.rets = [0.001] * 10 + [-0.20] + [0.001] * 10
        self.dates = [f"2025-04-{i + 1:02d}" for i in range(len(self.rets))]
        B111.set_axis(self.dates)
        self.panel = _flat_panel(self.dates, self.rets)

    def _eq(self, row):
        return row

    def test_one_day_rule_takes_the_crash_day_in_full(self):
        """The barrier #110 measured. If the harness avoided day one, every number would be a lie."""
        crash = self.dates[10]
        one = B111.simulate(self.dates, self.panel, ["only"], mode="1day", defend_frac=0.0)
        oracle = B111.simulate(self.dates, self.panel, ["only"], mode="given", defend_frac=0.0,
                               defend_days={crash})
        self.assertNotIn(crash, one["defend_days"], "a causal rule cannot defend on the day it learns")
        self.assertIn(self.dates[11], one["defend_days"], "it must defend the DAY AFTER")
        self.assertGreater(oracle["apy_pct"], one["apy_pct"])
        self.assertLess(oracle["maxdd_pct"], one["maxdd_pct"])

    def test_given_mode_refuses_to_default_to_invest(self):
        with self.assertRaises(ValueError):
            B111.simulate(self.dates, self.panel, ["only"], mode="given", defend_frac=0.0)

    def test_toll_follows_the_capital_that_moved(self):
        """The toll is `roundtrip x |change in risky weight|` — checked against the closed form.

        Measured on a scene with zero book returns and the RWA floor pinned to zero, so the only
        thing moving the equity IS the toll and the assertion can be exact. Asserting on APY
        instead gives 1.84 rather than 2.00 — annualisation over a 21-day scene is not linear in
        the toll, and a test that tolerated that gap would also tolerate a wrong toll.
        """
        days = {self.dates[5]}
        flat = _flat_panel(self.dates, [0.0] * len(self.dates))
        rt = 0.0096
        saved = B111.RWA_DAILY
        try:
            B111.RWA_DAILY = 0.0
            out = {}
            for name, df in (("half", 0.5), ("zero", 0.0)):
                r = B111.simulate(self.dates, flat, ["only"], mode="given", defend_frac=df,
                                  defend_days=days, roundtrip=rt)
                out[name] = (1.0 + r["apy_pct"] / 100.0) ** (r["n_days"] / 365.0)
                self.assertEqual(r["switches"], 2, "out and back is two changes of weight")
        finally:
            B111.RWA_DAILY = saved
        self.assertAlmostEqual(out["half"], (1.0 - rt * 0.5) ** 2, places=10)
        self.assertAlmostEqual(out["zero"], (1.0 - rt * 1.0) ** 2, places=10)

    def test_a_rule_that_never_defends_equals_the_ew_zero(self):
        ew = B111.simulate(self.dates, self.panel, ["only"], mode="ew", defend_frac=0.0)
        idle = B111.simulate(self.dates, self.panel, ["only"], mode="given", defend_frac=0.0,
                             defend_days=set(), roundtrip=0.0096)
        self.assertAlmostEqual(ew["apy_pct"], idle["apy_pct"], places=9)
        self.assertEqual(idle["switches"], 0)


class LeadTimeInstrument(unittest.TestCase):
    def setUp(self):
        self.axis = [f"2025-05-{i + 1:02d}" for i in range(31)]
        self.windows = [(self.axis[20], self.axis[25])]

    def test_a_permanent_defender_is_ALREADY_IN_not_early(self):
        """The defect this instrument was rewritten for: duty masquerading as lead."""
        rows = XLS.lead_times(self.axis, self.windows, set(self.axis))
        self.assertEqual(rows[0]["status"], "ALREADY-IN")
        self.assertIsNone(rows[0]["lead"])

    def test_a_transition_before_the_window_is_a_positive_lead(self):
        defend = set(self.axis[15:26])          # switches on at index 15, window opens at 20
        rows = XLS.lead_times(self.axis, self.windows, defend)
        self.assertEqual(rows[0]["status"], "fired")
        self.assertEqual(rows[0]["lead"], 5)

    def test_a_transition_after_the_window_is_a_negative_lead(self):
        rows = XLS.lead_times(self.axis, self.windows, set(self.axis[23:26]))
        self.assertEqual(rows[0]["lead"], -3)

    def test_silence_is_MISSED_and_not_a_zero_lead(self):
        rows = XLS.lead_times(self.axis, self.windows, set())
        self.assertEqual(rows[0]["status"], "MISSED")
        self.assertIsNone(rows[0]["lead"])

    def test_band_edge_transition_is_marked_saturated(self):
        rows = XLS.lead_times(self.axis, self.windows, set(self.axis[11:26]))
        self.assertTrue(rows[0]["saturated"], "a lead pinned to the band edge may be larger")

    def test_shifted_null_keeps_duty(self):
        defend = set(self.axis[5:12])
        shifted = XLS.shift_defend(self.axis, defend, 9)
        self.assertEqual(len(shifted), len(defend))
        self.assertNotEqual(shifted, defend)


class ExogenousSignals(unittest.TestCase):
    def setUp(self):
        self.axis = [f"2025-06-{i + 1:02d}" for i in range(20)]

    def test_funding_decision_cannot_read_its_own_day(self):
        """Mutating day t's funding must leave day t's decision untouched — only t+1 may move."""
        base = {d: 0.0001 for d in self.axis}
        flip = dict(base)
        flip[self.axis[9]] = -0.01
        d0, _ = XLS.funding_signal(self.axis, base, kind="neg")
        d1, _ = XLS.funding_signal(self.axis, flip, kind="neg")
        self.assertEqual(self.axis[9] in d0, self.axis[9] in d1,
                         "the day whose funding changed must not change its own allocation")
        self.assertNotEqual(self.axis[10] in d0, self.axis[10] in d1,
                            "the NEXT day must change, or the signal is not wired at all")

    def test_recovery_needs_n_recover_clear_days(self):
        fund = {d: 0.0001 for d in self.axis}
        fund[self.axis[4]] = -0.01
        defend, _ = XLS.funding_signal(self.axis, fund, kind="neg", n_recover=3)
        self.assertIn(self.axis[5], defend)
        self.assertIn(self.axis[7], defend, "must still defend while the clear-day count runs")
        self.assertNotIn(self.axis[8], defend, "and re-invest once it is met")

    def test_stale_policies_disagree_and_both_are_reachable(self):
        fund = {d: 0.0001 for d in self.axis}
        del fund[self.axis[5]]      # a hole: day 6's decision has no observation to read
        hold, c_hold = XLS.funding_signal(self.axis, fund, kind="neg", stale="hold")
        clos, c_clos = XLS.funding_signal(self.axis, fund, kind="neg", stale="defend")
        self.assertEqual(c_hold["blind_days"], c_clos["blind_days"])
        self.assertGreater(c_hold["blind_days"], 0)
        self.assertNotIn(self.axis[6], hold)
        self.assertIn(self.axis[6], clos, "fail-CLOSED must defend while blind")

    def test_warmup_is_counted_blind_not_silently_calm(self):
        fund = {d: 0.0001 + 0.00001 * i for i, d in enumerate(self.axis)}
        _, counts = XLS.funding_signal(self.axis, fund, kind="z", k=1.0)
        self.assertGreaterEqual(counts["blind_days"], 10,
                                "a z-score with too short a window is NOT MEASURED, not calm")

    def test_unknown_policies_and_kinds_refuse(self):
        fund = {d: 0.0001 for d in self.axis}
        with self.assertRaises(ValueError):
            XLS.funding_signal(self.axis, fund, kind="neg", stale="whatever")
        with self.assertRaises(ValueError):
            XLS.funding_signal(self.axis, fund, kind="nope")

    def test_breakeven_reports_never_fires_as_its_own_outcome(self):
        rets = [0.001] * 20
        B111.set_axis(self.axis)
        be = XLS.breakeven_bp(self.axis, _flat_panel(self.axis, rets), ["only"], set(), 0.0, 1.0)
        self.assertTrue(be is not None and math.isnan(be),
                        "a rule that never fires pays no toll — that is not a 0 bp budget")


class LoaderRefusals(unittest.TestCase):
    def test_empty_panel_dir_refuses_instead_of_returning_an_empty_panel(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises((RuntimeError, ValueError)):
                B111.load_real(Path(td))

    def test_missing_feed_refuses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(Exception):
                XLS.load_funding(Path(td))


if __name__ == "__main__":
    unittest.main()
