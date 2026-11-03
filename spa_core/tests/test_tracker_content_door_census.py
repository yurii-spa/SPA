#!/usr/bin/env python3
"""Положительные контроли к ДЕСЯТОЙ двери: СОДЕРЖИМОЕ ДЕРЕВА (ADR-905).

Прибор :mod:`spa_core.tests._tracker_content_door` отвечает на вопрос «какие тесты
меняют вердикт от содержимого очереди карточек, а не от кода». Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`, § «Проверка
сторожа сторожей»), поэтому здесь:

* поверхность AST сверяется с ДВУМЯ названными членами класса (цикл #1015, заказ
  G897 п. 2) — и с файлом, который очередь НЕ читает, то есть контроль в обе стороны;
* шов в файле проверяется как ОСЬ, а не как освобождение: файл, в котором шов
  встречается, с поверхности не уходит;
* сцены содержимого проверяются на настоящем каталоге очереди, и возврат — ПОБАЙТНЫЙ;
* дифференциальный замер гоняется НА ЖИВОМ ПРИБОРЕ в одноразовом дереве с тремя
  тестами, у которых ответы РАЗНЫЕ: предикат о содержимом (краснеет) · касание без
  предиката (вердикт не меняется) · уход в ``skipped`` (урок #465 — такой тест не
  краснеет и не проходит, он ИСЧЕЗАЕТ);
* отказ при ЖИВОЙ очереди проверяется в обе стороны: живую прибор трогать отказывается,
  одноразовую — берёт.

Подстрокой здесь не проходит ничего: вердикты сверяются по nodeid, а сцены — по
слепку содержимого (ADR-333).

Только stdlib, оффлайн.
"""
# Пометки `FROZEN-DATE-OK` здесь НЕТ намеренно: литеральных дат в файле нет вовсе, а
# претензия без якоря у сторожа претензии (`test_injected_clock_claim.py`) даёт НЕ
# ИЗМЕРЕНО — записка вместо замера есть ровно тот дефект, против которого он написан.
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.tests import _tracker_content_door as d

_REPO = Path(__file__).resolve().parents[2]

#: Названные циклом #1015 члены класса и дверь, которой каждый добирается до очереди.
KNOWN_MEMBERS = {
    "spa_core/tests/test_acceptance_probe_writer.py": d.DOOR_TREE_LITERAL,
    "spa_core/tests/test_inbox_acceptance_ratchet.py": d.DOOR_TREE_LITERAL,
}

_DEP = '''\
import glob, os
TRACKER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "nimbalyst-local", "tracker")


def test_at_least_one_card_declares_a_probe():
    hits = [p for p in glob.glob(os.path.join(TRACKER, "*.md"))
            if "acceptance_probe:" in open(p, encoding="utf-8").read()]
    assert hits, "ни одна карточка не объявляет пробы"
'''

_TOUCH = '''\
import os
TRACKER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "nimbalyst-local", "tracker")


def test_the_queue_can_be_listed():
    # Касание ВИДИМОЕ крюку (`os.listdir`) и при этом НЕ предикат о содержимом:
    # вердикт обязан остаться тем же при любом составе очереди.
    assert isinstance(os.listdir(TRACKER), list)
'''

_SKIP = '''\
import glob, os
import pytest
TRACKER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "nimbalyst-local", "tracker")


def test_skips_when_the_queue_is_empty():
    if not glob.glob(os.path.join(TRACKER, "*.md")):
        pytest.skip("карточек нет — мерить нечего")
    assert True
'''


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _card(tracker: Path, name: str, *, probe: str | None) -> Path:
    fm = ["type: inbox", f'title: "карточка {name}"', "status: in-progress"]
    if probe:
        fm.append(f"acceptance_probe: {probe}")
    return _write(tracker, f"{name}.md",
                  "---\n" + "\n".join(fm) + "\n---\n\n## тело\n\nстрока\n")



def _make_working_tree(root: Path) -> None:
    """Превратить одноразовый каталог в РАБОЧЕЕ ДЕРЕВО и зафиксировать содержимое.

    Урок ADR-789 (`.claude/rules/deployment.md`): сцена, которая не является
    рабочим деревом, получает от прибора отказ ЧУЖОГО гейта, и чинить надо СЦЕНУ,
    а не гейт. Прибор с замера #1021 спрашивает дерево о чистоте (содержимое есть
    его ВХОД), поэтому сцена обязана иметь вершину, с которой себя сверять.
    """
    subprocess.run(["git", "init", "-b", "main", str(root)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "сцена"], capture_output=True, check=True)


class SurfaceNamesTheRealReadersAndOnlyThem(unittest.TestCase):
    """Поверхность AST: оба названных члена класса — внутри, фикстурный читатель — вне."""

    def test_both_known_members_are_on_the_surface_with_their_door(self):
        res = d.measure_surface(_REPO)
        by_path = {f["path"]: f for f in res["files"]}
        for path, door in KNOWN_MEMBERS.items():
            with self.subTest(member=path):
                self.assertIn(path, by_path,
                              "названный циклом #1015 член класса обязан быть на поверхности")
                self.assertIn(door, by_path[path]["doors"])

    def test_a_fixture_only_reader_is_not_on_the_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "spa_core/tests/test_only_tmp.py",
                   "import tempfile\n\n\ndef test_x():\n"
                   "    with tempfile.TemporaryDirectory() as t:\n        assert t\n")
            res = d.measure_surface(root, ("spa_core/tests",))
            self.assertEqual(res["counts"]["on_surface"], 0,
                             "тест, читающий только свою песочницу, классом не является")

    def test_the_live_tracker_door_is_recognised_by_the_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "spa_core/tests/test_live_door.py",
                   "from spa_core.owner_queue.queue import TRACKER_DIR\n\n\n"
                   "def test_x():\n    assert TRACKER_DIR\n")
            res = d.measure_surface(root, ("spa_core/tests",))
            self.assertEqual(res["counts"]["live_tracker_dir"], 1)
            self.assertEqual(res["counts"]["tree_literal"], 0,
                             "дверь ЖИВОГО дерева и дверь своего дерева — РАЗНЫЕ оси")

    def test_the_seam_is_an_axis_and_never_a_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "spa_core/tests/test_mixed.py",
                   'P = "nimbalyst-local/tracker"\n'
                   'FLAG = "--tracker-dir"\n\n\ndef test_x():\n    assert P and FLAG\n')
            res = d.measure_surface(root, ("spa_core/tests",))
            self.assertEqual(res["counts"]["on_surface"], 1,
                             "шов в файле с поверхности не снимает: он живёт в одном "
                             "вызове и отсутствует в другом")
            self.assertEqual(res["counts"]["seam_present"], 1)

    def test_an_unparsable_file_is_unmeasured_never_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "spa_core/tests/test_broken.py", "def test_x(:\n    pass\n")
            res = d.measure_surface(root, ("spa_core/tests",))
            self.assertEqual(res["counts"]["unmeasured"], 1)
            self.assertIn("не разобран", res["files"][0]["unmeasured"])

    def test_a_missing_root_is_named_not_counted_as_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = d.measure_surface(Path(tmp), ("no/such/dir",))
            self.assertEqual(res["missing_roots"], ["no/such/dir"])


class OutcomeParsingKeepsSkippedDistinct(unittest.TestCase):
    """Урок #465: ушедший в ``skipped`` тест не краснеет и не проходит — он ИСЧЕЗАЕТ."""

    def test_every_verdict_form_survives_the_parser(self):
        out = d.parse_outcomes(
            "a.py::t1 PASSED [ 10%]\n"
            "a.py::t2 FAILED [ 20%]\n"
            "a.py::t3 SKIPPED [ 30%]\n"
            "a.py::t4 SUBFAILED [ 40%]\n"
            "a.py::t5 ERROR [ 50%]\n"
            "просто строка без nodeid\n")
        self.assertEqual(out, {"a.py::t1": "PASSED", "a.py::t2": "FAILED",
                               "a.py::t3": "SKIPPED", "a.py::t4": "SUBFAILED",
                               "a.py::t5": "ERROR"})

    def test_a_line_that_is_not_a_verdict_is_not_invented(self):
        self.assertEqual(d.parse_outcomes("a.py::t1 ЧТО-ТО [ 10%]\n"), {})


class ScenesChangeContentAndTheRestoreIsByteForByte(unittest.TestCase):
    """Сцена обязана менять ровно содержимое — и возвращаться побайтно."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tracker = Path(self._tmp.name) / "tracker"
        self.tracker.mkdir()
        _card(self.tracker, "с-пробой", probe="lead_channel_wiring_ok")
        _card(self.tracker, "без-пробы", probe=None)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fingerprint_notices_a_single_byte(self):
        before = d.fingerprint(self.tracker)
        path = self.tracker / "без-пробы.md"
        path.write_text(path.read_text(encoding="utf-8") + "x", encoding="utf-8")
        self.assertNotEqual(before, d.fingerprint(self.tracker))

    def test_empty_scene_removes_every_card(self):
        touched = d.apply_scene(self.tracker, d.SCENE_EMPTY)
        self.assertEqual(touched, 2)
        self.assertEqual(list(self.tracker.glob("*.md")), [])

    def test_no_criterion_scene_strips_only_the_criterion(self):
        touched = d.apply_scene(self.tracker, d.SCENE_NO_CRITERION)
        self.assertEqual(touched, 1, "тронуть обязана только карточку С критерием")
        text = (self.tracker / "с-пробой.md").read_text(encoding="utf-8")
        self.assertNotIn("acceptance_probe", text)
        self.assertIn("строка", text, "тело карточки обязано выжить")

    def test_base_scene_touches_nothing(self):
        before = d.fingerprint(self.tracker)
        self.assertEqual(d.apply_scene(self.tracker, d.SCENE_BASE), 0)
        self.assertEqual(before, d.fingerprint(self.tracker))

    def test_an_unknown_scene_refuses_loudly(self):
        with self.assertRaises(ValueError):
            d.apply_scene(self.tracker, "выдуманная")

    def test_restore_returns_the_bytes_exactly(self):
        backup = Path(self._tmp.name) / "backup"
        shutil.copytree(self.tracker, backup)
        before = d.fingerprint(self.tracker)
        d.apply_scene(self.tracker, d.SCENE_EMPTY)
        self.assertNotEqual(before, d.fingerprint(self.tracker))
        d._restore(self.tracker, backup)
        self.assertEqual(before, d.fingerprint(self.tracker))


class TheLiveQueueIsRefusedAndADisposableOneIsNot(unittest.TestCase):
    """Контроль в обе стороны: прибор правит содержимое, и живое дерево ему заказано."""

    def test_the_live_tracker_is_refused_with_a_named_reason(self):
        live = d._live_tracker_candidates()
        self.assertTrue(live, "кандидатов живой очереди обязан быть хотя бы один")
        reason = d.refuse_if_live(live[0])
        self.assertIsNotNone(reason)
        self.assertIn("ЖИВОЙ", reason)

    def test_a_disposable_tracker_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(d.refuse_if_live(Path(tmp)))

    def test_differential_refuses_a_tree_without_a_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = d.differential(Path(tmp), ["x.py"], timeout_s=30)
            self.assertEqual(res["verdict"], "unmeasured")
            self.assertIn("нет очереди", res["reason"])

    def test_differential_refuses_an_empty_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
            (root / "nimbalyst-local" / "tracker" / ".gitkeep").write_text("", encoding="utf-8")
            _make_working_tree(root)
            res = d.differential(root, [], timeout_s=30)
            self.assertEqual(res["verdict"], "unmeasured")
            self.assertIn("поверхность пуста", res["reason"])


class TheDifferentialNamesThePredicateAndSparesTheToucher(unittest.TestCase):
    """ЖИВОЙ прибор на одноразовом дереве: три теста, три РАЗНЫХ ответа.

    Сцена собрана рабочим деревом (`.claude/rules/deployment.md`, урок ADR-789): прибор
    зовёт pytest с ``cwd`` в этом дереве, и относительные пути обязаны от него и
    считаться.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "tree"
        tracker = cls.root.joinpath(*d.TRACKER_REL)
        tracker.mkdir(parents=True)
        _card(tracker, "inbox-с-пробой", probe="lead_channel_wiring_ok")
        _card(tracker, "inbox-без-пробы", probe=None)
        _write(cls.root, "t_dep.py", _DEP)
        _write(cls.root, "t_touch.py", _TOUCH)
        _write(cls.root, "t_skip.py", _SKIP)
        _make_working_tree(cls.root)
        cls.before = d.fingerprint(tracker)
        # SPA_LIVE_ROOT своего прогона убираем: иначе кандидат живой очереди
        # зависел бы от того, под какой песочницей идёт САМА батарея.
        cls._saved = os.environ.pop("SPA_LIVE_ROOT", None)
        try:
            cls.res = d.differential(cls.root, ["t_dep.py", "t_touch.py", "t_skip.py"],
                                     timeout_s=600)
        finally:
            if cls._saved is not None:
                os.environ["SPA_LIVE_ROOT"] = cls._saved
        cls.after = d.fingerprint(tracker)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_measurement_was_obtained_at_all(self):
        self.assertEqual(self.res["verdict"], "measured",
                         self.res.get("reason", "") + str(self.res.get("observe", "")))

    def test_the_run_observed_surface_holds_every_toucher(self):
        self.assertEqual(sorted(self.res["subset"]),
                         ["t_dep.py", "t_skip.py", "t_touch.py"],
                         "крюк обязан увидеть все три касания очереди")

    def test_a_stat_only_touch_is_invisible_and_the_gap_is_measured(self):
        """Дыра крюка ИЗМЕРЕНА, а не умолчана: ``os.stat`` событие не поднимает.

        Контроль нужен в эту сторону тоже: пока дыра закреплена замером, «в
        подмножестве нет» отличается от «не касался». Починит её сборка
        интерпретатора, которая событие поднимает, — и тогда этот тест покраснеет
        ПЕРВЫМ, то есть скажет о починке вслух.
        """
        seen: list[str] = []

        def hook(event: str, args: tuple) -> None:
            if event in d.WATCHED_EVENTS:
                seen.append(event)

        with tempfile.TemporaryDirectory() as tmp:
            # Крюк снять нельзя по построению, поэтому он дешёвый и живёт до конца
            # сессии; замер снимается ровно на одном вызове.
            sys.addaudithook(hook)
            seen.clear()
            os.path.isdir(tmp)
        self.assertNotIn("os.stat", list(seen),
                         "событие os.stat поднялось — дыра крюка закрыта, "
                         "и об этом надо сказать в приборе, а не промолчать")

    def test_the_class_is_not_empty_on_a_scene_that_has_a_predicate(self):
        self.assertFalse(self.res["class_empty"])

    def test_the_content_predicate_is_named_by_both_scenes(self):
        rows = {r["nodeid"]: r for r in self.res["candidates"]}
        node = "t_dep.py::test_at_least_one_card_declares_a_probe"
        self.assertIn(node, rows, rows)
        self.assertEqual(rows[node]["base"], "PASSED")
        self.assertEqual(rows[node]["scenes"].get(d.SCENE_EMPTY), "FAILED")
        self.assertEqual(rows[node]["scenes"].get(d.SCENE_NO_CRITERION), "FAILED",
                         "снятие критерия обязано краснить предикат о критерии")

    def test_the_vanishing_test_is_named_as_skipped_not_lost(self):
        rows = {r["nodeid"]: r for r in self.res["candidates"]}
        node = "t_skip.py::test_skips_when_the_queue_is_empty"
        self.assertIn(node, rows, "тест, ИСЧЕЗАЮЩИЙ в сцене, обязан быть назван (урок #465)")
        self.assertEqual(rows[node]["scenes"].get(d.SCENE_EMPTY), "SKIPPED")
        self.assertNotIn(d.SCENE_NO_CRITERION, rows[node]["scenes"],
                         "карточки на месте — исчезать не от чего")

    def test_a_mere_toucher_is_not_a_member_of_the_class(self):
        names = {r["nodeid"] for r in self.res["candidates"]}
        self.assertNotIn("t_touch.py::test_the_queue_can_be_listed", names,
                         "касание очереди предикатом о её содержимом не является")

    def test_nothing_was_called_noisy_on_a_deterministic_scene(self):
        self.assertEqual(self.res.get("noisy", []), [])

    def test_the_queue_came_back_byte_for_byte(self):
        self.assertEqual(self.before, self.after)

    def test_every_scene_reports_how_many_cards_it_touched(self):
        by_scene = {s["scene"]: s for s in self.res["scenes"]}
        self.assertEqual(by_scene[d.SCENE_EMPTY]["cards_touched"], 2)
        self.assertEqual(by_scene[d.SCENE_NO_CRITERION]["cards_touched"], 1)


class TheDeclarationWriterIsAProjectionOfAMeasurement(unittest.TestCase):
    """ОБЪЯВЛЕНИЕ класса (ADR-907) обязано быть проекцией ЗАМЕРА, а не списком из головы.

    Писатель один (`declaration_from_measurement`), и каждый его отказ ниже
    воспроизводит состояние, при котором объявление стало бы ЛОЖНЫМ. Контроль в
    обратную сторону — последний тест: исправный замер превращается в объявление
    молча, и `measured_in` у каждого имени заполняет ПИСАТЕЛЬ, а не рука.
    """

    #: Исправный замер в той же форме, что печатает `--differential --json`.
    GOOD = {
        "verdict": "measured",
        "class_empty": False,
        "base_verdicts": 920,
        "noisy": [],
        "scenes": [{"scene": "empty", "changed": 2}, {"scene": "no_criterion", "changed": 1}],
        "candidates": [
            {"nodeid": "spa_core/tests/test_b.py::test_two", "base": "FAILED",
             "scenes": {"empty": "PASSED"}, "base_again": "FAILED"},
            {"nodeid": "spa_core/tests/test_a.py::test_one", "base": "PASSED",
             "scenes": {"empty": "FAILED"}, "base_again": "PASSED"},
        ],
        "surface": {"files": [
            {"path": "spa_core/tests/test_a.py", "doors": ["tree_literal"]},
            {"path": "spa_core/tests/test_b.py", "doors": ["live_tracker_dir"]},
        ]},
    }

    def _emit(self, **over):
        doc = dict(self.GOOD)
        doc.update(over)
        kw = {"sha": "76c050ab4", "minutes_per_side": 85, "instrument": "прибор"}
        kw.update({k: v for k, v in over.items() if k in kw})
        for k in kw:
            doc.pop(k, None)
        return d.declaration_from_measurement(doc, **kw)

    def test_an_unmeasured_run_cannot_become_a_declaration(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._emit(verdict="unmeasured", reason="дерева нет")
        self.assertIn("не состоялся", str(ctx.exception))

    def test_noise_in_the_measurement_is_refused_not_dropped(self) -> None:
        # Шумное имя членом класса не является; выбросить его молча означало бы
        # объявить замер чище, чем он есть.
        with self.assertRaises(ValueError) as ctx:
            self._emit(noisy=[{"nodeid": "spa_core/tests/test_x.py::test_shum"}])
        self.assertIn("ШУМ", str(ctx.exception))
        self.assertIn("test_shum", str(ctx.exception))

    def test_an_empty_class_is_refused_because_an_empty_file_is_not_a_proof(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._emit(candidates=[])
        self.assertIn("ПУСТ", str(ctx.exception))

    def test_a_declaration_without_the_sha_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._emit(sha="")
        self.assertIn("sha", str(ctx.exception))

    def test_a_declaration_without_the_price_is_refused(self) -> None:
        # Именно незнание цены заставило цикл #1018 перемерять базу заново.
        with self.assertRaises(ValueError) as ctx:
            self._emit(minutes_per_side=0)
        self.assertIn("цена", str(ctx.exception))

    def test_a_good_measurement_becomes_a_declaration_with_filled_provenance(self) -> None:
        decl = self._emit()
        self.assertEqual(decl["schema"], d.DECLARATION_SCHEMA)
        self.assertEqual(decl["upper_bound"], 2)
        self.assertEqual(decl["measured_on_sha"], "76c050ab4")
        self.assertEqual(decl["wall_clock_minutes_per_side"], 85)
        names = [m["nodeid"] for m in decl["members"]]
        self.assertEqual(names, sorted(names), "перечень обязан быть устойчив к порядку")
        for m in decl["members"]:
            self.assertTrue(m["measured_in"], "писатель обязан заполнить замер сам")
            self.assertIn("76c050ab4", m["measured_in"])
        doors = {m["nodeid"]: m["door"] for m in decl["members"]}
        self.assertEqual(doors["spa_core/tests/test_a.py::test_one"], "tree_literal")
        self.assertEqual(doors["spa_core/tests/test_b.py::test_two"], "live_tracker_dir")

    def test_a_file_the_surface_is_silent_about_is_not_called_doorless(self) -> None:
        # Третий исход (инв. #17): «поверхность молчит» не равно «двери нет».
        decl = self._emit(surface={"files": []})
        self.assertTrue(all("НЕ ИЗМЕРЕНО" in m["door"] for m in decl["members"]))


class TheMeasuringTreeMustBeCleanOrTheClassIsUnmeasured(unittest.TestCase):
    """Содержимое дерева замера есть ВХОД этого прибора, а не его обстановка.

    Авария, которую воспроизводят эти контроли (замер #1021): сироты #1019/#1020
    мерили класс в дереве со своей незакоммиченной правкой карточки, и их замер
    назвал членом класса `test_live_board_matches_live_cards` с направлением
    `FAILED→PASSED` — тест был красен ОТ ПРАВКИ, а не от `origin/main`. Замер
    #1018 того же класса этого имени не назвал вовсе: два «воспроизведённых»
    замера расходились СОСТАВОМ по причине, не имеющей отношения к коду.
    """

    @staticmethod
    def _runner(stdout: str = "", rc: int = 0, stderr: str = "", boom=None):
        def run(cmd):
            if boom is not None:
                raise boom
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
        return run

    def test_a_clean_tree_is_not_refused(self) -> None:
        self.assertIsNone(d.refuse_if_dirty(Path("/нет/дерева"),
                                            runner=self._runner(stdout="")))

    def test_a_dirty_tree_is_refused_and_the_culprit_is_NAMED(self) -> None:
        reason = d.refuse_if_dirty(
            Path("/дерево"),
            runner=self._runner(stdout=" M nimbalyst-local/tracker/inbox-карточка.md\n"))
        self.assertIsNotNone(reason)
        self.assertIn("inbox-карточка.md", reason)
        self.assertIn("--allow-dirty-tree", reason)

    def test_a_long_dirty_list_is_truncated_but_counted(self) -> None:
        many = "".join(f" M файл-{i}.py\n" for i in range(d.DIRTY_PATHS_SHOWN + 5))
        reason = d.refuse_if_dirty(Path("/дерево"), runner=self._runner(stdout=many))
        self.assertIn(f"{d.DIRTY_PATHS_SHOWN + 5} путь(ей)", reason)
        self.assertIn("ещё 5", reason)

    def test_git_failing_is_unmeasured_not_clean(self) -> None:
        # «git не ответил» и «дерево чисто» — РАЗНЫЕ утверждения (инв. #17).
        reason = d.refuse_if_dirty(Path("/дерево"),
                                   runner=self._runner(rc=128, stderr="not a git repository"))
        self.assertIn("НЕ ИЗМЕРЕНО", reason)
        self.assertIn("128", reason)

    def test_an_exploding_runner_is_unmeasured_not_clean(self) -> None:
        reason = d.refuse_if_dirty(Path("/дерево"),
                                   runner=self._runner(boom=OSError("git не найден")))
        self.assertIn("НЕ ИЗМЕРЕНО", reason)
        self.assertIn("git не найден", reason)

    def test_the_differential_refuses_a_really_dirty_tree(self) -> None:
        # Контроль на НАСТОЯЩЕМ читателе: настоящий git, настоящее дерево, настоящая
        # правка. Сцена на собранном руками словаре мерила бы свой словарь (#944/#945).
        root = Path(tempfile.mkdtemp(prefix="tcd_dirty_"))
        try:
            subprocess.run(["git", "init", "-b", "main", str(root)],
                           capture_output=True, check=True)
            tracker = root.joinpath(*d.TRACKER_REL)
            tracker.mkdir(parents=True)
            card = tracker / "inbox-проба.md"
            card.write_text("---\nstatus: new\n---\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"],
                           capture_output=True, check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-m", "скамья"],
                           capture_output=True, check=True)
            # ЧИСТО: отказа этой двери нет (замер идёт дальше и упирается в другое).
            clean = d.differential(root, files=[], timeout_s=5)
            self.assertNotIn("НЕ ЧИСТО", clean.get("reason", ""))
            # ГРЯЗНО: та же сцена, одна правка — и дверь отказывает ИМЕНЕМ.
            card.write_text("---\nstatus: in-progress\n---\n", encoding="utf-8")
            dirty = d.differential(root, files=[], timeout_s=5)
            self.assertEqual(dirty["verdict"], "unmeasured")
            self.assertIn("НЕ ЧИСТО", dirty["reason"])
            self.assertIn("inbox-проба.md", dirty["reason"])
            # ОБХОД объявлен: та же грязь, но отказ уже НЕ про чистоту.
            allowed = d.differential(root, files=[], timeout_s=5, allow_dirty=True)
            self.assertEqual(allowed["verdict"], "unmeasured")
            self.assertNotIn("НЕ ЧИСТО", allowed["reason"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
