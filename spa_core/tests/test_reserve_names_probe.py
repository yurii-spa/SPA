#!/usr/bin/env python3
"""Приёмка ПРОБЫ `reserve_names_what_it_cannot_save` (ADR-1123).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом, где
она зелена на целом контуре и КРАСНА на каждом порванном звене — с названным звеном,
и где она НЕ проходит подстрокой (ADR-333).

Дерево — ВХОД пробы, поэтому все сцены собираются в одноразовом каталоге: живое
`data/`, прод-трекер и флот не трогаются ни одной из них. Имя ветви — тоже ВХОД
(`git init -b`): `init.defaultBranch` есть свойство ХОСТА.

FROZEN-DATE-OK: литеральных дат в файле нет — предмет меры есть ДОСТИЖИМОСТЬ объекта,
а не свежесть чего-либо.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED)

PROBE_NAME = "reserve_names_what_it_cannot_save"
_REAL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEASURE_REL = os.path.join("spa_core", "monitoring", "stranded_content.py")
RESERVE_REL = os.path.join("scripts", "stack_bundle.py")
BRANCH = "scene-main"


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={r.returncode}: {r.stderr[:300]}")
    return r.stdout


class ProbeAcceptance(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tree = os.path.join(self.tmp, "дерево")
        os.makedirs(os.path.join(self.tree, "spa_core", "monitoring"))
        os.makedirs(os.path.join(self.tree, "scripts"))
        # ПОБАЙТОВЫЕ копии: проба обязана судить ровно тот код, который доставляется.
        for rel in (MEASURE_REL, RESERVE_REL):
            shutil.copy2(os.path.join(_REAL_ROOT, rel), os.path.join(self.tree, rel))
        _git(self.tree, "init", "-b", BRANCH, "-q")
        _git(self.tree, "config", "user.email", "scene@example.invalid")
        _git(self.tree, "config", "user.name", "scene")
        with open(os.path.join(self.tree, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("база сцены\n")
        _git(self.tree, "add", "README.md")
        _git(self.tree, "commit", "-q", "-m", "база")
        _git(self.tree, "update-ref", f"refs/remotes/origin/{BRANCH}", "HEAD")

    def _ask(self, tree=None):
        return PROBES[PROBE_NAME](None, repo_root=tree or self.tree)

    # ── целый контур ────────────────────────────────────────────────────────────
    def test_the_whole_circuit_is_green(self):
        state, why = self._ask()
        self.assertEqual(state, SATISFIED, why)
        self.assertIn("НАЗЫВАЕТ разрыв", why)

    def test_the_verdict_carries_the_numbers_it_measured(self):
        """Вердикт обязан нести ЧИСЛА замера, а не слова: иначе он нечитаем как
        наблюдение."""
        _, why = self._ask()
        self.assertIn("потеря ПОЛНАЯ", why)
        self.assertRegex(why, r"работы без второй копии \d+")
        self.assertRegex(why, r"деревьев прочитано \d+ из \d+")

    # ── порванные звенья, каждое НАЗВАНО ───────────────────────────────────────
    def test_missing_measure_is_unmeasured(self):
        os.remove(os.path.join(self.tree, MEASURE_REL))
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("меры нет", why)

    def test_missing_reserve_is_unmeasured(self):
        os.remove(os.path.join(self.tree, RESERVE_REL))
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("связки нет", why)

    def test_unimportable_measure_is_unmeasured(self):
        with open(os.path.join(self.tree, MEASURE_REL), "w", encoding="utf-8") as fh:
            fh.write("это не питон(((\n")
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("не импортируется", why)

    def test_a_measure_without_its_door_is_unmeasured(self):
        with open(os.path.join(self.tree, MEASURE_REL), "w", encoding="utf-8") as fh:
            fh.write("НИЧЕГО = 1\n")
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("`measure`", why)

    def test_a_reserve_without_the_wiring_door_is_unmeasured(self):
        src = os.path.join(self.tree, RESERVE_REL)
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        body = body.replace("def uncovered_by_the_bundle(",
                            "def _снято_uncovered_by_the_bundle(")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(body)
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("uncovered_by_the_bundle", why)

    def test_a_measure_without_the_origin_prefix_door_is_named_not_a_crash(self):
        """Положительный контроль двери, добавленной циклом #1269.

        Сцена пробы берёт имя второго склада У МЕРЫ (`sc.ORIGIN_PREFIX`), и мера без
        этой двери обязана быть НАЗВАНА поимённо ДО зова. Без проверки исход остался бы
        тем же `unmeasured`, а ПРИЧИНА подменилась бы на «сцена не собралась:
        AttributeError» — дословно форма мутации M20: дверь обязана быть названа ДО
        зова, и слово «упала» в причине запрещено.

        Утверждение судит ПРИЧИНУ точно, а не подстрокой: имя двери обязано быть в
        тексте, а слова про падение сцены — нет."""
        with open(os.path.join(self.tree, MEASURE_REL), "w", encoding="utf-8") as fh:
            fh.write(
                "def reachable_objects(root, **kw):\n    return set()\n\n"
                "def measure(root, budget_s=None, **kw):\n"
                "    return {'verdict': 'empty', 'names': [], 'by_loss': {},\n"
                "            'by_kind': {}, 'trees_read': 1, 'trees_declared': 1,\n"
                "            'unmeasured': []}\n")
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("ORIGIN_PREFIX", why)
        self.assertNotIn("сцена не собралась", why,
                         "причина обязана НАЗЫВАТЬ дверь, а не докладывать о падении")

    def test_a_measure_that_loses_the_known_member_is_unmeasured(self):
        """Звено, несущее весь смысл: мера, не называющая форму аварии #1242
        (`git add` без коммита), обязана давать НЕ ИЗМЕРЕНО, а не «чисто»."""
        with open(os.path.join(self.tree, MEASURE_REL), "w", encoding="utf-8") as fh:
            fh.write(
                "ORIGIN_PREFIX = 'refs/remotes/origin/'\n"
                "def reachable_objects(root, **kw):\n    return set()\n\n"
                "def measure(root, budget_s=None, **kw):\n"
                "    return {'verdict': 'empty', 'names': [], 'by_loss': {},\n"
                "            'by_kind': {}, 'trees_read': 1, 'trees_declared': 1,\n"
                "            'unmeasured': []}\n")
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("ИЗВЕСТНЫЙ ЧЛЕН ПОТЕРЯН", why)

    def test_an_axis_on_object_existence_is_not_satisfied(self):
        """Мера, спрашивающая СУЩЕСТВОВАНИЕ объекта вместо достижимости, объявила бы
        работу #1242 сохранённой. Проба обязана это НАЗВАТЬ, а не промолчать."""
        src = os.path.join(self.tree, MEASURE_REL)
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        body += (
            "\n\ndef reachable_objects(root, git=None, **kw):\n"
            "    import subprocess\n"
            "    out = subprocess.run(['git', 'cat-file', '--batch-all-objects',\n"
            "                          '--batch-check=%(objectname)'], cwd=str(root),\n"
            "                         capture_output=True, text=True, timeout=120)\n"
            "    return {l.strip() for l in out.stdout.splitlines() if l.strip()}\n")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(body)
        state, why = self._ask()
        self.assertEqual(state, NOT_SATISFIED, why)
        self.assertIn("ось ВЫБРАНА НЕВЕРНО", why)

    def test_a_measure_that_names_committed_work_is_not_satisfied(self):
        """Обратное направление: мера, называющая членом и ЗАКОММИЧЕННУЮ работу,
        объявила бы предметом что угодно."""
        src = os.path.join(self.tree, MEASURE_REL)
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        body += (
            "\n\n_настоящая = measure\n\n"
            "def measure(root, budget_s=None, **kw):\n"
            "    doc = _настоящая(root, budget_s=budget_s, **kw)\n"
            "    if doc['verdict'] == 'empty':\n"
            "        doc['verdict'] = 'found'\n"
            "        doc['names'] = [{'path': 'выдумано'}]\n"
            "    return doc\n")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(body)
        state, why = self._ask()
        self.assertEqual(state, NOT_SATISFIED, why)
        self.assertIn("обратное направление НЕ СОШЛОСЬ", why)

    def test_a_silent_wiring_is_not_satisfied(self):
        """Связка, у которой проводка молчит (вопрос не задаётся вовсе), обязана
        краснить пробу: ровно это состояние и было до ADR-1123."""
        src = os.path.join(self.tree, RESERVE_REL)
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        body += ("\n\ndef uncovered_by_the_bundle(root, runner_file=None,\n"
                 "                            budget_s=None):\n"
                 "    return {'state': 'empty', 'trees_read': 0,\n"
                 "            'trees_declared': 0}\n")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(body)
        state, why = self._ask()
        self.assertEqual(state, NOT_SATISFIED, why)
        self.assertIn("разрыв НЕ НАЗЫВАЕТ", why)

    def test_a_wiring_without_the_third_outcome_is_not_satisfied(self):
        """«Вопрос не задан» обязан оставлять след. Проводка без третьего исхода —
        молчание под другим именем."""
        src = os.path.join(self.tree, RESERVE_REL)
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        body = body.replace(
            '''                      else {"state": UNMEASURED,
                            "why": "вопрос НЕ ЗАДАН (--skip-uncovered)"}),''',
            '''                      else {"state": EMPTY_CONTENT}),''')
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(body)
        state, why = self._ask()
        self.assertEqual(state, NOT_SATISFIED, why)
        self.assertIn("третий исход", why)

    def test_a_tree_without_git_is_unmeasured_not_clean(self):
        bare = os.path.join(self.tmp, "без_git")
        os.makedirs(os.path.join(bare, "spa_core", "monitoring"))
        os.makedirs(os.path.join(bare, "scripts"))
        for rel in (MEASURE_REL, RESERVE_REL):
            shutil.copy2(os.path.join(_REAL_ROOT, rel), os.path.join(bare, rel))
        state, why = self._ask(bare)
        self.assertEqual(state, UNMEASURED, why)

    # ── подстрокой не проходит (ADR-333) ───────────────────────────────────────
    def test_the_probe_does_not_pass_on_prose_alone(self):
        """Модуль, у которого ВСЁ нужное написано в докстринге и ничего не работает,
        обязан дать НЕ ИЗМЕРЕНО: проба меряет ИСХОД, а не текст."""
        with open(os.path.join(self.tree, MEASURE_REL), "w", encoding="utf-8") as fh:
            fh.write('"""Достижимость, hash-object без -w, измеренный ноль, '
                     'третий исход, by_loss whole delta, известный член #1242, '
                     'reachable_objects, measure, НАЗЫВАЕТ разрыв."""\n')
        state, why = self._ask()
        self.assertEqual(state, UNMEASURED, why)
        self.assertNotEqual(state, SATISFIED)

    def test_the_probe_refuses_an_argument(self):
        state, why = PROBES[PROBE_NAME]("какой-то-файл", repo_root=self.tree)
        self.assertEqual(state, UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)

    def test_the_probe_is_registered_under_its_name(self):
        self.assertIn(PROBE_NAME, PROBES)


if __name__ == "__main__":
    unittest.main()
