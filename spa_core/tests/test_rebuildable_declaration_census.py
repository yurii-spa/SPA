# FROZEN-DATE-OK: no-dates — ни одной даты в файле нет: сцены строятся из байтов,
# и о свежести этот сторож не судит ни одной строкой.
"""Контроль прибора `scripts/rebuildable_declaration_census.py` (ADR-1130).

Каждая проба здесь — либо ИЗМЕРЕННЫЙ дефект первой редакции прибора, либо
известный член класса ADR-1127, потребовавший своей двери. Проба, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Дефекты, закреплённые ЗДЕСЬ, найдены контролем прибора 28.11:

    `текст.replace("a","b")` считался зовом ЗАПИСИ  → у ADR-1112 находилось
      ДВА зова записи там, где их НОЛЬ, и известный член уходил из
      `no_write_at_all` в `writes_unresolved`, то есть ось теряла разницу,
      на которой стоит
    «любое имя `*.py` строкой — спрошенный инструмент» → у ADR-1112 добирался
      `scripts/check_owner_gate.py` из ДАННЫХ СЦЕНЫ (`file="..."`) и голые
      `a.py`/`b.py` из `docs/evidence/...`
    разбор только МОДУЛЬНОГО уровня → терялся ADR-1060: цель записи доски
      лежит в локальной переменной `main`
    дверь «ответ прибора класса» ОДНА → терялся ADR-889 (`producers=[]`)
    дверь «команда пересборки» ОДНА → терялся ADR-1073 (команды не несёт)
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    """Прибор ввозится ПО ПУТИ из ЭТОГО дерева, а не по имени."""
    path = REPO / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"спек не собран для {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


rdc = _load("rebuildable_declaration_census_under_test",
            "scripts/rebuildable_declaration_census.py")


def _tree(root: pathlib.Path, files: dict) -> None:
    """Одноразовая сцена: git-репозиторий с НАЗВАННОЙ веткой и проиндексированными
    файлами. Имя ветки — вход сцены (`-b main`): умолчание `init.defaultBranch`
    есть свойство ХОСТА (`.claude/rules/deployment.md`, § git-окружение)."""
    subprocess.run(["git", "init", "-b", "main", str(root)],
                   capture_output=True, check=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, check=True)


def _shelf(root: pathlib.Path):
    return rdc.Tree(root)


def _fold_of(source: str, expr_src: str):
    tree = ast.parse(source)
    consts = rdc.module_consts(tree)
    return rdc._fold(ast.parse(expr_src, mode="eval").body, consts)


# ───────────────────────── складыватель путей ──────────────────────────────

class FoldsThePathFormsKnownMembersUse(unittest.TestCase):
    def test_f_string_over_a_module_constant_folds(self):
        """Форма ADR-889: `INDEX_REL = f"{DECISIONS_DIR}/INDEX.md"`.

        Её и не разбирает `_PathResolver` прибора ADR-1073 (`форма не
        разбирается: JoinedStr`) — ради неё складыватель здесь свой.
        """
        src = 'DECISIONS_DIR = "docs/decisions"\nINDEX_REL = f"{DECISIONS_DIR}/INDEX.md"\n'
        self.assertEqual(_fold_of(src, "INDEX_REL"), "docs/decisions/INDEX.md")

    def test_a_local_binding_folds_too_and_this_keeps_adr_1060(self):
        """Форма ADR-1060: цель записи доски лежит в ЛОКАЛЬНОЙ переменной `main`.

        Область видимости здесь намеренно не соблюдается. Разбор только
        модульного уровня терял бы известного члена, то есть форма была бы
        ОПРОВЕРГНУТА (урок ADR-1074).
        """
        src = (
            'from pathlib import Path\n'
            'REPO = Path(__file__).resolve().parent.parent\n'
            'OUT = REPO / "nimbalyst-local" / "tracker" / "_BOARD.md"\n'
            'def main(args, tracker):\n'
            '    out = tracker / OUT.name if args.tracker_dir else OUT\n'
            '    return out\n'
        )
        self.assertEqual(_fold_of(src, "out"), "nimbalyst-local/tracker/_BOARD.md")

    def test_the_ternary_takes_the_branch_that_folds(self):
        src = 'OUT = "docs/x.md"\ny = unknown_thing if flag else OUT\n'
        self.assertEqual(_fold_of(src, "y"), "docs/x.md")

    def test_dot_name_and_dot_stem_are_the_basename(self):
        src = 'OUT = "a/b/_BOARD.md"\n'
        self.assertEqual(_fold_of(src, "OUT.name"), "_BOARD.md")
        self.assertEqual(_fold_of(src, "OUT.stem"), "_BOARD")

    def test_concatenation_and_join_fold(self):
        src = 'import os\nA = "docs"\nB = "x.md"\n'
        self.assertEqual(_fold_of(src, 'A + "/" + B'), "docs/x.md")
        self.assertEqual(_fold_of(src, "os.path.join(A, B)"), "docs/x.md")

    def test_a_self_referential_binding_answers_none_and_does_not_hang(self):
        """Привязка на себя обязана дать `None`, а не висеть: иначе прибор
        отвечает ЗАВИСАНИЕМ, а зависание неотличимо от «долго считает»."""
        src = 'A = A + "x"\n'
        self.assertIsNone(_fold_of(src, "A"))

    def test_a_form_that_does_not_fold_answers_none_rather_than_a_guess(self):
        src = 'A = some_call()\n'
        self.assertIsNone(_fold_of(src, "A"))


# ──────────────────── дерево: разрешение имени в путь ───────────────────────

class ResolvesANameOnlyWhenTheTreeAnswersOnce(unittest.TestCase):
    def test_exact_tracked_path_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"docs/decisions/INDEX.md": "x\n"})
            self.assertEqual(_shelf(root).resolve("docs/decisions/INDEX.md"),
                             "docs/decisions/INDEX.md")

    def test_a_bare_name_resolves_when_exactly_one_file_answers(self):
        """Без этой формы терялся бы ADR-1060: сторож доски называет `_BOARD.md`
        голым именем, а не путём."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"nimbalyst-local/tracker/_BOARD.md": "x\n"})
            self.assertEqual(_shelf(root).resolve("_BOARD.md"),
                             "nimbalyst-local/tracker/_BOARD.md")

    def test_an_ambiguous_bare_name_is_counted_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"a/base.json": "{}\n", "b/base.json": "{}\n"})
            shelf = _shelf(root)
            self.assertIsNone(shelf.resolve("base.json"))
            self.assertEqual(shelf.ambiguous_names, 1,
                             "двусмысленное имя обязано быть СОЧТЕНО, а не забыто")

    def test_a_tree_without_git_refuses_instead_of_answering_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rdc.NotMeasured):
                rdc.Tree(pathlib.Path(tmp))


# ──────────────────────── зовы записи на диск ──────────────────────────────

class TellsAWriteCallFromAStringMethodOfTheSameName(unittest.TestCase):
    """ИЗМЕРЕННЫЙ дефект первой редакции: `текст.replace("a","b")` считался
    записью, и у `python_git_ref_provenance.py` находилось ДВА зова там, где
    их НОЛЬ. Известный член ADR-1112 отличается от прочих ровно этим."""

    def _sites(self, src: str) -> int:
        return len(rdc.write_sites(ast.parse(src)))

    def test_str_replace_is_not_a_write(self):
        self.assertEqual(self._sites('dotted = m.rel[:-3].replace("/", ".")\n'), 0)

    def test_os_replace_is_a_write(self):
        self.assertEqual(self._sites('import os\nos.replace(tmp, path)\n'), 1)

    def test_shutil_move_is_a_write(self):
        self.assertEqual(self._sites('import shutil\nshutil.move(a, b)\n'), 1)

    def test_write_text_and_atomic_save_are_writes(self):
        self.assertEqual(self._sites('p.write_text("x")\n'), 1)
        self.assertEqual(self._sites('atomic_save(p, {})\n'), 1)

    def test_open_for_reading_is_not_a_write_and_for_writing_is(self):
        self.assertEqual(self._sites('open(p)\n'), 0)
        self.assertEqual(self._sites('open(p, "r")\n'), 0)
        self.assertEqual(self._sites('open(p, "w")\n'), 1)
        self.assertEqual(self._sites('open(p, "ab")\n'), 1)


class ResolvesTheWrittenPathIncludingOneHopThroughAParameter(unittest.TestCase):
    def test_a_module_constant_target_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"spa_core/analytics/_untiered_census.py": "x = 1\n"})
            src = ('from pathlib import Path\n'
                   'R = Path(__file__).resolve().parent.parent\n'
                   'CENSUS = R / "spa_core" / "analytics" / "_untiered_census.py"\n'
                   'CENSUS.write_text("x")\n')
            written, sites, unresolved = rdc.written_paths(ast.parse(src), _shelf(root))
            self.assertEqual(written, {"spa_core/analytics/_untiered_census.py"})
            self.assertEqual((sites, unresolved), (1, 0))

    def test_one_hop_through_a_parameter_keeps_adr_1060(self):
        """`atomic_write(path, …)` пишет ПАРАМЕТР, и значение ему назначает
        ВЫЗЫВАЮЩИЙ. Без хопа у доски не разрешалась НИ ОДНА цель записи."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"nimbalyst-local/tracker/_BOARD.md": "x\n"})
            src = ('import os\n'
                   'from pathlib import Path\n'
                   'REPO = Path(__file__).resolve().parent.parent\n'
                   'OUT = REPO / "nimbalyst-local" / "tracker" / "_BOARD.md"\n'
                   'def atomic_write(path, content):\n'
                   '    os.replace(tmp, path)\n'
                   'def main():\n'
                   '    atomic_write(OUT, "x")\n')
            written, _, unresolved = rdc.written_paths(ast.parse(src), _shelf(root))
            self.assertEqual(written, {"nimbalyst-local/tracker/_BOARD.md"})
            self.assertEqual(unresolved, 0)

    def test_an_unresolved_target_is_counted_and_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"docs/x.md": "x\n"})
            src = 'p = build_it(whatever)\np.write_text("x")\n'
            written, sites, unresolved = rdc.written_paths(ast.parse(src), _shelf(root))
            self.assertEqual(written, set())
            self.assertEqual((sites, unresolved), (1, 1),
                             "несложенная цель обязана быть СОЧТЕНА: иначе «не измерено» "
                             "становится неотличимо от «не пишет»")

    def test_a_state_directory_target_is_not_a_declaration(self):
        """`data/` пишет живой флот. Путь оттуда, засчитанный объявлением,
        сделал бы «пересобираемо» свойством ПРОГОНА, а не дерева."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"data/live.json": "{}\n"})
            src = 'from pathlib import Path\nP = Path("data/live.json")\nP.write_text("x")\n'
            written, sites, unresolved = rdc.written_paths(ast.parse(src), _shelf(root))
            self.assertEqual(written, set())
            self.assertEqual((sites, unresolved), (1, 1))


# ───────────────── какие инструменты мера СПРАШИВАЕТ ───────────────────────

class AsksATool(unittest.TestCase):
    FILES = {
        "scripts/adr_number.py": "x = 1\n",
        "scripts/build_tracker_board.py": "x = 1\n",
        "scripts/check_owner_gate.py": "x = 1\n",
        "spa_core/monitoring/card_acceptance.py": "x = 1\n",
        "spa_core/tests/test_neighbour.py": "x = 1\n",
        "docs/evidence/calc/a.py": "x = 1\n",
    }

    def _tools(self, source: str, asked=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, dict(self.FILES))
            return rdc.guard_tools(_shelf(root), ast.parse(source), list(asked),
                                   "spa_core/tests/test_x.py")

    def test_the_class_prober_answer_is_one_door(self):
        self.assertIn("scripts/build_tracker_board.py",
                      self._tools("x = 1\n", ["build_tracker_board.py"]))

    def test_a_rebuild_command_is_the_other_door_and_it_keeps_adr_889(self):
        """У `test_adr_index_titles.py` прибор класса отвечает `producers=[]`:
        инструмент ввозится локальным помощником. Мера называет его КОМАНДОЙ
        ПОЧИНКИ, и без этой двери известный член ADR-889 терялся."""
        source = 'MSG = "Позови `python3 scripts/adr_number.py titles --write`"\n'
        self.assertIn("scripts/adr_number.py", self._tools(source))
        self.assertEqual(self._tools(source, []).get("scripts/adr_number.py"),
                         "команда пересборки в тексте меры")

    def test_neither_door_alone_is_enough(self):
        """Вопрос пробы — «обе ли двери НУЖНЫ», а не «работает ли каждая».

        Сцена даёт КАЖДОЙ двери свой инструмент, которого ДРУГАЯ дверь не
        видит: `adr_number.py` назван только командой (форма ADR-889, где
        прибор класса отвечает `producers=[]`), `build_tracker_board.py` —
        только ответом прибора класса (форма ADR-1073, где команды нет).
        Снятие любой двери теряет СВОЙ инструмент.
        """
        tools = self._tools('M = "python3 scripts/adr_number.py titles --write"\n',
                            ["build_tracker_board.py"])
        self.assertEqual(sorted(tools),
                         ["scripts/adr_number.py", "scripts/build_tracker_board.py"])
        self.assertEqual(tools["scripts/adr_number.py"],
                         "команда пересборки в тексте меры")
        self.assertEqual(tools["scripts/build_tracker_board.py"],
                         "прибор класса: мера ЗОВЁТ")

    def test_a_py_path_that_is_only_scene_data_is_not_an_asked_tool(self):
        """ИЗМЕРЕННЫЙ дефект: у `test_python_git_ref_provenance.py` форма «любое
        имя `*.py` строкой» добирала `scripts/check_owner_gate.py` из
        `file="scripts/check_owner_gate.py"`, и известный член ADR-1112 уходил
        из `no_write_at_all` в `writes_unresolved`."""
        source = 'row = make(verdict="cache_only", file="scripts/check_owner_gate.py")\n'
        self.assertEqual(self._tools(source), {})

    def test_a_path_outside_scripts_and_spa_core_is_not_a_tool(self):
        """Инструмент обязан лежать под `scripts/` или `spa_core/`.

        Сцена подаёт имя ЧЕРЕЗ РАБОЧУЮ дверь (ответ прибора класса) — иначе
        проба была бы зелена по построению: ни одна дверь имя и так бы не
        подобрала, и ограничение по каталогу осталось бы непроверенным.
        Измеренный повод: у `test_python_git_ref_provenance.py` голые
        `a.py`/`b.py` разрешались в `docs/evidence/.../calc/`.
        """
        # дверь прибора класса: голое имя ищется только под `spa_core/`
        self.assertEqual(self._tools("x = 1\n", ["a.py"]), {})
        # дверь команды: путь назван ПОЛНОСТЬЮ и существует — отвергает уже
        # приёмщик `_add`, и это ВТОРОЙ слой, а не тот же самый
        self.assertEqual(self._tools('M = "python3 docs/evidence/calc/a.py"\n'), {})

    def test_a_neighbouring_guard_is_not_a_tool(self):
        source = 'M = "python3 spa_core/tests/test_neighbour.py"\n'
        self.assertEqual(self._tools(source), {})

    def test_a_tool_under_spa_core_is_found_by_the_class_prober_door(self):
        self.assertIn("spa_core/monitoring/card_acceptance.py",
                      self._tools("x = 1\n", ["card_acceptance.py"]))


# ──────────────────────── сам замер и его контроль ─────────────────────────

STUB = '''"""Подставной прибор класса для сцены."""
import json, pathlib
GATED = "gated"
SUBJECT = "subject"
UNMEASURED = "unmeasured"


def _payload(root):
    return json.loads((pathlib.Path(root) / "scene.json").read_text(encoding="utf-8"))


def measure(root):
    return _payload(root)["class"]


def register_doors(root):
    data = _payload(root)
    return ({n: {"title": n, "gates": [], "guards": g}
             for n, g in data["register"].items()}, ["сцена"])


def _guard_producers(entry):
    return set()
'''


def _scene(root: pathlib.Path, *, guards, register, extra=None):
    files = {
        "scripts/delivery_question_census.py": STUB,
        "scene.json": json.dumps({"class": {"guards": guards,
                                            "counts": {"subject": len(guards)}},
                                  "register": register}, ensure_ascii=False),
    }
    files.update(extra or {})
    _tree(root, files)


def _guard(path, *, verdict="subject", producers=(), body="x = 1\n"):
    return {"path": path, "verdict": verdict, "producers": list(producers),
            "ties": {}, "reason": ""}


class AssemblesTheVerdictOfEachKind(unittest.TestCase):
    def test_each_of_the_four_verdicts_is_produced_by_its_own_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guards = [
                _guard("spa_core/tests/test_writes.py", producers=["writer.py"]),
                _guard("spa_core/tests/test_unres.py", producers=["blind.py"]),
                _guard("spa_core/tests/test_nowrite.py", producers=["silent.py"]),
                _guard("spa_core/tests/test_notool.py"),
                _guard("spa_core/tests/test_control.py", verdict="gated",
                       producers=["writer.py"]),
            ]
            _scene(root, guards=guards,
                   register={"ADR-1": ["test_control.py"], "ADR-2": ["test_nowrite.py"]},
                   extra={
                       "docs/decl.md": "x\n",
                       "scripts/writer.py": ('from pathlib import Path\n'
                                             'P = Path("docs/decl.md")\n'
                                             'P.write_text("x")\n'),
                       "scripts/blind.py": 'p = compute()\np.write_text("x")\n',
                       "scripts/silent.py": 'x = 1\n',
                       "spa_core/tests/test_writes.py": "x = 1\n",
                       "spa_core/tests/test_unres.py": "x = 1\n",
                       "spa_core/tests/test_nowrite.py": "x = 1\n",
                       "spa_core/tests/test_notool.py": "x = 1\n",
                       "spa_core/tests/test_control.py": "x = 1\n",
                   })
            rdc.CONTROL["ADR-1"] = {"guard": "test_control.py",
                                    "expect": rdc.PRODUCER_WRITES, "why": "сцена"}
            rdc.CONTROL["ADR-2"] = {"guard": "test_nowrite.py",
                                    "expect": rdc.NO_WRITE_AT_ALL, "why": "сцена"}
            try:
                # членов контроля ДВА с ПРОТИВОПОЛОЖНЫМИ ожиданиями: прибор
                # отказывает, если ось не делит, и сцена обязана это обеспечить
                report = rdc.measure(root)
            finally:
                rdc.CONTROL.pop("ADR-1", None)
                rdc.CONTROL.pop("ADR-2", None)
            got = {m["path"].rsplit("/", 1)[-1]: m["verdict"] for m in report["measures"]}
            self.assertEqual(got["test_writes.py"], rdc.PRODUCER_WRITES)
            self.assertEqual(got["test_unres.py"], rdc.WRITES_UNRESOLVED)
            self.assertEqual(got["test_nowrite.py"], rdc.NO_WRITE_AT_ALL)
            self.assertEqual(got["test_notool.py"], rdc.NO_PRODUCER)

    def test_the_unknown_rest_is_a_fork_and_is_not_added_to_nothing_to_rebuild(self):
        """`writes_unresolved` обязан остаться ОТДЕЛЬНЫМ числом: приписать его к
        «пересобирать нечем» значило бы выдать неизмеренное за ответ (инв. #17)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guards = [
                _guard("spa_core/tests/test_a.py", producers=["writer.py"]),
                _guard("spa_core/tests/test_b.py", producers=["blind.py"]),
                _guard("spa_core/tests/test_c.py", producers=["silent.py"]),
            ]
            _scene(root, guards=guards,
                   register={"ADR-1": ["test_a.py"], "ADR-2": ["test_c.py"]},
                   extra={"docs/decl.md": "x\n",
                          "scripts/writer.py": ('from pathlib import Path\n'
                                                'P = Path("docs/decl.md")\n'
                                                'P.write_text("x")\n'),
                          "scripts/blind.py": 'p = compute()\np.write_text("x")\n',
                          "scripts/silent.py": 'x = 1\n',
                          "spa_core/tests/test_a.py": "x = 1\n",
                          "spa_core/tests/test_b.py": "x = 1\n",
                          "spa_core/tests/test_c.py": "x = 1\n"})
            rdc.CONTROL["ADR-1"] = {"guard": "test_a.py",
                                    "expect": rdc.PRODUCER_WRITES, "why": "сцена"}
            rdc.CONTROL["ADR-2"] = {"guard": "test_c.py",
                                    "expect": rdc.NO_WRITE_AT_ALL, "why": "сцена"}
            try:
                report = rdc.measure(root)
            finally:
                rdc.CONTROL.pop("ADR-1", None)
                rdc.CONTROL.pop("ADR-2", None)
            text = rdc.render(report, False, 5)
            self.assertEqual(report["general_door_covers"], 1)
            self.assertIn("ВИЛКА 1 … 2", text)
            self.assertIn("НЕ накрывается ТОЧНО: 1", text)
            self.assertEqual(report["code"], 1)

    def test_full_coverage_answers_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guards = [_guard("spa_core/tests/test_a.py", producers=["writer.py"]),
                      _guard("spa_core/tests/test_g.py", verdict="gated",
                             producers=["silent.py"])]
            _scene(root, guards=guards,
                   register={"ADR-1": ["test_a.py"], "ADR-2": ["test_g.py"]},
                   extra={"docs/decl.md": "x\n",
                          "scripts/writer.py": ('from pathlib import Path\n'
                                                'P = Path("docs/decl.md")\n'
                                                'P.write_text("x")\n'),
                          "scripts/silent.py": 'x = 1\n',
                          "spa_core/tests/test_a.py": "x = 1\n",
                          "spa_core/tests/test_g.py": "x = 1\n"})
            rdc.CONTROL["ADR-1"] = {"guard": "test_a.py",
                                    "expect": rdc.PRODUCER_WRITES, "why": "сцена"}
            rdc.CONTROL["ADR-2"] = {"guard": "test_g.py",
                                    "expect": rdc.NO_WRITE_AT_ALL, "why": "сцена"}
            try:
                report = rdc.measure(root)
            finally:
                rdc.CONTROL.pop("ADR-1", None)
                rdc.CONTROL.pop("ADR-2", None)
            self.assertEqual(report["code"], 0,
                             "предмет накрыт целиком ⇒ находки нет")


class RefusesInsteadOfAnsweringAboutItsOwnYardstick(unittest.TestCase):
    def test_a_register_door_absent_from_control_is_unmeasured_by_name(self):
        """Закрытый перечень известных членов зелен ПО ПОСТРОЕНИЮ (ADR-1113):
        полноту ставит РЕЕСТР, и необъявленная дверь обязана ОТКАЗАТЬ с номером."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _scene(root, guards=[_guard("spa_core/tests/test_newdoor.py", verdict="gated")],
                   register={"ADR-9999": ["test_newdoor.py"]},
                   extra={"spa_core/tests/test_newdoor.py": "x = 1\n"})
            with self.assertRaises(rdc.NotMeasured) as caught:
                rdc.measure(root)
            self.assertIn("ADR-9999", str(caught.exception))

    def test_a_control_member_with_another_verdict_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _scene(root, guards=[_guard("spa_core/tests/test_ctl.py", verdict="gated")],
                   register={"ADR-1": ["test_ctl.py"]},
                   extra={"spa_core/tests/test_ctl.py": "x = 1\n"})
            rdc.CONTROL["ADR-1"] = {"guard": "test_ctl.py",
                                    "expect": rdc.PRODUCER_WRITES, "why": "сцена"}
            try:
                with self.assertRaises(rdc.NotMeasured) as caught:
                    rdc.measure(root)
            finally:
                rdc.CONTROL.pop("ADR-1", None)
            self.assertIn("ось не подтверждена", str(caught.exception))

    def test_an_axis_that_does_not_distinguish_refuses(self):
        """Ось, срабатывающая у ВСЕХ членов одинаково, не делит — тогда число
        пересобираемых было бы ответом о МЕРКЕ, а не о классе."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guards = [_guard("spa_core/tests/test_p.py", verdict="gated"),
                      _guard("spa_core/tests/test_q.py", verdict="gated")]
            _scene(root, guards=guards,
                   register={"ADR-1": ["test_p.py"], "ADR-2": ["test_q.py"]},
                   extra={"spa_core/tests/test_p.py": "x = 1\n",
                          "spa_core/tests/test_q.py": "x = 1\n"})
            rdc.CONTROL["ADR-1"] = {"guard": "test_p.py",
                                    "expect": rdc.NO_PRODUCER, "why": "сцена"}
            rdc.CONTROL["ADR-2"] = {"guard": "test_q.py",
                                    "expect": rdc.NO_PRODUCER, "why": "сцена"}
            try:
                with self.assertRaises(rdc.NotMeasured) as caught:
                    rdc.measure(root)
            finally:
                rdc.CONTROL.pop("ADR-1", None)
                rdc.CONTROL.pop("ADR-2", None)
            self.assertIn("НЕ РАЗЛИЧАЕТ", str(caught.exception))

    def test_a_missing_class_prober_refuses_instead_of_returning_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"scene.json": "{}"})
            with self.assertRaises(rdc.NotMeasured) as caught:
                rdc.measure(root)
            self.assertIn("не ввезён", str(caught.exception))

    def test_the_class_prober_is_taken_by_path_not_by_name(self):
        """Ввоз ПО ИМЕНИ отдал бы модуль, уже лежащий в `sys.modules`, и перепись
        отвечала бы о ЧУЖОМ дереве МОЛЧА (ADR-796 внутри процесса, ADR-1127).

        СЦЕНА ОБЯЗАНА РАЗЛИЧАТЬ, и первая её редакция НЕ различала: она убирала
        прибор из дерева, поэтому отказ приходил от проверки «нет файла» ЕЩЁ ДО
        ввоза, и мутация «сначала посмотреть в `sys.modules`» переживала её
        молча (мутация M18 замера 28.11 ВЫЖИЛА — дыра сцены, не кода).

        Теперь прибор в дереве ЕСТЬ, а в `sys.modules` под тем же именем лежит
        ДРУГОЙ модуль, и проба спрашивает, ЧЕЙ ответ вернулся.
        """
        import types
        decoy = types.ModuleType("_dqc_for_rebuildable")
        decoy.measure = lambda root: {"guards": [], "counts": {}}   # type: ignore[attr-defined]
        decoy.register_doors = lambda root: ({}, [])                # type: ignore[attr-defined]
        decoy._guard_producers = lambda entry: set()                # type: ignore[attr-defined]
        decoy.WHOSE_ANSWER = "подставка из sys.modules"             # type: ignore[attr-defined]
        sys.modules["_dqc_for_rebuildable"] = decoy
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                _tree(root, {"scripts/delivery_question_census.py":
                             STUB + '\nWHOSE_ANSWER = "прибор из НАЗВАННОГО дерева"\n'})
                got = rdc.load_class_prober(root)
                self.assertEqual(got.WHOSE_ANSWER, "прибор из НАЗВАННОГО дерева",
                                 "ввоз отдал модуль из sys.modules — перепись ответила бы "
                                 "о ЧУЖОМ дереве и не сказала бы об этом ни строкой")
        finally:
            sys.modules.pop("_dqc_for_rebuildable", None)

    def test_an_absent_prober_refuses_even_with_a_decoy_in_sys_modules(self):
        """Обратная половина той же пары: прибора в дереве НЕТ, подставка в
        `sys.modules` ЕСТЬ. Ввоз по имени удался бы и выдал её за ответ."""
        import types
        sys.modules["_dqc_for_rebuildable"] = types.ModuleType("_dqc_for_rebuildable")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                _tree(root, {"scene.json": "{}"})
                with self.assertRaises(rdc.NotMeasured):
                    rdc.load_class_prober(root)
        finally:
            sys.modules.pop("_dqc_for_rebuildable", None)

    def test_a_prober_without_a_needed_door_refuses_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _tree(root, {"scripts/delivery_question_census.py": "def measure(root):\n    return {}\n"})
            with self.assertRaises(rdc.NotMeasured) as caught:
                rdc.load_class_prober(root)
            self.assertIn("register_doors", str(caught.exception))

    def test_an_unreadable_named_tree_is_code_two_not_a_silent_fallback(self):
        code = rdc.main(["--repo-root", "/нет/такого/дерева/никогда"])
        self.assertEqual(code, 2, "нечитаемое НАЗВАННОЕ дерево обязано дать код 2, "
                                  "а не молчаливый возврат к своему")


class ControlIsNotDecorative(unittest.TestCase):
    def test_control_names_both_a_rebuildable_and_a_hand_kept_known_member(self):
        """Контроль обязан нести ПРОТИВОПОЛОЖНЫЕ ожидания: перечень, у которого
        все ожидания одинаковы, не доказывает, что ось делит."""
        expectations = {entry["expect"] for entry in rdc.CONTROL.values()}
        self.assertIn(rdc.PRODUCER_WRITES, expectations)
        self.assertIn(rdc.NO_WRITE_AT_ALL, expectations)

    def test_every_control_entry_names_the_origin_of_its_expectation(self):
        for number, entry in rdc.CONTROL.items():
            self.assertTrue(entry.get("why"), f"{number}: ожидание без происхождения")
            self.assertTrue(entry["guard"].startswith("test_"), number)


if __name__ == "__main__":
    unittest.main()
