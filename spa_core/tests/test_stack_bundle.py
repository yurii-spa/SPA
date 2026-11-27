#!/usr/bin/env python3
"""Сторож `scripts/stack_bundle.py` — ВТОРАЯ копия работы, которой нельзя уехать на origin.

Каждый тест здесь — положительный контроль: он воспроизводит состояние, НАБЛЮДЁННОЕ
25.11.2026 (цикл #1249), и краснеет, если соответствующее свойство прибора снять.

Наблюдённая авария: ключ `GITHUB_PAT_SPA` истёк 24.11, циклы #1238…#1248 сложили стек из
одиннадцати коммитов, и вершина `92845a4fc` не существовала НИ В ОДНОМ другом объектном
складе (`git cat-file -e` в полном зеркале ⇒ ненулевой код). Отдать их origin повторно
нельзя: ключ мёртв. Сценами ниже тот же мир собирается в одноразовых репозиториях.

Сцены создают репозитории `git init -b <имя>` с ЯВНЫМ именем ветки: `init.defaultBranch`
есть свойство ХОСТА (`.claude/rules/deployment.md` § GIT-ОКРУЖЕНИЕ — Apple Git даёт `main`,
`ubuntu-latest` даёт `master`), и фикстура, умолчавшая имя, зелена здесь и красна на CI.
Сети ни одна сцена не касается: «удалённый» репозиторий — каталог рядом.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    """Ввезти прибор по пути: он лежит в `scripts/`, пакетом не является."""
    path = _ROOT / "scripts" / "stack_bundle.py"
    spec = importlib.util.spec_from_file_location("stack_bundle_under_test", path)
    assert spec and spec.loader, f"прибор не ввезён: {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sb = _load()


def _run(cwd, *args, check=True):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args[:3])} в {cwd} ⇒ {p.returncode}: "
                             f"{p.stderr.strip()[:300]}")
    return p.stdout


class Scene:
    """Мир из трёх частей: «удалённый» склад · источник · контроль.

    Контроль — КЛОН удалённого: у него есть предпосылки и НЕТ спорных коммитов. Именно это
    отличает проверку от тавтологии, и именно поэтому он клонируется, а не копируется из
    источника.
    """

    BRANCH = "main"

    def __init__(self, tmp: pathlib.Path):
        self.tmp = tmp
        self.remote = tmp / "remote.git"
        self.src = tmp / "src"
        self.control = tmp / "control"
        self.dest = tmp / "bundles"

        _run(tmp, "init", "--quiet", "--bare", "-b", self.BRANCH, str(self.remote))
        _run(tmp, "init", "--quiet", "-b", self.BRANCH, str(self.src))
        _run(self.src, "config", "user.email", "scene@example.invalid")
        _run(self.src, "config", "user.name", "scene")
        _run(self.src, "remote", "add", "origin", str(self.remote))

    def commit(self, name: str, body: str) -> str:
        (self.src / name).write_text(body, encoding="utf-8")
        _run(self.src, "add", name)
        _run(self.src, "commit", "--quiet", "-m", f"add {name}")
        return _run(self.src, "rev-parse", "HEAD").strip()

    def deliver(self) -> None:
        """Доставить на «удалённый» и узнать об этом локально (как настоящий push)."""
        _run(self.src, "push", "--quiet", "origin", f"{self.BRANCH}:{self.BRANCH}")
        _run(self.src, "fetch", "--quiet", "origin")

    def strand(self, branch: str, name: str, body: str) -> str:
        """Положить работу на ветку, которой на «удалённом» нет — та самая авария."""
        _run(self.src, "checkout", "--quiet", "-b", branch)
        sha = self.commit(name, body)
        _run(self.src, "checkout", "--quiet", self.BRANCH)
        return sha

    def clone_control(self) -> None:
        _run(self.tmp, "clone", "--quiet", "--no-checkout", str(self.remote),
             str(self.control))


class StackBundleTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    # ——— что считается неотправленным ———————————————————————————————————————

    def test_delivered_work_is_a_measured_zero_not_a_backup(self):
        """Всё доставлено ⇒ исход «сохранять нечего» (код 1), а не «резерв сделан».

        Положительный контроль инв. #17 с той стороны, где ошибка тише: измеренный ноль
        обязан отличаться от «не смотрели».
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        meas = sb.stranded(s.src)
        self.assertEqual(meas["state"], sb.NOTHING, meas)
        self.assertEqual(meas["commits"], 0, meas)
        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(s.control)])
        self.assertEqual(rc, 1, "доставленная работа обязана давать код 1")
        self.assertFalse(list(s.dest.glob("*.bundle")) if s.dest.exists() else [],
                         "резерв не создаётся, когда сохранять нечего")

    def test_a_commit_on_another_origin_branch_is_not_stranded(self):
        """Коммит, лежащий на origin/<другая-ветка>, НЕ потерян — и в счёт не идёт.

        Положительный контроль на выбор базы. Сними исключение по ВСЕМ origin-рефам (оставь
        один `origin/main`) — и этот тест покраснеет: прибор объявит сохранной работой
        1345 коммитов вместо 0 (замер 25.11 на живом клоне: 27 686 против 1345).
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        _run(s.src, "checkout", "--quiet", "-b", "feature")
        s.commit("f.txt", "f")
        _run(s.src, "push", "--quiet", "origin", "feature:feature")
        _run(s.src, "fetch", "--quiet", "origin")
        _run(s.src, "checkout", "--quiet", Scene.BRANCH)

        meas = sb.stranded(s.src)
        self.assertEqual(meas["commits"], 0,
                         f"ветка доставлена на origin — терять нечего: {meas['by_head']}")

    def test_stranded_commit_is_counted_and_named(self):
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        sha = s.strand("rescue/c9999-work", "stranded.txt", "работа цикла")

        meas = sb.stranded(s.src)
        self.assertEqual(meas["state"], sb.HAVE_WORK, meas)
        self.assertEqual(meas["commits"], 1, meas)
        self.assertIn("refs/heads/rescue/c9999-work", meas["by_head"], meas)
        self.assertTrue(sha)

    # ——— несущее свойство: bundle ВОССТАНАВЛИВАЕТСЯ ———————————————————————————

    def test_bundle_restores_the_stranded_work_in_a_repo_that_never_had_it(self):
        """Авария целиком: работа есть в ОДНОМ складе, bundle возвращает её в ДРУГОЙ.

        Это главный тест файла. Сцена сперва доказывает, что без bundle работы в контроле
        НЕТ (иначе «восстановилось» было бы правдой по построению), и только потом
        восстанавливает.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "байты, которых нет на origin")
        s.clone_control()

        # ОБРАТНАЯ половина: до восстановления контроль о работе не знает.
        before = subprocess.run(["git", "cat-file", "-e",
                                 _run(s.src, "rev-parse", "rescue/c9999-work").strip()],
                                cwd=str(s.control), capture_output=True)
        self.assertNotEqual(before.returncode, 0,
                            "сцена не различает: контроль уже содержит спорный коммит")

        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(s.control)])
        self.assertEqual(rc, 0, "записанный и проверенный bundle обязан давать код 0")
        bundles = list(s.dest.glob("*.bundle"))
        self.assertEqual(len(bundles), 1, bundles)

        restored = self.tmp / "restored"
        _run(self.tmp, "clone", "--quiet", "--no-checkout", str(s.remote), str(restored))
        _run(restored, "fetch", "--quiet", str(bundles[0]),
             "refs/heads/rescue/c9999-work:refs/heads/back")
        body = _run(restored, "show", "back:stranded.txt")
        self.assertEqual(body, "байты, которых нет на origin",
                         "восстановились не те байты")

    # ——— проверка обязана быть НЕ тавтологией ————————————————————————————————

    def test_verification_in_the_source_clone_is_refused_as_tautology(self):
        """Контроль, делящий склад с источником, резервом объявлять НЕ даёт (код 2).

        Положительный контроль: сними сверку складов — и прибор начнёт звать резервом
        bundle, восстановимость которого никто не проверял. У источника `bundle verify`
        успешен ВСЕГДА.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")

        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(s.src)])
        self.assertEqual(rc, 2, "проверка в своём же складе не есть проверка")
        self.assertTrue(list(s.dest.glob("*.bundle")),
                        "файл обязан остаться на диске и быть НАЗВАННЫМ: "
                        "«не проверен» это не «не записан»")

    def test_a_linked_worktree_shares_the_store_and_is_also_refused(self):
        """Линкованный worktree — ДРУГОЙ каталог и ТОТ ЖЕ склад объектов.

        Тонкая половина предыдущего контроля: сверка ПУТЕЙ рабочих деревьев её бы
        пропустила, сверка `--git-common-dir` ловит.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")
        wt = self.tmp / "linked"
        _run(s.src, "worktree", "add", "--quiet", "--detach", str(wt))

        self.assertEqual(sb._object_store(wt), sb._object_store(s.src),
                         "сцена не воспроизводит предмет: склады обязаны совпасть")
        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(wt)])
        self.assertEqual(rc, 2, "worktree источника контролем не является")

    def test_control_without_the_prerequisites_is_unmeasured_not_verified(self):
        """У контроля нет предпосылок ⇒ НЕ ИЗМЕРЕНО с причиной, а не «резерв есть».

        Так выглядит отставшее зеркало. Fail-CLOSED: о восстановимости мы не узнали ничего.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")
        empty = self.tmp / "empty"
        _run(self.tmp, "init", "--quiet", "-b", "main", str(empty))

        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(empty)])
        self.assertEqual(rc, 2, rc)

    def test_a_missing_control_repo_is_unmeasured(self):
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")

        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(self.tmp / "nope")])
        self.assertEqual(rc, 2, rc)

    # ——— отказы, которые нельзя подменить нулём ———————————————————————————————

    def test_a_repo_without_origin_refs_is_unmeasured_not_whole_history(self):
        """Базы исключения нет ⇒ отказ, а НЕ «вся история — неотправленная работа».

        Без этого отказа прибор на свежем `git init` объявил бы резервом весь репозиторий
        и назвал бы это находкой.
        """
        lone = self.tmp / "lone"
        _run(self.tmp, "init", "--quiet", "-b", "main", str(lone))
        _run(lone, "config", "user.email", "scene@example.invalid")
        _run(lone, "config", "user.name", "scene")
        (lone / "a.txt").write_text("a", encoding="utf-8")
        _run(lone, "add", "a.txt")
        _run(lone, "commit", "--quiet", "-m", "a")

        with self.assertRaises(sb.NotMeasured):
            sb.stranded(lone)
        rc = sb.main(["--repo-root", str(lone), "--dest", str(self.tmp / "d"),
                      "--control-repo", str(self.tmp / "c")])
        self.assertEqual(rc, 2, rc)

    def test_a_non_repository_is_unmeasured_and_names_git_as_the_cause(self):
        """git не ответил ⇒ отказ, И ПРИЧИНА названа замером, а не догадкой.

        Положительный контроль, добытый мутацией (цикл #1249, M7): пока тест требовал лишь
        «поднялось `NotMeasured`», подмена «сбой git ⇒ пустая строка» ВЫЖИВАЛА — отказ
        всё равно случался, но уже по ДРУГОЙ причине («локальных ветвей нет вовсе»), то есть
        отсутствие git докладывалось как отсутствие работы. Причина внутри «НЕ ИЗМЕРЕНО»
        обязана быть ЗАМЕРОМ (ADR-1058), поэтому сверяется именно она.
        """
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(sb.NotMeasured) as caught:
            sb.stranded(plain)
        why = str(caught.exception)
        self.assertIn("git", why,
                      f"причина обязана назвать git, а не ветви: {why!r}")
        self.assertNotIn("локальных ветвей", why,
                         f"сбой git доложен как «нет работы»: {why!r}")

    def test_a_verify_output_naming_no_refs_is_not_accepted_as_proof(self):
        """`bundle verify` без единого рефа в выводе ⇒ НЕ ИЗМЕРЕНО.

        Положительный контроль, добытый мутацией (цикл #1249, M10): ни одна сцена не подавала
        прибору вывод, в котором СОСТАВ bundle не назван, — и подмена «пустой перечень рефов
        считать проверкой» выживала. Это дыра ПОКРЫТИЯ, а не дефект кода: о составе такой
        ответ не говорит ничего, а выглядит успехом.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.clone_control()
        bundle = self.tmp / "any.bundle"
        bundle.write_bytes(b"x")

        real_git = sb._git

        def mute_refs(root, *args, **kw):
            if args[:2] == ("bundle", "verify"):
                # Только предпосылка, ни одного рефа — форма, при которой о составе
                # bundle не сказано.
                return "0" * 40 + "\n"
            return real_git(root, *args, **kw)

        with mock.patch.object(sb, "_git", mute_refs):
            ver = sb.verify(bundle, s.control, root=s.src)
        self.assertEqual(ver["state"], sb.UNVERIFIED, ver)
        self.assertIn("рефа", ver["why"], ver)

    def test_a_zero_size_bundle_is_refused(self):
        """Bundle нулевого размера резервом не является (мутация M10/M12, цикл #1249).

        Сцена, которой не было: git отвечает кодом 0 и не пишет НИ БАЙТА. Без этой проверки
        на диск ложится пустой файл под честным именем.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")
        meas = sb.stranded(s.src)

        real_git = sb._git

        def writes_nothing(root, *args, **kw):
            if args[:2] == ("bundle", "create"):
                pathlib.Path(args[2]).write_bytes(b"")
                return ""
            return real_git(root, *args, **kw)

        with mock.patch.object(sb, "_git", writes_nothing):
            with self.assertRaises(sb.NotMeasured) as caught:
                sb.build(s.src, s.dest, meas)
        self.assertIn("нулевого размера", str(caught.exception))
        self.assertEqual(list(s.dest.glob("*.bundle")), [])
        self.assertEqual(list(s.dest.glob("*.tmp")), [])

    def test_a_failed_write_never_lands_under_the_final_name(self):
        """Сбой на записи не оставляет ни итогового имени, ни `.tmp`-мусора (инв. #5).

        Частично записанный bundle под итоговым именем — худший исход: он ВЫГЛЯДИТ резервом.
        """
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")
        meas = sb.stranded(s.src)

        real_git = sb._git

        def half_written(root, *args, **kw):
            if args[:2] == ("bundle", "create"):
                pathlib.Path(args[2]).write_bytes(b"# PACK but truncated")
                raise sb.NotMeasured("сцена: git умер на середине записи")
            return real_git(root, *args, **kw)

        # Дверь закрывается установщиком С ВОЗВРАТОМ: подмена, пережившая сцену, вредит
        # СОСЕДУ по процессу, а не автору (`.claude/rules/deployment.md` § СОСЕД ПО
        # ПРОЦЕССУ — замер #1219: прямое присваивание атрибута модуля заглушило чужой
        # положительный контроль и было зелёным до тасовки шардов).
        with mock.patch.object(sb, "_git", half_written):
            with self.assertRaises(sb.NotMeasured):
                sb.build(s.src, s.dest, meas)

        self.assertEqual(list(s.dest.glob("*.bundle")), [],
                         "итогового имени после сбоя быть не должно")
        self.assertEqual(list(s.dest.glob("*.tmp")), [], "мусор .tmp не убран")

    def test_measure_only_does_not_claim_a_backup(self):
        """Только замер ⇒ резерва не возникло, и прибор этого не скрывает."""
        s = Scene(self.tmp)
        s.commit("a.txt", "a")
        s.deliver()
        s.strand("rescue/c9999-work", "stranded.txt", "работа")

        rc = sb.main(["--repo-root", str(s.src), "--dest", str(s.dest),
                      "--control-repo", str(s.control), "--measure-only"])
        self.assertEqual(rc, 2, "замер без записи резервом не является")
        self.assertFalse(list(s.dest.glob("*.bundle")) if s.dest.exists() else [])

    def test_retention_keeps_the_freshest_and_touches_only_its_own_names(self):
        dest = self.tmp / "d"
        dest.mkdir()
        for i in range(5):
            (dest / f"spa_stranded_2026-11-2{i}T000000Z.bundle").write_bytes(b"x")
        foreign = dest / "do-not-touch.bundle"
        foreign.write_bytes(b"x")

        dropped = sb.prune(dest, keep=2)
        self.assertEqual(len(dropped), 3, dropped)
        left = sorted(p.name for p in dest.glob("spa_stranded_*.bundle"))
        self.assertEqual(left, ["spa_stranded_2026-11-23T000000Z.bundle",
                                "spa_stranded_2026-11-24T000000Z.bundle"], left)
        self.assertTrue(foreign.exists(), "удалено чужое имя")


if __name__ == "__main__":
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════════
# ADR-1123 (заказ G1087 п. 4): связка обязана НАЗЫВАТЬ то, что сохранить не может
#
# До ADR-1123 связка МОЛЧАЛА о незакоммиченном: её вердикт «резерв записан и
# проверен» верен про коммиты и ничего не утверждает про диск. Цена молчания
# наблюдена — цикл #1242 умер между правкой и коммитом, 1640 строк остались в
# индексе одноразовых деревьев `/private/tmp`, который macOS чистит сам.
# ══════════════════════════════════════════════════════════════════════════════

_FAKE_DOOR = '''
EMPTY, FOUND, UNMEASURED = "empty", "found", "unmeasured"


def measure(root, budget_s=None, **kw):
    return {"verdict": "found", "names": [{"path": "МЕТКА-ЧУЖОГО-ДЕРЕВА"}],
            "by_loss": {"whole": 7, "delta": 0}, "by_kind": {"work": 7},
            "trees_read": 1, "trees_declared": 1, "unmeasured": []}
'''


class UncoveredByTheBundle(unittest.TestCase):
    """Положительные контроли проводки — в ОБЕ стороны."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmpdir, True)
        self.tmp = pathlib.Path(self.tmpdir)

    def _tree_with_door(self, body: str) -> pathlib.Path:
        """Одноразовое дерево со СВОЕЙ копией двери и файлом-бегуном в `scripts/`."""
        root = self.tmp / "чужое_дерево"
        (root / "spa_core" / "monitoring").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        (root / "spa_core" / "monitoring" / "stranded_content.py").write_text(
            body, encoding="utf-8")
        runner = root / "scripts" / "stack_bundle.py"
        runner.write_text("# бегун сцены\n", encoding="utf-8")
        return runner

    def test_the_door_is_taken_from_the_running_tree_not_a_constant(self):
        """Дверь берётся из дерева ЗАПУЩЕННОГО скрипта. Положительный контроль —
        ЧУЖОЕ дерево со своей копией двери: ответ обязан прийти ИЗ НЕГО."""
        runner = self._tree_with_door(_FAKE_DOOR)
        got = sb.uncovered_by_the_bundle(self.tmp, runner_file=str(runner))
        self.assertEqual(got["state"], "found", got)
        self.assertEqual(got["work"], 1, got)
        self.assertEqual(got["by_loss"], {"whole": 7, "delta": 0}, got)

    def test_a_missing_door_is_unmeasured_with_a_named_reason(self):
        """Двери нет ⇒ НЕ ИЗМЕРЕНО с названной причиной, а НЕ ноль и не молчание."""
        bare = self.tmp / "пустое" / "scripts" / "stack_bundle.py"
        bare.parent.mkdir(parents=True)
        bare.write_text("# бегун\n", encoding="utf-8")
        got = sb.uncovered_by_the_bundle(self.tmp, runner_file=str(bare))
        self.assertEqual(got["state"], sb.UNMEASURED, got)
        self.assertIn("НЕ ИЗМЕРЕНА", got["why"])
        self.assertNotIn("work", got, "НЕ ИЗМЕРЕНО не вправе называть число")

    def test_a_door_without_measure_is_unmeasured(self):
        """Файл есть, двери `measure` в нём нет — это тоже НЕ ИЗМЕРЕНО, а не ноль."""
        runner = self._tree_with_door("СОДЕРЖИМОЕ = 1\n")
        got = sb.uncovered_by_the_bundle(self.tmp, runner_file=str(runner))
        self.assertEqual(got["state"], sb.UNMEASURED, got)
        # ПРИЧИНА судится точно, а не подстрокой «measure»: МУТАЦИЯ M20 (снятие
        # проверки двери) давала тот же исход `unmeasured`, но причиной уже «мера
        # упала (AttributeError … measure)» — а это ДРУГОЙ отказ, и чинится он другим.
        self.assertIn("двери `measure` в нём нет", got["why"])
        self.assertNotIn("упала", got["why"],
                         "дверь обязана быть названа ДО зова, а не после падения")

    def test_a_door_that_raises_is_unmeasured_not_a_crash(self):
        runner = self._tree_with_door(
            "def measure(root, budget_s=None, **kw):\n    raise RuntimeError('дверь')\n")
        got = sb.uncovered_by_the_bundle(self.tmp, runner_file=str(runner))
        self.assertEqual(got["state"], sb.UNMEASURED, got)
        self.assertIn("RuntimeError", got["why"])

    def test_the_report_names_the_gap(self):
        doc = {"state": sb.BUNDLED, "heads_total": 1, "origin_refs": 1, "commits": 1,
               "by_head": {}, "bundle": "/x", "bytes": 1,
               "verify": {"state": sb.VERIFIED, "control": "/c", "heads": [],
                          "prereqs": []},
               "pruned": [],
               "uncovered": {"state": "found", "work": 714,
                             "by_loss": {"whole": 416, "delta": 298},
                             "trees_read": 179, "trees_declared": 179,
                             "unmeasured": 0, "reasons": []}}
        text = "\n".join(sb.report(doc))
        self.assertIn("СВЯЗКА ЭТОГО НЕ СОХРАНИТ", text)
        self.assertIn("714", text)
        self.assertIn("416", text)
        self.assertIn("НЕ меняется", text)

    def test_the_gap_is_named_even_when_there_is_nothing_to_bundle(self):
        """Склейка, из-за которой проводка и нужна: «резерв не нужен» и «резерв
        неполон» — РАЗНЫЕ утверждения. Печатать первое вместо второго значило бы
        вернуть молчание ADR-1104."""
        doc = {"state": sb.NOTHING, "heads_total": 3, "origin_refs": 2,
               "uncovered": {"state": "found", "work": 5,
                             "by_loss": {"whole": 5, "delta": 0},
                             "trees_read": 2, "trees_declared": 2,
                             "unmeasured": 0, "reasons": []}}
        text = "\n".join(sb.report(doc))
        self.assertIn("ИЗМЕРЕННЫЙ ноль", text, "про коммиты ответ прежний")
        self.assertIn("СВЯЗКА ЭТОГО НЕ СОХРАНИТ", text, "и про диск он ДРУГОЙ")

    def test_a_measured_zero_differs_from_unmeasured_in_the_report(self):
        base = {"state": sb.NOTHING, "heads_total": 1, "origin_refs": 1}
        zero = "\n".join(sb.report({**base, "uncovered": {
            "state": sb.EMPTY_CONTENT, "trees_read": 9, "trees_declared": 9}}))
        unm = "\n".join(sb.report({**base, "uncovered": {
            "state": sb.UNMEASURED, "why": "дверь не ввезена"}}))
        self.assertIn("НЕ НАБЛЮДАЛОСЬ", zero)
        self.assertIn("ИЗМЕРЕННЫЙ ноль", zero)
        self.assertIn("НЕ ИЗМЕРЕНО", unm)
        self.assertNotIn("НЕ НАБЛЮДАЛОСЬ", unm)

    def test_the_block_missing_from_the_doc_is_unmeasured_not_silence(self):
        """Блока в отчёте нет вовсе ⇒ НЕ ИЗМЕРЕНО. Отсутствие ключа не вправе
        читаться как «вопрос задан, и чисто»."""
        text = "\n".join(sb.report({"state": sb.NOTHING, "heads_total": 1,
                                    "origin_refs": 1}))
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_skipping_the_question_is_printed_as_not_asked(self):
        """`--skip-uncovered` обязан оставлять СЛЕД: «не спрашивали» это третий
        исход, а не тишина."""
        with tempfile.TemporaryDirectory() as tmp:
            scene = Scene(pathlib.Path(tmp))
            scene.commit("a.txt", "a")
            scene.deliver()
            doc = sb.run(scene.src, scene.dest, scene.control, do_build=False,
                         ask_uncovered=False)
        self.assertEqual(doc["uncovered"]["state"], sb.UNMEASURED, doc["uncovered"])
        self.assertIn("НЕ ЗАДАН", doc["uncovered"]["why"])
        self.assertIn("НЕ ЗАДАН", "\n".join(sb.report(doc)))

    def test_asking_is_the_default(self):
        """Умолчание — СПРАШИВАТЬ. Иначе проводка существовала бы и молчала."""
        with tempfile.TemporaryDirectory() as tmp:
            scene = Scene(pathlib.Path(tmp))
            scene.commit("a.txt", "a")
            scene.deliver()
            doc = sb.run(scene.src, scene.dest, scene.control, do_build=False)
        self.assertNotEqual(doc["uncovered"].get("why"),
                            "вопрос НЕ ЗАДАН (--skip-uncovered)", doc["uncovered"])
