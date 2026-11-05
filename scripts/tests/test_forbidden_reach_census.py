#!/usr/bin/env python3
"""scripts/tests/test_forbidden_reach_census.py — сторож переписи G107 п. 3.

Авария, которую воспроизводит набор, — НЕ случившаяся, а ВОЗМОЖНАЯ, и именно
поэтому её надо было измерить: сторож запрещённых импортов
(``scripts/lint_forbidden_imports.py``, инв. #3 и #4) объявляет область пятью
каталогами и ищет в них ПРЯМОЙ импорт. Файл рантайм-домена, ввозящий
``requests`` или ``anthropic`` через помощника из `spa_core/utils/`, проходит
мимо него ни одной формой — и цена этой односторонности есть пропущенное
нарушение инварианта, а не неточность вердикта.

Пары «в обе стороны» обязательны у КАЖДОГО звена: находка обязана исчезать,
когда звено порвано, и звено названо в имени теста. Проверка, которая только
зеленеет на целом контуре, не отличима от проверки, не смотрящей никуда.

Литеральных дат и литеральных pid в наборе нет ПО ПОСТРОЕНИЮ: единственный
вход меры — путь дерева.
"""
# LLM_FORBIDDEN
import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_SCRIPTS_DIR)
for _p in (_REPO, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forbidden_reach_census as census  # noqa: E402
import lint_forbidden_imports as linter  # noqa: E402
from spa_core.monitoring.membership_reach_census import build_graph  # noqa: E402


def _write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))
    return path


def _scene(root, watcher_body, helper_body, extra=None):
    """Одноразовое дерево: ВСЕ объявленные домены + помощник вне них.

    Все пять каталогов обязательны: отсутствие домена сторож объявляет третьим
    исходом, и сцена без них мерила бы «не измерено», а не предмет.
    """
    _write(root, "spa_core/__init__.py", "")
    for domain in linter.DOMAINS:
        _write(root, f"{domain}/__init__.py", "")
    _write(root, "spa_core/monitoring/watcher.py", watcher_body)
    _write(root, "spa_core/helpers/__init__.py", "")
    _write(root, "spa_core/helpers/net.py", helper_body)
    for rel, body in (extra or {}).items():
        _write(root, rel, body)


_WATCHER_IMPORTS_HELPER = """
from spa_core.helpers.net import fetch

def run():
    return fetch()
"""

_HELPER_IMPORTS_REQUESTS = """
import requests

def fetch():
    return requests.get("https://example.invalid")
"""


class HelperRoadIsFound(unittest.TestCase):
    """Ось ЗАНИЖЕНИЯ: что сторож не видит ни одной формой."""

    def test_library_through_a_helper_is_found_while_the_guard_stays_silent(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            # сам сторож на этом дереве ЧИСТ — это вторая сторона находки
            own, own_unmeasured, own_scanned = linter.scan_tree(root)
            self.assertEqual(own, [], "сторож не должен видеть дорогу через помощника")
            self.assertEqual(own_unmeasured, [])
            self.assertGreater(own_scanned, 0)

            self.assertEqual(doc["counts"][census.VIA_HELPER], 1, doc["counts"])
            finding = doc["findings"][0]
            self.assertEqual(finding["path"], "spa_core/monitoring/watcher.py")
            self.assertEqual(finding["key"], "requests")
            self.assertIn("spa_core/helpers/net.py", finding["chain"])
            self.assertEqual(census.verdict(doc), "НАХОДКА")

    def test_direct_import_is_not_counted_as_a_helper_road(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, "import requests\n", _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.DIRECT], 1, doc["counts"])
            self.assertEqual(doc["counts"][census.VIA_HELPER], 0, doc["counts"])

    def test_broken_link_the_helper_edge(self):
        """Звено 1 порвано: файл домена помощника больше не ввозит."""
        with tempfile.TemporaryDirectory() as root:
            _scene(root, "def run():\n    return None\n", _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 0, doc["counts"])
            self.assertEqual(census.verdict(doc), "НИЖНЯЯ ГРАНИЦА")

    def test_broken_link_the_forbidden_import_itself(self):
        """Звено 2 порвано: помощник больше не ввозит запрещённую библиотеку."""
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, "def fetch():\n    return 1\n")
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 0, doc["counts"])

    def test_road_longer_than_the_limit_is_a_third_outcome_not_absence(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER,
                   "from spa_core.helpers.deep import fetch\n",
                   extra={"spa_core/helpers/deep.py": _HELPER_IMPORTS_REQUESTS})
            near = census.measure(root, max_depth=2)
            self.assertEqual(near["counts"][census.VIA_HELPER], 1, near["counts"])
            far = census.measure(root, max_depth=1)
            self.assertEqual(far["counts"][census.VIA_HELPER], 0, far["counts"])
            self.assertEqual(far["counts"][census.BEYOND], 1, far["counts"])
            self.assertNotEqual(far["counts"][census.NOT_REACHED],
                                near["counts"][census.NOT_REACHED] + 1,
                                "дорога за пределом не имеет права стать «дороги нет»")


class ExecutionAxisDiscriminates(unittest.TestCase):
    """Ось ЗАВЫШЕНИЯ: дорога импорта есть достижимость, а не исполнение."""

    def test_module_level_contour_is_executed_by_the_import_itself(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["findings"][0]["execution"], census.EXECUTED)
            self.assertEqual(doc["execution_counts"][census.EXECUTED], 1)
            self.assertEqual(doc["execution_counts"][census.DEFERRED], 0)

    def test_guarded_forbidden_import_is_deferred_not_executed(self):
        guarded = """
        try:
            import requests
        except ImportError:
            requests = None

        def fetch():
            return requests
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, guarded)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 1, doc["counts"])
            self.assertEqual(doc["findings"][0]["execution"], census.DEFERRED)

    def test_function_local_helper_edge_is_deferred_not_executed(self):
        deferred_edge = """
        def run():
            from spa_core.helpers.net import fetch
            return fetch()
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, deferred_edge, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 1,
                             "дорога остаётся дорогой — меняется только ось исполнения")
            self.assertEqual(doc["findings"][0]["execution"], census.DEFERRED)

    def test_type_checking_edge_is_deferred_not_executed(self):
        type_only = """
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from spa_core.helpers.net import fetch

        def run():
            return None
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, type_only, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 1)
            self.assertEqual(doc["findings"][0]["execution"], census.DEFERRED)

    def test_execution_road_longer_than_the_limit_is_deferred_not_executed(self):
        """Верхняя граница оси исполнения — своя, и она НЕ следует из дороги.

        Дыру нашёл мутационный замер: сцены, где обе дороги укладываются в
        предел, равно зелены и при `1 <= hops <= max_depth`, и при одном
        `hops is not None`. Здесь дороги РАЗНОЙ длины: достижимость — одна
        дуга (импорт внутри функции), исполнение — три (кружной путь
        верхнего уровня).
        """
        watcher = """
        from spa_core.helpers.a import step

        def run():
            from spa_core.helpers.net import fetch
            return fetch(), step()
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, watcher, _HELPER_IMPORTS_REQUESTS, extra={
                "spa_core/helpers/a.py": "from spa_core.helpers.b import step\n",
                "spa_core/helpers/b.py": "from spa_core.helpers.net import fetch\n\ndef step():\n    return fetch\n",
            })
            doc = census.measure(root, max_depth=2)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 1, doc["counts"])
            self.assertEqual(doc["findings"][0]["distance"], 1)
            self.assertEqual(doc["findings"][0]["execution"], census.DEFERRED)
            # и с пределом, покрывающим кружной путь, тот же контур ИСПОЛНЯЕТСЯ
            wide = census.measure(root, max_depth=3)
            self.assertEqual(wide["findings"][0]["execution"], census.EXECUTED)

    def test_zero_hops_in_the_execution_graph_is_unreachable_by_construction(self):
        """Нижняя граница `1 <= hops` равносильна: до неё дорога не доходит.

        Ноль дуг в графе исполнения означает, что файл ввозит библиотеку САМ, —
        а тогда и в полном графе расстояние ноль, и пара ушла в
        `brought_in_directly` раньше, чем ось исполнения была спрошена.
        Равносильность доказана ТЕСТОМ предпосылки, а не рассуждением.
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, "import requests\n\nfrom spa_core.helpers.net import fetch\n",
                   _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts"][census.DIRECT], 1, doc["counts"])
            self.assertEqual(doc["findings"], [],
                             "пара, ввезённая напрямую, оси исполнения не достигает")

    def test_second_kind_of_graph_really_differs_from_the_first(self):
        """Контроль самого второго рода графа, а не только его вердикта."""
        guarded_edge = """
        try:
            from spa_core.helpers.net import fetch
        except ImportError:
            fetch = None
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, guarded_edge, _HELPER_IMPORTS_REQUESTS)
            full = build_graph(root)
            execed = build_graph(root, module_level_only=True)
            self.assertFalse(full["module_level_only"])
            self.assertTrue(execed["module_level_only"])
            watcher = "spa_core/monitoring/watcher.py"
            self.assertIn("spa_core/helpers/net.py", full["edges"][watcher])
            self.assertNotIn("spa_core/helpers/net.py", execed["edges"][watcher])

    def test_default_graph_keeps_the_guarded_edge(self):
        """Умолчание нового параметра не меняет прежнего поведения соседа."""
        guarded_edge = """
        try:
            from spa_core.helpers.net import fetch
        except ImportError:
            fetch = None
        """
        with tempfile.TemporaryDirectory() as root:
            _scene(root, guarded_edge, _HELPER_IMPORTS_REQUESTS)
            self.assertEqual(build_graph(root)["edges"],
                             build_graph(root, module_level_only=False)["edges"])


class LaunchAxisIsAskedButNotOverclaimed(unittest.TestCase):
    """Вторая дверь LLM-сторожа: ЗАПУСК бинаря, а не импорт SDK."""

    _LAUNCHER = """
    import subprocess

    def ask(prompt):
        return subprocess.run(["claude", "-p", prompt], capture_output=True)
    """

    def test_a_reachable_launcher_is_found_through_a_helper(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, self._LAUNCHER)
            doc = census.measure(root)
            self.assertEqual(doc["launch"]["counts"][census.VIA_HELPER], 1,
                             doc["launch"]["counts"])
            self.assertEqual(doc["launch"]["findings"][0]["path"],
                             "spa_core/monitoring/watcher.py")
            self.assertEqual(census.verdict(doc), "НАХОДКА")

    def test_launch_axis_declares_that_execution_was_not_asked(self):
        """Молчание об исполнении обязано быть НАЗВАНО, а не выглядеть нулём."""
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, self._LAUNCHER)
            doc = census.measure(root)
            self.assertEqual(doc["launch"]["findings"][0]["execution"],
                             census.LAUNCH_EXEC_NOT_ASKED)
            self.assertIn(census.LAUNCH_EXEC_NOT_ASKED, census.format_report(doc))

    def test_no_launcher_in_the_tree_is_a_declared_zero(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, "def fetch():\n    return 1\n")
            doc = census.measure(root)
            self.assertEqual(doc["launch"]["seed_files"], [])
            self.assertEqual(doc["launch"]["counts"][census.VIA_HELPER], 0)
            self.assertIn("[ЗАПУСК БИНАРЯ LLM] семян 0", census.format_report(doc))


class ClosedListAndThirdOutcome(unittest.TestCase):

    def test_outcomes_sum_equals_population(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["counts_sum"], doc["population"])
            self.assertEqual(sorted(doc["counts"]), sorted(census.OUTCOMES))

    def test_zero_population_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "spa_core/__init__.py", "")
            for domain in linter.DOMAINS:
                os.makedirs(os.path.join(root, domain), exist_ok=True)
            _write(root, "tool.py", "x = 1\n")
            doc = census.measure(root)
            self.assertEqual(doc["population"], 0)
            self.assertEqual(census.verdict(doc), "НЕ ИЗМЕРЕНО")
            # Вердикта НЕ ДОСТАТОЧНО: третий исход обязан нести НАЗВАННУЮ
            # причину (инв. #17). Дыру нашёл мутационный замер — без этой
            # проверки снятие причины оставалось незамеченным, потому что
            # вердикт держался на втором признаке.
            self.assertTrue(any("население равно нулю" in line
                                for line in doc["unmeasured"]), doc["unmeasured"])

    def test_unparsable_domain_file_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            _write(root, "spa_core/monitoring/broken.py", "def (\n")
            doc = census.measure(root)
            self.assertEqual(census.verdict(doc), "НЕ ИЗМЕРЕНО")
            self.assertTrue(any("broken.py" in line for line in doc["unmeasured"]),
                            doc["unmeasured"])

    def test_parity_with_the_guard_can_go_red(self):
        """Контроль обязан УМЕТЬ краснеть, иначе он украшение."""
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            real = linter.scan_tree

            def lying(tree_root, *a, **kw):
                found, unmeasured, scanned = real(tree_root, *a, **kw)
                extra = linter.Finding("spa_core/monitoring/watcher.py", "numpy", 1,
                                       "import")
                return found + [extra], unmeasured, scanned

            linter.scan_tree = lying
            try:
                doc = census.measure(root)
            finally:
                linter.scan_tree = real
            self.assertFalse(doc["parity"]["equal"])
            self.assertEqual(census.verdict(doc), "НЕ ИЗМЕРЕНО")
            self.assertTrue(any("паритет" in line for line in doc["unmeasured"]))

    def test_disagreeing_walks_are_named_not_swallowed(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            real = linter.scan_tree

            def fewer(tree_root, *a, **kw):
                found, unmeasured, scanned = real(tree_root, *a, **kw)
                return found, unmeasured, scanned - 1

            linter.scan_tree = fewer
            try:
                doc = census.measure(root)
            finally:
                linter.scan_tree = real
            self.assertFalse(doc["parity"]["walks_agree"])
            self.assertEqual(census.verdict(doc), "НЕ ИЗМЕРЕНО")


class RuleIsNotCopied(unittest.TestCase):
    """Что запрещено и где — решает сторож, а не перепись."""

    def test_library_list_comes_from_the_guard(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER,
                   "import brandnewsdk\n\ndef fetch():\n    return 1\n")
            doc_before = census.measure(root)
            self.assertEqual(doc_before["counts"][census.VIA_HELPER], 0)
            linter.FORBIDDEN["brandnewsdk"] = linter.CLASS_LLM
            try:
                doc_after = census.measure(root)
            finally:
                del linter.FORBIDDEN["brandnewsdk"]
            self.assertEqual(doc_after["counts"][census.VIA_HELPER], 1,
                             "перепись обязана читать перечень у сторожа, а не свой")
            self.assertIn("brandnewsdk", doc_after["libraries"])

    def test_domain_list_comes_from_the_guard(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root)
            self.assertEqual(doc["domains"], list(linter.DOMAINS))


class OfficeStepIsTheReader(unittest.TestCase):
    """Проводка меряется ВЫЗОВОМ: один импорт ради правила вызовом не является."""

    @staticmethod
    def _calls_of_census(source: str) -> list[str]:
        tree = ast.parse(source)
        bound: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "forbidden_reach_census"):
                for alias in node.names:
                    bound.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("forbidden_reach_census"):
                        bound.add(alias.asname or alias.name.split(".")[-1])
        called: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
                if name in bound:
                    called.append(name)
        return called

    def test_office_step_calls_the_census(self):
        path = os.path.join(_REPO, "scripts", "consume_office_reports.py")
        with open(path, encoding="utf-8") as fh:
            calls = self._calls_of_census(fh.read())
        self.assertTrue(calls, "шаг 0-офис обязан ЗВАТЬ перепись, а не только ввозить")

    def test_a_mere_import_is_not_a_call(self):
        """Обратная сторона той же меры — иначе храповик считал бы импорт чтением."""
        source = "from forbidden_reach_census import measure\n"
        self.assertEqual(self._calls_of_census(source), [])


class ExitCodesAreThree(unittest.TestCase):

    def _run(self, root, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(_REPO, "scripts",
                                          "forbidden_reach_census.py"),
             "--root", root, *extra],
            capture_output=True, text=True)

    def test_finding_is_one_and_clean_is_zero_and_unmeasured_is_two(self):
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            self.assertEqual(self._run(root).returncode, 1)
        with tempfile.TemporaryDirectory() as root:
            _scene(root, "def run():\n    return 1\n", "def fetch():\n    return 1\n")
            self.assertEqual(self._run(root).returncode, 0)
        with tempfile.TemporaryDirectory() as root:
            out = self._run(os.path.join(root, "no-such-tree"))
            self.assertEqual(out.returncode, 2)
            self.assertIn("НЕ ИЗМЕРЕНО", out.stdout)

    def test_json_output_is_machine_readable(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            out = self._run(root, "--json")
            doc = json.loads(out.stdout)
            self.assertEqual(doc["counts"][census.VIA_HELPER], 1)


if __name__ == "__main__":
    unittest.main()


# ───────────────────────────────── ТАКТ (ADR-927) ─────────────────────────────
#
# Такт стои́т на ОДНОМ условии: ключ покрывает все входы, от которых вердикт
# может измениться. Поэтому у каждого класса входа здесь ПОЛОЖИТЕЛЬНЫЙ
# КОНТРОЛЬ — мутация этого входа ОБЯЗАНА сменить ключ. Класс без своего
# контроля был бы украшением: ключ, не замечающий входа, переиспользует
# устаревший вердикт МОЛЧА, и это fail-OPEN, то есть ровно то, против чего
# написан инв. #17.

def _tact_scene(root):
    """Сцена такта: предмет переписи + каталог `data/`, без которого такта нет."""
    _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    return root


class TactKeyCoversEveryInputItClaims(unittest.TestCase):
    """Шесть классов входа — шесть мутаций, каждая обязана сменить ключ."""

    def _key(self, root):
        key, _material, unmeasured = census.tact_key(root)
        self.assertEqual(unmeasured, [], "ключ сцены обязан быть ПОЛНЫМ")
        return key

    def test_a_byte_in_any_tree_file_changes_the_key(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            before = self._key(root)
            _write(root, "spa_core/helpers/net.py",
                   _HELPER_IMPORTS_REQUESTS + "\n# один байт больше\n")
            self.assertNotEqual(before, self._key(root))

    def test_an_added_py_file_changes_the_key(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            before = self._key(root)
            _write(root, "spa_core/helpers/second.py", "x = 1\n")
            self.assertNotEqual(before, self._key(root))

    def test_a_removed_py_file_changes_the_key(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            _write(root, "spa_core/helpers/second.py", "x = 1\n")
            before = self._key(root)
            os.remove(os.path.join(root, "spa_core/helpers/second.py"))
            self.assertNotEqual(before, self._key(root))

    def test_an_empty_top_level_directory_changes_the_key(self):
        """Дверь, которую ключ по одним БАЙТАМ .py не закрыл бы.

        `_top_level_names` читает ЗАПИСИ КАТАЛОГА, а не только файлы `.py`:
        пустой каталог верхнего уровня с именем сторонней библиотеки
        переводит её имя из `outside_the_tree` в `unresolved`, то есть МЕНЯЕТ
        вердикт оси имени, не тронув ни одного байта `.py`. Найдено чтением
        исходника до доставки (цикл #1040).
        """
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            before = self._key(root)
            os.makedirs(os.path.join(root, "requests"))
            self.assertNotEqual(
                before, self._key(root),
                "пустой каталог верхнего уровня меняет ось ИМЕНИ — ключ обязан это видеть")

    def test_the_declared_depth_changes_the_key(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            self.assertNotEqual(census.tact_key(root, max_depth=3)[0],
                                census.tact_key(root, max_depth=2)[0])

    def test_the_measured_tree_path_changes_the_key(self):
        with tempfile.TemporaryDirectory() as one:
            with tempfile.TemporaryDirectory() as two:
                _tact_scene(one)
                _tact_scene(two)
                self.assertNotEqual(self._key(one), self._key(two),
                                    "ответ несёт абсолютный repo_root — он вход")

    def test_the_loaded_rule_bytes_are_in_the_key(self):
        """Правило приезжает из дерева ПРИБОРА, а не из мерянного дерева."""
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            _key, material, _u = census.tact_key(root)
            labels = {name for name, _digest in material["rule_modules"]}
            self.assertIn("lint_forbidden_imports.py", labels)
            self.assertIn("membership_reach_census.py", labels)
            self.assertIn("forbidden_reach_census.py", labels)

    def test_the_interpreter_is_in_the_key(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            _key, material, _u = census.tact_key(root)
            self.assertEqual(material["interpreter"], sys.version)

    def test_every_declared_class_is_present_in_the_material(self):
        """Паритет с объявлением: перечень классов и материал не расходятся."""
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            _key, material, _u = census.tact_key(root)
            self.assertEqual(sorted(material), sorted(census.KEY_CLASSES))


class TactReuseNeverChangesTheAnswer(unittest.TestCase):

    def test_a_key_hit_returns_the_same_answer_with_the_named_moment(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            first = census.measure(root, now="2026-01-01T00:00:00Z")
            self.assertFalse(first["tact"]["reused"])
            second = census.measure(root, now="2026-02-02T00:00:00Z")
            self.assertTrue(second["tact"]["reused"])
            # момент — ПЕРВОГО замера, а не второго зова
            self.assertEqual(second["tact"]["measured_at"], "2026-01-01T00:00:00Z")
            self.assertEqual({k: v for k, v in first.items() if k != "tact"},
                             {k: v for k, v in second.items() if k != "tact"})
            self.assertEqual(census.verdict(first), census.verdict(second))

    def test_a_changed_tree_is_measured_again_not_reused(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            census.measure(root, now="2026-01-01T00:00:00Z")
            _write(root, "spa_core/helpers/net.py", "def fetch():\n    return None\n")
            again = census.measure(root, now="2026-03-03T00:00:00Z")
            self.assertFalse(again["tact"]["reused"],
                             "дерево изменилось — переиспользовать ЗАПРЕЩЕНО")
            self.assertEqual(again["tact"]["measured_at"], "2026-03-03T00:00:00Z")

    def test_the_answer_differs_after_the_tree_changed(self):
        """Контроль самого контроля: если бы такт врал, вердикт бы не сдвинулся."""
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            with_road = census.measure(root, now="2026-01-01T00:00:00Z")
            self.assertEqual(census.verdict(with_road), "НАХОДКА")
            _write(root, "spa_core/helpers/net.py", "def fetch():\n    return None\n")
            without = census.measure(root, now="2026-03-03T00:00:00Z")
            self.assertEqual(census.verdict(without), "НИЖНЯЯ ГРАНИЦА")

    def test_cache_off_never_reads_and_never_writes(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            doc = census.measure(root, cache=False, now="2026-01-01T00:00:00Z")
            self.assertFalse(doc["tact"]["reused"])
            self.assertIsNone(doc["tact"]["cache"])
            self.assertFalse(os.path.exists(os.path.join(root, census.CACHE_REL)))

    def test_no_data_dir_means_no_tact_at_all(self):
        """Сцена в `tempfile` без `data/` обязана мерить, а не читать чужой кеш."""
        with tempfile.TemporaryDirectory() as root:
            _scene(root, _WATCHER_IMPORTS_HELPER, _HELPER_IMPORTS_REQUESTS)
            doc = census.measure(root, now="2026-01-01T00:00:00Z")
            self.assertFalse(doc["tact"]["reused"])
            self.assertIsNone(doc["tact"]["cache"])
            self.assertIn("нет", doc["tact"]["miss"])


class TactMissIsNeverCleanAndNeverSilent(unittest.TestCase):

    def test_a_corrupt_cache_is_a_miss_not_an_answer(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            with open(os.path.join(root, census.CACHE_REL), "w",
                      encoding="utf-8") as fh:
                fh.write("{не json")
            doc = census.measure(root, now="2026-01-01T00:00:00Z")
            self.assertFalse(doc["tact"]["reused"])
            self.assertIn("не прочитан", doc["tact"]["miss"])
            self.assertEqual(census.verdict(doc), "НАХОДКА")

    def test_a_cache_of_the_wrong_shape_is_a_miss(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            with open(os.path.join(root, census.CACHE_REL), "w",
                      encoding="utf-8") as fh:
                fh.write('{"key": "x"}')
            doc = census.measure(root, now="2026-01-01T00:00:00Z")
            self.assertFalse(doc["tact"]["reused"])
            self.assertIn("формы", doc["tact"]["miss"])

    def test_a_foreign_key_in_the_cache_is_a_miss(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            census.measure(root, now="2026-01-01T00:00:00Z")
            path = os.path.join(root, census.CACHE_REL)
            with open(path, encoding="utf-8") as fh:
                stored = json.load(fh)
            stored["key"] = "0" * 64
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(stored, fh)
            doc = census.measure(root, now="2026-04-04T00:00:00Z")
            self.assertFalse(doc["tact"]["reused"])
            self.assertIn("НЕ совпал", doc["tact"]["miss"])

    def test_an_incomplete_key_refuses_to_reuse(self):
        """Ключ НЕ ПОЛОН ⇒ мерить. Переиспользовать по неполному ключу — fail-OPEN."""
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            census.measure(root, now="2026-01-01T00:00:00Z")
            real = census.tact_key

            def incomplete(repo_root, max_depth=census.MAX_DEPTH):
                key, material, _u = real(repo_root, max_depth)
                return key, material, ["вход не прочитан — проба"]

            census.tact_key = incomplete
            try:
                doc = census.measure(root, now="2026-05-05T00:00:00Z")
            finally:
                census.tact_key = real
            self.assertFalse(doc["tact"]["reused"])
            self.assertIn("НЕ ПОЛОН", doc["tact"]["miss"])
            self.assertEqual(doc["tact"]["measured_at"], "2026-05-05T00:00:00Z")

    def test_the_report_names_the_moment_of_the_reused_measurement(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            census.measure(root, now="2026-01-01T00:00:00Z")
            reused = census.measure(root, now="2026-02-02T00:00:00Z")
            report = census.format_report(reused)
            self.assertIn("ПЕРЕИСПОЛЬЗОВАН", report)
            self.assertIn("2026-01-01T00:00:00Z", report)
            fresh = census.measure(root, cache=False, now="2026-02-02T00:00:00Z")
            self.assertIn("ИЗМЕРЕНО сейчас", census.format_report(fresh))

    def test_a_document_without_a_tact_block_is_named_not_assumed_fresh(self):
        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            doc = census.measure(root, cache=False, now="2026-01-01T00:00:00Z")
            doc.pop("tact")
            self.assertIn("[ТАКТ] НЕ ИЗМЕРЕН", census.format_report(doc))


class TactReadsNothingTheKeyDoesNotCover(unittest.TestCase):
    """Сторож ПОЛНОТЫ ключа: новый вход-файл обязан покраснить эту проверку.

    Контроль отвечает на вопрос «читает ли замер что-нибудь, чего ключ не
    покрывает», а не «перечислены ли классы». Перечень классов можно дописать
    словом; этот тест дописать словом нельзя — он смотрит на НАСТОЯЩИЕ чтения
    живого замера на сцене.
    """

    def test_every_path_the_measurement_reads_is_covered_by_the_key(self):
        import builtins
        import pathlib as _pathlib

        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            real_open = builtins.open
            real_read_text = _pathlib.Path.read_text
            real_read_bytes = _pathlib.Path.read_bytes
            seen: list[str] = []

            def note(path):
                try:
                    seen.append(os.path.abspath(str(path)))
                except Exception:  # noqa: BLE001
                    pass

            def open_spy(file, *a, **kw):
                note(file)
                return real_open(file, *a, **kw)

            def read_text_spy(self, *a, **kw):
                note(self)
                return real_read_text(self, *a, **kw)

            def read_bytes_spy(self, *a, **kw):
                note(self)
                return real_read_bytes(self, *a, **kw)

            builtins.open = open_spy
            _pathlib.Path.read_text = read_text_spy
            _pathlib.Path.read_bytes = read_bytes_spy
            try:
                census.measure(root, cache=False, now="2026-01-01T00:00:00Z")
            finally:
                builtins.open = real_open
                _pathlib.Path.read_text = real_read_text
                _pathlib.Path.read_bytes = real_read_bytes

            rule_files = {path for _label, path in census._rule_module_files()}
            uncovered = []
            for path in set(seen):
                if path in rule_files:
                    continue
                if path.endswith(".py"):
                    continue          # байты .py — класс `py_files`
                if not path.startswith(os.path.abspath(root) + os.sep):
                    continue          # вне мерянного дерева и не правило
                uncovered.append(path)
            self.assertEqual(
                sorted(uncovered), [],
                "замер прочитал путь, которого ключ НЕ покрывает: такт "
                "переиспользовал бы устаревший вердикт молча")

    def test_the_spy_itself_can_go_red(self):
        """Положительный контроль сторожа: подложенное чтение обязано найтись."""
        import pathlib as _pathlib

        with tempfile.TemporaryDirectory() as root:
            _tact_scene(root)
            smuggled = os.path.join(root, "data", "unkeyed_input.txt")
            with open(smuggled, "w", encoding="utf-8") as fh:
                fh.write("вход, которого нет в ключе\n")
            real_read_text = _pathlib.Path.read_text
            seen: list[str] = []

            def spy(self, *a, **kw):
                seen.append(os.path.abspath(str(self)))
                return real_read_text(self, *a, **kw)

            _pathlib.Path.read_text = spy
            try:
                _pathlib.Path(smuggled).read_text(encoding="utf-8")
            finally:
                _pathlib.Path.read_text = real_read_text
            uncovered = [p for p in seen
                         if not p.endswith(".py")
                         and p.startswith(os.path.abspath(root) + os.sep)]
            self.assertEqual(uncovered, [smuggled],
                             "сторож обязан УМЕТЬ краснеть, иначе он украшение")
