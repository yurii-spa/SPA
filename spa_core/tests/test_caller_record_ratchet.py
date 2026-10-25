"""Храповик заказа G804 п. 3: ступень с ТАКТОМ обязана называть ЗВАВШЕГО.

Утверждение одно, и оно о ПОЯВЛЕНИИ: население класса может только убывать, а
десятая ступень с тактом и без измеренной записи о звавшем обязана покраснеть
здесь, а не утонуть в прозе ADR. До этого храповика девять имён жили абзацем
ADR-804, которого не читает ни один код (класс ADR-345 — находка без читателя).

Сверка живёт в ПРИБОРЕ (`_caller_record_gap.verdict`), а не в теле теста, и
причина ИЗМЕРЕНА, а не унаследована: ADR-803 показал на соседе, что сверка живой
базы с живым замером МУТАЦИЮ ПЕРЕЖИВАЕТ по построению — храповик не может
воспроизвести аварию, не правя живую базу. Поэтому здесь два разных теста:
один читает ЖИВОЕ дерево (сигнал), остальные собирают СЦЕНЫ и рвут звенья.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from spa_core.tests import _caller_record_gap as crg

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = ROOT / "spa_core" / "tests" / "caller_record_baseline.json"


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


class CallerRecordRatchet(unittest.TestCase):
    """Живое дерево против объявленного населения."""

    def test_no_new_stage_carries_a_tact_without_naming_its_caller(self):
        census = crg.measure(root=ROOT)
        verdict = crg.verdict(census, _baseline())
        self.assertIsNone(
            verdict.unmeasured,
            "перепись ступеней НЕ ИЗМЕРЕНА — это третий исход, и зелёным он "
            f"быть не вправе: {verdict.unmeasured}")
        self.assertEqual(
            [], verdict.problems,
            "население класса «ступень с тактом не называет звавшего» ВЫРОСЛО "
            "либо объявление разошлось с собой. Дописывать имя в базу, чтобы "
            "погасить падение, ЗАПРЕЩЕНО (инв. #16) — провести запись:\n"
            + "\n".join(verdict.problems))

    def test_the_baseline_only_shrinks(self):
        census = crg.measure(root=ROOT)
        declared = set(_baseline()["missing"])
        self.assertLessEqual(
            set(census.names("missing")), declared,
            "замер назвал ступень, которой в объявлении нет — это ПОЯВЛЕНИЕ")

    def test_the_operand_accounts_for_every_declared_stage(self):
        """Сумма ведёр равна числу объявленных ступеней.

        Без этого утверждения ступень могла бы выпасть из переписи МОЛЧА — ни в
        одном ведре, и ни один вердикт бы не сдвинулся.
        """
        census = crg.measure(root=ROOT)
        operand = crg.operand(census)
        self.assertEqual(
            census.stages_declared, sum(operand.values()),
            f"ступени потерялись между ведрами: {operand}")

    def test_the_operand_names_every_outcome_of_the_census(self):
        """Исход, добавленный в `Census` и НЕ дописанный в `OPERAND_BUCKETS`,
        выпал бы из операнда — и это бы молчало."""
        fields = {name for name in vars(crg.Census()) if name != "stages_declared"}
        self.assertEqual(
            set(crg.OPERAND_BUCKETS), fields,
            "перечень ведёр операнда разошёлся с полями переписи")


class TheVerdictNamesWhatItFound(unittest.TestCase):
    """Сцены: каждое звено рвётся по отдельности и НАЗЫВАЕТСЯ."""

    TACT_NO_RECORD = (
        "def run(root, *, if_due=False):\n"
        "    return {'generated_at': '…'}\n")
    WITH_RECORD = (
        "from spa_core.monitoring.call_provenance import call_provenance\n"
        "def run(root, *, if_due=False):\n"
        "    return {'invoked_by': call_provenance(tree_root=root)}\n")

    def _census(self, sources: dict) -> crg.Census:
        return crg.measure(
            registry={n: {"module": f"{n}.py"} for n in sources},
            read_source=lambda rel: sources.get(rel[:-3]))

    def test_an_appearance_is_named_by_stage_and_by_module(self):
        census = self._census({"newcomer": self.TACT_NO_RECORD})
        verdict = crg.verdict(census, {"missing": [], "missing_total": 0})
        self.assertTrue(any("ПОЯВИЛАСЬ newcomer" in p for p in verdict.problems),
                        verdict.problems)
        self.assertTrue(any("newcomer.py" in p for p in verdict.problems),
                        "вердикт не называет модуль — находка не адресуема")

    def test_a_shrinking_population_is_silent(self):
        """Починка — не регресс, и краснеть на ней сторож не вправе."""
        census = self._census({"fixed": self.WITH_RECORD})
        verdict = crg.verdict(census, {"missing": ["fixed"], "missing_total": 1})
        self.assertEqual([], verdict.problems)
        self.assertIsNone(verdict.unmeasured)

    def test_a_total_that_disagrees_with_its_own_list_is_named(self):
        """Объявление сверяется САМО С СОБОЙ: иначе остаётся честный выход
        «перепечатал итог, перечень не тронул» (класс ADR-803)."""
        census = self._census({"fixed": self.WITH_RECORD})
        verdict = crg.verdict(census, {"missing": ["a", "b"], "missing_total": 7})
        self.assertTrue(
            any("ОБЪЯВЛЕНИЕ НЕ СОШЛОСЬ С СОБОЙ" in p for p in verdict.problems),
            verdict.problems)

    def test_an_unreadable_module_is_a_third_outcome_not_a_zero(self):
        census = self._census({"gone": None})
        self.assertEqual(("gone",), census.names("unmeasured"))
        self.assertEqual((), census.missing)
        verdict = crg.verdict(census, {"missing": [], "missing_total": 0})
        self.assertIsNotNone(
            verdict.unmeasured,
            "ступень НЕ ИЗМЕРЕНА, а вердикт молчит — fail-OPEN тише красного")
        self.assertEqual([], verdict.problems,
                         "«не прочитан» выдан за ПОЯВЛЕНИЕ — это другой дефект")

    def test_a_module_that_does_not_parse_is_unmeasured(self):
        census = self._census({"broken": "def run(  # обрыв\n"})
        self.assertEqual(("broken",), census.names("unmeasured"))

    def test_a_registry_without_a_module_name_is_unmeasured(self):
        census = crg.measure(registry={"nameless": {}},
                             read_source=lambda rel: None)
        self.assertEqual(("nameless",), census.names("unmeasured"))

    def test_an_empty_registry_is_unmeasured_not_clean(self):
        verdict = crg.verdict(crg.measure(registry={}, read_source=lambda r: None),
                              {"missing": [], "missing_total": 0})
        self.assertIsNotNone(verdict.unmeasured)
        self.assertIn("ни одной ступени", verdict.unmeasured)

    def test_a_baseline_that_is_not_a_document_is_unmeasured(self):
        """`subTest` здесь НЕ используется намеренно, и это замер, а не стиль.

        Первая редакция держала четыре случая под `subTest`, и мутационный
        прогон ADR-805 объявил носителя ВЫЖИВШИМ: тест мутацию ловит (4 failed),
        но прибор дельты сравнивает НАБОР УПАВШИХ ИМЁН, а `SUBFAILED` приходит
        под ТЕМ ЖЕ nodeid — набор «не изменился», и утверждение стало невидимо
        (класс ADR-761, цикл #876). Четыре отдельных имени видны прибору.
        """
        census = self._census({"x": self.WITH_RECORD})
        self.assertIsNotNone(crg.verdict(census, "перечень").unmeasured,
                             "база-строка")
        self.assertIsNotNone(crg.verdict(census, None).unmeasured, "база-None")
        self.assertIsNotNone(crg.verdict(census, ["a"]).unmeasured, "база-список")
        self.assertIsNotNone(crg.verdict(census, 7).unmeasured, "база-число")

    def test_a_baseline_without_a_list_or_a_total_is_unmeasured(self):
        census = self._census({"x": self.WITH_RECORD})
        self.assertIn("перечня `missing`",
                      crg.verdict(census, {"missing_total": 0}).unmeasured)
        self.assertIn("итога `missing_total`",
                      crg.verdict(census, {"missing": []}).unmeasured)
        self.assertIn("итога `missing_total`",
                      crg.verdict(census, {"missing": [],
                                           "missing_total": True}).unmeasured)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
