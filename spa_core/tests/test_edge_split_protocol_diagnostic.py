"""Acceptance for scripts/edge_split_protocol_diagnostic.py (registry ideas SPD / WUD).

Advisory-only research harness. Nothing here touches RiskPolicy v1.0, the kill-switch, the
live track, the fleet or `data/`. Every test builds its own synthetic panel: the real
aggressive-lab panel is ABSENT in a worktree by construction, and a test that skipped itself
there would make "not measured" indistinguishable from "passed".

The entry's claim is a claim about a MEASUREMENT PROTOCOL, so the load-bearing tests are about
the instrument, and each is mutated so it cannot pass vacuously:

  * `test_traced_path_is_bitwise_the_deployed_organ` — §5 needs the exposure the organ chose
    each day, and the deployed function returns the path and discards the decisions. The
    tracing copy is therefore held to the original BIT FOR BIT. If it drifted by one line,
    every "warm-up debt" in the entry would be a measurement of the drift.
  * `test_trace_identity_refuses_when_the_subject_moves` — its mutation. If the copy and the
    subject can disagree without the file refusing, the test above proves nothing.
  * `test_restart_and_carry_disagree_on_a_stateful_path` — the entry's whole premise, pinned
    as a property: a path that carries state gives DIFFERENT test-half numbers depending on
    whether the state crosses the boundary.
  * `test_restart_and_carry_agree_when_there_is_no_state_to_carry` — its other half, and the
    one that makes the first meaningful: on a book the guardian never acts on, the two
    protocols must agree EXACTLY. Otherwise the disagreement above would be bookkeeping, not
    state.
  * `test_replay_98_refuses_a_counter_that_disagrees_with_the_registry` and
    `test_replay_95_refuses_a_restart_arm_that_does_not_reproduce_the_published_column` — the
    two positive controls of the script, exercised in BOTH directions.
  * `test_census_refuses_when_the_screen_goes_blind` — the screen's own control. A screen that
    resolves nothing would print an empty flag list, and an empty flag list reads exactly like
    a clean bill of health. It must refuse instead.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: the date IS the subject. "2025-06-30" is the registry's canonical
# TRAIN/TEST boundary (#79), and this file measures what that boundary does to a stateful
# path; a relative date would be measuring a different boundary every day. The other
# literals are synthetic calendar axes for fixtures, not freshness windows — nothing here
# asks whether anything is stale, so no clock reaches this file.
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import edge_overlay_domain_admissibility as oda  # noqa: E402
import edge_split_protocol_diagnostic as spd  # noqa: E402
import edge_trim_proceeds_destination as tpd  # noqa: E402

PARAMS = {"lookback": 10, "vol_mult": 2.0, "derisk_frac": 0.0, "calm_mult": 1.2,
          "min_vol": 1e-5}
COST = 15.0 / 1e4


def _quiet_then_stormy(n: int = 400, seed: int = 9):
    """A book with a volatility burst just BEFORE the boundary and another just after.

    The burst before the boundary is what makes the two protocols differ: a carried path enters
    the test half already de-risked, a restarted one enters it flat. Without a burst there the
    test would compare two identical paths and pass for the wrong reason — which is why
    `test_the_fixture_actually_derisks` asserts the guardian really fires.
    """
    x = seed
    out = []
    for i in range(n):
        x = (1103515245 * x + 12345) % (1 << 31)
        u = x / (1 << 31) - 0.5
        stormy = 195 <= i < 215 or 260 <= i < 275
        out.append(0.0006 + u * (0.05 if stormy else 0.002))
    return out


def _flat(n: int = 400):
    """A book with no volatility structure at all: the guardian can never fire on it."""
    return [0.0004] * n


class SplitProtocolDiagnosticTest(unittest.TestCase):

    # ── the instrument ────────────────────────────────────────────────────────────────────
    def test_traced_path_is_bitwise_the_deployed_organ(self):
        eq = oda._equity(_quiet_then_stormy())
        for admit in (None, oda.oda_admission(eq, 90, 5.0, COST)):
            mine, trace = spd.traced_guarded_path(eq, admit, roundtrip_cost=COST, **PARAMS)
            theirs = oda.guarded_path(eq, admit, roundtrip_cost=COST, **PARAMS)
            self.assertEqual(mine, theirs, "the tracing copy is not the deployed organ")
            self.assertEqual(len(trace), len(eq) - 1)

    def test_trace_identity_refuses_when_the_subject_moves(self):
        """MUTATION of the test above: make the subject differ and the file must REFUSE."""
        eq = oda._equity(_quiet_then_stormy())
        original = oda.guarded_path
        try:
            oda.guarded_path = lambda equity, admit=None, **kw: [1.0] * len(equity)
            with self.assertRaises(spd.ControlFailed):
                spd.assert_trace_matches_subject(eq, None, roundtrip_cost=COST, **PARAMS)
        finally:
            oda.guarded_path = original
        # and it stops refusing once the subject is itself again
        spd.assert_trace_matches_subject(eq, None, roundtrip_cost=COST, **PARAMS)

    def test_the_fixture_actually_derisks(self):
        """The fixture's own positive control: no de-risk anywhere and every protocol test
        below would be comparing two copies of the same path."""
        eq = oda._equity(_quiet_then_stormy())
        _, trace = spd.traced_guarded_path(eq, None, roundtrip_cost=COST, **PARAMS)
        self.assertGreater(sum(1 for e in trace if e != 1.0), 0,
                           "the guardian never fires on this fixture — the protocol tests "
                           "would pass for the wrong reason")

    # ── the entry's premise, in both directions ───────────────────────────────────────────
    def test_restart_and_carry_disagree_on_a_stateful_path(self):
        rets = _quiet_then_stormy()
        cell = spd.Cell(rets, idx=209, window=90, cost=COST, params=PARAMS)
        self.assertNotEqual(cell.organ_restart, cell.organ_carry,
                            "restart and carry produced the same test half on a path that "
                            "carries state — then CARRY is a relabelled RESTART and the whole "
                            "entry is measuring nothing")
        self.assertGreater(cell.organ_exp_restart.count(1.0)
                           + cell.organ_exp_carry.count(1.0), 0)

    def test_restart_and_carry_agree_when_there_is_no_state_to_carry(self):
        """The half that makes the half above meaningful. Constant returns: the guardian never
        fires, so there is no state at the boundary, so the protocols MUST agree exactly."""
        cell = spd.Cell(_flat(), idx=209, window=90, cost=COST, params=PARAMS)
        self.assertEqual(cell.organ_restart, cell.organ_carry)
        self.assertEqual(cell.organ_exp_restart, cell.organ_exp_carry)

    def test_both_protocols_choose_the_same_k_because_train_is_identical(self):
        """The comparison is only an instrument if the two arms differ in ONE thing. K* is
        chosen on the train half, which both protocols share, so it cannot be the difference."""
        rets = _quiet_then_stormy()
        eq_train = oda._equity(rets[:210])
        self.assertEqual(spd.Cell(rets, 209, 90, COST, PARAMS).k,
                         spd.choose_k_on_train(eq_train, 90, COST, PARAMS))

    # ── the warm-up debt helper ───────────────────────────────────────────────────────────
    def test_decision_debt_reports_never_rather_than_a_number(self):
        self.assertEqual(spd.decision_debt([1, 1, 1], [1, 1, 1]), (0, 0))
        self.assertEqual(spd.decision_debt([0, 1, 1, 1], [1, 1, 1, 1]), (1, 1))
        # still disagreeing on the last compared day: NEVER, not "settled at the end"
        self.assertEqual(spd.decision_debt([1, 1, 0], [1, 1, 1]), (1, None))

    # ── the script's own positive controls, exercised both ways ───────────────────────────
    def test_replay_98_refuses_a_counter_that_disagrees_with_the_registry(self):
        dates, book_rets = self._tiny_panel()
        original = tpd.capped_bh

        def never_binds(book_rets, live, *, cap, cost, destination="prorata", cash_legs=1,
                        trace=None):
            if trace is not None:
                trace.extend([0.0] * len(book_rets[live[0]]))
            return [0.0] * len(book_rets[live[0]])

        try:
            tpd.capped_bh = never_binds
            with self.assertRaises(spd.ControlFailed):
                with redirect_stdout(io.StringIO()):
                    spd.section0a_replay_98(dates, book_rets)
        finally:
            tpd.capped_bh = original

    def test_replay_95_accepts_the_published_column_and_refuses_a_drifted_one(self):
        class Stub:
            def __init__(self, d):
                self._d = d

            @property
            def d_restart(self):
                return self._d

        good = {b: Stub(v[0] if v[0] is not None else float("nan"))
                for b, v in spd.KNOWN_95_SPLIT.items()}
        with redirect_stdout(io.StringIO()):
            spd.section0b_replay_95(good)          # must not raise

        bad = dict(good)
        bad["susde_spot"] = Stub(spd.KNOWN_95_SPLIT["susde_spot"][0] + 0.5)
        with self.assertRaises(spd.ControlFailed):
            with redirect_stdout(io.StringIO()):
                spd.section0b_replay_95(bad)

    def test_census_refuses_when_the_screen_goes_blind(self):
        """A screen that resolves nothing prints an empty flag list, and an empty flag list
        reads exactly like a clean bill of health. It has to refuse instead."""
        original = spd.corpus_boundary_names
        try:
            spd.corpus_boundary_names = lambda paths: set()
            with self.assertRaises(spd.ControlFailed):
                with redirect_stdout(io.StringIO()):
                    spd.section1_census(ROOT / "scripts")
        finally:
            spd.corpus_boundary_names = original

    def test_census_classifies_the_three_modules_whose_answer_is_published(self):
        scripts = ROOT / "scripts"
        paths = sorted(p for p in scripts.glob("edge_*.py")
                       if spd.BOUNDARY_LITERAL in p.read_text(encoding="utf-8"))
        names = spd.corpus_boundary_names(paths)
        self.assertIn("SPLIT_DATE", names)
        self.assertIn("TRAIN_END", names,
                      "the corpus spells the boundary TRAIN_END in most modules; a screen that "
                      "only knows the word SPLIT_DATE answers about spelling, not about state")
        want = {
            "edge_trim_proceeds_destination.py": "RE-RUNS ON THE SLICE",
            "edge_overlay_domain_admissibility.py": "RE-RUNS ON THE SLICE",
            "edge_mhfc_backtest.py": "OUTPUT-SPLIT (CARRY by construction)",
        }
        for module, verdict in want.items():
            self.assertEqual(spd.census_module(scripts / module, names)["verdict"], verdict,
                             f"{module} misclassified")

    def test_the_closure_step_of_the_name_search_is_load_bearing(self):
        """The closure exists so a module that ALIASES the boundary under a new name is still
        screened. On today's corpus it happens to add nothing — measured, not assumed: every
        boundary name in the tree also carries the literal, so the seed alone finds them. The
        control therefore runs on a synthetic two-module corpus, which is the only way to
        exercise the step at all; a step that no test can turn red is decoration, and the
        honest choice is to control it or delete it.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "edge_a.py").write_text('SPLIT_DATE = "2025-06-30"\n', encoding="utf-8")
            (root / "edge_b.py").write_text(
                "import edge_a\n"
                "CUT = edge_a.SPLIT_DATE\n"
                "def report(rets, dates):\n"
                "    idx = 0\n"
                "    for i, d in enumerate(dates):\n"
                "        if d <= CUT:\n"
                "            idx = i\n"
                "    te = rets[idx + 1:]\n"
                "    return rebuild_the_path(te)\n",
                encoding="utf-8")
            paths = sorted(root.glob("edge_*.py"))
            names = spd.corpus_boundary_names(paths)
            self.assertIn("CUT", names,
                          "the closure did not reach `CUT = edge_a.SPLIT_DATE`; edge_b would "
                          "then be filed as having no boundary at all, which reads like "
                          "'nothing to see here'")
            self.assertEqual(spd.census_module(root / "edge_b.py", names)["verdict"],
                             "RE-RUNS ON THE SLICE")
            self.assertEqual(
                spd.census_module(root / "edge_b.py", {"SPLIT_DATE"})["verdict"],
                "NO BOUNDARY-AWARE FUNCTION",
                "without the closure the same module comes out clean — that is the fail-OPEN "
                "direction this step exists to close")

    # ── refusals ──────────────────────────────────────────────────────────────────────────
    def test_split_index_refuses_a_boundary_that_empties_a_half(self):
        import datetime
        dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(10)]
        with self.assertRaises(ValueError):
            spd.split_index(dates, "2024-01-01")
        with self.assertRaises(ValueError):
            spd.split_index(dates, "2030-01-01")

    def test_json_output_under_data_is_refused(self):
        self.assertEqual(spd.main(["--json", "data/whatever.json"]), 2)

    def test_build_cells_refuses_an_all_dead_panel(self):
        import datetime
        dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(60)]
        with self.assertRaises(spd.ControlFailed):
            spd.build_cells(dates, {"dead": [0.0] * 60}, "2025-01-30", 90, COST, PARAMS)

    # ── helper ────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _tiny_panel():
        import datetime
        n = 40
        dates = [datetime.date(2025, 6, 1) + datetime.timedelta(days=i) for i in range(n)]
        return dates, {"a": [0.001] * n, "b": [0.0005] * n}


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
