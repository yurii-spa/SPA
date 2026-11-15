#!/usr/bin/env python3
"""Контроли на прибор «чья РЕДАКЦИЯ произвела вывод артефакта».

Каждый тест воспроизводит НАСТОЯЩУЮ аварию замера 2026-11-15 (цикл #1158):

* `data/cio_architecture_constraints.json` произведён 29.10 и печатал CRITICAL
  об инварианте #3, а его производителя починил ADR-969 девятого ноября —
  находка осталась напечатанной, будучи уже неверной (класс
  :data:`STALE_EDITION`);
* тот же вопрос, заданный УСЕЧЁННОМУ прод-клону, расходится с полным у **118**
  производителей из 133 и почти везде отдаёт подставную дату границы — то есть
  усечение РОЖДАЕТ находку (ADR-918). Поэтому «клон не способен ответить» —
  самостоятельный исход, а не ответ.

**Времени в сценах нет ни одной литеральной даты.** Якорь — настоящие часы, а
все отметки сцены выводятся из него сдвигом, и ОБЕ стороны сравнения приходят
входом: `produced_at` параметром, дата коммита через `GIT_*_DATE`. Такой тест
бессмертен по построению (`.claude/rules/deployment.md` § «Время в тестах»,
приём №1), и храповику замороженных дат предъявлять нечего.

Имя ветки сцены ОБЪЯВЛЕНО (`git init -b`): умолчание `init.defaultBranch`
принадлежит ХОСТУ, и на `ubuntu-latest` оно `master` (там же § «GIT-ОКРУЖЕНИЕ
в тестах»).
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_edition as ae

BRANCH = "main"
PRODUCER = "spa_core/monitoring/make_it.py"
ARTIFACT = "make_it.json"


def _run(repo: Path, *args: str, when: dt.datetime | None = None) -> None:
    env = dict(os.environ)
    if when is not None:
        stamp = when.isoformat()
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    proc = subprocess.run(["git", "-C", str(repo), *args], env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr.strip()}")


def _scene(tmp: Path, *, producer_written_at: dt.datetime,
           path: str = PRODUCER) -> Path:
    """Клон с ОДНИМ производителем, закоммиченным в названный момент."""
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    _run(repo, "init", "-b", BRANCH)
    _run(repo, "config", "user.email", "scene@example.invalid")
    _run(repo, "config", "user.name", "scene")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# производитель сцены\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "producer", when=producer_written_at)
    # Прибор спрашивает УДАЛЁННУЮ ветку: локальная дрейфует от origin по
    # построению (пуши идут через API, минуя индекс — ADR-152).
    _run(repo, "update-ref", f"refs/remotes/origin/{BRANCH}", BRANCH)
    return repo


class TheRealAccident(unittest.TestCase):
    """Авария 15.11: находка напечатана кодом, которого в дереве уже нет."""

    def test_a_producer_changed_after_the_artifact_is_a_stale_edition(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        produced = now - dt.timedelta(hours=414)     # возраст артефакта 29.10
        changed = now - dt.timedelta(hours=140)      # починка ADR-969 позже
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d), producer_written_at=changed)
            v = ae.verdict(ARTIFACT, PRODUCER, produced_at=produced, repo=repo)
        self.assertEqual(v.kind, ae.STALE_EDITION)
        self.assertGreater(v.lag_hours, 0.0)
        self.assertIsNotNone(v.changed_at)

    def test_the_verdict_names_the_next_step_instead_of_acting(self) -> None:
        """Строка обязана звать ПЕРЕМЕРИТЬ, а не действовать по напечатанному."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d),
                          producer_written_at=now - dt.timedelta(hours=10))
            v = ae.verdict(ARTIFACT, PRODUCER,
                           produced_at=now - dt.timedelta(hours=400), repo=repo)
        lines = "\n".join(ae.edition_line(v))
        self.assertIn("ПРЕЖНЕЙ РЕДАКЦИИ", lines)
        self.assertIn("ПЕРЕМЕРИТЬ", lines)
        self.assertIn(PRODUCER, lines)

    def test_a_producer_older_than_the_artifact_is_current_and_silent(self) -> None:
        """Обратная сторона: у 110 артефактов из 133 печатать нечего."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d),
                          producer_written_at=now - dt.timedelta(hours=400))
            v = ae.verdict(ARTIFACT, PRODUCER,
                           produced_at=now - dt.timedelta(hours=10), repo=repo)
        self.assertEqual(v.kind, ae.CURRENT)
        self.assertEqual(ae.edition_line(v), [],
                         "у сегодняшней редакции строки быть не должно — иначе "
                         "110 строк утопят 18")


class ThirdOutcomeIsNeverCurrent(unittest.TestCase):
    """«Не измерено» не имеет права читаться как «сверено» (инв. #17)."""

    def test_a_shallow_clone_is_refused_not_believed(self) -> None:
        """Положительный контроль на ADR-918: усечённый клон РОЖДАЕТ находку.

        Замер #1158: ответ усечённого прод-клона расходится с полным у 118
        производителей из 133. Прибор обязан такой клон ОТВЕРГНУТЬ, а не принять
        его подставную дату границы.
        """
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            tmp = Path(d)
            full = _scene(tmp, producer_written_at=now - dt.timedelta(hours=400))
            # Второй коммит — чтобы у усечения было что отрезать.
            (full / PRODUCER).write_text("# вторая редакция\n")
            _run(full, "add", "-A")
            _run(full, "commit", "-m", "second", when=now - dt.timedelta(hours=10))
            _run(full, "update-ref", f"refs/remotes/origin/{BRANCH}", BRANCH)

            shallow = tmp / "shallow"
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", "-b", BRANCH,
                 full.as_uri(), str(shallow)],
                capture_output=True, text=True)
            if proc.returncode != 0:
                self.fail("предпосылка НЕ ОБЕСПЕЧЕНА: усечённый клон не создан "
                          f"({proc.stderr.strip()}) — подменять его полным "
                          "нельзя, контроль мерил бы не тот клон")
            self.assertEqual(
                ae._git(shallow, "rev-parse", "--is-shallow-repository")[1],
                "true", "сцена не усечена — контроль изображал бы аварию, "
                        "которой нет")

            c = ae.measure({ARTIFACT: PRODUCER}, {ARTIFACT: now},
                           repos=[str(shallow)])
        self.assertFalse(c.measured,
                         "усечённый клон принят за ответ — это ровно авария "
                         "ADR-918, только в новом приборе")
        self.assertIn("УСЕЧЁН", c.reason or "")

    def test_the_full_clone_is_chosen_and_printed(self) -> None:
        """Выбор клона ПЕЧАТАЕТСЯ: молча подставить второй — хуже ошибки."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            tmp = Path(d)
            full = _scene(tmp, producer_written_at=now - dt.timedelta(hours=400))
            c = ae.measure({ARTIFACT: PRODUCER}, {ARTIFACT: now},
                           repos=[str(tmp / "absent-clone"), str(full)])
        self.assertTrue(c.measured)
        self.assertEqual(c.repo, str(full))
        self.assertTrue(any("absent-clone" in r.get("repo", "")
                            for r in c.rejected),
                        "отвергнутый клон обязан быть НАЗВАН")
        self.assertTrue(any("absent-clone" in line for line in ae.report(c)))

    def test_a_path_without_commits_is_unmeasured_not_current(self) -> None:
        """Пустой ответ git — НЕ «производитель не менялся»."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d),
                          producer_written_at=now - dt.timedelta(hours=400))
            v = ae.verdict(ARTIFACT, "spa_core/monitoring/never_existed.py",
                           produced_at=now, repo=repo)
        self.assertEqual(v.kind, ae.UNMEASURED)
        self.assertIn("нет ни одного коммита", v.reason or "")
        self.assertNotEqual(v.kind, ae.CURRENT)

    def test_an_unread_moment_is_unmeasured_not_current(self) -> None:
        """Артефакт без прочитанного момента — третий исход, а не «актуален»."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d),
                          producer_written_at=now - dt.timedelta(hours=400))
            v = ae.verdict(ARTIFACT, PRODUCER, produced_at=None, repo=repo)
        self.assertEqual(v.kind, ae.UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНА", "\n".join(ae.edition_line(v)))

    def test_an_artifact_missing_from_moments_is_unmeasured_not_skipped(self) -> None:
        """Пропущенная строка неотличима от сверенной — поэтому её нет."""
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            repo = _scene(Path(d),
                          producer_written_at=now - dt.timedelta(hours=400))
            c = ae.measure({ARTIFACT: PRODUCER}, {}, repos=[str(repo)])
        self.assertEqual(len(c.verdicts), 1)
        self.assertEqual(c.verdicts[0].kind, ae.UNMEASURED)

    def test_no_clone_can_answer_means_no_census_at_all(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spa_ae_") as d:
            c = ae.measure({ARTIFACT: PRODUCER}, {ARTIFACT: None},
                           repos=[str(Path(d) / "nope")])
        self.assertFalse(c.measured)
        self.assertIn("РЕДАКЦИЯ ПРОИЗВОДИТЕЛЕЙ НЕ ИЗМЕРЕНА",
                      "\n".join(ae.report(c)))


class TheDoorIsSingle(unittest.TestCase):
    """Прибор не держит своей копии решений, у которых уже есть дверь."""

    def test_the_shallow_question_is_asked_through_the_lineage_seam(self) -> None:
        """Второе определение «полный ли клон» разошлось бы с первым молча."""
        src = Path(ae.__file__).read_text()
        self.assertIn("pick_lineage_repo", src)
        self.assertNotIn("--is-shallow-repository\"]", src.replace(" ", ""),
                         "прибор завёл СВОЙ вопрос об усечении — дверь должна "
                         "остаться одна (acceptance_tree_lineage)")

    def test_the_moment_is_an_input_not_a_second_home(self) -> None:
        """Единица и поле отметки объявлены у офиса (ADR-513) — не здесь."""
        src = Path(ae.__file__).read_text()
        self.assertNotIn("_TS_UNIT = ", src)
        self.assertNotIn("_TS_FIELD = ", src)


if __name__ == "__main__":
    unittest.main()
