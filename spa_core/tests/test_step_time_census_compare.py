"""Положительные контроли сравнения двух переписей (ADR-677, заказ G108 п. 3).

Каждый тест ниже воспроизводит ОДНО названное порванное звено и краснеет на нём.
Батарея, никогда не видевшая настоящей поломки, есть украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

**Зачем мера вообще.** ADR-534 измерил ОДНУ сессию ноги 3.12, строки `end` у неё не
нашёл и честно назвал размах 245 мин НИЖНЕЙ ГРАНИЦЕЙ. Заказ G108 п. 3 запретил
читать её как бюджет до второго дошедшего прогона. Замер цикла #815 по пятнадцати
сессиям той же ноги: у ЧЕТЫРЁХ дошедших размах 194,2…229,1 мин — нога помещается в
границу 240 мин, а одиннадцать оборванных стоя́т на самой границе, не на своей
длительности. Отличить «работы больше» от «раннер медленнее» одним размахом нельзя:
у оборванной сессии другое население. Мера берётся по ПЕРЕСЕЧЕНИЮ имён случаев.

**Времени-якоря в файле нет ПО ПОСТРОЕНИЮ.** Все отметки строятся от безразмерной
базы ``BASE_T`` и входят в прибор аргументом — приём №1 правила доставки, а не
литеральная дата. Личности процесса в файле нет вовсе; ``git init`` — тоже.

Инв. #16: ни один существующий тест не ослаблен и не сужен — файл только ДОБАВЛЯЕТ.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.step_time_census import (
    COMPARE_OK,
    COMPARE_OTHER_UNREADABLE,
    COMPARE_REFERENCE_NOT_ENDED,
    COMPARE_REFERENCE_UNREADABLE,
    COMPARE_TOO_FEW_COMMON,
    MEDIAN_FLOOR_S,
    MIN_COMMON_CASES,
    READ_OK,
    census_from_events,
    census_from_path,
    compare_common,
    format_comparison,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Безразмерная база отметок. Это НЕ дата: прибор судит только о РАЗНИЦАХ.
BASE_T = 1000.0

_FILE = "spa_core/tests/test_alpha.py"


def _session(args: list[str] | None = None) -> dict:
    return {"e": "session", "t": BASE_T, "iso": "-", "pid": 1,
            "args": args if args is not None else ["spa_core/tests/", "--timeout=180"]}


def _end(t: float) -> dict:
    return {"e": "end", "t": t, "status": 0, "started": 0, "finished": 0}


def _run(per_case_s: float, *, cases: int, ended: bool = True,
         first: str = "test", skew: dict[int, float] | None = None) -> list[dict]:
    """Сессия из ``cases`` случаев, каждый длиной ``per_case_s``.

    ``skew`` — номер случая → СВОЯ длительность: так строится клин, не меняя
    остального населения. ``ended=False`` даёт ОБОРВАННУЮ сессию (без строки `end`).
    """
    events = [_session()]
    t = BASE_T
    for i in range(cases):
        node = f"{_FILE}::{first}_{i}"
        length = (skew or {}).get(i, per_case_s)
        events.append({"e": "start", "n": node, "t": t})
        events.append({"e": "ok", "n": node, "t": t + length, "d": length})
        t += length
    if ended:
        events.append(_end(t))
    return events


def _census(events: list[dict]):
    c = census_from_events(events)
    assert c.read == READ_OK, c.reason
    return c


N = MIN_COMMON_CASES + 10          # население заведомо выше объявленного порога


# ---------------------------------------------------------------------------
# A. Третьи исходы: отказ НАЗВАН, а не отвечен числом
# ---------------------------------------------------------------------------
class RefusalsAreNamed(unittest.TestCase):

    def test_an_unreadable_reference_refuses_instead_of_ratio(self):
        """Порванное звено: эталон не прочитан. Отношение к нечитанному = выдумка."""
        got = compare_common(census_from_path(None), _census(_run(1.0, cases=N)))
        self.assertEqual(got.read, COMPARE_REFERENCE_UNREADABLE)
        self.assertIsNone(got.ratio)
        self.assertIsNone(got.slower)

    def test_an_unreadable_run_refuses_instead_of_ratio(self):
        """Порванное звено: сравниваемая запись не прочитана."""
        got = compare_common(_census(_run(1.0, cases=N)), census_from_path(None))
        self.assertEqual(got.read, COMPARE_OTHER_UNREADABLE)
        self.assertIsNone(got.ratio)

    def test_a_CUT_reference_refuses_because_its_span_is_only_a_lower_bound(self):
        """Главное звено ADR-677: эталоном имеет право быть ТОЛЬКО дошедшая сессия.

        Это ровно тот дефект, который заказ G108 п. 3 и запрещает: размах
        оборванной сессии есть нижняя граница (ADR-534), и отношение к ней было бы
        отношением к ГРАНИЦЕ, а не к бюджету.
        """
        cut = _census(_run(1.0, cases=N, ended=False))
        self.assertFalse(cut.measured_budget)
        got = compare_common(cut, _census(_run(1.0, cases=N)))
        self.assertEqual(got.read, COMPARE_REFERENCE_NOT_ENDED)
        self.assertIsNone(got.ratio)
        self.assertIn("нижняя граница", got.reason)

    def test_a_reference_that_DID_end_is_accepted(self):
        """Обратная сторона предыдущего: заслон обязан ПУСКАТЬ дошедшую сессию."""
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(1.0, cases=N)))
        self.assertEqual(got.read, COMPARE_OK)

    def test_too_few_common_cases_refuses_instead_of_measuring_noise(self):
        """Порванное звено: пересечение мало. Отношение на нём есть шум."""
        got = compare_common(
            _census(_run(1.0, cases=N)),
            _census(_run(2.0, cases=5, first="test")),
        )
        self.assertEqual(got.read, COMPARE_TOO_FEW_COMMON)
        self.assertIsNone(got.ratio)
        self.assertEqual(got.common_cases, 5)

    def test_disjoint_populations_refuse_rather_than_report_a_ratio_of_nothing(self):
        """Порванное звено: имена не совпадают ВОВСЕ — общих случаев ноль."""
        got = compare_common(
            _census(_run(1.0, cases=N, first="alpha")),
            _census(_run(1.0, cases=N, first="beta")),
        )
        self.assertEqual(got.read, COMPARE_TOO_FEW_COMMON)
        self.assertEqual(got.common_cases, 0)
        self.assertEqual(got.other_cases_without_reference, N)

    def test_a_case_without_an_outcome_is_not_counted_as_zero(self):
        """Инв. #17: у случая без исхода наблюдённой фазы НЕТ вовсе.

        Подставить ему ноль значило бы считать отсутствие наблюдения наблюдением —
        и занизить время оборванной сессии ровно на тот случай, на котором её сняли.
        """
        # Имя зависшего случая обязано БЫТЬ у эталона, иначе он выпал бы как
        # «неизвестный эталону», а заслон по исходу остался бы непройденным —
        # сцена, не исполняющая проверяемую ветку, зелена ПО ПОСТРОЕНИЮ (урок #752).
        hung = f"{_FILE}::test_{N}"
        reference = _census(_run(1.0, cases=N + 1))
        self.assertIn(hung, {c.nodeid for c in reference.cases}, "сцена непригодна")
        events = _run(1.0, cases=N, ended=False)
        events.append({"e": "start", "n": hung, "t": BASE_T + 99999})
        run = _census(events)
        self.assertEqual(run.cases_without_outcome, 1)
        got = compare_common(reference, run)
        self.assertEqual(got.read, COMPARE_OK)
        self.assertEqual(got.common_cases, N, "случай без исхода попал в сравнение")
        self.assertEqual(got.other_cases_without_reference, 0,
                         "зависший случай выпал как неизвестный, а не как безысходный")


# ---------------------------------------------------------------------------
# B. Отношение: знак и величина
# ---------------------------------------------------------------------------
class TheRatioIsMeasuredOnTheSAMECases(unittest.TestCase):

    def test_a_uniformly_slower_run_is_reported_slower(self):
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(2.0, cases=N)))
        self.assertEqual(got.read, COMPARE_OK)
        self.assertAlmostEqual(got.ratio, 2.0, places=6)
        self.assertTrue(got.slower)
        self.assertGreater(got.excess_s, 0)

    def test_a_FASTER_run_is_not_reported_slower(self):
        """Знак обязан МЕНЯТЬСЯ: замер #815 нашёл дошедшие сессии быстрее эталона."""
        got = compare_common(_census(_run(2.0, cases=N)), _census(_run(1.0, cases=N)))
        self.assertAlmostEqual(got.ratio, 0.5, places=6)
        self.assertFalse(got.slower)
        self.assertLess(got.excess_s, 0)

    def test_a_shorter_run_is_NOT_called_faster_merely_for_being_shorter(self):
        """Звено, ради которого мера и берётся по ПЕРЕСЕЧЕНИЮ.

        Оборванная сессия прошла вдвое меньше случаев и потому короче ЦЕЛИКОМ. Если
        бы прибор сравнивал размахи, он объявил бы её быстрее; по общим случаям она
        честно медленнее. Это и есть дефект, на котором «≥245 мин» прочлось как
        бюджет ноги.
        """
        reference = _census(_run(1.0, cases=2 * N))
        cut = _census(_run(1.5, cases=N, ended=False))
        self.assertLess(cut.span_s, reference.span_s, "сцена непригодна: она не короче")
        got = compare_common(reference, cut)
        self.assertAlmostEqual(got.ratio, 1.5, places=6)
        self.assertTrue(got.slower)

    def test_the_excess_is_reported_in_seconds_not_only_as_a_ratio(self):
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(1.5, cases=N)))
        self.assertAlmostEqual(got.excess_s, 0.5 * N, places=3)


# ---------------------------------------------------------------------------
# C. РАЗМАЗАНО или КЛИН — два разных дефекта, и прибор обязан их различать
# ---------------------------------------------------------------------------
class UniformSlownessIsNotAWedge(unittest.TestCase):

    def test_a_single_wedge_puts_nearly_all_the_excess_in_one_case(self):
        """Клин: одно население, один случай съел время."""
        got = compare_common(
            _census(_run(1.0, cases=N)),
            _census(_run(1.0, cases=N, skew={7: 1.0 + 10_000.0})),
        )
        self.assertGreater(got.top1_share, 0.99)
        self.assertAlmostEqual(got.median_case_ratio, 1.0, places=6)
        self.assertEqual(got.cases_slower_than_twice, 1)

    def test_uniform_slowness_leaves_the_first_hundred_a_minority_of_the_excess(self):
        """Замазанное замедление: медиана высокая, доля первых ста низкая.

        Это форма, измеренная на живых записях (#815): top-100 несёт 36…53 %
        избытка, медианное отношение 1,87…2,11×, случаев медленнее вдвое — 15 тысяч.
        """
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(2.5, cases=N)))
        self.assertLess(got.top100_share, 0.5)
        self.assertAlmostEqual(got.median_case_ratio, 2.5, places=6)
        self.assertEqual(got.cases_slower_than_twice, N)

    def test_exactly_twice_is_NOT_counted_as_slower_than_twice(self):
        """Край счёта назван отдельным контролем, а не оставлен на догадку.

        «Медленнее ВДВОЕ» — строгое неравенство: случай, повторивший эталон ровно
        вдвое, в улику не входит. Без этого контроля замена `>` на `>=` прошла бы
        незамеченной, а число улик выросло бы на всё население разом.
        """
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(2.0, cases=N)))
        self.assertAlmostEqual(got.median_case_ratio, 2.0, places=6)
        self.assertEqual(got.cases_slower_than_twice, 0)

    def test_shares_are_NONE_and_not_zero_when_there_is_no_excess(self):
        """Инв. #17: у прогона быстрее эталона «доля в избытке» не ноль, а НЕТ."""
        got = compare_common(_census(_run(2.0, cases=N)), _census(_run(1.0, cases=N)))
        self.assertIsNone(got.top1_share)
        self.assertIsNone(got.top10_share)
        self.assertIsNone(got.top100_share)

    def test_the_median_floor_keeps_near_zero_cases_out_of_the_median(self):
        """Порванное звено: без пола медиана считается частным двух шумов.

        Население ниже пола берётся ВДВОЕ больше основного — без пола медиана
        съехала бы к нему, и «типичный случай вдвое медленнее» стало бы ложью.
        """
        tiny = MEDIAN_FLOOR_S / 10.0
        reference = _run(1.0, cases=N) + []
        run = _run(2.0, cases=N)
        # дописать 2N дешёвых случаев, у которых отношение РОВНО 1
        extra_ref, extra_run = [], []
        t = BASE_T + 500_000
        for i in range(2 * N):
            node = f"{_FILE}::test_tiny_{i}"
            for bucket in (extra_ref, extra_run):
                bucket.append({"e": "start", "n": node, "t": t})
                bucket.append({"e": "ok", "n": node, "t": t + tiny, "d": tiny})
            t += tiny
        reference = reference[:-1] + extra_ref + [_end(t)]
        run = run[:-1] + extra_run + [_end(t)]
        got = compare_common(_census(reference), _census(run))
        self.assertAlmostEqual(got.median_case_ratio, 2.0, places=6)
        self.assertEqual(got.median_population, N,
                         "дешёвые случаи попали в медиану — пол не действует")

    def test_the_heaviest_contributors_are_named_not_merely_counted(self):
        got = compare_common(
            _census(_run(1.0, cases=N)),
            _census(_run(1.0, cases=N, skew={3: 900.0})),
        )
        self.assertTrue(got.heaviest)
        nodeid, base, run, delta = got.heaviest[0]
        self.assertEqual(nodeid, f"{_FILE}::test_3")
        self.assertAlmostEqual(base, 1.0, places=6)
        self.assertAlmostEqual(run, 900.0, places=6)
        self.assertAlmostEqual(delta, 899.0, places=6)


# ---------------------------------------------------------------------------
# D. Запас сверки: пересечение само обязано быть ИЗМЕРЕНО
# ---------------------------------------------------------------------------
class TheJoinReportsItsOwnMargin(unittest.TestCase):

    def test_cases_absent_from_the_reference_are_counted_not_dropped_in_silence(self):
        """Сверка ЧИСЛА населения потерю узла не ловит — ловит краевая раскладка.

        Тест дерева растёт между прогонами; случай, которого у эталона нет, из
        сравнения выпадает ПО ПРАВУ, но молчаливое выпадение сделало бы «общих
        случаев N» неотличимым от «совпало всё».
        """
        got = compare_common(_census(_run(1.0, cases=N)), _census(_run(1.0, cases=N + 25)))
        self.assertEqual(got.common_cases, N)
        self.assertEqual(got.other_cases_without_reference, 25)


# ---------------------------------------------------------------------------
# E. У находки есть ЧИТАТЕЛЬ, и проверяется ФОРМА ВЫЗОВА, а не подстрока
# ---------------------------------------------------------------------------
class TheFindingHasAReader(unittest.TestCase):
    """ADR-526: произведённая находка без читателя — отдельный класс вреда.

    Читатель здесь — сам интерфейс прибора (`--against`): запись лежит в выгрузке,
    и сравнить две выгрузки может только тот, у кого на руках обе. Подстрока
    переживает отрыв проводки, а форма вызова — нет (ADR-414/427).
    """

    @staticmethod
    def _tree() -> ast.Module:
        path = REPO_ROOT / "spa_core" / "monitoring" / "step_time_census.py"
        return ast.parse(path.read_text(encoding="utf-8"))

    def test_the_cli_declares_the_against_input(self):
        literals = {
            arg.value for node in ast.walk(self._tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        }
        self.assertIn("--against", literals, "у прибора нет входа для эталона")

    def test_the_cli_CALLS_compare_common_and_format_comparison(self):
        called = {
            node.func.id for node in ast.walk(self._tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for name in ("compare_common", "format_comparison"):
            self.assertIn(name, called, f"{name} объявлен, но НЕ ВЫЗВАН — проводки нет")

    def test_the_cli_prints_the_comparison_on_two_real_records(self):
        """Самый дорогой контроль: прибор зовётся как его зовёт человек."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name, events in (("ref", _run(1.0, cases=N)), ("run", _run(2.0, cases=N))):
                p = Path(tmp) / f"{name}.jsonl"
                p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
                paths[name] = p
            done = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring.step_time_census",
                 str(paths["run"]), "--against", str(paths["ref"]), "--json"],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        payload = json.loads(done.stdout)["comparison"]
        self.assertIsNotNone(payload, "блок сравнения не напечатан вовсе")
        self.assertEqual(payload["read"], COMPARE_OK)
        self.assertAlmostEqual(payload["ratio"], 2.0, places=6)
        self.assertTrue(payload["slower"])

    def test_the_cli_stays_silent_about_a_comparison_nobody_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "run.jsonl"
            p.write_text("\n".join(json.dumps(e) for e in _run(1.0, cases=10)) + "\n",
                         encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring.step_time_census",
                 str(p), "--json"],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIsNone(json.loads(done.stdout)["comparison"])


# ---------------------------------------------------------------------------
# F. Выжимка обязана НАЗЫВАТЬ отказ, а не печатать пустоту
# ---------------------------------------------------------------------------
class TheSummaryNamesWhatItCouldNotMeasure(unittest.TestCase):

    def test_a_refusal_is_printed_with_its_reason(self):
        text = format_comparison(
            compare_common(_census(_run(1.0, cases=N, ended=False)),
                           _census(_run(1.0, cases=N))))
        self.assertIn("нижняя граница", text)
        # Отказ обязан не нести НИ ОДНОГО числа сравнения: слово «отношение» в самой
        # причине стоит по делу, а напечатанная величина была бы ответом там, где
        # прибор отказался отвечать.
        self.assertNotIn("МЕДЛЕННЕЕ эталона", text)
        self.assertNotIn("медианное отношение", text)
        self.assertNotIn("×", text)

    def test_a_measurement_prints_the_ratio_the_excess_and_the_spread(self):
        text = format_comparison(
            compare_common(_census(_run(1.0, cases=N)), _census(_run(2.0, cases=N))))
        self.assertIn(str(N), text)                 # население пересечения названо
        self.assertIn("2.00×", text)
        self.assertIn("МЕДЛЕННЕЕ эталона", text)
        self.assertIn("медианное отношение", text)

    def test_the_summary_says_NOT_MEASURED_when_the_median_has_no_population(self):
        """Третий исход: пол отсёк всё население — это не единица и не ноль."""
        tiny = MEDIAN_FLOOR_S / 10.0
        got = compare_common(_census(_run(tiny, cases=N)), _census(_run(tiny, cases=N)))
        self.assertEqual(got.read, COMPARE_OK)
        self.assertIsNone(got.median_case_ratio)
        self.assertEqual(got.median_population, 0)
        self.assertIn("НЕ ИЗМЕРЕНО", format_comparison(got))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
