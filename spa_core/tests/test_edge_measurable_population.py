"""Controls for registry #148 (MPC census) and #149 (LBS loss-budget sizing).

Every test here is a POSITIVE CONTROL: it either replays a defect this measurement actually
hit, or it breaks one named wire of the instrument and demands the instrument notice. None of
them asserts on a substring of the printed report (ADR-333) — each calls the real function on a
real scene built from a synthetic panel written to a temp directory, so the live `data/` tree is
never opened and the verdicts are reproducible on any host.

FROZEN-DATE-OK: synthetic-axis — the dates below are the panel's own axis, invented by
`_write_panel` to be a date axis at all. `scripts/edge_measurable_population.py` reads NO clock
(it imports no datetime/time and takes no `now`), so no verdict in this file can change because
the calendar moved. The word "window" that trips the detector here means the TRAIN/TEST halves
of a backtest, not a freshness window.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_measurable_population.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_mpc_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_mpc_under_test"] = m
    spec.loader.exec_module(m)
    return m


MPC = _mod()
_EPOCH = (2024, 3, 6)


def _dates(n: int) -> list:
    """`n` consecutive ISO dates. Built by arithmetic so the axis is data, not a constant."""
    import datetime as _dt
    d0 = _dt.date(*_EPOCH)
    return [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_panel(root: Path, books: dict) -> Path:
    """{book: [daily returns]} -> a panel directory the real loader accepts.

    Writes phase="backtest" rows with compounded equity_usd, which is what `load_panel` reads.
    """
    root.mkdir(parents=True, exist_ok=True)
    n = 1 + max(len(v) for v in books.values())
    axis = _dates(n)
    for book, rets in books.items():
        sub = root / book
        sub.mkdir(parents=True, exist_ok=True)
        eq = 100_000.0
        rows = [{"date": axis[0], "phase": "backtest", "equity_usd": eq}]
        for i, r in enumerate(rets, start=1):
            eq *= 1.0 + r
            rows.append({"date": axis[i], "phase": "backtest", "equity_usd": eq})
        (sub / "realized_series.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n")
    return root


def _scene(tmp: Path, *, n: int = 400, quiet_books: int = 4, loud_books: int = 6) -> Path:
    """A panel with `quiet_books` never-losing books and `loud_books` that take a real hit.

    The hit is placed in the FIRST half so it lands in TRAIN at the split used below: the whole
    point of #149 is that the sizer reads TRAIN drawdowns, so a scene whose drawdowns are all in
    TEST would measure nothing about the rule.
    """
    books = {}
    for i in range(quiet_books):
        books[f"quiet_{i}"] = [0.0002] * n
    for i in range(loud_books):
        r = [0.0003] * n
        for d in range(20, 20 + 10 + i):          # a distinct drawdown depth per loud book
            r[d] = -0.01
        books[f"loud_{i}"] = r
    return _write_panel(tmp / "panel", books)


def _scene_test_side(tmp: Path, *, n: int = 400, split_at: int = 200) -> Path:
    """A panel whose drawdowns land in the TEST half, in two sizes around the toll.

    The census is a statement about TEST, so a scene with all its drawdowns in TRAIN cannot
    tell whether the count is reading the toll or reading nothing (this scene exists because
    the first version of the toll test measured exactly that and passed 0 against 0).
    """
    books = {}
    for i in range(4):
        books[f"quiet_{i}"] = [0.0002] * n                   # no drawdown at all, ever
    for i in range(3):
        r = [0.0003] * n
        for d in range(split_at + 20, split_at + 23):
            r[d] = -0.001                                   # ~0.3 %: non-zero, BELOW the toll
        books[f"sub_{i}"] = r
    for i in range(3):
        r = [0.0003] * n
        for d in range(split_at + 30, split_at + 36 + i):
            r[d] = -0.01                                    # ~6 %: ABOVE the toll
        books[f"over_{i}"] = r
    return _write_panel(tmp / "panel_test_side", books)


class CensusTests(unittest.TestCase):
    """#148 §1 — the census must count by the toll, and must not call silence zero."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mpc_census_"))
        self.panel = _scene(self.tmp)
        self.split = _dates(400)[200]

    def test_a_frozen_book_is_unmeasured_not_measurable(self) -> None:
        """inv. #17: a book that never moved on TEST reports WHY, not a clean 0 % drawdown."""
        books = {f"quiet_{i}": [0.0002] * 400 for i in range(4)}
        books["frozen"] = [0.0002] * 200 + [0.0] * 200     # alive on TRAIN, dead on TEST
        for i in range(5):
            r = [0.0003] * 400
            for d in range(20, 32 + i):
                r[d] = -0.01
            books[f"loud_{i}"] = r
        panel = _write_panel(self.tmp / "frozen_panel", books)
        rep = MPC.book_measurability(panel, splits=(self.split,))
        row = next(r for r in rep["splits"][self.split]["rows"] if r["book"] == "frozen")
        self.assertEqual(row["moves_test"], 0)
        self.assertFalse(row["test_measurable"])
        self.assertIsNotNone(row["unmeasured"], "a frozen book reported as a measured zero")
        self.assertIn("frozen", rep["splits"][self.split]["frozen_on_test"])

    def test_the_count_is_decided_by_the_toll_and_moves_with_it(self) -> None:
        """Break the door: with a toll of 0 every mover counts, with a huge toll nobody does.

        This is what makes `n_measurable` a measurement rather than a label. The toll is read
        from the harness, so it is patched here rather than re-declared.
        """
        panel = _scene_test_side(self.tmp)
        base = MPC.book_measurability(panel, splits=(self.split,))
        n_base = base["splits"][self.split]["n_measurable"]
        self.assertEqual(n_base, 3, "scene is wrong: exactly the three `over_` books clear 96 bp")
        real = MPC.toll
        try:
            MPC.toll = lambda: 0.0
            loose = MPC.book_measurability(panel, splits=(self.split,))
            MPC.toll = lambda: 0.99
            tight = MPC.book_measurability(panel, splits=(self.split,))
        finally:
            MPC.toll = real
        self.assertEqual(loose["splits"][self.split]["n_measurable"], 6,
                         "a toll of zero must also admit the three sub-toll books")
        self.assertEqual(tight["splits"][self.split]["n_measurable"], 0)
        self.assertGreater(loose["splits"][self.split]["n_measurable"], n_base,
                           "the count did not move with the toll — it is not measuring it")

    def test_a_split_that_leaves_a_stub_half_REFUSES(self) -> None:
        """Half shorter than 60 days: refuse, never publish a drawdown measured on a stub."""
        with self.assertRaises(MPC.PopulationError):
            MPC.book_measurability(self.panel, splits=(_dates(400)[5],))


class ForwardTests(unittest.TestCase):
    """#148 §2 — an unreadable source is a third outcome, never a clean zero."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mpc_fwd_"))

    def _write(self, *, track: bool = True, blend: bool = True, dd_pct: float = 0.0) -> Path:
        root = self.tmp / "data"
        if track:
            (root / "rates_desk").mkdir(parents=True, exist_ok=True)
            axis, eq, rows = _dates(120), 100_000.0, []
            for d in axis:
                eq *= 1.0 + 0.0001
                rows.append({"date": d, "close_equity": eq, "daily_yield_usd": 10.0})
            (root / "rates_desk" / "equity_track.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n")
        if blend:
            (root / "swarm").mkdir(parents=True, exist_ok=True)
            (root / "swarm" / "blend_forward.json").write_text(json.dumps({
                "window": {"start": _dates(90)[0], "end": _dates(90)[-1]},
                "common_days": 86,
                "blend": {"apy_pct": 4.0, "max_dd_pct": dd_pct},
                "legs": {"susde": {"days": 86, "apy_pct": 12.0, "max_dd_pct": dd_pct}},
            }))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_a_missing_source_is_unmeasured_and_is_not_counted_as_clean(self) -> None:
        rep = MPC.forward_measurability(self._write(track=True, blend=False))
        missing = [r for r in rep["sources"] if r.get("unmeasured")]
        self.assertTrue(missing, "an absent blend file vanished from the report")
        self.assertEqual(rep["n_unmeasured"], len(missing))
        self.assertEqual(rep["n_judged"] + rep["n_unmeasured"], len(rep["sources"]))

    def test_no_readable_source_at_all_REFUSES(self) -> None:
        """"nothing is measurable" must not be returned when nothing was measured."""
        with self.assertRaises(MPC.PopulationError):
            MPC.forward_measurability(self._write(track=False, blend=False))

    def test_a_forward_drawdown_above_the_toll_IS_counted(self) -> None:
        """The opposite direction: the section is able to say YES, so its NO means something."""
        flat = MPC.forward_measurability(self._write(dd_pct=0.0))
        loud = MPC.forward_measurability(self._write(dd_pct=5.0))
        self.assertEqual(flat["n_measurable"], 0)
        self.assertGreaterEqual(loud["n_measurable"], 2)


class CapWeightTests(unittest.TestCase):
    """The water-fill. Replays the oscillation this instrument actually hit on the real panel."""

    def test_several_names_over_the_ceiling_converge_and_respect_it(self) -> None:
        """The defect: recomputing the capped set each pass re-spilled onto already-capped
        names, so the fill never converged and the real panel got a refusal instead of weights.
        """
        raw = {f"huge_{i}": 1_000.0 for i in range(4)} | {f"small_{i}": 1.0 for i in range(6)}
        w = MPC.cap_weights(raw, 0.20)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        self.assertLessEqual(max(w.values()), 0.20 + 1e-9)
        for i in range(4):
            self.assertAlmostEqual(w[f"huge_{i}"], 0.20, places=9)

    def test_capping_that_takes_TWO_rounds_converges(self) -> None:
        """The scene where the real defect lives — and the first version of this file missed it.

        One round of capping is self-correcting even in the buggy editon: the spill lands on
        names that are still far below the ceiling. The oscillation needs a SECOND round, i.e.
        a name pushed over the ceiling BY the first spill — then the old code hands spill back
        to names already sitting on the ceiling and never converges. The mutation prober
        survived the one-round scene, which is how this gap was found rather than argued.
        """
        raw = {"a": 1e6, "b": 1e6, "c": 100.0}
        raw.update({f"d{i}": 1.0 for i in range(7)})
        w = MPC.cap_weights(raw, 0.20)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
        self.assertLessEqual(max(w.values()), 0.20 + 1e-9)
        for k in ("a", "b", "c"):
            self.assertAlmostEqual(w[k], 0.20, places=9,
                                   msg=f"{k} should sit on the ceiling after two rounds")

    def test_a_universe_too_small_for_the_ceiling_REFUSES(self) -> None:
        with self.assertRaises(MPC.PopulationError):
            MPC.cap_weights({"a": 1.0, "b": 1.0}, 0.20)

    def test_non_positive_raw_weights_REFUSE(self) -> None:
        with self.assertRaises(MPC.PopulationError):
            MPC.cap_weights({"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0, "e": 0.0}, 0.50)


class LbsTests(unittest.TestCase):
    """#149 — the floor, the budget, the toll and the placebo, each broken on purpose."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mpc_lbs_"))
        self.panel = _scene(self.tmp)
        self.split = _dates(400)[200]
        e = MPC.ens()
        self.axis, self.rets, self.books = e.plb_load(self.panel)
        self.hi = MPC.split_index(self.axis, self.split)

    def test_the_budget_is_read_from_the_kill_switch_not_written_down(self) -> None:
        """A second copy of the SOFT rung is how a rung drifts from the stop enforcing it."""
        sys.path.insert(0, str(ROOT))
        from spa_core.governance import kill_switch
        self.assertAlmostEqual(MPC.loss_budget(),
                               kill_switch.SOFT_DERISK_THRESHOLD_PCT / 100.0, places=12)

    def test_the_denominator_floor_is_what_bounds_a_never_losing_book(self) -> None:
        """Break the floor and the quiet book takes the panel — the #128 leak, measured.

        Floored weights are capped at the ceiling; unfloored 1/maxDD gives a book whose TRAIN
        drawdown is ~0 a weight orders of magnitude larger before any cap can speak.
        """
        got = MPC.lbs_weights(self.rets, self.books, train_hi=self.hi)
        quiet = [b for b in self.books if b.startswith("quiet_")]
        self.assertEqual(sorted(got["denominator_floored"]), sorted(quiet),
                         "the floor did not catch exactly the never-losing books")
        unfloored = {b: 1.0 / max(abs(MPC.ens().perf(list(self.rets[b][:self.hi]))["maxdd"]),
                                  1e-12) for b in self.books}
        share_unfloored = sum(unfloored[b] for b in quiet) / sum(unfloored.values())
        share_floored = sum(got["weights"][b] for b in quiet)
        self.assertGreater(share_unfloored, 0.999,
                           "scene is wrong: the quiet books must dominate WITHOUT the floor")
        self.assertLess(share_floored, share_unfloored,
                        "the floor changed nothing — it is not bounding anything")

    def test_the_toll_is_charged_once_not_every_day(self) -> None:
        w = {b: 1.0 / len(self.books) for b in self.books}
        n = len(self.axis) - self.hi
        free = MPC.arm(self.rets, w, lo=self.hi, hi=len(self.axis), roundtrip=0.0)
        paid = MPC.arm(self.rets, w, lo=self.hi, hi=len(self.axis), roundtrip=0.01)
        # one charge of 1 % over n days moves the annualised rate by ~ (365/n) * 1 %, not n times
        drop = free["apy"] - paid["apy"]
        self.assertLess(drop, 0.01 * 365.0 / n * 3.0, "the toll looks charged more than once")
        self.assertGreater(drop, 0.0, "the toll was not charged at all")

    def test_cash_pays_exactly_zero_and_scales_the_tail(self) -> None:
        w = {b: 1.0 / len(self.books) for b in self.books}
        full = MPC.arm(self.rets, w, lo=self.hi, hi=len(self.axis), roundtrip=0.0)
        half = MPC.arm(self.rets, w, lo=self.hi, hi=len(self.axis), roundtrip=0.0, deployed=0.5)
        self.assertAlmostEqual(half["maxdd"], full["maxdd"] * 0.5, delta=full["maxdd"] * 0.05)
        self.assertEqual(half["deployed"], 0.5)

    def test_calmar_is_REFUSED_when_the_denominator_is_below_the_toll(self) -> None:
        """#129: a quotient over a degenerate denominator is not a risk-adjusted number."""
        quiet = {b: (1.0 / 4 if b.startswith("quiet_") else 0.0) for b in self.books}
        loud = {b: (1.0 / 6 if b.startswith("loud_") else 0.0) for b in self.books}
        self.assertTrue(MPC.arm(self.rets, quiet, lo=self.hi, hi=len(self.axis))["calmar_refused"])
        self.assertFalse(MPC.arm(self.rets, loud, lo=0, hi=self.hi)["calmar_refused"],
                         "a real drawdown was refused — the flag is stuck on")

    def test_the_placebo_permutes_and_refuses_to_be_thin(self) -> None:
        w = MPC.lbs_weights(self.rets, self.books, train_hi=self.hi)["weights"]
        pl = MPC.placebo_percentile(self.rets, w, lo=self.hi, hi=len(self.axis), n=50)
        self.assertEqual(pl["n"], 50)
        self.assertTrue(0.0 <= pl["pct_calmar"] <= 100.0)
        with self.assertRaises(MPC.PopulationError):
            # more distinct permutations requested than a 3-name vector can supply
            MPC.placebo_percentile(self.rets, {b: 1 / 3 for b in self.books[:3]},
                                   lo=self.hi, hi=len(self.axis), n=10_000)

    def test_the_identity_exclusion_is_observable_on_an_EXHAUSTIBLE_space(self) -> None:
        """Three names have 3! = 6 orderings, of which exactly 5 are not the identity.

        This is the only place the identity guard can be SEEN: with ten books the identity is
        one draw in 3 628 800, so deleting the guard changes nothing measurable at n = 300 —
        the prober survived that scene and was right to. Here the space is exhaustible, so
        "5 available" IS the guard, and asking for 6 must refuse.
        """
        three = {b: 1 / 3 for b in self.books[:3]}
        ok = MPC.placebo_percentile(self.rets, three, lo=self.hi, hi=len(self.axis), n=5)
        self.assertEqual(ok["n"], 5, "the non-identity orderings of three names are exactly 5")
        with self.assertRaises(MPC.PopulationError):
            MPC.placebo_percentile(self.rets, three, lo=self.hi, hi=len(self.axis), n=6)

    def test_an_all_cash_arm_earns_exactly_zero(self) -> None:
        """A research arm that pays its idle capital an invented floor beats a benchmark it
        made up. The prober found this hole: scaling `deployed` was checked, the RATE cash
        earns was not. Measured at the only point where the rate is the whole answer.
        """
        w = {b: 1.0 / len(self.books) for b in self.books}
        cash = MPC.arm(self.rets, w, lo=self.hi, hi=len(self.axis), roundtrip=0.0, deployed=0.0)
        self.assertEqual(cash["apy"], 0.0, "idle capital earned something")
        self.assertEqual(cash["maxdd"], 0.0, "idle capital lost something")

    def test_the_placebo_never_scores_the_arm_against_itself(self) -> None:
        """The identity permutation must be excluded, and that is COUNTED, not assumed.

        Needs a scene where the arm's Calmar is reachable by exactly ONE assignment, so a tie
        can only be the identity. The default scene is NOT that scene — its four quiet books
        carry byte-identical series, so permuting weights among them rebuilds the same
        portfolio and ties legitimately (measured: 3 ties). The premise is therefore built
        here and ASSERTED before the claim is made, rather than assumed.
        """
        panel = _write_panel(self.tmp / "distinct", {
            f"b{i}": [0.0001 * (i + 1) if d % (7 + i) else -0.004 * (i + 1)
                      for d in range(400)] for i in range(10)})
        axis, rets, books = MPC.ens().plb_load(panel)
        hi = MPC.split_index(axis, self.split)
        w = MPC.cap_weights({b: float(i + 1) for i, b in enumerate(books)}, 0.20)
        self.assertEqual(len(set(tuple(rets[b]) for b in books)), len(books),
                         "scene is wrong: the books must have pairwise distinct series")
        pl = MPC.placebo_percentile(rets, w, lo=hi, hi=len(axis), n=300)
        self.assertEqual(pl["ties_with_actual"], 0,
                         "a placebo sample equals the arm — the identity was not excluded")

    def test_the_placebo_is_not_just_the_arm_repeated(self) -> None:
        """A placebo that keeps the identity permutation would score the arm against itself."""
        w = MPC.lbs_weights(self.rets, self.books, train_hi=self.hi)["weights"]
        pl = MPC.placebo_percentile(self.rets, w, lo=self.hi, hi=len(self.axis), n=200)
        self.assertLess(pl["pct_calmar"], 100.0 - 1e-9,
                        "every permutation scored at or below the arm — identity not excluded")

    def test_the_report_names_the_quiet_and_measurable_control_arms(self) -> None:
        """The two arms that decide #149 must exist and be built from the FLOORED set.

        Wire check, not a substring check: the QUIET arm's return series has to equal an equal
        weighting of exactly the floored books, recomputed here independently.
        """
        rep = MPC.lbs_report(self.panel, splits=(self.split,), placebo_n=50)
        s = rep["splits"][self.split]
        quiet_arm = next(v for k, v in s["arms"].items() if k.startswith("КОНТРОЛЬ QUIET"))
        expect = MPC.arm(self.rets,
                         {b: (1.0 / len(s["denominator_floored"])
                              if b in s["denominator_floored"] else 0.0) for b in self.books},
                         lo=self.hi, hi=len(self.axis))
        self.assertAlmostEqual(quiet_arm["apy"], expect["apy"], places=12)
        self.assertAlmostEqual(quiet_arm["maxdd"], expect["maxdd"], places=12)
        self.assertTrue(any(k.startswith("КОНТРОЛЬ MEAS") for k in s["arms"]))
        self.assertAlmostEqual(s["quiet_weight"],
                               sum(s["weights_lbs"][b] for b in s["denominator_floored"]),
                               places=12)

    def test_the_identity_test_against_inverse_sigma_is_a_real_number(self) -> None:
        """#149 lives or dies on this: a sizer ranking books like an entry already in the
        registry IS that entry. A constant vector has no rank correlation and must say so
        rather than return 0.0.
        """
        rep = MPC.lbs_report(self.panel, splits=(self.split,), placebo_n=50)
        rho = rep["splits"][self.split]["identity_vs_inv_sigma_raw"]
        self.assertIsInstance(rho, float)
        self.assertTrue(-1.0 - 1e-9 <= rho <= 1.0 + 1e-9)

    def test_the_whole_report_is_deterministic(self) -> None:
        a = MPC.lbs_report(self.panel, splits=(self.split,), placebo_n=100)
        b = MPC.lbs_report(self.panel, splits=(self.split,), placebo_n=100)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str),
                         json.dumps(b, sort_keys=True, default=str))

    def test_it_stays_advisory(self) -> None:
        self.assertTrue(MPC.IS_ADVISORY)
        self.assertTrue(MPC.OUTSIDE_RISKPOLICY)
        import ast
        src = SCRIPT.read_text()
        tree = ast.parse(src)
        # The name appears in the module docstring, in the sentence promising the track is
        # never opened. Asserting on the raw source would therefore fail on the promise
        # itself, so the claim is measured where it CAN be false: every string literal in the
        # file except that one docstring node. The node is identified by POSITION (the first
        # statement of the module), not by comparing text — `ast.get_docstring` returns a
        # cleaned, dedented copy that never equals the raw constant.
        self.assertIn("equity_curve_daily", ast.get_docstring(tree) or "",
                      "the advisory promise left the docstring")
        head = tree.body[0]
        doc_node = head.value if isinstance(head, ast.Expr) else None
        for node in ast.walk(tree):
            if node is doc_node:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn("equity_curve_daily", node.value,
                                 "an advisory probe names the live track in CODE")
        for forbidden in ("atomic_save", "open(", "write_text", "mkdir"):
            self.assertNotIn(f".{forbidden}", src.replace("Path(", ""),
                             f"a read-only probe calls {forbidden}")


if __name__ == "__main__":
    unittest.main()
