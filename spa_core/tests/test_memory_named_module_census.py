"""Сторож прибора «запись памяти называет модуль, которого на `origin/main` нет» (ADR-1084).

Каждая сцена — положительный контроль: мера обязана КРАСНЕТЬ на том состоянии, ради
которого написана, и быть зелёной на верном. Проверяется ИСХОД прибора, а не его форма.

Время здесь предметом не является — литеральных дат в файле нет вовсе.
Имя ветки одноразового репозитория ОБЪЯВЛЕНО (`git init -b`): `.claude/rules/deployment.md`
§ «GIT-ОКРУЖЕНИЕ в тестах» — `init.defaultBranch` хоста есть необъявленный вход, и на
`ubuntu-latest` он даёт `master`, а на Маке `main`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts import memory_named_module_census as census  # noqa: E402

BRANCH = "main"


def _disposable_repo(root: str, paths: dict) -> str:
    """Одноразовый репозиторий с ОБЪЯВЛЕННЫМ именем ветки и ссылкой `origin/<BRANCH>`."""
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-b", BRANCH, repo], check=True,
                   capture_output=True)
    for rel, body in paths.items():
        dest = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(body)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "scene"], check=True, capture_output=True)
    # ссылка origin/<BRANCH> делается локально: сети у сцены нет по построению
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-C", repo, "update-ref", f"refs/remotes/origin/{BRANCH}", head],
                   check=True, capture_output=True)
    return repo


def _memory(root: str, notes: dict) -> str:
    mem = os.path.join(root, "memory")
    os.makedirs(mem)
    for name, body in notes.items():
        with open(os.path.join(mem, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    return mem


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: измерено · измерено и находок нет · НЕ ИЗМЕРЕНО — три разных ответа."""

    def test_an_existing_module_is_not_a_finding(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"a.md": "зовётся `scripts/real_tool.py` каждый цикл"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_EXISTS, rep)
            self.assertEqual(rep["findings"], [])
            self.assertEqual(census.exit_code(rep), census.EXIT_CLEAN)
            self.assertEqual(rep["modules_named"], 1, rep)

    def test_an_absent_module_IS_a_finding_and_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {
                "ghost.md": "класс МЕРИТ ПРИБОР `spa_core/monitoring/ghost_census.py`",
            })
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_ABSENT, rep)
            self.assertEqual(census.exit_code(rep), census.EXIT_FINDINGS)
            self.assertEqual(len(rep["findings"]), 1, rep)
            self.assertEqual(rep["findings"][0]["note"], "ghost.md")
            self.assertIn("spa_core/monitoring/ghost_census.py",
                          rep["findings"][0]["absent"])
            self.assertIn("ghost_census.py", census.format_report(rep))

    def test_an_unreadable_memory_dir_is_UNMEASURED_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            rep = census.build_report(os.path.join(root, "nope"), repo,
                                      f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_UNMEASURED, rep)
            self.assertEqual(census.exit_code(rep), census.EXIT_UNMEASURED)
            self.assertTrue(rep["why"], "причина обязана быть НАЗВАНА")
            self.assertIn("НЕ ИЗМЕРЕНО", census.format_report(rep))

    def test_an_unreadable_ref_is_UNMEASURED_and_NOT_an_empty_tree(self):
        """Несущая сцена: пустой набор объявил бы находкой КАЖДУЮ запись."""
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"a.md": "зовётся `scripts/real_tool.py`"})
            rep = census.build_report(mem, repo, "origin/no-such-ref")
            self.assertEqual(rep["outcome"], census.OUT_UNMEASURED, rep)
            self.assertEqual(census.exit_code(rep), census.EXIT_UNMEASURED)
            self.assertEqual(rep["findings"], [],
                             "непрочитанная ссылка НЕ имеет права рождать находки")
            self.assertTrue(rep["why"])

    def test_an_undecodable_note_is_UNMEASURED_not_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"ok.md": "зовётся `scripts/real_tool.py`"})
            with open(os.path.join(mem, "broken.md"), "wb") as fh:
                fh.write(b"\xff\xfe\x00bad bytes")
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_UNMEASURED, rep)
            self.assertEqual(census.exit_code(rep), census.EXIT_UNMEASURED)
            self.assertEqual(len(rep["undecodable"]), 1, rep)

    def test_an_empty_memory_dir_is_UNMEASURED_not_clean(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_UNMEASURED, rep)
            self.assertEqual(census.exit_code(rep), census.EXIT_UNMEASURED)


class PlaceholdersAreCOUNTEDNotSwallowed(unittest.TestCase):
    """Отсев заполнителя прозы обязан быть ВИДЕН: молчаливый отсев однажды спрячет находку."""

    def test_a_prose_placeholder_is_not_a_finding(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"p.md": "вызов `scripts/X.py` ломает проводку"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_EXISTS, rep)
            self.assertEqual(rep["findings"], [])

    def test_the_placeholder_is_COUNTED(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"p.md": "`scripts/X.py` и `spa_core/tests/test_x.py`"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["placeholders_skipped"], 2, rep)

    def test_a_real_module_next_to_a_placeholder_is_STILL_a_finding(self):
        """Различитель: отсев по заполнителю не вправе глотать соседа в той же записи."""
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {
                "mixed.md": "`scripts/X.py` — форма; мерит `scripts/ghost_tool.py`",
            })
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_ABSENT, rep)
            self.assertEqual(rep["findings"][0]["absent"], ["scripts/ghost_tool.py"])
            self.assertEqual(rep["placeholders_skipped"], 1, rep)


class TheAxisIsNarrowedBYDESIGN(unittest.TestCase):
    """`data/` в .gitignore по построению: «нет на origin» там НЕ значит «не существует»."""

    def test_a_runtime_data_path_is_NOT_asked_about(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"d.md": "артефакт `data/undelivered_work_census.json`"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_EXISTS, rep)
            self.assertEqual(rep["modules_named"], 0, rep)

    def test_a_prose_shorthand_is_NOT_asked_about(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"s.md": "общий стандарт эвиденса `docs/37`"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["modules_named"], 0, rep)


class TheCloneDepthIsPRINTEDNotAssumed(unittest.TestCase):
    """Поправка #1031: выбор и способность клона ПЕЧАТАЮТСЯ, а не подставляются молча."""

    def test_the_depth_and_the_question_are_in_the_report(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"a.md": "зовётся `scripts/real_tool.py`"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertIn(rep["clone_depth"], ("полный", "УСЕЧЁН"), rep)
            self.assertIn("вершин", str(rep["question"]))
            text = census.format_report(rep)
            self.assertIn("клон", text)
            self.assertIn(f"origin/{BRANCH}", text)


class TheLiveCallIsMeasuredNotAssumed(unittest.TestCase):
    """Живой зов стои́т в теле `test_*`, а НЕ в `setUpClass`: иначе пробой он не считается."""

    def test_the_live_tree_gets_one_of_the_three_declared_outcomes(self):
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        rep = census.build_report(census.DEFAULT_MEMORY_DIR, root, "origin/main")
        self.assertIn(rep["outcome"],
                      (census.OUT_EXISTS, census.OUT_ABSENT, census.OUT_UNMEASURED), rep)
        if rep["outcome"] == census.OUT_UNMEASURED:
            self.assertTrue(rep["why"], "НЕ ИЗМЕРЕНО обязано назвать причину")
        else:
            # числа населения тут НЕ закрепляются: они убывают по мере починки записей,
            # и литерал превратил бы сторожа в будильник (урок ADR-348)
            self.assertIsInstance(rep["notes_total"], int)
            self.assertEqual(census.exit_code(rep),
                             census.EXIT_FINDINGS if rep["findings"] else census.EXIT_CLEAN)


class TheCLIReturnsTheCodeOfTheOutcome(unittest.TestCase):
    def test_cli_code_follows_the_outcome_not_the_print(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"g.md": "мерит `scripts/ghost_tool.py`"})
            code = census.main(["--memory-dir", mem, "--repo-root", repo,
                                "--ref", f"origin/{BRANCH}", "--json"])
            self.assertEqual(code, census.EXIT_FINDINGS)
            mem2 = _memory(os.path.join(root, "second"),
                           {"g.md": "зовётся `scripts/real_tool.py`"})
            code2 = census.main(["--memory-dir", mem2, "--repo-root", repo,
                                 "--ref", f"origin/{BRANCH}"])
            self.assertEqual(code2, census.EXIT_CLEAN)


if __name__ == "__main__":
    unittest.main()


class AnEmptyTreeIsNotAnAnswer(unittest.TestCase):
    """Дыра покрытия, найденная мутацией M02: `ls-tree` вернул НОЛЬ строк при коде 0."""

    def test_a_tree_read_as_EMPTY_is_UNMEASURED_not_every_note_a_finding(self):
        with tempfile.TemporaryDirectory() as root:
            repo = os.path.join(root, "repo")
            os.makedirs(repo)
            subprocess.run(["git", "init", "-b", BRANCH, repo], check=True,
                           capture_output=True)
            # коммит БЕЗ единого файла: дерево вершины пусто, а git отвечает кодом 0
            subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "--allow-empty", "-m", "empty"], check=True,
                           capture_output=True)
            head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            subprocess.run(["git", "-C", repo, "update-ref",
                            f"refs/remotes/origin/{BRANCH}", head], check=True,
                           capture_output=True)
            paths, why = census.tracked_paths(repo, f"origin/{BRANCH}")
            self.assertIsNone(paths, "пустое дерево НЕ имеет права стать ответом")
            self.assertTrue(why, "причина обязана быть НАЗВАНА")

            mem = _memory(root, {"a.md": "зовётся `scripts/real_tool.py`"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_UNMEASURED, rep)
            self.assertEqual(rep["findings"], [],
                             "пустое дерево не вправе объявить находкой КАЖДУЮ запись")


class TheReasonIsPRINTEDNotJustTheWord(unittest.TestCase):
    """Дыра покрытия, найденная мутацией M14: слово «НЕ ИЗМЕРЕНО» без причины."""

    def test_the_unmeasured_line_carries_the_REASON(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            rep = census.build_report(os.path.join(root, "nope"), repo,
                                      f"origin/{BRANCH}")
            text = census.format_report(rep)
            self.assertIn("НЕ ИЗМЕРЕНО", text)
            self.assertIn(str(rep["why"]), text,
                          "причина обязана ПЕЧАТАТЬСЯ, а не только лежать в отчёте")


class TheDepthRefusalIsItsOwnOutcome(unittest.TestCase):
    """Дыра покрытия, найденная мутацией M15: отказ git о глубине — НЕ «полный клон»."""

    def test_git_refusing_the_depth_question_is_UNMEASURED_not_full(self):
        with tempfile.TemporaryDirectory() as root:
            not_a_repo = os.path.join(root, "plain")
            os.makedirs(not_a_repo)
            depth = census.clone_depth(not_a_repo)
            self.assertIn("НЕ ИЗМЕРЕНА", depth, depth)
            self.assertNotEqual(depth, "полный")

    def test_a_real_repo_answers_one_of_the_two_measured_words(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            self.assertIn(census.clone_depth(repo), ("полный", "УСЕЧЁН"))


class AbsenceMayBeDECLAREDWithAReason(unittest.TestCase):
    """`ABSENT-OK: <причина>` — решение на протоколе, образец `FROZEN-DATE-OK`."""

    def test_a_declared_absence_is_not_a_finding_and_is_COUNTED(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {
                "d.md": "команда про удалённый `scripts/gone_tool.py` "
                        "ABSENT-OK: иллюстрация удаления, файла нет НАМЕРЕННО",
            })
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_EXISTS, rep)
            self.assertEqual(rep["findings"], [])
            self.assertEqual(rep["declared_absent"], 1, rep)
            self.assertIn("отсутствий ОБЪЯВЛЕНО с причиной 1", census.format_report(rep))

    def test_a_declaration_WITHOUT_a_reason_does_NOT_exempt(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {"d.md": "`scripts/gone_tool.py` ABSENT-OK:"})
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_ABSENT, rep)
            self.assertEqual(rep["declared_absent"], 0, rep)

    def test_a_declaration_does_NOT_reach_a_NEIGHBOUR_line(self):
        """Различитель: пометка в шапке не вправе прикрыть всю запись (урок M07)."""
        with tempfile.TemporaryDirectory() as root:
            repo = _disposable_repo(root, {"scripts/real_tool.py": "x = 1\n"})
            mem = _memory(root, {
                "d.md": "`scripts/gone_a.py` ABSENT-OK: назван намеренно\n"
                        "а вот `scripts/gone_b.py` объявления НЕ несёт\n",
            })
            rep = census.build_report(mem, repo, f"origin/{BRANCH}")
            self.assertEqual(rep["outcome"], census.OUT_ABSENT, rep)
            self.assertEqual(rep["findings"][0]["absent"], ["scripts/gone_b.py"], rep)
            self.assertEqual(rep["declared_absent"], 1, rep)
