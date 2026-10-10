#!/usr/bin/env python3
"""Контроли прибора «вторая сторона цены оси D» — заказ **G111 п. 3** (ADR-536).

Каждый тест — ОДНО порванное звено с названным именем, либо положительный контроль
свойства, на котором замер держится:

* **архив уборщика переносит ИСХОДНУЮ отметку записи** — на этом стоит единственная
  дверь, переживающая снятие дерева, и проверяется она ПРОГОНОМ настоящего
  `reap_stale_worktrees.archive`, а не чтением документации `shutil.copy2`;
* **общее живое дерево — ОТКАЗ атрибуции, а не пробел**: отметку прод-дерева пишет
  флот круглосуточно, и взять её за span значило бы выдать такт дневного цикла за
  работу сессии. Вопрос задаётся ДО двери живого дерева, и у порядка свой контроль;
* **«следа не осталось» нельзя изготовить из своей слепоты**: нечитаемый архив или
  нечитаемые квитанции — ОТКАЗ замера (fail-CLOSED), иначе объявление «класс
  неизмерим» получилось бы из непрочитанного файла;
* **запись ДО захвата — ИЗМЕРЕННЫЙ НУЛЬ**, а не «не измерено» (инв. #17);
* **колонка видимой стороны приходит ОТ СОСЕДА** (`claim_release_census`), и это
  проверено подменой соседа, а не сверкой числа с собой (ADR-220).

Время здесь — ВХОД, а не окружение: якорь `_NOW` связан с именем, от него ПРОИСХОДЯТ
и отметки записей журнала (`_stamp`), и отметки файлов сцены (`_touch`), и он же
уезжает аргументом `now=` в `build_report`. Реестр git инъектируется (`git=`), поэтому
дверь к ОС на этом пути тоже закрыта.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` (datetime-литерал) связан с именем;
# от него вычитанием происходят отметки записей журнала (`_stamp`) и отметки файлов
# сцены (`_touch`), и он же передаётся аргументом `now=` в `build_report`. Реестр
# деревьев инъектируется параметром `git=`, живой календарь на вердикт не влияет.
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import claim_release_census as census
from spa_core.monitoring import unannounced_span as uas

#: Якорь времени сцены. ВСЕ отметки — и записей, и файлов — происходят отсюда.
_NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)

#: Соседи грузятся из НАСТОЯЩЕГО дерева один раз: сцены лежат в `mkdtemp`, где
#: скриптов-соседей нет по построению, а подменять их заглушкой значило бы судить
#: о приборе вместо правила.
_KIN = uas.load_neighbours(ROOT)

_MAIN_TREE = "/scene/main-tree"


def _stamp(hours_ago: float) -> str:
    """Отметка времени записи, ПРОИСХОДЯЩАЯ от якоря сцены."""
    return (_NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(hours_ago: float) -> float:
    """Отметка файла, ПРОИСХОДЯЩАЯ от того же якоря."""
    return (_NOW - timedelta(hours=hours_ago)).timestamp()


def _touch(path: Path, hours_ago: float) -> Path:
    """Файл со ЗАДАННЫМ временем записи. Обе отметки от якоря — часы хоста не спрошены."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (_epoch(hours_ago), _epoch(hours_ago)))
    return path


def _record(card, state="claim", *, hours_ago, label="cycle-1", files=(), cwd=None):
    row = {"ts": _stamp(hours_ago), "session": label, "summary": "s",
           "files": list(files), "verified": "v", "card": card, "card_state": state}
    if cwd is not None:
        row["cwd"] = cwd
    return row


def _git_registry(paths=(_MAIN_TREE,), *, rc=0):
    """Поддельный `git worktree list --porcelain`. Первым идёт ГЛАВНОЕ дерево."""
    def git(cwd, *args):
        if rc != 0:
            return rc, "", "fatal: not a git repository"
        return 0, "".join(f"worktree {p}\nHEAD 0000\n\n" for p in paths), ""
    return git


class Scene:
    """Одноразовая сцена: корень дерева, журнал, архив уборщика, квитанции."""

    def __init__(self, records, *, archive_trees=(), ledger_trees=()):
        self.root = Path(tempfile.mkdtemp(prefix="uas_scene_"))
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.journal = self.root / "data" / "session_changes.jsonl"
        self.journal.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8")
        self.archive_root = self.root / "archive"
        self.archive_root.mkdir(parents=True, exist_ok=True)
        for name, tree, hours_ago in archive_trees:
            dest = self.archive_root / name
            (dest).mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text(
                json.dumps({"worktree": tree, "base": "origin/main",
                            "archived_at": "scene", "paths": []}), encoding="utf-8")
            if hours_ago is not None:
                _touch(dest / "files" / "spa_core" / "x.py", hours_ago)
        self.ledger = self.root / uas.LEDGER_REL
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(
            "".join(json.dumps({"ts": "scene", "worktree": t}) + "\n"
                    for t in ledger_trees), encoding="utf-8")

    def report(self, **kw):
        kw.setdefault("git", _git_registry())
        kw.setdefault("journal_path", self.journal)
        kw.setdefault("archive_root", self.archive_root)
        kw.setdefault("ledger_path", self.ledger)
        kw.setdefault("neighbours", _KIN)
        return uas.build_report(self.root, now=_NOW, **kw)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _one_row(report):
    rows = report["rows"]
    assert len(rows) == 1, f"сцена обязана дать РОВНО одну строку, дала {len(rows)}"
    return rows[0]


class LiveTreeDoor(unittest.TestCase):
    """Дверь 1: дерево ещё на диске."""

    def setUp(self):
        self.tree = Path(tempfile.mkdtemp(prefix="uas_tree_"))
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_span_is_measured_from_the_newest_write_in_the_live_tree(self):
        _touch(self.tree / "spa_core" / "a.py", 7.0)
        _touch(self.tree / "spa_core" / "b.py", 3.0)   # самая свежая запись
        scene = self._scene([_record("card-a", hours_ago=10.0,
                                     files=[str(self.tree / "spa_core" / "a.py")])])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.DOOR_TREE)
        self.assertAlmostEqual(row["span_hours"], 7.0, places=2)
        self.assertTrue(row["wrote_after_claim"])

    def test_a_write_BEFORE_the_claim_is_a_MEASURED_ZERO_not_unmeasured(self):
        """ИЗМЕРЕННЫЙ нуль и «не измерено» — разные исходы (инв. #17)."""
        _touch(self.tree / "spa_core" / "a.py", 20.0)
        scene = self._scene([_record("card-a", hours_ago=10.0,
                                     files=[str(self.tree / "spa_core" / "a.py")])])
        report = scene.report()
        row = _one_row(report)
        self.assertEqual(row["outcome"], uas.DOOR_TREE, "дверь ОТВЕТИЛА — это замер")
        self.assertFalse(row["wrote_after_claim"])
        self.assertLess(row["span_hours"], 0)
        self.assertEqual(report["spans"]["measured_zero_no_write_after_claim"], 1)
        self.assertEqual(report["spans"]["wrote_after_claim"], 0)
        for step in report["ladder"]["ladder"]:
            self.assertEqual(step["invisible_sole_identity"], 0,
                             "запись до захвата срок не оборвал бы")

    def test_a_write_at_EXACTLY_the_claim_moment_is_not_a_write_AFTER_it(self):
        """Граница строгая: запись В МОМЕНТ захвата продолжением работы не является."""
        _touch(self.tree / "spa_core" / "a.py", 10.0)
        scene = self._scene([_record("card-a", hours_ago=10.0,
                                     files=[str(self.tree / "spa_core" / "a.py")])])
        report = scene.report()
        row = _one_row(report)
        self.assertEqual(row["outcome"], uas.DOOR_TREE)
        self.assertEqual(row["span_hours"], 0.0)
        self.assertFalse(row["wrote_after_claim"],
                         "`>= 0` зачёл бы нулевой span как продолжение работы")
        self.assertEqual(report["spans"]["measured_zero_no_write_after_claim"], 1)

    def test_a_span_EXACTLY_equal_to_the_rung_is_NOT_cut_by_it(self):
        """Срок обрывает работу, которая ПЕРЕЖИЛА его, а не дотянула ровно до него."""
        _touch(self.tree / "spa_core" / "a.py", 4.0)
        scene = self._scene([_record("card-a", hours_ago=10.0,
                                     files=[str(self.tree / "spa_core" / "a.py")])])
        report = scene.report()
        self.assertEqual(_one_row(report)["span_hours"], 6.0, "сцена обязана дать РОВНО срок")
        rungs = {s["ttl_hours"]: s["invisible_sole_identity"]
                 for s in report["ladder"]["ladder"]}
        self.assertEqual(rungs[6], 0, "`>=` зачёл бы ровно дотянувшую работу оборванной")
        self.assertEqual(report["spans"]["wrote_after_claim"], 1,
                         "строка ИЗМЕРЕНА — иначе нуль на ступени был бы о пустой сцене")

    def test_skipped_directories_are_NOT_a_session_write(self):
        """`data/` пишет живой цикл, `__pycache__` — интерпретатор; это не работа сессии."""
        _touch(self.tree / "data" / "live.json", 1.0)
        _touch(self.tree / "spa_core" / "__pycache__" / "x.pyc", 1.0)
        stamp, why = uas.newest_write(self.tree)
        self.assertIsNone(stamp)
        self.assertIsNotNone(why)

    def test_newest_write_returns_NONE_with_a_reason_never_zero(self):
        """Нуль эпохи читался бы как «писали в 1970», а не как «не писали»."""
        stamp, why = uas.newest_write(self.tree)
        self.assertIsNone(stamp)
        self.assertIn("времени записи нет", why)


class ArchiveDoor(unittest.TestCase):
    """Дверь 2: дерево снято, но архив уборщика его отметку сохранил."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_span_is_measured_from_the_archive_when_the_tree_is_GONE(self):
        gone = "/tmp/uas_gone_tree"
        scene = self._scene(
            [_record("card-a", hours_ago=12.0, files=[gone + "/spa_core/a.py"])],
            archive_trees=[("gone-20261010T000000Z", gone, 4.0)])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.DOOR_ARCHIVE)
        self.assertAlmostEqual(row["span_hours"], 8.0, places=2)

    def test_the_NEWEST_of_several_archives_of_one_tree_wins(self):
        gone = "/tmp/uas_gone_two"
        scene = self._scene(
            [_record("card-a", hours_ago=20.0, files=[gone + "/spa_core/a.py"])],
            archive_trees=[("gone-A", gone, 15.0), ("gone-B", gone, 6.0)])
        row = _one_row(scene.report())
        self.assertAlmostEqual(row["span_hours"], 14.0, places=2)

    def test_archive_WITHOUT_files_is_a_record_without_write_times(self):
        """Архив без `files` говорит «работы не было», а не «когда писали»."""
        gone = "/tmp/uas_gone_empty"
        scene = self._scene(
            [_record("card-a", hours_ago=12.0, files=[gone + "/spa_core/a.py"])],
            archive_trees=[("gone-empty", gone, None)])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.UNM_RECORD_NO_TIMES)
        self.assertIn("архив уборщика", row["reason"])
        self.assertIsNone(row["span_hours"])

    def test_archive_key_is_the_tree_from_the_MANIFEST_not_the_directory_name(self):
        """Два разных дерева с одним базовым именем склеились бы под именем каталога."""
        gone = "/tmp/other/uas_same_basename"
        scene = self._scene(
            [_record("card-a", hours_ago=12.0, files=[gone + "/spa_core/a.py"])],
            archive_trees=[("uas_same_basename-20261010T000000Z",
                            "/tmp/elsewhere/uas_same_basename", 4.0)])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.UNM_NO_TRACE,
                         "манифест называет ДРУГОЕ дерево — склейка по имени каталога "
                         "выдала бы чужую отметку за свою")

    def test_the_archive_matches_the_tree_in_the_OTHER_SPELLING_of_tmp(self):
        """macOS отдаёт `/tmp/x` и `/private/tmp/x` за ОДИН каталог (мерка соседа).

        Журнал объявил одно написание, уборщик записал другое — побайтовое сравнение
        ответило бы «следа не осталось» и изготовило бы объявление класса неизмеримым
        из разницы в написании.
        """
        scene = self._scene(
            [_record("card-a", hours_ago=12.0,
                     files=["/tmp/uas_spelling/spa_core/a.py"])],
            archive_trees=[("spelling", "/private/tmp/uas_spelling", 4.0)])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.DOOR_ARCHIVE)
        self.assertAlmostEqual(row["span_hours"], 8.0, places=2)

    def test_the_REAL_reaper_archive_keeps_the_ORIGINAL_write_time(self):
        """Положительный контроль свойства, на котором стоит вся дверь 2.

        Гоняется НАСТОЯЩИЙ `reap_stale_worktrees.archive` (его `git` инъектирован),
        и span читается прибором из того, что архив реально записал. Если копирование
        перестанет переносить отметку, тест покраснеет — в отличие от утверждения
        «сосед зовёт copy2», которое слепо к поведению.
        """
        reaper = _KIN["reaper"]
        wt = Path(tempfile.mkdtemp(prefix="uas_wt_"))
        self.addCleanup(shutil.rmtree, wt, ignore_errors=True)
        _touch(wt / "spa_core" / "work.py", 5.0)
        archive_root = Path(tempfile.mkdtemp(prefix="uas_arch_"))
        self.addCleanup(shutil.rmtree, archive_root, ignore_errors=True)
        dest, why = reaper.archive(str(wt), "origin/main",
                                   [{"path": "spa_core/work.py", "verdict": "work"}],
                                   archive_root=archive_root,
                                   git=lambda *a, **k: (0, "", ""),
                                   stamp="20261010T000000Z")
        self.assertIsNone(why, f"архив не записан: {why}")
        self.assertIsNotNone(dest)
        scene = self._scene([_record("card-a", hours_ago=9.0,
                                     files=[str(wt / "spa_core" / "work.py")])])
        shutil.rmtree(wt, ignore_errors=True)       # дерево снято, остался архив
        row = _one_row(scene.report(archive_root=archive_root))
        self.assertEqual(row["outcome"], uas.DOOR_ARCHIVE)
        self.assertAlmostEqual(row["span_hours"], 4.0, places=1)


class SharedLivingTree(unittest.TestCase):
    """Общее живое дерево — ОТКАЗ атрибуции, и спрашивается он ПЕРВЫМ."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_the_main_tree_is_refused_even_though_its_writes_are_FRESH(self):
        main = Path(tempfile.mkdtemp(prefix="uas_main_"))
        self.addCleanup(shutil.rmtree, main, ignore_errors=True)
        _touch(main / "spa_core" / "a.py", 0.5)      # флот писал полчаса назад
        scene = self._scene([_record("card-a", hours_ago=800.0,
                                     files=[str(main / "spa_core" / "a.py")])])
        report = scene.report(git=_git_registry((str(main),)))
        row = _one_row(report)
        self.assertEqual(row["outcome"], uas.UNM_SHARED_LIVING,
                         "иначе такт дневного цикла уехал бы в span как работа сессии")
        self.assertIsNone(row["span_hours"])
        self.assertEqual(report["doors"]["counts"][uas.DOOR_TREE], 0,
                         "вопрос об общем дереве обязан стоять ДО двери живого дерева")
        for step in report["ladder"]["ladder"]:
            self.assertEqual(step["invisible_sole_identity"], 0)
            self.assertEqual(step["invisible_multiple_identities"], 0)

    def test_a_NON_main_tree_at_the_same_path_shape_is_measured(self):
        """Контроль в обратную сторону: отказ держится на вердикте git, не на форме пути."""
        tree = Path(tempfile.mkdtemp(prefix="uas_notmain_"))
        self.addCleanup(shutil.rmtree, tree, ignore_errors=True)
        _touch(tree / "spa_core" / "a.py", 2.0)
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=[str(tree / "spa_core" / "a.py")])])
        row = _one_row(scene.report(git=_git_registry((_MAIN_TREE, str(tree)))))
        self.assertEqual(row["outcome"], uas.DOOR_TREE)


class UnmeasuredOutcomes(unittest.TestCase):
    """Остаток объявлен ПО ПРИЧИНАМ, и ни одна причина не подменяет другую."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_tree_unnamed_is_its_own_outcome(self):
        scene = self._scene([_record("card-a", hours_ago=5.0, files=["relative/path.py"])])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.UNM_TREE_UNNAMED)
        self.assertIsNone(row["tree"])
        self.assertIsNone(row["attribution"], "атрибуция без дерева предмета не имеет")

    def test_no_trace_DECLARES_the_class_unmeasurable(self):
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=["/tmp/uas_vanished/spa_core/a.py"])])
        report = scene.report()
        self.assertEqual(_one_row(report)["outcome"], uas.UNM_NO_TRACE)
        self.assertEqual(report["status"], uas.STATUS_CLASS_UNMEASURABLE)
        self.assertEqual(uas.exit_code_for(report), 1)
        self.assertTrue(report["measured"], "объявление класса неизмеримым ЕСТЬ замер")

    def test_a_ledger_receipt_is_a_record_without_write_times_not_no_trace(self):
        gone = "/tmp/uas_reaped_only"
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=[gone + "/spa_core/a.py"])],
                            ledger_trees=[gone])
        row = _one_row(scene.report())
        self.assertEqual(row["outcome"], uas.UNM_RECORD_NO_TIMES)
        self.assertIn("квитанция снятия", row["reason"])

    def test_a_git_registration_outlives_the_directory_and_is_named(self):
        gone = "/tmp/uas_registered_gone"
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=[gone + "/spa_core/a.py"])])
        row = _one_row(scene.report(git=_git_registry((_MAIN_TREE, gone))))
        self.assertEqual(row["outcome"], uas.UNM_RECORD_NO_TIMES)
        self.assertIn("регистрация git", row["reason"])

    def test_every_declared_outcome_is_counted_and_the_sum_closes(self):
        rows = [
            _record("c1", hours_ago=5.0, files=["relative/x.py"]),
            _record("c2", hours_ago=5.0, files=["/tmp/uas_nowhere/spa_core/a.py"]),
            _record("c3", hours_ago=5.0, files=["/tmp/uas_reaped/spa_core/a.py"]),
        ]
        scene = self._scene(rows, ledger_trees=["/tmp/uas_reaped"])
        report = scene.report()
        counts = report["doors"]["counts"]
        self.assertEqual(sum(counts.values()), len(report["rows"]))
        self.assertEqual(report["doors"]["unmeasured"], 3)
        self.assertEqual(report["doors"]["measured"], 0)
        self.assertEqual(report["doors"]["measurable_share_pct"], 0.0)


class FailClosed(unittest.TestCase):
    """Своя слепота не имеет права выглядеть измеренным исходом."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_an_unreadable_git_registry_FAILS_CLOSED(self):
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=["/tmp/uas_x/spa_core/a.py"])])
        report = scene.report(git=_git_registry(rc=128))
        self.assertFalse(report["measured"])
        self.assertEqual(report["status"], uas.STATUS_UNMEASURED)
        self.assertIn("ОБЩЕЕ", report["reason"])
        self.assertEqual(uas.exit_code_for(report), 2)

    def test_an_unreadable_ARCHIVE_root_FAILS_CLOSED_not_no_trace(self):
        """Иначе «следа не осталось» получалось бы из непрочитанного каталога."""
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=["/tmp/uas_y/spa_core/a.py"])])
        report = scene.report(archive_root=scene.root / "no-such-archive")
        self.assertFalse(report["measured"])
        self.assertIn("было бы выдумкой", report["reason"])
        self.assertEqual(uas.exit_code_for(report), 2)

    def test_unreadable_LEDGER_fails_closed_too(self):
        scene = self._scene([_record("card-a", hours_ago=5.0,
                                     files=["/tmp/uas_z/spa_core/a.py"])])
        report = scene.report(ledger_path=scene.root / "no-such-ledger.jsonl")
        self.assertFalse(report["measured"])
        self.assertIn("было бы выдумкой", report["reason"])

    def test_an_unreadable_journal_is_UNMEASURED(self):
        scene = self._scene([])
        report = scene.report(journal_path=scene.root / "no-such-journal.jsonl")
        self.assertFalse(report["measured"])
        self.assertIn("журнал не прочитан", report["reason"])

    def test_a_missing_neighbour_is_UNMEASURED_not_a_hand_written_substitute(self):
        empty = Path(tempfile.mkdtemp(prefix="uas_noroot_"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        report = uas.build_report(empty, now=_NOW)
        self.assertFalse(report["measured"])
        self.assertIn("соседние мерки", report["reason"])

    def test_zero_open_claims_is_a_NAMED_third_outcome_not_class_unmeasurable(self):
        """Предмета нет — и это не то же, что «класс неизмерим»."""
        scene = self._scene([_record("card-a", "claim", hours_ago=5.0),
                             _record("card-a", "done", hours_ago=4.0)])
        report = scene.report()
        self.assertFalse(report["measured"])
        self.assertIn("не имеет предмета", report["reason"])
        self.assertNotEqual(report["status"], uas.STATUS_CLASS_UNMEASURABLE)


class BorrowedMeasures(unittest.TestCase):
    """Мерки соседа взяты ЦЕЛИКОМ, и это проверено подменой, а не сверкой с собой."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_the_visible_column_comes_FROM_THE_NEIGHBOUR(self):
        """Подменяем соседскую лестницу — колонка видимой стороны обязана поехать за ней."""
        scene = self._scene([_record("c1", hours_ago=5.0,
                                     files=["/tmp/uas_q/spa_core/a.py"])])
        original = census.measure_expiry_ladder
        sentinel = -777

        def fake(open_rows, latencies, *, ladder=census.TTL_LADDER_HOURS):
            doc = original(open_rows, latencies, ladder=ladder)
            for step in doc["ladder"]:
                step["would_have_cut_self_closing_work"] = sentinel
            return doc

        census.measure_expiry_ladder = fake
        try:
            report = scene.report()
        finally:
            census.measure_expiry_ladder = original
        self.assertTrue(report["ladder"]["ladder"])
        for step in report["ladder"]["ladder"]:
            self.assertEqual(step["visible_self_closing"], sentinel,
                             "колонка посчитана СВОИМ правилом — это второй экземпляр "
                             "чужого замера (ADR-220)")

    def test_the_ttl_grid_IS_the_neighbours_object_not_a_literal_copy(self):
        import inspect
        default = inspect.signature(uas.measure_ladder).parameters["ladder"].default
        self.assertIs(default, census.TTL_LADDER_HOURS,
                      "своя копия сетки сроков разошлась бы с соседом молча")

    def test_the_population_is_the_SAME_as_the_neighbours_open_claims(self):
        """Прибор уточняет цену ТОГО ЖЕ замера — иначе уточнял бы чужую."""
        records = [
            _record("c1", hours_ago=9.0, files=["/tmp/uas_p1/spa_core/a.py"]),
            _record("c2", hours_ago=8.0, files=["/tmp/uas_p2/spa_core/a.py"]),
            _record("c2", "done", hours_ago=7.0, files=["/tmp/uas_p2/spa_core/a.py"]),
        ]
        scene = self._scene(records)
        mine = scene.report()
        theirs = census.build_report(scene.root, now=_NOW, journal_path=scene.journal,
                                     ps=lambda pid: (1, ""),
                                     cmd_probe=lambda pid: (1, ""),
                                     neighbours={"guard": _KIN["guard"],
                                                 "sibling": _KIN["sibling"],
                                                 "missing": []})
        self.assertEqual(mine["population"]["open_claims"],
                         theirs["open_claims"]["open_claims"])
        self.assertEqual(mine["population"]["closed_pairs"], theirs["latency"]["closed_pairs"])


class Attribution(unittest.TestCase):
    """Атрибуция отметки — отдельный вопрос от двери, и колонки не смешиваются."""

    def setUp(self):
        self.tree = Path(tempfile.mkdtemp(prefix="uas_attr_"))
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_two_identities_naming_one_tree_move_the_row_to_the_MULTIPLE_column(self):
        _touch(self.tree / "spa_core" / "a.py", 1.0)
        path = str(self.tree / "spa_core" / "a.py")
        scene = self._scene([
            _record("card-a", hours_ago=10.0, label="cycle-1", files=[path]),
            # сосед писал в то же дерево и карточку не захватывал
            _record("card-b", "done", hours_ago=2.0, label="cycle-2", files=[path]),
        ])
        report = scene.report()
        row = [r for r in report["rows"] if r["card"] == "card-a"][0]
        self.assertEqual(row["attribution"], uas.ATTR_MULTIPLE)
        self.assertEqual(row["identities_naming_tree"], 2)
        self.assertEqual(report["spans"]["by_attribution"][uas.ATTR_SOLE], 0)
        self.assertEqual(report["spans"]["by_attribution"][uas.ATTR_MULTIPLE], 1)
        for step in report["ladder"]["ladder"]:
            if step["ttl_hours"] <= 6:
                self.assertEqual(step["invisible_sole_identity"], 0,
                                 "завышающая колонка не имеет права течь в доверяемую")

    def test_one_identity_stays_in_the_SOLE_column(self):
        _touch(self.tree / "spa_core" / "a.py", 1.0)
        path = str(self.tree / "spa_core" / "a.py")
        scene = self._scene([_record("card-a", hours_ago=10.0, files=[path])])
        report = scene.report()
        self.assertEqual(_one_row(report)["attribution"], uas.ATTR_SOLE)
        self.assertEqual(report["spans"]["by_attribution"][uas.ATTR_SOLE], 1)
        step6 = [s for s in report["ladder"]["ladder"] if s["ttl_hours"] == 6][0]
        self.assertEqual(step6["invisible_sole_identity"], 1,
                         "span 9 ч длиннее срока 6 ч — срок оборвал бы эту работу")


class ReportShape(unittest.TestCase):
    """Отчёт и его отрисовка: форма постоянна, третий исход печатается вслух."""

    def setUp(self):
        self.scenes = []
        self.addCleanup(lambda: [s.close() for s in self.scenes])

    def _scene(self, records, **kw):
        s = Scene(records, **kw)
        self.scenes.append(s)
        return s

    def test_format_report_names_every_unmeasured_cause(self):
        scene = self._scene([
            _record("c1", hours_ago=5.0, files=["relative/x.py"]),
            _record("c2", hours_ago=5.0, files=["/tmp/uas_fmt/spa_core/a.py"]),
        ])
        text = "\n".join(uas.format_report(scene.report()))
        for needle in ("дерево не названо", "общее живое дерево",
                       "запись без времени записи", "следа нет нигде",
                       "НЕИЗМЕРИМ", "НЕ ДОКЛАДЫВАЕТ", "ADVISORY"):
            self.assertTrue(needle in text, f"в отрисовке нет {needle!r}")

    def test_format_report_says_UNMEASURED_out_loud(self):
        scene = self._scene([])
        text = "\n".join(uas.format_report(
            scene.report(journal_path=scene.root / "nope.jsonl")))
        self.assertTrue("НЕ ИЗМЕРЕНО" in text)

    def test_format_report_refuses_a_report_without_its_sections(self):
        """Раздела НЕТ и раздел ПУСТ — разные вещи; `or {}` склеил бы их."""
        scene = self._scene([_record("c1", hours_ago=5.0,
                                     files=["/tmp/uas_sec/spa_core/a.py"])])
        report = scene.report()
        report.pop("spans")
        text = "\n".join(uas.format_report(report))
        self.assertTrue("НЕ ИЗМЕРЕНО" in text)

    def test_the_report_keys_are_declared_even_when_unmeasured(self):
        scene = self._scene([])
        report = scene.report(journal_path=scene.root / "nope.jsonl")
        for key in ("generated_at", "order", "measured", "status", "reason", "applied",
                    "population", "doors", "spans", "ladder", "sources"):
            self.assertIn(key, report)
        self.assertFalse(report["applied"], "прибор только ЧИТАЕТ")

    def test_run_leaves_the_artifact_even_on_the_third_outcome(self):
        empty = Path(tempfile.mkdtemp(prefix="uas_run_"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        (empty / "data").mkdir()
        out = uas.run(root=str(empty), now=_NOW)
        self.assertFalse(out["measured"])
        doc = json.loads((empty / "data" / uas.ARTIFACT_NAME).read_text(encoding="utf-8"))
        self.assertIsNotNone(doc["reason"],
                             "отсутствие файла неотличимо от «ступень не запускалась»")

    def test_exit_code_is_zero_only_when_the_WHOLE_class_is_measurable(self):
        tree = Path(tempfile.mkdtemp(prefix="uas_rc_"))
        self.addCleanup(shutil.rmtree, tree, ignore_errors=True)
        _touch(tree / "spa_core" / "a.py", 1.0)
        scene = self._scene([_record("c1", hours_ago=5.0,
                                     files=[str(tree / "spa_core" / "a.py")])])
        report = scene.report()
        self.assertEqual(report["status"], uas.STATUS_MEASURABLE)
        self.assertEqual(uas.exit_code_for(report), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
