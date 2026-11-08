"""СУДЬБА глушителя — род, который предмет ДВИГАЕТ, и это ИЗМЕРЕНО крайностями.

Предмет (ADR-951, цикл #1069, заказ G939 п. 1). ADR-950 ответил: из 82 чтений
`x[k]` за границей своей функции заглушено звавшим **66**. Заказ велел завести
для них род — и поставил условие, выросшее из цены ADR-943:

> сперва прогнать ось с родом и без рода, сравнить предмет, и только потом править

Условие и есть предмет этого файла, и у него ДВЕ половины, которые нельзя
смешивать:

* **крайности РАСХОДЯТСЯ** ⇒ род двигает предмет ПО ПОСТРОЕНИЮ, и двигает его
  РОВНО одна судьба — `reraised`;
* **крайности внутри глушащих судеб СОВПАДАЮТ** ⇒ перекладывание чтения между
  `renamed` и `lost` предмета не меняет НИКОГДА — это описание ВРЕДА, а не
  принадлежности предмету. Ровно форма ADR-943, и сказать её вслух обязательно:
  отчёт сам по себе внушает обратное.

Контроль в ОБРАТНУЮ сторону обязателен (`.claude/rules/acceptance.md` п. 3): при
роде, сделанном декоративным (ни одна судьба не снимает глушение), крайности
обязаны СОВПАСТЬ — иначе тест не умеет видеть поломку и является украшением.

Сцены — одноразовые деревья; живое `data/`, трекер и прод-дерево не трогаются ни
одним байтом. Прибор только ЧИТАЕТ: ни один глушитель дерева не снят и не правлен.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

from spa_core.tests import _caller_silencer as cs
from spa_core.tests import _empty_collection_harm as harm
from spa_core.tests import _silencer_fate as fates

_TREE_FACTS: Optional[Dict[str, cs.ModuleFacts]] = None


def tree_facts() -> Dict[str, cs.ModuleFacts]:
    """Факты НАСТОЯЩЕГО дерева — один раз на прогон."""
    global _TREE_FACTS
    if _TREE_FACTS is None:
        _TREE_FACTS, _unread = cs.load_surface(harm.REPO_ROOT)
    return _TREE_FACTS


def fate(code: str, index: int = 0):
    """Судьба обработчика №``index`` в коде ``code``."""
    node = ast.parse(code).body[0]
    assert isinstance(node, ast.Try), "сцена обязана быть `try`"
    return fates.fate_of_handler(node.handlers[index])


class Scene:
    """Одноразовое дерево-сцена: только файлы, которые назвал тест."""

    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spa_core").mkdir()

    def write(self, rel: str, text: str) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return rel

    def ask(self, rel: str, fname: str, fate_of=None) -> dict:
        facts, unread = cs.load_surface(self.root)
        assert not unread, f"сцена не прочитана: {unread}"
        return cs.loudness_through_callers(rel, fname, False, facts, fate_of)

    def close(self) -> None:
        self._tmp.cleanup()


# ─────────────────────── судьба ОДНОГО обработчика ───────────────────────────

class FateOfOneHandler(unittest.TestCase):
    """Сцены: каждая пара различается РОВНО одним звеном."""

    def test_an_unconditional_raise_is_reraised(self) -> None:
        got, why = fate("try:\n  g()\nexcept Exception:\n  raise\n")
        self.assertEqual("reraised", got, why)

    def test_a_conditional_raise_is_unmeasured_not_reraised(self) -> None:
        """`reraised` ТРЕБУЕТ доказательства по ВСЕМ путям.

        Отличие от сцены выше — РОВНО одно звено (`if`), и ответ обязан
        съехать в третий исход, а не в судьбу: часть путей из обработчика
        выходит молча.
        """
        got, why = fate("try:\n  g()\nexcept Exception:\n  if x:\n    raise\n")
        self.assertEqual("unmeasured", got, why)
        self.assertIn("НЕ на каждом пути", why)

    def test_a_raise_inside_a_nested_def_is_not_reraised(self) -> None:
        """Отложенный код поимкой исключения не исполняется."""
        got, why = fate("try:\n  g()\nexcept Exception:\n"
                        "  def later():\n    raise RuntimeError\n  pass\n")
        self.assertEqual("lost", got, why)

    def test_the_caught_exception_leaving_the_handler_is_renamed(self) -> None:
        """Господствующая форма дерева: причина уходит наружу СТРОКОЙ."""
        got, why = fate('try:\n  g()\nexcept Exception as exc:\n'
                        '  return {"r": f"{type(exc).__name__}: {exc}"}\n')
        self.assertEqual("renamed", got, why)
        self.assertIn("уходит наружу", why)

    def test_a_recording_call_is_renamed_even_without_a_bound_name(self) -> None:
        got, why = fate("try:\n  g()\nexcept Exception:\n  unread.append(rel)\n")
        self.assertEqual("renamed", got, why)
        self.assertIn(".append()", why)

    def test_a_return_that_never_mentions_the_exception_is_lost(self) -> None:
        """Отличие от `..._is_renamed` — РОВНО дорога значения."""
        got, why = fate("try:\n  g()\nexcept Exception as exc:\n  return None\n")
        self.assertEqual("lost", got, why)

    def test_pass_is_lost(self) -> None:
        got, why = fate("try:\n  g()\nexcept Exception:\n  pass\n")
        self.assertEqual("lost", got, why)

    def test_substituting_a_default_is_lost(self) -> None:
        got, why = fate("try:\n  g()\nexcept Exception:\n  _fm = {}\n")
        self.assertEqual("lost", got, why)

    def test_an_unparsed_body_is_unmeasured_not_lost(self) -> None:
        """Третий исход не выдаётся ни за одну судьбу (инв. #17)."""
        got, why = fate("try:\n  g()\nexcept Exception:\n"
                        "  for y in z:\n    y.ping\n")
        self.assertEqual("unmeasured", got, why)
        self.assertIn("не разобрано", why)


# ───────────────── ДВЕ КРАЙНОСТИ: покупает ли род хоть бит ───────────────────

#: Сцена: ОДНО чтение, заглушённое звавшим. Без неё замер был бы ПУСТЫМ, и обе
#: крайности совпали бы «ни о чём» — поэтому непустота проверяется ГРОМКО.
SCENE_SILENCED = '''\
TARGET = {}


def reader():
    return TARGET["k"]


def caller():
    try:
        return reader()
    except Exception as exc:
        return {"reason": str(exc)}
'''


class TheExtremesOfTheFateAxis(unittest.TestCase):
    """Крайности мерятся ДО того, как род начинает судить (заказ G939 п. 1)."""

    def setUp(self) -> None:
        self.scene = Scene()
        self.addCleanup(self.scene.close)
        self.rel = self.scene.write("spa_core/scene_mod.py", SCENE_SILENCED)

    def test_the_scene_is_not_empty_and_that_is_measured(self) -> None:
        """Сцена, не предъявившая глушения, не доказывает НИЧЕГО."""
        got = self.scene.ask(self.rel, "reader")
        self.assertEqual("silenced", got["loudness"], got["why"])

    def test_without_the_kind_the_answer_is_exactly_ADR_950(self) -> None:
        """`fate_of=None` означает «вопрос о судьбе не задан» — и только это."""
        got = self.scene.ask(self.rel, "reader", None)
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertIsNone(got.get("fate"))

    def test_the_extremes_DIVERGE_so_the_kind_buys_a_bit(self) -> None:
        """ГЛАВНОЕ утверждение: род двигает предмет ПО ПОСТРОЕНИЮ.

        Это ровно тот замер, которого не хватило ADR-943: там крайности
        СОВПАЛИ (предмет 571 -> 571), и ось оказалась украшением. Здесь они
        обязаны разойтись — иначе род заводить нельзя.
        """
        lost = self.scene.ask(self.rel, "reader", fates.constant_fate("lost"))
        reraised = self.scene.ask(self.rel, "reader",
                                  fates.constant_fate("reraised"))
        self.assertEqual("silenced", lost["loudness"], lost["why"])
        self.assertNotEqual("silenced", reraised["loudness"], reraised["why"])

    def test_moving_a_read_BETWEEN_silencing_fates_changes_nothing(self) -> None:
        """Вторая половина утверждения, и сказать её вслух обязательно.

        `renamed` и `lost` — описание ВРЕДА, а не принадлежности предмету.
        Отчёт, печатающий их рядом с `reraised`, внушает, будто каждая судьба
        что-то решает; предмет при перекладывании между ними НЕ МЕНЯЕТСЯ.
        """
        verdicts = {
            name: self.scene.ask(self.rel, "reader",
                                 fates.constant_fate(name))["loudness"]
            for name in fates.SILENCING_FATES
        }
        self.assertEqual({"silenced"}, set(verdicts.values()), verdicts)

    def test_a_decorative_kind_makes_the_extremes_COINCIDE(self) -> None:
        """КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ.

        Род, ни одна судьба которого не снимает глушения, обязан дать
        совпадение крайностей. Не умей тест этого увидеть — он был бы
        украшением, а не мерой.
        """
        decorative = {name: self.scene.ask(
            self.rel, "reader",
            fates.constant_fate("lost" if name == "reraised" else name),
        )["loudness"] for name in fates.FATES}
        self.assertEqual({"silenced"}, set(decorative.values()), decorative)


# ──────────── контроль на НАСТОЯЩИХ членах дерева (п. 3 правила) ─────────────

class ControlOnRealTreeMembers(unittest.TestCase):
    """Три известных члена класса ADR-950 — и у всех трёх судьба ОДНА.

    Первая редакция прибора спрашивала ФОРМУ последнего оператора и называла
    `return` бесследным; на этих трёх она ответила `lost` у 3 из 3, то есть
    ошиблась в ОПАСНУЮ сторону (вред завышен, причина названа неверно). Контроль
    и нашёл дефект — он здесь не для украшения.
    """

    MEMBERS = (
        ("spa_core/monitoring/reachability_of_the_rest.py", "_cross"),
        ("spa_core/monitoring/criterion_sign_price.py", "scorable_days"),
    )

    def test_known_members_are_silenced_and_their_fate_is_renamed(self) -> None:
        for rel, fname in self.MEMBERS:
            with self.subTest(member=f"{rel}::{fname}"):
                got = cs.loudness_through_callers(
                    rel, fname, False, tree_facts(),
                    fates.fate_of_handler)
                self.assertEqual("silenced", got["loudness"], got["why"])
                self.assertEqual("renamed", got.get("fate"),
                                 got.get("fate_why") or got["why"])

    def test_the_same_members_stay_silenced_when_the_kind_is_not_asked(self) -> None:
        """Род ничего не ломает: без вопроса ответ тот же, что у ADR-950."""
        for rel, fname in self.MEMBERS:
            with self.subTest(member=f"{rel}::{fname}"):
                got = cs.loudness_through_callers(rel, fname, False, tree_facts())
                self.assertEqual("silenced", got["loudness"], got["why"])
                self.assertIsNone(got.get("fate"))


# ───────────────── объявление несёт СВОЙ контракт (ADR-932) ──────────────────

class DeclarationCarriesItsOwnContract(unittest.TestCase):

    SOURCE = Path(fates.__file__).read_text(encoding="utf-8")

    def test_every_declared_fate_is_actually_produced(self) -> None:
        produced = {node.value for node in ast.walk(ast.parse(self.SOURCE))
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)}
        for name in fates.FATES:
            self.assertIn(name, produced,
                          f"объявленная судьба `{name}` прибором не произносится")

    def test_the_silencing_fates_are_DERIVED_not_hand_listed(self) -> None:
        """Разойдись перечень с выводом — и утверждение «предмет двигает ровно
        `reraised`» перестало бы быть верным МОЛЧА (урок ADR-943)."""
        self.assertEqual(set(fates.FATES) - {"reraised"},
                         set(fates.SILENCING_FATES))
        self.assertNotIn("reraised", fates.SILENCING_FATES)

    def test_a_fate_outside_the_closed_list_reddens_the_guard(self) -> None:
        with self.assertRaises(ValueError):
            fates.fate_tally([{"fate": "выдуманная"}])
        with self.assertRaises(ValueError):
            fates.constant_fate("выдуманная")

    def test_the_tally_keys_are_exactly_the_closed_list(self) -> None:
        self.assertEqual(list(fates.FATES), list(fates.fate_tally([]).keys()))

    def test_the_kind_is_NOT_asked_unless_it_is_asked(self) -> None:
        """Умолчание `fate_of=None` — у КАЖДОЙ двери, и это claim, а не вкус.

        Поведение ADR-950 обязано остаться прежним у того, кто род не
        спрашивал. Прогон `caller_reads()` стои́т ≈180 с, в батарею его не
        позвать, поэтому claim проверяется там, где он ОБЪЯВЛЕН — в подписи:
        мутация «умолчание = `fate_of_handler`» пережила первую редакцию этой
        батареи РОВНО потому, что ни один тест не спрашивал про умолчание.
        """
        for door in (cs.caller_reads, cs.loudness_through_callers,
                     cs.silencer_at_site_with_fate):
            with self.subTest(door=door.__name__):
                param = inspect.signature(door).parameters.get("fate_of")
                self.assertIsNotNone(param, f"у `{door.__name__}` нет входа `fate_of`")
                self.assertIsNone(
                    param.default,
                    f"`{door.__name__}` спрашивает род БЕЗ просьбы — поведение "
                    "ADR-950 у её вызывающих изменилось бы молча")

    def test_the_old_door_asks_nothing_about_the_kind(self) -> None:
        """У прежней двери входа `fate_of` нет ВОВСЕ — она его и не передаёт."""
        self.assertNotIn("fate_of",
                         inspect.signature(cs.silencer_at_site).parameters)

    def test_the_old_door_delegates_and_keeps_no_copy(self) -> None:
        """У разбора ОДИН вход: своя копия разошлась бы молча (урок ADR-774)."""
        tree = ast.parse(Path(cs.__file__).read_text(encoding="utf-8"))
        bodies = [node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "silencer_at_site"]
        self.assertEqual(1, len(bodies))
        delegates = [node for node in ast.walk(bodies[0])
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)
                     and node.func.id == "silencer_at_site_with_fate"]
        self.assertEqual(1, len(delegates),
                         "прежняя дверь обязана ДЕЛЕГИРОВАТЬ, а не повторять разбор")


# ───────────────── объявление ИМЕНАМИ и его ЧИТАТЕЛЬ ────────────────────────

class TheDeclarationOfTheMeasuredPopulation(unittest.TestCase):
    """База объявляет 66 членов ИМЕНАМИ, и у неё есть читатель.

    Число без имён перемерить нельзя (урок ADR-913), а объявление без читателя
    есть записка (урок ADR-918). Дорогую перепись (≈180 с) в батарею звать
    нельзя, поэтому читатель здесь ДВОЙНОЙ: контракт базы проверяется целиком,
    а согласие с живым прибором — на ВЫБОРКЕ известных членов, и команда
    полного перемера объявлена в самой базе.
    """

    BASE = json.loads(
        (Path(__file__).resolve().parent / "silencer_fate_baseline.json")
        .read_text(encoding="utf-8"))

    def test_the_declaration_counts_its_own_members(self) -> None:
        self.assertEqual(self.BASE["предмет"]["silenced"],
                         len(self.BASE["члены"]))
        by_fate: Dict[str, int] = {}
        for member in self.BASE["члены"]:
            by_fate[member["судьба"]] = by_fate.get(member["судьба"], 0) + 1
        declared = {k: v for k, v in self.BASE["судьбы"].items() if v}
        self.assertEqual(declared, by_fate)

    def test_every_declared_fate_is_in_the_closed_list(self) -> None:
        self.assertEqual(list(fates.FATES), list(self.BASE["судьбы"].keys()))
        for member in self.BASE["члены"]:
            self.assertIn(member["судьба"], fates.FATES, member)

    def test_the_extremes_are_declared_and_they_DIVERGE(self) -> None:
        """Заказ G939 п. 1 требовал сравнения ДО правки — и оно в базе."""
        ext = self.BASE["крайности_на_том_же_дереве"]
        self.assertNotEqual(ext["без_рода"]["silenced"],
                            ext["все_reraised"]["silenced"],
                            "крайности СОВПАЛИ — род был бы украшением (ADR-943)")
        self.assertEqual(ext["все_lost"]["silenced"], ext["все_renamed"]["silenced"],
                         "перекладывание между глушащими судьбами предмет НЕ меняет")

    def test_the_command_to_remeasure_is_named(self) -> None:
        """«Перемерить нечем» — та же записка, что объявление без читателя."""
        self.assertIn("caller_reads", self.BASE["_перемерить"])
        self.assertIn("fate_of_handler", self.BASE["_перемерить"])

    def test_a_sample_of_the_declaration_agrees_with_the_live_instrument(self) -> None:
        """Выборка: известные члены дерева. Полный перемер — командой из базы."""
        declared = {m["чтение"]: m for m in self.BASE["члены"]}
        checked = 0
        for rel, fname in ControlOnRealTreeMembers.MEMBERS:
            got = cs.loudness_through_callers(rel, fname, False, tree_facts(),
                                              fates.fate_of_handler)
            hits = [m for key, m in declared.items()
                    if key.startswith(f"{rel}:") and m["функция"] == fname]
            self.assertTrue(hits, f"{rel}::{fname} в базе не объявлен")
            for member in hits:
                self.assertEqual(member["судьба"], got.get("fate"), member)
                checked += 1
        self.assertGreater(checked, 0, "выборка ПУСТА — тест не доказывает ничего")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
