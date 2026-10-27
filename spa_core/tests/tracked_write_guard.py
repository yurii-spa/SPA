"""Сторож: тест не имеет права менять git-tracked состояние (`data/`, фикстуры, база).

Карточка `agent-test-run-dirties-tracked-fixtures` (04.08). Замер 27.10 на чистом
`origin/main f4e21f1cb`: прогон `tests/` изменил 9 отслеживаемых файлов `data/`
(`adapter_status.json`, `gap_monitor.json`, `risk_alerts.json`, …), прогон одного
модуля `spa_core/tests` — `data/fixed_vs_floating_yield_decision_log.json`. В прод-дереве
это ЖИВОЕ состояние; в рабочем — «чистое дерево» перестаёт быть сигналом.

Как устроено. На старте сессии — `git ls-files` наблюдаемых каталогов и их `stat`
(mtime_ns, size). На границе каждого модуля (последний тест модуля, ПОСЛЕ его teardown,
то есть и после модульных фикстур) `stat` сверяется заново; изменившиеся файлы
приписываются этому модулю. Отчёт печатается в конце сессии.

Храповик: `tracked_write_baseline.json` — модули, писавшие на момент введения (замер).
Модуль ВНЕ базы или новый файл у модуля из базы ⇒ сессия падает (exitstatus 1) с
названными модулем и файлами. База может только уменьшаться; дописывать её, чтобы
погасить падение, запрещено (тот же порядок, что у остальных баз). Сторож НИЧЕГО не
восстанавливает: `git restore` спрятал бы дефект, а чужие правки стёр бы.

Ограничение, измеренное при введении: два прогона pytest в ОДНОМ дереве одновременно
делят его `data/`, и чужая запись приписывается модулю, на границе которого её заметили.
Прогоны в одном дереве — это уже нарушение гигиены; сторож не разводит их, а называет файл.

Три исхода (инв. #17): git недоступен / каталог не репозиторий ⇒ «НЕ ИЗМЕРЕНО» с
причиной в отчёте; это не «чисто» и не падение.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

WATCHED = ("data", "tests/fixtures", "spa_core/data", "spa_core/database")
BASELINE = Path(__file__).resolve().parent / "tracked_write_baseline.json"
PLUGIN_NAME = "spa_tracked_write_guard"


def _git_root(start: Path):
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git недоступен: {type(exc).__name__}"
    if out.returncode != 0:
        return None, "каталог не является git-репозиторием"
    return Path(out.stdout.strip()), None


def _tracked(root: Path):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *WATCHED],
                         capture_output=True, timeout=60)
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _stat(root: Path, files):
    snap = {}
    for rel in files:
        try:
            st = os.stat(root / rel)
            snap[rel] = (st.st_mtime_ns, st.st_size)
        except OSError:
            snap[rel] = None  # исчез — это тоже изменение
    return snap


def load_baseline(path: Path = BASELINE) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {m: set(fs) for m, fs in doc["modules"].items()}


def judge(findings: dict, baseline: dict) -> list:
    """Нарушения храповика: [(модуль, [новые файлы])] — модуль вне базы или файл сверх неё."""
    bad = []
    for mod, files in sorted(findings.items()):
        extra = sorted(set(files) - baseline.get(mod, set()))
        if extra:
            bad.append((mod, extra))
    return bad


class TrackedWriteGuard:
    def __init__(self, rootdir: Path):
        self.root, self.unmeasured = _git_root(rootdir)
        self.files = None
        self.findings: dict = {}
        if self.root is not None:
            self.files = _tracked(self.root)
            if self.files is None:
                self.unmeasured = "git ls-files не ответил"
        self.snap = _stat(self.root, self.files) if self.files is not None else None

    @pytest.hookimpl(hookwrapper=True, trylast=True)
    def pytest_runtest_teardown(self, item, nextitem):
        yield
        if self.snap is None:
            return
        if nextitem is not None and nextitem.path == item.path:
            return
        cur = _stat(self.root, self.files)
        changed = [f for f in self.files if cur.get(f) != self.snap.get(f)]
        if changed:
            mod = os.path.relpath(str(item.path), str(self.root))
            self.findings.setdefault(mod, set()).update(changed)
        self.snap = cur

    def violations(self) -> list:
        try:
            base = load_baseline()
        except (OSError, ValueError, KeyError) as exc:
            return [("<база>", [f"база не читается: {type(exc).__name__} — НЕ ИЗМЕРЕНО"])]
        return judge(self.findings, base)

    def pytest_terminal_summary(self, terminalreporter):
        if self.unmeasured:
            terminalreporter.write_sep("=", "tracked-write guard: НЕ ИЗМЕРЕНО")
            terminalreporter.write_line(self.unmeasured)
            return
        if not self.findings:
            return
        terminalreporter.write_sep("=", "tests changed git-tracked state")
        for mod, files in sorted(self.findings.items()):
            terminalreporter.write_line(f"{mod}: {', '.join(sorted(files))}")
        for mod, extra in self.violations():
            terminalreporter.write_line(f"НОВОЕ (вне базы): {mod}: {', '.join(extra)}")

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        if self.snap is not None and self.violations() and session.exitstatus == 0:
            session.exitstatus = 1


def install(config) -> None:
    """Зарегистрировать ОДИН экземпляр на сессию (обе корневые conftest зовут install)."""
    if config.pluginmanager.has_plugin(PLUGIN_NAME):
        return
    config.pluginmanager.register(TrackedWriteGuard(Path(str(config.rootpath))), PLUGIN_NAME)
