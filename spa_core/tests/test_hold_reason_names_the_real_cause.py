"""Причина удержания книги называется НАСТОЯЩАЯ (замер 30.08).

Цикл печатал «no rebalance: |Δ|=$28,684 ≤ $200 threshold» — утверждение ложное: 28 684 не
меньше 200. Строка писалась БЕЗУСЛОВНО, хотя удержаний четыре: не выполнилась проверка
безопасности, заблокировала политика риска, дельта ниже порога, не пустил анти-черн (ADR-168).
Настоящей в тот раз была четвёртая — 72-часовой демпфер после перекладки 7.7 ч назад.

Цена такой строки — чужое время: читатель чинит не то. Меня самого она едва не увела искать
ошибку в вычислении дельты там, где капитал держал демпфер. Это тот же класс, что и отказ
гейта, который нельзя проверить по журналу (ADR-171).
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading.risk_gate import hold_reason


class EachHoldNamesItself(unittest.TestCase):
    def test_churn_damper_is_named_and_the_delta_is_not_blamed(self):
        """Положительный контроль: ровно числа 30.08."""
        r = hold_reason(28684.0, 200.0, churn_allowed=False,
                        churn_detail="последняя перекладка 7.7 ч назад, минимум 72 ч")
        self.assertIn("анти-черн", r)
        self.assertIn("ADR-168", r)
        self.assertIn("72 ч", r)
        self.assertNotIn("≤", r, "дельта снова названа причиной, хотя она выше порога")

    def test_churn_hold_says_the_redistribution_is_waiting_not_lost(self):
        """Важное для читателя: деньги не потеряны, перераздача одобрена и ждёт."""
        r = hold_reason(28684.0, 200.0, churn_allowed=False, churn_detail="x")
        self.assertIn("одобрена и ждёт", r)
        self.assertIn("28,684", r)

    def test_small_delta_still_reports_the_threshold(self):
        """Обратная сторона: когда причина ДЕЙСТВИТЕЛЬНО дельта — так и написано."""
        r = hold_reason(50.0, 200.0, churn_allowed=True)
        self.assertIn("≤", r)
        self.assertIn("threshold", r)

    def test_safety_failure_outranks_everything(self):
        r = hold_reason(50.0, 200.0, churn_allowed=False, safety_failed=True,
                        policy_blocked=True)
        self.assertIn("проверка безопасности", r)

    def test_policy_block_outranks_the_damper(self):
        r = hold_reason(50.0, 200.0, churn_allowed=False, policy_blocked=True)
        self.assertIn("политикой риска", r)

    def test_the_four_causes_give_four_different_texts(self):
        """Иначе одна причина снова маскировала бы остальные."""
        texts = {
            hold_reason(50.0, 200.0, churn_allowed=True),
            hold_reason(50.0, 200.0, churn_allowed=False, churn_detail="d"),
            hold_reason(50.0, 200.0, churn_allowed=True, policy_blocked=True),
            hold_reason(50.0, 200.0, churn_allowed=True, safety_failed=True),
        }
        self.assertEqual(len(texts), 4)


class ItIsActuallyWiredIntoTheCycle(unittest.TestCase):
    def test_cycle_runner_calls_it_instead_of_the_hardcoded_string(self):
        import ast
        import inspect
        from spa_core.paper_trading import cycle_runner
        tree = ast.parse(inspect.getsource(cycle_runner))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "hold_reason"]
        self.assertTrue(calls, "цикл снова пишет причину удержания жёстко")


if __name__ == "__main__":
    unittest.main()
