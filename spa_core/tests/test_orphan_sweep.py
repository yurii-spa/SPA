#!/usr/bin/env python3
"""Контроль переписи сирот (:mod:`spa_core.monitoring.orphan_sweep`, ADR-923).

Каждая сцена — ОДНА настоящая авария или её зеркало, и сцены строятся на живом
`git`, а не на подменённом словаре: контроль, собранный руками, мерил бы свой же
словарь, а не проводку (урок #944/#945).

**Имя ветки объявлено входом сцены** (`git init -b main`), а не взято у хоста:
`init.defaultBranch` у Apple Git `main`, у git на `ubuntu-latest` — `master`,
и фикстура без `-b` зелена здесь и красна там
(`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»).

Часов в приборе нет вовсе, поэтому замороженных дат здесь нет и быть не может.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.acceptance_tree_lineage import Unmeasured  # noqa: E402
from spa_core.monitoring import orphan_sweep as osw  # noqa: E402

BRANCH = "main"


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} в {repo}: {out.stderr.strip()}")
    return out.stdout.strip()


def commit(repo, name, text="x"):
    (Path(repo) / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


class OrphanSweepScenes(unittest.TestCase):
    """Сцены на настоящем git: upstream + его клон + деревья клона."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # upstream — то, что играет роль origin
        self.up = base / "upstream"
        self.up.mkdir()
        git(self.up, "init", "-b", BRANCH, "--quiet")
        git(self.up, "config", "user.email", "t@t")
        git(self.up, "config", "user.name", "t")
        for i in range(3):
            commit(self.up, f"f{i}.txt")
        self.up_tip = git(self.up, "rev-parse", BRANCH)

        # ПОЛНЫЙ клон — он же играет роль зеркала (отвечает о происхождении)
        self.full = base / "full"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.full))
        git(self.full, "config", "user.email", "t@t")
        git(self.full, "config", "user.name", "t")

        # рабочий клон, чьи деревья переписываются
        self.work = base / "work"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.work))
        git(self.work, "config", "user.email", "t@t")
        git(self.work, "config", "user.name", "t")
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def sweep(self, lineage=None):
        return osw.sweep(self.work, ref=f"origin/{BRANCH}",
                         lineage_candidates=lineage or [str(self.full)])

    # ── сцена 1: дерево на вершине ref — поднимать нечего ────────────────────
    def test_a_tree_on_the_ref_is_not_a_candidate(self):
        doc = self.sweep()
        self.assertEqual(doc["state"], "measured", doc.get("reason"))
        self.assertEqual(doc["tally"]["on_main"], 1)
        self.assertEqual(doc["fresh_candidates"], [])
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(self.full)]), 0)

    # ── сцена 2: НАСТОЯЩАЯ сирота — коммит поверх вершины, никуда не уехал ──
    def test_a_fresh_unpushed_commit_is_a_fresh_candidate(self):
        sha = commit(self.work, "orphan.txt")
        doc = self.sweep()
        row = next(r for r in doc["rows"] if r["head"] == sha)
        self.assertEqual(row["verdict"], "never_pushed")
        self.assertEqual(row["span"], 1)
        self.assertEqual(row["span_state"], "measured")
        self.assertEqual(row["base_lag"], 0, "база сироты ЕСТЬ вершина ref")
        self.assertEqual([r["head"] for r in doc["fresh_candidates"]], [sha])
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(self.full)]), 1)

    # ── сцена 3: ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 04.11 — усечённый клон ───────
    def test_a_shallow_lineage_clone_is_unmeasured_not_an_answer(self):
        """Усечённый клон обязан дать НЕ ИЗМЕРЕНО, а не ложного кандидата.

        Это дословное воспроизведение дефекта, который родил первую редакцию
        прибора ADR-918 и который замер #1036 нашёл в ручной переписи сирот:
        на усечённом графе `merge-base --is-ancestor` отвечает «не предок»
        кодом 0 и без предупреждения, и усечение РОЖДАЕТ кандидата.
        """
        commit(self.up, "more.txt")           # чтобы истории было что терять
        shallow = self.base / "shallow"
        git(self.base, "clone", "--quiet", "--depth", "1",
            f"file://{self.up}", str(shallow))
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository"), "true",
                         "предпосылка сцены НЕ ОБЕСПЕЧЕНА: клон не усечён")
        doc = self.sweep(lineage=[str(shallow)])
        self.assertEqual(doc["state"], "unmeasured")
        self.assertIn("усеч", doc["reason"].lower())
        self.assertEqual(doc["rows"], [], "у НЕ ИЗМЕРЕНО не бывает строк-находок")
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(shallow)]), 2)

    # ── сцена 4: коммит в полном клоне ЕСТЬ, но не на ref — это не сирота ───
    def test_a_commit_on_an_unmerged_branch_is_not_an_orphan(self):
        git(self.work, "checkout", "--quiet", "-b", "side")
        sha = commit(self.work, "side.txt")
        git(self.work, "push", "--quiet", "origin", "side")
        git(self.full, "fetch", "--quiet", "origin", "side")
        doc = self.sweep()
        row = next(r for r in doc["rows"] if r["head"] == sha)
        self.assertEqual(row["verdict"], "off_main_branch")
        self.assertEqual(doc["fresh_candidates"], [],
                         "невлитая ветка есть вопрос мержа, а не подъёма")

    # ── сцена 5: кандидат со СТАРОЙ базой свежим НЕ является ────────────────
    def test_a_candidate_on_a_stale_base_is_a_candidate_but_not_fresh(self):
        """Форма `b71dde9e2` замера #1036: пролёт 1, база отстаёт на 4737.

        Разделяет не ПРОЛЁТ, а отставание БАЗЫ. Рука цикла #1036 выбрала
        пролёт и совпала с правдой случайно — этот тест и есть промах-половина
        той ошибки.
        """
        older = git(self.work, "rev-parse", f"origin/{BRANCH}~2")
        git(self.work, "checkout", "--quiet", "--detach", older)
        sha = commit(self.work, "stale.txt")
        doc = osw.sweep(self.work, ref=f"origin/{BRANCH}",
                        lineage_candidates=[str(self.full)],
                        fresh_base_lag_max=1)
        row = next(r for r in doc["rows"] if r["head"] == sha)
        self.assertEqual(row["verdict"], "never_pushed")
        self.assertEqual(row["span"], 1, "пролёт тот же, что у настоящей сироты")
        self.assertEqual(row["base_lag"], 2, "а база отстаёт — вот разделитель")
        self.assertIn(row, doc["candidates_with_measured_span"])
        self.assertEqual(doc["fresh_candidates"], [])
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(self.full),
                                   "--fresh-base-lag-max", "1"]), 0)

    def test_a_days_worth_of_churn_does_not_hide_a_real_orphan(self):
        """ПРОМАХ-половина второй ошибки: порог 0 ошибался бы в ПРОПУСК.

        Сирота #1035 имела `base_lag` = 0 только потому, что её база ещё была
        вершиной. Один автокоммит сайт-кустодиана поверх — и порог 0 объявил бы
        настоящую сироту «не свежей» МОЛЧА. Порог УМОЛЧАНИЯ обязан переживать
        суточный поток `main`.
        """
        sha = commit(self.work, "orphan.txt")
        for i in range(3):            # поверх базы сироты приехало чужое
            commit(self.up, f"churn{i}.txt")
        git(self.work, "fetch", "--quiet", "origin", BRANCH)
        git(self.full, "fetch", "--quiet", "origin", BRANCH)
        doc = self.sweep()
        row = next(r for r in doc["rows"] if r["head"] == sha)
        self.assertEqual(row["verdict"], "never_pushed")
        self.assertEqual(row["base_lag"], 3, "база отстала на чужой поток")
        self.assertIn(row, doc["fresh_candidates"],
                      "суточный поток main НЕ ИМЕЕТ ПРАВА прятать сироту")

    # ── сцена 6: пролёт за пределом — НЕ ИЗМЕРЕНО, а не число ───────────────
    def test_a_span_beyond_the_limit_is_unmeasured_not_the_limit(self):
        for i in range(3):
            commit(self.work, f"deep{i}.txt")
        doc = osw.sweep(self.work, ref=f"origin/{BRANCH}",
                        lineage_candidates=[str(self.full)], limit=2)
        row = next(r for r in doc["rows"] if r["verdict"] == "never_pushed")
        self.assertIsNone(row["span"])
        self.assertEqual(row["span_state"], "unmeasured")
        self.assertNotIn(row, doc["fresh_candidates"])
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(self.full),
                                   "--span-limit", "2"]), 0,
                         "НЕ ИЗМЕРЕНО не выдаётся за находку")

    # ── сцена 7: ноль отставания и «не сосчитали» РАЗЛИЧИМЫ ────────────────
    def test_zero_lag_and_uncounted_lag_are_distinct(self):
        commit(self.work, "orphan.txt")
        doc = self.sweep()
        row = next(r for r in doc["rows"] if r["verdict"] == "never_pushed")
        self.assertEqual(row["base_lag_state"], "measured")
        self.assertEqual(row["base_lag"], 0)
        self.assertIsNone(osw._count_span(self.full, "no-such-ref..HEAD"),
                          "несосчитанное отставание обязано быть None, а не 0")


class OrphanSweepRefusals(unittest.TestCase):
    """Отказы прибора: молчание никогда не выдаётся за чистый ответ."""

    def test_worktrees_refuses_instead_of_returning_an_empty_list(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(Unmeasured):
                osw.worktrees(Path(t))   # не репозиторий

    def test_no_full_clone_at_all_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as t:
            doc = osw.sweep(t, lineage_candidates=[str(Path(t) / "nope")])
            self.assertEqual(doc["state"], "unmeasured")
            self.assertIn("nope", doc["reason"])

    def test_git_answered_with_zero_trees_is_a_refusal_not_an_empty_sweep(self):
        """`git` ответил успехом и НИ ОДНИМ деревом — это молчание, не ответ.

        Сегодня `git worktree list` на исправном репозитории всегда называет
        хотя бы главное дерево, поэтому сцену на живом git построить нельзя —
        и ровно поэтому контроль ставится у ЕДИНСТВЕННОЙ двери к git
        (`orphan_sweep._git`). Без него страж fail-CLOSED пережил мутацию
        6/9 замера #1036: «не ответил» было бы неотличимо от «деревьев нет».
        """
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(osw, "_git", return_value=(0, "")):
                with self.assertRaises(Unmeasured) as ctx:
                    osw.worktrees(Path(t))
            self.assertIn("ноль деревьев", str(ctx.exception))

    def test_git_silence_about_a_commit_is_unmeasured_not_never_pushed(self):
        """«git не ответил, есть ли коммит» НИКОГДА не значит «коммита нет».

        Это дословно та подмена, которой усечённый клон РОЖДАЕТ кандидата
        (ADR-918): склей их — и дерево, про которое ничего не известно,
        поедет в отчёт как сирота, готовая к подъёму. Мутация 7/9 замера
        #1036 пережила батарею без этого контроля.
        """
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "r"
            repo.mkdir()
            git(repo, "init", "-b", BRANCH, "--quiet")
            git(repo, "config", "user.email", "t@t")
            git(repo, "config", "user.name", "t")
            commit(repo, "a.txt")

            real = osw._git

            def answers(r, *args, **kw):
                if args[:2] == ("cat-file", "-e"):
                    return 129, "git ответил кодом, которого мы не понимаем"
                return real(r, *args, **kw)

            with mock.patch.object(osw, "_git", side_effect=answers):
                row = osw._tree_row(repo, repo, f"{BRANCH}")
            self.assertEqual(row["verdict"], "unmeasured")
            self.assertNotEqual(row["verdict"], "never_pushed")
            self.assertIn("не ответил", row["reason"])

    def test_the_threshold_separates_two_measured_populations(self):
        """Порог держится НЕРАВЕНСТВОМ между двумя замерами, а не своей копией.

        Сверять число с самим собой значило бы мерить свою же мерку (урок
        #1027: оба выживших мутанта были ровно этой болезнью). Поэтому
        проверяется отношение порога к ИЗМЕРЕННЫМ населениям: он обязан
        переживать самые загруженные сутки `main` и отвергать ближайшее
        заброшенное дерево.
        """
        self.assertLess(osw.MEASURED_BUSIEST_DAY_ON_REF, osw.FRESH_BASE_LAG_MAX,
                        "порог ниже суточного потока main ПРЯЧЕТ сироту")
        self.assertLess(osw.FRESH_BASE_LAG_MAX, osw.MEASURED_NEAREST_ABANDONED,
                        "порог выше ближайшего заброшенного дерева зовёт его работой")

    def test_the_verdict_vocabulary_is_closed_and_the_tally_balances(self):
        self.assertIn("unmeasured", osw.VERDICTS)
        self.assertEqual(osw.CANDIDATE_VERDICTS, ("never_pushed",))
        self.assertTrue(set(osw.CANDIDATE_VERDICTS) <= set(osw.VERDICTS))


if __name__ == "__main__":
    unittest.main()
