#!/usr/bin/env python3
"""Контроль прибора ADR-950 — громкость чтения ЗА границей своей функции.

# LLM_FORBIDDEN

Каждая сцена отличается от соседней РОВНО одним звеном, и вердикты
ПРОТИВОПОЛОЖНЫЕ: прибор, отвечающий одно и то же всегда, дал бы те же числа, и
отличить его от замера было бы нечем (дословный урок `pyflakes`).

**Два контроля стоя́т на НАСТОЯЩИХ членах дерева, а не только на сценах** — ровно
то, чего не хватило ADR-949 и чего потребовал заказ G938 п. 2. Сцены показывают,
что дверь СРАБАТЫВАЕТ; члены дерева показывают, что она срабатывает на том, что в
дереве действительно есть.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

from spa_core.tests import _caller_silencer as cs
from spa_core.tests import _empty_collection_harm as harm

_TREE_FACTS: Optional[Dict[str, cs.ModuleFacts]] = None


def tree_facts() -> Dict[str, cs.ModuleFacts]:
    """Факты НАСТОЯЩЕГО дерева — один раз на прогон (разбор 5.5 тыс. файлов)."""
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

    def ask(self, rel: str, fname: str, is_method: bool = False) -> dict:
        facts, unread = cs.load_surface(self.root)
        assert not unread, f"сцена не прочитана: {unread}"
        return cs.loudness_through_callers(rel, fname, is_method, facts)

    def close(self) -> None:
        self._tmp.cleanup()


class CallerSilencerScenes(unittest.TestCase):
    """Сцены: каждая пара различается РОВНО одним звеном."""

    def setUp(self) -> None:
        self.scene = Scene()
        self.addCleanup(self.scene.close)

    # ─────────────────── глушитель у звавшего ───────────────────

    def test_call_in_try_body_is_silenced(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "D = {}\n"
            "def f():\n"
            "    d = {k: 1 for k in D}\n"
            "    return d['x']\n"
            "try:\n"
            "    f()\n"
            "except KeyError:\n"
            "    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("try", got["silencer"])

    def test_the_same_call_without_the_try_is_loud(self) -> None:
        """Отличие от соседа РОВНО одно — снят `try`. Вердикт ПРОТИВОПОЛОЖНЫЙ."""
        rel = self.scene.write("spa_core/a.py", (
            "D = {}\n"
            "def f():\n"
            "    d = {k: 1 for k in D}\n"
            "    return d['x']\n"
            "f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["module_level"])

    def test_handler_of_a_foreign_kind_does_not_silence(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "def f():\n    return {}['x']\n"
            "try:\n    f()\nexcept ValueError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])

    def test_handler_kind_built_by_an_expression_is_unmeasured(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "ERRS = (KeyError,)\n"
            "def f():\n    return {}['x']\n"
            "try:\n    f()\nexcept ERRS[0]:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("НЕ РАЗОБРАН", got["why"])

    def test_a_call_in_the_else_branch_is_not_in_the_try_body(self) -> None:
        """`else` у `try` телом НЕ является: исключение из него наружу уходит,
        обработчики его не кроют (то же правило, что у ADR-949 внутри области)."""
        rel = self.scene.write("spa_core/a.py", (
            "def f():\n    return {}['x']\n"
            "try:\n    pass\nexcept KeyError:\n    pass\nelse:\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])

    @unittest.skipUnless(hasattr(ast, "TryStar"), "`except*` требует Python 3.11+")
    def test_except_star_silences_too(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "def f():\n    return {}['x']\n"
            "try:\n    f()\nexcept* KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])

    # ─────────────────── менеджер контекста ───────────────────

    def test_with_raises_swallows_and_is_a_silencer(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "import pytest\n"
            "def f():\n    return {}['x']\n"
            "with pytest.raises(KeyError):\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("with", got["silencer"])

    def test_with_suppress_swallows_too(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "from contextlib import suppress\n"
            "def f():\n    return {}['x']\n"
            "with suppress(KeyError):\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertEqual("with", got["silencer"])

    def test_with_raises_of_a_foreign_kind_does_not_silence(self) -> None:
        """Отличие от соседа РОВНО одно — род в менеджере. Вердикт обратный."""
        rel = self.scene.write("spa_core/a.py", (
            "import pytest\n"
            "def f():\n    return {}['x']\n"
            "with pytest.raises(ValueError):\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])

    def test_with_manager_without_a_named_kind_is_unmeasured(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "import pytest\n"
            "def f():\n    return {}['x']\n"
            "with pytest.raises():\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])

    # ─────────────────── привязка к ОБЪЯВЛЯЮЩЕМУ модулю ───────────────────

    def test_a_namesake_in_another_module_is_not_merged(self) -> None:
        """Урок ADR-941/942: голое имя сливает незнакомцев. Глушитель ЧУЖОЙ `f`
        не имеет права заглушить НАШУ."""
        rel = self.scene.write("spa_core/a.py", (
            "def f():\n    return {}['x']\n"))
        self.scene.write("spa_core/b.py", (
            "def f():\n    return 1\n"
            "try:\n    f()\nexcept KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertNotEqual("silenced", got["loudness"], got["why"])
        self.assertIn("не зовёт ни одна строка", got["why"])

    def test_an_imported_name_binds_across_modules(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/b.py", (
            "from spa_core.a import f\n"
            "try:\n    f()\nexcept KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])

    def test_a_module_alias_attribute_binds_across_modules(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/b.py", (
            "from spa_core import a as mod\n"
            "try:\n    mod.f()\nexcept KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])

    def test_an_alias_to_a_different_module_does_not_bind(self) -> None:
        """Отличие от соседа РОВНО одно — псевдоним ведёт в ДРУГОЙ модуль."""
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/c.py", "def f():\n    return 1\n")
        self.scene.write("spa_core/b.py", (
            "from spa_core import c as mod\n"
            "try:\n    mod.f()\nexcept KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertNotEqual("silenced", got["loudness"], got["why"])

    def test_a_locally_bound_namesake_is_unmeasured(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/b.py", (
            "def g(f):\n"
            "    try:\n        f()\n    except KeyError:\n        pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("не привязанных", got["why"])

    def test_a_name_fetched_by_string_is_unmeasured(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/b.py", (
            "from spa_core import a as mod\n"
            "getattr(mod, 'f')()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("СТРОКОЙ", got["why"])

    # ─────────────────── полнота замыкания ───────────────────

    def test_a_decorated_caller_makes_the_closure_unenumerable(self) -> None:
        """Замер 08.11: `@router.get` назначает звавшим КАРКАС, и восемь вызовов
        из тестов полным набором звавших не являются."""
        rel = self.scene.write("spa_core/a.py", (
            "router = object()\n"
            "def f():\n    return {}['x']\n"
            "@router.get('/x')\n"
            "def handler():\n    return f()\n"
            "handler()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("декоратор", got["why"])

    def test_a_transparent_decorator_does_not_block(self) -> None:
        """Отличие от соседа РОВНО одно — декоратор из объявленного перечня."""
        rel = self.scene.write("spa_core/a.py", (
            "import functools\n"
            "def f():\n    return {}['x']\n"
            "@functools.lru_cache\n"
            "def handler():\n    return f()\n"
            "handler()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])

    def test_a_found_silencer_beats_an_incomplete_closure(self) -> None:
        """Положительный контроль НА СВОЙ ЖЕ дефект: первая редакция прибора
        спрашивала декоратор ДО вызовов и понижала НАЙДЕННЫЙ глушитель
        `open_class_counter_census` до `unmeasured`, то есть теряла находку."""
        rel = self.scene.write("spa_core/a.py", (
            "router = object()\n"
            "@router.get('/x')\n"
            "def f():\n    return {}['x']\n"
            "try:\n    f()\nexcept KeyError:\n    pass\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("silenced", got["loudness"], got["why"])

    def test_a_caller_guard_is_unmeasured_not_loud(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "def f(rows):\n    return rows['x']\n"
            "ROWS = {}\n"
            "if ROWS:\n    f(ROWS)\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("охрана у звавшего", got["why"])

    def test_a_pytest_test_is_an_entry_point(self) -> None:
        rel = self.scene.write("spa_core/a.py", "def f():\n    return {}['x']\n")
        self.scene.write("spa_core/tests/test_s.py", (
            "from spa_core.a import f\n"
            "def test_s():\n    f()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("loud", got["loudness"], got["why"])
        self.assertEqual(1, got["entry"]["pytest_test"])

    def test_a_closure_longer_than_the_limit_is_unmeasured(self) -> None:
        body = ["def f():\n    return {}['x']\n"]
        body.append("def w0():\n    return f()\n")
        for i in range(1, cs.CALLER_HOPS + 2):
            body.append(f"def w{i}():\n    return w{i - 1}()\n")
        body.append(f"w{cs.CALLER_HOPS + 1}()\n")
        rel = self.scene.write("spa_core/a.py", "".join(body))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("длиннее предела", got["why"])

    def test_a_closure_that_only_cycles_is_unmeasured_not_loud(self) -> None:
        """Замыкание, не дошедшее ни до одной точки входа, перечислением не
        является: `loud` здесь был бы ошибкой в ОПАСНУЮ сторону."""
        rel = self.scene.write("spa_core/a.py", (
            "def f():\n    return {}['x']\n"
            "def g():\n    return f() or h()\n"
            "def h():\n    return g()\n"))
        got = self.scene.ask(rel, "f")
        self.assertEqual("unmeasured", got["loudness"], got["why"])
        self.assertIn("ЦИКЛ", got["why"])

    def test_a_method_is_unmeasured_because_attributes_do_not_resolve(self) -> None:
        rel = self.scene.write("spa_core/a.py", (
            "class C:\n"
            "    def f(self):\n        return {}['x']\n"
            "def use(obj):\n"
            "    try:\n        obj.f()\n    except KeyError:\n        pass\n"))
        got = self.scene.ask(rel, "f", is_method=True)
        self.assertEqual("unmeasured", got["loudness"], got["why"])


class ControlOnRealTreeMembers(unittest.TestCase):
    """Контроль на НАСТОЯЩИХ членах дерева — требование заказа G938 п. 2."""

    def test_the_known_member_cross_is_silenced_by_its_own_module(self) -> None:
        """`reachability_of_the_rest._cross` несёт громкое `cross[…]`, и её зовут
        из тела `try: … except Exception` — код говорит это вслух сам."""
        got = cs.loudness_through_callers(
            "spa_core/monitoring/reachability_of_the_rest.py", "_cross",
            False, tree_facts())
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertIn("reachability_of_the_rest.py", got["why"])

    def test_the_known_member_scorable_days_is_silenced_by_measure(self) -> None:
        got = cs.loudness_through_callers(
            "spa_core/monitoring/criterion_sign_price.py", "scorable_days",
            False, tree_facts())
        self.assertEqual("silenced", got["loudness"], got["why"])
        self.assertIn("criterion_sign_price.py", got["why"])

    def test_a_route_handler_of_the_tree_is_unmeasured_not_loud(self) -> None:
        got = cs.loudness_through_callers(
            "spa_core/academy/api/routes/auth.py", "me", False, tree_facts())
        self.assertEqual("unmeasured", got["loudness"], got["why"])


class DeclarationCarriesItsOwnContract(unittest.TestCase):
    """Объявления прибора обязаны СОВПАДАТЬ с тем, что он умеет произвести."""

    SOURCE = Path(cs.__file__).read_text(encoding="utf-8")

    def test_every_produced_outcome_is_a_declared_outcome(self) -> None:
        produced = {node.value for node in ast.walk(ast.parse(self.SOURCE))
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)}
        for outcome in cs.OUTCOMES:
            self.assertIn(outcome, produced,
                          f"объявленный исход `{outcome}` прибор не произносит")

    def test_the_input_comes_through_the_single_door(self) -> None:
        """Своей копии замера ADR-949 здесь быть не должно: разойдись она с
        `subscript_reads`, и прибор отвечал бы про ДРУГОЕ население."""
        tree = ast.parse(self.SOURCE)
        doors = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "subscript_reads"]
        self.assertEqual(1, len(doors), "дверь замера обязана быть РОВНО одна")
        own = [node for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "census"]
        self.assertEqual([], own, "своя копия переписи — второе место для числа")

    def test_the_reader_surface_is_the_censuss_own_door(self) -> None:
        self.assertIn("READER_ROOTS", self.SOURCE)
        self.assertNotIn('rglob("*.py")', self.SOURCE,
                         "свой обход поверхности разойдётся с переписью")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
