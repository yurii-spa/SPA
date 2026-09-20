"""Перепись обрезанного входа: сторож прибора, у каждой проверки обратная сторона.

Заказ **G49 п. 2** приказа владельца «Portfolio CIO», решение — ADR-427.

## Что здесь проверяется и почему именно так

Прибор делит зовущих общей проводки по РОДУ ЧТЕНИЯ, и ошибиться он может в обе
стороны. Опасна одна: назвать читателя перечня «хвостом» — такой вывод
молчалив, и находка исчезнет, не покраснев. Поэтому у каждой сцены есть
обратная, а само дерево сцен собрано из ИСХОДНИКОВ, а не из подделанных
словарей: правило читает AST, и проверять его на заранее разобранных данных
значило бы проверять свою же фикстуру.

**Два положительных контроля — на НАСТОЯЩЕМ контуре, а не на строках:**

1. настоящий git-репозиторий с тремя рабочими деревьями, чьи ПУТИ длиннее
   бюджета: `git worktree list --porcelain` перерастает 2000 знаков, и видно,
   что прежний бюджет унёс бы голову перечня, а нынешний — нет;
2. настоящий pytest по файлу с тремя десятками падающих тестов: сводка
   `-rf` перерастает бюджет, проводка ставит метку, и `failed_tests`
   отвечает третьим исходом вместо укороченного перечня.

Без них проверка была бы утверждением о строках, а не о вреде.

Литеральных дат здесь нет: часы прибора инъектируются параметром ``now``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import absent_path_probe as apd
from spa_core.monitoring import copy_independence_probe as runner
from spa_core.monitoring import truncated_input_census as census
from spa_core.monitoring import vacuous_guard_census as vgc
from spa_core.monitoring import vacuous_guard_probe as vgp

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Неподвижные часы: прибор берёт их параметром.
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Заголовок модуля-зовущего: ввоз проводки под тем же алиасом, что в проде.
_IMPORT = ("from spa_core.monitoring import copy_independence_probe as base\n"
           "import sys\n\n\n")


def _tree(tmp: Path, callers: dict, *, budget: int = 2000) -> Path:
    """Крошечное дерево: модуль проводки со своим бюджетом + файлы-зовущие.

    Проводка кладётся НАСТОЯЩИМ путём (`spa_core/monitoring/…`), потому что
    перепись ищет её по пути, и подделка пути проверяла бы фикстуру.
    """
    root = tmp / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "spa_core" / "monitoring" / "copy_independence_probe.py").write_text(
        f"KEEP_OUTPUT_CHARS = {budget}\n\n\n"
        "def _run(cmd, *, cwd, timeout=60, keep=KEEP_OUTPUT_CHARS):\n"
        "    return 0, ''\n\n\n"
        "def output_truncated(text):\n"
        "    return '…' in text\n",
        encoding="utf-8")
    for rel, src in callers.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    return root


def _rows(doc: dict, module: str) -> list:
    return [r for r in doc["rows"] if r["module"] == module]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


# --------------------------------------------------------------- род чтения

class ReadingKindSeparatesListFromTail(unittest.TestCase):
    """Перечень против хвоста — и обратная сторона у каждой формы."""

    def test_a_comprehension_over_lines_is_a_list_read(self):
        body = ast.parse("def f(out):\n"
                         "    return [l for l in out.splitlines() if l]\n")
        self.assertEqual(census.reading_kind(body), census.READ_LIST)

    def test_a_for_loop_that_appends_is_a_list_read(self):
        body = ast.parse("def f(out):\n"
                         "    acc = []\n"
                         "    for l in out.splitlines():\n"
                         "        acc.append(l)\n"
                         "    return acc\n")
        self.assertEqual(census.reading_kind(body), census.READ_LIST)

    def test_a_loop_that_breaks_on_the_summary_is_a_tail_read(self):
        """Обратная сторона: поиск сводки читает ОДНУ строку, и режется голова."""
        body = ast.parse("def f(out):\n"
                         "    for l in reversed(out.splitlines()):\n"
                         "        if 'passed' in l:\n"
                         "            return l\n")
        self.assertEqual(census.reading_kind(body), census.READ_TAIL)

    def test_the_last_line_is_a_tail_read(self):
        body = ast.parse("def f(out):\n    return out.strip().splitlines()[-1]\n")
        self.assertEqual(census.reading_kind(body), census.READ_TAIL)


class DoorHasTwoFormsAndBothCount(unittest.TestCase):
    def test_the_named_door_is_found(self):
        body = ast.parse("def f(out):\n"
                         "    if base.output_truncated(out):\n"
                         "        return None\n")
        self.assertEqual(census.has_door(body, {"out"}), census.DOOR_NAMED)

    def test_the_count_crosscheck_is_a_door_too(self):
        """Арифметика `_collected_ids` СТАРШЕ метки и засчитывается наравне."""
        body = ast.parse("def f(out, declared):\n"
                         "    ids = [l for l in out.splitlines()]\n"
                         "    return ids if len(ids) == declared else None\n")
        self.assertEqual(census.has_door(body, {"out"}), census.DOOR_COUNT)

    def test_a_body_without_either_has_no_door(self):
        body = ast.parse("def f(out):\n"
                         "    return [l for l in out.splitlines()]\n")
        self.assertIsNone(census.has_door(body, {"out"}))


# ------------------------------------------- дверь считает ТОЛЬКО свой перечень

class DoorCountRequiresProvenance(unittest.TestCase):
    """Заказ G51 п. 3: сверяемое ``len(X)`` обязано ПРОИСХОДИТЬ от вывода.

    Каждая проверка здесь — положительный контроль на дефект, названный
    ADR-428 («чего решение не доказывает», п. 4): прежнее правило засчитывало
    дверью ЛЮБУЮ сверку ``len(...)`` в теле, включая длину КОМАНДЫ, и
    ошибалось в сторону молчания — ложная дверь превращает находку в
    ``guarded``, то есть гасит её, ничего не починив.
    """

    def test_the_length_of_the_command_is_not_a_door(self):
        """Тот самый промах: сверяется длина команды, а не перечня."""
        body = ast.parse("def f(out, cmd):\n"
                         "    rows = [l for l in out.splitlines()]\n"
                         "    if len(cmd) != 3:\n"
                         "        return None\n"
                         "    return rows\n")
        self.assertIsNone(census.has_door(body, {"out"}))

    def test_the_same_body_under_the_old_rule_would_have_claimed_a_door(self):
        """Обратная сторона: сузилось ПРАВИЛО, а не сцена.

        Сцена выше содержит сверку `len(...)` внутри `Compare` — ровно то, на
        что откликалось прежнее правило. Здесь это проверяется признаком
        сцены, а не памятью о старом коде: иначе проверка утверждала бы, что
        сужение сработало, не показав, было ли на чём срабатывать.
        """
        body = ast.parse("def f(out, cmd):\n"
                         "    rows = [l for l in out.splitlines()]\n"
                         "    if len(cmd) != 3:\n"
                         "        return None\n"
                         "    return rows\n")
        lens = [n for n in ast.walk(body)
                if isinstance(n, ast.Compare)
                for side in [n.left, *n.comparators]
                if isinstance(side, ast.Call)
                and isinstance(side.func, ast.Name) and side.func.id == "len"]
        self.assertTrue(lens, "сцена обязана нести сверку len(...) внутри Compare")

    def test_the_real_door_survives_the_narrowing(self):
        """Живая дверь `_collected_ids` обязана УСТОЯТЬ — иначе сузили лишнее."""
        body = ast.parse("def f(out, guard_rel):\n"
                         "    declared = 0\n"
                         "    ids = [l.strip() for l in (out or '').splitlines()\n"
                         "           if '::' in l]\n"
                         "    return ids if len(ids) == declared else None\n")
        self.assertEqual(census.has_door(body, {"out"}), census.DOOR_COUNT)

    def test_the_declined_crosscheck_is_named_not_swallowed(self):
        """Сужение, которое нельзя перемерить, — та же ложная дверь наизнанку."""
        body = ast.parse("def f(out, cmd):\n"
                         "    rows = [l for l in out.splitlines()]\n"
                         "    if len(cmd) != 3:\n"
                         "        return None\n"
                         "    return rows\n")
        door, declined = census.door_evidence(body, {"out"})
        self.assertIsNone(door)
        self.assertEqual(len(declined), 1)
        self.assertEqual(declined[0]["measured"], "cmd")
        self.assertIn("не происходит", declined[0]["reason"])

    def test_an_unnamed_anchor_is_a_different_reason(self):
        """«Якорь не назван» и «сверяется чужое» — два разных ответа (инв. #17)."""
        body = ast.parse("def f(out, cmd):\n"
                         "    if len(cmd) != 3:\n"
                         "        return None\n")
        _, declined = census.door_evidence(body, set())
        self.assertEqual(len(declined), 1)
        self.assertIn("якорь вывода", declined[0]["reason"])
        _, other = census.door_evidence(body, {"out"})
        self.assertNotEqual(declined[0]["reason"], other[0]["reason"])

    def test_the_named_door_does_not_need_provenance(self):
        """Метку ставит САМА проводка: у неё вопрос о происхождении не стои́т."""
        body = ast.parse("def f(text):\n"
                         "    if base.output_truncated(text):\n"
                         "        return None\n")
        self.assertEqual(census.has_door(body, set()), census.DOOR_NAMED)

    def test_a_container_is_not_a_derivation(self):
        """`.claude/rules/deployment.md`: `doc = {...}` выводом не делает."""
        expr = ast.parse("{'out': text}", mode="eval").body
        self.assertFalse(census.derives_from(expr, {"text"}))
        self.assertTrue(census.derives_from(
            ast.parse("text.splitlines()", mode="eval").body, {"text"}))

    def test_derivation_reaches_a_fixed_point(self):
        """Цепочка идёт ПРОТИВ порядка строк — иначе сцена верна по построению.

        Батарея поймала первую редакцию: там связывания стояли по порядку, и
        ОДНОГО прохода хватало, потому что `ast.walk` идёт сверху вниз. Такая
        сцена не проверяет неподвижную точку — она её обходит.
        """
        body = ast.parse("def f(out):\n"
                         "    c = [x for x in b]\n"
                         "    b = a[:2]\n"
                         "    a = out.splitlines()\n")
        self.assertEqual(census.derived_names(body, "out"),
                         {"out", "a", "b", "c"})

    def test_a_binding_cycle_terminates(self):
        """Предел обхода — про завершимость, а не про скорость."""
        body = ast.parse("def f(out):\n"
                         "    a = out\n"
                         "    b = a\n"
                         "    a = b\n")
        self.assertEqual(census.derived_names(body, "out"), {"out", "a", "b"})

    def test_no_anchor_means_no_names(self):
        body = ast.parse("def f(out):\n    a = out\n")
        self.assertEqual(census.derived_names(body), set())


class TheAnchorInsideTheReaderIsNamed(unittest.TestCase):
    """Вывод входит в вынесенного читателя ПАРАМЕТРОМ — его и надо назвать."""

    def _body(self, src: str) -> ast.AST:
        return ast.parse(src).body[0]

    def test_a_positional_argument_maps_to_its_parameter(self):
        body = self._body("def r(out, rel):\n    return out\n")
        self.assertEqual(census.anchor_in_reader(body, 0), "out")
        self.assertEqual(census.anchor_in_reader(body, 1), "rel")

    def test_a_keyword_argument_maps_by_name(self):
        body = self._body("def r(rel, *, out=None):\n    return out\n")
        self.assertEqual(census.anchor_in_reader(body, "out"), "out")

    def test_an_unmappable_place_is_not_guessed(self):
        """Третий исход: сопоставить не удалось ≠ «двери нет».

        Сцена НАРОЧНО несёт параметры: батарея поймала первую редакцию, где
        читатель был `def r(*args)` — при пустом перечне параметров подмена
        «взять первый» неотличима от отказа, то есть сцена была украшением.
        """
        body = self._body("def r(rel, flag):\n    return rel\n")
        self.assertIsNone(census.anchor_in_reader(body, 5))
        self.assertIsNone(census.anchor_in_reader(body, "out"))
        starred = self._body("def r(*args):\n    return args\n")
        self.assertIsNone(census.anchor_in_reader(starred, 0))

    def test_readers_of_carries_the_place(self):
        scope = ast.parse("def f():\n"
                          "    code, text = base._run(cmd)\n"
                          "    a = parse(text)\n"
                          "    b = other(rel, out=text)\n").body[0]
        found, _ = census.readers_of("text", scope)
        self.assertIn((None, "parse", 0), found)
        self.assertIn((None, "other", "out"), found)


# -------------------------------------------------------------- классификация

class VerdictsOnRealSources(unittest.TestCase):
    """Каждый вердикт — на собственном исходнике, и рядом его противоположность."""

    def _measure(self, callers: dict, **kw) -> dict:
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), callers, **kw)
            return census.measure(root, now=_NOW)

    def test_a_list_reader_without_a_door_is_a_finding(self):
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root)\n"
            "    return [l for l in out.splitlines() if l.startswith('w ')]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual(row["budget"], 2000)
        self.assertEqual(doc["status"], "FINDING")

    def test_the_same_reader_with_a_door_is_guarded(self):
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root)\n"
            "    if base.output_truncated(out):\n"
            "        return None\n"
            "    return [l for l in out.splitlines() if l.startswith('w ')]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_GUARDED)
        self.assertEqual(doc["status"], "CLEAN")

    def test_a_crosscheck_of_the_command_no_longer_buys_a_door(self):
        """Заказ G51 п. 3 на НАСТОЯЩЕМ исходнике, а не на разобранном теле.

        Сверяется длина КОМАНДЫ — перечню она ничего не обещает. Прежнее
        правило вернуло бы `guarded` и погасило находку; теперь строка
        остаётся находкой, а отклонённая сверка НАЗВАНА.
        """
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root, cmd):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    if len(cmd) != 3:\n"
            "        return None\n"
            "    return [l for l in out.splitlines() if l]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual(row["door"], "")
        self.assertEqual([d["measured"] for d in row["door_declined"]], ["cmd"])
        self.assertEqual(doc["counts"]["door_declined"], 1)

    def test_a_crosscheck_of_the_output_still_buys_a_door(self):
        """Обратная сторона той же сцены: сузилось правило, а не класс дверей."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root, cmd, declared):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    rows = [l for l in out.splitlines() if l]\n"
            "    if len(rows) != declared:\n"
            "        return None\n"
            "    return rows\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_GUARDED)
        self.assertEqual(row["door"], census.DOOR_COUNT)
        self.assertEqual(row["door_declined"], [])
        self.assertEqual(doc["counts"]["door_declined"], 0)

    def test_the_door_of_an_external_reader_is_read_at_its_own_parameter(self):
        """Читатель вынесен — якорь у него СВОЙ, и он обязан быть сопоставлен."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def parse(text, declared):\n"
            "    ids = [l for l in text.splitlines() if l]\n"
            "    return ids if len(ids) == declared else None\n\n\n"
            "def go(root, cmd):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    return parse(out, 3)\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_GUARDED)
        self.assertEqual(row["door"], census.DOOR_COUNT)

    def test_an_external_reader_that_counts_something_else_is_a_finding(self):
        """Та же форма, но считается ЧУЖОЙ перечень — двери нет."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def parse(text, declared):\n"
            "    ids = [l for l in text.splitlines() if l]\n"
            "    return ids if len(declared) == 3 else None\n\n\n"
            "def go(root, cmd):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    return parse(out, cmd)\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual([d["measured"] for d in row["door_declined"]],
                         ["declared"])

    def test_the_declined_count_in_the_summary_equals_the_rows(self):
        """Сводка и строки — один замер: разойтись им нельзя ни на единицу."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root, cmd):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    if len(cmd) != 3:\n"
            "        return None\n"
            "    return [l for l in out.splitlines() if l]\n"), "scripts/b.py": _IMPORT + (
            "def go(root, cmd):\n"
            "    code, out = base._run(cmd, cwd=root)\n"
            "    if len(cmd) > 1 and len(root) > 1:\n"
            "        return None\n"
            "    return [l for l in out.splitlines() if l]\n")})
        self.assertEqual(
            doc["counts"]["door_declined"],
            sum(len(r["door_declined"]) for r in doc["rows"]))
        self.assertEqual(doc["counts"]["door_declined"], 3)

    def test_a_tail_reader_is_safe_by_construction(self):
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root)\n"
            "    return out.strip().splitlines()[-1]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_TAIL_SAFE)

    def test_keep_none_removes_truncation_entirely(self):
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root, keep=None)\n"
            "    return [l for l in out.splitlines()]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_UNBOUNDED)
        self.assertIsNone(row["budget"])

    def test_a_budget_that_is_not_a_number_is_the_third_outcome(self):
        """Не «умолчание»: подставить его значило бы соврать в сторону покоя."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root, n):\n"
            "    code, out = base._run(['git'], cwd=root, keep=n * 2)\n"
            "    return [l for l in out.splitlines()]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertEqual(row["budget"], census.BUDGET_UNRESOLVED)

    def test_a_named_budget_constant_is_resolved(self):
        doc = self._measure({"scripts/a.py": "BIG = 99\n" + _IMPORT + (
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root, keep=BIG)\n"
            "    return [l for l in out.splitlines()]\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["budget"], 99)
        self.assertEqual(row["verdict"], census.CLASS_SILENT)

    def test_a_cached_binding_is_named_not_guessed(self):
        """Третий исход НАЗЫВАЕТ форму: «не разобрано» без причины бесполезно."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def go(root, cache):\n"
            "    cache['k'] = base._run(['git'], cwd=root)\n"
            "    return cache\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_UNMEASURED)
        self.assertIn("Subscript", row["reason"])

    def test_a_call_through_a_wrapper_inherits_the_wrappers_budget(self):
        doc = self._measure({"scripts/a.py": "SMALL = 7\n" + _IMPORT + (
            "def wrapped(root):\n"
            "    return base._run(['git'], cwd=root, keep=SMALL)\n\n\n"
            "def go(root):\n"
            "    code, out = wrapped(root)\n"
            "    return [l for l in out.splitlines()]\n")})
        rows = _rows(doc, "scripts/a.py")
        through = [r for r in rows if r["via_wrapper"] == "wrapped"]
        self.assertEqual(len(through), 1, rows)
        self.assertEqual(through[0]["budget"], 7)
        self.assertEqual(through[0]["verdict"], census.CLASS_SILENT)

    def test_a_wrapper_over_a_wrapper_is_counted_not_swallowed(self):
        """Слепота правила глубины названа ЧИСЛОМ, а не обещанием."""
        doc = self._measure({"scripts/a.py": _IMPORT + (
            "def wrapped(root):\n"
            "    return base._run(['git'], cwd=root)\n\n\n"
            "def deeper(root):\n"
            "    return wrapped(root)\n")})
        self.assertEqual(doc["wrapper_depth_exceeded"], ["scripts/a.py::deeper"])

    def test_a_reader_in_a_neighbour_module_is_resolved_by_import(self):
        doc = self._measure({
            "scripts/reader.py": (
                "def names(out):\n"
                "    acc = []\n"
                "    for l in out.splitlines():\n"
                "        acc.append(l)\n"
                "    return acc\n"),
            "scripts/a.py": _IMPORT + (
                "from scripts import reader as rd\n\n\n"
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return rd.names(out)\n")})
        row, = _rows(doc, "scripts/a.py")
        self.assertEqual(row["verdict"], census.CLASS_SILENT)
        self.assertEqual(row["readers"], ["rd.names"])

    def test_a_namesake_from_another_package_is_not_the_wiring(self):
        """Имя листа совпало, пакет — нет. Правило имени взяло бы чужой модуль."""
        doc = self._measure({"scripts/a.py": (
            "from vendor.tools import copy_independence_probe as base\n\n\n"
            "def go(root):\n"
            "    code, out = base._run(['git'], cwd=root)\n"
            "    return [l for l in out.splitlines()]\n")})
        self.assertEqual(_rows(doc, "scripts/a.py"), [])

    def test_mentioning_the_runner_in_a_string_is_not_an_import(self):
        """Ввоз разбирается AST: текстовое правило выдумало бы находку."""
        doc = self._measure({"scripts/a.py": (
            "DOC = 'spa_core.monitoring.copy_independence_probe'\n\n\n"
            "def go(base, root):\n"
            "    code, out = base._run(['git'], cwd=root)\n"
            "    return [l for l in out.splitlines()]\n")})
        self.assertEqual(_rows(doc, "scripts/a.py"), [])


class DefaultBudgetIsReadFromTheWiringNotStoredHere(unittest.TestCase):
    """Вторая копия числа разошлась бы молча (ADR-417) — её нет."""

    def test_the_census_reports_the_budget_the_wiring_declares(self):
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return [l for l in out.splitlines()]\n")}, budget=321)
            doc = census.measure(root, now=_NOW)
        self.assertEqual(doc["runner"]["default_budget"], 321)
        self.assertEqual(_rows(doc, "scripts/a.py")[0]["budget"], 321)

    def test_the_live_wiring_default_is_unchanged(self):
        """Правка ADR-427 добавляет МЕТКУ, а не меняет бюджет."""
        self.assertEqual(runner.KEEP_OUTPUT_CHARS, 2000)
        self.assertEqual(census.runner_default_budget(_REPO_ROOT), 2000)


class AccountingIsIdenticalAndUnmeasuredIsLoud(unittest.TestCase):
    def test_scanned_equals_classified_plus_unreadable(self):
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {
                "scripts/a.py": _IMPORT + (
                    "def go(root):\n"
                    "    code, out = base._run(['git'], cwd=root)\n"
                    "    return [l for l in out.splitlines()]\n"),
                "scripts/broken.py": "def (\n"})
            doc = census.measure(root, now=_NOW)
        counts = doc["counts"]
        classified = sum(counts[c] for c in (
            census.CLASS_SILENT, census.CLASS_GUARDED, census.CLASS_TAIL_SAFE,
            census.CLASS_UNBOUNDED, census.CLASS_UNMEASURED))
        self.assertEqual(doc["call_sites"], classified)
        self.assertEqual(counts["unreadable"], 1)
        self.assertEqual(doc["unreadable"][0]["module"], "scripts/broken.py")
        self.assertTrue(doc["unreadable"][0]["reason"])

    def test_a_missing_root_is_the_third_outcome_and_exits_nonzero(self):
        with TemporaryDirectory() as tmp:
            out = census.run(Path(tmp) / "нет-такого", write=False, now=_NOW)
        self.assertEqual(out["doc"]["status"], "UNMEASURED")
        self.assertIn("не прочитан", out["doc"]["reason"])
        self.assertEqual(census.report(out["doc"])[0][:12], "НЕ ИЗМЕРЕНО ")

    def test_a_missing_population_directory_is_not_an_empty_census(self):
        """Пропустить каталог значило бы ответить «чисто», осмотрев половину."""
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return [l for l in out.splitlines()]\n")})
            import shutil
            shutil.rmtree(root / "scripts")
            with self.assertRaises(census.NotMeasured):
                census.measure(root, now=_NOW)
            doc = census.run(root, write=False, now=_NOW)["doc"]
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("scripts", doc["reason"])

    def test_a_missing_wiring_module_is_not_a_clean_pass(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "t"
            (root / "spa_core").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "scripts" / "a.py").write_text("x = 1\n", encoding="utf-8")
            doc = census.run(root, write=False, now=_NOW)["doc"]
        self.assertEqual(doc["status"], "UNMEASURED")

    def test_main_exit_codes_separate_the_three_outcomes(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "нет"
            self.assertEqual(
                census.main(["--root", str(missing), "--no-write"]), 2)
            root = _tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return [l for l in out.splitlines()]\n")})
            self.assertEqual(census.main(["--root", str(root), "--no-write"]), 1)
            clean = _tree(Path(tmp) / "b", {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return out.strip().splitlines()[-1]\n")})
            self.assertEqual(census.main(["--root", str(clean), "--no-write"]), 0)


class ReportLeadsWithFindingsAndAdmitsItsOwnCut(unittest.TestCase):
    def test_findings_come_first_because_the_tail_is_cut(self):
        """Имена выбраны ПРОТИВ порядка: находка сортируется ПОСЛЕ безопасного.

        Батарея мутаций поймала первую редакцию: там находка лежала в
        `zzz_list.py`, а хвостовой читатель — в `zzz_tail.py`, и по алфавиту
        находка шла первой и БЕЗ сортировки по вердикту. Сцена была верна по
        построению — то есть украшением.
        """
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {
                "scripts/aaa_tail.py": _IMPORT + (
                    "def go(root):\n"
                    "    code, out = base._run(['git'], cwd=root)\n"
                    "    return out.strip().splitlines()[-1]\n"),
                "scripts/zzz_list.py": _IMPORT + (
                    "def go(root):\n"
                    "    code, out = base._run(['git'], cwd=root)\n"
                    "    return [l for l in out.splitlines()]\n")})
            doc = census.measure(root, now=_NOW)
        self.assertEqual(doc["rows"][0]["module"], "scripts/zzz_list.py")
        self.assertEqual(doc["rows"][0]["verdict"], census.CLASS_SILENT)

    def test_a_cut_report_says_so(self):
        """Прибор об обрезании не вправе молчать сам — это его же предмет."""
        with TemporaryDirectory() as tmp:
            callers = {f"scripts/m{i}.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return [l for l in out.splitlines()]\n") for i in range(4)}
            doc = census.measure(_tree(Path(tmp), callers), now=_NOW)
        lines = census.report(doc, max_rows=2)
        self.assertTrue(any(line.startswith("[…] показаны 2 находки из 4")
                            for line in lines), lines)

    def test_the_report_names_the_crosscheck_it_declined(self):
        """Сужение, о котором отчёт молчит, проверить нечем — и поверить тоже."""
        with TemporaryDirectory() as tmp:
            doc = census.measure(_tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root, cmd):\n"
                "    code, out = base._run(cmd, cwd=root)\n"
                "    if len(cmd) != 3:\n"
                "        return None\n"
                "    return [l for l in out.splitlines()]\n")}), now=_NOW)
        lines = census.report(doc)
        self.assertIn("сверок отклонено 1", lines[0])
        named = [l for l in lines if l.startswith("[СВЕРКА НЕ ДВЕРЬ]")]
        self.assertEqual(len(named), 1, lines)
        self.assertIn("len(cmd)", named[0])

    def test_a_clean_tree_says_zero_declined_rather_than_nothing(self):
        """Обратная сторона: ноль обязан быть НАПЕЧАТАН, а не подразумеваться.

        Молчание о нуле и «не мерили» с виду одно и то же (инв. #17), а вопрос
        здесь ровно тот, из-за которого заказ и написан.
        """
        with TemporaryDirectory() as tmp:
            doc = census.measure(_tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return out.strip().splitlines()[-1]\n")}), now=_NOW)
        lines = census.report(doc)
        self.assertIn("сверок отклонено 0", lines[0])
        self.assertFalse([l for l in lines if l.startswith("[СВЕРКА НЕ ДВЕРЬ]")])

    def test_the_office_rendering_delegates_and_marks_a_finding(self):
        with TemporaryDirectory() as tmp:
            doc = census.measure(_tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return [l for l in out.splitlines()]\n")}), now=_NOW)
        self.assertTrue(census.format_report(doc)[0].startswith("⚠️ "))


class ArtifactIsWrittenAtomically(unittest.TestCase):
    def test_run_writes_the_document_where_it_says(self):
        with TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), {"scripts/a.py": _IMPORT + (
                "def go(root):\n"
                "    code, out = base._run(['git'], cwd=root)\n"
                "    return out.strip().splitlines()[-1]\n")})
            dest = Path(tmp) / "out.json"
            out = census.run(root, dest=dest, now=_NOW)
            self.assertEqual(
                json.loads(dest.read_text(encoding="utf-8"))["status"], "CLEAN")
            self.assertEqual(out["artifact"], str(dest))


# ------------------------------------------------- проводка: метка и её отсутствие

class TheWiringMarksTheCut(unittest.TestCase):
    def test_a_short_text_is_untouched(self):
        self.assertEqual(runner.truncate("abc", 10), "abc")
        self.assertFalse(runner.output_truncated("abc"))

    def test_a_long_text_keeps_the_tail_and_says_so(self):
        cut = runner.truncate("голова" + "x" * 50, 10)
        self.assertTrue(cut.endswith("x" * 10))
        self.assertTrue(runner.output_truncated(cut))
        self.assertIn("отброшено", cut)

    def test_keep_none_never_truncates(self):
        text = "x" * 10_000
        self.assertEqual(runner.truncate(text, None), text)
        self.assertFalse(runner.output_truncated(runner.truncate(text, None)))

    def test_the_mark_cannot_be_mistaken_for_a_line_any_reader_parses(self):
        """Метка не должна отравить разборы соседей — обе стороны проверены."""
        mark = runner.TRUNCATION_MARK
        self.assertFalse(mark.startswith("FAILED "))
        self.assertNotIn("::", mark)
        self.assertIsNone(vgp.summary_count(mark + ": отброшено 5 знак(ов)"))

    def test_a_real_subprocess_longer_than_the_budget_is_marked(self):
        """Настоящий прогон, а не строка: проводка мерится своим контуром."""
        code, out = runner._run(
            [sys.executable, "-c", "print('y' * 5000)"],
            cwd=_REPO_ROOT, timeout=60, keep=200)
        self.assertEqual(code, 0)
        self.assertTrue(runner.output_truncated(out))
        code, whole = runner._run(
            [sys.executable, "-c", "print('y' * 5000)"],
            cwd=_REPO_ROOT, timeout=60, keep=None)
        self.assertFalse(runner.output_truncated(whole))


class TheJanitorSeesEveryWorktree(unittest.TestCase):
    """Положительный контроль ЖИВОГО вреда: перечень длиннее бюджета."""

    def test_trees_beyond_the_old_budget_are_still_found(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "t@t")
            _git(repo, "config", "user.name", "t")
            (repo / "f.txt").write_text("x", encoding="utf-8")
            _git(repo, "add", "f.txt")
            _git(repo, "commit", "-qm", "init")
            # Пути намеренно ДЛИННЫЕ: так перечень перерастает бюджет на трёх
            # деревьях вместо пятидесяти, и опыт стоит секунды, а не минуты.
            long = "d" * 180
            made = []
            for i in range(4):
                path = Path(tmp) / f"{long}_{i}" / f"{long}" / f"spa_copy_probe_{i}"
                _git(repo, "worktree", "add", "--detach", "-q", str(path))
                made.append(str(path))

            raw = subprocess.run(
                ["git", "worktree", "list", "--porcelain"], cwd=str(repo),
                capture_output=True, text=True, check=True).stdout
            self.assertGreater(len(raw), runner.KEEP_OUTPUT_CHARS,
                               "сцена обязана перерасти бюджет — иначе она "
                               "верна по построению и ничего не доказывает")

            seen = runner.stale_disposable_trees(repo, prefix="spa_copy_probe_")
            self.assertEqual(len(seen), 4, seen)

            # Обратная сторона: тот же вывод через ПРЕЖНИЙ бюджет теряет голову.
            through_old = [
                line.split(" ", 1)[1].strip()
                for line in runner.truncate(raw, runner.KEEP_OUTPUT_CHARS).splitlines()
                if line.startswith("worktree ") and "spa_copy_probe_" in line]
            self.assertLess(len(through_old), len(seen),
                            "если бюджет ничего не уносит, сцена не о вреде")


# ------------------------------------------------ читатель перечня: третий исход

class FailedTestsRefusesATruncatedList(unittest.TestCase):
    def test_a_marked_output_yields_the_third_outcome(self):
        marked = runner.truncate("FAILED a.py::test_x - boom\n" * 400, 300)
        self.assertIsNone(vgp.failed_tests(marked))

    def test_the_same_output_unmarked_yields_names(self):
        self.assertEqual(vgp.failed_tests("FAILED a.py::test_x - boom\n"),
                         ["a.py::test_x"])

    def test_a_real_pytest_run_longer_than_the_budget_refuses(self):
        """Настоящий pytest: сводка `-rf` тридцати падений перерастает бюджет."""
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "test_many_failures_with_a_long_name.py").write_text(
                "".join(
                    f"def test_a_failure_with_a_deliberately_long_name_{i}():\n"
                    f"    assert False, 'сцена обязана дать длинную сводку'\n\n"
                    for i in range(40)),
                encoding="utf-8")
            code, out = vgp.run_guard(tree, "test_many_failures_with_a_long_name.py")
        self.assertNotEqual(code, 0)
        self.assertTrue(runner.output_truncated(out),
                        "сцена обязана перерасти бюджет — иначе она пуста")
        self.assertIsNone(vgp.failed_tests(out))
        # Обратная сторона: сводка ЖИВА, и хвостовой разбор её по-прежнему видит.
        self.assertEqual(vgp.summary_count(out, "failed"), 40)


class AttributionRefusesInsteadOfInventingAFinding(unittest.TestCase):
    """Главный вред: укороченный перечень переворачивал вердикт в находку."""

    _ROW = {"name": "X", "consumer_tests": ["test_consumer"]}

    def test_truncated_names_are_not_consumer_green(self):
        verdict, attribution = vgc._attribute(
            self._ROW, {"failed_tests": None})
        self.assertEqual(attribution, vgc.ATTRIBUTION_TRUNCATED)
        self.assertNotEqual(verdict, vgc.VERDICT_ELSEWHERE)

    def test_a_record_without_the_field_is_not_called_truncated(self):
        """Обратная сторона: запись ДО ADR-427 поля не несёт — это «имён не
        разобрали», а не «имена обрезали». Слияние двух было бы той же
        подменой неизмеренного, против которой написан класс."""
        verdict, attribution = vgc._attribute(self._ROW, {})
        self.assertEqual(attribution, vgc.ATTRIBUTION_HELPER)
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)

    def test_a_full_list_naming_the_consumer_is_still_direct(self):
        verdict, attribution = vgc._attribute(
            self._ROW, {"failed_tests": ["f.py::test_consumer"]})
        self.assertEqual(attribution, vgc.ATTRIBUTION_DIRECT)
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)

    def test_a_full_list_without_the_consumer_is_still_elsewhere(self):
        """Обратная сторона: настоящую находку правка НЕ гасит."""
        verdict, attribution = vgc._attribute(
            self._ROW, {"failed_tests": ["f.py::test_neighbour"]})
        self.assertEqual(verdict, vgc.VERDICT_ELSEWHERE)
        self.assertEqual(attribution, vgc.ATTRIBUTION_NONE)

    def test_the_truncated_row_survives_the_whole_verdict_path(self):
        row = {"key": "k", "guard_sha": "s", "value": "v",
               "name": "X", "consumer_tests": ["test_consumer"]}
        ledger = {"k": {"guard_sha": "s", "value": "v",
                        "verdict": vgc.VERDICT_REFUSES, "failed_tests": None}}
        out = vgc._verdict(row, ledger, None)
        self.assertEqual(out["attribution"], vgc.ATTRIBUTION_TRUNCATED)
        self.assertNotEqual(out["verdict"], vgc.VERDICT_ELSEWHERE)


class TheNeighbourProbeAlsoRefuses(unittest.TestCase):
    def test_consumer_is_red_is_none_when_the_list_was_cut(self):
        """`False` здесь значило бы «потребитель зелен» — вывод из неизмеренного."""
        source = Path(apd.__file__).read_text(encoding="utf-8")
        self.assertIn("entry[\"consumer_is_red\"] = None if names is None", source)


class TheLiveTreeIsCleanAndTheReadingIsNotHollow(unittest.TestCase):
    """Приёмка правки снимается ПРИБОРОМ на живом дереве, а не глазами."""

    def test_no_caller_of_the_wiring_truncates_silently(self):
        doc = census.measure(_REPO_ROOT, now=_NOW)
        silent = [f"{r['module']}:{r['line']}" for r in doc["rows"]
                  if r["verdict"] == census.CLASS_SILENT]
        self.assertEqual(silent, [], silent)

    def test_the_population_is_not_empty(self):
        """Ноль находок при нуле вызовов был бы вырожденным «чисто»."""
        doc = census.measure(_REPO_ROOT, now=_NOW)
        self.assertGreaterEqual(doc["call_sites"], 10)
        self.assertGreaterEqual(doc["counts"][census.CLASS_GUARDED], 2)
        self.assertGreaterEqual(doc["counts"][census.CLASS_UNBOUNDED], 1)


if __name__ == "__main__":
    unittest.main()
