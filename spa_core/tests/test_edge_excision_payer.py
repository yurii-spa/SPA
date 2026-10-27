"""Controls for scripts/edge_excision_payer.py — registry ideas #145 EDX and #146 PYD.

FROZEN-DATE-OK: даты здесь — САМ ПРЕДМЕТ, а не якорь свежести. Это синтетическая ось дат
панели (значения данных, которые загрузчик читает как ряд); ни одна проверка в этом пути не
судит о «протухло / свежо», понятия свежести у него нет вовсе, поэтому сдвиг календаря не
может уронить ни один тест этого файла.

Каждый тест — положительный контроль: он краснеет на ОДНОЙ названной порче и зелен иначе.
Пять мутаций, которые эти тесты обязаны убить (и убивают — прогон в журнале W44):
  M1 вырез имени, которого в панели нет, становится молчаливым no-op
      (-> «вырез ничего не меняет» напечатано без выреза);
  M2 `axis_identity` перестаёт отказывать на РАЗНЫХ осях (смена окна выдаётся за эффект выреза);
  M3 дырка в границе N-ног становится нулём вместо названной причины (инв. #17);
  M4 PYD-веса делятся по КНИГАМ, а не по классам (правило вырождается в EW и «подтверждается»);
  M5 плацебо теряет детерминизм / профиль (перцентиль перестаёт быть воспроизводимым числом).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_excision_payer.py"


def _mod():
    spec = importlib.util.spec_from_file_location("edge_excision_payer_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _mod()


def write_panel(root: Path, books: dict) -> Path:
    """books = {name: [(date, equity), ...]} -> a panel dir the real loaders accept."""
    root.mkdir(parents=True, exist_ok=True)
    for name, rows in books.items():
        d = root / name
        d.mkdir(exist_ok=True)
        (d / "realized_series.jsonl").write_text(
            "\n".join(json.dumps({"date": dt, "equity_usd": eq, "phase": "backtest"})
                      for dt, eq in rows) + "\n"
        )
    return root


def ramp(n: int, step: float = 0.0004, start_day: int = 1) -> list:
    """A gently rising series on a synthetic axis; no move anywhere near JUMP_REFUSE."""
    out, eq = [], 100000.0
    for i in range(n):
        eq *= 1.0 + step
        out.append((f"2024-{(start_day + i) // 28 + 1:02d}-{(start_day + i) % 28 + 1:02d}", eq))
    return out


def axis_of(n: int, start_day: int = 1) -> list:
    return [d for d, _ in ramp(n, start_day=start_day)]


class ShadowPanelIsTheSameBytes(unittest.TestCase):
    """M1 — an excision that did not happen must never be reported as one."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.real = write_panel(Path(self.tmp.name) / "real",
                                {"a": ramp(80), "b": ramp(80), "c": ramp(80)})

    def tearDown(self):
        self.tmp.cleanup()

    def test_dropping_a_name_absent_from_the_panel_is_an_error_not_a_no_op(self):
        with self.assertRaises(M.ExcisionError) as ctx:
            M.build_shadow_panel(self.real, ("not_a_book",), Path(self.tmp.name) / "s1")
        self.assertIn("not_a_book", str(ctx.exception))

    def test_the_shadow_panel_holds_every_other_book_and_the_dropped_name_is_returned(self):
        shadow, dropped = M.build_shadow_panel(self.real, ("b",), Path(self.tmp.name) / "s2")
        self.assertEqual(dropped, ["b"])
        self.assertEqual(sorted(p.parent.name for p in shadow.glob("*/realized_series.jsonl")),
                         ["a", "c"])

    def test_the_excised_run_reads_the_identical_bytes(self):
        """A copy could drift; the comparison then would not be about the excision."""
        shadow, _ = M.build_shadow_panel(self.real, ("b",), Path(self.tmp.name) / "s3")
        for book in ("a", "c"):
            self.assertEqual((shadow / book / "realized_series.jsonl").read_bytes(),
                             (self.real / book / "realized_series.jsonl").read_bytes())

    def test_an_excision_that_leaves_fewer_than_two_books_refuses(self):
        with self.assertRaises(M.ExcisionError):
            M.build_shadow_panel(self.real, ("a", "b"), Path(self.tmp.name) / "s4")


class AxisIdentityIsMeasuredNotAssumed(unittest.TestCase):
    """M2 — the whole comparison rests on both runs judging the same days."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_axes_are_reported_as_identical_with_their_numbers(self):
        real = write_panel(Path(self.tmp.name) / "same",
                           {"a": ramp(80), "b": ramp(80), "c": ramp(80)})
        shadow, _ = M.build_shadow_panel(real, ("b",), Path(self.tmp.name) / "sh")
        out = M.axis_identity(real, shadow)
        self.assertTrue(out["identical"])
        self.assertEqual(out["grew_by"], 0)
        self.assertEqual(out["full_days"], out["exc_days"])

    def test_an_excision_that_enlarges_the_axis_REFUSES(self):
        """POSITIVE CONTROL replaying the confound: the short book is the one removed.

        `common_axis` intersects, so dropping the book that was clipping the window ENLARGES
        it. Printing a difference measured over more days as the effect of the excision is
        exactly the silent error this guard exists for.
        """
        long_rows, short_rows = ramp(90), ramp(70)
        real = write_panel(Path(self.tmp.name) / "ragged",
                           {"a": long_rows, "b": short_rows, "c": long_rows})
        shadow, _ = M.build_shadow_panel(real, ("b",), Path(self.tmp.name) / "sh2")
        with self.assertRaises(M.ExcisionError) as ctx:
            M.axis_identity(real, shadow)
        msg = str(ctx.exception)
        self.assertIn("changed the judged axis", msg)
        self.assertIn("Refusing", msg)


class FrontierShapeKeepsTheThirdOutcome(unittest.TestCase):
    """M3 — a rung that was not admitted is a named reason, never a zero (inv. #17)."""

    @staticmethod
    def rows(apys, admitted=True):
        out = []
        for i, a in enumerate(apys, start=1):
            if a is None:
                out.append({"n": i, "admitted": 0, "train": None, "test": None,
                            "reason": f"no subset of size {i} under the cap"})
            else:
                out.append({"n": i, "admitted": 3, "train": {"apy": a}, "test": {"apy": a}})
        return out

    def test_a_falling_frontier_is_called_falling(self):
        s = M.nlf_shape(self.rows([0.3, 0.2, 0.1, 0.05]), "test")
        self.assertTrue(s["monotone_down"])
        self.assertEqual(s["sign"], "down")
        self.assertEqual(s["best_n"], 1)

    def test_a_rising_frontier_is_called_rising_so_a_sign_flip_is_detectable(self):
        s = M.nlf_shape(self.rows([0.05, 0.1, 0.2, 0.3]), "test")
        self.assertTrue(s["monotone_up"])
        self.assertEqual(s["sign"], "up")
        self.assertEqual(s["best_n"], 4)

    def test_an_unadmitted_rung_becomes_a_hole_with_a_reason_and_not_a_zero(self):
        s = M.nlf_shape(self.rows([0.3, None, 0.1, 0.05]), "test")
        self.assertEqual([h["n"] for h in s["holes"]], [2])
        self.assertIn("under the cap", s["holes"][0]["reason"])
        self.assertNotIn(0.0, [v for _, v in s["series"]])
        self.assertEqual([n for n, _ in s["series"]], [1, 3, 4])

    def test_too_few_admitted_rungs_is_unmeasured_not_a_verdict(self):
        s = M.nlf_shape(self.rows([0.3, None, None, None]), "test")
        self.assertIsNone(s["series"])
        self.assertIn("admitted rungs", s["unmeasured"])


class PayerWeightsSplitByClassNotByBook(unittest.TestCase):
    """M4 — if the split is per book, PYD degenerates into EW and 'confirms itself'."""

    def test_each_class_gets_one_over_n_classes_regardless_of_its_size(self):
        groups = {"x": ["a", "b", "c"], "y": ["d"], "z": ["e", "f"]}
        w = M.partition_weights(groups)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=12)
        self.assertAlmostEqual(w["d"], 1 / 3, places=12)
        self.assertAlmostEqual(w["a"], (1 / 3) / 3, places=12)
        self.assertAlmostEqual(w["e"], (1 / 3) / 2, places=12)
        # the decisive difference from equal weight over books:
        self.assertNotAlmostEqual(w["d"], 1 / 6, places=6)

    def test_one_class_per_book_is_exactly_equal_weight_the_degenerate_case(self):
        groups = {b: [b] for b in "abcdef"}
        w = M.partition_weights(groups)
        for v in w.values():
            self.assertAlmostEqual(v, 1 / 6, places=12)

    def test_no_classes_refuses_instead_of_weighting_nothing(self):
        with self.assertRaises(M.ExcisionError):
            M.partition_weights({})

    def test_the_declared_taxonomy_is_read_from_the_roster_and_an_unknown_book_is_not_bucketed(self):
        cls = M.payer_classes(["susde_dn", "points_farm", "no_such_book"])
        self.assertEqual(cls["unclassified"], ["no_such_book"])
        self.assertNotIn("no_such_book", cls["shape"])
        self.assertEqual(cls["shape"]["susde_dn"], "funding_flip")
        self.assertEqual(cls["shape"]["points_farm"], "incentive_decay")
        for members in cls["groups"].values():
            self.assertNotIn("no_such_book", members)


class PlaceboIsDeterministicAndKeepsTheProfile(unittest.TestCase):
    """M5 — the percentile is only a number if the control is reproducible."""

    BOOKS = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    PROFILE = [3, 3, 2, 1, 1]

    def test_the_same_seed_gives_the_same_partitions_on_every_run(self):
        one = M.placebo_partitions(self.BOOKS, self.PROFILE, n=50, seed=7)
        two = M.placebo_partitions(self.BOOKS, self.PROFILE, n=50, seed=7)
        self.assertEqual(one, two)

    def test_a_different_seed_gives_a_different_draw(self):
        one = M.placebo_partitions(self.BOOKS, self.PROFILE, n=50, seed=7)
        two = M.placebo_partitions(self.BOOKS, self.PROFILE, n=50, seed=8)
        self.assertNotEqual(one, two)

    def test_every_placebo_carries_the_identical_size_profile_and_every_book_once(self):
        for g in M.placebo_partitions(self.BOOKS, self.PROFILE, n=100, seed=3):
            self.assertEqual(sorted((len(v) for v in g.values()), reverse=True), self.PROFILE)
            flat = [b for v in g.values() for b in v]
            self.assertEqual(sorted(flat), sorted(self.BOOKS))

    def test_the_placebos_are_distinct_so_the_distribution_is_not_one_point_repeated(self):
        got = M.placebo_partitions(self.BOOKS, self.PROFILE, n=200, seed=11)
        keys = {tuple(sorted(tuple(v) for v in g.values())) for g in got}
        self.assertEqual(len(keys), len(got))

    def test_a_profile_that_does_not_cover_the_books_refuses(self):
        with self.assertRaises(M.ExcisionError):
            M.placebo_partitions(self.BOOKS, [3, 3, 2], n=10, seed=1)


class RefusedAndFalseStayDistinguishable(unittest.TestCase):
    """inv. #17 on both tallies: 'measured false' must never read as 'not measured'."""

    def test_tub_tally_counts_false_and_none_separately(self):
        a = {"oos": {
            "r1": {"ew": {"test": {"three_vs_ew_live": {"all_three": True},
                                   "calmar_degenerate": None, "apy_net": 0.1}}},
            "r2": {"ew": {"test": {"three_vs_ew_live": {"all_three": False},
                                   "calmar_degenerate": None, "apy_net": 0.1}}},
            "r3": {"ew": {"test": {"three_vs_ew_live": {},
                                   "calmar_degenerate": "below toll", "apy_net": 0.1}}},
        }}
        t = M.tub_tally(a)
        self.assertEqual(t["n_rows"], 3)
        self.assertEqual(t["all_three_true"], 1)
        self.assertEqual(t["all_three_unmeasured"], 1)
        self.assertEqual(t["calmar_refused"], 1)

    def test_a_refused_delta_has_sign_None_and_not_zero(self):
        gz = {"zeros": {"ew10": {
            "raw": {"maxdd_frac": 0.004},
            "vol": {"maxdd_frac": 0.004, "switches": 3},
            "reactive": {"maxdd_frac": 0.004, "switches": 1},
            "delta_vol": {"delta_calmar": None, "status": "refused", "reason": "below toll"},
            "delta_reactive": {"delta_calmar": -0.5, "status": "measured", "reason": None},
        }}}
        s = M.gz_signs(gz)
        self.assertIsNone(s["ew10/delta_vol"]["sign"])
        self.assertEqual(s["ew10/delta_vol"]["status"], "refused")
        self.assertEqual(s["ew10/delta_reactive"]["sign"], "-")
        # the denominator the delta stands on travels with it
        self.assertAlmostEqual(s["ew10/delta_reactive"]["base_maxdd"], 0.004, places=12)

    def test_a_flip_is_only_claimed_when_both_sides_were_measured(self):
        full = {"k_star": 6, "gz": {"z/delta_vol": {"sign": "-", "delta_calmar": -0.2}},
                "tub": {"all_three_true": 5, "calmar_refused": 3, "n_rows": 12, "rows": []},
                "nlf_shapes": {}}
        exc = {"k_star": 6, "gz": {"z/delta_vol": {"sign": None, "delta_calmar": None}},
               "tub": {"all_three_true": 0, "calmar_refused": 10, "n_rows": 12, "rows": []},
               "nlf_shapes": {}}
        fl = M.flip_verdicts(full, exc)
        self.assertFalse(fl["#132 GZ dCalmar"]["z/delta_vol"]["flipped"])
        self.assertTrue(fl["#141 TUB all_three"]["flipped"])
        self.assertFalse(fl["#131 ASE k*"]["flipped"])

    def test_a_real_sign_change_is_claimed(self):
        full = {"k_star": 6, "gz": {"z/delta_vol": {"sign": "-", "delta_calmar": -0.2}},
                "tub": {"all_three_true": 0, "calmar_refused": 1, "n_rows": 12, "rows": []},
                "nlf_shapes": {}}
        exc = {"k_star": 5, "gz": {"z/delta_vol": {"sign": "+", "delta_calmar": 2.3}},
               "tub": {"all_three_true": 0, "calmar_refused": 1, "n_rows": 12, "rows": []},
               "nlf_shapes": {}}
        fl = M.flip_verdicts(full, exc)
        self.assertTrue(fl["#132 GZ dCalmar"]["z/delta_vol"]["flipped"])
        self.assertTrue(fl["#131 ASE k*"]["flipped"])
        self.assertFalse(fl["#141 TUB all_three"]["flipped"])


class AdvisoryContractHolds(unittest.TestCase):
    """The iron invariant of the directive, asserted and not merely written in a docstring."""

    def test_the_module_declares_itself_advisory_and_outside_riskpolicy(self):
        self.assertTrue(M.IS_ADVISORY)
        self.assertTrue(M.OUTSIDE_RISKPOLICY)

    def test_the_policy_ceiling_is_only_read_never_changed(self):
        self.assertAlmostEqual(M.POLICY_CAP, 0.20, places=12)
        src = SCRIPT.read_text()
        self.assertNotIn("POLICY_CAP =", src.split("POLICY_CAP = 0.20", 1)[1])

    @staticmethod
    def code_only() -> str:
        """The script's CODE with every comment and string literal removed.

        Grepping the raw file answers "does the file MENTION this", which is a different
        question: the module docstring names `data/equity_curve_daily.json` precisely in order
        to say it is never opened, and a raw grep would read that promise as its violation.
        """
        import io
        import tokenize
        keep = []
        with open(SCRIPT, "rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                                tokenize.ENCODING, tokenize.ENDMARKER):
                    continue
                keep.append(tok.string)
        return " ".join(keep)

    def test_the_code_never_touches_the_live_track_risk_or_execution(self):
        code = self.code_only()
        for forbidden in ("equity_curve_daily", "atomic_save", "execution"):
            self.assertNotIn(forbidden, code,
                             f"{forbidden} must not appear in CODE: §1/§2 only print")
        self.assertNotIn("spa_core . risk", code)

    def test_the_stripper_itself_is_not_vacuous(self):
        """Positive control: the forbidden names DO appear in the raw file, and are prose."""
        raw = SCRIPT.read_text()
        self.assertIn("equity_curve_daily", raw)
        self.assertIn("RiskPolicy", raw)
        self.assertNotIn("equity_curve_daily", self.code_only())

    def test_the_code_opens_no_file_for_writing(self):
        code = self.code_only()
        for forbidden in (". write_text", ". write_bytes", "atomic_save", "json . dump "):
            self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
