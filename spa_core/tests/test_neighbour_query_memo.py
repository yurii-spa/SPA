"""Память соседских запросов: один вопрос о неизменившемся дереве — один ответ.

Цикл #692. Прибор `spa_core/monitoring/rule_second_copy_census.py` идёт на
живом дереве **313 с** при пороге CI **180 с на тест**, и половина этой работы
— повторный ответ на уже отвеченный вопрос: соседу
:data:`rsc.NEIGHBOUR_CENSUS` за один прогон задаётся ``find_by_name_consumers``
**7 раз** и ``find_callees`` **3 раза**, каждый раз с полным обходом дерева.

Батарея держит ЧЕТЫРЕ свойства памяти, и ни одно не выводится из другого:

1. **тот же ответ** — иначе починена цена ценой предмета;
2. **ответ-КОПИЯ** — до памяти каждый зов отдавал свежий объект, и правка
   одним читателем до другого не доезжала;
3. **разные вопросы не сливаются** — опасное направление ошибки: ответ о ЧУЖОМ
   дереве выглядит как ответ о своём;
4. **обёртка снимается всегда**, включая выход исключением: модуль соседа
   общий на процесс, и оставленная в нём обёртка пережила бы прогон.

Плюс третий исход (инв. #17): соседа нет / у него нет имени ⇒ память НЕ
поставлена с названной причиной, а не «повторов не было».
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
import datetime as dt
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as rsc  # noqa: E402

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=_NOW)`;
# стенных часов ни один тест файла не спрашивает.
_NOW = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)


#: Файл «переписи», который сосед-счётчик числит своей. Он ОБЯЗАН существовать
#: в сцене: `invisible_consumer_scale` разбирает файл каждой названной соседом
#: переписи, и непрочитанный файл увёл бы сцену в чужой отказ.
_STUB_CENSUS_REL = "spa_core/monitoring/alpha.py"


def _stub_neighbour(name: str = "spa_core.monitoring._memo_stub_neighbour"):
    """Сосед-счётчик: отвечает дёшево и ЗАПОМИНАЕТ, о чём его спросили.

    Стенного соседа брать нельзя: его ответ стои́т десятки секунд, и тест
    мерил бы скорость машины вместо поведения памяти.
    """
    mod = types.ModuleType(name)
    mod.calls = []

    def find_callees(root):
        mod.calls.append(("find_callees", str(root)))
        return {"alpha": _STUB_CENSUS_REL}

    def find_by_name_consumers(root, callees):
        mod.calls.append(("find_by_name_consumers", str(root),
                          tuple(sorted(callees.items()))))
        return [{"file": "scripts/reader.py", "callee": "alpha", "line": 1}]

    mod.find_callees = find_callees
    mod.find_by_name_consumers = find_by_name_consumers
    mod.find_cli_consumers = lambda root, callees: []
    # Форма ответа — НЕ выдумка счётчика: у настоящего соседа
    # `find_dynamic_consumers` отдаёт словарь `{resolved, unresolved}`, и
    # список вместо него увёл бы сцену в чужое падение вместо предмета.
    mod.find_dynamic_consumers = lambda root, callees: {"resolved": [],
                                                        "unresolved": []}
    mod.find_fleet_consumers = lambda root, callees: []
    mod.measure = lambda root, **kw: {"status": "CLEAN", "consumers": {}}
    mod.OUTPUT_FILENAME = "stub_census.json"
    mod._CODE_DIRS = ("spa_core", "scripts")
    return mod


class _StubNeighbourCase(unittest.TestCase):
    """Общая сцена: сосед подменён счётчиком на время теста."""

    def setUp(self):
        self.stub = _stub_neighbour()
        sys.modules[self.stub.__name__] = self.stub
        self.addCleanup(sys.modules.pop, self.stub.__name__, None)
        patch = mock.patch.object(rsc, "NEIGHBOUR_CENSUS", self.stub.__name__)
        patch.start()
        self.addCleanup(patch.stop)


class TheKeyExpressesTheQuestionOrRefusesToGuess(unittest.TestCase):
    """Ключ памяти. Неразобранная форма — ТРЕТИЙ исход, а не отказ."""

    def test_the_two_declared_questions_get_a_key(self):
        self.assertIsNotNone(
            rsc._neighbour_query_key("find_callees", (Path("/t"),), {}))
        self.assertIsNotNone(rsc._neighbour_query_key(
            "find_by_name_consumers", (Path("/t"), {"a": "b"}), {}))

    def test_a_different_tree_is_a_different_question(self):
        one = rsc._neighbour_query_key("find_callees", (Path("/one"),), {})
        two = rsc._neighbour_query_key("find_callees", (Path("/two"),), {})
        self.assertNotEqual(one, two)

    def test_a_different_callee_population_is_a_different_question(self):
        one = rsc._neighbour_query_key("find_by_name_consumers",
                                       (Path("/t"), {"a": "x"}), {})
        two = rsc._neighbour_query_key("find_by_name_consumers",
                                       (Path("/t"), {"a": "y"}), {})
        self.assertNotEqual(one, two)

    def test_the_same_population_in_another_order_is_the_same_question(self):
        one = rsc._neighbour_query_key("find_by_name_consumers",
                                       (Path("/t"), {"a": "1", "b": "2"}), {})
        two = rsc._neighbour_query_key("find_by_name_consumers",
                                       (Path("/t"), {"b": "2", "a": "1"}), {})
        self.assertEqual(one, two)

    def test_a_named_argument_is_not_expressed_by_the_key(self):
        self.assertIsNone(rsc._neighbour_query_key(
            "find_callees", (), {"root": Path("/t")}))

    def test_a_full_positional_call_with_an_extra_keyword_is_not_keyed(self):
        """Самая острая форма — и она найдена МУТАЦИЕЙ, а не чтением.

        Позиционные аргументы на месте, значит проверка их числа пропускает
        зов дальше; ответ при этом зависит ещё и от ключевого слова, которого
        в ключе нет. Без этого теста мутация «убрать проверку `kwargs`»
        выживает, и память отдала бы ответ на ДРУГОЙ вопрос.
        """
        self.assertIsNone(rsc._neighbour_query_key(
            "find_callees", (Path("/t"),), {"depth": 2}))
        self.assertIsNone(rsc._neighbour_query_key(
            "find_by_name_consumers", (Path("/t"), {"a": "b"}),
            {"strict": True}))

    def test_an_unexpected_arity_is_not_expressed_by_the_key(self):
        self.assertIsNone(rsc._neighbour_query_key(
            "find_callees", (Path("/t"), "extra"), {}))
        self.assertIsNone(rsc._neighbour_query_key(
            "find_by_name_consumers", (Path("/t"),), {}))

    def test_a_callee_population_that_is_not_a_mapping_is_not_keyed(self):
        self.assertIsNone(rsc._neighbour_query_key(
            "find_by_name_consumers", (Path("/t"), ["a"]), {}))

    def test_an_unknown_query_is_never_keyed(self):
        self.assertIsNone(rsc._neighbour_query_key(
            "find_cli_consumers", (Path("/t"), {}), {}))


class TheMemoAnswersTheSameAndOnlyOnce(_StubNeighbourCase):
    """Тот же ответ, посчитанный однажды."""

    def test_the_second_ask_is_reused_and_equal(self):
        with rsc._neighbour_query_memo() as witness:
            neighbour = sys.modules[self.stub.__name__]
            first = neighbour.find_callees(Path("/tree"))
            second = neighbour.find_callees(Path("/tree"))
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.stub.calls))
        stats = witness["queries"]["find_callees"]
        self.assertEqual({"computed": 1, "reused": 1, "unkeyed": 0}, stats)

    def test_the_answer_is_a_copy_and_not_the_stored_object(self):
        """Правка ответа одним читателем до другого не доезжает.

        Отдать общий объект значило бы завести между шагами связь, которой в
        измеряемом поведении нет, — то есть починить цену, сломав предмет.
        """
        with rsc._neighbour_query_memo():
            neighbour = sys.modules[self.stub.__name__]
            first = neighbour.find_by_name_consumers(Path("/t"), {"a": "b"})
            first[0]["file"] = "ПОДМЕНЕНО"
            first.append({"file": "лишний"})
            second = neighbour.find_by_name_consumers(Path("/t"), {"a": "b"})
        self.assertEqual(1, len(second))
        self.assertEqual("scripts/reader.py", second[0]["file"])

    def test_two_different_trees_are_asked_separately(self):
        """Опасное направление: ответ о ЧУЖОМ дереве выглядит как свой."""
        with rsc._neighbour_query_memo() as witness:
            neighbour = sys.modules[self.stub.__name__]
            neighbour.find_callees(Path("/one"))
            neighbour.find_callees(Path("/two"))
        self.assertEqual(2, len(self.stub.calls))
        self.assertEqual(2, witness["queries"]["find_callees"]["computed"])
        self.assertEqual(0, witness["queries"]["find_callees"]["reused"])

    def test_an_unkeyed_call_is_computed_every_time_and_counted_apart(self):
        with rsc._neighbour_query_memo() as witness:
            neighbour = sys.modules[self.stub.__name__]
            neighbour.find_callees(root=Path("/t"))
            neighbour.find_callees(root=Path("/t"))
        self.assertEqual(2, len(self.stub.calls))
        stats = witness["queries"]["find_callees"]
        self.assertEqual({"computed": 0, "reused": 0, "unkeyed": 2}, stats)

    def test_the_widened_wrapper_still_gets_a_different_answer(self):
        """Контроль в ОБРАТНУЮ сторону: память не гасит предмет соседней ступени.

        `neighbour_population_harm` мерит разницу «чистый прогон против
        расширенного», подменяя то же имя. Если бы память отдавала чистый
        ответ и расширенному зову, разница обнулилась бы МОЛЧА — и ступень
        доложила бы «вреда нет» из пустоты.
        """
        with rsc._neighbour_query_memo():
            neighbour = sys.modules[self.stub.__name__]
            real = neighbour.find_by_name_consumers
            clean = real(Path("/t"), {"a": "b"})
            extra = [{"file": "scripts/synthetic.py", "callee": "alpha"}]
            widened = list(real(Path("/t"), {"a": "b"})) + list(extra)
        self.assertNotEqual(clean, widened)
        self.assertEqual(len(clean) + 1, len(widened))


class TheWrapperIsAlwaysTakenBack(_StubNeighbourCase):
    """Модуль соседа общий на процесс: обёртка обязана сниматься всегда."""

    def test_the_originals_are_restored_after_a_clean_exit(self):
        before = (self.stub.find_callees, self.stub.find_by_name_consumers)
        with rsc._neighbour_query_memo():
            self.assertIsNot(before[0], self.stub.find_callees)
        self.assertIs(before[0], self.stub.find_callees)
        self.assertIs(before[1], self.stub.find_by_name_consumers)

    def test_the_originals_are_restored_after_an_exception(self):
        before = (self.stub.find_callees, self.stub.find_by_name_consumers)
        with self.assertRaises(RuntimeError):
            with rsc._neighbour_query_memo():
                raise RuntimeError("тело прогона упало")
        self.assertIs(before[0], self.stub.find_callees)
        self.assertIs(before[1], self.stub.find_by_name_consumers)

    def test_the_originals_are_restored_even_if_a_step_left_its_own_patch(self):
        """Ступень `neighbour_population_harm` подменяет те же имена.

        К моменту выхода в модуле стои́т ЕЁ восстановленное значение — наша
        обёртка; после нас обязан стоять настоящий сосед.
        """
        before = self.stub.find_by_name_consumers
        with rsc._neighbour_query_memo():
            inner = self.stub.find_by_name_consumers
            self.stub.find_by_name_consumers = lambda *a, **k: ["расширено"]
            self.stub.find_by_name_consumers = inner       # её собственный finally
        self.assertIs(before, self.stub.find_by_name_consumers)


class AbsentMemoIsNamedAndNotMistakenForSilence(unittest.TestCase):
    """Третий исход (инв. #17): память не поставлена — это НЕ «повторов нет»."""

    def test_an_unimportable_neighbour_names_the_reason(self):
        with mock.patch.object(rsc, "NEIGHBOUR_CENSUS",
                               "spa_core.monitoring.нет_такого_соседа"):
            with rsc._neighbour_query_memo() as witness:
                pass
        self.assertFalse(witness["installed"])
        self.assertIn("не ввезён", witness["reason"])
        self.assertIn("НЕ «повторов не было»", witness["reason"])
        self.assertEqual({}, witness["queries"])

    def test_a_neighbour_without_the_named_query_names_the_reason(self):
        mod = types.ModuleType("spa_core.monitoring._memo_stub_halfneighbour")
        mod.find_callees = lambda root: {}
        sys.modules[mod.__name__] = mod
        self.addCleanup(sys.modules.pop, mod.__name__, None)
        with mock.patch.object(rsc, "NEIGHBOUR_CENSUS", mod.__name__):
            with rsc._neighbour_query_memo() as witness:
                pass
        self.assertFalse(witness["installed"])
        self.assertIn("find_by_name_consumers", witness["reason"])
        self.assertIn("НЕ «повторов не было»", witness["reason"])

    def test_a_query_that_is_not_callable_is_not_wrapped(self):
        mod = types.ModuleType("spa_core.monitoring._memo_stub_notcallable")
        mod.find_callees = lambda root: {}
        mod.find_by_name_consumers = "строка, а не функция"
        sys.modules[mod.__name__] = mod
        self.addCleanup(sys.modules.pop, mod.__name__, None)
        with mock.patch.object(rsc, "NEIGHBOUR_CENSUS", mod.__name__):
            with rsc._neighbour_query_memo() as witness:
                pass
        self.assertFalse(witness["installed"])
        self.assertEqual("строка, а не функция", mod.find_by_name_consumers)


class TheMemoIsWiredIntoMeasureItself(_StubNeighbourCase):
    """Проводка: память ставит САМ прогон, и свидетель едет в документ."""

    @staticmethod
    def _tree(base: Path) -> Path:
        (base / "spa_core" / "tests").mkdir(parents=True)
        (base / "scripts").mkdir(parents=True)
        (base / "spa_core" / "risk").mkdir(parents=True, exist_ok=True)
        (base / "spa_core" / "risk" / "policy.py").write_text(
            "MAX_DRAWDOWN = 0.07\n", encoding="utf-8")
        (base / "spa_core" / "tests" / "test_nothing.py").write_text(
            "OTHER = 1\n_read = (OTHER,)\n", encoding="utf-8")
        (base / "scripts" / "executor.py").write_text(
            "OTHER = 1\n", encoding="utf-8")
        census = base / _STUB_CENSUS_REL
        census.parent.mkdir(parents=True, exist_ok=True)
        census.write_text("def run(root=None):\n    return {}\n",
                          encoding="utf-8")
        return base

    def test_the_document_carries_the_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = rsc.measure(self._tree(Path(tmp)), now=_NOW)
        memo = doc["neighbour_query_memo"]
        self.assertTrue(memo["installed"])
        self.assertEqual(list(rsc.MEMOISED_NEIGHBOUR_QUERIES),
                         memo["queries_declared"])
        self.assertEqual(list(rsc.MEMO_OUTCOMES), memo["outcomes_declared"])

    def test_the_neighbour_is_asked_each_question_once_per_run(self):
        """Собственно предмет: повторный вопрос о том же дереве не доезжает.

        Сцена мала, поэтому число зовов мало; проверяется НЕ величина
        экономии (её мерит цикл), а то, что у КАЖДОГО объявленного вопроса
        счётчик соседа не растёт со второго раза.
        """
        with tempfile.TemporaryDirectory() as tmp:
            doc = rsc.measure(self._tree(Path(tmp)), now=_NOW)
        memo = doc["neighbour_query_memo"]
        asked = {}
        for call in self.stub.calls:
            asked[call] = asked.get(call, 0) + 1
        self.assertTrue(asked, "сосед не был спрошен ни разу — сцена ничего не мерит")
        self.assertEqual([], [k for k, n in asked.items() if n > 1],
                         f"один и тот же вопрос задан соседу дважды: {asked}")
        reused = sum(s["reused"] for s in memo["queries"].values())
        self.assertGreater(
            reused, 0,
            "ни один вопрос не был задан дважды — сцена не отличила бы "
            "работающую память от её отсутствия")

    def test_without_the_memo_the_same_question_is_asked_again(self):
        """Контроль в ОБРАТНУЮ сторону: сцена ВИДИТ повтор, когда он есть.

        Тело переписи зовётся напрямую (``measure.__wrapped__``), то есть мимо
        памяти. Если бы сцена не умела различать два состояния, зелёный
        соседний тест ничего бы не значил.
        """
        with tempfile.TemporaryDirectory() as tmp:
            rsc.measure.__wrapped__(self._tree(Path(tmp)), now=_NOW)
        asked = {}
        for call in self.stub.calls:
            asked[call] = asked.get(call, 0) + 1
        self.assertTrue([k for k, n in asked.items() if n > 1],
                        f"без памяти повтора не случилось: {asked}")

    def test_the_memo_is_taken_back_after_measure(self):
        before = self.stub.find_callees
        with tempfile.TemporaryDirectory() as tmp:
            rsc.measure(self._tree(Path(tmp)), now=_NOW)
        self.assertIs(before, self.stub.find_callees)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
