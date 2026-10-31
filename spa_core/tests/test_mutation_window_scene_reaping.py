"""CI-PROCESS-01 (ARB раунд 7): проба окна мутаций завершает ВСЕ процессы своей сцены до её уборки.

Диагностика 31.10 (5 прогонов): при выходе из `TemporaryDirectory` в сцене жил сиротский
`pytest t/test_x.py` (PPID 1) — ребёнок убитого прибора; ещё ≈6.3 с после начала уборки. Проба убивала
и ждала только родителя. Здесь проверяется ЖИЗНЕННЫЙ ЦИКЛ, а не причина прошлого ENOTEMPTY в CI
(она не доказана). Сигналы — только группе, созданной самой сценой; чужие процессы не трогаются.
"""
import os
import subprocess
import sys
import tempfile

import pytest

from spa_core.monitoring import card_acceptance as ca

_PROBE = "mutation_window_restore_refuses_a_live_owner"


def _group_members(pgid: int) -> list:
    # `-ww`: без терминала Linux-ps обрезает колонку command (CI 41198597497: «-m pytest t/t»), и
    # положительный контроль по имени ребёнка промахивался при живом ребёнке в группе.
    out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,pgid=,command="], capture_output=True,
                         text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[1] == str(pgid) and parts[0] != str(os.getpid()):
            rows.append(line.strip())
    return rows


@pytest.fixture
def watched(monkeypatch):
    """Снимки группы сцены: ДО сбора (положительный контроль) и в начале уборки каталога."""
    seen = {"before_reap": [], "at_cleanup": [], "pgids": []}
    real_reap = ca._reap_scene_group

    def reap(proc, **kw):
        if proc is not None:
            seen["pgids"].append(proc.pid)
            seen["before_reap"].append(_group_members(proc.pid))
        return real_reap(proc, **kw)
    monkeypatch.setattr(ca, "_reap_scene_group", reap)

    real_td = tempfile.TemporaryDirectory

    class Watched(real_td):
        def cleanup(self):
            for pgid in seen["pgids"]:
                seen["at_cleanup"].append(_group_members(pgid))
            return super().cleanup()
    monkeypatch.setattr(tempfile, "TemporaryDirectory", Watched)
    return seen


def _assert_no_leftovers(seen):
    assert seen["pgids"], "сбор группы сцены не вызывался"
    assert any("test_x.py" in row for snap in seen["before_reap"] for row in snap), (
        f"положительный контроль: ребёнок прибора не был виден в группе сцены: {seen['before_reap']}")
    assert all(m == [] for m in seen["at_cleanup"]), f"в сцене живы процессы при уборке: {seen['at_cleanup']}"


@pytest.mark.timeout(900)
def test_success_path_leaves_no_scene_process_at_cleanup(watched):
    verdict, why = ca.PROBES[_PROBE](None, repo_root=ca.REPO_ROOT)
    assert verdict == ca.SATISFIED, why                                 # исходный смысл пробы цел
    _assert_no_leftovers(watched)


def _fail_restore(monkeypatch, exc):
    real_run = subprocess.run

    def run(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and "--window-restore" in cmd:
            raise exc
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.timeout(900)
def test_exception_path_leaves_no_scene_process_at_cleanup(watched, monkeypatch):
    _fail_restore(monkeypatch, RuntimeError("отказ двери возврата"))
    verdict, why = ca.PROBES[_PROBE](None, repo_root=ca.REPO_ROOT)
    assert verdict == ca.UNMEASURED and "отказ двери возврата" in why, why
    _assert_no_leftovers(watched)


@pytest.mark.timeout(900)
def test_timeout_path_leaves_no_scene_process_at_cleanup(watched, monkeypatch):
    _fail_restore(monkeypatch, subprocess.TimeoutExpired(cmd="--window-restore", timeout=1))
    verdict, why = ca.PROBES[_PROBE](None, repo_root=ca.REPO_ROOT)
    assert verdict == ca.UNMEASURED and "не ответила" in why, why
    _assert_no_leftovers(watched)


def test_reaper_kills_the_child_that_outlives_its_parent(tmp_path):
    """Синтетическая сцена: родитель с ребёнком в СОБСТВЕННОЙ группе. Положительный контроль — ребёнок
    жив до сбора; после сбора группа пуста. Контроль мутации «завершить только родителя» — ребёнок жив."""
    child_pid_file = tmp_path / "child.pid"
    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            f"open({str(child_pid_file)!r},'w').write(str(c.pid));time.sleep(60)")

    def scene():
        p = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
        for _ in range(500):
            if child_pid_file.exists() and child_pid_file.read_text().strip():
                break
            __import__("time").sleep(0.01)
        return p, int(child_pid_file.read_text())

    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        out = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout
        return bool(out.strip()) and not out.strip().startswith("Z")

    p, child = scene()
    assert alive(child)                                                   # ребёнок действительно запущен
    assert ca._reap_scene_group(p) == []
    assert not alive(child) and _group_members(p.pid) == []

    child_pid_file.unlink()
    p2, child2 = scene()
    p2.kill(); p2.wait()                                                  # мутация: убит только родитель
    try:
        assert alive(child2), "контроль пуст: ребёнок умер сам вместе с родителем"
    finally:
        ca._reap_scene_group(p2)                                          # своя группа — убрать за собой
    assert not alive(child2)
