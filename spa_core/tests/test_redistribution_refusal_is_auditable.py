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
