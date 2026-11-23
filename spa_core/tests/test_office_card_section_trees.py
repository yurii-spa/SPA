"""ADR-1081 — раздел офиса «критерии открытых карточек» собран из ДВУХ деревьев.

Каждый тест здесь — положительный контроль НАСТОЯЩЕГО состояния, измеренного
2026-11-23 (цикл #1227) на прод-трекере, откуда и ходит обязательный шаг 0-офис:

* открытых карточек с объявленной пробой — **54**;
* у **47** из них проба объявляет `data_dir` входом, а `audit` этот вход НЕ
  ПЕРЕДАВАЛ ВООБЩЕ ⇒ 47 строк раздела собирались из двух деревьев (статусы из
  прод-дерева, числа из дерева МОДУЛЯ), и ни одна об этом не говорила;
* в живом выводе это читалось как «НЕ ИЗМЕРЕНО: проблема не найдена в
  `<worktree>/data/problems.json`» — то есть «не измерено» было свойством
  ПРОВОДКИ, а не предмета;
* единственная строка «🟩 КРИТЕРИЙ ВЫПОЛНЕН, а карточка открыта» касалась
  карточки, которая на `origin/main` имеет статус `done`.

Родня прямая: ADR-1080 («читатель не сказал, о КАКОМ трекере ответ»). Здесь
носителей ДВА в ОДНОЙ строке, поэтому вопрос другой: не «о чьём дереве вердикт»,
а «из скольких деревьев он собран».

Время и личность процесса здесь не предмет — литеральных дат и pid в файле нет.
Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import os
import pathlib
import tempfile
import shutil
import unittest

from spa_core.monitoring import card_acceptance as ca

_REPO = pathlib.Path(__file__).resolve().parents[2]
_OFFICE = _REPO / "scripts" / "consume_office_reports.py"


def _scene(root: pathlib.Path, pid: str) -> pathlib.Path:
    """Одноразовое дерево: карточка с объявленной пробой + своё `data/`."""
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (tracker / "inbox-scene.md").write_text(
        "---\n"
        "trackerStatus:\n  type: inbox\n"
        "title: сцена\n"
        "status: new\n"
        f"acceptance_probe: problem_absent:{pid}\n"
        "---\n\nсцена\n", encoding="utf-8")
    (root / "data" / "problems.json").write_text(
        json.dumps({"problems": {pid: {"problem_id": pid, "status": "CLOSED",
                                       "consecutive_absences": 3, "rca": "сцена"}}},
                   ensure_ascii=False), encoding="utf-8")
    return tracker


class SceneBase(unittest.TestCase):
    PID = "adr1081.guard.closed"

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="adr1081_guard_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.a = self.tmp / "treeA"
        self.b = self.tmp / "treeB"
        self.tracker_a = _scene(self.a, self.PID)
        _scene(self.b, self.PID)

    def audit(self, **kw):
        return ca.audit(str(self.tracker_a), origin_readthrough=False, **kw)


class OneTreeIsAFinding(SceneBase):
    """Сцена-РАЗЛИЧИТЕЛЬ №1: статусы и числа из ОДНОГО дерева ⇒ находка ЕСТЬ.

    Без неё любая мутация, глушащая находки целиком, выжила бы: «находок нет»
    выглядит как «чисто» (урок циклов #1202/#1217 — мутация без различающей
    сцены выживает).
    """

    def test_trees_are_reported_as_one(self):
        res = self.audit(data_dir=str(self.a / "data"))
        self.assertEqual(res["trees"]["state"], ca.TREES_SAME, res["trees"])

    def test_the_satisfied_criterion_is_a_finding(self):
        res = self.audit(data_dir=str(self.a / "data"))
        self.assertEqual(res["counts"]["satisfied_but_open_one_tree"], 1)
        self.assertTrue(any("🟩" in ln for ln in ca.report_lines(res)))

    def test_the_exit_code_calls_it_a_finding(self):
        rc = ca.main(["--tracker-dir", str(self.tracker_a),
                      "--data-dir", str(self.a / "data")])
        self.assertEqual(rc, 1)

    def test_the_tally_of_findings_by_tree_is_printed(self):
        # Дыра покрытия, найденная мутацией M23 второго круга: раскладу находок
        # по деревьям не предъявлял требований НИ ОДИН тест, и снятие его из
        # строки проходило молча. Читатель без расклада не отличит «находок нет»
        # от «все находки ушли в расхождение деревьев».
        text = "\n".join(ca.report_lines(self.audit(data_dir=str(self.a / "data"))))
        self.assertIn("находки: одно дерево 1", text)
        self.assertIn("ДВА дерева 0", text)
        self.assertIn("дерево чисел не измерено 0", text)

    def test_the_agreement_is_said_out_loud(self):
        # Совпадение ПЕЧАТАЕТСЯ — тот же порядок, что у ADR-1080: молчание о
        # совпадении неотличимо от молчания о том, что никто не мерил.
        text = "\n".join(ca.report_lines(self.audit(data_dir=str(self.a / "data"))))
        self.assertIn("ОДНОГО дерева", text)


class TwoTreesAreNotAFinding(SceneBase):
    """Сцена-РАЗЛИЧИТЕЛЬ №2: числа из ДРУГОГО дерева ⇒ находки НЕТ, оба корня названы.

    Это и есть авария 23.11: вердикт о числах дерева A под статусом из дерева B
    читался как «перемерить и закрыть».
    """

    def test_the_section_says_there_are_two(self):
        res = self.audit(data_dir=str(self.b / "data"))
        self.assertEqual(res["trees"]["state"], ca.TREES_SPLIT, res["trees"])

    def test_the_verdict_is_not_announced_as_a_finding(self):
        res = self.audit(data_dir=str(self.b / "data"))
        self.assertEqual(res["counts"]["satisfied_but_open_one_tree"], 0)
        self.assertEqual(res["counts"]["satisfied_but_open_split"], 1)
        self.assertNotIn("🟩", "\n".join(ca.report_lines(res)))

    def test_the_total_is_not_lost(self):
        # Итог ДЕЛИТСЯ, а не заменяется: «находок стало меньше» иначе читалось бы
        # как улучшение (инв. #16 наизнанку).
        res = self.audit(data_dir=str(self.b / "data"))
        self.assertEqual(res["counts"]["satisfied_but_open"], 1)

    def test_both_roots_are_named_by_name(self):
        text = "\n".join(ca.report_lines(self.audit(data_dir=str(self.b / "data"))))
        self.assertIn(str(self.a), text)
        self.assertIn(str(self.b), text)

    def test_the_exit_code_is_fail_closed(self):
        rc = ca.main(["--tracker-dir", str(self.tracker_a),
                      "--data-dir", str(self.b / "data")])
        self.assertEqual(rc, 2, "вердикт из двух деревьев обязан дать код 2, не 1 и не 0")


class ASilentCallerReadsTheModuleTree(SceneBase):
    """Сцена-РАЗЛИЧИТЕЛЬ №3: вход не назван ⇒ читается дерево МОДУЛЯ, и это сказано.

    Умолчание не подставляется догадкой: «не назвал» и «двери нет» — разные
    состояния (урок мутации M10 цикла #1226).
    """

    def test_the_row_is_marked_as_module_tree(self):
        res = self.audit()
        self.assertEqual(res["counts"]["numbers_module"], 1)
        self.assertEqual(res["counts"]["numbers_named"], 0)

    def test_it_is_not_a_finding_about_a_card_from_another_tree(self):
        res = self.audit()
        self.assertEqual(res["trees"]["state"], ca.TREES_SPLIT)
        self.assertEqual(res["counts"]["satisfied_but_open_one_tree"], 0)

    def test_the_header_says_the_numbers_tree_was_not_named(self):
        head = ca.report_lines(self.audit())[0]
        self.assertIn("статусы:", head)
        self.assertIn("числа:", head)
        self.assertIn("НЕ НАЗВАНЫ", head)


class TheHeaderNamesBothCarriers(SceneBase):
    """Приёмка карточки дословно: раздел называет, из какого дерева статусы и из какого числа."""

    def test_both_trees_are_in_the_first_line(self):
        head = ca.report_lines(self.audit(data_dir=str(self.a / "data")))[0]
        self.assertIn(str(self.tracker_a), head)
        self.assertIn(str(self.a / "data"), head)


class ThirdOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» никогда не выдаётся за «совпало»."""

    def test_an_undeclared_door_is_neither_same_nor_split(self):
        row = {"numbers_tree": {"state": ca.NUMBERS_UNMEASURED, "root": None,
                                "reason": "двери нет"}}
        rt = ca.row_trees(row, statuses_root="/tmp/x")
        self.assertEqual(rt["state"], ca.ROW_UNMEASURED,
                         "проба без двери к числам может прочитать ЛЮБОЕ дерево — "
                         "ни «совпало», ни «разошлось»")
        self.assertIn("двери нет", rt["reason"])

    def test_a_measured_divergence_is_split(self):
        row = {"numbers_tree": {"state": ca.NUMBERS_NAMED, "root": "/tmp/other"}}
        rt = ca.row_trees(row, statuses_root="/tmp/mine")
        self.assertEqual(rt["state"], ca.ROW_SPLIT)
        self.assertIn("/tmp/other", rt["reason"])
        self.assertIn("/tmp/mine", rt["reason"])

    def test_a_nameless_statuses_tree_is_unmeasured(self):
        res = {"tracker_dir": "", "rows": [], "counts": {}}
        trees = ca.section_trees(res)
        self.assertEqual(trees["state"], ca.TREES_UNMEASURED)
        self.assertTrue(trees["reason"])

    def test_rows_without_any_measured_numbers_tree_are_unmeasured_not_clean(self):
        res = {"tracker_dir": "/tmp/t/nimbalyst-local/tracker",
               "rows": [{"open": True,
                         "numbers_tree": {"state": ca.NUMBERS_UNMEASURED,
                                          "root": None, "reason": "двери нет"}}],
               "counts": {}}
        trees = ca.section_trees(res)
        self.assertEqual(trees["state"], ca.TREES_UNMEASURED)
        self.assertIn("НЕ ИЗВЕСТНО НИЧЕГО", trees["reason"])

    def test_a_report_of_the_old_shape_is_unmeasured_not_clean(self):
        # Капкан ADR-248: ключа в отчёте нет не потому, что замер пуст. Отчёт,
        # произведённый читателем ДО ADR-1081, блока `trees` не несёт вовсе — и
        # молчание о нём читалось бы как «деревья совпали».
        lines = ca.section_tree_lines({"counts": {}})
        self.assertTrue(lines)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("СТАРОГО образца", lines[0])
        self.assertIn("НЕ «деревья совпали»", lines[0])

    def test_the_numbers_tree_of_a_probe_without_the_door(self):
        # `adapter_status_live_apy` дверь `data_dir` не объявляет — замер #1227.
        nt = ca.probe_numbers_tree("adapter_status_live_apy", data_dir="/tmp/d")
        self.assertEqual(nt["state"], ca.NUMBERS_UNMEASURED)
        self.assertTrue(nt["reason"])

    def test_the_numbers_tree_of_a_probe_with_the_door(self):
        nt = ca.probe_numbers_tree("problem_absent", data_dir="/tmp/tree/data")
        self.assertEqual(nt["state"], ca.NUMBERS_NAMED)
        self.assertEqual(nt["root"], "/tmp/tree")


class AnUnmeasuredNumbersTreeDoesNotKillTheFinding(unittest.TestCase):
    """Цена ПЕРВОЙ редакции ADR-1081, пойманная замером, а не рассуждением.

    Первая редакция склеила «дерево чисел НЕ ИЗМЕРЕНО» со «деревья РАЗОШЛИСЬ» и
    глушила находку в обоих случаях. На этом покраснели ДВА положительных
    контроля ADR-208 (`test_open_card_with_satisfied_criterion_is_the_finding`,
    `test_exit_codes_are_fail_closed`): их проба — структурная сверка, НИКАКОГО
    дерева она не читает, разойтись по деревьям не может, и «находки нет» было бы
    молчаливым снятием основного предмета модуля ПОД ВИДОМ усиления (инв. #16
    наизнанку).

    Поэтому исходов три, и этот класс — положительный контроль третьего.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="adr1081_nodoor_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        tracker = self.tmp / "nimbalyst-local" / "tracker"
        tracker.mkdir(parents=True)
        (tracker / "inbox-structural.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\ntitle: структурная\n"
            "status: new\nacceptance_probe: _adr1081_no_door\n---\n\nсцена\n",
            encoding="utf-8")
        self.tracker = tracker
        ca.PROBES["_adr1081_no_door"] = lambda _a: (ca.SATISFIED, "выполнено")
        self.addCleanup(ca.PROBES.pop, "_adr1081_no_door", None)

    def test_the_finding_survives_and_the_ignorance_is_named(self):
        res = ca.audit(str(self.tracker), data_dir=str(self.tmp / "data"),
                       origin_readthrough=False)
        self.assertEqual(res["counts"]["satisfied_but_open_tree_unmeasured"], 1)
        self.assertEqual(res["counts"]["satisfied_but_open_split"], 0)
        text = "\n".join(ca.report_lines(res))
        self.assertIn("🟩", text, "находка ADR-208 снята под видом усиления")
        self.assertIn("дерево ЧИСЕЛ НЕ ИЗМЕРЕНО", text,
                      "незнание не названо — молчание неотличимо от ответа")

    def test_the_exit_code_still_calls_it_a_finding(self):
        rc = ca.main(["--tracker-dir", str(self.tracker),
                      "--data-dir", str(self.tmp / "data")])
        self.assertEqual(rc, 1)


class TheWiringIsMeasuredByASTNotBySubstring(unittest.TestCase):
    """Проводка меряется разбором, а не подстрокой.

    Урок цикла #1217 дословно: моя же проба искала имя двери ПОДСТРОКОЙ и зачла
    упоминание в ДОКСТРИНГЕ за зов. Дефект был У МЕРКИ, не у кода.
    """

    @staticmethod
    def _calls_named(tree: ast.AST, func_tail: str) -> list:
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == func_tail:
                out.append(node)
        return out

    def test_the_office_step_hands_the_numbers_tree_to_audit(self):
        tree = ast.parse(_OFFICE.read_text(encoding="utf-8"))
        calls = self._calls_named(tree, "audit")
        self.assertTrue(calls, "шаг 0-офис не зовёт `audit` вовсе — проводки нет")
        wired = [c for c in calls
                 if any(k.arg == "data_dir" for k in c.keywords)]
        self.assertEqual(
            len(wired), len(calls),
            "зов `audit` без входа `data_dir`: статусы взяты из одного дерева, "
            "числа — из дерева модуля, и строка раздела склеит два носителя")

    def test_both_reads_of_the_office_step_come_from_ONE_root(self):
        # Присутствие входа — НЕ то же, что ОДНО дерево: зов
        # `audit(_tracker, data_dir=<своё дерево>)` проверку «вход есть» прошёл бы,
        # а два носителя оставил бы на месте. Поэтому мерится ПРОИСХОЖДЕНИЕ
        # обоих аргументов: имя, от значения которого они произведены (поиск до
        # неподвижной точки — порядок § «injected-clock» из
        # `.claude/rules/deployment.md`).
        tree = ast.parse(_OFFICE.read_text(encoding="utf-8"))
        # ИМЕНА МОДУЛЕЙ из пересечения выбрасываются, и это не косметика: первая
        # редакция этой мерки объявила M2 («офис передаёт СВОЁ дерево») УБИТОЙ
        # по общему имени `os`, которое есть в обоих аргументах у ЛЮБОГО зова
        # `os.path.join`. Мутация ВЫЖИЛА, и дефект был У МЕРКИ, а не у кода
        # (дословный урок цикла #1217).
        imported: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {(a.asname or a.name).split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {(a.asname or a.name) for a in node.names}
        origins: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        origins.setdefault(t.id, set()).update(names)
        def roots_of(expr) -> set:
            seen = {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}
            while True:
                grown = set(seen)
                for n in list(seen):
                    grown |= origins.get(n, set())
                if grown == seen:
                    return seen - imported
                seen = grown
        calls = self._calls_named(tree, "audit")
        self.assertTrue(calls, "шаг 0-офис не зовёт `audit` вовсе")
        for c in calls:
            statuses = roots_of(c.args[0]) if c.args else set()
            kw = next((k for k in c.keywords if k.arg == "data_dir"), None)
            self.assertIsNotNone(kw, "зов `audit` без входа `data_dir`")
            numbers = roots_of(kw.value)
            self.assertTrue(
                statuses & numbers,
                f"статусы произведены от {sorted(statuses)}, числа — от "
                f"{sorted(numbers)}: общего корня НЕТ, значит раздел по-прежнему "
                f"собирается из двух деревьев")

    def test_audit_hands_the_numbers_tree_to_run_probe(self):
        src = (_REPO / "spa_core" / "monitoring" / "card_acceptance.py").read_text(
            encoding="utf-8")
        fn = next((n for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name == "audit"), None)
        self.assertIsNotNone(fn, "функции `audit` в модуле нет")
        self.assertIn("data_dir", [a.arg for a in fn.args.kwonlyargs],
                      "`audit` не объявляет дерево ЧИСЕЛ входом")
        calls = self._calls_named(fn, "run_probe")
        self.assertTrue(calls, "`audit` не зовёт `run_probe`")
        for c in calls:
            self.assertIn("data_dir", [k.arg for k in c.keywords],
                          "вход объявлен, но до пробы НЕ ДОХОДИТ — «половина "
                          "инъекции», только у дерева, а не у часов")


class TheProbeIsRegisteredWithControlsBothWays(unittest.TestCase):
    """Проба карточки существует в реестре и даёт `satisfied` на этом дереве."""

    def test_the_probe_is_in_the_registry(self):
        self.assertIn("office_card_section_names_both_trees", ca.PROBES)

    def test_the_probe_is_satisfied_on_this_tree(self):
        verdict, detail = ca.run_probe("office_card_section_names_both_trees")
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_the_probe_refuses_when_the_input_does_not_reach_the_probe(self):
        # Обратная половина контроля: отними у `audit` вход — и проба обязана
        # сказать `not_satisfied` с НАЗВАННОЙ причиной, а не `unmeasured` и не
        # `satisfied`. Подменяем ЕДИНСТВЕННУЮ дверь и возвращаем её обратно
        # (`.claude/rules/deployment.md` § «СОСЕД ПО ПРОЦЕССУ»: подмена, пережившая
        # сцену, — дефект, даже когда она зелена).
        real = ca.audit

        def deaf_audit(tracker_dir=None, *, origin_readthrough=True,
                       ref=ca.ORIGIN_REF, repo_root=None):
            return real(tracker_dir, origin_readthrough=origin_readthrough,
                        ref=ref, repo_root=repo_root)

        ca.audit = deaf_audit
        try:
            verdict, detail = ca.run_probe("office_card_section_names_both_trees")
        finally:
            ca.audit = real
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("data_dir", detail)
        self.assertIs(ca.audit, real, "подмена двери пережила сцену")


if __name__ == "__main__":
    unittest.main()
