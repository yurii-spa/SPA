#!/usr/bin/env python3
"""Контроль двери «один хоп через ПАРАМЕТР» у переписи набор-зависимости.

Заказ G1101 п. 2 (направление 3) приказа владельца «Portfolio CIO», карточка
`inbox-naselenie-mer-bez-voprosa-pri-dostavke-2`, решение ADR-1129.

ЗАМЕР, РАДИ КОТОРОГО ДВЕРЬ ПОСТАВЛЕНА (28.11, цикл #1275)
─────────────────────────────────────────────────────────────────────────────
Третий исход переписи `scripts/delivery_question_census.py` — 106 файлов «путь
сторожа прибором НЕ РАЗОБРАН», и верхний край вилки предмета (265 … 371) держали
ИМЕННО ОНИ: неразобранный путь нулём не считается (инв. #17). Причина у 52 из
106 файлов одна — «имя `X` в модуле не привязано», а 78 её зовов разложились:

    64  имя есть ПАРАМЕТР объемлющей функции
     8  распаковка кортежа
     4  цель цикла `for`
     2  не найдено нигде

Значение параметра назначает не модуль, а ВЫЗЫВАЮЩИЙ либо фикстура pytest того
же имени — отсюда дверь. После неё: НЕ РАЗОБРАНО 106 → 81, предмет 265 → 262,
верхний край вилки 371 → 343, а охват прибора не тронут ни строкой (сужение
ОХВАТА вместо ОТВЕТА карточка запрещает прямым текстом).

КАЖДЫЙ ТЕСТ ЗДЕСЬ — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ, И ОБЕ СТОРОНЫ НУЖНЫ
─────────────────────────────────────────────────────────────────────────────
Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»). Дверь, у которой
проверено только «разбирает», молча разрешила бы УГАДЫВАНИЕ: поэтому у каждой
сцены есть обратная половина, где источники не согласны и дверь ОТКАЗЫВАЕТ с
названной причиной.

Отдельно закреплены три находки, измеренные на самой двери:

* **Согласие мерится ВЕРДИКТОМ, а не текстом причины.** Две одноразовые сцены
  объясняются разными словами (`tmp_path` против `TemporaryDirectory`), и ключ
  по тексту объявил бы их расхождением — то есть отказал бы там, где оба
  источника говорят ОДНО И ТО ЖЕ.
* **Параметр ЧУЖОЙ функции привязкой не является.** Это та же дисциплина, что
  «контейнер привязкой не является» в § «Время в тестах»: считать «в модуле
  есть функция с таким аргументом» происхождением значило бы оправдать догадку.
* **Хоп ОДИН, и граница ВИДНА.** Аргумент зова, сам являющийся параметром, даёт
  `unresolved` со СВОЕЙ причиной, поэтому население за границей одного хопа
  печатается, а не выдаётся за ноль.

Время, номера процессов и git-окружение здесь не спрашиваются ни одной дверью:
прибор статический, сцены строятся в одноразовых каталогах. Литеральных дат в
файле нет вовсе — значит и бомбы календаря нет по построению.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CENSUS = REPO / "scripts" / "derived_artifact_census.py"

#: Шапка сцены: `REPO` разбирается прибором до корня репозитория, поэтому
#: `REPO / "scripts"` — проверяемый ответ, а не литерал, зависящий от cwd.
HEAD = "import pathlib\nREPO = pathlib.Path(__file__).resolve().parents[2]\n"


def _load():
    """Прибор ввозится ПО ПУТИ из СВОЕГО дерева, а не по имени.

    Ввоз по имени удался бы из `sys.modules`/`sys.path` и мерил бы ЧУЖОЕ
    дерево, не сказав об этом ни строкой — дословно класс ADR-796 внутри
    процесса (ADR-1127, п. 4б заказа G1101).
    """
    spec = importlib.util.spec_from_file_location("spa_param_hop_test", CENSUS)
    assert spec and spec.loader, f"прибор не ввезён из {CENSUS}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spa_param_hop_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _calls(mod, name: str, body: str):
    """Сцена в ОДНОРАЗОВОМ дереве → перечисляющие зовы настоящего прибора."""
    with tempfile.TemporaryDirectory(prefix="param_hop_") as d:
        root = pathlib.Path(d)
        tests = root / "spa_core" / "tests"
        tests.mkdir(parents=True)
        (tests / f"test_{name}.py").write_text(HEAD + body, encoding="utf-8")
        surface = mod.measure_surface(root)
    return [c for entry in surface.entries for c in entry.calls]


def _only(testcase, mod, name: str, body: str):
    calls = _calls(mod, name, body)
    testcase.assertEqual(len(calls), 1,
                         f"сцена обязана дать РОВНО один зов, дала {len(calls)}: "
                         f"{[(c.kind, c.reason) for c in calls]}")
    return calls[0]


class TheHopAnswersWhenTheSourceIsSingle(unittest.TestCase):
    """Параметр разобран — и ярлык несёт НАЗВАННЫЙ каталог, а не «что-то»."""

    def test_the_only_caller_names_a_repository_directory(self):
        mod = _load()
        call = _only(self, mod, "caller_repo_dir",
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def test_x():\n"
                     "    assert _dirs(REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_the_only_caller_passes_a_disposable_scene(self):
        mod = _load()
        call = _only(self, mod, "caller_sandbox",
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def test_x(tmp_path):\n"
                     "    assert _dirs(tmp_path) is not None\n")
        self.assertEqual(call.kind, mod.SANDBOX, call.reason)
        self.assertIn("одноразовую сцену", call.reason)

    def test_an_in_module_fixture_of_the_same_name_is_a_source(self):
        mod = _load()
        call = _only(self, mod, "fixture_same_name",
                     "import pytest\n"
                     "@pytest.fixture\n"
                     "def where():\n"
                     "    return REPO / 'scripts'\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_the_declared_default_is_a_source(self):
        mod = _load()
        call = _only(self, mod, "default_is_a_source",
                     "def _dirs(where=REPO / 'scripts'):\n"
                     "    return list(where.iterdir())\n"
                     "def test_x():\n"
                     "    assert _dirs() is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_a_bound_method_shifts_the_positional_index(self):
        """`self._dirs(x)` съедает первый позиционный — смещение ИЗМЕРЕНО.

        Без смещения дверь взяла бы аргументом `self` и ответила бы о нём, то
        есть дала бы НЕВЕРНЫЙ каталог вместо отказа — ошибка в опасную сторону.
        """
        mod = _load()
        call = _only(self, mod, "method_offset",
                     "import unittest\n"
                     "class K(unittest.TestCase):\n"
                     "    def _dirs(self, where):\n"
                     "        return list(where.iterdir())\n"
                     "    def test_x(self):\n"
                     "        assert self._dirs(REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)


class TheHopRefusesInsteadOfGuessing(unittest.TestCase):
    """Обратная половина КАЖДОЙ сцены выше: нет согласия ⇒ отказ с причиной."""

    def test_two_callers_naming_different_directories_refuse(self):
        mod = _load()
        call = _only(self, mod, "callers_disagree",
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def test_a():\n"
                     "    assert _dirs(REPO / 'scripts') is not None\n"
                     "def test_b():\n"
                     "    assert _dirs(REPO / 'docs') is not None\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("РАСХОДЯТСЯ", call.reason)
        self.assertIn("scripts", call.reason)
        self.assertIn("docs", call.reason)

    def test_two_fixtures_of_one_name_refuse(self):
        mod = _load()
        call = _only(self, mod, "two_fixtures_one_name",
                     "import pytest\n"
                     "@pytest.fixture\n"
                     "def where():\n"
                     "    return REPO / 'scripts'\n"
                     "@pytest.fixture\n"
                     "def where():\n"
                     "    return REPO / 'docs'\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("больше одной", call.reason)

    def test_two_functions_of_one_name_refuse(self):
        """Чьи зовы подставляют параметр — вопрос, а не догадка."""
        mod = _load()
        call = _only(self, mod, "two_funcs_one_name",
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def _dirs(where):\n"
                     "    return []\n"
                     "def test_x():\n"
                     "    assert _dirs(REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("не единственно", call.reason)
        self.assertIn("НЕ ИЗМЕРЕНО", call.reason)

    def test_a_fixture_decorator_is_asked_not_the_name(self):
        """Функция без декоратора фикстурой НЕ является.

        «Похоже на фикстуру по имени» — та же мерка по соглашению об имени,
        которую положительный контроль реестра опроверг у переписи дверей
        доставки (ADR-1127, п. 4а): там гейт звался `enforce_adr_numbers`,
        а мерка брала один префикс `enforce_delivery_*`.
        """
        mod = _load()
        call = _only(self, mod, "fixture_needs_a_decorator",
                     "def where():\n"
                     "    return REPO / 'scripts'\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("зовов `test_x`", call.reason)


class TheThreeFindingsMeasuredOnTheDoorItself(unittest.TestCase):
    """Находки, каждая из которых сначала была дефектом ЭТОЙ двери."""

    def test_agreement_is_keyed_by_the_verdict_not_by_the_wording(self):
        """Две сцены разными словами — ОДИН вердикт, а не расхождение."""
        mod = _load()
        call = _only(self, mod, "two_scenes_one_verdict",
                     "import tempfile\n"
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def test_a(tmp_path):\n"
                     "    assert _dirs(tmp_path) is not None\n"
                     "def test_b():\n"
                     "    with tempfile.TemporaryDirectory() as td:\n"
                     "        assert _dirs(pathlib.Path(td)) is not None\n")
        self.assertEqual(call.kind, mod.SANDBOX, call.reason)
        self.assertNotIn("РАСХОДЯТСЯ", call.reason)

    def test_a_parameter_of_another_function_is_not_a_binding(self):
        """Имя — параметр ЧУЖОЙ функции, объемлющая его не объявляет."""
        mod = _load()
        call = _only(self, mod, "param_of_another_function",
                     "def _other(where):\n"
                     "    return where\n"
                     "def _dirs():\n"
                     "    return list(where.iterdir())\n"
                     "def test_x():\n"
                     "    assert _other(REPO / 'scripts') is not None\n"
                     "    assert _dirs() is not None\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("в модуле не привязано", call.reason)

    def test_the_second_hop_is_not_made_and_says_so(self):
        """Граница одного хопа ВИДНА: причина называет её словами."""
        mod = _load()
        call = _only(self, mod, "second_hop_not_made",
                     "def _dirs(where):\n"
                     "    return list(where.iterdir())\n"
                     "def _outer(given):\n"
                     "    return _dirs(given)\n"
                     "def test_x():\n"
                     "    assert _outer(REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("второй хоп не делается", call.reason)


class TheFixtureIsASourceONLYWherePytestInjects(unittest.TestCase):
    """Применимость источника — ВОПРОС, а не старшинство.

    Сцена `inner_scope_wins` нашла это дефектом двери 28.11: фикстура
    спрашивалась и там, где параметр подставляют ЯВНЫЕ зовы, поэтому замыкание
    `def _dirs(where)` внутри `def test_x(where)` получало ДВА источника и
    уходило в «РАСХОДЯТСЯ» — дверь отказывала там, где ответ был один. pytest
    внедряет фикстуру в параметр, которого зов не подставил; у помощника,
    зовомого руками, фикстура источником не является ВОВСЕ.
    """

    def test_the_innermost_owner_wins_over_an_outer_same_name(self):
        mod = _load()
        call = _only(self, mod, "inner_scope_wins",
                     "import pytest\n"
                     "@pytest.fixture\n"
                     "def where():\n"
                     "    return REPO / 'docs'\n"
                     "def test_x(where):\n"
                     "    def _dirs(where):\n"
                     "        return list(where.iterdir())\n"
                     "    assert _dirs(REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_a_keyword_argument_is_matched_by_its_name(self):
        """Декой-ключевое слово стои́т ПОСЛЕ верного — и это измеренная находка.

        Мутация «брать ЛЮБОЕ ключевое слово» перезаписывает найденное
        значение, поэтому при декое ПЕРЕД верным аргументом последним
        остаётся верный и мутация ВЫЖИВАЕТ (замер 28.11, первый прогон).
        Порядок в сцене — несущая её часть, а не оформление.
        """
        mod = _load()
        call = _only(self, mod, "keyword_is_matched_by_name",
                     "def _dirs(where, other=None):\n"
                     "    return list(where.iterdir())\n"
                     "def test_x():\n"
                     "    assert _dirs(where=REPO / 'scripts',\n"
                     "                 other=REPO / 'docs') is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_a_fixture_of_two_different_returns_refuses(self):
        mod = _load()
        call = _only(self, mod, "fixture_with_two_returns",
                     "import pytest\n"
                     "@pytest.fixture\n"
                     "def where(request):\n"
                     "    if request.param:\n"
                     "        return REPO / 'scripts'\n"
                     "    return REPO / 'docs'\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("возвращает 2 разных", call.reason)

    def test_a_fixture_that_returns_nothing_refuses(self):
        mod = _load()
        call = _only(self, mod, "fixture_returns_nothing",
                     "import pytest\n"
                     "@pytest.fixture\n"
                     "def where():\n"
                     "    pass\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertIn("ничего не возвращает", call.reason)


class TheThreeSceneHolesFoundByTheMutationRun(unittest.TestCase):
    """Сцены, которых НЕ ХВАТАЛО: каждую назвала выжившая мутация.

    Девятый цикл подряд подтверждал: выжившая мутация — чаще дефект СЦЕНЫ, чем
    кода. Первый прогон этой двери дал 15 из 20, и из пяти выживших ТРИ были
    дырами сцен (ни одна не подавала keyword-only параметр, ни одна не ставила
    декой ПОСЛЕ верного аргумента, ни одна не вешала НЕ-фикстурный декоратор),
    одна требовала сцены на объявленное «ничего», и РОВНО ОДНА оказалась
    эквивалентной — это записано в ADR-1129, а не замазано.
    """

    def test_a_keyword_only_parameter_is_a_parameter_too(self):
        mod = _load()
        call = _only(self, mod, "kwonly_is_a_parameter_too",
                     "def _dirs(*, where):\n"
                     "    return list(where.iterdir())\n"
                     "def test_x():\n"
                     "    assert _dirs(where=REPO / 'scripts') is not None\n")
        self.assertEqual(call.kind, mod.SOURCE_DIR, call.reason)
        self.assertEqual(call.rel_dir, "scripts", call.reason)

    def test_a_non_fixture_decorator_is_not_a_fixture(self):
        """Декоратор СПРАШИВАЕТСЯ по имени `fixture`, а не по наличию."""
        mod = _load()
        call = _only(self, mod, "a_non_fixture_decorator_is_not_a_fixture",
                     "import functools\n"
                     "@functools.lru_cache\n"
                     "def where():\n"
                     "    return REPO / 'docs'\n"
                     "def test_x(where):\n"
                     "    assert list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertNotIn("docs", call.reason)

    def test_a_declared_none_default_is_not_a_value(self):
        """`where=None` — отсутствие значения, и причиной оно не становится."""
        mod = _load()
        call = _only(self, mod, "a_none_default_is_not_a_value",
                     "def _dirs(where=None):\n"
                     "    return list(where.iterdir())\n")
        self.assertEqual(call.kind, mod.UNRESOLVED, call.reason)
        self.assertNotIn("умолчание", call.reason)


class TheHopIsAskedByTheCallNodeAndNotByDefault(unittest.TestCase):
    """«Параметр разобран» и «параметр НЕ СПРОШЕН» обязаны быть различимы."""

    @staticmethod
    def _resolver_and_call(mod):
        src = (HEAD
               + "def _dirs(where):\n"
                 "    return list(where.iterdir())\n"
                 "def test_x():\n"
                 "    assert _dirs(REPO / 'scripts') is not None\n")
        tree = ast.parse(src)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "iterdir")
        resolver = mod._PathResolver(
            tree, pathlib.PurePosixPath("spa_core/tests/test_x.py"))
        return resolver, node

    def test_without_the_call_node_there_is_no_hop(self):
        mod = _load()
        resolver, node = self._resolver_and_call(mod)
        kind, rel, reason = resolver.resolve(node.func.value)
        self.assertEqual(kind, mod.UNRESOLVED, reason)
        self.assertIsNone(rel)

    def test_with_the_call_node_the_hop_answers(self):
        mod = _load()
        resolver, node = self._resolver_and_call(mod)
        kind, rel, reason = resolver.resolve(node.func.value, at=node)
        self.assertEqual(kind, mod.SOURCE_DIR, reason)
        self.assertEqual(rel, "scripts", reason)


class TheDoorDidNotLoseAKnownMember(unittest.TestCase):
    """Форма, потерявшая известного члена, ОПРОВЕРГНУТА (урок ADR-1074).

    Дверь СНИМАЕТ ложные срабатывания — значит обязана быть проверена и с
    обратной стороны: не снесла ли она вместе с ними настоящую поверхность.
    Полнота самого перечня спрашивается у РЕЕСТРА РЕШЕНИЙ (ADR-1113), поэтому
    он читается из прибора, а не набирается здесь второй копией.
    """

    def test_every_known_member_stays_in_the_surface(self):
        mod = _load()
        surface = mod.measure_surface(REPO)
        kinds = {e.path: e.kind for e in surface.entries}
        missing = {m: kinds.get(m) for m in mod.KNOWN_MEMBERS
                   if kinds.get(m) != mod.SOURCE_DIR}
        self.assertEqual(missing, {},
                         "дверь вынесла известного члена из поверхности — "
                         "форма ОПРОВЕРГНУТА, а не улучшена")

    def test_the_prober_scope_is_untouched_by_the_door(self):
        """Сужение ОХВАТА вместо ОТВЕТА карточка запрещает прямым текстом."""
        mod = _load()
        surface = mod.measure_surface(REPO)
        self.assertGreater(surface.tests_total, 2000,
                           "охват прибора схлопнулся — число предмета стало бы "
                           "ответом о мерке, а не о дереве")


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
