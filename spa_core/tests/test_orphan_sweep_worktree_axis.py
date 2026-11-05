#!/usr/bin/env python3
"""Ось РАБОЧЕГО ДЕРЕВА у переписи сирот (:mod:`spa_core.monitoring.orphan_sweep`, ADR-929).

Каждая сцена — настоящая авария 2026-11-05 или её зеркало.

**Авария, ради которой ось написана.** Перепись напечатала
``✅ поднимать нечего`` над деревом ``SPA_worktrees/c1042``, которое она САМА
перечислила и у которого САМА записала ``dirty=13``, — а в нём лежала
законченная и не доставленная работа цикла #1042 (ADR, тест, журнал, заказ).
Предел «не читаю рабочее дерево» был объявлен в ДОКСТРИНГЕ модуля, то есть там,
где читателя вердикта нет; сам вердикт о нём молчал.

**Вторая авария того же дня — молчаливая порча пути.** Общая дверь ``_git``
отдаёт вывод ``.strip()``-нутым, поэтому ПЕРВАЯ строка ``git status --porcelain``
теряет ведущий пробел. Срез ``line[3:]`` съедал у неё первый символ: замер дал
``ata/adapter_status.json`` вместо ``data/adapter_status.json``, и путь, обязанный
попасть в «не считано», уехал в НАХОДКУ. Счётчик ``dirty`` рядом этого не видит
ПО ПОСТРОЕНИЮ — он считает строки, а не разбирает их. Цена ошибки измерена:
``carries 56 → 53``, ``clean 17 → 20``.

**Отметка — ВХОД сцены, а не окружение**
(`.claude/rules/deployment.md`, приём №1): ``mtime_probe`` передаётся каждой
сцене, которая о новизне спрашивает, поэтому ни один вердикт здесь не зависит от
календаря. Литеральных дат в файле нет, и стенных часов прибор на этом пути не
спрашивает.

**Имя ветки объявлено входом сцены** (``git init -b main``), а не взято у хоста:
`init.defaultBranch` у Apple Git — ``main``, у git на ``ubuntu-latest`` —
``master`` (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import orphan_sweep as osw  # noqa: E402

BRANCH = "main"

#: Отметки сцен — ВХОД. Числа произвольны и соотносятся только друг с другом:
#: ось спрашивает «что новее», а не «который час».
OLD, MID, NEW = 1_000.0, 2_000.0, 3_000.0


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} в {repo}: {out.stderr.strip()}")
    return out.stdout.strip()


def stamps(mapping, default=None):
    """Проба отметок: путь → число. Пути вне словаря — ``default``."""
    return lambda p: mapping.get(Path(p).name, default)


class WorktreeDoorOutcomes(unittest.TestCase):
    """Три исхода оси различимы (инв. #17)."""

    def test_git_silence_is_unmeasured_never_clean(self):
        got = osw.worktree_door(128, "fatal: not a git repository")
        self.assertEqual(got["worktree"], "unmeasured")
        self.assertIsNone(got["worktree_outside"],
                          "число путей при молчании git обязано быть None, а не 0")
        self.assertIn("git не назвал состояние", got["worktree_reason"])

    def test_empty_status_is_clean_and_says_there_is_no_subject(self):
        got = osw.worktree_door(0, "")
        self.assertEqual(got["worktree"], "clean")
        self.assertEqual(got["worktree_outside"], 0)
        # «мерить нечего» — НЕ «не измерено»: у чистого дерева вопроса нет.
        self.assertEqual(got["worktree_newest_state"], "no_subject")

    def test_a_carried_path_outside_data_is_named(self):
        got = osw.worktree_door(
            0, "?? docs/decisions/ADR-928-x.md\n M spa_core/monitoring/y.py",
            tree=Path("/t"), mtime_probe=stamps({"ADR-928-x.md": NEW, "y.py": OLD}))
        self.assertEqual(got["worktree"], "carries")
        self.assertEqual(got["worktree_outside"], 2)
        self.assertEqual(got["worktree_ignored"], 0)
        self.assertEqual(got["worktree_newest"], NEW, "новизна — МАКСИМУМ по путям")
        self.assertEqual(got["worktree_newest_state"], "measured")

    def test_dirt_only_under_data_is_clean_and_the_exclusion_is_counted(self):
        """`data/` — живое состояние; считать его значило бы обнулить ось."""
        got = osw.worktree_door(0, " M data/a.json\n M data/b.json",
                                tree=Path("/t"), mtime_probe=stamps({}, NEW))
        self.assertEqual(got["worktree"], "clean")
        self.assertEqual(got["worktree_outside"], 0)
        # Исключённое НАЗВАНО числом, а не умолчано.
        self.assertEqual(got["worktree_ignored"], 2)


class TheStrippedFirstLineTrap(unittest.TestCase):
    """Положительный контроль аварии порчи пути (05.11)."""

    def test_first_line_without_its_leading_space_is_still_data(self):
        # Ровно то, что отдаёт `_git` после `.strip()`: у ПЕРВОЙ строки
        # ведущего пробела нет, у остальных есть.
        got = osw.worktree_door(0, "M data/adapter_status.json\n M data/other.json",
                                tree=Path("/t"), mtime_probe=stamps({}, NEW))
        self.assertEqual(got["worktree"], "clean",
                         "обрезанная первая строка — всё ещё путь под data/")
        self.assertEqual(got["worktree_ignored"], 2)
        self.assertEqual(got["worktree_outside"], 0)

    def test_the_old_column_slice_would_have_failed_this_very_scene(self):
        """Срез по КОЛОНКЕ на той же сцене даёт путь, которого нет.

        Без этой пробы починка была бы утверждением о себе: сцена показывает,
        что прежняя мера ошибалась, и ошибалась в сторону НАХОДКИ.
        """
        line = "M data/adapter_status.json"
        self.assertEqual(line[3:], "ata/adapter_status.json")
        self.assertFalse(line[3:].startswith(osw.WORKTREE_IGNORED_PREFIX))
        # Новая дверь на той же строке отвечает верно.
        self.assertEqual(osw._porcelain_path(line), "data/adapter_status.json")

    def test_the_prefix_comes_from_live_git_not_from_a_hand_written_string(self):
        """Форма строки берётся у ЖИВОГО git, иначе проверяли бы свою выдумку."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            repo.mkdir()
            git(repo, "init", "-b", BRANCH)
            git(repo, "config", "user.email", "t@t")
            git(repo, "config", "user.name", "t")
            (repo / "data").mkdir()
            (repo / "data" / "live.json").write_text("{}")
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "base")
            (repo / "data" / "live.json").write_text('{"x":1}')
            raw = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                 capture_output=True, text=True).stdout
            self.assertTrue(raw.startswith(" M "), f"форма git изменилась: {raw!r}")
            # А вот что из неё делает общая дверь: ведущий пробел исчезает.
            code, stripped = osw._git(repo, "status", "--porcelain")
            self.assertEqual(code, 0)
            self.assertFalse(stripped.startswith(" "),
                             "предпосылка аварии снята: `_git` больше не strip-ает")
            got = osw.worktree_door(code, stripped, tree=repo,
                                    mtime_probe=stamps({}, NEW))
            self.assertEqual(got["worktree"], "clean")
            self.assertEqual(got["worktree_ignored"], 1)


class UnparsedAndUnreadAreTheirOwnOutcomes(unittest.TestCase):

    def test_an_unparsed_status_line_refuses_the_whole_axis(self):
        """Неразобранная строка ⇒ ось НЕ ИЗМЕРЕНА, а не «carries 0»."""
        got = osw.worktree_door(0, "совершенно не та форма", tree=Path("/t"),
                                mtime_probe=stamps({}, NEW))
        self.assertEqual(got["worktree"], "unmeasured")
        self.assertIsNone(got["worktree_outside"])
        self.assertIn("не разобрано строк", got["worktree_reason"])

    def test_no_stamp_read_at_all_is_unmeasured_not_old(self):
        got = osw.worktree_door(0, "?? a/b.py", tree=Path("/t"),
                                mtime_probe=lambda p: None)
        self.assertEqual(got["worktree"], "carries", "байты есть — это измерено")
        self.assertEqual(got["worktree_newest_state"], "unmeasured")
        self.assertIsNone(got["worktree_newest"])
        self.assertIn("НЕ ПРОЧИТАНА", got["worktree_reason"])

    def test_a_rename_is_judged_by_its_new_name(self):
        got = osw.worktree_door(0, "R  data/old.json -> scripts/new.py",
                                tree=Path("/t"), mtime_probe=stamps({}, MID))
        self.assertEqual(got["worktree"], "carries",
                         "предмет — НОВОЕ имя: именно его байты лежат в дереве")
        self.assertEqual(got["worktree_examples"], ["scripts/new.py"])

    def test_the_outcome_list_is_closed(self):
        self.assertEqual(set(osw.WORKTREE_STATES),
                         {"carries", "clean", "unmeasured"})


class TheOrderIsByRecencyNotByCount(unittest.TestCase):
    """Порядок — свойство ОТВЕТА, и счёт на вопрос оси не отвечает.

    Замер 05.11: по счёту первым идёт прод-дерево с 2916 чужими заметками, а
    предмет — дерево ``c1042`` с 13 путями, в котором час назад умер цикл.
    Поэтому порядок проверяется ОТДЕЛЬНО: без этой сцены подмена ключа
    сортировки на счёт прошла бы молча (все прочие сцены остались бы зелены).
    """

    def _sweep_rows(self, rows):
        """Порядок спрашивается у ДВЕРИ ПРИБОРА, а не у своей копии правила.

        Первая редакция этой сцены держала копию `sorted(...)` рядом — и
        мутация «сортировать по счёту» в самом приборе осталась ЖИВОЙ
        (M5, 19 passed). Копия правила мерит себя.
        """
        return osw.order_carrying(rows)

    def test_the_fresher_tree_comes_first_even_with_far_fewer_paths(self):
        bulky = {"tree": "/prod", "worktree": "carries",
                 "worktree_outside": 2916, "worktree_newest": OLD}
        fresh = {"tree": "/w/c1042", "worktree": "carries",
                 "worktree_outside": 13, "worktree_newest": NEW}
        got = [r["tree"] for r in self._sweep_rows([bulky, fresh])]
        self.assertEqual(got, ["/w/c1042", "/prod"],
                         "по счёту порядок был бы обратным — это и есть предмет")

    def test_a_tree_without_a_read_stamp_goes_last_and_not_first(self):
        unread = {"tree": "/w/unread", "worktree": "carries",
                  "worktree_outside": 99, "worktree_newest": None}
        known = {"tree": "/w/known", "worktree": "carries",
                 "worktree_outside": 1, "worktree_newest": OLD}
        got = [r["tree"] for r in self._sweep_rows([unread, known])]
        self.assertEqual(got, ["/w/known", "/w/unread"],
                         "«отметки нет» не выдаётся ни за свежее, ни за давнее")

    def test_the_live_sweep_builds_the_same_order(self):
        """Порядок берётся у ЖИВОГО `sweep()`, а не только у копии правила."""
        with tempfile.TemporaryDirectory() as tmp:
            lineage = Path(tmp) / "origin"
            lineage.mkdir()
            git(lineage, "init", "-b", BRANCH)
            git(lineage, "config", "user.email", "t@t")
            git(lineage, "config", "user.name", "t")
            (lineage / "f.txt").write_text("1")
            git(lineage, "add", "-A")
            git(lineage, "commit", "-m", "base")
            # ДВА порядка обязаны быть ПРОТИВОПОЛОЖНЫ, иначе сцена не способна
            # отличить новизну от счёта: у `newer` путей МЕНЬШЕ, у `older` —
            # больше. Равные счёта дали бы ничью, стабильная сортировка
            # сохранила бы входной порядок, и мутант выжил бы (M5).
            import os as _os
            for name, extra in (("older", 4), ("newer", 0)):
                w = Path(tmp) / name
                git(lineage, "worktree", "add", "--detach", str(w), BRANCH)
                (w / "f.txt").write_text(name)
                for i in range(extra):
                    (w / f"extra{i}.py").write_text("x = 1")
            stamp = {"older": OLD, "newer": NEW}
            for name in ("older", "newer"):
                for f in sorted((Path(tmp) / name).glob("*")):
                    _os.utime(f, (stamp[name], stamp[name]))
            # РОДОСЛОВНЫЙ КЛОН — ВХОД СЦЕНЫ, а не свойство хоста.
            # `LINEAGE_CANDIDATES_DEFAULT` — литеральные пути рабочего Мака
            # (`~/Documents/SPA_mirror`, `~/Documents/SPA_Claude`); на раннере
            # их нет, `pick_lineage_repo` честно отвечает `unmeasured`, и первая
            # редакция этой сцены была ЗЕЛЕНА здесь и КРАСНА в CI (прогон
            # 42090640014). Половина инъекции — та же бомба: сцена построила
            # настоящий git-репозиторий и при этом оставила ВТОРУЮ дверь к
            # окружению открытой (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ»).
            doc = osw.sweep(lineage, ref=BRANCH, previous=None, cuw=None,
                            lineage_candidates=[str(lineage)])
            self.assertEqual(doc["state"], "measured", doc.get("reason"))
            # Положительный контроль инъекции: ответ пришёл о МОЁМ клоне.
            # Без него подстановка хостового пути вернулась бы незамеченной.
            self.assertEqual(Path(doc["lineage_repo"]), lineage)
            rows = {Path(r["tree"]).name: r for r in doc["worktree_carrying"]}
            self.assertGreater(rows["older"]["worktree_outside"],
                               rows["newer"]["worktree_outside"],
                               "предпосылка сцены: по СЧЁТУ порядок обратный")
            order = [Path(r["tree"]).name for r in doc["worktree_carrying"]]
            self.assertEqual(order[:2], ["newer", "older"])

    def test_an_undeclared_lineage_clone_is_unmeasured_not_a_verdict(self):
        """Отрицательный контроль того же механизма, что покраснел в CI.

        Он держит ДВА утверждения сразу: родословная без клона — третий исход
        (а не «поднимать нечего»), и именно ЭТО происходило на раннере, пока
        сцена выше не объявила свой клон. Без него починка была бы
        утверждением о себе.
        """
        doc = osw.sweep(Path("/nonexistent-tree"), ref=BRANCH, previous=None,
                        cuw=None, lineage_candidates=["/nonexistent-clone"])
        self.assertEqual(doc["state"], "unmeasured")
        self.assertIn("клона нет на диске", doc["reason"])


class TheReportCarriesTheAxis(unittest.TestCase):
    """Предел обязан стоять в ВЫВОДЕ, а не только в докстринге."""

    def _doc(self):
        return {
            "state": "measured", "ref": "origin/main", "trees": 2,
            "lineage_repo": "/mirror", "lineage_rejected": [],
            "tally": {v: 0 for v in osw.VERDICTS},
            "candidates": [], "candidates_with_measured_span": [],
            "fresh_candidates": [], "fresh_base_lag_max": 100,
            "fresh_to_raise": [],
            "worktree_tally": {"carries": 1, "clean": 1, "unmeasured": 0},
            "worktree_ignored_prefix": "data/",
            "worktree_carrying": [{
                "tree": "/w/c1042", "worktree_outside": 13,
                "worktree_ignored": 0, "worktree_newest": NEW,
                "worktree_newest_state": "measured",
                "worktree_examples": ["docs/decisions/ADR-928-x.md"]}],
            "rows": [],
        }

    def test_the_headline_names_its_subject_and_does_not_claim_more(self):
        lines = osw.report(self._doc())
        head = [x for x in lines if "поднимать" in x]
        self.assertTrue(head, "строка вердикта исчезла")
        self.assertIn("ПО КОММИТАМ", head[0],
                      "безусловное «поднимать нечего» и есть предмет ADR-929")

    def test_the_carrying_tree_is_printed_with_its_newest_byte(self):
        lines = "\n".join(osw.report(self._doc()))
        self.assertIn("/w/c1042", lines)
        self.assertIn("НЕСЁТ НЕЗАКОММИЧЕННОЕ", lines)
        self.assertIn("ADR-928-x.md", lines)
        self.assertIn("ось РАБОЧЕГО ДЕРЕВА", lines)
        # Годность к подъёму прибор не судит (ADR-908: признак точностью 3/5).
        self.assertIn("НЕ СУДИТСЯ", lines)

    def test_an_unmeasured_row_is_printed_by_name(self):
        doc = self._doc()
        doc["worktree_tally"] = {"carries": 0, "clean": 0, "unmeasured": 1}
        doc["worktree_carrying"] = []
        doc["rows"] = [{"tree": "/w/broken", "worktree": "unmeasured",
                        "worktree_reason": "git не назвал состояние дерева"}]
        lines = "\n".join(osw.report(doc))
        self.assertIn("ось рабочего дерева НЕ ИЗМЕРЕНА", lines)
        self.assertIn("/w/broken", lines)


class TheAxisIsAskedOfEveryTreeNotOnlyCandidates(unittest.TestCase):
    """Предмет оси — ровно те деревья, которые вердикт `on_main` исключает."""

    def test_a_tree_whose_head_is_on_the_ref_still_gets_the_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            lineage = Path(tmp) / "origin"
            lineage.mkdir()
            git(lineage, "init", "-b", BRANCH)
            git(lineage, "config", "user.email", "t@t")
            git(lineage, "config", "user.name", "t")
            (lineage / "f.txt").write_text("1")
            git(lineage, "add", "-A")
            git(lineage, "commit", "-m", "base")

            work = Path(tmp) / "work"
            git(lineage, "worktree", "add", "--detach", str(work), BRANCH)
            # Законченная и НЕ закоммиченная работа — ровно случай #1042.
            (work / "docs").mkdir(parents=True, exist_ok=True)
            (work / "docs" / "ADR-999-x.md").write_text("# решение")

            row = osw._tree_row(work, lineage, BRANCH)
            self.assertEqual(row["verdict"], "on_main",
                             "предпосылка сцены: по коммитам дерево НЕ кандидат")
            self.assertEqual(row["worktree"], "carries",
                             "ось обязана спрашиваться и у НЕ кандидата — "
                             "иначе она не задана там, где единственно нужна")
            # git сворачивает ЦЕЛИКОМ неотслеживаемый каталог в ОДНУ запись
            # `?? docs/` — см. `TheUntrackedDirectoryCollapse` ниже. Ось
            # считает ЗАПИСИ состояния, и это объявлено, а не подразумевается.
            self.assertEqual(row["worktree_examples"], ["docs/"])
            self.assertEqual(row["worktree_outside"], 1)


class TheUntrackedDirectoryCollapse(unittest.TestCase):
    """Объявленный предел: ось считает ЗАПИСИ состояния, а не файлы.

    ``git status --porcelain`` сворачивает целиком неотслеживаемый каталог в
    одну запись (``?? docs/``). Поэтому число оси — это число записей git, и
    дерево с сотней новых файлов в одном новом каталоге даст ``1``.

    Снять свёртку мог бы ``--untracked-files=all``, но флаг пришлось бы менять у
    ТОГО ЖЕ вызова, из которого рядом считается ``dirty``, то есть изменить
    ПУБЛИКУЕМОЕ число соседа ради своего (тот же порядок, что у ``_py_files`` в
    ADR-928, и та же причина не трогать общую дверь). Предел объявлен здесь и в
    модуле; порядок деревьев он не портит — отметка берётся у каталога, а она
    двигается вместе с записью в него.
    """

    def test_a_whole_new_directory_is_one_entry_and_this_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            repo.mkdir()
            git(repo, "init", "-b", BRANCH)
            git(repo, "config", "user.email", "t@t")
            git(repo, "config", "user.name", "t")
            (repo / "keep.txt").write_text("1")
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "base")
            new = repo / "fresh"
            new.mkdir()
            for i in range(3):
                (new / f"f{i}.py").write_text("x = 1")
            code, out = osw._git(repo, "status", "--porcelain")
            self.assertEqual(code, 0)
            self.assertEqual(out.splitlines(), ["?? fresh/"],
                             "предпосылка предела: git свернул каталог сам")
            got = osw.worktree_door(code, out, tree=repo,
                                    mtime_probe=stamps({"fresh": NEW}))
            self.assertEqual(got["worktree"], "carries")
            self.assertEqual(got["worktree_outside"], 1,
                             "три файла — ОДНА запись; число оси есть число записей")
            self.assertEqual(got["worktree_newest"], NEW,
                             "отметка берётся у каталога и двигается с записью")


if __name__ == "__main__":
    unittest.main()
