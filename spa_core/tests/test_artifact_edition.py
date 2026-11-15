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

import contextlib
import datetime as dt
import inspect
import io
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


def _kinds(n_stale: int, n_unmeasured: int = 0) -> ae.Census:
    """Замер с названным населением каждого рода — без git и без часов."""
    c = ae.Census(repo="/scene/full-clone")
    for i in range(n_stale):
        c.verdicts.append(ae.Verdict(
            kind=ae.STALE_EDITION, artifact=f"stale_{i:02d}.json",
            producer=f"spa_core/monitoring/p_{i:02d}.py",
            lag_hours=float(n_stale - i)))
    for i in range(n_unmeasured):
        c.verdicts.append(ae.Verdict(
            kind=ae.UNMEASURED, artifact=f"unmeasured_{i:02d}.json",
            producer=f"spa_core/monitoring/u_{i:02d}.py",
            reason="момент производства не прочитан"))
    return c


class WithheldNamesAreDeclared(unittest.TestCase):
    """Авария 15.11 (цикл #1159): СЧЁТ сказал 18, ПЕЧАТЬ назвала 12.

    Заказ G1009 п. 1 потребовал «идти ПОИМЁННО» и назвал этот прибор; прибор
    же резал перечень `[:max_rows]` МОЛЧА, и шесть членов класса существовали
    только как число — для читающего цикла «названы все» было неотличимо от
    «названа часть». Это инвариант #17 в печатной форме.
    """

    def test_the_cut_list_says_how_many_names_it_withheld(self) -> None:
        """Прямая авария: 18 членов, предел 12 ⇒ умолчание НАЗВАНО числом."""
        lines = ae.report(_kinds(18), max_rows=12)
        named = [ln for ln in lines if "[ПРЕЖНЯЯ]" in ln]
        self.assertEqual(len(named), 12)
        withheld = [ln for ln in lines if "[УМОЛЧАНО]" in ln]
        self.assertEqual(len(withheld), 1, "умолчание обязано быть объявлено")
        self.assertIn("ещё 6", withheld[0])
        self.assertIn("ПРЕЖНЯЯ", withheld[0])
        self.assertIn("--all", withheld[0], "объявление обязано назвать ВЫХОД")

    def test_nothing_withheld_means_no_line_at_all(self) -> None:
        """Обратная сторона: «ещё 0» — шум, который учат пролистывать."""
        lines = ae.report(_kinds(12), max_rows=12)
        self.assertEqual(len([ln for ln in lines if "[ПРЕЖНЯЯ]" in ln]), 12)
        self.assertEqual([ln for ln in lines if "[УМОЛЧАНО]" in ln], [])

    def test_all_prints_every_name_and_withholds_nothing(self) -> None:
        """Выход из умолчания обязан РАБОТАТЬ, а не только называться."""
        lines = ae.report(_kinds(18), max_rows=None)
        self.assertEqual(len([ln for ln in lines if "[ПРЕЖНЯЯ]" in ln]), 18)
        self.assertEqual([ln for ln in lines if "[УМОЛЧАНО]" in ln], [])

    def test_the_second_kind_obeys_the_same_limit_and_declares_too(self) -> None:
        """Иначе два рода разойдутся, и молчащий будет опаснее."""
        lines = ae.report(_kinds(0, n_unmeasured=14), max_rows=12)
        self.assertEqual(len([ln for ln in lines if "[НЕ ИЗМЕРЕНО]" in ln]), 12)
        withheld = [ln for ln in lines if "[УМОЛЧАНО]" in ln]
        self.assertEqual(len(withheld), 1)
        self.assertIn("ещё 2", withheld[0])
        self.assertIn("НЕ ИЗМЕРЕНО", withheld[0])

    def test_both_kinds_declare_independently_in_one_report(self) -> None:
        """Два рода режутся одновременно — умолчаний обязано быть ДВА."""
        lines = ae.report(_kinds(18, n_unmeasured=20), max_rows=12)
        withheld = [ln for ln in lines if "[УМОЛЧАНО]" in ln]
        self.assertEqual(len(withheld), 2, "\n".join(lines))
        self.assertIn("ещё 6", withheld[0])
        self.assertIn("ещё 8", withheld[1])

    def test_the_cut_is_one_door_for_both_kinds(self) -> None:
        """Свой срез рядом с дверью вернул бы молчание ОДНОМУ из родов.

        Срез обязан жить РОВНО в одном месте — в `_named_rows`, где рядом с
        ним стоит объявление остатка. Срез в `report()` (та самая прежняя
        редакция) резал перечень молча, и именно он здесь запрещён.
        """
        self.assertNotIn("[:max_rows]", inspect.getsource(ae.report),
                         "срез в report() мимо _named_rows: именно он и резал "
                         "перечень молча")
        self.assertEqual(
            Path(ae.__file__).read_text().count("[:max_rows]"), 1,
            "срезов больше одного — второй разойдётся с объявлением остатка")
        self.assertIn("[:max_rows]", inspect.getsource(ae._named_rows))

    def test_the_cli_flag_reaches_the_printer(self) -> None:
        """`--all` обязан ДОХОДИТЬ до печати, а не только быть объявленным.

        «Половина инъекции» — знакомый класс (`.claude/rules/deployment.md`
        § «ЛИЧНОСТЬ ПРОЦЕССА», поправка #453): флаг у разборщика есть, а до
        двери не доходит. Поэтому сцена идёт через НАСТОЯЩИЙ `main()`, и
        перечень производителей приходит входом, минуя офис и живое `data/`.
        """
        now = dt.datetime.now(dt.timezone.utc)
        produced = now - dt.timedelta(hours=400)
        n = 18
        producers = {f"a_{i:02d}.json": f"spa_core/monitoring/p_{i:02d}.py"
                     for i in range(n)}
        with tempfile.TemporaryDirectory(prefix="spa_ae_cli_") as d:
            tmp = Path(d)
            repo = _scene(tmp, producer_written_at=now - dt.timedelta(hours=10),
                          path=next(iter(producers.values())))
            for rel in list(producers.values())[1:]:
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# производитель сцены\n")
            _run(repo, "add", "-A")
            _run(repo, "commit", "-m", "the rest",
                 when=now - dt.timedelta(hours=10))
            _run(repo, "update-ref", f"refs/remotes/origin/{BRANCH}", BRANCH)

            moments = {name: produced for name in producers}
            original = ae._office_moments
            ae._office_moments = lambda data_dir: (producers, moments)
            try:
                out = {}
                for label, argv in (("умолчание", []), ("--all", ["--all"])):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        code = ae.main([*argv, "--repo", str(repo),
                                        "--data-dir", str(tmp)])
                    out[label] = (code, buf.getvalue().splitlines())
            finally:
                ae._office_moments = original

        for label, (code, lines) in out.items():
            self.assertEqual(code, 1, f"{label}: сцена обязана дать «есть прежние»")
            self.assertIn(f"вывод ПРЕЖНЕЙ редакции: {n}", "\n".join(lines))
        named_default = [l for l in out["умолчание"][1] if "[ПРЕЖНЯЯ]" in l]
        named_all = [l for l in out["--all"][1] if "[ПРЕЖНЯЯ]" in l]
        self.assertEqual(len(named_default), 12)
        self.assertEqual(len(named_all), n, "флаг до печати НЕ ДОШЁЛ")
        self.assertTrue(any("[УМОЛЧАНО]" in l for l in out["умолчание"][1]))
        self.assertFalse(any("[УМОЛЧАНО]" in l for l in out["--all"][1]))

    def test_the_count_and_the_names_cannot_disagree_silently(self) -> None:
        """Сквозной контроль: сумма «названо + умолчано» = объявленный счёт."""
        lines = ae.report(_kinds(18, n_unmeasured=20), max_rows=12)
        total = {"ПРЕЖНЯЯ": 0, "НЕ ИЗМЕРЕНО": 0}
        for ln in lines:
            if "[ПРЕЖНЯЯ]" in ln:
                total["ПРЕЖНЯЯ"] += 1
            elif "[НЕ ИЗМЕРЕНО]" in ln:
                total["НЕ ИЗМЕРЕНО"] += 1
            elif "[УМОЛЧАНО]" in ln:
                kind = "ПРЕЖНЯЯ" if "ПРЕЖНЯЯ" in ln else "НЕ ИЗМЕРЕНО"
                total[kind] += int(ln.split("ещё ")[1].split()[0])
        self.assertEqual(total["ПРЕЖНЯЯ"], 18)
        self.assertEqual(total["НЕ ИЗМЕРЕНО"], 20)


if __name__ == "__main__":
    unittest.main()
