"""Проба `office_absence_guard_not_fooled_by_tracked` меряет ИСХОД (ADR-875).

Правило `.claude/rules/acceptance.md` §3: новая проба регистрируется только с
тестом, где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на каждом порванном звене —
с названным звеном, — и где она НЕ проходит подстрокой (ADR-333).

Авария, которую проба охраняет (цикл #993): шаг 1 приказа, исполненный из
изолированного worktree, дал «прочитано 3, не прочитано 140» при ЖИВОМ
прод-офисе («прочитано 143, не прочитано 0» тем же прибором с `--data-dir`).
Сторож `_office_absent_wholesale` существовал и не сработал: его признак был
«хоть один артефакт СУЩЕСТВУЕТ», а существовали ровно две цели из 142, и обе
git-tracked — вывезенные `git checkout`, а не написанные флотом.

Звенья рвутся НА КОПИИ исходника шага, а не подменой словаря пробы: проба
обязана отвечать про НАСТОЯЩИЙ прибор. Рвать копию мы вправе — она
одноразовая; дерево доставки не трогается ни битом.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from spa_core.monitoring import card_acceptance as ca

PROBE = "office_absence_guard_not_fooled_by_tracked"
OFFICE = os.path.join(ca.REPO_ROOT, "scripts", "consume_office_reports.py")


def _probe_in_tree(root: str) -> tuple[str, str]:
    """Вердикт пробы, когда `REPO_ROOT` указывает на одноразовое дерево."""
    saved = ca.REPO_ROOT
    try:
        ca.REPO_ROOT = root
        return ca.PROBES[PROBE](None)
    finally:
        ca.REPO_ROOT = saved


class _Scene(unittest.TestCase):
    def setUp(self) -> None:
        self.box = tempfile.mkdtemp(prefix="office_guard_probe_")
        self.root = os.path.join(self.box, "tree")
        os.makedirs(os.path.join(self.root, "scripts"))
        self.src = os.path.join(self.root, "scripts",
                                "consume_office_reports.py")
        shutil.copy2(OFFICE, self.src)
        # Пакет `spa_core` проба не из дерева берёт, а из прогона — копировать
        # его незачем: предмет пробы это ОДИН файл шага.
        self.addCleanup(shutil.rmtree, self.box, ignore_errors=True)

    def _tear(self, old: str, new: str) -> None:
        text = open(self.src, encoding="utf-8").read()
        self.assertEqual(text.count(old), 1,
                         f"якорь звена не найден ровно один раз: {old!r}")
        open(self.src, "w", encoding="utf-8").write(text.replace(old, new))


class TheProbeIsGreenOnTheWholeContour(_Scene):
    def test_green_on_the_delivered_step(self) -> None:
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.SATISFIED, why)
        self.assertIn("доказательству ПИСАТЕЛЯ", why)


class TheProbeIsRedOnEveryTornLink(_Scene):
    def test_link1_red_when_the_guard_trusts_mere_existence(self) -> None:
        """Признак возвращён к «хоть один СУЩЕСТВУЕТ» — дословная авария."""
        self._tear("    witnesses = [r for r in present "
                   "if evidence.get(r) != _WRITER_CONST]",
                   "    witnesses = list(present)")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 1", why)

    def test_link2_red_when_the_guard_goes_blind(self) -> None:
        """Сторож срабатывает ВСЕГДА — ложная тишина вместо ложного шума.

        Это и есть покупка тишины ценой слепоты: без звена 2 проба зеленела бы
        на приборе, который глотает КАЖДУЮ настоящую пропажу.
        """
        self._tear("    witnesses = [r for r in present "
                   "if evidence.get(r) != _WRITER_CONST]",
                   "    witnesses = []")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 2", why)

    def test_link3_red_when_unmeasured_is_folded_into_an_answer(self) -> None:
        """Неответ git подставлен ответом — инв. #17 наизнанку."""
        self._tear("        return {rel: _WRITER_UNMEASURED for rel in present}",
                   "        return {rel: _WRITER_YES for rel in present}")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 3", why)

    def test_link3_red_when_the_признак_is_absent_altogether(self) -> None:
        """Признака «доказательство писателя» в приборе нет вовсе."""
        self._tear("def _writer_evidence(", "def _writer_evidence_renamed(")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("звено 3", why)
        self.assertIn("_writer_evidence", why)


class TheProbeRefusesInsteadOfGuessing(_Scene):
    def test_missing_step_source_is_unmeasured_not_clean(self) -> None:
        os.remove(self.src)
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕН", why)

    def test_unimportable_step_is_unmeasured_not_clean(self) -> None:
        open(self.src, "w", encoding="utf-8").write("this is not python(\n")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("НЕ ИЗМЕРЕН", why)

    def test_an_argument_is_refused_not_ignored(self) -> None:
        verdict, why = ca.PROBES[PROBE]("data/uptime_status.json")
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)


class TheProbeDoesNotPassBySubstring(_Scene):
    def test_prose_about_the_fix_does_not_satisfy_the_probe(self) -> None:
        """ADR-333: объявление в тексте пробу не закрывает.

        Прибор, который ПИШЕТ все нужные слова и при этом судит по
        существованию пути, обязан остаться красным.
        """
        self._tear("    witnesses = [r for r in present "
                   "if evidence.get(r) != _WRITER_CONST]",
                   "    # доказательство ПИСАТЕЛЯ: константа не наблюдение, "
                   "ОФИС НЕ ИЗМЕРЕН, git-tracked равен HEAD\n"
                   "    witnesses = list(present)")
        verdict, why = _probe_in_tree(self.root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)


if __name__ == "__main__":
    unittest.main()
