#!/usr/bin/env python3
"""Тесты `scripts/code_sync_from_origin.sh` — синхронизация прод-дерева с origin.

**Каждый тест здесь — авария 2026-09-04 (цикл #482), а не выдуманный случай.**
В тот день прод-дерево расходилось с `origin/main` ровно на 13 файлов, и все 13
были на origin УДАЛЕНЫ осознанно (`retire(2/2)`, `cleanup: удалён мёртвый
aggressive_lab`, `changelog: генератор в attic`). Поскольку `git checkout <ref> --
<путь>` удалять не умеет, дрейф не мог стать нулём никогда — каждые 10 минут
снимался пре-синк-архив всего кода: 1300 архивов, 70 ГБ в `/tmp` при 55 ГБ
свободных на диске. Тогда же в логе дважды (10:57:13Z, 11:07:16Z) стоит
`fatal: Unable to create '.git/index.lock'` от параллельных запусков, а
следующей строкой — `synced 15 file(s) + import probe OK`: код возврата чекаута
не проверялся, и недоставка объявлялась доставкой.

У скрипта до этого дня не было ни одного теста ПО ПОСТРОЕНИЮ: он ходил в одно
дерево на одном Маке. Тесты гоняют НАСТОЯЩИЙ скрипт на НАСТОЯЩЕМ временном
git-репозитории (`SPA_SYNC_REPO` и соседние знаки), а не подставленный вывод, —
вакуум цикла #474 держался ровно на подставленном входе.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "code_sync_from_origin.sh"


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


class _Fixture:
    """Пара репозиториев «origin ← прод-дерево» и запуск настоящего скрипта.

    `data/` в прод-дереве создаётся: артефакт `data/code_sync_status.json` пишет
    сам скрипт через `atomic_save`, и это и есть предмет проверки.
    """

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.repo = tmp / "prod"
        self.snaps = tmp / "snaps"
        self.snaps.mkdir()
        self.log = tmp / "sync.log"

        # Все CODE_PATHS создаются в семени намеренно: пре-синк-архив снимается
        # ОДНОЙ командой `tar` по всему списку, и отсутствующий путь роняет её
        # целиком (вердикт SNAPSHOT_FAILED). Дерево-фикстура обязано быть похоже
        # на прод в том, что скрипт трогает, иначе тест судит о своей же нехватке.
        seed = tmp / "seed"
        for d in ("spa_core", "scripts", "tests", "architecture", ".claude/rules"):
            (seed / d).mkdir(parents=True)
        (seed / "spa_core" / "live.py").write_text("VALUE = 1\n")
        (seed / "scripts" / "keep.sh").write_text("#!/bin/bash\ntrue\n")
        (seed / "tests" / "test_seed.py").write_text("def test_seed():\n    pass\n")
        (seed / "architecture" / "manifest.json").write_text("{}\n")
        (seed / ".claude" / "rules" / "kept.md").write_text("правило\n")
        (seed / "CLAUDE.md").write_text("инструкции\n")
        (seed / "push_to_github.py").write_text("MARK = 1\n")
        (seed / "push_to_github_batch.py").write_text("MARK = 1\n")
        _git(seed, "init", "-q", "-b", "main")
        _git(seed, "config", "user.email", "t@t")
        _git(seed, "config", "user.name", "t")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "seed")
        _git(seed, "clone", "-q", "--bare", str(seed), str(self.origin))

        _git(tmp, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "data").mkdir(exist_ok=True)

    def origin_commit(self, mutate) -> None:
        """Двинуть origin: `mutate(work)` правит рабочую копию, коммит уезжает."""
        work = self.tmp / "work"
        if work.exists():
            shutil.rmtree(work)
        _git(self.tmp, "clone", "-q", str(self.origin), str(work))
        _git(work, "config", "user.email", "t@t")
        _git(work, "config", "user.name", "t")
        mutate(work)
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", "origin move")
        _git(work, "push", "-q", "origin", "main")

    def run(self, extra_env: dict | None = None, path_shim: Path | None = None):
        env = dict(os.environ)
        env.update({
            "SPA_SYNC_REPO": str(self.repo),
            "SPA_SYNC_PYTHON": sys.executable,
            "SPA_SYNC_LOG": str(self.log),
            "SPA_SYNC_SNAP_DIR": str(self.snaps),
            # Проба импорта и `atomic_save` должны видеть НАСТОЯЩИЙ пакет: cwd у
            # скрипта — временное дерево, где spa_core свой и пустой.
            "PYTHONPATH": str(_REPO_ROOT),
        })
        if path_shim is not None:
            env["PATH"] = f"{path_shim}{os.pathsep}{env['PATH']}"
        env.update(extra_env or {})
        return subprocess.run(["bash", str(_SCRIPT)], capture_output=True,
                              text=True, env=env)

    def status(self) -> dict:
        return json.loads((self.repo / "data" / "code_sync_status.json").read_text())

    def snapshots(self) -> list[Path]:
        return sorted(self.snaps.glob("spa_code_presync_*.tgz"))


class CodeSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = _Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    # ── авария дня: файл СНЯТ на origin ───────────────────────────────────────
    def test_file_retired_on_origin_is_not_drift(self):
        """13 файлов, снятых на origin, объявлялись дрейфом — вечно."""
        self.fx.origin_commit(lambda w: (w / "spa_core" / "live.py").unlink())
        r = self.fx.run()
        st = self.fx.status()
        self.assertEqual(st["result"], "IN_SYNC", r.stdout + r.stderr)
        self.assertEqual(st["files_changed"], 0)
        self.assertEqual(st["retired_code"], ["spa_core/live.py"])

    def test_retired_code_takes_no_snapshot(self):
        """Из вечного дрейфа рождались 1300 архивов на 70 ГБ."""
        self.fx.origin_commit(lambda w: (w / "spa_core" / "live.py").unlink())
        self.fx.run()
        self.assertEqual(self.fx.snapshots(), [])

    def test_retired_code_is_named_but_never_deleted(self):
        """Уборка прод-дерева — действие владельца (правило доставки, §6)."""
        self.fx.origin_commit(lambda w: (w / "spa_core" / "live.py").unlink())
        self.fx.run()
        self.assertTrue((self.fx.repo / "spa_core" / "live.py").exists())

    def test_retired_instructions_are_not_double_counted_as_retired_code(self):
        """Один файл, названный дважды, читается как две находки."""
        (self.fx.repo / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
        (self.fx.repo / ".claude" / "rules" / "gone.md").write_text("правило\n")
        _git(self.fx.repo, "add", "-A")
        _git(self.fx.repo, "commit", "-qm", "local rule")
        r = self.fx.run()
        st = self.fx.status()
        self.assertIn(".claude/rules/gone.md", st["retired_instructions"], r.stdout)
        self.assertNotIn(".claude/rules/gone.md", st["retired_code"])

    # ── обратная сторона: настоящий дрейф обязан синкаться ────────────────────
    def test_real_drift_is_still_synced(self):
        self.fx.origin_commit(
            lambda w: (w / "spa_core" / "live.py").write_text("VALUE = 2\n"))
        r = self.fx.run()
        st = self.fx.status()
        self.assertEqual(st["result"], "SYNCED", r.stdout + r.stderr)
        self.assertEqual(st["files_changed"], 1)
        self.assertEqual((self.fx.repo / "spa_core" / "live.py").read_text(),
                         "VALUE = 2\n")
        self.assertEqual(len(self.fx.snapshots()), 1)

    def test_clean_tree_reports_in_sync_and_empty_retired_code(self):
        """«Измерено и пусто» обязано отличаться от «не измерено» (None)."""
        r = self.fx.run()
        st = self.fx.status()
        self.assertEqual(st["result"], "IN_SYNC", r.stdout + r.stderr)
        self.assertEqual(st["retired_code"], [])
        self.assertIsNotNone(st["retired_instructions"])

    # ── авария дня: чекаут не доставил ничего, а вердикт был SYNCED ───────────
    def _git_shim(self, body: str) -> Path:
        """Подмена ДВЕРИ к git, а не выхода функции: скрипт зовёт `git` из PATH."""
        shim_dir = self.fx.tmp / "shim"
        shim_dir.mkdir(exist_ok=True)
        real = shutil.which("git")
        (shim_dir / "git").write_text(
            textwrap.dedent(f"""\
                #!/bin/bash
                REAL={real}
                {body}
                exec "$REAL" "$@"
                """))
        (shim_dir / "git").chmod(0o755)
        return shim_dir

    def test_failed_checkout_is_never_reported_as_synced(self):
        """04.09 10:57:13Z: index.lock, чекаут упал, в артефакт ушло SYNCED."""
        self.fx.origin_commit(
            lambda w: (w / "spa_core" / "live.py").write_text("VALUE = 3\n"))
        shim = self._git_shim('if [ "$1" = "checkout" ]; then exit 1; fi')
        r = self.fx.run(path_shim=shim)
        st = self.fx.status()
        self.assertEqual(st["result"], "CHECKOUT_FAILED", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.fx.repo / "spa_core" / "live.py").read_text(),
                         "VALUE = 1\n")

    def test_checkout_that_delivers_nothing_is_not_reported_as_synced(self):
        """Нулевой код возврата — намерение; вердикт обязан быть перемером.

        Тише упавшего чекаута и потому опаснее: команда молчит, проба импорта
        радуется СТАРОМУ дереву (оно импортировалось и до синка), и «доставлено»
        пишется о недоставленном.
        """
        self.fx.origin_commit(
            lambda w: (w / "spa_core" / "live.py").write_text("VALUE = 4\n"))
        shim = self._git_shim('if [ "$1" = "checkout" ]; then exit 0; fi')
        r = self.fx.run(path_shim=shim)
        st = self.fx.status()
        self.assertEqual(st["result"], "NOT_CONVERGED", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 1)

    # ── ретенция архивов ──────────────────────────────────────────────────────
    def test_stale_snapshots_are_pruned_to_the_newest_n(self):
        for i in range(25):
            (self.fx.snaps / f"spa_code_presync_20260901T{i:04d}00Z.tgz").write_bytes(b"x")
        self.fx.run(extra_env={"SPA_SYNC_SNAP_KEEP": "10"})
        self.assertEqual(len(self.fx.snapshots()), 10)

    def test_pruning_happens_even_when_the_tree_is_already_in_sync(self):
        """Починка дрейфа закрыла бы единственную дорогу к уборке."""
        for i in range(12):
            (self.fx.snaps / f"spa_code_presync_20260902T{i:04d}00Z.tgz").write_bytes(b"x")
        r = self.fx.run(extra_env={"SPA_SYNC_SNAP_KEEP": "3"})
        self.assertEqual(self.fx.status()["result"], "IN_SYNC", r.stdout)
        self.assertEqual(len(self.fx.snapshots()), 3)

    # ── недоступный origin: «не измерено» ≠ «пусто» ───────────────────────────
    def test_fetch_failure_leaves_retired_lists_unmeasured(self):
        shim = self._git_shim('if [ "$1" = "fetch" ]; then exit 1; fi')
        r = self.fx.run(path_shim=shim)
        st = self.fx.status()
        self.assertEqual(st["result"], "FETCH_FAILED", r.stdout + r.stderr)
        self.assertIsNone(st["retired_code"])
        self.assertIsNone(st["retired_instructions"])

    # ── режим файла: расхождение, которое скрипт создаёт САМ ──────────────────
    def test_exec_bit_the_sync_sets_itself_is_not_eternal_drift(self):
        """На origin 73 из 181 `scripts/*.sh` лежат как 100644, а скрипт ставит +x.

        На хосте, где git различает режимы, такой файл расходился бы с origin
        после КАЖДОГО синка — второй вечный, несводимый дрейф того же класса.
        """
        _git(self.fx.repo, "config", "core.fileMode", "true")
        self.fx.origin_commit(
            lambda w: (w / "scripts" / "keep.sh").write_text("#!/bin/bash\nfalse\n"))
        r = self.fx.run()
        st = self.fx.status()
        self.assertEqual(st["result"], "SYNCED", r.stdout + r.stderr)
        self.assertTrue(os.access(self.fx.repo / "scripts" / "keep.sh", os.X_OK))
        # Второй прогон на том же дереве обязан быть чистым, а не «снова дрейф».
        self.fx.run()
        self.assertEqual(self.fx.status()["result"], "IN_SYNC")


if __name__ == "__main__":
    unittest.main()
