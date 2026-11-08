#!/usr/bin/env python3
"""Контроль объявления ADR-952 — ТОЧКА ВХОДА КАРКАСА.

# LLM_FORBIDDEN

Каждая сцена отличается от соседней РОВНО одним звеном, и вердикты
ПРОТИВОПОЛОЖНЫЕ: прибор, отвечающий одно и то же всегда, дал бы те же числа, и
отличить его от замера было бы нечем (дословный урок `pyflakes`).

**Контроли стоя́т на НАСТОЯЩИХ членах дерева, а не только на сценах** — то же
требование, что у ADR-950/951. Члены названы поимённо: `auth.py::me` и
`agents.py::_public_view` (маршруты), `test_consume_office_reports.py::
test_report_without_generated_at_is_unmeasured` (тест как цель замера), и ДВА
прежних члена ADR-950 (`_cross`, `scorable_days`) — как контроль на то, что
объявление НЕ сдвинуло ни одного ответа, который прибор уже давал.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

from spa_core.tests import _caller_silencer as cs
from spa_core.tests import _empty_collection_harm as harm
from spa_core.tests import _framework_entry as fw
from spa_core.tests import _silencer_fate as fates

_TREE_FACTS: Optional[Dict[str, cs.ModuleFacts]] = None


def tree_facts() -> Dict[str, cs.ModuleFacts]:
    """Факты НАСТОЯЩЕГО дерева — один раз на прогон."""
    global _TREE_FACTS
    if _TREE_FACTS is None:
        _TREE_FACTS, _unread = cs.load_surface(harm.REPO_ROOT)
    return _TREE_FACTS


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

    def ask(self, rel: str, fname: str, is_method: bool = False,
            with_fate: bool = True) -> dict:
        facts, unread = cs.load_surface(self.root)
        assert not unread, f"сцена не прочитана: {unread}"
        return cs.loudness_through_callers(
            rel, fname, is_method, facts,
            fates.fate_of_handler if with_fate else None)

    def facts(self) -> Dict[str, cs.ModuleFacts]:
        facts, unread = cs.load_surface(self.root)
        assert not unread, f"сцена не прочитана: {unread}"
        return facts

    def close(self) -> None:
        self._tmp.cleanup()


class SceneBase(unittest.TestCase):

    def setUp(self) -> None:
        self.scene = Scene()
        self.addCleanup(self.scene.close)


# ────────────────────── маршрут ASGI: ДОРОГА ЗНАЧЕНИЯ ───────────────────────

_ROUTE = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "@router.get('/x')\n"
    "def handler():\n    return {}['x']\n"
)


class AnAsgiRouteIsDeclaredSilenced(SceneBase):

    def test_a_route_handler_is_silenced_and_its_fate_is_renamed(self) -> None:
        rel = self.scene.write("spa_core/a.py", _ROUTE)
        got = self.scene.ask(rel, "handler")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("asgi_route", got["silencer"], got["why"])
        self.assertEqual("renamed", got.get("fate"), got["why"])
        self.assertIn("ServerErrorMiddleware", got["why"])

    def test_the_SAME_decorator_on_a_router_that_is_NOT_one_is_unmeasured(self) -> None:
        """Отличие от соседа РОВНО одно — откуда в `router` пришло ЗНАЧЕНИЕ.

        Признавай прибор маршрут по написанию имени, и `router = object()`
        отвечал бы «заглушено» — то есть объявление мерило бы орфографию.
        """
        rel = self.scene.write("spa_core/a.py", (
            "router = object()\n"
            "@router.get('/x')\n"
            "def handler():\n    return {}['x']\n"))
        got = self.scene.ask(rel, "handler")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("НЕ ОБЪЯВЛЕН", got["why"])

    def test_a_factory_not_imported_from_the_framework_is_unmeasured(self) -> None:
        """Отличие РОВНО одно — `APIRouter` ввезён не из каркаса."""
        rel = self.scene.write("spa_core/a.py", (
            "from spa_core.local import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/x')\n"
            "def handler():\n    return {}['x']\n"))
        self.scene.write("spa_core/local.py", "def APIRouter():\n    return object()\n")
        got = self.scene.ask(rel, "handler")
        self.assertEqual("unmeasured", got["loudness"], got["why"])

    def test_a_verb_outside_the_declared_list_is_unmeasured(self) -> None:
        """Отличие РОВНО одно — глагол. `@router.middleware` маршрутом не является."""
        rel = self.scene.write("spa_core/a.py", _ROUTE.replace(
            "@router.get('/x')", "@router.middleware('http')"))
        got = self.scene.ask(rel, "handler")
        self.assertEqual("unmeasured", got["loudness"], got["why"])

    def test_a_route_that_is_ALSO_a_pytest_test_is_silenced_not_loud(self) -> None:
        """Одно имя — два объявленных каркаса, и побеждает ЗАГЛУШАЮЩИЙ.

        Порядок :data:`_framework_entry._PROBES` есть утверждение: `loud` —
        единственный вердикт, снимающий чтение с приоритета, поэтому ошибаться
        при встрече двух каркасов обязано в сторону предмета. Возьми прибор
        первый попавшийся каркас (порядок обхода AST), и тот же файл отвечал бы
        по-разному от перестановки строк.
        """
        rel = self.scene.write("spa_core/tests/test_s.py", (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/x')\n"
            "def test_route():\n    return {}['x']\n"))
        got = self.scene.ask(rel, "test_route")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("asgi_route", got["silencer"], got["why"])

    def test_the_worst_kind_wins_even_when_AST_ORDER_disagrees(self) -> None:
        """Мутация M16 ПЕРЕЖИЛА первую редакцию батареи, и названа честно.

        Прежняя сцена ставила ОБА каркаса на ОДНО объявление, и тогда порядок
        обхода AST совпадал с порядком опроса — мутант «бери первый найденный»
        был ей ЭКВИВАЛЕНТЕН. Здесь объявления ДВА и порядок в файле ОБРАТНЫЙ
        нужному: мутант ответил бы `loud`, то есть снял бы чтение с предмета от
        перестановки строк в чужом файле.
        """
        rel = self.scene.write("spa_core/tests/test_s.py", (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "def test_route():\n    return {}['x']\n"
            "@router.get('/x')\n"
            "def test_route():\n    return {}['x']\n"))
        got = self.scene.ask(rel, "test_route")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("asgi_route", got["silencer"], got["why"])

    def test_a_route_silences_even_when_tests_call_it(self) -> None:
        """Громкость принадлежит ПУТИ, и один заглушающий путь отменяет остальные.

        Это та же мера, что у ADR-950, и положительный контроль на обратную
        ошибку: восемь вызовов из тестов полным набором звавших не являются,
        потому что в проде обработчик зовёт каркас.
        """
        rel = self.scene.write("spa_core/a.py", _ROUTE)
        self.scene.write("spa_core/tests/test_s.py", (
            "from spa_core.a import handler\n"
            "def test_s():\n    handler()\n"))
        got = self.scene.ask(rel, "handler")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("asgi_route", got["silencer"], got["why"])


# ─────────── тест как ЦЕЛЬ замера: асимметрия прыжка закрыта ────────────────


class APytestTestIsTheSameEntryAtBothHops(SceneBase):
    """Один и тот же `def test_…` — точка входа и когда ЗВЁТ, и когда ЕГО мерят.

    До ADR-952 ответ решал НОМЕР ПРЫЖКА: вызов внутри теста давал `loud`
    (`entry.pytest_test`), а чтение В ТЕЛЕ того же теста — «звавший вне дерева».
    Обе сцены ниже отличаются РОВНО тем, где лежит чтение, и обязаны дать ОДИН
    вердикт и ОДИН род точки входа.
    """

    def test_a_read_inside_a_test_body_is_loud(self) -> None:
        rel = self.scene.write("spa_core/tests/test_s.py",
                               "def test_s():\n    return {}['x']\n")
        got = self.scene.ask(rel, "test_s")
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["pytest_test"])

    def test_a_read_one_hop_below_the_same_test_is_loud_too(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/tests/test_s.py", (
            "from spa_core.a import f\n"
            "def test_s():\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["pytest_test"])

    def test_a_helper_in_a_test_file_is_NOT_a_test(self) -> None:
        """Отличие РОВНО одно — имя не начинается с `test_`; pytest её не зовёт."""
        rel = self.scene.write("spa_core/tests/test_s.py",
                               "def helper():\n    return {}['x']\n")
        got = self.scene.ask(rel, "helper")
        self.assertEqual("unmeasured", got["loudness"], got["why"])

    def test_a_test_named_function_OUTSIDE_a_test_path_is_not_a_test(self) -> None:
        """Отличие РОВНО одно — путь. pytest собирает по пути, а не по имени."""
        rel = self.scene.write("spa_core/a.py",
                               "def test_s():\n    return {}['x']\n")
        got = self.scene.ask(rel, "test_s")
        self.assertEqual("unmeasured", got["loudness"], got["why"])


# ───────────────────── фикстура и крюк unittest ─────────────────────────────


class PytestFixtureAndUnittestHook(SceneBase):

    def test_a_pytest_fixture_is_a_loud_entry(self) -> None:
        rel = self.scene.write("spa_core/tests/conftest.py", (
            "import pytest\n"
            "@pytest.fixture\n"
            "def thing():\n    return {}['x']\n"))
        got = self.scene.ask(rel, "thing")
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["pytest_fixture"])

    def test_the_same_decorator_without_pytest_is_unmeasured(self) -> None:
        """Отличие РОВНО одно — `fixture` ввезена не из pytest."""
        rel = self.scene.write("spa_core/tests/conftest.py", (
            "from spa_core.local import fixture\n"
            "@fixture\n"
            "def thing():\n    return {}['x']\n"))
        self.scene.write("spa_core/local.py", "def fixture(f):\n    return f\n")
        got = self.scene.ask(rel, "thing")
        self.assertEqual("unmeasured", got["loudness"], got["why"])

    def test_a_unittest_hook_is_a_loud_entry(self) -> None:
        rel = self.scene.write("spa_core/tests/test_s.py", (
            "import unittest\n"
            "class C(unittest.TestCase):\n"
            "    def setUp(self):\n        self.x = {}['x']\n"))
        got = self.scene.ask(rel, "setUp", is_method=True)
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["unittest_hook"])

    def test_the_same_hook_name_outside_a_TestCase_is_unmeasured(self) -> None:
        """Отличие РОВНО одно — база класса. `setUp` у чужого класса не крюк."""
        rel = self.scene.write("spa_core/tests/test_s.py", (
            "class C:\n"
            "    def setUp(self):\n        self.x = {}['x']\n"))
        got = self.scene.ask(rel, "setUp", is_method=True)
        self.assertEqual("unmeasured", got["loudness"], got["why"])


# ──────────────────── каркас ВНЕ объявления — fail-CLOSED ───────────────────


class AnUndeclaredFrameworkStaysUnmeasured(SceneBase):

    def test_an_unknown_decorator_is_unmeasured_not_loud_and_not_silenced(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "import celery\n"
            "@celery.task\n"
            "def job():\n    return {}['x']\n"))
        got = self.scene.ask(rel, "job")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("НЕ ОБЪЯВЛЕН", got["why"])

    def test_the_door_answers_None_for_a_module_outside_the_surface(self) -> None:
        self.assertIsNone(fw.framework_entry("нет/такого.py", "f", {}))

    def test_the_door_answers_None_for_an_unparsed_module(self) -> None:
        facts = {"spa_core/a.py": cs.ModuleFacts("spa_core/a.py", None, "не прочитан")}
        self.assertIsNone(fw.framework_entry("spa_core/a.py", "f", facts))


# ───────────── объявление несёт СВОЙ контракт (ADR-932) ─────────────────────


class TheDeclarationCarriesItsOwnContract(unittest.TestCase):

    def test_every_member_names_its_mechanism(self) -> None:
        for kind, entry in fw.DECLARATION.items():
            with self.subTest(kind=kind):
                self.assertGreaterEqual(
                    len(entry.why), 40,
                    "механизм не назван — это не объявление, а вкус")

    def test_a_verdict_outside_the_closed_list_reddens_the_check(self) -> None:
        broken = dict(fw.DECLARATION)
        broken["pytest_test"] = fw.DECLARATION["pytest_test"]._replace(
            verdict="выдуманный")
        with _declaration(broken), self.assertRaises(ValueError):
            fw._check_declaration()

    def test_a_silencing_member_without_a_fate_reddens_the_check(self) -> None:
        broken = dict(fw.DECLARATION)
        broken["asgi_route"] = fw.DECLARATION["asgi_route"]._replace(fate=None)
        with _declaration(broken), self.assertRaises(ValueError):
            fw._check_declaration()

    def test_a_fate_on_a_loud_member_reddens_the_check(self) -> None:
        """Судьба при `loud` — поле без читателя, и это тоже дефект."""
        broken = dict(fw.DECLARATION)
        broken["pytest_test"] = fw.DECLARATION["pytest_test"]._replace(
            fate="renamed")
        with _declaration(broken), self.assertRaises(ValueError):
            fw._check_declaration()

    def test_a_member_without_a_named_mechanism_reddens_the_check(self) -> None:
        """Мутация M17 ПЕРЕЖИЛА первую редакцию батареи, и названа честно.

        Соседний тест сверял длину механизма ПРЯМО у объявления, то есть
        проверял объявление, а не ПРОВЕРКУ: сними требование из
        `_check_declaration`, и ни один тест не покраснел бы — у claim «объявление
        без механизма есть ярлык» не было читателя (та же форма, что M9 у
        ADR-951).
        """
        broken = dict(fw.DECLARATION)
        broken["pytest_test"] = fw.DECLARATION["pytest_test"]._replace(
            why="каркас")
        with _declaration(broken), self.assertRaises(ValueError):
            fw._check_declaration()

    def test_a_member_filed_under_another_name_reddens_the_check(self) -> None:
        broken = dict(fw.DECLARATION)
        broken["asgi_route"] = fw.DECLARATION["asgi_route"]._replace(kind="чужое")
        with _declaration(broken), self.assertRaises(ValueError):
            fw._check_declaration()

    def test_the_declared_fate_belongs_to_the_closed_list_of_fates(self) -> None:
        for kind in fw.SILENCED_ENTRY_KINDS:
            self.assertIn(fw.DECLARATION[kind].fate, fates.SILENCING_FATES, kind)

    def test_the_kind_lists_are_DERIVED_not_hand_listed(self) -> None:
        """Разойдись перечень с объявлением — и утверждение «вот эти каркасы
        громкие» перестало бы быть верным МОЛЧА (урок ADR-943)."""
        self.assertEqual(set(fw.DECLARATION), set(fw.ENTRY_KINDS))
        self.assertEqual(
            set(fw.LOUD_ENTRY_KINDS),
            {k for k, v in fw.DECLARATION.items() if v.verdict == "loud"})
        self.assertEqual(
            set(fw.SILENCED_ENTRY_KINDS),
            {k for k, v in fw.DECLARATION.items() if v.verdict == "silenced"})
        self.assertFalse(set(fw.LOUD_ENTRY_KINDS) & set(fw.SILENCED_ENTRY_KINDS))

    def test_the_kind_lists_are_derived_IN_THE_SOURCE_not_only_in_value(self) -> None:
        """Мутация M9 ПЕРЕЖИЛА первую редакцию батареи, и названа честно.

        Соседний тест сверяет ЗНАЧЕНИЯ, а перечень, набранный рукой, даёт сегодня
        РОВНО те же значения — то есть у claim «выведено, а не перечислено» не
        было читателя ВООБЩЕ (дословно та же форма дефекта, что M9 у ADR-951).
        Читается ИСХОДНИК: правая часть каждого перечня обязана ссылаться на
        `DECLARATION`, иначе перечень разойдётся с объявлением МОЛЧА при первом
        же новом каркасе.
        """
        tree = ast.parse(Path(fw.__file__).read_text(encoding="utf-8"))
        wanted = {"LOUD_ENTRY_KINDS", "SILENCED_ENTRY_KINDS", "ENTRY_KINDS"}
        seen = set()
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign)
                       else [])
            names = {t.id for t in targets if isinstance(t, ast.Name)} & wanted
            if not names or node.value is None:
                continue
            refs = {sub.id for sub in ast.walk(node.value)
                    if isinstance(sub, ast.Name)}
            for name in names:
                seen.add(name)
                self.assertIn(
                    "DECLARATION", refs,
                    f"`{name}` набран РУКОЙ: разойдись он с объявлением — и "
                    "утверждение «вот эти каркасы громкие» перестанет быть "
                    "верным молча (ADR-943)")
        self.assertEqual(wanted, seen, "перечень не найден в исходнике")

    def test_the_contract_of_the_declaration_is_checked_AT_IMPORT(self) -> None:
        """Проверка без вызова — записка (урок ADR-918): зов обязан быть в модуле."""
        tree = ast.parse(Path(fw.__file__).read_text(encoding="utf-8"))
        calls = [node for node in tree.body
                 if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call)
                 and isinstance(node.value.func, ast.Name)
                 and node.value.func.id == "_check_declaration"]
        self.assertEqual(1, len(calls),
                         "контракт объявления обязан проверяться НА ИМПОРТЕ")

    def test_the_instrument_derives_its_own_lists_from_the_declaration(self) -> None:
        """Перечни прибора ВЫВЕДЕНЫ: своя копия разошлась бы молча (ADR-774)."""
        for kind in fw.SILENCED_ENTRY_KINDS:
            self.assertIn(kind, cs.SILENCER_KINDS)
        for kind in fw.LOUD_ENTRY_KINDS:
            self.assertIn(kind, cs.ENTRY_KINDS)
        self.assertNotIn("asgi_route", cs.ENTRY_KINDS,
                         "глушащий каркас точкой входа `loud` быть не может")

    def test_the_silenced_verdict_is_asked_BEFORE_the_loud_one(self) -> None:
        """Порядок — утверждение, а не вкус: `loud` снимает чтение с предмета."""
        order = [kind for kind, _probe in fw._PROBES]
        self.assertEqual(order[0], "asgi_route")
        for kind in fw.LOUD_ENTRY_KINDS:
            self.assertGreater(order.index(kind), order.index("asgi_route"))


class _declaration:
    """Подменяет объявление на время сцены и ВОЗВРАЩАЕТ его."""

    def __init__(self, replacement: dict) -> None:
        self._new = replacement

    def __enter__(self) -> None:
        self._old = fw.DECLARATION.copy()
        fw.DECLARATION.clear()
        fw.DECLARATION.update(self._new)

    def __exit__(self, *_exc: object) -> None:
        fw.DECLARATION.clear()
        fw.DECLARATION.update(self._old)


# ───────────────────── ОДНА дверь у предиката теста ─────────────────────────


class ThePytestPredicateHasExactlyOneDoor(unittest.TestCase):

    SOURCE = Path(cs.__file__).read_text(encoding="utf-8")

    def test_the_instrument_delegates_and_keeps_no_copy(self) -> None:
        tree = ast.parse(self.SOURCE)
        bodies = [node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_is_pytest_test"]
        self.assertEqual(1, len(bodies))
        delegates = [node for node in ast.walk(bodies[0])
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "is_pytest_test"]
        self.assertEqual(1, len(delegates),
                         "предикат обязан ДЕЛЕГИРОВАТЬ, а не повторять разбор")
        literals = {node.value for node in ast.walk(bodies[0])
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)}
        self.assertNotIn("test_", literals,
                         "своя копия признака вернула бы асимметрию прыжка")


# ───────────────── КОНТРОЛЬ на НАСТОЯЩИХ членах дерева ──────────────────────


class ControlOnRealTreeMembers(unittest.TestCase):
    """Сцены показывают, что дверь СРАБАТЫВАЕТ; члены — что на том, что в дереве."""

    ROUTES = (
        ("spa_core/academy/api/routes/auth.py", "me"),
        ("spa_core/api/routers/agents.py", "_public_view"),
    )
    #: Прежние члены ADR-950: объявление НЕ имеет права сдвинуть их ответ.
    UNTOUCHED = (
        ("spa_core/monitoring/reachability_of_the_rest.py", "_cross"),
        ("spa_core/monitoring/criterion_sign_price.py", "scorable_days"),
    )

    def test_route_handlers_of_the_tree_are_silenced_by_the_framework(self) -> None:
        """Прежний контроль ADR-950 утверждал про эти же члены «НЕ loud», и это
        утверждение сохранено дословно: `silenced` его не ослабляет, а усиливает —
        чтение переходит из «неизвестно» НА ПРЕДМЕТ."""
        for rel, fname in self.ROUTES:
            with self.subTest(member=f"{rel}::{fname}"):
                got = cs.loudness_through_callers(rel, fname, False, tree_facts(),
                                                  fates.fate_of_handler)
                self.assertNotEqual("loud", got["loudness"], got["why"])
                self.assertEqual("silenced", got["loudness"], got["why"])
                self.assertEqual("asgi_route", got["silencer"], got["why"])
                self.assertEqual("renamed", got.get("fate"), got["why"])

    def test_a_route_of_the_tree_stays_silenced_when_the_fate_is_not_asked(self) -> None:
        """Умолчание ADR-950 не тронуто: без вопроса о судьбе её в ответе НЕТ.

        Этот контроль НАШЁЛ дефект в первой редакции ADR-952: объявленная
        каркасом судьба отдавалась всем, в том числе тому, кто о ней не
        спрашивал, — и «судьбы нет» перестало отличаться от «не спрашивали»
        (инв. #17). Вердикт при этом обязан остаться `silenced`: глушитель есть
        свойство пути, а не вопроса о судьбе.
        """
        for rel, fname in self.ROUTES:
            with self.subTest(member=f"{rel}::{fname}"):
                got = cs.loudness_through_callers(rel, fname, False, tree_facts())
                self.assertEqual("silenced", got["loudness"], got["why"])
                self.assertEqual("asgi_route", got["silencer"], got["why"])
                self.assertIsNone(got.get("fate"))
                self.assertIsNone(got.get("fate_why"))

    def test_a_pytest_test_of_the_tree_is_loud_as_the_target_itself(self) -> None:
        got = cs.loudness_through_callers(
            "spa_core/tests/test_consume_office_reports.py",
            "test_report_without_generated_at_is_unmeasured",
            False, tree_facts(), fates.fate_of_handler)
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["pytest_test"], got["why"])

    def test_the_known_members_of_ADR_950_are_UNMOVED(self) -> None:
        """Положительный контроль на обратную ошибку: объявление каркаса обязано
        НИЧЕГО не менять там, где глушитель уже найден разбором."""
        for rel, fname in self.UNTOUCHED:
            with self.subTest(member=f"{rel}::{fname}"):
                got = cs.loudness_through_callers(rel, fname, False, tree_facts(),
                                                  fates.fate_of_handler)
                self.assertEqual("silenced", got["loudness"], got["why"])
                self.assertEqual("try", got["silencer"], got["why"])
                self.assertEqual("renamed", got.get("fate"), got["why"])

    def test_an_undeclared_entry_of_the_tree_stays_unmeasured(self) -> None:
        """`caller_reads` зовёт РУКА, и каркаса для руки не объявлено — третий
        исход сохраняется, а не подменяется догадкой."""
        got = cs.loudness_through_callers(
            "spa_core/tests/_caller_silencer.py", "caller_reads", False,
            tree_facts(), fates.fate_of_handler)
        self.assertEqual("unmeasured", got["loudness"], got["why"])


# ─────────────── ОБЪЯВЛЕНИЕ ЗАМЕРА и его ЧИТАТЕЛЬ ──────────────────────────


class TheMeasurementIsDeclaredByNames(unittest.TestCase):
    """База объявляет закрытые чтения ИМЕНАМИ и сходится с базой ADR-951.

    Число без имён перемерить нельзя (урок ADR-913), а объявление без читателя
    есть записка (урок ADR-918). Полная перепись стои́т ≈180 с и в батарею не
    зовётся; читатель здесь ДВОЙНОЙ — контракт базы целиком, и согласие с живым
    прибором на ВЫБОРКЕ названных членов.
    """

    HERE = Path(__file__).resolve().parent
    BASE = json.loads((HERE / "framework_entry_baseline.json")
                      .read_text(encoding="utf-8"))
    PRIOR = json.loads((HERE / "silencer_fate_baseline.json")
                       .read_text(encoding="utf-8"))
    SHIFT = BASE["вход_тоже_сдвинулся_и_это_НЕ_закрытие"]

    def test_the_declaration_counts_its_own_closed_reads(self) -> None:
        self.assertEqual(len(self.BASE["закрытые"]),
                         self.BASE["закрыто"])

    def test_every_closed_read_names_the_kind_that_closed_it(self) -> None:
        for row in self.BASE["закрытые"]:
            with self.subTest(read=row["чтение"]):
                self.assertIn(row["род"], fw.ENTRY_KINDS)
                self.assertIn(row["исход"], cs.OUTCOMES)
                self.assertNotEqual("unmeasured", row["исход"])

    def test_the_two_baselines_RECONCILE(self) -> None:
        """Читатель, который покраснеет, разойдись замеры МОЛЧА.

        База ADR-951 датирована своим деревом и НЕ правится; но её числа и мои
        обязаны сходиться, иначе одно из двух объявлений перестало быть правдой,
        и сказать об этом некому.

        **Слагаемое «вышли из поверхности» — не поправка, а ЗАМЕР, и без него
        отчёт удвоил бы заслугу.** Предмет убыл на 8, а ОБЪЯВЛЕНИЕМ закрыты
        ровно 4; ещё 4 чтения ответа не получили — они перестали быть членами
        класса, потому что батарея этого же цикла ДАЛА читателя объявлениям
        `ENTRY_KINDS`/`SILENCER_KINDS`, а поверхность класса есть «производные
        от объявления, которое ещё никто не читает». Причина проверена
        дифференциально (поле `проверка` базы), а не выведена из формы.
        """
        prior, mine = self.PRIOR["предмет"], self.BASE["предмет"]
        left = len(self.SHIFT["вышли_из_поверхности"])
        closed = self.BASE["закрытые"]
        by_outcome: Dict[str, int] = {}
        for row in closed:
            by_outcome[row["исход"]] = by_outcome.get(row["исход"], 0) + 1
        self.assertEqual(prior["unmeasured"] - len(closed) - left,
                         mine["unmeasured"])
        for outcome in ("silenced", "loud"):
            self.assertEqual(prior[outcome] + by_outcome.get(outcome, 0),
                             mine[outcome], outcome)
        self.assertEqual(sum(mine.values()), self.BASE["вход"]["loud"],
                         "предмет обязан исчерпывать вход")
        self.assertEqual(sum(prior.values()),
                         self.BASE["замер_до_правки"]["вход"]["loud"],
                         "вход ДО обязан исчерпываться предметом ADR-951")
        self.assertEqual(self.BASE["замер_до_правки"]["вход"]["loud"] - left,
                         self.BASE["вход"]["loud"],
                         "вход сдвинулся РОВНО на вышедшие из поверхности")

    def test_the_measurement_before_the_change_REPRODUCES_ADR_951(self) -> None:
        """Сравнивать можно только со СВОИМ замером того же прибора.

        Не воспроизведи замер на чистом `origin/main` числа ADR-951 — и сверять
        с ними было бы нечего; сказать это обязан тест, а не читатель.
        """
        self.assertEqual(self.PRIOR["предмет"],
                         self.BASE["замер_до_правки"]["предмет"])

    def test_the_cause_of_the_surface_shift_is_measured_DIFFERENTIALLY(self) -> None:
        """«Почему вышли» — вердикт, сменившийся от РОВНО одного звена.

        Совпади оба прогона, утверждение о причине было бы догадкой, а не
        замером, и этот тест обязан это сказать.
        """
        check = self.SHIFT["проверка"]
        with_bat, without = check["с_батареей"], check["без_батареи"]
        self.assertNotEqual(with_bat["вход"], without["вход"],
                            "прогоны СОВПАЛИ — причина не доказана (ADR-943)")
        self.assertEqual(with_bat["вход"], self.BASE["вход"]["loud"])
        self.assertEqual(with_bat["предмет"], self.BASE["предмет"])
        self.assertEqual(
            without["предмет"]["unmeasured"]
            - len(self.SHIFT["вышли_из_поверхности"]) - 1,
            self.BASE["предмет"]["unmeasured"],
            "остаток без батареи обязан отличаться на ЧЕТЫРЕ вышедших и ОДНО "
            "рождённое дельтой чтение")

    def test_the_born_read_of_the_delta_is_named_and_NOT_counted_as_closed(self) -> None:
        """«Прибор — член своего класса» объявлено СТРОКОЙ кода, а не словами."""
        born = self.SHIFT["родился_дельтой"]
        self.assertIn("entries[entry.kind]", born["чтение"])
        source = Path(cs.__file__).read_text(encoding="utf-8")
        self.assertIn("entries[entry.kind] += 1", source,
                      "объявленное чтение в приборе отсутствует")
        self.assertFalse(
            [row for row in self.BASE["остаток"]
             if row["чтение"].startswith("spa_core/tests/_caller_silencer.py")],
            "чтения прибора членами класса больше не являются")
        self.assertFalse(
            [row for row in self.BASE["закрытые"]
             if row["чтение"].startswith("spa_core/tests/_caller_silencer.py")],
            "вышедшее из поверхности закрытым не считается")

    def test_every_read_that_LEFT_the_surface_is_named_by_line(self) -> None:
        """«Четыре вышли» без имён перемерить нечем (урок ADR-913)."""
        for row in self.SHIFT["вышли_из_поверхности"]:
            with self.subTest(read=row["чтение"]):
                rel, _, lineno = row["чтение"].rpartition(":")
                self.assertEqual("spa_core/tests/_caller_silencer.py", rel)
                self.assertIn(row["имя"], ("entries", "kinds"))
                self.assertTrue(int(lineno) > 0)

    def test_the_causes_of_the_remainder_are_NOT_a_partition(self) -> None:
        """Находка цикла: причин БОЛЬШЕ, чем строк, и заказ читал их разбиением."""
        total = sum(self.BASE["причины_остатка"].values())
        self.assertGreater(total, len(self.BASE["остаток"]),
                           "совпади число причин с числом строк — утверждение о "
                           "неразбиении перестало бы быть верным")
        self.assertIn("РАЗБИЕНИЕ", self.BASE["причины_НЕ_являются_разбиением"])
        counted: Dict[str, int] = {}
        for row in self.BASE["остаток"]:
            for cause in row["причины"]:
                counted[cause] = counted.get(cause, 0) + 1
        self.assertEqual(self.BASE["причины_остатка"], counted,
                         "сводка причин обязана быть ВЫВЕДЕНА из имён")
        before = self.BASE["замер_до_правки"]
        self.assertEqual(before["сумма_причин"],
                         sum(before["по_причинам"].values()))
        self.assertGreater(before["сумма_причин"],
                           before["предмет"]["unmeasured"],
                           "и ДО правки причин было больше, чем строк")

    def test_the_remainder_is_declared_by_cause_and_sums_up(self) -> None:
        """Остаток назван ПРИЧИНАМИ: «12» без причин перемерить нечем."""
        self.assertEqual(len(self.BASE["остаток"]),
                         self.BASE["предмет"]["unmeasured"])

    def test_the_command_to_remeasure_is_named(self) -> None:
        self.assertIn("caller_reads", self.BASE["_перемерить"])
        self.assertIn("fate_of_handler", self.BASE["_перемерить"])

    def test_a_sample_of_the_declaration_agrees_with_the_live_instrument(self) -> None:
        declared = {row["чтение"]: row for row in self.BASE["закрытые"]}
        checked = 0
        for row in declared.values():
            rel, _, lineno = row["чтение"].rpartition(":")
            got = cs.loudness_through_callers(rel, row["функция"], False,
                                              tree_facts(), fates.fate_of_handler)
            self.assertEqual(row["исход"], got["loudness"],
                             f"{row['чтение']}: {got['why']}")
            checked += 1
        self.assertGreater(checked, 0, "выборка ПУСТА — тест не доказывает ничего")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
