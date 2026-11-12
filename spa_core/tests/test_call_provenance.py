"""Провенанс зова: кем позван прогон, собравший документ (заказ G36 п. 1, ADR-412).

Каждый тест здесь — положительный контроль наблюдённого дефекта, а не украшение:

* **замер 18.09** — два зова переписи через ДВЕ настоящие двери (рука цикла
  ``python3 -m`` против формы ступени моста ``<модуль>.run(root=…)``) дали
  документы, разошедшиеся ровно в ОДНОМ листе из 3942: ``generated_at``. То есть
  наблюдение, поставленное заказом G36 п. 1 на 25.09, звавшего различить не
  могло ни при каком состоянии системы;
* **дефект в этом же модуле, найденный первым прогоном через дверь
  ``python3 -c``**: ``sys.argv[0]`` равен строке ``"-c"``, ``Path("-c").resolve()``
  молча приставляет текущий каталог, и запись выходила ``measured: true`` с
  точкой входа ``"-c"`` — ненаблюдение в одежде наблюдения.

Разбор проверяется подставленным входом, а **настоящие двери — настоящими
подпроцессами**: инъекция проверяет только разбор своего же входа и о чтении
процесса не говорит ничего.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring.call_provenance import (  # noqa: E402
    call_provenance, describe,
)

MODULE = "spa_core.monitoring.call_provenance"


def _run(args, cwd=ROOT):
    return subprocess.run([sys.executable] + args, cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


class ParsingOfAGivenEntry(unittest.TestCase):
    """Разбор входа. Вход подставлен, и файлы на диске НАСТОЯЩИЕ.

    Настоящие они потому, что признак «дверь назвала существующий файл» и есть
    то, чем отличается наблюдение от строки — подставить сюда несуществующий
    путь значило бы проверить разбор в обход самой различающей проверки.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_g36_")
        self.tree = Path(self._tmp.name) / "tree"
        (self.tree / "pkg").mkdir(parents=True)
        self.inside = self.tree / "pkg" / "runner.py"
        self.inside.write_text("", encoding="utf-8")
        self.outside = Path(self._tmp.name) / "foreign_driver.py"
        self.outside.write_text("", encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_entry_inside_the_tree_is_recorded_relative_to_it(self):
        doc = call_provenance(tree_root=self.tree, main_file=str(self.inside),
                              argv=[str(self.inside)])
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["entry"], "pkg/runner.py")
        self.assertTrue(doc["inside_tree"])

    def test_entry_outside_the_tree_is_named_without_its_absolute_path(self):
        """Обратная сторона: чужая точка входа названа, но домашний каталог — нет.

        Абсолютный путь снаружи дерева ничего не добавляет к ответу (различающим
        является ИМЯ) и при этом уносит в артефакт домашний каталог владельца.
        """
        doc = call_provenance(tree_root=self.tree, main_file=str(self.outside),
                              argv=[str(self.outside)])
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["entry"], "foreign_driver.py")
        self.assertFalse(doc["inside_tree"])
        self.assertNotIn(str(self.outside.parent), json.dumps(doc))

    def test_doors_that_disagree_are_recorded_and_not_resolved_silently(self):
        """У подтверждающего чтения обязана быть своя частота ошибок."""
        doc = call_provenance(tree_root=self.tree, main_file=str(self.inside),
                              argv=[str(self.outside)])
        self.assertIs(doc["doors_agree"], False)
        self.assertEqual(doc["entry"], "pkg/runner.py")
        self.assertEqual(doc["entry_by_argv"], "foreign_driver.py")
        self.assertIn("двери спорят", describe(doc))

    def test_doors_that_agree_say_so_and_carry_no_second_entry(self):
        """Обратная сторона предыдущего: согласие не выдаётся за спор."""
        doc = call_provenance(tree_root=self.tree, main_file=str(self.inside),
                              argv=[str(self.inside)])
        self.assertIs(doc["doors_agree"], True)
        self.assertNotIn("entry_by_argv", doc)
        self.assertNotIn("двери спорят", describe(doc))

    def test_one_silent_door_is_named_not_hidden(self):
        doc = call_provenance(tree_root=self.tree, main_file=str(self.inside),
                              argv=[])
        self.assertTrue(doc["measured"])
        self.assertIsNone(doc["doors_agree"])
        self.assertEqual(doc["one_door_silent"], "sys.argv[0]")
        self.assertIn("одна дверь молчала", describe(doc))

    def test_a_door_naming_a_path_that_is_no_file_does_not_count_as_read(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ дефекта, найденного первым живым прогоном.

        ``"-c"`` — непустая строка, и без проверки существования она проходила
        весь путь до записи ``{"measured": true, "entry": "-c"}``.
        """
        doc = call_provenance(tree_root=self.tree, main_file=None, argv=["-c"])
        self.assertFalse(doc["measured"])
        self.assertIn("не назвали существующего файла", doc["reason"])
        self.assertNotIn("entry", doc)

    def test_the_third_outcome_is_not_dressed_as_a_name(self):
        """«Не измерено» обязано читаться как отсутствие, а не как имя звавшего."""
        doc = call_provenance(tree_root=self.tree, main_file=None, argv=[])
        self.assertFalse(doc["measured"])
        self.assertIn("НЕ ИЗМЕРЕНО", describe(doc))

    def test_a_document_without_the_field_is_not_a_document_with_it(self):
        self.assertIn("НЕ ЗАПИСАНО", describe(None))
        self.assertIn("НЕ ЗАПИСАНО", describe({}))


class RealDoorsOfARealProcess(unittest.TestCase):
    """Настоящие двери. Никакой инъекции — только подпроцессы."""

    def test_a_module_run_names_the_module_itself(self):
        proc = _run(["-m", MODULE])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["entry"], "spa_core/monitoring/call_provenance.py")
        self.assertEqual(doc["read_by"], "sys.modules['__main__'].__file__")

    def test_the_argv_door_is_wired_to_the_real_sys_argv(self):
        """Вторая дверь читает ИМЕННО `sys.argv`, и это проверяется у ЖИВОГО процесса.

        Дифференциальная батарея цикла #629 (независимая проверка унаследованной
        работы цикла #628): подмена `sys.argv` на `sys.orig_argv` в умолчании
        ВЫЖИВАЛА — все прочие проверки подают `argv` параметром, а настоящие
        двери спрашивают только про `read_by`, то есть про дверь-победителя.
        Между тем под `python3 -m <модуль>` у `sys.orig_argv` нулевым элементом
        стоит САМ ИНТЕРПРЕТАТОР, файл существующий: запись вышла бы «измерено»,
        двери молча разошлись бы, и подтверждающая дверь подтверждала бы не то.
        Прибор, у которого вторая дверь не проверена, не удваивает свидетельство —
        он удваивает доверие к одному чтению.
        """
        proc = _run(["-m", MODULE])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertIs(doc["doors_agree"], True,
                      f"двери разошлись у обычного зова `-m`: {doc}")
        self.assertNotIn("entry_by_argv", doc)
        self.assertNotIn(Path(sys.executable).name, json.dumps(doc),
                         "в записи оказался интерпретатор — дверь читает не sys.argv")

    def test_a_different_entry_point_yields_a_different_record(self):
        """РЕШАЮЩИЙ контроль: тот же зовомый, другой звавший — другая запись.

        Ровно этого свойства не было ни у одного из двух артефактов, которые
        заказ G36 п. 1 собирался сравнивать 25.09: замер 18.09 дал по ним 1
        разошедшийся лист из 3942, и тот — часы.
        """
        import tempfile
        with tempfile.TemporaryDirectory(prefix="spa_g36_drv_") as tmp:
            driver = Path(tmp) / "stage_like_driver.py"
            driver.write_text(
                "import json, sys\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from pathlib import Path\n"
                "from spa_core.monitoring.call_provenance import call_provenance\n"
                f"print(json.dumps(call_provenance(tree_root=Path({str(ROOT)!r}))))\n",
                encoding="utf-8")
            proc = _run([str(driver)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["entry"], "stage_like_driver.py")

        by_module = json.loads(_run(["-m", MODULE]).stdout)
        self.assertNotEqual(doc["entry"], by_module["entry"])

    def test_python_dash_c_is_the_third_outcome_through_the_real_door(self):
        """Тот же дефект, что выше, но через НАСТОЯЩУЮ дверь, а не подставленную."""
        proc = _run(["-c",
                     f"import json, sys; sys.path.insert(0, {str(ROOT)!r});"
                     " from pathlib import Path;"
                     " from spa_core.monitoring.call_provenance import call_provenance;"
                     f" print(json.dumps(call_provenance(tree_root=Path({str(ROOT)!r}))))"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertFalse(doc["measured"])
        self.assertIn("не назвали существующего файла", doc["reason"])


class TheProducersActuallyCarryIt(unittest.TestCase):
    """Проводка до документа — у ОБОИХ приборов, которых сравнивает заказ.

    Проверяется не наличие строки в исходнике, а ЗНАЧЕНИЕ в собранном документе,
    и значение сверяется с провенансом ЭТОГО процесса: константа, вписанная в
    производителя руками, такую проверку не прошла бы.
    """

    def _here(self):
        return call_provenance(tree_root=ROOT)

    def test_list_identity_census_doc_carries_the_caller(self):
        from spa_core.monitoring.list_identity_census import measure
        doc = measure(ROOT / "нет-такого-каталога", ROOT)
        self.assertEqual(doc["invoked_by"], self._here())

    def test_python_reader_clock_doors_doc_carries_the_caller(self):
        from spa_core.monitoring.python_reader_clock_doors import measure
        doc = measure(ROOT / "нет-такого-каталога", ROOT)
        self.assertEqual(doc["invoked_by"], self._here())

    def test_generated_by_cannot_stand_in_for_the_caller(self):
        """Сам дефект, замороженный тестом.

        ``generated_by`` — константа с именем производителя, и под ЛЮБЫМ звавшим
        она одна и та же. Пока она была единственным «провенансом» в документе,
        она читалась как ответ на вопрос, на который не отвечает.
        """
        from spa_core.monitoring import list_identity_census as census
        doc = census.measure(ROOT / "нет-такого-каталога", ROOT)
        self.assertEqual(doc["generated_by"], census.PRODUCER)
        # Прогон идёт под pytest, то есть звавший ЗАВЕДОМО не сам производитель.
        self.assertTrue(doc["invoked_by"]["measured"])
        self.assertNotEqual(doc["invoked_by"]["entry"], doc["generated_by"])

    def test_the_census_report_says_who_called_even_when_unmeasured(self):
        """Запись без читателя — это ADR-259; строка печатается до раннего возврата."""
        from spa_core.monitoring.list_identity_census import measure, report
        doc = measure(ROOT / "нет-такого-каталога", ROOT)
        lines = report(doc)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertTrue(any(line.startswith("[ЗВАВШИЙ]") for line in lines),
                        f"строки о звавшем нет вовсе: {lines[:4]}")

    def test_a_document_that_lost_the_field_is_reported_as_lost(self):
        """Обратная сторона: снятая проводка обязана быть ВИДНА, а не промолчать."""
        from spa_core.monitoring.list_identity_census import measure, report
        doc = measure(ROOT / "нет-такого-каталога", ROOT)
        doc.pop("invoked_by")
        line = next(l for l in report(doc) if l.startswith("[ЗВАВШИЙ]"))
        self.assertIn("НЕ ЗАПИСАНО", line)


# ---------------------------------------------------------------------------
# Вторая ось — КТО ЗАПУСТИЛ процесс (ADR-997, заказ G985 п. 1а)
# ---------------------------------------------------------------------------

from spa_core.monitoring.call_provenance import (  # noqa: E402
    LAUNCHER_SCHEMA, describe_launcher, launcher_provenance)

FLEET = "/bin/bash /Users/x/Documents/SPA_Claude/scripts/agent_template.sh decision_loop spa_core.monitoring.findings_bridge --run"
PY = "/Users/x/miniconda3/bin/python3 -m spa_core.monitoring.findings_bridge --run"


def chain_reader(table: dict[int, tuple[int, str]]):
    """Подставленная дверь `ps`: таблица pid → (ppid, command); нет строки — дверь молчит."""
    def read(pid: int):
        return table.get(pid)
    return read


class LauncherParsing(unittest.TestCase):
    """Разбор цепи. Цепь подставлена — чужую вживую не подстроишь; настоящая дверь ниже."""

    def test_fleet_job_is_two_hops_and_named_launchd_job(self):
        # Замер 12.11 живого флота: python ← agent_template.sh ← launchd (pid 1).
        doc = launcher_provenance(start_pid=2917, read_parent=chain_reader(
            {2917: (2571, PY), 2571: (1, FLEET)}))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["schema"], LAUNCHER_SCHEMA)
        self.assertEqual(doc["kind"], "launchd_job")
        self.assertEqual(doc["hops_to_launchd"], 2)
        self.assertTrue(doc["fleet_wrapper"])
        self.assertIn("agent_template.sh decision_loop", doc["launchd_child"])
        self.assertEqual([c["pid"] for c in doc["chain"]], [2917, 2571])

    def test_direct_child_of_launchd_is_a_launchd_job_in_one_hop(self):
        # Форма `director_server`: python — сам ребёнок launchd.
        doc = launcher_provenance(start_pid=2494, read_parent=chain_reader({2494: (1, PY)}))
        self.assertEqual((doc["kind"], doc["hops_to_launchd"], doc["fleet_wrapper"]),
                         ("launchd_job", 1, False))

    def test_hand_in_a_session_is_nested_and_the_chain_is_named(self):
        # Замер 12.11 сессии оркестратора: пять ходов до launchd.
        table = {100: (90, PY), 90: (80, "/bin/zsh -c …"), 80: (70, "~/.local/bin/claude -p …"),
                 70: (60, "python3 scripts/claude_run_with_timeout.py …"),
                 60: (1, "/bin/bash scripts/agent_orchestrator.sh")}
        doc = launcher_provenance(start_pid=100, read_parent=chain_reader(table))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["kind"], "nested")
        self.assertEqual(doc["hops_to_launchd"], 5)
        self.assertFalse(doc["fleet_wrapper"])
        self.assertEqual(doc["launchd_child"], "/bin/bash scripts/agent_orchestrator.sh")
        line = describe_launcher(doc)
        self.assertIn("вложенный прогон", line)
        self.assertIn("claude", line)

    def test_fleet_wrapper_started_by_a_shell_is_nested_not_a_job(self):
        # Рука набрала `bash scripts/agent_decision_loop.sh` из терминала: обёртка та же,
        # но её родитель — оболочка, а не launchd. Обёртка ≠ задание.
        table = {100: (90, PY), 90: (80, FLEET), 80: (70, "/bin/zsh -l"), 70: (1, "Terminal")}
        doc = launcher_provenance(start_pid=100, read_parent=chain_reader(table))
        self.assertEqual(doc["kind"], "nested")
        self.assertEqual(doc["hops_to_launchd"], 4)

    def test_two_hops_through_a_shell_is_nested_the_wrapper_is_the_discriminator(self):
        # Два хода — но над процессом оболочка, а не обёртка флота: `python ← zsh ← launchd`.
        # Глубина одна и та же, что у задания флота; различает ОБЁРТКА, не число ходов.
        doc = launcher_provenance(start_pid=100, read_parent=chain_reader(
            {100: (90, PY), 90: (1, "/bin/zsh -l")}))
        self.assertEqual((doc["kind"], doc["hops_to_launchd"], doc["fleet_wrapper"]),
                         ("nested", 2, False))

    def test_silent_door_is_unmeasured_with_the_pid_named(self):
        doc = launcher_provenance(start_pid=100, read_parent=chain_reader({100: (90, PY)}))
        self.assertFalse(doc["measured"])
        self.assertNotIn("kind", doc)
        self.assertIn("pid 90", doc["reason"])
        self.assertEqual(len(doc["chain"]), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", describe_launcher(doc))

    def test_cycle_in_the_chain_is_unmeasured_not_nested(self):
        doc = launcher_provenance(start_pid=100, read_parent=chain_reader(
            {100: (90, PY), 90: (100, "/bin/zsh")}))
        self.assertFalse(doc["measured"])
        self.assertIn("зациклилась", doc["reason"])

    def test_chain_longer_than_max_hops_is_unmeasured(self):
        table = {i: (i - 1, "p") for i in range(3, 40)}
        doc = launcher_provenance(start_pid=39, read_parent=chain_reader(table), max_hops=5)
        self.assertFalse(doc["measured"])
        self.assertIn("длиннее 5", doc["reason"])

    def test_tree_root_and_home_are_folded_out_of_commands(self):
        cmd = f"/bin/bash {ROOT}/scripts/agent_template.sh x y"
        doc = launcher_provenance(start_pid=5, read_parent=chain_reader({5: (1, cmd)}), tree_root=ROOT)
        self.assertEqual(doc["launchd_child"], "/bin/bash scripts/agent_template.sh x y")
        self.assertNotIn(str(Path.home()), doc["launchd_child"])

    def test_absent_record_is_not_a_record(self):
        self.assertIn("НЕ ЗАПИСАНО", describe_launcher(None))
        self.assertIn("НЕ ЗАПИСАНО", describe_launcher({}))

    def test_launchd_job_line_names_the_child(self):
        doc = launcher_provenance(start_pid=2917, read_parent=chain_reader(
            {2917: (2571, PY), 2571: (1, FLEET)}))
        line = describe_launcher(doc)
        self.assertIn("прямое задание launchd", line)
        self.assertIn("agent_template.sh decision_loop", line)


class LauncherRealDoor(unittest.TestCase):
    """Положительный контроль НАСТОЯЩЕЙ двери: отдельный процесс читает свою `ps`."""

    def test_a_real_process_reaches_launchd_and_the_last_link_has_ppid_one(self):
        code = ("import json; from spa_core.monitoring.call_provenance import launcher_provenance; "
                "print(json.dumps(launcher_provenance()))")
        res = _run(["-c", code])
        self.assertEqual(res.returncode, 0, res.stderr)
        doc = json.loads(res.stdout.strip().splitlines()[-1])
        self.assertEqual(doc["schema"], LAUNCHER_SCHEMA)
        self.assertTrue(doc["measured"], doc.get("reason"))
        self.assertIn(doc["kind"], ("launchd_job", "nested"))
        self.assertGreaterEqual(doc["hops_to_launchd"], 1)
        self.assertEqual(doc["chain"][-1]["ppid"], 1)
        # Ребёнок pytest — НЕ задание флота: pytest стоит между ним и launchd.
        self.assertEqual(doc["kind"], "nested")


if __name__ == "__main__":
    unittest.main()
