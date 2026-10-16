"""Побудка приёма заданий НЕ ТЕРЯЕТСЯ: `scripts/agent_inbox_intake.sh` коалесцирует, а не сбрасывает.

Положительные контроли (ARB 16.10). На `origin/main` 3584de55f красны все, кроме контрольного
`test_a_quiet_run_runs_once`:

  * побудка во время прогона (`inbox/.cockpit-wake` новее начала) ⇒ ещё проход (было: потеряна);
  * событие в окне дребезга ⇒ ждём остаток окна и прогоняем (было: «debounce — skip»);
  * событие при занятом замке ⇒ PENDING, держатель повторяет (было: «busy — skip», потеряно);
  * ЖИВОЙ держатель старше 300 с замок не теряет (было: замок снимался по возрасту — замер 16.10:
    прогон длится 15–17 мин, т. е. второй приём шёл ПАРАЛЛЕЛЬНО первому);
  * мёртвый держатель (процесс убит посреди прогона) ⇒ замок снимается сразу (было: ждали 300 с,
    событие внутри окна терялось).

Сцена: копия обёртки с путями в песочницу, вместо интерпретатора — заглушка, которая только
считает вызовы приёма. Живые /tmp-пути агента и прод-дерево не трогаются.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "agent_inbox_intake.sh"

_FAKE_PY = r'''#!/bin/bash
# Заглушка интерпретатора: считает ТОЛЬКО вызовы приёма (`-c … run_note_intake …`).
if [ "$1" = "-c" ]; then
    echo "call $(date +%s)" >> "{calls}"
    n=$(wc -l < "{calls}" | tr -d ' ')
    if [ -n "${{FAKE_TOUCH_WAKE:-}}" ] && {{ [ "$FAKE_TOUCH_WAKE" = "always" ] || [ "$n" = "1" ]; }}; then
        sleep 1; touch "{wake}"
    fi
    sleep "${{FAKE_SLEEP:-0}}"
    echo '{{"processed": [], "urgent": false}}'
fi
exit 0
'''


class Scene:
    def __init__(self, tmp: Path, debounce: int = 60):
        self.tmp = tmp
        self.repo = tmp / "repo"
        (self.repo / "inbox").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        self.calls = tmp / "calls.txt"
        self.wake = self.repo / "inbox" / ".cockpit-wake"
        self.log = tmp / "intake.log"
        self.lock = tmp / "intake.lock.d"
        self.ts = tmp / "intake.ts"
        self.pending = tmp / "intake.pending"
        fake = tmp / "fake_py.sh"
        fake.write_text(_FAKE_PY.format(calls=self.calls, wake=self.wake))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        src = _SCRIPT.read_text()
        for var, val in (("REPO", self.repo), ("PY", fake), ("LOG", self.log), ("LOCKDIR", self.lock),
                         ("TS", self.ts), ("DEBOUNCE", debounce), ("SETTLE", 0), ("PENDING", self.pending)):
            src, n = re.subn(rf'^{var}=.*$', f'{var}="{val}"', src, count=1, flags=re.M)
            if var != "PENDING":                       # PENDING есть только в новой редакции
                assert n == 1, f"в обёртке нет строки {var}= — сцена не управляет путём"
        self.script = tmp / "intake.sh"
        self.script.write_text(src)

    def env(self, **kw):
        e = dict(os.environ)
        e.update({k: str(v) for k, v in kw.items()})
        return e

    def run(self, **kw):
        return subprocess.run(["/bin/bash", str(self.script)], env=self.env(**kw),
                              capture_output=True, text=True, timeout=120)

    def start(self, **kw):
        return subprocess.Popen(["/bin/bash", str(self.script)], env=self.env(**kw),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def n_calls(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def logtext(self):
        return self.log.read_text() if self.log.exists() else ""


def _dead_pid() -> int:
    """Номер ЗАВЕДОМО мёртвого процесса, измеренный у той же двери (`kill -0`), что спросит обёртка."""
    p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    p.wait()
    try:
        os.kill(p.pid, 0)
    except ProcessLookupError:
        return p.pid
    pytest.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: номер {p.pid} уже занят живым процессом")


def test_a_quiet_run_runs_once(tmp_path):
    s = Scene(tmp_path)
    s.run()
    assert s.n_calls() == 1 and not s.lock.exists()


def test_wake_arriving_during_the_run_is_coalesced_not_dropped(tmp_path):
    s = Scene(tmp_path)
    s.run(FAKE_TOUCH_WAKE="first")
    assert s.n_calls() == 2, s.logtext()
    assert "coalesce" in s.logtext()


def test_coalescing_is_bounded(tmp_path):
    s = Scene(tmp_path)
    s.run(FAKE_TOUCH_WAKE="always")
    assert s.n_calls() == 5 and "предел" in s.logtext()


def test_event_inside_debounce_waits_instead_of_skipping(tmp_path):
    s = Scene(tmp_path, debounce=2)
    s.ts.write_text(str(int(time.time())))         # прошлый прогон начался только что
    s.run()
    assert s.n_calls() == 1, s.logtext()
    assert "skip" not in s.logtext()


def test_event_while_busy_is_kept_pending_and_rerun_by_the_holder(tmp_path):
    s = Scene(tmp_path)
    a = s.start(FAKE_SLEEP=3)
    deadline = time.time() + 30
    while not (s.lock / "pid").exists() and not s.calls.exists():
        assert time.time() < deadline, "держатель не взял замок"
        time.sleep(0.05)
    while not s.calls.exists():
        assert time.time() < deadline
        time.sleep(0.05)
    s.run()                                          # второе событие посреди прогона
    assert s.pending.exists() or s.n_calls() >= 1
    a.wait(timeout=60)
    assert s.n_calls() == 2, s.logtext()
    assert not s.lock.exists()


def test_live_holder_older_than_300s_keeps_the_lock(tmp_path):
    s = Scene(tmp_path)
    s.lock.mkdir()
    (s.lock / "pid").write_text(str(os.getpid()))   # живой по построению
    old = time.time() - 400
    os.utime(s.lock, (old, old))
    s.run()
    assert s.n_calls() == 0, "живой замок снят по возрасту — второй приём пошёл параллельно"
    assert s.pending.exists() and s.lock.exists()


def test_dead_holder_lock_is_reclaimed_at_once(tmp_path):
    s = Scene(tmp_path)
    s.lock.mkdir()
    (s.lock / "pid").write_text(str(_dead_pid()))   # процесс убит посреди прогона
    s.run()
    assert s.n_calls() == 1, s.logtext()
    assert "reclaim" in s.logtext() and not s.lock.exists()
