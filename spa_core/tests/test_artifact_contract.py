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


class TestVerdictIsPerArtifactNotPerAgent(unittest.TestCase):
    """Одной видимой записи НЕ хватает, чтобы подтвердить объявление из многих строк.

    Каждая сцена ниже — замер 08.09 по живому дереву (`origin/main` 3934fe7f5), а не
    выдуманный случай:

    * `com.spa.decision_loop` объявляет 27 продуктов, запись видна у ОДНОГО — и до
      этой правки агент назывался `confirmed`. Тот же перекос #522 замерил как «1 из 25»;
    * `com.spa.daily_cycle` — 3 из 10, и среди семи неизмеренных
      `data/equity_curve_daily.json` (живой трек) и `data/current_positions.json`;
    * по флоту: у 34 агентов с вердиктом `confirmed` объявлено 85 продуктов, а запись
      видна у 45. Зелёное слово покрывало 40 продуктов, про которые не измерено ничего.

    Обратная сторона проверяется тоже: при ПОЛНОМ покрытии ответ обязан остаться
    прежним слово в слово, иначе исход не разделён, а подменён.
    """

    def _agent(self, td, src):
        root = Path(td)
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "a.py").write_text(src, encoding="utf-8")
        return root

    def test_one_visible_write_does_not_confirm_ten_declarations(self):
        """Форма `com.spa.daily_cycle`: объявлено 10, видно 3."""
        decl = ", ".join(f'"data/x{i}.json"' for i in range(10))
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, f"PRODUCES = ({decl})\n"
                                   'atomic_save(d, "data/x0.json")\n'
                                   'atomic_save(d, "data/x1.json")\n'
                                   'atomic_save(d, "data/x2.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.PARTIAL)
            self.assertNotEqual(r["verdict"], ac.CONFIRMED,
                                "три видимые записи из десяти — это не подтверждение контракта")
            self.assertEqual(r["coverage"]["declared"], 10)
            self.assertEqual(len(r["coverage"]["confirmed"]), 3)
            self.assertEqual(len(r["coverage"]["unmeasured"]), 7)

    def test_full_coverage_is_still_confirmed(self):
        """Обратная половина: разделение исхода не смеет красить исправное."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json", "data/y.json")\n'
                                   'atomic_save(d, "data/x.json")\n'
                                   'atomic_save(d, "data/y.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONFIRMED)
            self.assertEqual(r["coverage"]["unmeasured"], [])

    def test_coverage_names_each_unmeasured_product(self):
        """Счётчик не говорит, ЧТО не измерено, — а решение принимают по продукту."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/seen.json", "data/track.json")\n'
                                   'atomic_save(d, "data/seen.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["coverage"]["confirmed"], ["data/seen.json"])
            self.assertEqual(r["coverage"]["unmeasured"], ["data/track.json"])

    def test_nothing_visible_is_still_unmeasured_not_partial(self):
        """`partial` — про ЧАСТЬ. Ноль видимых записей это по-прежнему «не измерено»."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json", "data/y.json")\n'
                                   'def emit(self):\n'
                                   '    atomic_save(d, str(self.dir / f"{self.key}.json"))\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.UNMEASURED)

    def test_contradiction_still_wins_over_partial(self):
        """Дефект важнее неполноты: запись мимо контракта остаётся находкой."""
        with tempfile.TemporaryDirectory() as td:
            root = self._agent(td, 'PRODUCES = ("data/x.json", "data/y.json")\n'
                                   'atomic_save(d, "data/x.json")\n'
                                   'atomic_save(z, "data/surprise.json")\n')
            r = ac.check_agent("a", "pkg.a", root)
            self.assertEqual(r["verdict"], ac.CONTRADICTION)

    def test_partial_is_not_a_finding_for_the_watchdog(self):
        """B7 берёт находкой ТОЛЬКО противоречие — новый исход не смеет стать потоком.

        Условие подключения B7 было названо вслух в его собственной шапке: сигнал
        такого объёма стал бы потоком находок владельцу. `partial` сегодня шесть.
        """
        self.assertNotEqual(ac.PARTIAL, ac.CONTRADICTION)


class TestAcceptanceProbeStopsOverclaiming(unittest.TestCase):
    """Проба приёмки карточки — место, где неполный вердикт становится РЕШЕНИЕМ.

    Замер 08.09: карточка `inbox-dnevnoi-tsikl-pishet-chetyre-artefakta-mimo-kontrakta`
    несёт `acceptance_probe: artifact_contract_confirmed:com.spa.daily_cycle`, и проба
    отвечала ВЫПОЛНЕНО по свидетельству о трёх продуктах из десяти.
    """

    def _row(self, verdict, cov=None):
        row = {"label": "com.spa.x", "verdict": verdict}
        if cov is not None:
            row["coverage"] = cov
        return {"rows": [row]}

    def _run(self, audit):
        from spa_core.monitoring import artifact_contract as m
        from spa_core.monitoring import card_acceptance as ca
        real = m.audit_fleet
        m.audit_fleet = lambda *a, **k: audit
        try:
            return ca.run_probe("artifact_contract_confirmed:com.spa.x")
        finally:
            m.audit_fleet = real

    def test_partial_is_unmeasured_not_satisfied(self):
        from spa_core.monitoring import card_acceptance as ca
        v, detail = self._run(self._row(ac.PARTIAL, {
            "declared": 10, "confirmed": ["data/a.json"],
            "unmeasured": ["data/equity_curve_daily.json"]}))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertNotEqual(v, ca.SATISFIED, "три продукта из десяти — не выполненный критерий")
        self.assertIn("equity_curve_daily", detail,
                      "неизмеренный продукт обязан быть НАЗВАН, а не сосчитан")

    def test_partial_is_not_reported_as_failure_either(self):
        """«Не выполнено» было бы такой же неправдой: про эти продукты не измерено НИЧЕГО."""
        from spa_core.monitoring import card_acceptance as ca
        v, _ = self._run(self._row(ac.PARTIAL, {
            "declared": 2, "confirmed": ["data/a.json"], "unmeasured": ["data/b.json"]}))
        self.assertNotEqual(v, ca.NOT_SATISFIED)

    def test_full_coverage_still_satisfies(self):
        from spa_core.monitoring import card_acceptance as ca
        v, _ = self._run(self._row(ac.CONFIRMED))
        self.assertEqual(v, ca.SATISFIED)

    def test_contradiction_still_fails(self):
        from spa_core.monitoring import card_acceptance as ca
        v, _ = self._run(self._row(ac.CONTRADICTION))
        self.assertEqual(v, ca.NOT_SATISFIED)


class TestPartialIsSaidAloud(unittest.TestCase):
    """Третий исход, который не звучит, — тот же молчащий канал (ADR-261).

    Найдено СВОЕЙ батареей: мутация «снять печать `ЧАСТИЧНО`» ВЫЖИЛА — счётчик
    `partial` в сводке был, а поимённой строки не проверял никто. Ровно тот приём,
    ради которого #525 вынес печать сторожа в `_print_report`: «звучит ли исход
    вслух» обязано быть ИЗМЕРИМО, иначе третий исход существует только в JSON.
    """

    def _audit(self):
        return {"total": 2, "counts": {ac.PARTIAL: 1, ac.CONFIRMED: 1},
                "rows": [
                    {"label": "com.spa.x", "module": "pkg.x", "verdict": ac.PARTIAL,
                     "declared": ["data/a.json", "data/b.json"],
                     "coverage": {"declared": 2, "confirmed": ["data/a.json"],
                                  "unmeasured": ["data/b.json"]}},
                    {"label": "com.spa.y", "module": "pkg.y", "verdict": ac.CONFIRMED,
                     "declared": ["data/c.json"],
                     "coverage": {"declared": 1, "confirmed": ["data/c.json"],
                                  "unmeasured": []}}]}

    def _out(self):
        import contextlib, io, sys as _s
        real = ac.audit_fleet
        ac.audit_fleet = lambda *a, **k: self._audit()
        argv = _s.argv
        _s.argv = ["artifact_contract"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ac.main()
        finally:
            ac.audit_fleet = real
            _s.argv = argv
        return buf.getvalue()

    def test_partial_agent_is_named_not_only_counted(self):
        out = self._out()
        self.assertIn("ЧАСТИЧНО", out, "исход есть в счётчике и молчит в выводе")
        self.assertIn("com.spa.x", out)

    def test_the_unmeasured_product_is_named_in_the_output(self):
        """Счётчик не говорит, ЧТО не измерено, — а решение принимают по продукту."""
        out = self._out()
        self.assertIn("data/b.json", out)

    def test_confirmed_agent_is_not_announced_as_partial(self):
        """Обратный контроль: строка не печатается для всех подряд."""
        out = self._out()
        self.assertNotIn("ЧАСТИЧНО com.spa.y", out)

    def test_partial_appears_in_the_counter_block_too(self):
        out = self._out()
        self.assertRegex(out, r"partial\s+1")


if __name__ == "__main__":
    unittest.main()
