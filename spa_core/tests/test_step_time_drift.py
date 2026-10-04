"""Батарея сравнителя «работа или среда» (заказ G87 п. 3, переоткрыт).

Каждый тест — либо положительный контроль РЕАЛЬНОЙ формы (равномерный множитель
02.10→03.10, контроль матрицы py3.11/py3.12 одного коммита), либо контроль в ОБРАТНУЮ
сторону: исход обязан меняться от порванного звена, и рвать надо каждое звено поимённо.

Часов в сравнителе нет ВОВСЕ: он читает отметки записи. Поэтому литеральных дат здесь
нет по построению — `FROZEN-DATE-OK` не нужен и не ставится. Литеральных pid нет:
ни одного процесса прибор не спрашивает. Отметки сцен ОТНОСИТЕЛЬНЫЕ (от `T0`).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from spa_core.monitoring import step_time_drift as D            # noqa: E402
from spa_core.monitoring.step_time_census import census_from_path  # noqa: E402

T0 = 1_000_000.0


def write_record(path, per_file, *, ended=True, cases_per_file=2):
    """Запись прогона, где файл `f` стои́т `per_file[f]` секунд, поровну по случаям."""
    lines = [json.dumps({"e": "session", "t": T0, "iso": "scene", "pid": 1,
                         "args": ["spa_core/tests/"]}, sort_keys=True)]
    t = T0 + 1.0
    for fname, total in sorted(per_file.items()):
        each = total / cases_per_file
        for i in range(cases_per_file):
            nid = "%s::t%d" % (fname, i)
            lines.append(json.dumps({"e": "start", "n": nid, "t": t}, sort_keys=True))
            t += each
            lines.append(json.dumps({"e": "ok", "n": nid, "t": t, "d": each / 2}, sort_keys=True))
    if ended:
        lines.append(json.dumps({"e": "end", "t": t, "status": 0,
                                 "started": 0, "finished": 0}, sort_keys=True))
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return census_from_path(pathlib.Path(path))


def scene(td, name, per_file, **kw):
    return write_record(pathlib.Path(td) / name, per_file, **kw)


#: 200 файлов по 2 с — довольно, чтобы квартили имели смысл (порог 100).
BASE = {"spa_core/tests/f%03d.py" % i: 2.0 + i * 0.01 for i in range(200)}


class AUniformMultiplierIsReadAsEnvironment(unittest.TestCase):
    """Форма 02.10→03.10 дословно: дорожают ВСЕ файлы и примерно одинаково."""

    def test_a_uniform_multiplier_above_the_control_is_named_environment(self):
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", {f: v * 1.39 for f, v in BASE.items()})
            r = D.drift(b, l)
        self.assertEqual(r["verdict"], "measured")
        self.assertAlmostEqual(r["median_ratio"], 1.39, places=2)
        self.assertLess(r["iqr"], 0.25)
        self.assertEqual(r["share_slower"], 1.0)
        self.assertEqual(D.read_as_work_or_environment(r, control_ratio=1.09),
                         "environment_beyond_runner_spread")

    def test_the_same_multiplier_below_the_control_is_within_runner_spread(self):
        """Обратная сторона: тот же РОД, но в пределах измеренного разброса парка."""
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", {f: v * 1.05 for f, v in BASE.items()})
            r = D.drift(b, l)
        self.assertEqual(D.read_as_work_or_environment(r, control_ratio=1.09),
                         "within_runner_spread")

    def test_without_a_same_commit_control_the_kind_is_unmeasured_not_guessed(self):
        """Звено «контроль» порвано: вывод обязан исчезнуть, а не стать догадкой."""
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", {f: v * 1.39 for f, v in BASE.items()})
            r = D.drift(b, l)
        self.assertEqual(D.read_as_work_or_environment(r, control_ratio=None),
                         "unmeasured:no_same_commit_control")


class TheCentreMustBeTheMedianNotTheMean(unittest.TestCase):
    """Сцена, на которой выбор середины РЕШАЕТ вердикт, а не украшает его.

    195 файлов подорожали на 5 % (внутри разброса парка), пятеро — в тридцать раз.
    Медиана говорит ×1.05 и отвечает «в пределах разброса»; среднее утягивается
    пятёркой до ×1.7 и объявило бы находку там, где её нет. Без этой сцены мутант
    «среднее вместо медианы» ВЫЖИВАЛ: на симметричных сценах они совпадают.
    """

    def setUp(self):
        files = sorted(BASE)
        later = {f: BASE[f] * 1.05 for f in files}
        for f in files[:5]:
            later[f] = BASE[f] * 30.0
        self.td = tempfile.TemporaryDirectory()
        b = scene(self.td.name, "b.jsonl", BASE)
        l = scene(self.td.name, "l.jsonl", later)
        self.r = D.drift(b, l)
        self.mean = sum(BASE[f] and later[f] / BASE[f] for f in files) / len(files)

    def tearDown(self):
        self.td.cleanup()

    def test_the_shape_is_uniform_so_the_centre_is_what_decides(self):
        self.assertLess(self.r["iqr"], 0.25)
        self.assertEqual(self.r["share_slower"], 1.0)

    def test_the_median_sits_inside_the_runner_spread(self):
        self.assertAlmostEqual(self.r["median_ratio"], 1.05, places=2)
        self.assertEqual(D.read_as_work_or_environment(self.r, control_ratio=1.09),
                         "within_runner_spread")

    def test_the_mean_would_have_called_a_finding_that_is_not_there(self):
        self.assertGreater(self.mean, 1.09)
        self.assertGreater(self.mean, self.r["median_ratio"] * 1.5)


class WorkGrowthHasADifferentSHAPE(unittest.TestCase):
    """Если подорожала РАБОТА, дорожает часть файлов — размах широкий."""

    def test_a_few_files_getting_much_slower_is_read_as_work_not_environment(self):
        later = dict(BASE)
        for i in range(10):                      # десять файлов в пять раз дороже
            later["spa_core/tests/f%03d.py" % i] *= 5.0
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", later)
            r = D.drift(b, l)
        self.assertEqual(r["verdict"], "measured")
        self.assertLess(r["share_slower"], 0.90)
        self.assertEqual(D.read_as_work_or_environment(r, control_ratio=1.09), "work_changed")

    def test_a_wide_spread_is_work_even_when_every_file_got_slower(self):
        """Доля «все подорожали» одна НЕ решает: род решает и размах."""
        later = {f: v * (1.1 + (i % 50) * 0.08) for i, (f, v) in enumerate(sorted(BASE.items()))}
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", later)
            r = D.drift(b, l)
        self.assertEqual(r["share_slower"], 1.0)
        self.assertGreater(r["iqr"], 0.25)
        self.assertEqual(D.read_as_work_or_environment(r, control_ratio=1.09), "work_changed")


class ThePopulationIsFilteredBeforeTheRatio(unittest.TestCase):
    def test_a_file_whose_case_count_changed_is_not_comparable(self):
        with tempfile.TemporaryDirectory() as td:
            b = write_record(pathlib.Path(td) / "b.jsonl", BASE, cases_per_file=2)
            l = write_record(pathlib.Path(td) / "l.jsonl", BASE, cases_per_file=3)
            self.assertEqual(D.comparable_files(b, l), set())
            self.assertEqual(D.drift(b, l)["verdict"], "unmeasured:too_few_comparable_files")

    def test_files_cheaper_than_the_floor_are_left_out_of_the_ratio(self):
        """На десятых долях секунды отношение меряет часы, а не стоимость."""
        tiny = {"spa_core/tests/tiny%03d.py" % i: 0.02 for i in range(200)}
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", {**BASE, **tiny})
            l = scene(td, "l.jsonl", {f: v * 1.39 for f, v in {**BASE, **tiny}.items()})
            r = D.drift(b, l)
        self.assertEqual(r["comparable_files"], len(BASE))

    def test_too_few_comparable_files_is_unmeasured_and_not_a_quartile(self):
        small = {"spa_core/tests/f%03d.py" % i: 2.0 for i in range(5)}
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", small)
            l = scene(td, "l.jsonl", {f: v * 1.4 for f, v in small.items()})
            r = D.drift(b, l)
        self.assertEqual(r["verdict"], "unmeasured:too_few_comparable_files")
        self.assertNotIn("median_ratio", r)


class RefusalsAreNamedAndNeverZero(unittest.TestCase):
    def test_an_absent_baseline_record_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            l = scene(td, "l.jsonl", BASE)
            r = D.drift(census_from_path(pathlib.Path(td) / "nope.jsonl"), l)
        self.assertTrue(r["verdict"].startswith("unmeasured:baseline_"), r["verdict"])

    def test_an_absent_later_record_is_unmeasured_and_names_which_side(self):
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            r = D.drift(b, census_from_path(pathlib.Path(td) / "nope.jsonl"))
        self.assertTrue(r["verdict"].startswith("unmeasured:later_"), r["verdict"])
        self.assertNotIn("baseline", r["verdict"])

    def test_the_kind_of_an_unmeasured_comparison_is_never_a_verdict(self):
        self.assertEqual(
            D.read_as_work_or_environment({"verdict": "unmeasured:later_record_absent"}, 1.09),
            "unmeasured:later_record_absent")


class ATruncatedSessionStillComparesButSaysSo(unittest.TestCase):
    """Стена оборванного прогона — нижняя граница; отношения по файлам целы."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.b = scene(self.td.name, "b.jsonl", BASE)
        self.l = scene(self.td.name, "l.jsonl", {f: v * 1.39 for f, v in BASE.items()}, ended=False)
        self.r = D.drift(self.b, self.l)

    def tearDown(self):
        self.td.cleanup()

    def test_the_comparison_is_still_measured(self):
        self.assertEqual(self.r["verdict"], "measured")
        self.assertAlmostEqual(self.r["median_ratio"], 1.39, places=2)

    def test_the_truncation_is_carried_into_the_result(self):
        self.assertTrue(self.r["base_ended"])
        self.assertFalse(self.r["later_ended"])

    def test_the_printout_names_the_lower_bound_a_human_reads(self):
        text = D.render(self.r, "b", "l", control_ratio=1.09)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", text)

    def test_a_complete_pair_does_not_claim_a_lower_bound(self):
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", {f: v * 1.39 for f, v in BASE.items()})
            text = D.render(D.drift(b, l), "b", "l", control_ratio=1.09)
        self.assertNotIn("НИЖНЯЯ ГРАНИЦА", text)


class ThePrintoutAndExitCodes(unittest.TestCase):
    def test_an_unmeasured_comparison_prints_the_reason_and_no_quartiles(self):
        text = D.render({"verdict": "unmeasured:too_few_comparable_files"}, "b", "l")
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("медиана", text)

    def test_the_printout_declares_what_it_does_not_report(self):
        with tempfile.TemporaryDirectory() as td:
            b = scene(td, "b.jsonl", BASE)
            l = scene(td, "l.jsonl", {f: v * 1.39 for f, v in BASE.items()})
            text = D.render(D.drift(b, l), "b", "l", control_ratio=1.09)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)
        self.assertIn("ADVISORY", text)

    def test_environment_beyond_spread_exits_one_and_within_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            pb = pathlib.Path(td) / "b.jsonl"
            pl = pathlib.Path(td) / "l.jsonl"
            pca = pathlib.Path(td) / "ca.jsonl"
            pcb = pathlib.Path(td) / "cb.jsonl"
            write_record(pb, BASE)
            write_record(pl, {f: v * 1.39 for f, v in BASE.items()})
            write_record(pca, BASE)
            write_record(pcb, {f: v * 1.09 for f, v in BASE.items()})
            over = D.main([str(pb), str(pl), "--control-a", str(pca),
                           "--control-b", str(pcb), "--json"])
            under = D.main([str(pb), str(pcb), "--control-a", str(pca),
                            "--control-b", str(pcb), "--json"])
        self.assertEqual(over, 1)
        self.assertEqual(under, 0)

    def test_an_unmeasured_run_exits_two(self):
        with tempfile.TemporaryDirectory() as td:
            pb = pathlib.Path(td) / "b.jsonl"
            write_record(pb, BASE)
            self.assertEqual(D.main([str(pb), str(pathlib.Path(td) / "nope.jsonl"), "--json"]), 2)


class ItReusesTheCensusRatherThanParsingAgain(unittest.TestCase):
    """Одно имя — один объект: второй разбор записи был бы вторым прибором."""

    def test_the_module_has_no_record_parser_of_its_own(self):
        src = pathlib.Path(D.__file__).read_text(encoding="utf-8")
        self.assertNotIn("json.loads", src)
        self.assertIn("census_from_path", src)

    def test_it_reads_the_record_only_through_the_census_door(self):
        import inspect
        names = {n for n, _ in inspect.getmembers(D) if not n.startswith("_")}
        self.assertIn("census_from_path", names)
        self.assertIn("by_file", names)


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
