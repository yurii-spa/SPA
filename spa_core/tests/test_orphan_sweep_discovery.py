"""Ось ОТКРЫТИЯ переписи сирот: кто вообще увидел дерево (ADR-930).

Предмет — карточка `inbox-perepis-sirot-slepa-k-kopiyam-dereva-odi` (заказ G917
п. 2). Замер цикла #1043: `git worktree list --porcelain` печатает ОДНУ запись на
АДМИНИСТРАТИВНЫЙ каталог, а дерево, сделанное `cp -r` с живого worktree, несёт
`.git`, указывающий на ТОТ ЖЕ административный каталог. Из восьми деревьев
мёртвого цикла #1042 перечисление видело ДВА; байты в копиях РАСХОДИЛИСЬ (ADR у
`c1042` — 193 строки против 157 у `c1042fin`), и третьего исхода у невидимого
дерева нет ПО ПОСТРОЕНИЮ: оно не попадает в `rows`, поэтому `unmeasured 0`
честен и бесполезен — он о перечисленных.

**Сцена НАСТОЯЩАЯ, а не нарисованная.** Каждый контроль строит одноразовый
репозиторий, настоящий `git worktree add` и настоящую `cp -r` копию: проверять
копию подделкой значило бы проверять свою догадку о том, как ведёт себя git с
общим административным каталогом, — а ровно эта догадка и была дефектом.

Три семейства бомб правила доставки закрыты по построению:

* **календарь** — ни одной литеральной даты: предмет замера — население, а не
  срок, и часов прибор не спрашивает вовсе;
* **имя ветки** — `git init -b <имя>` ЯВНО, и то же имя читают все ссылки
  сцены: без `-b` Apple Git даёт `main`, а git на `ubuntu-latest` — `master`;
* **личность процесса** — pid не участвует: ось открытия о нём не спрашивает.

Корни обхода и дверь границы — ВХОДЫ (`walk_roots=`, `is_repo_dir=`), поэтому ни
одна проверка не трогает ни прод-дерево, ни `$HOME`, ни объявленные боевые
корни.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from spa_core.monitoring import orphan_sweep as sweep
from spa_core.monitoring.acceptance_tree_lineage import Unmeasured

#: Имя ветки сцены объявляется ОДИН раз и читается всеми её ссылками.
SCENE_BRANCH = "main"


def _run(*args: str, cwd: pathlib.Path) -> str:
    out = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(
            f"сцена не обеспечила предпосылку: {' '.join(args)} → код "
            f"{out.returncode}: {(out.stderr or out.stdout).strip()[:200]}")
    return out.stdout


def _repo(base: pathlib.Path, name: str) -> pathlib.Path:
    """Одноразовый репозиторий с одним коммитом. Имя ветки — ЯВНОЕ."""
    root = base / name
    root.mkdir(parents=True)
    _run("git", "init", "-b", SCENE_BRANCH, cwd=root)
    _run("git", "config", "user.email", "scene@example.invalid", cwd=root)
    _run("git", "config", "user.name", "Scene", cwd=root)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run("git", "add", "seed.txt", cwd=root)
    _run("git", "commit", "-m", "seed", cwd=root)
    return root


class DiscoveryAxis(unittest.TestCase):
    """Копия, невидимая перечислению, обязана попасть в население."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="orphan_discovery_")
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = _repo(self.base, "clone")
        # Настоящий worktree: его `.git` — ФАЙЛ со строкой `gitdir: …`.
        self.wt = self.base / "trees" / "live"
        _run("git", "worktree", "add", "--detach", str(self.wt), SCENE_BRANCH,
             cwd=self.repo)
        # Настоящая `cp -r` копия: `.git`-файл скопирован дословно и указывает
        # на ТОТ ЖЕ административный каталог. Ровно эта форма невидима git'у.
        self.copy = self.base / "trees" / "copy"
        shutil.copytree(self.wt, self.copy, symlinks=True)
        self.addCleanup(self.tmp.cleanup)

    def _discover(self, **kw):
        kw.setdefault("walk_roots", [str(self.base)])
        return sweep.discover_trees(self.repo, **kw)

    # ── предпосылка: сцена действительно воспроизводит дефект ──────────────
    def test_the_scene_reproduces_the_defect_git_listing_misses_the_copy(self):
        listed = {str(p.resolve()) for p in sweep.worktrees(self.repo)}
        self.assertIn(str(self.wt.resolve()), listed,
                      "сцена не обеспечила предпосылку: живого worktree нет в "
                      "перечислении")
        self.assertNotIn(
            str(self.copy.resolve()), listed,
            "сцена НЕ воспроизводит дефект: перечисление git'а увидело копию — "
            "на таком стенде вердикт ниже не относится к предмету")
        self.assertTrue((self.copy / ".git").is_file(),
                        "сцена не обеспечила предпосылку: у копии нет `.git`-ФАЙЛА")

    def test_the_copy_shares_the_admin_directory_with_its_original(self):
        own, why = sweep.common_dir(self.repo)
        self.assertIsNotNone(own, f"административный каталог клона не измерен: {why}")
        self.assertEqual(sweep.common_dir(self.copy)[0], own,
                         "предпосылка признака членства не выполнена: у копии "
                         "административный каталог ДРУГОЙ")

    # ── сам предмет ────────────────────────────────────────────────────────
    def test_discovery_names_the_copy_as_walk_only(self):
        doc = self._discover()
        self.assertEqual(doc["walk_state"], "measured", doc.get("walk_reason"))
        self.assertEqual(doc["discovery"].get(str(self.copy)), "walk_only",
                         f"копия не названа осью открытия: {doc['discovery']}")
        self.assertEqual(doc["discovery"].get(str(self.wt)), "both")
        self.assertEqual(doc["discovery_tally"]["walk_only"], 1,
                         doc["discovery_tally"])

    def test_the_copy_enters_the_population(self):
        listed = len(sweep.worktrees(self.repo))
        doc = self._discover()
        self.assertEqual(len(doc["trees"]), listed + 1,
                         "население не выросло на копию: "
                         f"{[str(t) for t in doc['trees']]}")

    def test_the_sweep_row_of_the_copy_carries_the_axis_and_the_caveat(self):
        doc = sweep.sweep(self.repo, ref=f"refs/heads/{SCENE_BRANCH}",
                          lineage_candidates=[str(self.repo)],
                          walk_roots=[str(self.base)], journal=self.base / "nope.jsonl",
                          cuw=None)
        self.assertEqual(doc.get("state"), "measured", doc.get("reason"))
        rows = {r["tree"]: r for r in doc["rows"]}
        self.assertIn(str(self.copy), rows, sorted(rows))
        row = rows[str(self.copy)]
        self.assertEqual(row["discovery"], "walk_only")
        # Оговорка — не украшение: HEAD копии приходит из ОБЩЕГО
        # административного каталога, и молчание об этом выдало бы ответ об
        # оригинале за ответ о копии.
        self.assertIn("ОРИГИНАЛА", row.get("discovery_caveat", ""))
        self.assertNotIn("discovery_caveat", rows[str(self.wt)],
                         "оговорка о копии поставлена зарегистрированному дереву")
        self.assertEqual(doc["discovery_tally"]["walk_only"], 1)

    def test_the_report_prints_the_copy_by_name(self):
        doc = sweep.sweep(self.repo, ref=f"refs/heads/{SCENE_BRANCH}",
                          lineage_candidates=[str(self.repo)],
                          walk_roots=[str(self.base)], journal=self.base / "nope.jsonl",
                          cuw=None)
        text = "\n".join(sweep.report(doc))
        self.assertIn("ось ОТКРЫТИЯ", text)
        self.assertIn(str(self.copy), text,
                      "копия найдена, но читателю не названа — вердикт без "
                      "адреса есть записка (класс ADR-918)")

    # ── контроль в обратную сторону: порви звено — покраснеет ──────────────
    def test_breaking_the_boundary_door_loses_the_copy(self):
        """Положительный контроль: дверь границы НЕСУЩАЯ, а не украшение."""
        doc = self._discover(is_repo_dir=lambda _p: False)
        self.assertEqual(doc["discovery_tally"]["walk_only"], 0,
                         "сломанная дверь границы всё равно нашла копию — "
                         "значит копию находит НЕ она, и контроль ничего не держит")

    def test_asking_is_dir_instead_of_exists_loses_the_copy(self):
        """Форма метки НАЗВАНА, а не угадана: у worktree `.git` — ФАЙЛ."""
        doc = self._discover(is_repo_dir=lambda p: (p / ".git").is_dir())
        self.assertEqual(
            doc["discovery_tally"]["walk_only"], 0,
            "`is_dir` нашёл копию — тогда `exists` в готовой двери ничего не "
            "решает, и ADR-928 списан напрасно")

    def test_a_foreign_tree_in_the_same_roots_is_not_taken_into_the_population(self):
        """Обход находит ЛЮБОЙ репозиторий; наш вопрос — о НАШЕМ клоне."""
        alien = _repo(self.base, "alien")
        doc = self._discover()
        self.assertNotIn(str(alien), doc["discovery"],
                         "чужой клон вошёл в население — каждое чужое дерево "
                         "машины стало бы кандидатом в сироты")
        self.assertEqual(doc["membership_tally"]["foreign"], 1,
                         doc["membership_tally"])
        self.assertTrue(any(v["tree"] == str(alien)
                            for v in doc["membership_foreign"]),
                        "чужое дерево отвергнуто МОЛЧА")

    def test_a_dangling_git_mark_is_unmeasured_not_foreign(self):
        """`.git` есть, а административного каталога нет ⇒ третий исход."""
        broken = self.base / "trees" / "broken"
        broken.mkdir(parents=True)
        (broken / ".git").write_text(
            f"gitdir: {self.base}/nowhere/.git/worktrees/ghost\n", encoding="utf-8")
        doc = self._discover()
        self.assertEqual(doc["membership_tally"]["unmeasured"], 1,
                         doc["membership_tally"])
        self.assertNotIn(str(broken), doc["discovery"],
                         "НЕ ИЗМЕРЕНО взято в население как член")
        self.assertTrue(any(v["tree"] == str(broken)
                            for v in doc["membership_unmeasured"]))

    def test_the_walk_does_not_descend_into_a_found_tree(self):
        """Сужение обхода НАЗВАНО: дерево внутри дерева достаёт перечисление.

        Вложенное дерево лежит ПРЯМО внутри найденного (`live/nested`), а не
        глубже, и это не вкусовщина: первая редакция ставила его в
        `live/inner/nested`, то есть на четвёртый уровень сцены, — и мутант
        «обход СПУСКАЕТСЯ внутрь дерева» ВЫЖИЛ, потому что до него всё равно
        не доставал предел глубины. Контроль проходил по ДРУГОЙ причине, чем
        утверждал, то есть сужение не мерил вовсе (урок #1041: выживший мутант
        прячет половину двери).
        """
        nested = self.wt / "nested"
        _run("git", "worktree", "add", "--detach", str(nested), SCENE_BRANCH,
             cwd=self.repo)
        # Предпосылка: если бы обход спускался, предел глубины его бы ПУСТИЛ —
        # иначе контроль опять проходил бы не за то.
        reachable = sweep.walk_trees([str(self.base)], depth_max=4,
                                     is_repo_dir=lambda p: (p / ".git").exists()
                                     and p.name != "live")
        self.assertIn(str(nested.resolve()), reachable["found"],
                      "сцена не обеспечила предпосылку: вложенное дерево НЕ "
                      "достижимо обходом даже при снятой границе — контроль "
                      "ниже прошёл бы из-за предела глубины, а не из-за сужения")
        doc = self._discover()
        self.assertNotIn(str(nested.resolve()),
                         sweep.walk_trees([str(self.base)])["found"],
                         "обход СПУСТИЛСЯ внутрь найденного дерева")
        self.assertEqual(doc["discovery"].get(str(nested)), "registered_only",
                         "сужение обхода либо не действует, либо не названо: "
                         f"{doc['discovery'].get(str(nested))!r}")
        text = "\n".join(sweep.report(sweep.sweep(
            self.repo, ref=f"refs/heads/{SCENE_BRANCH}",
            lineage_candidates=[str(self.repo)], walk_roots=[str(self.base)],
            journal=self.base / "nope.jsonl", cuw=None)))
        self.assertIn("ТОЛЬКО ПЕРЕЧИСЛЕНИЕМ", text,
                      "слепое пятно обхода не напечатано — «обход добавляет» "
                      "стало похвальбой без цены")

    def test_depth_limit_is_an_input_and_a_shallower_walk_loses_the_copy(self):
        """Предел глубины — ЗАМЕР и ВХОД: копия лежит на втором уровне сцены."""
        doc = self._discover(depth_max=1)
        self.assertEqual(doc["discovery_tally"]["walk_only"], 0,
                         "обход глубины 1 достал копию со второго уровня — "
                         "значит предел не действует вовсе")
        self.assertEqual(self._discover(depth_max=2)["discovery_tally"]["walk_only"], 1)


class WalkThirdOutcome(unittest.TestCase):
    """«Копий не найдено» и «корни не обойдены» обязаны выглядеть по-разному."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="orphan_walk_")
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = _repo(self.base, "clone")
        self.addCleanup(self.tmp.cleanup)

    def test_no_declared_root_exists_is_unmeasured_not_zero(self):
        doc = sweep.discover_trees(self.repo,
                                   walk_roots=[str(self.base / "no-such-root")])
        self.assertEqual(doc["walk_state"], "unmeasured")
        self.assertIn("НЕ утверждается", "\n".join(
            sweep.report({**doc, "state": "measured", "ref": "x",
                          "lineage_repo": "y", "trees": 0, "rows": [],
                          "tally": {v: 0 for v in sweep.VERDICTS},
                          "candidates": [], "candidates_with_measured_span": [],
                          "fresh_candidates": [], "fresh_base_lag_max": 1})),
            "ось не измерена, а отчёт об этом молчит — ложный ноль вернулся")

    def test_an_absent_root_is_named_by_state_not_dropped(self):
        doc = sweep.walk_trees([str(self.base), str(self.base / "ghost")])
        self.assertEqual(doc["state"], "measured")
        states = {r["root"]: r["state"] for r in doc["roots"]}
        self.assertEqual(states[str(self.base / "ghost")], "absent")
        self.assertEqual(states[str(self.base)], "walked")

    def test_root_outcomes_stay_inside_the_closed_list(self):
        for row in sweep.walk_trees([str(self.base), str(self.base / "ghost")])["roots"]:
            self.assertIn(row["state"], sweep.ROOT_STATES, row)

    def test_the_same_root_twice_is_counted_once(self):
        """`/tmp` и `/private/tmp` — один каталог; двойной счёт был бы выдумкой."""
        doc = sweep.walk_trees([str(self.base), str(self.base)])
        self.assertEqual(len(doc["roots"]), 1, doc["roots"])

    def test_membership_without_our_own_common_dir_is_unmeasured(self):
        verdict = sweep.clone_membership(self.repo, None)
        self.assertEqual(verdict["state"], "unmeasured")
        self.assertIn("не измерен", verdict["reason"])

    def test_the_boundary_door_is_the_imported_one(self):
        """Своя копия признака разошлась бы — дверь ОДНА (ADR-928)."""
        from spa_core.monitoring import membership_reach_census as reach
        self.assertIs(sweep._is_repo_dir.__wrapped__
                      if hasattr(sweep._is_repo_dir, "__wrapped__")
                      else reach._is_repo_dir, reach._is_repo_dir)
        marked = self.base / "marked"
        marked.mkdir()
        self.assertFalse(sweep._is_repo_dir(marked))
        (marked / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        self.assertTrue(sweep._is_repo_dir(marked),
                        "`.git`-ФАЙЛ не опознан деревом — именно эта форма у "
                        "worktree и у его копии")


class DeclaredSurface(unittest.TestCase):
    """Объявления — мерка, которой прибор мерит сам себя (урок ADR-913)."""

    def test_closed_lists_are_declared_and_disjoint(self):
        self.assertEqual(sweep.DISCOVERY_STATES,
                         ("both", "registered_only", "walk_only"))
        self.assertEqual(sweep.MEMBERSHIP_STATES,
                         ("member", "foreign", "unmeasured"))
        self.assertEqual(sweep.ROOT_STATES, ("walked", "absent", "unreadable"))
        self.assertEqual(sweep.WALK_STATES, ("measured", "unmeasured"))

    def test_declared_roots_are_absolute_and_unique(self):
        roots = sweep.WALK_ROOTS_DEFAULT
        self.assertTrue(roots, "корни обхода не объявлены вовсе")
        for r in roots:
            self.assertTrue(os.path.isabs(r), f"корень не абсолютен: {r}")
        self.assertEqual(len(set(roots)), len(roots), roots)

    def test_the_skip_list_does_not_pretend_to_be_the_boundary(self):
        """Граница — метка `.git`, а `WALK_SKIP_DIRS` — цена, и это разные вещи."""
        self.assertNotIn(".claude", sweep.WALK_SKIP_DIRS,
                         "литерал имени каталога вернулся в границу — ровно та "
                         "догадка, вместо которой ADR-928 ввёл метку дерева")
        self.assertIn(".git", sweep.WALK_SKIP_DIRS)


if __name__ == "__main__":
    unittest.main()
