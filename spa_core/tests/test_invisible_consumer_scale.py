"""Масштаб класса «невидимый потребитель» у ВСЕХ переписей — заказ **G67 п. 1**.

ADR-444 нашёл у ОДНОЙ переписи потребителя, невидимого соседу
``census_consumer_census`` по ФОРМЕ вопроса: сосед спрашивает «кто зовёт
``run``», а шаг 0-офис ``run`` не зовёт — он ввозит отрисовщик. Заказ требует
померить класс у всех 85: находка у одной без замера у остальных есть догадка
о масштабе.

Тесты держат ровно это:

* что **отрисовщик ИЗМЕРЕН, а не взят словарём**: правило спрашивает у самого
  модуля, чей результат он печатает. Словарь ``("report", "format_report")``,
  объявленный ADR-444 для одного производителя, на 85 переписей был бы второй
  копией правила в СЛОВАРЕ — тем самым классом, который перепись ищет у
  других;
* что **обе дороги к ``run`` закрыты**: зов через местное имя модуля и зов
  ввезённого напрямую ``run``. Спросить одну значило бы повторить слепоту
  соседа на соседней оси;
* что **пакетная форма ввоза видна**: ``from spa_core.monitoring import X``
  полного имени в тексте не оставляет вовсе, а по ней перепись зовёт мост;
* что **третий исход РАЗДЕЛЁН** (инв. #17): «у модуля нет ни одной текстовой
  функции» (класс не применим по построению) и «текстовые функции есть, но
  печать их не решает» (граница правила) — разные утверждения, и слить их
  значило бы выдать первое за второе;
* что **цена правила печати едет ЧИСЛОМ**: нижняя граница занижения опирается
  на разрешённый печатью отрисовщик, верхняя добавляет тех, у кого печать его
  не решает; интервал измерен, а не оговорён прозой;
* что **обратная сторона измерена**: занижено ли население ДО НУЛЯ — отдельный
  вопрос, и ответ на него в документе, а не в умолчании;
* что **порог НЕ введён**: вердикт переписи координата не меняет.

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
    CHANNEL_CODE,
    CHANNEL_TEST,
    NEIGHBOUR_CENSUS,
    ORCHESTRATOR_READER,
    RENDERER_NONE_EXISTS,
    RENDERER_NOT_PRINTED,
    invisible_consumer_scale,
    printed_by_producer,
    report,
)

#: Наименьшая перепись: верхнеуровневый `run`, принимающий `root`, и документ,
#: который сам модуль печатает НАЗВАННОЙ функцией.
_CENSUS = '''
def measure(root):
    return {"pairs": 0}


def format_report(doc):
    return [f"пар {doc.get('pairs')}"]


def run(root=".", *, write=True):
    return {"doc": measure(root)}


def main(argv=None):
    for line in format_report(run(".")["doc"]):
        print(line)
    return 0
'''

#: Та же перепись, но печатающая ВСТРОЕННО и без единой текстовой функции:
#: отдать потребителю нечего, и класс сюда не применим по построению.
_CENSUS_INLINE = '''
def measure(root):
    return {"pairs": 0}


def run(root=".", *, write=True):
    return {"doc": measure(root)}


def main(argv=None):
    doc = run(".")["doc"]
    print(f"пар {doc.get('pairs')}")
    return 0
'''

#: Перепись с текстовой функцией, которую сама НЕ печатает: граница правила.
_CENSUS_UNPRINTED = '''
from typing import List


def measure(root):
    return {"pairs": 0}


def lines_of(doc) -> List[str]:
    return [f"пар {doc.get('pairs')}"]


def run(root=".", *, write=True):
    return {"doc": measure(root)}


def main(argv=None):
    print("готово")
    return 0
'''


#: Модуль печатает ВВЕЗЁННУЮ функцию: своей она не становится.
FOREIGN_PRINT = '''
from helpers import shout


def measure(root):
    return {}


def main():
    print(shout({}))
    return 0
'''


def _full_stand(root: Path, *, reader: str = "scripts/reader.py") -> Path:
    """Дерево, пригодное для ВСЕЙ переписи, а не только для координаты.

    У ``measure`` своя предпосылка — хотя бы один файл-сторож; без неё она
    отказывает fail-CLOSED (`NotMeasured`), и это верно. Проводку надо мерить
    на дереве, где отказала бы ТОЛЬКО она, а не предпосылка соседней части.
    """
    _write(root, "spa_core/monitoring/alpha.py", _CENSUS)
    _write(root, reader,
           "from spa_core.monitoring.alpha import format_report\n"
           "def show(doc):\n    return format_report(doc)\n")
    _write(root, "spa_core/tests/test_guard.py",
           "def test_guard():\n    assert True\n")
    return root


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


class PrintedByProducerTest(unittest.TestCase):
    """Правило отрисовщика: печать у САМОГО производителя, а не имя."""

    def test_function_whose_result_the_module_prints_is_a_renderer(self):
        self.assertEqual(printed_by_producer(ast.parse(_CENSUS)),
                         ["format_report"])

    def test_function_the_module_merely_defines_is_NOT_a_renderer(self):
        """Обратная сторона: та же функция, но её результат не печатают."""
        source = _CENSUS.replace("for line in format_report(run(\".\")[\"doc\"]):\n        print(line)",
                                 "format_report(run(\".\")[\"doc\"])")
        self.assertNotIn("print(line)", source)
        self.assertEqual(printed_by_producer(ast.parse(source)), [])

    def test_for_loop_without_a_print_in_its_body_is_not_counted(self):
        """Обратная сторона обхода: без печати в теле это не отрисовка."""
        source = '''
def rows(doc):
    return [1]


def main():
    total = 0
    for row in rows({}):
        total += row
    return total
'''
        self.assertEqual(printed_by_producer(ast.parse(source)), [])

    def test_run_main_measure_are_never_renderers(self):
        """`print(run(...))` не делает `run` отрисовщиком: его зов сосед видит."""
        source = '''
def run(root="."):
    return "готово"


def main():
    print(run("."))
    return 0
'''
        self.assertEqual(printed_by_producer(ast.parse(source)), [])

    def test_a_printed_call_to_a_FOREIGN_function_is_not_our_renderer(self):
        """Обратная сторона отбора: печатают чужое имя, а не функцию модуля.

        Дыра, найденная батареей: без проверки «имя объявлено ЗДЕСЬ» правило
        объявило бы отрисовщиком переписи любую ВВЕЗЁННУЮ функцию, которую
        модуль печатает, — и потребитель, ввёзший её у настоящего владельца,
        стал бы находкой о чужой переписи.
        """
        source = FOREIGN_PRINT
        self.assertEqual(printed_by_producer(ast.parse(source)), [])

    def test_renderer_reached_through_join_inside_print_is_found(self):
        source = '''
def body(doc):
    return ["a"]


def main():
    print("\\n".join(body({})))
    return 0
'''
        self.assertEqual(printed_by_producer(ast.parse(source)), ["body"])


class _Stand(unittest.TestCase):
    """Одноразовое дерево: живой репозиторий тестами не трогается."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def measure(self):
        return invisible_consumer_scale(self.root)


class InvisibleConsumerTest(_Stand):

    def test_consumer_importing_the_renderer_without_calling_run_is_found(self):
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.alpha import format_report\n"
               "def show(doc):\n    return format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["status"], "CRITICAL")
        self.assertEqual(doc["understated"], ["alpha"])
        self.assertEqual(doc["counts"]["sites"], 1)
        self.assertEqual(doc["counts"]["sites_code"], 1)
        self.assertEqual(doc["counts"]["sites_test"], 0)

    def test_the_same_consumer_that_DOES_call_run_is_not_a_finding(self):
        """Обратная сторона: зов `run` виден соседу, и занижения нет."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring import alpha\n"
               "def show():\n"
               "    doc = alpha.run('.')['doc']\n"
               "    return alpha.format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["understated"], [])
        self.assertEqual(doc["status"], "OK")

    def test_run_imported_directly_and_called_closes_the_second_road(self):
        """Вторая дорога к `run`: ввезён напрямую. Правило знает обе."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.alpha import format_report, run\n"
               "def show():\n    return format_report(run('.')['doc'])\n")
        self.assertEqual(self.measure()["understated"], [])

    def test_package_import_form_is_seen_though_it_leaves_no_dotted_text(self):
        """Пакетная форма: полного имени модуля в тексте нет вовсе."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        source = ("from spa_core.monitoring import alpha\n"
                  "def show(doc):\n    return alpha.format_report(doc)\n")
        _write(self.root, "scripts/reader.py", source)
        self.assertNotIn("monitoring.alpha", source)   # текстом не находится
        doc = self.measure()
        self.assertEqual(doc["understated"], ["alpha"])

    def test_dotted_import_form_is_seen_too(self):
        """Третья форма ввоза: ``import spa_core.monitoring.alpha as alpha``.

        Дыра, найденная батареей: правило знало две формы из трёх, и
        потребитель, ввозящий модуль точкой, был бы невидим — ровно той же
        слепотой, которую вся координата и мерит у соседа.
        """
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "import spa_core.monitoring.alpha as alpha\n"
               "def show(doc):\n    return alpha.format_report(doc)\n")
        self.assertEqual(self.measure()["understated"], ["alpha"])

    def test_the_census_is_not_its_own_consumer(self):
        """Обратная сторона: производитель себя не ввозит и находкой не станет."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        self.assertEqual(self.measure()["understated"], [])

    def test_a_census_that_imports_ITSELF_is_still_not_its_own_consumer(self):
        """Обратная сторона: ввоз себя (форма загрузки по пути) — не читатель.

        Дыра, найденная батареей: прежний тест сцены не строил вовсе — файл
        себя не ввозил, и снятие защиты не меняло ничего. Здесь ввоз есть, и
        без защиты перепись стала бы собственным невидимым потребителем.
        """
        _write(self.root, "spa_core/monitoring/alpha.py",
               "from spa_core.monitoring import alpha\n" + _CENSUS
               + "\n\ndef again(doc):\n    return alpha.format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["understated"], [])
        self.assertEqual(doc["counts"]["sites"], 0)

    def test_test_channel_is_counted_apart_and_declared_before_the_measure(self):
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "spa_core/tests/test_reader.py",
               "from spa_core.monitoring.alpha import format_report\n"
               "def check(doc):\n    return format_report(doc)\n")
        counts = self.measure()["counts"]
        self.assertEqual(counts["sites_test"], 1)
        self.assertEqual(counts["sites_code"], 0)

    def test_orchestrator_reader_is_named_apart_from_the_rest(self):
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, ORCHESTRATOR_READER,
               "from spa_core.monitoring.alpha import format_report\n"
               "def show(doc):\n    return format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(
            doc["counts"]["censuses_invisible_to_orchestrator_reader"], 1)
        self.assertTrue(doc["findings"][0]["reaches_orchestrator"])

    def test_a_consumer_that_is_not_the_orchestrator_reader_does_not_claim_to_be(self):
        """Обратная сторона предыдущего: поле не проставляется всем подряд."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/other.py",
               "from spa_core.monitoring.alpha import format_report\n"
               "def show(doc):\n    return format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(
            doc["counts"]["censuses_invisible_to_orchestrator_reader"], 0)
        self.assertFalse(doc["findings"][0]["reaches_orchestrator"])


class RendererIsMeasuredNotDeclaredTest(_Stand):

    def test_a_renderer_named_outside_the_ADR444_vocabulary_is_still_found(self):
        """Словарём `report`/`format_report` эта перепись названа не была бы."""
        source = _CENSUS.replace("format_report", "render")
        _write(self.root, "spa_core/monitoring/beta.py", source)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.beta import render\n"
               "def show(doc):\n    return render(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["understated"], ["beta"])
        self.assertEqual(doc["renderer_names"], {"render": 1})
        self.assertEqual([item["census"] for item in doc["vocabulary_missed"]],
                         ["beta"])

    def test_a_renderer_inside_the_vocabulary_is_not_reported_as_missed(self):
        """Обратная сторона: расхождение со словарём — находка, а не всегда."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        doc = self.measure()
        self.assertEqual(doc["vocabulary_missed"], [])
        self.assertEqual(doc["counts"]["vocabulary_missed"], 0)


class ThirdOutcomeTest(_Stand):

    def test_no_text_function_at_all_is_NOT_the_same_as_unmeasured(self):
        _write(self.root, "spa_core/monitoring/inline.py", _CENSUS_INLINE)
        doc = self.measure()
        kinds = [item["kind"] for item in doc["renderer_unresolved"]]
        self.assertEqual(kinds, [RENDERER_NONE_EXISTS])
        self.assertEqual(doc["counts"]["renderer_none_exists"], 1)
        self.assertEqual(doc["counts"]["renderer_not_printed"], 0)
        self.assertIn("ПО\nПОСТРОЕНИЮ".replace("\n", " "),
                      doc["renderer_unresolved"][0]["reason"])

    def test_a_text_function_the_producer_never_prints_is_the_RULE_BOUNDARY(self):
        """Обратная сторона: отдавать есть что, а печать этого не решает."""
        _write(self.root, "spa_core/monitoring/gamma.py", _CENSUS_UNPRINTED)
        doc = self.measure()
        item = doc["renderer_unresolved"][0]
        self.assertEqual(item["kind"], RENDERER_NOT_PRINTED)
        self.assertEqual(item["candidates"], ["lines_of"])
        self.assertEqual(doc["counts"]["renderer_not_printed"], 1)
        self.assertEqual(doc["counts"]["renderer_none_exists"], 0)

    def test_the_boundary_raises_the_UPPER_bound_and_says_so_with_a_number(self):
        _write(self.root, "spa_core/monitoring/gamma.py", _CENSUS_UNPRINTED)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.gamma import lines_of\n"
               "def show(doc):\n    return lines_of(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["understated_interval"], [0, 1])
        self.assertEqual(doc["counts"]["understated_upper_bound"], 1)
        self.assertEqual([hit["census"] for hit in doc["boundary_hits"]],
                         ["gamma"])

    def test_without_such_a_consumer_both_bounds_coincide(self):
        """Обратная сторона: интервал не раздувается сам по себе."""
        _write(self.root, "spa_core/monitoring/gamma.py", _CENSUS_UNPRINTED)
        doc = self.measure()
        self.assertEqual(doc["understated_interval"], [0, 0])
        self.assertEqual(doc["boundary_hits"], [])

    def test_absent_neighbour_is_UNMEASURED_and_never_zero_findings(self):
        saved = sys.modules.pop(NEIGHBOUR_CENSUS, None)
        sys.modules[NEIGHBOUR_CENSUS] = None        # ImportError при ввозе
        try:
            doc = self.measure()
        finally:
            if saved is not None:
                sys.modules[NEIGHBOUR_CENSUS] = saved
            else:
                sys.modules.pop(NEIGHBOUR_CENSUS, None)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn(NEIGHBOUR_CENSUS, doc["reason"])
        self.assertNotIn("understated", doc)

    def test_no_censuses_at_all_is_UNMEASURED_not_a_clean_pass(self):
        doc = self.measure()                        # пустое дерево
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("НЕ «невидимых потребителей нет»", doc["reason"])

    def test_an_unreadable_file_is_recorded_and_counted_not_skipped(self):
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/broken.py", "def show(:\n")
        doc = self.measure()
        self.assertEqual(doc["counts"]["files_unreadable"], 1)
        self.assertEqual([item["file"] for item in doc["unreadable"]],
                         ["scripts/broken.py"])


class ReverseSideTest(_Stand):

    def test_blanked_to_zero_is_measured_not_assumed(self):
        """Невидимый потребитель ПРИ НУЛЕ видимых у соседа — тяжелее занижения."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.alpha import format_report\n"
               "def show(doc):\n    return format_report(doc)\n")
        doc = self.measure()
        self.assertEqual(doc["blanked_to_zero"], ["alpha"])
        self.assertEqual(doc["counts"]["blanked_to_zero"], 1)

    def test_a_visible_caller_elsewhere_removes_the_census_from_blanked(self):
        """Обратная сторона: занижение и обнуление — разные утверждения."""
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        _write(self.root, "scripts/reader.py",
               "from spa_core.monitoring.alpha import format_report\n"
               "def show(doc):\n    return format_report(doc)\n")
        _write(self.root, "scripts/caller.py",
               "from spa_core.monitoring import alpha\n"
               "def go():\n    return alpha.run(root='.')\n")
        doc = self.measure()
        self.assertEqual(doc["understated"], ["alpha"])
        self.assertEqual(doc["blanked_to_zero"], [])

    def test_no_threshold_is_introduced_by_this_coordinate(self):
        _write(self.root, "spa_core/monitoring/alpha.py", _CENSUS)
        self.assertFalse(self.measure()["applied"])


class WiringTest(unittest.TestCase):
    """Проводка: координата обязана доехать до документа и до отчёта."""

    def test_measure_calls_the_coordinate_and_stores_it_under_its_own_key(self):
        """Проводка проверяется ФОРМОЙ ЗОВА, а не наличием имени в файле.

        Полный ``measure`` на живом дереве идёт 80 с и требует всего
        репозитория; на одноразовом стенде он отказывает по предпосылкам
        СОСЕДНИХ частей, а не своей. Поэтому проводка меряется разбором:
        зов ``invisible_consumer_scale(root)`` в теле ``measure`` и ключ, под
        которым его результат уезжает в документ. Снятие любого из двух
        краснит этот тест.
        """
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        measure_fn = next(node for node in tree.body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "measure")
        bound = {
            target.id
            for node in ast.walk(measure_fn)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "invisible_consumer_scale"
            and [ast.unparse(arg) for arg in node.value.args] == ["root"]
            for target in node.targets if isinstance(target, ast.Name)}
        self.assertTrue(bound, "measure() не зовёт invisible_consumer_scale(root)")
        returned = next(node.value for node in ast.walk(measure_fn)
                        if isinstance(node, ast.Return)
                        and isinstance(node.value, ast.Dict))
        carried = {ast.unparse(key): ast.unparse(value)
                   for key, value in zip(returned.keys, returned.values)
                   if key is not None}
        self.assertIn("'invisible_consumer_scale'", carried)
        self.assertIn(carried["'invisible_consumer_scale'"], bound)

    def test_the_report_prints_the_section_on_REAL_coordinate_output(self):
        """Живое чтение, не холостое: в отчёт уезжает настоящий замер стенда."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _full_stand(Path(tmp), reader=ORCHESTRATOR_READER)
            scale = invisible_consumer_scale(root)
        doc = {"rows": [], "unreadable": [], "classified": 0,
               "invisible_consumer_scale": scale}
        lines = [line for line in report(doc) if "МАСШТАБ НЕВИДИМОСТИ" in line]
        self.assertTrue(lines, "секция отчёта не напечатана вовсе")
        self.assertTrue(any("ИНТЕРВАЛ" in line for line in lines))
        self.assertTrue(any("ТРЕТИЙ ИСХОД" in line for line in lines))
        self.assertTrue(any("ОБРАТНАЯ СТОРОНА" in line for line in lines))
        self.assertTrue(any("alpha" in line for line in lines),
                        "находка напечатана без имени переписи")
        self.assertTrue(any(ORCHESTRATOR_READER in line for line in lines))

    def test_a_document_without_the_key_says_NOT_MEASURED_not_silence(self):
        lines = report({"rows": [], "unreadable": [], "classified": 0})
        section = [line for line in lines if "МАСШТАБ НЕВИДИМОСТИ" in line]
        self.assertEqual(len(section), 1)
        self.assertIn("НЕ ИЗМЕРЕН", section[0])

    def test_MEASURED_without_counts_is_its_own_outcome_not_empty_counts(self):
        """Инв. #17: «счётчиков нет» ≠ «счётчики нулевые» (регрессия #664)."""
        lines = report({"rows": [], "unreadable": [], "classified": 0,
                        "invisible_consumer_scale": {"status": "CRITICAL"}})
        section = [line for line in lines if "МАСШТАБ НЕВИДИМОСТИ" in line]
        self.assertEqual(len(section), 1)
        self.assertIn("НЕ нулевые", section[0])

    def test_the_neighbour_module_name_is_not_a_second_literal_copy(self):
        """Второй экземпляр имени соседа в этом файле был бы своим же классом."""
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            source.count('"spa_core.monitoring.census_consumer_census"'), 1,
            "имя соседа объявлено дважды — это вторая копия правила")

    def test_the_neighbour_still_answers_a_DIFFERENT_question(self):
        """Опора замера: сосед и вправду не видит ввоз отрисовщика."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "spa_core/monitoring/alpha.py", _CENSUS)
            _write(root, "scripts/reader.py",
                   "from spa_core.monitoring.alpha import format_report\n"
                   "def show(doc):\n    return format_report(doc)\n")
            callees = neighbour.find_callees(root)
            seen = neighbour.find_by_name_consumers(root, callees)
        self.assertEqual(sorted(callees), ["alpha"])
        self.assertEqual(seen, [], "сосед внезапно видит ввоз — опора замера ушла")


class ChannelConstantsTest(unittest.TestCase):

    def test_channel_labels_come_from_the_producer_not_from_here(self):
        self.assertEqual((CHANNEL_CODE, CHANNEL_TEST), ("code", "test"))


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
