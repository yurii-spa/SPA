"""ADR-168: журнал сделок обязан записывать размер хода тем же определением,
которым демпфер этот ход судит.

Авария 30.08 (настоящая запись T030): цикл разместил $28 684 простаивающего кэша,
а в журнал ушло `delta_abs = 14 342.11` — ровно половина. Причина: `diff_usd` это
L1-расстояние по ключам ПРОТОКОЛОВ, у кэша ключа нет, поэтому у одностороннего
размещения нет продающей ноги, и деление на два занижает его вдвое.

Оба потребителя (`churn_damper._recent`, `allocation_rationale`) суммируют
`delta_abs` как НЕДЕЛЬНЫЙ ОБОРОТ. Занижение вдвое — послабление риск-контроля,
то есть отказ в сторону fail-OPEN.

Второй тест — обратный контроль: для обычной двусторонней перекладки величина
обязана остаться прежней, иначе починка молча ужесточила бы оборот всем.
"""
import ast
import inspect
import unittest

from spa_core.governance.churn_damper import one_sided_turnover

# Настоящие значения из data/trades.json, запись T030.
T030_FROM = {"compound_v3": 37894.74, "maple": 18947.37, "fluid_usdc": 9473.68}
T030_TO = {"compound_v3": 37894.74, "maple": 18947.37, "fluid_usdc": 9473.68,
           "morpho_blue_base": 6578.95, "aave_v3": 22105.26}


def _l1(cur, tgt):
    """Прежняя арифметика журнала: L1 по протоколам, делённое пополам."""
    keys = set(cur) | set(tgt)
    return sum(abs(tgt.get(k, 0.0) - cur.get(k, 0.0)) for k in keys) / 2.0


class TestTradeJournalRecordsMoveSize(unittest.TestCase):

    def test_pure_placement_is_not_halved(self):
        size = one_sided_turnover(T030_FROM, T030_TO)
        self.assertAlmostEqual(
            size, 28684.21, places=2,
            msg="размещение кэша обязано записываться полной величиной")
        self.assertAlmostEqual(
            _l1(T030_FROM, T030_TO), 14342.105, places=2,
            msg="контроль посылки: прежняя арифметика действительно давала половину")

    def test_two_sided_reshuffle_is_unchanged(self):
        """Обратный контроль: там, где обе ноги есть, число прежнее."""
        cur = {"a": 50000.0, "b": 50000.0}
        tgt = {"a": 40000.0, "b": 60000.0}
        self.assertAlmostEqual(one_sided_turnover(cur, tgt), _l1(cur, tgt), places=6)
        self.assertAlmostEqual(one_sided_turnover(cur, tgt), 10000.0, places=2)

    def test_pure_exit_is_not_halved_either(self):
        """Полный выход из протокола — тоже одна нога."""
        cur = {"a": 20000.0, "b": 30000.0}
        tgt = {"b": 30000.0}
        self.assertAlmostEqual(one_sided_turnover(cur, tgt), 20000.0, places=2)

class TestTheRecorderActuallyUsesIt(unittest.TestCase):
    """Проводка проверяется ФОРМОЙ вызова, а не наличием имени в файле.

    Импорта `one_sided_turnover` недостаточно: он удовлетворил бы поиск по имени,
    оставив рядом прежнее `diff_usd / 2.0`. Поэтому смотрим, откуда РЕАЛЬНО берётся
    значение ключа `delta_abs` в записи журнала.
    """

    def _tree(self):
        import spa_core.paper_trading.cycle_runner as cr
        return ast.parse(inspect.getsource(cr))

    def test_delta_abs_comes_from_the_declared_definition(self):
        tree = self._tree()
        # имя, которому присвоен результат one_sided_turnover(...)
        holders = {
            t.id
            for n in ast.walk(tree) if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "one_sided_turnover"
        }
        self.assertTrue(
            holders,
            "в cycle_runner никто не зовёт one_sided_turnover — размер хода "
            "по-прежнему считается собственной арифметикой")
        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, ast.Constant) and k.value == "delta_abs"):
                    continue
                seen += 1
                names = {x.id for x in ast.walk(v) if isinstance(x, ast.Name)}
                self.assertTrue(
                    names & holders,
                    f"delta_abs собирается не из объявленного определения: "
                    f"{ast.dump(v)[:120]}")
        self.assertEqual(seen, 2, f"мест записи delta_abs ожидалось 2, найдено {seen}")

    def test_the_halving_arithmetic_is_gone(self):
        """Прямой контроль на рецидив: деления пополам в записи быть не должно."""
        import spa_core.paper_trading.cycle_runner as cr
        src = inspect.getsource(cr)
        self.assertNotIn(
            "round(diff_usd / 2.0, 2)", src,
            "вернулась прежняя арифметика брутто/2 в записи журнала")


if __name__ == "__main__":
    unittest.main()
