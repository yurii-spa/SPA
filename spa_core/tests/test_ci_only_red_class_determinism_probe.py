# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — проба не спрашивает ни часов, ни pid, ни порта;
# дерево она принимает ВХОДОМ (`repo_root=`), и все сцены ниже — одноразовые. Литеральной
# даты в файле нет вовсе, кроме номера блоба, который адресуется СОДЕРЖИМЫМ.
"""Контроль пробы `ci_only_red_class_determinism_named` (ADR-1031).

`.claude/rules/acceptance.md` п. 3: проба регистрируется только с тестом, где она зелена
на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с названным звеном, — и где она НЕ
проходит подстрокой (ADR-333).

Сцены одноразовые и собираются из НАСТОЯЩИХ пред-замерных байтов объявления: они
засеваются в временный репозиторий через `git hash-object -w`, поэтому номер блоба
совпадает ПО ПОСТРОЕНИЮ (блоб адресуется содержимым). Живое дерево не трогается ни одной
сценой.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from spa_core.monitoring import card_acceptance as ca  # noqa: E402

_PROBE_NAME = "ci_only_red_class_determinism_named"
_REL = Path("spa_core/tests/ci_only_red_class_baseline.json")
_PRE_AXIS_BLOB = "99fde88850b0779d4206c29554a9c6a7cb2e7db7"


def _probe():
    assert _PROBE_NAME in ca.PROBES, (
        "проба потеряла РЕГИСТРАЦИЮ: шаг 0-офис обходит РЕЕСТР, а не модуль, — "
        "незарегистрированная проба не меряет ничего и молчит об этом")
    return ca.PROBES[_PROBE_NAME]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root),
                          capture_output=True, text=True, check=True)


def _pre_axis_bytes() -> str:
    """Пред-замерные байты объявления из ЖИВОГО репозитория (только чтение)."""
    got = subprocess.run(["git", "cat-file", "blob", _PRE_AXIS_BLOB],
                         cwd=str(_REPO), capture_output=True, text=True)
    if got.returncode != 0 or not got.stdout.strip():
        raise unittest.SkipTest  # недостижимо: ниже есть громкий контроль на это
    return got.stdout


class _SceneCase(unittest.TestCase):
    """Одноразовое дерево-репозиторий с засеянным пред-замерным блобом."""

    def scene(self, doc: dict | None, *, seed_blob: bool = True) -> str:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # Имя ветки — ВХОД сцены: `init.defaultBranch` хоста здесь не спрашивается
        # (`.claude/rules/deployment.md` § GIT-ОКРУЖЕНИЕ).
        _git(root, "init", "-q", "-b", "main")
        if seed_blob:
            seeded = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"], cwd=str(root),
                input=self.pre_axis, capture_output=True, text=True, check=True)
            self.assertEqual(
                seeded.stdout.strip(), _PRE_AXIS_BLOB,
                "засеянный блоб не совпал с закреплённым: сцена изображала бы ДРУГОЕ "
                "пред-замерное состояние, и нулевая проба говорила бы не о том")
        if doc is not None:
            target = root / _REL
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        return str(root)

    def setUp(self) -> None:
        self.pre_axis = _pre_axis_bytes()

    def live_doc(self) -> dict:
        return json.loads((_REPO / _REL).read_text(encoding="utf-8"))


class TheProbeIsGreenOnTheWholeContour(_SceneCase):

    def test_the_live_declaration_satisfies_the_criterion(self) -> None:
        verdict, why = _probe()(None, repo_root=str(_REPO))
        self.assertEqual(verdict, ca.SATISFIED, why)
        self.assertIn("у ВСЕХ", why)

    def test_an_untouched_copy_of_the_live_declaration_is_also_green(self) -> None:
        """Обратная сторона всех поломок ниже: красный не должен происходить из самого
        копирования сцены."""
        verdict, why = _probe()(None, repo_root=self.scene(self.live_doc()))
        self.assertEqual(verdict, ca.SATISFIED, why)


class EveryBrokenLinkIsCaughtAndNamed(_SceneCase):

    def test_a_member_without_a_mechanism_is_refused(self) -> None:
        """ЗВЕНО: вердикт оси объявлен СЛОВОМ, механизма нет. Это ровно та форма, в
        которой проба НЕ имеет права проходить подстрокой (ADR-333)."""
        doc = self.live_doc()
        doc["members"][0]["determinism_mechanism"] = "зелено дважды"
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("механизм не назван", why)

    def test_a_member_without_a_named_door_is_refused(self) -> None:
        doc = self.live_doc()
        doc["members"][0]["determinism_door"] = ""
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("дверь к живой машине не названа", why)

    def test_a_verdict_outside_the_declared_vocabulary_is_refused(self) -> None:
        doc = self.live_doc()
        doc["members"][0]["determinism"] = "наверное_детерминировано"
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("вне словаря", why)

    def test_a_vocabulary_widened_in_the_declaration_still_refuses_a_bomb(self) -> None:
        """ЗВЕНО: `bomb` дописан в словарь, чтобы член остался в объявлении словом.

        Мерка берётся у объявления — значит расширить её можно. Но критерий этим НЕ
        гасится: население перестаёт сходиться, потому что выведенных бомбой стало
        меньше, а членов больше. Проверяется ИСХОД, а не запрет слова.
        """
        doc = self.live_doc()
        doc["determinism_axis"]["словарь"] = ["deterministic", "unmeasured", "bomb"]
        doc["members"].append(dict(doc["members"][0], nodeid="x.py::test_x",
                                   determinism="bomb"))
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("спорит со своим же замером", why)

    def test_a_tally_that_does_not_add_up_is_refused(self) -> None:
        """ЗВЕНО: кого-то вывели из объявления, не назвав КУДА."""
        doc = self.live_doc()
        doc["determinism_axis"]["замер_1170"]["bomb_removed"] = 3
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("не сходятся с населением", why)

    def test_an_upper_bound_drifted_from_its_producer_is_refused(self) -> None:
        doc = self.live_doc()
        doc["upper_bound"] = len(doc["members"]) + 4
        verdict, why = _probe()(None, repo_root=self.scene(doc))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("разошёлся со своим производителем", why)

    def test_an_absent_declaration_is_the_subject_not_unmeasured(self) -> None:
        """Отсутствие объявления есть сам дефект (предмет карточки), а не невозможность
        измерить — иначе `unmeasured` накрыл бы ровно то, о чём карточка."""
        verdict, why = _probe()(None, repo_root=self.scene(None))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("объявления класса нет", why)


class TheThirdOutcomeIsDistinguishable(_SceneCase):
    """Инв. #17: «не измерено» не выдаётся ни за «выполнено», ни за «не выполнено»."""

    def test_an_unreachable_zero_probe_is_unmeasured_not_satisfied(self) -> None:
        """ЗВЕНО: пред-замерных байтов не достать (дерево без блоба).

        Это и есть урок #1144 в обратную сторону: проба, потерявшая нулевую сцену,
        обязана СКАЗАТЬ это, а не зазеленеть на живом объявлении.
        """
        verdict, why = _probe()(None, repo_root=self.scene(self.live_doc(),
                                                           seed_blob=False))
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("предпосылка НЕ ОБЕСПЕЧЕНА", why)

    def test_a_broken_declaration_is_unmeasured_not_a_clean_class(self) -> None:
        root = self.scene(self.live_doc())
        (Path(root) / _REL).write_text("{не json", encoding="utf-8")
        verdict, why = _probe()(None, repo_root=root)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не разбирается", why)

    def test_the_probe_takes_no_argument(self) -> None:
        verdict, why = _probe()("spa_core/tests/что-нибудь.py", repo_root=str(_REPO))
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)

    def test_the_pinned_blob_must_be_the_PRE_fix_edition(self) -> None:
        """Контроль на сам якорь: закреплённые байты обязаны быть ДО замера.

        Закрепи сюда ПОЧИНЕННУЮ редакцию — и нулевая проба изображала бы состояние,
        которого не было; проба зазеленела бы, ничего не проверив.
        """
        pre = json.loads(self.pre_axis)
        self.assertEqual(len(pre["members"]), 19,
                         "пред-замерное объявление обязано нести 19 членов")
        self.assertFalse(
            [m for m in pre["members"] if m.get("determinism")],
            "закреплённый блоб уже несёт ось детерминизма — это ПОЧИНЕННАЯ редакция, "
            "и нулевая проба на ней ничего не держит")


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
