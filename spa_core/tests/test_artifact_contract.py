"""Тесты объявления контракта агента и сверки его с кодом (ADR-154/158).

Каждый тест воспроизводит дефект, ДОПУЩЕННЫЙ при постройке 28.08 и пойманный
замером, а не придуманный ради покрытия (`.claude/rules/deployment.md`):

  1. Поиск по вхождению строки не отличал запись от чтения — `KANBAN.json`
     объявлялся продуктом агента, который его ЧИТАЕТ.
  2. Одна таблица имён на модуль склеивала области видимости: имя `path` из
     двух функций давало `agent_passports` ложную запись в манифест.
  3. Путь почти всегда собирается через локальную переменную, а не литералом.
  4. `f"{agent_key}.json"` оставляет в коде константу `".json"`; без основы
     она становилась «артефактом» и давала 11 ложных противоречий.
  5. Замыкание импортов для вердикта не годится: общая библиотека алертов
     пишет `push_state.json`, и его получали 17 агентов из 19.
  6. `PRODUCES` в ПРОЗЕ докстринга принималось за объявление.

Только stdlib, оффлайн, реальное дерево не изменяется.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_contract as ac
from spa_core.monitoring.artifact_io_scan import READ, WRITE, scan_source


class TestWriteIsNotRead(unittest.TestCase):
    def test_read_is_not_reported_as_write(self):
        """Авария 1: `KANBAN.json` числился продуктом своего ЧИТАТЕЛЯ."""
        got = scan_source('import json\nd = json.load(open("KANBAN.json"))\n')
        self.assertEqual(got.get("KANBAN.json"), {READ})

    def test_write_is_reported_as_write(self):
        """Обратный контроль."""
        got = scan_source('from spa_core.utils.atomic import atomic_save\n'
                          'atomic_save(d, "data/x.json")\n')
        self.assertEqual(got.get("data/x.json"), {WRITE})

    def test_open_for_writing_is_a_write(self):
        got = scan_source('f = open("data/y.json", "w")\n')
        self.assertEqual(got.get("data/y.json"), {WRITE})


class TestNameResolution(unittest.TestCase):
    def test_path_built_through_a_local_variable_is_found(self):
        """Авария 3: реальные модули пишут не литералом, а собранной переменной."""
        src = ('ARTIFACT_REL = "agent_passports.json"\n'
               'def write_artifact(ddir):\n'
               '    path = ddir / ARTIFACT_REL\n'
               '    atomic_save({}, str(path))\n')
        self.assertEqual(scan_source(src).get("agent_passports.json"), {WRITE})

    def test_same_name_in_two_functions_is_not_conflated(self):
        """Авария 2, самая дорогая: ложный ПИСАТЕЛЬ получает чужое расписание,
        а значит чужой срок годности."""
        src = ('MANIFEST = "architecture/manifest.json"\n'
               'ART = "agent_passports.json"\n'
               'def audit():\n'
               '    path = MANIFEST\n'
               '    return json.loads(open(path).read())\n'
               'def write_artifact(ddir):\n'
               '    path = ddir / ART\n'
               '    atomic_save({}, str(path))\n')
        got = scan_source(src)
        self.assertEqual(got.get("agent_passports.json"), {WRITE})
        self.assertNotIn(WRITE, got.get("architecture/manifest.json", set()),
                         "манифест только читается — запись это склейка областей")

    def test_bare_suffix_from_an_fstring_is_not_an_artifact(self):
        """Авария 4: `f\"{agent_key}.json\"` оставляет константу `\".json\"`."""
        src = ('def emit(self):\n'
               '    atomic_save({}, str(self.data_dir / f"{self.agent_key}.json"))\n')
        self.assertNotIn(".json", scan_source(src))


class TestDeclaration(unittest.TestCase):
    def _mod(self, td, src):
        p = Path(td) / "m.py"
        p.write_text(src, encoding="utf-8")
        return p

    def test_declaration_is_read(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._mod(td, 'PRODUCES = (\n    "data/a.json",\n    "data/b.json",\n)\n')
            self.assertEqual(ac.declared_produces(p), ("data/a.json", "data/b.json"))

    def test_the_word_in_prose_is_not_a_declaration(self):
        """Авария 6: `market_regime.py` пишет «The desk already PRODUCES two
        regime signals» — проверка подстрокой сочла это объявлением и пропустила
        агента. Сверять структурой, а не текстом."""
        with tempfile.TemporaryDirectory() as td:
            p = self._mod(td, '"""The desk already PRODUCES two regime signals."""\nx = 1\n')
            self.assertIsNone(ac.declared_produces(p))

    def test_absent_and_empty_are_different_answers(self):
        """`PRODUCES = ()` — автор ОТВЕТИЛ «ничего»; отсутствие — никто не
        высказывался. Одно закрывает работу, другое её заводит."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ac.declared_produces(self._mod(td, "PRODUCES = ()\n")), ())
            self.assertIsNone(ac.declared_produces(self._mod(td, "x = 1\n")))


class TestThreeOutcomes(unittest.TestCase):
    """Двух исходов НЕ хватает: семья `io_*` пишет имя, собранное на лету, и
    при двух исходах вечно краснела бы как «объявил, но не пишет»."""

    def _agent(self, td, src):
        root = Path(td)
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "a.py").write_text(src, encoding="utf-8")
        return root

    def test_confirmed_when_declaration_matches_the_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'atomic_save(d, "data/x.json")\n')
            self.assertEqual(ac.check_agent("a", "pkg.a", root)["verdict"], ac.CONFIRMED)

    def test_unmeasured_when_the_name_is_built_at_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'def emit(self):\n'
                                   '    atomic_save(d, str(self.dir / f"{self.key}.json"))\n')
            self.assertEqual(ac.check_agent("a", "pkg.a", root)["verdict"], ac.UNMEASURED)

    def test_contradiction_when_the_module_writes_something_undeclared(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'atomic_save(d, "data/surprise.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONTRADICTION)
            self.assertIn("surprise.json", r["undeclared_writes"])

    def test_explicit_empty_is_an_ANSWER_not_unmeasured(self):
        """`PRODUCES = ()` — автор сказал «ничего». Замер 28.08: без отдельного исхода
        шесть агентов с ясным ответом попадали в `unmeasured`, то есть ясный ответ
        выглядел как невыясненный."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, "PRODUCES = ()\n")
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.DECLARED_NONE)
            self.assertNotEqual(r["verdict"], ac.UNMEASURED)

    def test_undeclared_is_its_own_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'atomic_save(d, "data/x.json")\n')
            self.assertEqual(ac.check_agent("a", "pkg.a", root)["verdict"], ac.UNDECLARED)


class TestInternalWritesIsSaidAloudNotHidden(unittest.TestCase):
    """`INTERNAL_WRITES` — третий ответ на «модуль пишет файл, которого нет в контракте».

    Замер 29.08 нашёл два таких: `findings_bridge` пишет собственную память между
    прогонами, а `cycle_runner` — разовую копию кривой при переходе с демо на
    настоящий трек, которой в проде НЕТ ВОВСЕ. Объявить их продуктами значило бы
    завести вечную находку о протухании файла, которого никто не ждёт; промолчать —
    оставить вечное противоречие. Верный ответ третий: сказать, что запись есть и
    продуктом не является.

    Опасность приёма очевидна — это потенциальная ГЛУШИЛКА. Поэтому здесь
    проверяется не только что она работает, но и что она НЕ всесильна.
    """

    def _agent(self, td, src):
        root = Path(td)
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "a.py").write_text(src, encoding="utf-8")
        return root

    def test_declared_internal_write_is_not_a_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'INTERNAL_WRITES = ("data/state.json",)\n'
                                   'atomic_save(d, "data/x.json")\n'
                                   'atomic_save(s, "data/state.json")\n')
            self.assertEqual(ac.check_agent("a", "pkg.a", root)["verdict"], ac.CONFIRMED)

    def test_it_cannot_hide_a_write_it_did_not_name(self):
        """Глушилка не всесильна: НЕназванная запись по-прежнему противоречие."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'INTERNAL_WRITES = ("data/state.json",)\n'
                                   'atomic_save(d, "data/x.json")\n'
                                   'atomic_save(z, "data/surprise.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONTRADICTION)
            self.assertEqual(r["undeclared_writes"], ["surprise.json"])

    def test_being_in_both_declarations_is_itself_a_contradiction(self):
        """Автор не решил, продукт это или внутренняя запись — вопрос открыт, не закрыт."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'INTERNAL_WRITES = ("data/x.json",)\n'
                                   'atomic_save(d, "data/x.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONTRADICTION)
            self.assertIn("не решил", r["note"])

    def test_absent_declaration_changes_nothing(self):
        """Обратная сторона: без объявления поведение прежнее слово в слово."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json",)\n'
                                   'atomic_save(d, "data/x.json")\n'
                                   'atomic_save(z, "data/state.json")\n')
            self.assertEqual(ac.check_agent("a", "pkg.a", root)["verdict"], ac.CONTRADICTION)

    def test_prose_mentioning_internal_writes_is_not_a_declaration(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.py"
            p.write_text('"""This module INTERNAL_WRITES nothing."""\nx = 1\n', encoding="utf-8")
            self.assertEqual(ac.declared_internal(p), ())


class TestWriteHelperVocabulary(unittest.TestCase):
    """Флот пишет НЕ каноническим `atomic_save`, а локальными помощниками.

    Замер 28.08: `_atomic_write(` — 656 вызовов, `_write_json(` — 530,
    `_atomic_write_json(` — 331, против `atomic_save(` — 680 но сосредоточенных.
    Первая редакция сканера знала только `atomic_save`/`open(...,"w")` и потому не
    видела ОСНОВНОЙ способ записи — из-за этого оставалась невидимой, например,
    запись стоп-крана `kill_switch_active.json` телеграм-ботом.
    """

    def test_local_helper_write_is_seen(self):
        got = scan_source('_atomic_write_json(ddir / "kill_switch_active.json", payload)\n')
        self.assertEqual(got.get("kill_switch_active.json"), {WRITE})

    def test_helper_with_path_as_SECOND_argument_is_seen(self):
        """Сигнатуры расходятся у разных авторов: `(path, obj)` и `(data, path)`.
        Поэтому просматриваются ВСЕ аргументы, а не фиксированная позиция."""
        got = scan_source('_atomic_write_json(payload, "data/x.json")\n')
        self.assertEqual(got.get("data/x.json"), {WRITE})

    def test_read_helper_is_not_a_write(self):
        """Обратный контроль: `_read_json` — чтение, и оно не должно стать записью."""
        got = scan_source('doc = _read_json(KILL, {})\nKILL = "kill_switch_active.json"\n')
        self.assertEqual(got.get("kill_switch_active.json"), {READ})


class TestBasenameComparisonIsNamedNotHidden(unittest.TestCase):
    """Одинаковые имена в разных каталогах существуют, и это НЕ ошибка кода.

    `data/market_regime.json` пишет дневной цикл в свой ddir (MP-534), а
    `data/investment_os/market_regime.json` — аналитик `io_market_regime`. Сверка
    сравнивает базовые имена (каталог статически неизвестен), и предел назван в коде.
    Тест стережёт, чтобы совпадение имени НЕ выдавалось за совпадение пути.
    """

    def test_same_basename_different_directory_does_not_raise_contradiction(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "a.py").write_text(
                'PRODUCES = ("data/investment_os/market_regime.json",)\n'
                '_atomic_write_json(ddir / "market_regime.json", r)\n', encoding="utf-8")
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONFIRMED,
                             "совпадение базового имени не обязано давать противоречие")


if __name__ == "__main__":
    unittest.main()
