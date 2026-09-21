"""Реестр читателей переписи против ИЗМЕРЕННОГО населения зовущих — заказ **G66 п. 1**.

ADR-443 измерил, какую базу берёт каждый НАЗВАННЫЙ читатель, и сказал вслух,
чего не спрашивал: реестр :data:`CENSUS_CONSUMERS` литерален, и читатель, в нём
не названный, прибору невидим. Заказ G66 п. 1 требует свести два населения —
объявленное реестром и измеренное — и спросить, есть ли среди неназванных
печатающий числа переписи.

Тесты держат ровно это:

* что измеренное население берётся У СОСЕДА (`census_consumer_census`), а не
  обходится заново: второй экземпляр того же правила и есть предмет переписи;
* что сведение идёт по координате «файл + ОБЛАСТЬ»: запись реестра с
  объявленной областью НЕ называет место вне неё, даже если файл тот же;
* что поверхность ввоза разбирается AST, а не текстом: форма
  ``from spa_core.monitoring import rule_second_copy_census`` полного имени в
  тексте не оставляет вовсе, а по ней перепись зовёт мост;
* что якорь есть ИМЯ, и имя, связанное с документом в одной функции, в
  соседней не связано ничем (собственная ошибка замера 21.09: первая редакция
  объявила чужой `doc` нашим и выдумала находку того самого класса, который
  ищет);
* что местное имя производителя (``import … as census``) читается: правило,
  знающее одно написание, объявило бы не читающим того, кто зовёт
  ``census.measure(root)`` прямо;
* что каждое отсутствие осталось ОТДЕЛЬНЫМ значением (инв. #17): соседа нет /
  у него нет имени / он не числит перепись переписью / реестр пуст — четыре
  разных исхода, и ни один не ноль;
* что порог НЕ введён: вердикт переписи координата не меняет.

Каждый тест — обратная сторона: сцена строится так, чтобы утверждение можно
было ОПРОВЕРГНУТЬ. Литеральных дат и литеральных pid здесь нет: мера не
спрашивает ни часов, ни ОС.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import census_consumer_census as neighbour
from spa_core.monitoring import rule_second_copy_census as mod
from spa_core.monitoring.rule_second_copy_census import (
    ANCHOR_LOCAL_RUN,
    CENSUS_CONSUMERS,
    CHANNEL_CODE,
    CHANNEL_TEST,
    CLI_SCOPE,
    CONSUMER_DELEGATES,
    CONSUMER_NO_READ,
    CONSUMER_READS,
    CONSUMER_UNMEASURED,
    IMPORT_MODULE,
    IMPORT_RENDERER,
    IMPORT_SYMBOLS,
    NEIGHBOUR_CENSUS,
    ORIGIN_BY_NAME,
    ORIGIN_CLI,
    ORIGIN_IMPORT,
    PRODUCER,
    SITE_NAMED,
    SITE_UNNAMED,
    UNSEEN_INSIDE_PRODUCER,
    UNSEEN_NO_LINK,
    UNSEEN_RENDERER_IMPORT,
    _binding_regions,
    consumer_registry_completeness,
    producer_import_surface,
    report,
)

_ROOT = Path(__file__).resolve().parents[2]

#: Пути реестра читаются ИЗ НЕГО САМОГО: вторая копия этого списка была бы
#: ровно тем дефектом, который перепись и ищет.
_PATH_OF = {spec["key"]: spec["path"] for spec in CENSUS_CONSUMERS}

#: Наименьший модуль, который сосед признаёт переписью: верхнеуровневый
#: `run`, принимающий `root`. Без него измеренного населения нет вовсе.
_PRODUCER_STUB = '''
def measure(root, *, now=None):
    return {"counts": {}, "pairs": 0}


def report(doc):
    return [f"перепись: пар {doc.get('pairs')}"]


def format_report(doc):
    return report(doc)


def run(root=".", *, write=True):
    return {"doc": measure(root)}


def main(argv=None):
    outcome = run(".")
    for line in report(outcome["doc"]):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


class _Scene:
    """Одноразовое дерево-сцена: настоящие файлы, настоящий разбор AST."""

    def __init__(self, files: dict, *, producer: str = _PRODUCER_STUB):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, PRODUCER, producer)
        for rel, source in files.items():
            _write(self.root, rel, source)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    def measure(self) -> dict:
        return consumer_registry_completeness(self.root)


def _site(doc: dict, rel: str, *, origin: str = None) -> dict:
    for site in doc["sites"]:
        if site["file"] == rel and (origin is None or site["origin"] == origin):
            return site
    raise AssertionError(f"места {rel!r} ({origin}) нет в замере: "
                         f"{[(s['file'], s['origin']) for s in doc['sites']]}")


def _unseen(doc: dict, key: str) -> dict:
    for item in doc["declared_unseen"]:
        if item["key"] == key:
            return item
    raise AssertionError(f"{key!r} не числится невидимым соседу")


class TestPopulationComesFromTheNeighbour(unittest.TestCase):
    """Измеренное население спрашивается у соседа, а не обходится заново."""

    def test_neighbour_absent_is_a_named_third_outcome(self):
        """Соседа не ввезти ⇒ НЕ ИЗМЕРЕНО с причиной, а не «зовущих нет»."""
        saved = sys.modules.pop(NEIGHBOUR_CENSUS, None)
        sys.modules[NEIGHBOUR_CENSUS] = None     # ввоз обязан упасть
        try:
            with _Scene({}) as scene:
                doc = scene.measure()
        finally:
            if saved is not None:
                sys.modules[NEIGHBOUR_CENSUS] = saved
            else:
                sys.modules.pop(NEIGHBOUR_CENSUS, None)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("не ввезена", doc["reason"])
        self.assertNotIn("counts", doc)

    def test_neighbour_without_the_needed_name_is_unmeasured(self):
        """У соседа нет нужного имени ⇒ НЕ ИЗМЕРЕНО, имя названо."""
        class _Crippled:
            pass

        crippled = _Crippled()
        for name in ("find_callees", "find_by_name_consumers",
                     "find_cli_consumers", "find_dynamic_consumers",
                     "_CODE_DIRS"):
            setattr(crippled, name, getattr(neighbour, name))
        saved = sys.modules.get(NEIGHBOUR_CENSUS)
        sys.modules[NEIGHBOUR_CENSUS] = crippled
        try:
            with _Scene({}) as scene:
                doc = scene.measure()
        finally:
            if saved is not None:
                sys.modules[NEIGHBOUR_CENSUS] = saved
            else:
                sys.modules.pop(NEIGHBOUR_CENSUS, None)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("find_fleet_consumers", doc["reason"])

    def test_producer_without_run_root_is_not_a_callee(self):
        """Сосед не числит перепись переписью ⇒ НЕ ИЗМЕРЕНО, не ноль."""
        with _Scene({}, producer="def measure(root):\n    return {}\n") as scene:
            doc = scene.measure()
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("не числит", doc["reason"])

    def test_empty_registry_is_unmeasured_not_zero_unnamed(self):
        """Пустой реестр ⇒ сводить не с чем; это НЕ «неназванных нет»."""
        saved = mod.CENSUS_CONSUMERS
        mod.CENSUS_CONSUMERS = ()
        try:
            with _Scene({}) as scene:
                doc = scene.measure()
        finally:
            mod.CENSUS_CONSUMERS = saved
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("пуст", doc["reason"])

    def test_by_name_caller_of_another_census_is_not_ours(self):
        """Зов ЧУЖОЙ переписи в наше население не попадает."""
        other = "spa_core/monitoring/other_census.py"
        caller = ("from spa_core.monitoring import other_census\n"
                  "\n"
                  "def step(args):\n"
                  "    return other_census.run(root=args.root)\n")
        with _Scene({other: _PRODUCER_STUB,
                     _PATH_OF["findings_bridge"]: caller}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["status"], "MEASURED")
        files = [s["file"] for s in doc["sites"] if s["origin"] == ORIGIN_BY_NAME]
        self.assertEqual(files, [])


class TestJoinIsByFileAndScope(unittest.TestCase):
    """Сведение идёт по «файл + ОБЛАСТЬ», иначе область реестра ничего не значит."""

    def test_cli_of_the_producer_is_not_named_by_the_scoped_entry(self):
        """`main` производителя запись про отрисовщик НЕ называет."""
        with _Scene({}) as scene:
            doc = scene.measure()
        site = _site(doc, PRODUCER, origin=ORIGIN_CLI)
        self.assertEqual(site["scope"], CLI_SCOPE)
        self.assertEqual(site["verdict"], SITE_UNNAMED)
        self.assertIsNone(site["registry"])

    def test_same_entry_without_scope_would_name_it(self):
        """Обратная сторона: снять область — и то же место станет названным."""
        saved = mod.CENSUS_CONSUMERS
        mod.CENSUS_CONSUMERS = tuple(
            dict(spec, scope=None) if spec["path"] == PRODUCER else spec
            for spec in saved)
        try:
            with _Scene({}) as scene:
                doc = scene.measure()
        finally:
            mod.CENSUS_CONSUMERS = saved
        site = _site(doc, PRODUCER, origin=ORIGIN_CLI)
        self.assertEqual(site["verdict"], SITE_NAMED)

    def test_site_outside_any_function_says_so_by_its_own_reason(self):
        """Место вне функции — свой ОТКАЗ, а не чужая «области нет».

        Дыра найдена батареей 21.09: снятие ветки давало тот же исход
        `UNMEASURED`, но с причиной про отсутствующую область — то есть
        отвечало не на тот вопрос.
        """
        caller = ("from spa_core.monitoring import rule_second_copy_census\n"
                  "\n"
                  "DOC = rule_second_copy_census.run(root=\".\")\n")
        with _Scene({"spa_core/monitoring/toplevel.py": caller}) as scene:
            site = _site(scene.measure(), "spa_core/monitoring/toplevel.py",
                         origin=ORIGIN_BY_NAME)
        self.assertIsNone(site["scope"])
        self.assertEqual(site["read"]["status"], CONSUMER_UNMEASURED)
        self.assertIn("вне функции", site["read"]["reason"])

    def test_producer_without_a_main_is_not_a_cli_consumer(self):
        """Нет `__main__` — нет и CLI-потребителя; ноль здесь ЗАРАБОТАН.

        Дыра найдена батареей 21.09: сцена всегда несла `__main__`, и ветка
        отсева проверялась вхолостую.
        """
        headless = _PRODUCER_STUB.replace(
            'if __name__ == "__main__":\n    raise SystemExit(main())\n', "")
        self.assertNotIn("__main__", headless)
        with _Scene({}, producer=headless) as scene:
            doc = scene.measure()
        self.assertEqual(
            [s for s in doc["sites"] if s["origin"] == ORIGIN_CLI], [])

    def test_call_inside_a_named_file_is_named(self):
        """Зов в файле, названном реестром без области, — НАЗВАН."""
        caller = ("from spa_core.monitoring import rule_second_copy_census\n"
                  "\n"
                  "def step(args):\n"
                  "    return rule_second_copy_census.run(root=args.root)\n")
        with _Scene({_PATH_OF["findings_bridge"]: caller}) as scene:
            doc = scene.measure()
        site = _site(doc, _PATH_OF["findings_bridge"], origin=ORIGIN_BY_NAME)
        self.assertEqual(site["verdict"], SITE_NAMED)
        self.assertEqual(site["registry"], "findings_bridge")
        self.assertEqual(site["scope"], "step")


class TestImportSurfaceIsParsedNotGrepped(unittest.TestCase):
    """Поверхность ввоза — AST: текстовое правило теряет форму моста."""

    def test_three_import_forms_are_all_found(self):
        files = {
            "spa_core/monitoring/a.py":
                "from spa_core.monitoring.rule_second_copy_census import report\n",
            "spa_core/monitoring/b.py":
                "from spa_core.monitoring import rule_second_copy_census as census\n",
            "spa_core/monitoring/c.py":
                "import spa_core.monitoring.rule_second_copy_census as rsc\n",
            "spa_core/monitoring/d.py":
                "from spa_core.monitoring.rule_second_copy_census import PRODUCER\n",
        }
        with _Scene(files) as scene:
            surface = producer_import_surface(scene.root, neighbour._CODE_DIRS)
        kinds = {item["file"]: item["kind"] for item in surface}
        self.assertEqual(kinds["spa_core/monitoring/a.py"], IMPORT_RENDERER)
        self.assertEqual(kinds["spa_core/monitoring/b.py"], IMPORT_MODULE)
        self.assertEqual(kinds["spa_core/monitoring/c.py"], IMPORT_MODULE)
        self.assertEqual(kinds["spa_core/monitoring/d.py"], IMPORT_SYMBOLS)

    def test_package_form_leaves_no_full_name_in_the_text(self):
        """Обратная сторона: та форма, которую текстовое правило теряет."""
        source = "from spa_core.monitoring import rule_second_copy_census as census\n"
        self.assertNotIn("spa_core.monitoring.rule_second_copy_census", source)
        with _Scene({"spa_core/monitoring/b.py": source}) as scene:
            surface = producer_import_surface(scene.root, neighbour._CODE_DIRS)
        files = [item["file"] for item in surface]
        self.assertIn("spa_core/monitoring/b.py", files)

    def test_local_alias_is_recorded(self):
        with _Scene({"spa_core/monitoring/b.py":
                     "from spa_core.monitoring import "
                     "rule_second_copy_census as census\n"}) as scene:
            surface = producer_import_surface(scene.root, neighbour._CODE_DIRS)
        item = [i for i in surface if i["file"] == "spa_core/monitoring/b.py"][0]
        self.assertEqual(item["aliases"], ["census"])

    def test_the_producer_does_not_import_itself(self):
        """Сцена несёт САМОВВОЗ: без него ветка отсева проверялась бы вхолостую.

        Дыра найдена батареей 21.09: снятие отсева не меняло вердиктов, потому
        что в сцене производитель себя не ввозил вовсе (класс «сторож не
        проверен, пока умолчание делает его лишним»).
        """
        selfish = ("from spa_core.monitoring import rule_second_copy_census\n"
                   + _PRODUCER_STUB)
        with _Scene({}, producer=selfish) as scene:
            surface = producer_import_surface(scene.root, neighbour._CODE_DIRS)
            doc = scene.measure()
        self.assertIn("rule_second_copy_census", selfish.split("\n")[0])
        self.assertNotIn(PRODUCER, [item["file"] for item in surface])
        self.assertNotIn(
            ORIGIN_IMPORT,
            [s["origin"] for s in doc["sites"] if s["file"] == PRODUCER])

    def test_unreadable_file_is_a_number_not_silence(self):
        with _Scene({"spa_core/monitoring/broken.py":
                     "def f(:\n"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["counts"]["import_files_unreadable"], 1)
        self.assertEqual(doc["unreadable"][0]["file"],
                         "spa_core/monitoring/broken.py")

    def test_code_dirs_come_from_the_neighbour_not_from_a_second_copy(self):
        """Каталоги — ЧУЖОЙ параметр: своей копии определения населения нет."""
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("neighbour._CODE_DIRS", source)
        self.assertIn("_CODE_DIRS", mod._NEIGHBOUR_API)


class TestReadingIsAskedPerBindingRegion(unittest.TestCase):
    """Якорь есть ИМЯ, и в соседней функции оно не связано ничем."""

    _READER_SAME_FUNCTION = (
        "from spa_core.monitoring import rule_second_copy_census as census\n"
        "\n"
        "def show(root):\n"
        "    doc = census.measure(root)\n"
        "    print(f\"перепись: пар {doc['pairs']} · всё\")\n")

    _READER_OTHER_FUNCTION = (
        "from spa_core.monitoring import rule_second_copy_census as census\n"
        "\n"
        "def collect(root):\n"
        "    doc = census.measure(root)\n"
        "    return doc\n"
        "\n"
        "def show(doc):\n"
        "    print(f\"свой зонд: пар {doc['pairs']} · всё\")\n")

    def test_number_in_the_same_function_is_read(self):
        with _Scene({"spa_core/monitoring/reader.py":
                     self._READER_SAME_FUNCTION}) as scene:
            doc = scene.measure()
        site = _site(doc, "spa_core/monitoring/reader.py", origin=ORIGIN_IMPORT)
        self.assertEqual(site["read"]["status"], CONSUMER_READS)
        self.assertEqual(doc["counts"]["unnamed_reading"], 1)

    def test_same_name_in_another_function_is_not_our_document(self):
        """Обратная сторона той же сцены — собственная ошибка замера 21.09."""
        with _Scene({"spa_core/monitoring/reader.py":
                     self._READER_OTHER_FUNCTION}) as scene:
            doc = scene.measure()
        site = _site(doc, "spa_core/monitoring/reader.py", origin=ORIGIN_IMPORT)
        self.assertEqual(site["read"]["status"], CONSUMER_NO_READ)
        self.assertEqual(doc["counts"]["unnamed_reading"], 0)

    def test_binding_regions_split_functions_and_keep_closures(self):
        tree = ast.parse("x = 1\n"
                         "def a():\n"
                         "    def inner():\n"
                         "        pass\n"
                         "def b():\n"
                         "    pass\n"
                         "class C:\n"
                         "    def m(self):\n"
                         "        pass\n")
        regions = _binding_regions([tree])
        names = []
        for region in regions:
            for node in region:
                names.append(getattr(node, "name", "<модуль>"))
        self.assertEqual(sorted(names), ["<модуль>", "a", "b", "m"])
        inner = [node for region in regions for node in region
                 if getattr(node, "name", None) == "inner"]
        self.assertEqual(inner, [], "замыкание обязано остаться внутри родителя")

    def test_alias_is_resolved_and_the_bare_module_name_is_not_assumed(self):
        """Местное имя читается; правило одного написания промахнулось бы."""
        with _Scene({"spa_core/monitoring/reader.py":
                     self._READER_SAME_FUNCTION}) as scene:
            site = _site(scene.measure(), "spa_core/monitoring/reader.py",
                         origin=ORIGIN_IMPORT)
        self.assertEqual(site["aliases"], ["census"])
        self.assertNotIn("rule_second_copy_census",
                         self._READER_SAME_FUNCTION.split("\n")[3])

    def test_import_without_any_call_is_no_read_not_a_finding(self):
        with _Scene({"spa_core/monitoring/quiet.py":
                     "from spa_core.monitoring.rule_second_copy_census "
                     "import PRODUCER\n"
                     "\n"
                     "NAME = PRODUCER\n"}) as scene:
            doc = scene.measure()
        site = _site(doc, "spa_core/monitoring/quiet.py", origin=ORIGIN_IMPORT)
        self.assertEqual(site["read"]["status"], CONSUMER_NO_READ)
        self.assertEqual(doc["findings"], [])

    def test_producer_cli_delegates_through_a_bare_call(self):
        """Внутри производителя отрисовщик зовётся ГОЛЫМ именем, не ввозом."""
        with _Scene({}) as scene:
            site = _site(scene.measure(), PRODUCER, origin=ORIGIN_CLI)
        self.assertEqual(site["read"]["status"], CONSUMER_DELEGATES)
        self.assertIn("report", site["read"]["delegates_via"])

    def test_cli_that_prints_its_own_numbers_is_read_not_delegated(self):
        """Обратная сторона: `main`, печатающий числа сам, — ЧИТАЕТ.

        Держит якорь `local_run`: внутри производителя документ рождается
        голым зовом `run()`/`measure()`, и правило «первый параметр» тут
        промахнулось бы мимо (первый параметр `main` — `argv`).
        """
        producer = _PRODUCER_STUB.replace(
            "    for line in report(outcome[\"doc\"]):\n        print(line)\n",
            "    doc = outcome[\"doc\"]\n"
            "    print(f\"перепись: пар {doc['pairs']} · всё\")\n")
        self.assertNotIn("for line in report", producer)
        with _Scene({}, producer=producer) as scene:
            site = _site(scene.measure(), PRODUCER, origin=ORIGIN_CLI)
        self.assertEqual(site["read"]["status"], CONSUMER_READS)

    def test_two_aliases_in_one_file_are_both_kept(self):
        """Файл, ввёзший производителя дважды, читается под ОБОИМИ именами."""
        # Оба ввоза МОДУЛЬНЫЕ и равного ранга: при замене (а не сложении)
        # первое имя терялось бы, и чтение под ним стало бы невидимым. Дыра
        # найдена батареей 21.09 — прежняя сцена ранги имела разные, и
        # замена давала тот же ответ, что и сложение.
        source = ("from spa_core.monitoring import "
                  "rule_second_copy_census as census\n"
                  "import spa_core.monitoring.rule_second_copy_census as rsc\n"
                  "\n"
                  "def show(root):\n"
                  "    doc = census.measure(root)\n"
                  "    print(f\"пар {doc['pairs']} · всё\")\n")
        with _Scene({"spa_core/monitoring/two.py": source}) as scene:
            site = _site(scene.measure(), "spa_core/monitoring/two.py",
                         origin=ORIGIN_IMPORT)
        self.assertEqual(site["aliases"], ["census", "rsc"])
        self.assertEqual(site["read"]["status"], CONSUMER_READS)

    def test_enclosing_scope_is_the_innermost_function(self):
        """Область места — САМАЯ ВНУТРЕННЯЯ функция, а не верхняя."""
        caller = ("from spa_core.monitoring import rule_second_copy_census\n"
                  "\n"
                  "def outer(args):\n"
                  "    def inner():\n"
                  "        return rule_second_copy_census.run(root=args.root)\n"
                  "    return inner\n")
        with _Scene({_PATH_OF["findings_bridge"]: caller}) as scene:
            site = _site(scene.measure(), _PATH_OF["findings_bridge"],
                         origin=ORIGIN_BY_NAME)
        self.assertEqual(site["scope"], "inner")

    def test_anchor_mode_of_the_cli_is_declared_local_run(self):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn(ANCHOR_LOCAL_RUN, source)


class TestChannelsAreSeparatedBeforeTheMeasurement(unittest.TestCase):
    """Печать теста до оркестратора не доезжает — канал объявлен заранее."""

    _READER = ("from spa_core.monitoring import rule_second_copy_census as c\n"
               "\n"
               "def show(root):\n"
               "    doc = c.measure(root)\n"
               "    print(f\"пар {doc['pairs']} · всё\")\n")

    def test_test_file_and_code_file_are_counted_apart(self):
        with _Scene({"spa_core/monitoring/reader.py": self._READER,
                     "spa_core/tests/test_reader.py": self._READER}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["counts"]["unnamed_code"], 2)   # + CLI производителя
        self.assertEqual(doc["counts"]["unnamed_test"], 1)
        self.assertEqual(
            _site(doc, "spa_core/tests/test_reader.py")["channel"], CHANNEL_TEST)
        self.assertEqual(
            _site(doc, "spa_core/monitoring/reader.py")["channel"], CHANNEL_CODE)

    def test_channel_is_decided_by_the_file_name_not_by_the_directory(self):
        with _Scene({"spa_core/monitoring/test_helper.py": self._READER}) as scene:
            doc = scene.measure()
        self.assertEqual(
            _site(doc, "spa_core/monitoring/test_helper.py")["channel"],
            CHANNEL_TEST)


class TestDeclaredSideHasThreeOutcomes(unittest.TestCase):
    """Объявленный читатель, не встреченный соседом, — три РАЗНЫЕ причины."""

    def test_region_of_the_producer_is_invisible_by_construction(self):
        with _Scene({}) as scene:
            doc = scene.measure()
        self.assertEqual(_unseen(doc, "report_section")["reason"],
                         UNSEEN_INSIDE_PRODUCER)

    def test_renderer_importer_is_the_finding(self):
        office = ("def step():\n"
                  "    from spa_core.monitoring.rule_second_copy_census "
                  "import format_report\n"
                  "    return format_report\n")
        with _Scene({_PATH_OF["office_step"]: office}) as scene:
            doc = scene.measure()
        item = _unseen(doc, "office_step")
        self.assertEqual(item["reason"], UNSEEN_RENDERER_IMPORT)
        self.assertTrue(item["seen_by_import_surface"])
        kinds = [f["kind"] for f in doc["findings"]]
        self.assertIn("declared_consumer_invisible_to_neighbour", kinds)

    def test_no_link_at_all_is_a_separate_reason(self):
        with _Scene({_PATH_OF["office_step"]: "X = 1\n"}) as scene:
            doc = scene.measure()
        item = _unseen(doc, "office_step")
        self.assertEqual(item["reason"], UNSEEN_NO_LINK)
        self.assertFalse(item["seen_by_import_surface"])
        self.assertEqual(doc["findings"], [])

    def test_caller_seen_by_the_neighbour_is_not_reported_as_unseen(self):
        """Обратная сторона: зовущий `run` из реестра исчезает из списка."""
        caller = ("from spa_core.monitoring import rule_second_copy_census\n"
                  "\n"
                  "def step(args):\n"
                  "    return rule_second_copy_census.run(root=args.root)\n")
        with _Scene({_PATH_OF["findings_bridge"]: caller}) as scene:
            doc = scene.measure()
        self.assertNotIn("findings_bridge",
                         [i["key"] for i in doc["declared_unseen"]])
        self.assertEqual(doc["counts"]["seen_by_neighbour"], 1)


class TestNoThresholdIsIntroduced(unittest.TestCase):
    """Координата НАЗЫВАЕТ; вердикта переписи она не двигает (запрет G62)."""

    def test_applied_is_false(self):
        with _Scene({}) as scene:
            self.assertIs(scene.measure()["applied"], False)

    def test_census_status_is_decided_by_rows_only(self):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn('"status": "FINDING" if findings else "CLEAN"', source)
        self.assertNotIn("consumer_registry_completeness[", source)


class TestReportSpeaksAndRefusesOutLoud(unittest.TestCase):
    """Отчёт печатает секцию и НЕ выдаёт «не измерено» за «чисто»."""

    def test_measured_section_names_the_numbers(self):
        with _Scene({}) as scene:
            doc = {"status": "CLEAN", "counts": {}, "rows": [],
                   "consumer_registry_completeness": scene.measure()}
            lines = [ln for ln in report(doc) if "РЕЕСТР ЧИТАТЕЛЕЙ" in ln]
        self.assertTrue(lines)
        self.assertTrue(any("НЕ названо" in ln for ln in lines))
        self.assertTrue(any("СОСЕД НЕ ВИДИТ" in ln for ln in lines))

    def test_unmeasured_section_prints_the_reason(self):
        doc = {"status": "CLEAN", "counts": {}, "rows": [],
               "consumer_registry_completeness": {
                   "status": "UNMEASURED", "reason": "соседа нет"}}
        lines = [ln for ln in report(doc) if "РЕЕСТР ЧИТАТЕЛЕЙ" in ln]
        self.assertEqual(len(lines), 1)
        self.assertIn("соседа нет", lines[0])

    def test_absent_key_is_not_silence(self):
        """«Ключа нет» и «причина такая-то» — РАЗНЫЕ строки, а не одна.

        Дыра найдена батареей 21.09: `observed(...) or {}` давало пустой
        словарь, и отсутствие ключа печаталось как «НЕ ИЗМЕРЕН: None» — то
        есть выдавалось за измеренную причину.
        """
        doc = {"status": "CLEAN", "counts": {}, "rows": []}
        lines = [ln for ln in report(doc) if "РЕЕСТР ЧИТАТЕЛЕЙ" in ln]
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕН — ", lines[0])
        self.assertIn("собрана без", lines[0])
        self.assertNotIn("None", lines[0])


class TestLiveTree(unittest.TestCase):
    """Живой контроль: замер на настоящем дереве не холостой."""

    @classmethod
    def setUpClass(cls):
        cls.doc = consumer_registry_completeness(_ROOT)

    def test_measured_and_not_empty(self):
        self.assertEqual(self.doc["status"], "MEASURED")
        self.assertGreater(self.doc["counts"]["sites"], 0)
        self.assertGreater(self.doc["counts"]["import_surface"], 0)

    def test_office_step_is_invisible_to_the_neighbour(self):
        """Читатель, доносящий перепись до оркестратора, соседу невидим."""
        item = _unseen(self.doc, "office_step")
        self.assertEqual(item["reason"], UNSEEN_RENDERER_IMPORT)

    def test_bridge_is_the_one_caller_the_neighbour_does_see(self):
        site = _site(self.doc, _PATH_OF["findings_bridge"],
                     origin=ORIGIN_BY_NAME)
        self.assertEqual(site["verdict"], SITE_NAMED)

    def test_unresolved_dynamic_calls_are_carried_as_a_number(self):
        self.assertIsInstance(
            self.doc["counts"]["neighbour_dynamic_unresolved"], int)
        self.assertIn("не разрешимых статикой",
                      " ".join(self.doc["blind"]))


if __name__ == "__main__":
    unittest.main()
