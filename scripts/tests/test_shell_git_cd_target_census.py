#!/usr/bin/env python3
"""Контроли прибора «КУДА ведёт доказанный `cd`» (ЗАКАЗ #578, ADR-356).

Каждый тест здесь — либо воспроизведение настоящей формы из набора, либо
контроль на конкретный способ соврать. Проверка, никогда не видевшая поломки,
— украшение (`.claude/rules/deployment.md`), поэтому положительный контроль
стои́т первым и он не фикстурный: это дословная идиома
`code_sync_from_origin.sh`, из-за которой заказ и написан.
"""
from __future__ import annotations

import io
import json
import shutil
import unittest
import subprocess
import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory

import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import shell_git_cd_target_census as M      # noqa: E402


def git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True)


def make_repo(root: Path, scripts: dict):
    """Одноразовое дерево-репозиторий с названными shell-скриптами."""
    root.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], root)
    for rel, body in scripts.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    return root


def verdicts(root: Path):
    """file:line → исход."""
    M._INVOCATIONS.clear()
    res = M.census(root)
    if "unmeasured_fatal" in res:
        return {"__fatal__": res["unmeasured_fatal"]}
    return {f"{r['file']}:{r['line']}": r["verdict"] for r in res["rows"]}


def run_cli(argv):
    """(код возврата, напечатанное)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = M.main(argv)
    return code, buf.getvalue()


CALL = 'git checkout origin/main -- spa_core scripts\n'


class ThreeOutcomes(unittest.TestCase):
    """Три исхода заказа, и третий не складывается в первый."""

    def setUp(self):
        self.td = TemporaryDirectory(prefix="cdt-")
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name) / "tree"

    # ── исход 3: НЕ ОПРЕДЕЛЕНО ────────────────────────────────────────────

    def test_default_value_is_not_a_known_directory(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — дословная форма `code_sync_from_origin.sh`.

        У переменной ЕСТЬ умолчание, и оно выглядит как прод-дерево. Прибор
        обязан ответить «НЕ ОПРЕДЕЛЕНО»: значение приходит от окружения.
        Соблазн прочитать умолчание и объявить корень — ровно тот дефект,
        ради которого написан заказ."""
        make_repo(self.root, {"scripts/sync_probe.sh":
                              '#!/bin/bash\n'
                              'REPO="${SPA_SYNC_REPO:-$HOME/Documents/SPA_Claude}"\n'
                              'cd "$REPO" || exit 1\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/sync_probe.sh:4"],
                         "undetermined")

    def test_home_derived_is_not_a_known_directory(self):
        """Форма `DEPLOY.sh`: `$HOME/...` — тоже окружение, а не файл."""
        make_repo(self.root, {"scripts/home_probe.sh":
                              '#!/bin/bash\nCD="$HOME/Documents/SPA_Claude"\n'
                              'cd "$CD"\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/home_probe.sh:4"],
                         "undetermined")

    def test_undetermined_is_named_by_file_and_line_and_exits_3(self):
        make_repo(self.root, {"scripts/home_probe.sh":
                              '#!/bin/bash\nCD="$HOME/x"\ncd "$CD"\n' + CALL})
        code, out = run_cli(["--root", str(self.root)])
        self.assertEqual(code, 3)
        self.assertIn("scripts/home_probe.sh:4", out)

    # ── исход 1: ДОКАЗАННЫЙ КОРЕНЬ ────────────────────────────────────────

    def test_script_location_derived_root_is_proven(self):
        """Форма `git_push.sh`: каталог идёт от места самого скрипта."""
        make_repo(self.root, {"scripts/own_probe.sh":
                              '#!/bin/bash\n'
                              'REPO="$(cd "$(dirname "$0")/.." && pwd)"\n'
                              'cd "$REPO"\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/own_probe.sh:4"],
                         "proven_root")

    def test_literal_equal_to_scanned_root_is_proven(self):
        make_repo(self.root, {"scripts/pin_probe.sh":
                              f'#!/bin/bash\ncd "{self.root}"\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/pin_probe.sh:3"],
                         "proven_root")

    # ── исход 2: ДОКАЗАННО ДРУГОЕ ─────────────────────────────────────────

    def test_following_the_copy_is_not_enough_it_must_be_the_ROOT(self):
        """КОНТРОЛЬ на проверку корня.

        `cd "$(dirname "$0")"` тоже идёт от места скрипта и тоже устойчив к
        окружению — но ведёт в ПОДКАТАЛОГ. Засчитать его корнем значило бы
        ответить верно по чужой причине на всех скриптах, лежащих в корне, и
        неверно на всех остальных."""
        make_repo(self.root, {"scripts/subdir_probe.sh":
                              '#!/bin/bash\n'
                              'D="$(cd "$(dirname "$0")" && pwd)"\ncd "$D"\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/subdir_probe.sh:4"],
                         "other_tree")

    def test_pinned_path_outside_the_scanned_tree_is_another_tree(self):
        """Форма `git_autopush.sh`: приколоченный абсолютный путь.

        Запущенный из копии репозитория, такой зов делает `reset --hard` НЕ в
        той копии, из которой запущен."""
        other = Path(self.td.name) / "elsewhere"
        make_repo(other, {})
        make_repo(self.root, {"scripts/pin_probe.sh":
                              f'#!/bin/bash\nR="{other}"\ncd "$R"\n' + CALL})
        self.assertEqual(verdicts(self.root)["scripts/pin_probe.sh:4"],
                         "other_tree")

    def test_the_same_call_flips_with_the_tree_you_measure_from(self):
        """Вердикт приколоченного зова есть свойство КОПИИ, и это сказано вслух.

        Тот же файл, тот же зов: из дерева A — «другое дерево», из дерева B,
        куда он приколочен, — «доказанный корень». Прибор обязан называть
        дерево, из которого мерил, а не выдавать один из двух ответов за
        безусловный."""
        treeB = Path(self.td.name) / "treeB"
        make_repo(treeB, {})
        body = (f'#!/bin/bash\nR="{treeB}"\ncd "$R"\n' + CALL)
        make_repo(self.root, {"scripts/pin_probe.sh": body})
        (treeB / "scripts").mkdir(parents=True, exist_ok=True)
        (treeB / "scripts/pin_probe.sh").write_text(body, encoding="utf-8")
        self.assertEqual(verdicts(self.root)["scripts/pin_probe.sh:4"],
                         "other_tree")
        self.assertEqual(verdicts(treeB)["scripts/pin_probe.sh:4"],
                         "proven_root")

    # ── обратный контроль: прибор различает СВОЙСТВО, а не наличие файла ──

    def test_same_call_two_verdicts_by_the_cd_alone(self):
        """Один и тот же зов git, два разных `cd` — два разных исхода.

        Без этого контроля «10 доказанных» держались бы на том, что в тех
        файлах вообще что-то написано, а не на том, куда ведёт `cd`."""
        make_repo(self.root, {
            "scripts/a_probe.sh": '#!/bin/bash\n'
                                  'R="$(cd "$(dirname "$0")/.." && pwd)"\n'
                                  'cd "$R"\n' + CALL,
            "scripts/b_probe.sh": '#!/bin/bash\nR="$HOME/x"\ncd "$R"\n' + CALL,
        })
        got = verdicts(self.root)
        self.assertEqual(got["scripts/a_probe.sh:4"], "proven_root")
        self.assertEqual(got["scripts/b_probe.sh:4"], "undetermined")


class ThirdOutcomeIsItsOwn(unittest.TestCase):
    """«Не измерено» — самостоятельный исход с ненулевым кодом (инвариант #17)."""

    def setUp(self):
        self.td = TemporaryDirectory(prefix="cdt-")
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name) / "tree"

    def test_root_that_is_not_a_worktree_is_unmeasured_not_clean(self):
        plain = Path(self.td.name) / "plain"
        plain.mkdir()
        code, out = run_cli(["--root", str(plain)])
        self.assertEqual(code, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", out)
        self.assertIn("корн", out)

    def test_foreign_substitution_is_refused_not_guessed(self):
        """Значение приходится ВЫЧИСЛЯТЬ, а вычисление `$(…)` есть запуск чужой
        команды. Прибор не запускает и не угадывает — он отказывает."""
        make_repo(self.root, {"scripts/wild_probe.sh":
                              '#!/bin/bash\nR="$(curl -s http://x/dir)"\n'
                              'cd "$R"\n' + CALL})
        code, out = run_cli(["--root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("curl", out)

    def test_cd_without_argument_is_unmeasured_with_a_reason(self):
        make_repo(self.root, {"scripts/bare_probe.sh":
                              '#!/bin/bash\ncd\n' + CALL})
        got = verdicts(self.root)
        self.assertEqual(got.get("scripts/bare_probe.sh:3"), "unmeasured")

    def test_unmeasured_never_passes_for_clean(self):
        """Смешанное дерево: один зов доказан, один не измерен. Код — 2."""
        make_repo(self.root, {
            "scripts/ok_probe.sh": '#!/bin/bash\n'
                                   'R="$(cd "$(dirname "$0")/.." && pwd)"\n'
                                   'cd "$R"\n' + CALL,
            "scripts/wild_probe.sh": '#!/bin/bash\nR="$(curl -s http://x)"\n'
                                     'cd "$R"\n' + CALL,
        })
        code, _out = run_cli(["--root", str(self.root)])
        self.assertEqual(code, 2)


class VerdictMustNotBeAPropertyOfTheHost(unittest.TestCase):
    """Личность ХОСТА не смеет решать вердикт (`.claude/rules/deployment.md`).

    Замер 2026-09-12: `env BASH_SOURCE=/hij bash script.sh` на bash 3.2.57
    (macOS, `/bin/bash` прод-хоста) ПЕРЕБИВАЕТ `${BASH_SOURCE[0]}`, а на
    bash 5.x (ubuntu, где идёт CI) — нет. Пусти это в главный вердикт — и один
    и тот же sha даст разные ответы на двух машинах.
    """

    def setUp(self):
        self.td = TemporaryDirectory(prefix="cdt-")
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name) / "tree"

    def test_bash_source_derived_root_is_proven_on_any_host(self):
        """Форма `secure_git_push.sh` — скрипт лежит В КОРНЕ дерева."""
        make_repo(self.root, {"root_probe.sh":
                              '#!/bin/bash\n'
                              'R="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                              'cd "$R"\n' + CALL})
        self.assertEqual(verdicts(self.root)["root_probe.sh:4"], "proven_root")

    def test_shell_set_names_are_excluded_from_the_environment_differential(self):
        self.assertIn("BASH_SOURCE", M.SHELL_SET_NAMES)
        self.assertNotIn("HOME", M.SHELL_SET_NAMES)
        _chain, ambient, shell_set = M.resolve_chain(
            '"$(dirname "${BASH_SOURCE[0]}")/$HOME"', {}, 10)
        self.assertEqual(ambient, {"HOME"})
        self.assertEqual(shell_set, {"BASH_SOURCE"})


class RatchetOnTheRealTree(unittest.TestCase):
    """Храповик: предмет может только уменьшаться."""

    BASELINE = REPO / "scripts" / "shell_git_cd_target_baseline.json"

    def test_baseline_is_well_formed(self):
        doc = json.loads(self.BASELINE.read_text(encoding="utf-8"))
        keys = doc["undetermined"]
        self.assertEqual(len(keys), len(set(keys)), "дубли в базе")
        for k in keys:
            path, _, line = k.rpartition(":")
            self.assertTrue(line.isdigit(), f"{k}: ключ не вида path:line")
            self.assertFalse(path.startswith("/"),
                             f"{k}: ключ обязан быть ОТНОСИТЕЛЬНЫМ — "
                             "абсолютный не совпадёт ни в одном другом дереве")

    def test_real_tree_subject_is_within_the_baseline(self):
        code, out = run_cli(["--root", str(REPO), "--baseline", str(self.BASELINE)])
        self.assertEqual(code, 0, out[-2000:])

    def test_the_ratchet_is_able_to_fail(self):
        """КОНТРОЛЬ НА СТОРОЖА. С пустой базой прогон по настоящему дереву
        обязан покраснеть ПОИМЁННО: иначе зелёный ответ выше не значит ничего."""
        with TemporaryDirectory(prefix="cdt-base-") as td:
            empty = Path(td) / "empty.json"
            empty.write_text(json.dumps({"undetermined": []}), encoding="utf-8")
            code, out = run_cli(["--root", str(REPO), "--baseline", str(empty)])
        self.assertEqual(code, 3)
        self.assertIn("code_sync_from_origin.sh", out)


class WiringAndOutput(unittest.TestCase):

    def test_json_mode_prints_json_and_nothing_else(self):
        """Потребитель храповика читает stdout. Человеческая строка, дописанная
        после JSON, ломает разбор — и ломала: первый прогон печатал вердикт
        следом за документом."""
        with TemporaryDirectory(prefix="cdt-") as td:
            root = Path(td) / "tree"
            make_repo(root, {"scripts/home_probe.sh":
                             '#!/bin/bash\nR="$HOME/x"\ncd "$R"\n' + CALL})
            code, out = run_cli(["--root", str(root), "--json"])
        self.assertEqual(code, 3)
        doc = json.loads(out)
        self.assertEqual(doc["by_verdict"]["undetermined"], 1)

    def test_instrument_is_wired_into_ci(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("shell_git_cd_target_census.py", ci)
        self.assertIn("shell_git_cd_target_baseline.json", ci,
                      "без базы прогон в CI красен по построению — и его "
                      "погасят, вместо того чтобы чинить скрипты")


if __name__ == "__main__":
    unittest.main()
