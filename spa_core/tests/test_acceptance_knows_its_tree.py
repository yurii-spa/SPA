"""Приёмка обязана знать, из какого дерева её спросили.

Авария 2026-08-08, воспроизведена дважды за один день — второй раз тем же автором
через ход после того, как он её записал в карту.

Карта требует гонять `deployment_acceptance` до и после изменений. Money-path
правится только в изолированном worktree — значит сессия физически находится в
worktree, когда выполняет это требование. Свежесть артефактов меряется по mtime
файлов в `data/`, а в worktree там git-checkout, а не живое состояние прода.

Результат: уверенное «`agent_health.json` протух — задание не отработало» про
агента, который отработал 18 минут назад с кодом 0. Проверка ответила на свой
вопрос честно, но её вопрос был не про то дерево.

Тот же класс, что ошибка с owner-gate (мерил из отставшего дерева и едва не
отправил owner-gated числа): **вердикт зависит от того, откуда меришь**, и
проверка, не знающая своего места, уверенно врёт.

Важно, почему лечение — «не измерено», а не «протухло». Ложная тревога дороже
молчания: она учит выключать проверку. `docs/` и память проекта фиксируют оба
конца — fail-OPEN сторож, отвечающий не на тот вопрос, и неснимаемое «не
измерено», забивающее очередь. Здесь верен средний ответ: сказать, что не
измерено, и назвать способ измерить.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import deployment_acceptance as acc


class TestWorktreeDetection(unittest.TestCase):
    """Признак структурный: у worktree `.git` — файл, у обычного дерева — каталог."""

    def test_a_worktree_is_recognised(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n",
                                       encoding="utf-8")
            self.assertTrue(acc.measuring_from_worktree(root))

    def test_a_normal_checkout_is_not(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").mkdir()
            self.assertFalse(acc.measuring_from_worktree(root))

    def test_no_git_at_all_is_not_a_worktree(self):
        """Отсутствие .git — не повод объявлять дерево чужим."""
        with TemporaryDirectory() as t:
            self.assertFalse(acc.measuring_from_worktree(Path(t)))


class TestTheRealIncident(unittest.TestCase):
    """Положительный контроль: воспроизводим аварию, а не абстракцию."""

    def _report(self, root: Path) -> dict:
        return acc.run_acceptance(repo_root=root)

    def test_a_stale_checkout_does_NOT_produce_a_confident_did_not_run(self):
        """Тот самый вердикт, который был ложным."""
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").write_text("gitdir: /x/.git/worktrees/y\n", encoding="utf-8")
            (root / "data").mkdir()
            rep = self._report(root)

        self.assertIsNotNone(rep.get("artifacts_unchecked"),
                             "из worktree свежесть обязана быть НЕ ИЗМЕРЕНА")
        self.assertEqual(rep.get("artifacts_overdue"), [],
                         "нельзя утверждать «задание не отработало» про чужое дерево")
        joined = " ".join(rep.get("reasons", []))
        self.assertNotIn("did not run", joined)
        self.assertIn("worktree", joined)

    def test_unchecked_is_NOT_reported_as_a_clean_bill_of_health(self):
        """Сторона, без которой правка стала бы глушением проверки.

        «Не измерено» обязано быть видно. Иначе мы разменяли ложную тревогу на
        тишину, а это ровно тот fail-OPEN, который проект закрывает годами.
        """
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").write_text("gitdir: /x/.git/worktrees/y\n", encoding="utf-8")
            (root / "data").mkdir()
            rep = self._report(root)
        self.assertNotEqual(rep.get("status"), acc.OK,
                            "непроверенное не может считаться чистым счётом")
        self.assertTrue(rep.get("reasons"), "причина обязана быть названа вслух")

    def test_the_message_says_how_to_measure_properly(self):
        """Диагноз без способа исправить порождает вторую аварию того же вида."""
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").write_text("gitdir: /x/.git/worktrees/y\n", encoding="utf-8")
            (root / "data").mkdir()
            rep = self._report(root)
        self.assertIn("прод", rep["artifacts_unchecked"].lower())


class TestProductionPathUnchanged(unittest.TestCase):
    """Из настоящего дерева проверка обязана работать ровно как раньше."""

    def test_a_real_tree_still_gets_a_freshness_verdict(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").mkdir()
            (root / "data").mkdir()
            rep = self._run(root)
        self.assertIsNone(rep.get("artifacts_unchecked"),
                          "в обычном дереве свежесть обязана ИЗМЕРЯТЬСЯ")
        self.assertTrue(rep.get("artifacts_overdue"),
                        "пустой data/ — артефакты не произведены, это и есть вердикт")

    def test_an_explicit_data_dir_is_always_honoured(self):
        """Явно указанный каталог — осознанное решение вызывающего, не угадываем."""
        with TemporaryDirectory() as t:
            root = Path(t)
            (root / ".git").write_text("gitdir: /x/.git/worktrees/y\n", encoding="utf-8")
            ddir = root / "data"
            ddir.mkdir()
            rep = acc.run_acceptance(repo_root=root, data_dir=ddir)
        self.assertIsNone(rep.get("artifacts_unchecked"))
        self.assertTrue(rep.get("artifacts_overdue"))

    def _run(self, root: Path) -> dict:
        return acc.run_acceptance(repo_root=root)


if __name__ == "__main__":
    unittest.main()
