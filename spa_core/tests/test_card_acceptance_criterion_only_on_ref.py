#!/usr/bin/env python3
"""Дочитывание популяции критериев ключуется КРИТЕРИЕМ, а не наличием файла.

ADR-1105, цикл #1250, карточка `inbox-obyavlennyi-kriterii-prikaza-uzhe-vypoln`.

**Предмет.** `card_acceptance.audit()` дочитывал с `origin/main` карточки по ключу
`n not in local_names` — то есть отвечал на вопрос «лежит ли ФАЙЛ в этом каталоге»,
тогда как предмет модуля — «объявлен ли у карточки машинный критерий». Карточка,
чей файл в дереве ЕСТЬ, а критерия в этой копии НЕТ, проваливалась между двумя
состояниями: дочитывание её не брало (файл есть), а строка по ней не строилась
(`if not spec: continue`).

**Замер 2026-11-25 на живом проде** (каталог карточек прод-дерева против
`origin/main` `ea5199701`, разбор ОДНОЙ дверью `parse_frontmatter`): карточек в
обеих копиях **930**, объявленный критерий совпадает у **915**, есть ТОЛЬКО на ref
у **15**, только в дереве у **0**, РАЗЛИЧАЕТСЯ у **0**, НЕ ИЗМЕРЕНО **0**. Среди
15 — голодающий приказ владельца `inbox-task-portfolio-cio-dynamic-capital-alloc`
(2297.6 ч `in-progress`, 514 циклов мимо), чья объявленная на ref проба
`apy_name_carries_one_kind` в тот же час дала **satisfied**. То есть перепись,
существующая ровно для фразы «перемерить и закрыть, а не делать заново», насчитала
34 таких карточки и приказа среди них НЕ НАЗВАЛА.

**Почему соседи молчали честно и мимо.** `check_tracker_drift` называет все 15 —
но классом `diverged`/`stale` («содержимое различается») и среди 1032 находок;
про КРИТЕРИЙ у него нет ни одной оси. Проба `card_copies_agree` спрашивает
`check_tracker_drift` о СТАТУСЕ и о «закрытии только здесь», а статусы этой пары
копий у приказа совпадают (`in-progress`/`in-progress`) — она отвечает «копии
сошлись», и отвечает верно о своём предмете.

**Что здесь НЕ проверяется.** Ось «критерий у копий РАЗЛИЧАЕТСЯ» (замер 25.11: 0):
дверь отдаёт победу копии ДЕРЕВА, и это названо в `audit()` вслух. Контроль на эту
ось есть (`TheTreeDeclarationWins`), но он закрепляет ВЫБОР, а не отсутствие класса.

**Герметичность.** Каждая сцена — свой одноразовый репозиторий с ветвью
`origin/main`; живой репозиторий не читается ни разу, иначе зелёный прогон был бы
вакуумным. Имя ветви задаётся `git init -b` (§ GIT-ОКРУЖЕНИЕ правила доставки):
без него `init.defaultBranch` хоста делает вердикт свойством машины.

**Времени в тестах нет** — предмет сцен есть ПОПУЛЯЦИЯ, а не возраст артефакта;
пробы подменяются реестром.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_card_acceptance_criterion_only",
    _ROOT / "spa_core" / "monitoring" / "card_acceptance.py")
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)

#: Проба-пустышка: предмет сцен — популяция, а не то, что показывает конкретная
#: проба. Реестр подменяется, чтобы вердикт не зависел от живого артефакта.
_PROBE = "scene_probe"


def _card(status: str, probe: str | None = None, body: str = "тело") -> str:
    head = ["---", "trackerStatus:", "  type: inbox", "title: сцена",
            f"status: {status}"]
    if probe is not None:
        head.append(f"acceptance_probe: {probe}")
    head += ["---", "", body, ""]
    return "\n".join(head)


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   capture_output=True, text=True)


class Scene:
    """Одноразовый репозиторий: что лежит на ветви доставки и что — в дереве."""

    def __init__(self, on_ref: dict, in_tree: dict):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.tracker = os.path.join(self.repo, "nimbalyst-local", "tracker")
        os.makedirs(self.tracker)
        # Имя ветви — ВХОД сцены, а не умолчание хоста.
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        for name, body in on_ref.items():
            Path(self.tracker, name).write_text(body, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "ref")
        _git(self.repo, "branch", "-f", "origin/main", "main")
        # Дерево приводится к своему составу ПОСЛЕ того, как ветвь зафиксирована.
        for name in on_ref:
            if name not in in_tree:
                os.remove(os.path.join(self.tracker, name))
        for name, body in in_tree.items():
            Path(self.tracker, name).write_text(body, encoding="utf-8")

    def audit(self, **kw):
        return ca.audit(self.tracker, repo_root=self.repo, **kw)

    def close(self):
        self.tmp.cleanup()


class _Registered(unittest.TestCase):
    """Общая подмена реестра: вердикт сцены задаётся, а не наблюдается."""

    verdict = ca.SATISFIED

    def setUp(self):
        self._saved = ca.PROBES.get(_PROBE)
        ca.PROBES[_PROBE] = lambda arg=None, **kw: (self.verdict, "сцена")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            ca.PROBES.pop(_PROBE, None)
        else:
            ca.PROBES[_PROBE] = self._saved


class CriterionOnlyOnTheRefEntersThePopulation(_Registered):
    """ПРЯМОЙ контроль — ровно замер 25.11, воспроизведённый сценой."""

    def setUp(self):
        super().setUp()
        self.sc = Scene(
            on_ref={"order.md": _card("in-progress", _PROBE)},
            # Копия дерева: файл ЕСТЬ, строки критерия в нём НЕТ.
            in_tree={"order.md": _card("in-progress", None)})
        self.addCleanup(self.sc.close)

    def test_the_row_exists_at_all(self):
        res = self.sc.audit()
        self.assertEqual({r["card"] for r in res["rows"]}, {"order"},
                         "критерий объявлен на ref, а строки по карточке нет — "
                         "именно этот провал и есть предмет ADR-1105")

    def test_the_verdict_is_a_finding(self):
        res = self.sc.audit()
        self.assertEqual(res["counts"]["satisfied_but_open"], 1)

    def test_the_cause_of_the_readthrough_is_named(self):
        res = self.sc.audit()
        row = next(r for r in res["rows"] if r["card"] == "order")
        self.assertEqual(row["origin_source"], ca.ROW_SOURCE_CRITERION_ONLY)
        self.assertTrue(row["from_origin"], "прежний контракт поля сохранён")
        self.assertEqual(res["origin"]["read_criterion_only_on_ref"], 1)
        self.assertEqual(res["origin"]["read_file_absent"], 0)

    def test_the_printed_line_does_not_claim_the_file_is_missing(self):
        lines = "\n".join(ca.report_lines(self.sc.audit()))
        self.assertIn("критерий объявлен ТОЛЬКО на", lines)
        self.assertNotIn("файла в этом дереве нет", lines,
                         "файл в дереве ЕСТЬ — прежняя фраза была бы ложью, и "
                         "следующая сессия пошла бы искать его на диске")

    def test_the_tree_copy_status_is_carried_not_silenced(self):
        row = next(r for r in self.sc.audit()["rows"] if r["card"] == "order")
        self.assertEqual(row["tree_status"], "in-progress")


class TheTwoStatesAreCountedApart(_Registered):
    """«Файла нет» и «файл есть, критерия нет» — РАЗНЫЕ числа и разное лечение."""

    def setUp(self):
        super().setUp()
        self.sc = Scene(
            on_ref={"absent.md": _card("new", _PROBE),
                    "silent.md": _card("new", _PROBE),
                    "own.md": _card("new", _PROBE)},
            in_tree={"silent.md": _card("new", None),
                     "own.md": _card("new", _PROBE)})
        self.addCleanup(self.sc.close)

    def test_each_cause_has_its_own_number(self):
        o = self.sc.audit()["origin"]
        self.assertEqual(o["read_file_absent"], 1)
        self.assertEqual(o["read_criterion_only_on_ref"], 1)
        self.assertEqual(o["read"], 2)

    def test_the_header_prints_both_numbers(self):
        lines = "\n".join(ca.report_lines(self.sc.audit()))
        self.assertIn("файла в дереве нет 1", lines)
        self.assertIn("объявлен ТОЛЬКО на ref 1", lines)

    def test_no_card_is_counted_twice(self):
        rows = self.sc.audit()["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len([r for r in rows if r["card"] == "silent"]), 1)
        self.assertEqual(len([r for r in rows if r["card"] == "own"]), 1)

    def test_the_locally_declared_card_is_not_marked_as_read_through(self):
        row = next(r for r in self.sc.audit()["rows"] if r["card"] == "own")
        self.assertFalse(row["from_origin"])
        self.assertEqual(row["origin_source"], ca.ROW_SOURCE_TREE)


class TheStatusComesFromTheSameCopyAsTheCriterion(_Registered):
    """Критерий с ref ⇒ и «открыта» с ref. Иначе вердикт собран из двух копий.

    Это предмет ADR-1081 на новом месте: взять критерий у одной копии, а статус
    у другой — значит объявить находкой карточку, которая на ветви доставки уже
    закрыта. Замер 25.11: у 12 из 15 карточек предмета статусы копий РАЗОШЛИСЬ,
    и у 11 из них ref говорит `done` — то есть ключ «статус из дерева» родил бы
    одиннадцать ложных находок.
    """

    def setUp(self):
        super().setUp()
        self.sc = Scene(
            # На ветви доставки работа СВЕДЕНА, в дереве копия отстала.
            on_ref={"settled.md": _card("done", _PROBE)},
            in_tree={"settled.md": _card("new", None)})
        self.addCleanup(self.sc.close)

    def test_a_card_closed_on_the_ref_is_not_a_finding(self):
        res = self.sc.audit()
        self.assertEqual(res["counts"]["satisfied_but_open"], 0,
                         "статус взят из отставшей копии дерева — находка ВЫДУМАНА")

    def test_the_declaration_is_still_counted(self):
        res = self.sc.audit()
        self.assertEqual(res["counts"]["declared"], 1)
        self.assertEqual(res["counts"]["declared_closed"], 1)


class TheTreeDeclarationWins(_Registered):
    """Локальное объявление НЕ вытесняется ref-овским — закрепляем ВЫБОР.

    Ось «критерий у копий РАЗЛИЧАЕТСЯ» в замере 25.11 пуста (0 из 930), и эта
    проверка не утверждает, что класса нет: она фиксирует, какая копия побеждает,
    чтобы обратный порядок не завёлся молча.
    """

    def test_the_ref_does_not_override_a_local_probe(self):
        other = "scene_probe_other"
        self._saved_other = ca.PROBES.get(other)
        ca.PROBES[other] = lambda arg=None, **kw: (ca.NOT_SATISFIED, "ref-овская")
        self.addCleanup(lambda: (ca.PROBES.pop(other, None)
                                 if self._saved_other is None
                                 else ca.PROBES.__setitem__(other, self._saved_other)))
        sc = Scene(on_ref={"both.md": _card("new", other)},
                   in_tree={"both.md": _card("new", _PROBE)})
        self.addCleanup(sc.close)
        rows = sc.audit()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["probe"], _PROBE)
        self.assertEqual(rows[0]["origin_source"], ca.ROW_SOURCE_TREE)


class NothingInvisibleIsStillSilence(_Registered):
    """ОБРАТНЫЙ контроль: без него «нечего добирать» = «добирать разучились»."""

    def test_two_agreeing_copies_produce_no_readthrough(self):
        card = _card("new", _PROBE)
        sc = Scene(on_ref={"a.md": card}, in_tree={"a.md": card})
        self.addCleanup(sc.close)
        res = sc.audit()
        self.assertEqual(res["origin"]["read"], 0)
        self.assertEqual(res["origin"]["read_criterion_only_on_ref"], 0)
        self.assertNotIn("дочитана с", "\n".join(ca.report_lines(res)))

    def test_readthrough_off_keeps_the_blindness_and_says_so(self):
        sc = Scene(on_ref={"order.md": _card("in-progress", _PROBE)},
                   in_tree={"order.md": _card("in-progress", None)})
        self.addCleanup(sc.close)
        res = sc.audit(origin_readthrough=False)
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["origin"]["state"], "off")


class AnOldShapedReportIsNotMistakenForAMeasuredCause(unittest.TestCase):
    """Отчёт БЕЗ поля причины — «не измерено», а не «файла нет» (инв. #17)."""

    def test_missing_field_is_named_unmeasured(self):
        line = ca._row_provenance({"from_origin": True}, ref="origin/main")
        self.assertIn("НЕ ИЗМЕРЕНА", line)
        self.assertNotIn("файла в этом дереве нет", line)

    def test_a_local_row_of_an_old_report_prints_nothing(self):
        self.assertEqual(ca._row_provenance({"from_origin": False}), "")

    def test_an_unreadable_tree_status_is_not_printed_as_empty(self):
        line = ca._row_provenance(
            {"origin_source": ca.ROW_SOURCE_CRITERION_ONLY, "tree_status": ""},
            ref="origin/main")
        self.assertIn("статус не прочитан", line)

    def test_a_header_without_the_split_says_unmeasured_and_not_zero(self):
        """Различающая сцена для шапки: отчёт БЕЗ слагаемых — не «по нулю каждого».

        Мутант M11 первого прогона («напечатать нули») ВЫЖИЛ ровно потому, что
        ни одна сцена не подавала `report_lines` отчёт старого образца: нули
        читались бы как измеренный ответ о причине, которой замер не видел.
        """
        old_shaped = {
            "tracker_dir": "/нет/такого", "data_dir": None, "scanned": 1,
            "counts": {"declared": 1, "declared_open": 1, "declared_closed": 0,
                       "satisfied_but_open": 0, "not_satisfied": 1, "unmeasured": 0},
            "rows": [{"card": "x", "status": "new", "open": True, "probe": "p",
                      "verdict": ca.NOT_SATISFIED, "detail": "сцена",
                      "from_origin": True, "seconds": None}],
            # Блок дочитывания БЕЗ слагаемых — ровно форма до ADR-1105.
            "origin": {"state": "read", "read": 1, "ref": "origin/main",
                       "declared_on_ref": 1},
        }
        lines = "\n".join(ca.report_lines(old_shaped))
        self.assertIn("НЕ ИЗМЕРЕНО — отчёт старого образца", lines)
        self.assertNotIn("файла в дереве нет 0", lines)


if __name__ == "__main__":
    unittest.main()
