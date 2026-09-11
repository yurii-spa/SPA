"""Честное чтение наблюдения: отсутствие отличимо от нуля (инвариант #17, ADR-344).

Помощник существует не ради красоты: форма `doc.get("k") or 0.0` пишется КОРОЧЕ
честной, поэтому появляется сама — 177 новых мест класса за 16 суток, пока инвариант
#17 отсутствовал в `CLAUDE.md`. Тесты ниже держат ровно ту границу, на которой класс
и живёт: пустота и ноль — ЗНАЧЕНИЯ, а отсутствие — не значение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import unittest

from spa_core.utils.observation import observed, observed_number


class AbsenceIsNotAValue(unittest.TestCase):
    def test_a_missing_key_is_None(self):
        self.assertIsNone(observed({}, "tvl_usd"))

    def test_an_explicit_null_is_None(self):
        self.assertIsNone(observed({"tvl_usd": None}, "tvl_usd"))

    def test_a_non_dict_document_is_None(self):
        for doc in (None, [], "нет", 0):
            with self.subTest(doc=doc):
                self.assertIsNone(observed(doc, "tvl_usd"))


class MeasuredZeroSurvives(unittest.TestCase):
    """Ядро инварианта: «измерено и равно нулю» обязано отличаться от «не измерено»."""

    def test_zero_is_a_value_not_absence(self):
        self.assertEqual(observed({"apy_pct": 0}, "apy_pct"), 0)
        self.assertEqual(observed_number({"apy_pct": 0.0}, "apy_pct"), 0.0)

    def test_an_empty_map_is_a_value(self):
        self.assertEqual(observed({"positions": {}}, "positions", kind=dict), {})

    def test_an_empty_list_is_a_value(self):
        self.assertEqual(observed({"legs": []}, "legs", kind=list), [])

    def test_the_three_outcomes_are_distinguishable(self):
        measured = observed({"drawdown_pct": 3.2}, "drawdown_pct", kind=(int, float))
        zero = observed({"drawdown_pct": 0.0}, "drawdown_pct", kind=(int, float))
        absent = observed({}, "drawdown_pct", kind=(int, float))
        self.assertEqual((measured, zero, absent), (3.2, 0.0, None))
        self.assertIsNot(zero, absent)


class GarbageIsNotAMeasurement(unittest.TestCase):
    def test_a_value_of_the_wrong_kind_is_absence(self):
        self.assertIsNone(observed({"positions": 5}, "positions", kind=dict))
        self.assertIsNone(observed_number({"apy_pct": "3.5"}, "apy_pct"))

    def test_a_bool_is_not_a_number(self):
        """«Да» — не число: `True` под видом ставки дало бы 1.0 и прошло бы границы."""
        self.assertIsNone(observed_number({"apy_pct": True}, "apy_pct"))
        self.assertIsNone(observed({"apy_pct": False}, "apy_pct", kind=(int, float)))

    def test_a_bool_asked_for_explicitly_survives(self):
        self.assertIs(observed({"armed": True}, "armed", kind=bool), True)
        self.assertIs(observed({"armed": False}, "armed", kind=bool), False)

    def test_without_a_kind_nothing_is_refused_for_its_type(self):
        self.assertEqual(observed({"x": "строка"}, "x"), "строка")


class TheHelperIsNotAnOrSubstitute(unittest.TestCase):
    """Помощник обязан ВЕРНУТЬ отсутствие, а не подставить благополучие."""

    def test_it_never_returns_a_falsy_stand_in_for_absence(self):
        for kind in (dict, list, (int, float), None):
            with self.subTest(kind=kind):
                self.assertIsNone(observed({}, "k", kind=kind) if kind else observed({}, "k"))

    def test_the_module_is_stdlib_only(self):
        import spa_core.utils.observation as mod
        src = open(mod.__file__, encoding="utf-8").read()
        for line in src.splitlines():
            if line.startswith(("import ", "from ")):
                self.assertTrue(
                    line.startswith(("from __future__", "from typing", "import typing")),
                    f"внешний импорт в рантайм-помощнике: {line}")


if __name__ == "__main__":
    unittest.main()
