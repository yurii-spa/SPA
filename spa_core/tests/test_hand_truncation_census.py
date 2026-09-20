"""Перепись «кто режет вывод своей рукой»: сторож прибора, у каждой проверки обратная сторона.

Заказ **G50 п. 2** приказа владельца «Portfolio CIO», решение — ADR-428.

## Что здесь проверяется и почему именно так

Прибор делит зовущих ВТОРОЙ проводки (``subprocess.run(...,
capture_output=True)``) по двум осям: режет ли зовущий своей рукой и читает ли
обрезанное как ПЕРЕЧЕНЬ. Ошибиться он может в обе стороны, и опасна одна:
назвать читателя перечня «прозой» — такой вывод молчалив, и находка исчезнет,
не покраснев. Поэтому у каждой сцены есть обратная, а дерево сцен собрано из
ИСХОДНИКОВ, а не из заранее разобранных словарей: правило читает AST, и
проверять его на подделанных данных значило бы проверять свою же фикстуру.

**Положительный контроль — НАСТОЯЩИЙ вред, а не классификация строк:**
подпроцесс печатает 200 строк, зовущий режет их своей рукой до 20 и
спрашивает членство. Ответ «такой строки нет» ЛОЖЕН при живой строке — вред
воспроизведён, и только после этого имеет смысл спрашивать, красит ли его
перепись.

Литеральных дат здесь нет: часы прибора инъектируются параметром ``now``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import hand_truncation_census as census
from spa_core.monitoring import truncated_input_census as neighbour

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Неподвижные часы: прибор берёт их параметром.
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

_IMPORT = "import subprocess\n\n\n"


def _tree(tmp: Path, callers: dict) -> Path:
    """Крошечное дерево населения: ``spa_core/`` + ``scripts/`` и файлы-зовущие."""
    root = tmp / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    (root / "scripts").mkdir()
    for rel, src in callers.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    return root


def _rows(doc: dict, module: str) -> list:
    return [r for r in doc["rows"] if r["module"] == module]


def _verdict(tmp: Path, src: str) -> dict:
    """Вердикт единственного вызова в сцене."""
    root = _tree(tmp, {"scripts/scene.py": _IMPORT + src})
    doc = census.measure(root, now=_NOW)
    rows = _rows(doc, "scripts/scene.py")
    assert len(rows) == 1, f"ожидался один вызов, получено {len(rows)}: {rows}"
    return rows[0]


# ------------------------------------------------- ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: вред

class HandCutOfAListReallyLies(unittest.TestCase):
    """Вред воспроизводится настоящим прогоном, а не утверждается словами."""

    def test_a_hand_cut_list_answers_absent_about_a_present_line(self):
        printer = ("import sys\n"
                   "for i in range(200):\n"
                   "    sys.stdout.write('row-%03d\\n' % i)\n")
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "printer.py"
            script.write_text(printer, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(script)],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0)
            full = proc.stdout.splitlines()
            self.assertIn("row-150", full)

            # Своя рука: срез ПО ЭЛЕМЕНТАМ, дальше вопрос о членстве.
            cut = full[:20]
            self.assertNotIn("row-150", cut)
            # Односторонность: срез может только УБРАТЬ, добавить — никогда.
            self.assertTrue(set(cut) <= set(full))
            # Обратная сторона того же прогона: хвостовой срез уносит ДРУГОЕ,
            # но направление вреда то же — «нет» при живом «есть».
            tail = full[-20:]
            self.assertNotIn("row-000", tail)
            self.assertIn("row-000", full)

    def test_the_census_paints_that_very_shape_red(self):
        src = ("def gather():\n"
               "    proc = subprocess.run(['x'], capture_output=True, text=True)\n"
               "    rows = proc.stdout.splitlines()[:20]\n"
               "    for row in rows:\n"
               "        print(row)\n"
               "    return 'row-150' in rows\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual(row["cut_unit"], census.UNIT_ITEMS)
        self.assertEqual(row["cut_side"], census.SIDE_TAIL)


# ------------------------------------------------------------ сторона разреза

class CutSideIsAFieldNotAnAssumption(unittest.TestCase):
    """У своей руки сторона разреза своя у каждого вызова."""

    def _side(self, expr: str) -> str:
        node = ast.parse(expr, mode="eval").body
        assert isinstance(node, ast.Subscript), expr
        cut = node.slice
        assert isinstance(cut, ast.Slice), expr
        return census.cut_side(cut)

    def test_negative_lower_takes_the_head(self):
        self.assertEqual(self._side("x[-300:]"), census.SIDE_HEAD)

    def test_positive_lower_also_takes_the_head(self):
        self.assertEqual(self._side("x[3:]"), census.SIDE_HEAD)

    def test_upper_only_takes_the_tail(self):
        """Обратная сторона: ровно то чтение, что безопасно у общей проводки."""
        self.assertEqual(self._side("x[:2000]"), census.SIDE_TAIL)

    def test_both_bounds_take_both_ends(self):
        self.assertEqual(self._side("x[10:20]"), census.SIDE_WINDOW)

    def test_an_empty_slice_is_not_a_cut_at_all(self):
        node = ast.parse("x[:]", mode="eval").body
        assert isinstance(node, ast.Subscript)
        cut = node.slice
        assert isinstance(cut, ast.Slice)
        self.assertFalse(census.is_cut(cut, {}))


class CutIsToldFromParsingByTheFormOfItsBound(unittest.TestCase):
    """Бюджет против разбора потока: решает форма ГРАНИЦЫ, не намерение."""

    def _cut(self, expr: str, consts=None) -> bool:
        node = ast.parse(expr, mode="eval").body
        assert isinstance(node, ast.Subscript), expr
        cut = node.slice
        assert isinstance(cut, ast.Slice), expr
        return census.is_cut(cut, consts or {})

    def test_a_literal_bound_is_a_budget(self):
        self.assertTrue(self._cut("x[:80]"))

    def test_a_module_constant_bound_is_a_budget(self):
        self.assertTrue(self._cut("x[:KEEP]", {"KEEP": 2000}))

    def test_computed_bounds_are_parsing_not_truncation(self):
        """Обратная сторона: ``buf[nl + 1:nl + 1 + size]`` материала не теряет."""
        self.assertFalse(self._cut("buf[nl + 1:nl + 1 + size]"))

    def test_an_unknown_name_bound_is_not_taken_for_a_budget(self):
        self.assertFalse(self._cut("x[:limit]"))

    def test_parse_slices_are_counted_and_not_classified(self):
        src = ("def read(buf_size):\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    buf = proc.stdout\n"
               "    pos = 0\n"
               "    body = buf[pos:pos + buf_size]\n"
               "    return body\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(len(doc["parse_slices"]), 1)
        self.assertEqual(_rows(doc, "scripts/scene.py")[0]["verdict"],
                         census.CLASS_ESCAPED)


# ------------------------------------------------------- перечень против прозы

class ListReadIsToldFromProse(unittest.TestCase):
    """Опасна одна ошибка: назвать читателя перечня прозой."""

    def test_iterating_the_cut_is_a_list_read(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    for row in proc.stdout.splitlines()[:5]:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["consumption"], census.READ_LIST)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)

    def test_membership_over_the_cut_is_a_list_read(self):
        src = ("def f(name):\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    rows = proc.stdout.splitlines()[:5]\n"
               "    return name in rows\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)

    def test_a_cut_folded_into_a_message_is_prose(self):
        """Обратная сторона: человек видит меньше, но ВЕРДИКТ не врёт."""
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    return False, (proc.stderr or '').strip()[-300:]\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_PROSE)

    def test_a_comprehension_that_feeds_join_is_prose(self):
        """Обход РАДИ строки перечнем не является: ответа из него не берут."""
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    subjects = proc.stdout.splitlines()\n"
               "    return '\\n'.join('- ' + s for s in subjects[:80])\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_PROSE)
        self.assertEqual(row["cut_unit"], census.UNIT_ITEMS)

    def test_no_cut_at_all_is_not_this_instruments_subject(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    for row in proc.stdout.splitlines():\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_NO_CUT)


class DoorMakesTheCutHonest(unittest.TestCase):
    """Дверь различает «перечень кончился» и «перечень обрезали»."""

    def test_the_named_door_turns_a_finding_into_guarded(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    rows = proc.stdout.splitlines()[:5]\n"
               "    if output_truncated(proc.stdout):\n"
               "        return None\n"
               "    for row in rows:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_GUARDED)
        self.assertEqual(row["door"], neighbour.DOOR_NAMED)

    def test_the_count_door_also_counts(self):
        src = ("def f(declared):\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    rows = proc.stdout.splitlines()[:5]\n"
               "    if len(rows) != declared:\n"
               "        return None\n"
               "    for row in rows:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_GUARDED)
        self.assertEqual(row["door"], neighbour.DOOR_COUNT)

    def test_the_door_rule_is_imported_and_not_copied(self):
        """Заказ G50 п. 3 в лоб: второй копии правила двери здесь быть не может."""
        source = Path(census.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assigned = {t.id for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    for t in node.targets if isinstance(t, ast.Name)}
        self.assertNotIn("DOOR_NAMED", assigned)
        self.assertNotIn("DOOR_COUNT", assigned)
        self.assertIs(census.DOOR_NAMED, neighbour.DOOR_NAMED)
        self.assertIs(census.has_door, neighbour.has_door)

    def test_the_provenance_rule_is_imported_and_not_copied(self):
        """Заказ G51 п. 3: правило двери спрашивает происхождение ⇒ копия одна.

        Держи их порознь — и сужение у соседа обошло бы эту перепись молча,
        а разошлись бы они ровно в ту сторону, в какую ошибается непочиненная
        копия.
        """
        tree = ast.parse(Path(census.__file__).read_text(encoding="utf-8"))
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("_derives_from", defined)
        self.assertNotIn("derived_names", defined)
        self.assertNotIn("_target_names", defined)
        self.assertIs(census._derives_from, neighbour.derives_from)
        self.assertIs(census.derived_names, neighbour.derived_names)
        self.assertIs(census._SPLITTERS, neighbour.SPLITTERS)


# ----------------------------------------------- происхождение, а не совпадение

class OnlyTheOutputCounts(unittest.TestCase):
    """Срез засчитывается, только если срезаемое ПРОИСХОДИТ от вывода."""

    def test_a_slice_of_the_command_is_not_a_cut_of_the_output(self):
        src = ("def f(args):\n"
               "    proc = subprocess.run(args, capture_output=True)\n"
               "    if proc.returncode:\n"
               "        raise RuntimeError(' '.join(args[:2]))\n"
               "    print(proc.stdout)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["cut_side"], "")
        self.assertEqual(row["verdict"], census.CLASS_NO_CUT)

    def test_a_container_is_not_a_derivation(self):
        """Правило `.claude/rules/deployment.md`: `doc = {...}` выводом не делает."""
        known = {"proc"}
        expr = ast.parse("{'out': proc.stdout}", mode="eval").body
        self.assertFalse(census._derives_from(expr, known))
        direct = ast.parse("proc.stdout", mode="eval").body
        self.assertTrue(census._derives_from(direct, known))

    def test_derivation_follows_splitting_and_loading(self):
        known = {"proc"}
        for expr in ("proc.stdout.splitlines()", "json.loads(proc.stdout)",
                     "(proc.stderr or proc.stdout)", "proc.stdout[:5]"):
            node = ast.parse(expr, mode="eval").body
            self.assertTrue(census._derives_from(node, known), expr)


class PopulationIsDeclaredAndBounded(unittest.TestCase):
    """Кто входит в население — и кто объявлен ВНЕ разбора."""

    def test_a_run_without_capture_is_not_in_the_population(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'])\n"
               "    return proc.returncode\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(_rows(doc, "scripts/scene.py"), [])
        self.assertEqual(doc["uncaptured_sites"], 1)

    def test_capture_output_false_is_read_as_the_word_says(self):
        """Обратная сторона: ключ ЕСТЬ, а значение говорит «не захвачено»."""
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=False)\n"
               "    return proc.returncode\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(_rows(doc, "scripts/scene.py"), [])
        self.assertEqual(doc["uncaptured_sites"], 1)

    def test_a_foreign_module_named_run_is_not_the_runner(self):
        """Обратная сторона ввоза: `mylib.run(...)` проводкой не является."""
        src = ("import mylib\n\n\n"
               "def f():\n"
               "    proc = mylib.run(['x'], capture_output=True)\n"
               "    for row in proc.stdout.splitlines()[:5]:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(_rows(doc, "scripts/scene.py"), [])

    def test_popen_is_named_out_of_scope_and_counted(self):
        src = ("def f():\n"
               "    proc = subprocess.Popen(['x'], stdout=subprocess.PIPE)\n"
               "    return proc\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(_rows(doc, "scripts/scene.py"), [])
        self.assertEqual(len(doc["popen_sites"]), 1)

    def test_check_output_captures_by_construction(self):
        src = ("def f():\n"
               "    out = subprocess.check_output(['x'])\n"
               "    for row in out.splitlines()[:5]:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)

    def test_an_alias_import_is_seen_and_a_comment_is_not(self):
        seen = census.runner_aliases(ast.parse("import subprocess as sp\n"))
        self.assertEqual(seen, {"sp"})
        mentioned = census.runner_aliases(ast.parse("# subprocess.run is used\n"))
        self.assertEqual(mentioned, set())

    def test_a_local_wrapper_of_depth_one_is_followed(self):
        src = ("def _git(args):\n"
               "    proc = subprocess.run(args, capture_output=True)\n"
               "    return proc.stdout\n"
               "\n\n"
               "def caller():\n"
               "    out = _git(['git', 'worktree', 'list'])\n"
               "    for row in out.splitlines()[:5]:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/scene.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        rows = {r["enclosing"]: r for r in _rows(doc, "scripts/scene.py")}
        self.assertEqual(rows["caller"]["verdict"], census.CLASS_SILENT)
        self.assertEqual(rows["caller"]["via_wrapper"], "_git")
        # Обратная сторона: сама обёртка вывод НЕ режет и находкой не является.
        self.assertEqual(rows["_git"]["verdict"], census.CLASS_ESCAPED)


# --------------------------------------------------------------- третий исход

class TheWorstCutDecidesTheSite(unittest.TestCase):
    """Один обрезанный перечень не лечится соседним безопасным срезом."""

    def test_a_prose_cut_standing_first_does_not_hide_the_list_cut(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    msg = proc.stderr.strip()[-300:]\n"
               "    rows = proc.stdout.splitlines()[:5]\n"
               "    for row in rows:\n"
               "        print(row, msg)\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual(row["cut_unit"], census.UNIT_ITEMS)


class NotMeasuredIsNeverPassedOffAsClean(unittest.TestCase):
    """Инв. #17: «не измерено» — своё значение с ПРИЧИНОЙ."""

    def test_a_container_hides_the_reader_and_that_is_said_aloud(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    doc = {'tail': proc.stderr.strip()[-300:]}\n"
               "    return doc\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertIn("контейнер", row["reason"])

    def test_an_unknown_consumer_is_unmeasured_with_its_name(self):
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    return Verdict(evidence=proc.stdout.splitlines()[:4])\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertIn("Verdict", row["reason"])

    def test_a_binding_form_that_is_not_a_name_is_unmeasured(self):
        src = ("def f(cache):\n"
               "    cache['p'] = subprocess.run(['x'], capture_output=True)\n"
               "    return cache\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertIn("Subscript", row["reason"])

    def test_a_bound_cut_that_nobody_reads_is_unmeasured(self):
        """Ветка достижима: цель присваивания читателем не считается."""
        src = ("def f():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    tail = proc.stdout[:100]\n"
               "    return proc.returncode\n")
        with TemporaryDirectory() as tmp:
            row = _verdict(Path(tmp), src)
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertIn("читателя в теле нет", row["reason"])

    def test_a_missing_population_directory_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "half"
            (root / "spa_core").mkdir(parents=True)
            outcome = census.run(root, write=False, now=_NOW)
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")
        self.assertFalse(outcome["measured"])
        self.assertIn("scripts", outcome["doc"]["reason"])

    def test_a_missing_root_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as tmp:
            outcome = census.run(Path(tmp) / "nope", write=False, now=_NOW)
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")

    def test_unmeasured_exits_two_and_says_so(self):
        with TemporaryDirectory() as tmp:
            code = census.main(["--root", str(Path(tmp) / "nope"), "--no-write"])
        self.assertEqual(code, 2)


class AccountingIsIdentical(unittest.TestCase):
    """``call_sites == сумма корзин``, иначе корзина потерялась молча."""

    def test_every_site_lands_in_exactly_one_bucket(self):
        doc = census.measure(_REPO_ROOT, now=_NOW)
        total = sum(doc["counts"][c] for c in (
            census.CLASS_SILENT, census.CLASS_GUARDED, census.CLASS_PROSE,
            census.CLASS_ESCAPED, census.CLASS_NO_CUT, census.CLASS_UNMEASURED))
        self.assertEqual(total, doc["call_sites"])

    def test_every_unmeasured_row_carries_a_reason(self):
        doc = census.measure(_REPO_ROOT, now=_NOW)
        for row in doc["rows"]:
            if row["verdict"] == census.CLASS_UNMEASURED:
                self.assertTrue(row.get("reason"), row)

    def test_the_clock_is_an_input(self):
        doc = census.measure(_REPO_ROOT, now=_NOW)
        self.assertEqual(doc["generated_at"], _NOW.isoformat())


class ReportLeadsWithFindings(unittest.TestCase):
    """Отчёт усекается с хвоста ⇒ голова обязана нести сильнейшее свидетельство."""

    def test_findings_come_before_the_quiet_rows(self):
        src_bad = ("def bad():\n"
                   "    proc = subprocess.run(['x'], capture_output=True)\n"
                   "    rows = proc.stdout.splitlines()[:5]\n"
                   "    for row in rows:\n"
                   "        print(row)\n")
        src_quiet = ("def quiet():\n"
                     "    proc = subprocess.run(['x'], capture_output=True)\n"
                     "    return proc.returncode\n")
        with TemporaryDirectory() as tmp:
            # Имена выбраны ПРОТИВ алфавита: `aaa` тих, `zzz` — находка.
            root = _tree(Path(tmp), {"scripts/aaa.py": _IMPORT + src_quiet,
                                     "scripts/zzz.py": _IMPORT + src_bad})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(doc["rows"][0]["verdict"], census.CLASS_SILENT)
        self.assertEqual(doc["rows"][0]["module"], "scripts/zzz.py")

    def test_a_finding_status_exits_one(self):
        src = ("def bad():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    rows = proc.stdout.splitlines()[:5]\n"
               "    for row in rows:\n"
               "        print(row)\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/zzz.py": _IMPORT + src})
            code = census.main(["--root", str(root), "--no-write"])
        self.assertEqual(code, 1)

    def test_a_clean_tree_exits_zero(self):
        src = ("def ok():\n"
               "    proc = subprocess.run(['x'], capture_output=True)\n"
               "    return proc.returncode\n")
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/ok.py": _IMPORT + src})
            code = census.main(["--root", str(root), "--no-write"])
        self.assertEqual(code, 0)

    def test_the_short_report_says_that_it_is_short(self):
        src = "\n\n".join(
            f"def bad{i}():\n"
            f"    proc = subprocess.run(['x'], capture_output=True)\n"
            f"    rows = proc.stdout.splitlines()[:5]\n"
            f"    for row in rows:\n"
            f"        print(row)\n" for i in range(8))
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/zzz.py": _IMPORT + src})
            doc = census.measure(root, now=_NOW)
        lines = census.format_report(doc, max_rows=3)
        self.assertTrue(any("показаны 3 находки из 8" in ln for ln in lines))
        self.assertTrue(lines[0].startswith("⚠️"))

    def test_the_side_line_names_every_side_seen(self):
        doc = census.measure(_REPO_ROOT, now=_NOW)
        line = [ln for ln in census.report(doc)
                if ln.startswith("[СТОРОНА РАЗРЕЗА]")][0]
        for side, count in doc["cut_sides"].items():
            self.assertIn(f"{side} {count}", line)


class ArtifactIsWrittenWhereAsked(unittest.TestCase):
    """Прогон ступени кладёт документ по объявленному имени."""

    def test_run_writes_the_named_artifact(self):
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/ok.py": _IMPORT + "def f():\n    pass\n"})
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            outcome = census.run(root, data_dir=data_dir, now=_NOW)
        self.assertTrue(outcome["artifact"].endswith(census.ARTIFACT))


if __name__ == "__main__":
    unittest.main()
