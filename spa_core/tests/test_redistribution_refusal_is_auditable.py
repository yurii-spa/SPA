"""Отказ повторного гейта обязан быть ПРОВЕРЯЕМЫМ (мандат владельца 29.08).

Три цикла подряд отказ «After trade, cash buffer 5.0% < minimum 5.0%» оставлял 33.7 %
капитала без работы; дневная доходность упала 4.21 % → 3.17 %. Воспроизвести отказ снаружи
не удалось НИ РАЗУ:

  · по округлённым числам журнала          → остаток 5000.000000000001, порог не срабатывает
  · по точным долям (девятнадцатые части)  → то же
  · через сам класс гейта, его формулой    → 5000.000000000012
  · вызов НАСТОЯЩЕГО гейта на этой цели    → APPROVED, нарушений ноль

Значит гейт судил по цели, которой в отчёте не было: в журнал уходил текст отказа без
самой цели. Отказ, который нельзя ни подтвердить, ни оспорить, — отдельная проблема, даже
если он верен.

Здесь закреплено то, чего не хватало: сама поданная цель, её сумма, капитал (знаменатель
буфера), остаток и его доля. Запись ничего не решает — она называет.
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading.risk_gate import redistribution_refusal_record as rec


class TheRecordCarriesWhatWasMissing(unittest.TestCase):
    def test_it_names_the_submitted_target_itself(self):
        r = rec({"b": 4736.84, "a": 17368.42}, 100000.0, {"a": 17368.42}, ["cash buffer"])
        self.assertEqual(r["submitted_target"], {"a": 17368.42, "b": 4736.84})
        self.assertEqual(r["legs"], 2)

    def test_it_names_the_denominator_of_the_buffer(self):
        """Спор идёт о доле от КАПИТАЛА — значит капитал обязан быть в записи."""
        self.assertEqual(rec({"a": 1.0}, 101120.32, {}, [])["capital_usd"], 101120.32)

    def test_it_computes_the_very_numbers_the_refusal_argues_about(self):
        """Ровно тот случай трёх циклов: 95 000 из 100 000, остаток 5 000 = 5 %."""
        r = rec({"a": 66315.79, "b": 17368.42, "c": 4736.84, "d": 6578.95},
                100000.0, {}, ["After trade, cash buffer 5.0% < minimum 5.0%"])
        self.assertEqual(r["submitted_sum_usd"], 95000.0)
        self.assertEqual(r["remaining_cash_usd"], 5000.0)
        self.assertEqual(r["remaining_cash_pct"], 5.0)

    def test_a_target_over_the_buffer_shows_a_NEGATIVE_margin(self):
        """Если цель и правда выше буфера — запись покажет это числом, а не спором."""
        r = rec({"a": 96000.0}, 100000.0, {}, ["cash buffer"])
        self.assertEqual(r["remaining_cash_usd"], 4000.0)
        self.assertLess(r["remaining_cash_pct"], 5.0)

    def test_violations_and_error_are_both_carried(self):
        r = rec({}, 100000.0, None, [], error="gate crashed")
        self.assertEqual(r["violations"], [])
        self.assertEqual(r["error"], "gate crashed")

    def test_zero_capital_does_not_divide_by_zero(self):
        self.assertIsNone(rec({"a": 1.0}, 0.0, {}, [])["remaining_cash_pct"])


class RoundingWouldEraseTheEvidence(unittest.TestCase):
    """Первая версия записи округляла до центов — и стёрла улику (29.08).

    Первый же живой отказ пришёл с суммой ровно 95 000.00 и остатком ровно 5 000.00 = 5.0 %,
    то есть по записи отказывать было НЕ ЗА ЧТО. Настоящие ноги — точные девятнадцатые доли
    (6578.947368421053), спор идёт о последних битах, и округление их убило.
    """

    LEGS = {"aave_v3": 420000 / 19.0, "compound_v3": 720000 / 19.0,
            "maple": 360000 / 19.0, "fluid_usdc": 180000 / 19.0,
            "morpho_blue_base": 125000 / 19.0}

    def test_raw_values_survive_untouched(self):
        r = rec(self.LEGS, 100000.0, {}, [])
        self.assertEqual(r["raw_target"]["morpho_blue_base"], repr(125000 / 19.0))
        self.assertNotEqual(r["raw_target"]["morpho_blue_base"], "6578.95")

    def test_the_refusal_can_be_recomputed_from_the_record_alone(self):
        """Смысл записи: по ней и только по ней отказ обязан пересчитываться."""
        r = rec(self.LEGS, 100000.0, {}, [])
        # ИЗМЕНЁН НАМЕРЕННО 29.08 (инв. #16): пересчёт приведён к арифметике ГЕЙТА.
        # Прежняя редакция вычитала последовательно и на реальных числах давала ровно
        # 5000.0 — то есть «доказывала», что отказывать не за что, тогда как гейт
        # считает `капитал − sum(предыдущие) − сумма` и получает 4999.999999999996.
        # Тест, считающий не тем способом, оправдывал бы цель, которую гейт отверг.
        prior = []
        cash = None
        for _p, v in sorted(r["raw_target"].items(), key=lambda kv: (-float(kv[1]), kv[0])):
            cash = r["capital_usd"] - sum(prior) - float(v)
            prior.append(float(v))
        self.assertEqual(repr(cash), r["raw_remaining_sequential"])

    def test_the_record_reproduces_the_real_refusal_of_29_aug(self):
        """Положительный контроль: на сырых числах прода запись обязана уйти НИЖЕ порога."""
        real = {"aave_v3": 22105.260000000006, "compound_v3": 37894.74,
                "fluid_usdc": 9473.68, "maple": 18947.37,
                "morpho_blue_base": 6578.950000000001}
        r = rec(real, 100000.0, {}, ["cash buffer"])
        self.assertLess(float(r["raw_remaining_frac"]), 0.05)
        self.assertEqual(r["remaining_cash_usd"], 5000.0,
                         "округлённое число обязано остаться читаемым для человека")

    def test_the_two_ways_of_counting_are_both_recorded(self):
        """Они РАСХОДЯТСЯ, и запись обязана показывать оба — иначе спор беспредметен."""
        r = rec(self.LEGS, 100000.0, {}, [])
        self.assertIn("raw_remaining_naive", r)
        self.assertIn("raw_remaining_sequential", r)

    def test_human_readable_numbers_are_still_there(self):
        r = rec(self.LEGS, 100000.0, {}, [])
        self.assertEqual(r["submitted_sum_usd"], 95000.0)
        self.assertEqual(r["remaining_cash_usd"], 5000.0)


class TheRecordIsWiredIntoTheRefusalBranch(unittest.TestCase):
    """Проводка, а не деталь: функция может быть исправна и никем не вызвана."""

    def test_cycle_runner_calls_it_where_the_gate_refuses(self):
        """Проверяется ФОРМА ВЫЗОВА, а не имя: строки импорта достаточно, чтобы имя
        встретилось, и первая версия этого теста осталась зелёной, когда мутация
        сняла сам вызов. Ищем вызов с аргументами и разбором `ast`, а не подстроку."""
        import ast
        import inspect
        from spa_core.paper_trading import cycle_runner
        src = inspect.getsource(cycle_runner)
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "redistribution_refusal_record"]
        self.assertTrue(calls, "ветка отказа больше не вызывает запись — отказ снова непроверяем")
        self.assertGreaterEqual(len(calls[0].args), 4,
                                "запись вызвана без цели/капитала — она пуста по существу")


if __name__ == "__main__":
    unittest.main()


class WhatTheGateItselfWorkedWith(unittest.TestCase):
    """Живой отказ 29.08 опроверг арифметику по ПОДАННОЙ цели, и это сузило вопрос.

    Сырые числа из прода: остаток ровно `5000.0`, доля ровно `0.05`. А `0.05 < 0.05`
    ложно — значит на поданной цели отказывать было НЕ ЗА ЧТО. Остаётся одно: внутри
    гейт работает с изменённым набором (потолки ёмкости, заморозка непроверенного TVL,
    подрезка под буфер). Поэтому запись несёт и то, что гейт ВЕРНУЛ, и поимённую
    разницу с поданным.
    """

    def test_the_gate_target_is_carried(self):
        r = rec({"a": 10.0}, 100.0, {}, [], gate_target={"a": 7.5})
        self.assertEqual(r["gate_target"], {"a": repr(7.5)})
        self.assertEqual(r["gate_sum"], repr(7.5))

    def test_the_difference_is_named_leg_by_leg(self):
        r = rec({"a": 10.0, "b": 20.0}, 100.0, {}, [], gate_target={"a": 10.0, "b": 15.0})
        self.assertEqual(r["gate_differs_from_submitted"], {"b": [repr(20.0), repr(15.0)]})

    def test_identical_sets_report_no_difference(self):
        """Обратная сторона: совпало — значит дело НЕ в изменении набора."""
        r = rec({"a": 10.0}, 100.0, {}, [], gate_target={"a": 10.0})
        self.assertEqual(r["gate_differs_from_submitted"], {})

    def test_absent_gate_target_is_None_not_empty(self):
        """«Не передали» ≠ «совпало» — иначе отсутствие данных читалось бы как согласие."""
        self.assertIsNone(rec({"a": 10.0}, 100.0, {}, [])["gate_differs_from_submitted"])
