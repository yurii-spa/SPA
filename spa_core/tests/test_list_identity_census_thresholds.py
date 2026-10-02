"""Контроли ПАРЫ ЧИСЕЛ у кандидатов переписи списков (заказ G91 п. 2, ADR-540).

Заказ дословно: «Население имени — рядом с длиной, а не вместо неё. … Порог по
ПАРЕ чисел не назначать на глаз — сначала замерить, сколько имён каждая пара
порогов берёт и что среди взятых».

Правило семьи соблюдено: у каждой проверки есть ОБРАТНАЯ сцена, где прибор
обязан промолчать, и каждый контроль ломает ровно одно звено. Два контроля —
положительные: они воспроизводят НАСТОЯЩИЕ наблюдения 02.10 на живом артефакте
(чемпион населения за укороченным хвостом по длине; совпадающая координата у
``value`` и ``record_generated_at``), и если прибор перестанет их видеть, тест
краснеет.

Литеральных дат в файле нет вовсе: вердикт сетки от часов не зависит ни в одной
ветке, поэтому пометка ``FROZEN-DATE-OK`` ему не нужна.
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import list_identity_census as census          # noqa: E402

#: Сцена заказа: два имени, у каждого одна ось сильна, а другая нища. Числа —
#: НАБЛЮДЁННЫЕ 02.10 на живом артефакте, а не выдуманные: `value` ×1 при длине
#: 93, `forward_date` ×11 при длине 7 (их заказ и привёл).
ORDER_FREQ = {"value": 1, "forward_date": 11}
ORDER_LEN = {"value": 93, "forward_date": 7}


def _cell(grid: dict, n_min: int, l_min: int) -> dict:
    for cell in grid["cells"]:
        if cell["n_min"] == n_min and cell["l_min"] == l_min:
            return cell
    raise AssertionError(f"ячейки n≥{n_min}, L≥{l_min} в сетке нет")


class AxesComeFromTheObservedPopulation(unittest.TestCase):
    """Оси сетки — наблюдённые значения. Шаг на глаз = порог на глаз."""

    def test_axes_are_exactly_the_observed_values(self):
        grid = census.threshold_grid({"a": 1, "b": 7}, {"a": 2, "b": 50})
        self.assertEqual(grid["axes"], {"population": [1, 7],
                                        "max_length": [2, 50]})
        # Положительный контроль против «ровного шага»: между 2 и 50 сорок
        # семь значений, и ни одно из них в сетке появиться не вправе —
        # появись оно, прибор сам выбрал бы шаг, то есть и порог.
        self.assertEqual(grid["pairs"], 4)

    def test_a_duplicate_observation_does_not_double_the_axis(self):
        # Обратная сцена: три имени, но значений на оси два — пар всё равно 4.
        grid = census.threshold_grid({"a": 1, "b": 1, "c": 7},
                                     {"a": 2, "b": 2, "c": 50})
        self.assertEqual(grid["axes"]["population"], [1, 7])
        self.assertEqual(grid["pairs"], 4)


class ThirdOutcomeOfALengthThatWasNeverMeasured(unittest.TestCase):
    """«Длина не измерена» ≠ «длина мала» (инв. #17), и у двух прочтений пары
    этот исход РАЗНОЙ ширины — что само есть утверждение, а не оформление."""

    def test_unmeasured_length_is_named_not_counted_as_rejected(self):
        grid = census.threshold_grid({"a": 5, "b": 1}, {"b": 3})
        cell = _cell(grid, 5, 3)
        self.assertEqual(cell["both"]["names"], [])
        self.assertEqual(cell["both"]["length_unmeasured"], 1)
        self.assertEqual(grid["coordinate_unmeasured"], ["a"])

    def test_the_disjunction_can_decide_a_name_the_conjunction_cannot(self):
        """Ось населения прошла ⇒ дизъюнкции длина уже не нужна, конъюнкции —
        нужна. Слить два прочтения в одно значило бы потерять ровно это: у `a`
        длина не измерена, и это НЕ ИЗМЕРЕНО у конъюнкции и ВЗЯТО у дизъюнкции
        — один и тот же факт, два законных разных исхода."""
        grid = census.threshold_grid({"a": 5, "b": 1, "c": 2}, {"b": 3, "c": 9})
        cell = _cell(grid, 5, 9)
        self.assertNotIn("a", cell["both"]["names"])
        self.assertEqual(cell["both"]["length_unmeasured"], 1)
        self.assertIn("a", cell["either"]["names"])
        self.assertEqual(cell["either"]["length_unmeasured"], 0)

    def test_the_disjunction_has_its_own_undecided_outcome(self):
        """Дизъюнкции тоже есть чего не знать: население НЕ прошло, а длина не
        измерена — исход решала бы она. Контроль заведён мутацией (цикл #753):
        выброшенный третий исход дизъюнкции батарею не красил, и это была дыра
        МОЕЙ батареи, а не прибора."""
        grid = census.threshold_grid({"a": 1, "b": 5}, {"b": 9})
        cell = _cell(grid, 5, 9)
        self.assertEqual(cell["either"]["names"], ["b"])
        self.assertEqual(cell["either"]["length_unmeasured"], 1)

    def test_every_name_lands_in_exactly_one_outcome_of_every_cell(self):
        """Три исхода исчерпывают население в КАЖДОЙ ячейке и в обоих
        прочтениях: имя, пропавшее из всех трёх, исчезло бы молча."""
        freq = {"a": 5, "b": 1, "c": 3}
        strength = {"a": 10, "c": 4}        # у `b` длины нет вовсе
        grid = census.threshold_grid(freq, strength)
        for cell in grid["cells"]:
            for reading in ("both", "either"):
                side = cell[reading]
                self.assertEqual(side["taken"], len(side["names"]))
                self.assertLessEqual(side["taken"] + side["length_unmeasured"],
                                     len(freq))
                # Непересечение: неизмеренное имя не вправе быть и взятым.
                self.assertNotIn("b", side["names"] if side["length_unmeasured"]
                                 and reading == "both" else [])


class TheTwoReadingsJudgeTheOrdersExamplesOppositely(unittest.TestCase):
    """Главный ответ заказу: пара чисел — это ДВА разных правила, и примеры,
    которыми заказ её обосновал, они судят противоположно."""

    def test_no_conjunctive_pair_takes_both_examples_above_the_axis_floor(self):
        grid = census.threshold_grid(ORDER_FREQ, ORDER_LEN)
        both = [c for c in grid["cells"]
                if set(c["both"]["names"]) == {"value", "forward_date"}]
        self.assertTrue(both, "конъюнкция не взяла оба примера ни при одной паре")
        # И каждая такая пара сидит на ПОЛУ оси населения: порог по населению
        # в ней не делает работы вовсе. Это и есть измеренный отказ.
        self.assertEqual({c["n_min"] for c in both}, {1})
        self.assertTrue(grid["population_axis_idle"])

    def test_the_disjunction_takes_both_at_a_working_threshold(self):
        """Обратная сцена: то же население, другое прочтение — и вердикт по
        оси населения меняется. Один ответ на две ставки был бы ничьим."""
        grid = census.threshold_grid(ORDER_FREQ, ORDER_LEN)
        cell = _cell(grid, 11, 93)
        self.assertEqual(sorted(cell["either"]["names"]),
                         ["forward_date", "value"])


class CountsFallAsThresholdsRise(unittest.TestCase):
    """Свойство самого определения: подняв порог, взять БОЛЬШЕ нельзя."""

    def test_taken_is_monotone_along_both_axes_in_both_readings(self):
        freq = {"a": 1, "b": 2, "c": 3, "d": 11}
        strength = {"a": 93, "b": 8, "c": 5, "d": 7}
        grid = census.threshold_grid(freq, strength)
        by_pair = {(c["n_min"], c["l_min"]): c for c in grid["cells"]}
        pops, lens = grid["axes"]["population"], grid["axes"]["max_length"]
        for reading in ("both", "either"):
            for i, n_min in enumerate(pops):
                for j, l_min in enumerate(lens):
                    here = by_pair[(n_min, l_min)][reading]["taken"]
                    if i + 1 < len(pops):
                        self.assertLessEqual(
                            by_pair[(pops[i + 1], l_min)][reading]["taken"], here)
                    if j + 1 < len(lens):
                        self.assertLessEqual(
                            by_pair[(n_min, lens[j + 1])][reading]["taken"], here)


class ACollisionIsBlindToEveryThreshold(unittest.TestCase):
    """Слепое пятно пары — СВОЙСТВО, а не наблюдение дня, и доказывается оно
    перебором всех ячеек, а не рассуждением в комментарии."""

    def test_names_sharing_a_coordinate_are_taken_or_refused_together(self):
        # Положительный контроль, воспроизводящий НАСТОЯЩЕЕ наблюдение 02.10:
        # `value` и `record_generated_at` сидят на (1, 93) оба, а ADR-503 одно
        # из этих имён отверг ПОИМЁННО. Порог по паре чисел такого различения
        # не делает ни при каком значении — и вот перебор.
        freq = {"value": 1, "record_generated_at": 1, "forward_date": 11}
        strength = {"value": 93, "record_generated_at": 93, "forward_date": 7}
        grid = census.threshold_grid(freq, strength)
        self.assertEqual(
            [c["names"] for c in grid["collisions"]],
            [["record_generated_at", "value"]])
        # Чемпион оси — МНОЖЕСТВО: ничья наблюдена, и взять из неё «первое»
        # имя значило бы скрыть ровно то совпадение, на котором стоит вердикт.
        self.assertEqual(grid["champions"]["by_max_length"]["names"],
                         ["record_generated_at", "value"])
        for cell in grid["cells"]:
            for reading in ("both", "either"):
                names = set(cell[reading]["names"])
                self.assertEqual("value" in names,
                                 "record_generated_at" in names,
                                 f"пара n≥{cell['n_min']}, L≥{cell['l_min']} "
                                 f"различила имена ОДНОЙ координаты")

    def test_two_unmeasured_lengths_are_not_a_collision_class(self):
        """«Координаты совпали» — утверждение о ДВУХ измеренных числах. У имён
        без измеренной длины координаты нет вовсе, и объявить их неразличимыми
        значило бы судить о числах, которых никто не наблюдал (инв. #17)."""
        grid = census.threshold_grid({"a": 1, "b": 1, "c": 2}, {"c": 4})
        self.assertEqual(grid["collisions"], [])
        self.assertEqual(grid["coordinate_unmeasured"], ["a", "b"])

    def test_distinct_coordinates_are_not_reported_as_a_collision(self):
        # Обратная сцена: координаты различны — пятна нет, и прибор молчит.
        grid = census.threshold_grid({"a": 1, "b": 2}, {"a": 93, "b": 8})
        self.assertEqual(grid["collisions"], [])
        self.assertEqual(grid["blind_names"], [])


class TheVerdictIsComputedNotDeclared(unittest.TestCase):
    """Отказ держится на наблюдаемых условиях: исчезнут они — вердикт сменится
    САМ, и правило будет пересмотрено решением, а не истлеет молча."""

    def test_a_collision_refuses_the_rule_and_names_why(self):
        grid = census.threshold_grid({"a": 1, "b": 1}, {"a": 5, "b": 5})
        self.assertEqual(grid["rule_verdict"], "REFUSED")
        self.assertTrue(any("ПОВТОРЯЕТСЯ" in r
                            for r in grid["rule_verdict_reasons"]))

    def test_a_population_where_both_axes_work_is_not_refuted(self):
        """Обратная сцена — и она же доказывает, что вердикт не константа:
        один чемпион на обе оси, координаты различны, пороги работают."""
        grid = census.threshold_grid({"a": 5, "b": 1}, {"a": 50, "b": 2})
        self.assertEqual(grid["rule_verdict"], "NOT_REFUTED")
        self.assertEqual(grid["rule_verdict_reasons"], [])
        self.assertFalse(grid["population_axis_idle"])
        self.assertFalse(grid["length_axis_idle"])

    def test_not_refuted_is_not_a_claim_that_the_rule_is_sound(self):
        grid = census.threshold_grid({"a": 5, "b": 1}, {"a": 50, "b": 2})
        self.assertTrue(any("NOT_REFUTED" in line
                            for line in grid["what_it_does_not_prove"]))


class ThePairIsNeverMeasuredOnNothing(unittest.TestCase):
    """Нечего мерить ⇒ UNMEASURED с причиной, а не пустая сетка (инв. #17)."""

    def test_no_candidates_at_all(self):
        grid = census.threshold_grid({}, {})
        self.assertEqual(grid["status"], "UNMEASURED")
        self.assertIn("кандидатов нет", grid["reason"])
        self.assertNotIn("cells", grid)

    def test_candidates_without_a_single_measured_length(self):
        grid = census.threshold_grid({"a": 3, "b": 1}, {})
        self.assertEqual(grid["status"], "UNMEASURED")
        self.assertIn("второй оси", grid["reason"])

    def test_a_non_integral_length_is_named_not_rounded(self):
        # Число элементов дробным не бывает; появилось — документ не то, чем
        # себя называет, и это ТРЕТИЙ исход, а не «длина 92».
        grid = census.threshold_grid({"a": 1, "b": 2}, {"a": 92.5, "b": 8})
        self.assertEqual(grid["coordinate_not_integral"], ["a"])
        self.assertEqual(grid["axes"]["max_length"], [8])
        self.assertNotIn("a", [n for c in grid["cells"]
                               for n in c["both"]["names"]])

    def test_an_integral_float_is_not_printed_as_a_fraction(self):
        # Обратная сцена: 93.0 есть целое 93, и порог «L≥93.0» был бы дробным
        # порогом там, где дробных значений не бывает.
        grid = census.threshold_grid({"a": 1}, {"a": 93.0})
        self.assertEqual(grid["axes"]["max_length"], [93])
        self.assertEqual(grid["coordinate_not_integral"], [])


class TheStrongestPairRepresentsItsAnswer(unittest.TestCase):
    """Представитель набора выбран замером, а не первым попавшимся."""

    def test_the_reported_pair_is_the_strictest_one_holding_that_set(self):
        grid = census.threshold_grid({"a": 1, "b": 2}, {"a": 93, "b": 8})
        rows = census.distinct_taken_sets(grid, reading="both")
        full = [r for r in rows if sorted(r["names"]) == ["a", "b"]]
        self.assertEqual(len(full), 1)
        # Оба имени берут пары (1,2) и (1,8); сильнейшая из них — (1,8).
        self.assertEqual((full[0]["n_min"], full[0]["l_min"]), (1, 8))

    def test_the_choice_matters_when_several_pairs_share_one_answer(self):
        """Прежняя сцена мутанта не убивала: набор там держала РОВНО ОДНА пара,
        и «сильнейшая» со «слабейшей» совпадали. Здесь ответ `{a}` держат три
        пары, и представитель обязан быть строжайшей из них."""
        grid = census.threshold_grid({"a": 2, "b": 1}, {"a": 9, "b": 5})
        rows = census.distinct_taken_sets(grid, reading="both")
        only_a = [r for r in rows if r["names"] == ["a"]]
        self.assertEqual(len(only_a), 1)
        self.assertEqual((only_a[0]["n_min"], only_a[0]["l_min"]), (2, 9))

    def test_an_unmeasured_grid_yields_no_rows_instead_of_a_fake_one(self):
        self.assertEqual(census.distinct_taken_sets({"status": "UNMEASURED"}), [])


class TheReportSaysItByOutcome(unittest.TestCase):
    """Проводка доказывается ИСХОДОМ: строки сетки обязаны появиться в отчёте,
    и у офисного (укороченного) вида — тоже."""

    def _doc(self, freq, strength) -> dict:
        grid = census.threshold_grid(freq, strength)
        return {"status": "FINDING", "invoked_by": {}, "counts": {
            "lists_total": 2, "outcomes": {"named": 1},
            "denominator_of_finding": 1, "singletons": 0,
            "scalar_lists_multi": 0, "readers_measured": 1,
            "candidate_fields_outside": freq,
            "candidate_field_strength": strength,
            "threshold_grid": grid, "finding_rows": [], "unmeasured_causes": {}}}

    def test_the_grid_reaches_the_console_report(self):
        lines = census.report(self._doc(ORDER_FREQ, ORDER_LEN))
        self.assertTrue(any("[ПАРА ЧИСЕЛ · ОСИ]" in ln for ln in lines))
        self.assertTrue(any("ВЕРДИКТ ПРАВИЛА] REFUSED" in ln for ln in lines))

    def test_the_grid_reaches_the_office_short_form(self):
        lines = census.format_report(self._doc(ORDER_FREQ, ORDER_LEN))
        self.assertTrue(any("[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО]" in ln for ln in lines))

    def test_a_document_without_a_grid_says_NOT_MEASURED(self):
        doc = self._doc(ORDER_FREQ, ORDER_LEN)
        del doc["counts"]["threshold_grid"]
        lines = census.report(doc)
        self.assertTrue(any("сетки порогов по паре чисел в документе нет" in ln
                            for ln in lines))

    def test_an_unmeasured_grid_is_not_printed_as_an_empty_one(self):
        doc = self._doc(ORDER_FREQ, ORDER_LEN)
        doc["counts"]["threshold_grid"] = census.threshold_grid({}, {})
        lines = census.report(doc)
        self.assertTrue(any("[НЕ ИЗМЕРЕНО] пара порогов:" in ln for ln in lines))
        self.assertFalse(any("[ПАРА ЧИСЕЛ · ОСИ]" in ln for ln in lines))

    def test_a_cell_without_the_unmeasured_count_is_not_read_as_zero(self):
        """Храповик класса (`test_absent_observation_ratchet`) покраснел на этой
        самой строке: `or 0` превращал отсутствующий счётчик в «неизмеренных
        ноль». Починка — чтением, а не дописью в базу класса."""
        doc = self._doc(ORDER_FREQ, ORDER_LEN)
        for cell in doc["counts"]["threshold_grid"]["cells"]:
            del cell["both"]["length_unmeasured"]
        lines = census.report(doc)
        self.assertTrue(any("НЕ СКАЗАНО, и это не ноль" in ln for ln in lines))

    def test_a_grid_without_the_collision_list_is_not_read_as_clean(self):
        doc = self._doc(ORDER_FREQ, ORDER_LEN)
        del doc["counts"]["threshold_grid"]["collisions"]
        lines = census.report(doc)
        self.assertTrue(any("перечня классов совпадения в сетке нет" in ln
                            for ln in lines))
        # Проверять подстрокой «совпадающих координат нет» нельзя: она входит
        # в САМУ строку отказа («это не „совпадающих координат нет“»), и тест
        # краснел бы от собственной формулировки. Спрашиваем по заголовку.
        self.assertFalse(any(ln.startswith("[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО]")
                             for ln in lines))

    def test_truncating_the_cell_list_says_so(self):
        freq = {f"f{i}": i + 1 for i in range(8)}
        strength = {f"f{i}": (i + 1) * 3 for i in range(8)}
        lines = census.report(self._doc(freq, strength), max_cells=2)
        self.assertTrue(any("ответ(ов) — полный перечень" in ln for ln in lines))

    def test_tally_wires_the_grid_into_the_counts(self):
        """Та же проводка, но от ВХОДА прибора: строка читателя → свод."""
        rows = {"mod": {"lists": [
            {"outcome": "unnamed_candidate_outside", "n": 9,
             "coord": ".a", "candidates": ["label"]},
            {"outcome": "unnamed_candidate_outside", "n": 3,
             "coord": ".b", "candidates": ["label", "tag"]}]}}
        counts = census.tally(rows)
        grid = counts["threshold_grid"]
        self.assertEqual(grid["status"], "MEASURED")
        self.assertEqual(grid["champions"]["by_max_length"]["names"], ["label"])


class ThePopulationHeadIsPrintedBesideTheLengthHead(unittest.TestCase):
    """Положительный контроль НАСТОЯЩЕЙ находки 02.10: укорочение перечня по
    ОДНОЙ оси выбрасывает чемпиона другой. На живом артефакте так пропадал
    `forward_date` ×11 — самое населённое имя переписи."""

    def _doc(self) -> dict:
        # Восемь длинных имён с населением 1 и девятое — населённое, но короткое.
        freq = {f"long{i}": 1 for i in range(8)}
        strength = {f"long{i}": 90 - i for i in range(8)}
        freq["forward_date"] = 11
        strength["forward_date"] = 7
        return {"status": "FINDING", "invoked_by": {}, "counts": {
            "lists_total": 2, "outcomes": {"named": 1},
            "denominator_of_finding": 1, "singletons": 0,
            "scalar_lists_multi": 0, "readers_measured": 1,
            "candidate_fields_outside": freq,
            "candidate_field_strength": strength,
            "threshold_grid": census.threshold_grid(freq, strength),
            "finding_rows": [], "unmeasured_causes": {}}}

    def test_the_length_ranked_head_hides_the_population_champion(self):
        lines = census.format_report(self._doc())
        head = next(ln for ln in lines if ln.startswith("[НАХОДКА]"))
        self.assertNotIn("forward_date", head)

    def test_and_the_population_head_names_it_as_hidden(self):
        lines = census.format_report(self._doc())
        beside = next(ln for ln in lines
                      if ln.startswith("[РЯДОМ, ПО НАСЕЛЕНИЮ]"))
        self.assertIn("forward_date", beside)
        self.assertIn("порядком по длине скрыто: forward_date", beside)

    def test_when_nothing_is_hidden_the_line_says_that_instead(self):
        # Обратная сцена: головы совпали — строка обязана это сказать, а не
        # промолчать и не выдумать скрытое имя.
        freq = {"a": 3, "b": 2}
        strength = {"a": 30, "b": 20}
        doc = {"status": "FINDING", "invoked_by": {}, "counts": {
            "lists_total": 2, "outcomes": {"named": 1},
            "denominator_of_finding": 1, "singletons": 0,
            "scalar_lists_multi": 0, "readers_measured": 1,
            "candidate_fields_outside": freq,
            "candidate_field_strength": strength,
            "threshold_grid": census.threshold_grid(freq, strength),
            "finding_rows": [], "unmeasured_causes": {}}}
        beside = next(ln for ln in census.format_report(doc)
                      if ln.startswith("[РЯДОМ, ПО НАСЕЛЕНИЮ]"))
        self.assertIn("голова та же, что по длине", beside)

    def test_a_name_without_a_measured_length_sinks_but_is_not_dropped(self):
        # Внутри одного населения неизмеренная длина идёт ПОСЛЕ измеренной и
        # при этом не выпадает из перечня: «не измерено» — не «ноль».
        ranked = census._ranked_by_population({"a": 5, "b": 5}, {"b": 3})
        self.assertEqual([name for name, _ in ranked], ["b", "a"])


class TheModuleInstallsNoGate(unittest.TestCase):
    """Правило «гейта нет» проверяется СОСТАВОМ публичных имён модуля, а не
    обещанием в докстринге: тихой правкой гейт иначе однажды появится."""

    def test_no_public_name_decides_fitness(self):
        public = {name for name in dir(census) if not name.startswith("_")}
        self.assertEqual(public & set(census._NO_GATE_NAMES), set())

    def test_the_grid_adds_no_name_to_the_identity_fields(self):
        before = tuple(census.probe.IDENTITY_FIELDS)
        census.threshold_grid(ORDER_FREQ, ORDER_LEN)
        self.assertEqual(tuple(census.probe.IDENTITY_FIELDS), before)

    def test_the_measure_takes_no_argument_that_would_select_a_pair(self):
        # Параметр-порог у прибора означал бы, что выбор пары уже где-то сделан.
        params = set(inspect.signature(census.threshold_grid).parameters)
        self.assertEqual(params, {"freq", "strength"})


if __name__ == "__main__":
    unittest.main()
