"""Гейт перед деплоем: тайм-аут снимает ВСЮ группу процессов команды, а не только её обёртку.

Замер 02.11: `run_with_timeout` убивал pid обёртки `agent_template.sh`; python-ребёнок агента оставался сиротой
(PPID 1) и 72 минуты держал ядро на 99 % после того, как гейт доложил «hang». Тест гоняет НАСТОЯЩУЮ функцию из
скрипта; обратный контроль — прежняя форма (kill только pid) внука оставляет живым."""
import os
import re
import signal
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_agent_before_deploy.sh"

OLD = '''run_with_timeout() {
    local secs="$1"; shift
    "$@" &
    local cmd_pid=$!
    (
        sleep "$secs"
        kill -0 "$cmd_pid" 2>/dev/null && kill -TERM "$cmd_pid" 2>/dev/null
        sleep 2
        kill -0 "$cmd_pid" 2>/dev/null && kill -KILL "$cmd_pid" 2>/dev/null
    ) &
    local wd_pid=$!
    wait "$cmd_pid" 2>/dev/null
    local rc=$?
    kill "$wd_pid" 2>/dev/null
    wait "$wd_pid" 2>/dev/null
    if [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then return 124; fi
    return "$rc"
}'''


def _real_function() -> str:
    m = re.search(r"^run_with_timeout\(\) \{\n.*?^\}\n", SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert m, "функция run_with_timeout не найдена в скрипте гейта"
    return m.group(0)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def _run(func: str, tmp_path: Path):
    gc = tmp_path / "grandchild.pid"
    # вывод внука уведён: иначе сирота держит трубу stdout, и `subprocess.run` ждёт его до своего тайм-аута
    child = f'bash -c \'sleep 60 >/dev/null 2>&1 & echo $! > "{gc}"; wait\''
    script = f'{func}\nrun_with_timeout 1 {child}\necho "rc=$?"\n'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
    deadline = time.time() + 5
    while not gc.exists() and time.time() < deadline:
        time.sleep(0.05)
    return out, int(gc.read_text().strip())


def test_timeout_kills_the_grandchild_too(tmp_path):
    out, pid = _run(_real_function(), tmp_path)
    try:
        assert "rc=124" in out, out
        time.sleep(0.3)
        assert not _alive(pid), "внук пережил тайм-аут гейта — сирота, как 02.11"
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_control_the_old_form_leaves_the_grandchild_alive(tmp_path):
    out, pid = _run(OLD, tmp_path)
    try:
        assert "rc=124" in out, out
        time.sleep(0.3)
        assert _alive(pid), "контроль: прежняя форма обязана оставлять внука — иначе тест выше ничего не мерит"
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_a_fast_command_keeps_its_exit_code():
    out = subprocess.run(["bash", "-c", f'{_real_function()}\nrun_with_timeout 5 bash -c "exit 3"\necho "rc=$?"\n'],
                         capture_output=True, text=True, timeout=30).stdout
    assert "rc=3" in out, out


def test_a_foreign_process_and_the_gate_itself_survive(tmp_path):
    """Сторож убивает ТОЛЬКО группу команды: посторонний процесс (запущен до гейта, своя группа) и сама оболочка
    гейта переживают тайм-аут; внук команды — нет."""
    foreign = subprocess.Popen(["sleep", "60"], start_new_session=True)
    gc = tmp_path / "gc.pid"
    script = (f'{_real_function()}\n'
              f'run_with_timeout 1 bash -c \'sleep 60 >/dev/null 2>&1 & echo $! > "{gc}"; wait\'\n'
              'echo "rc=$?"; echo "gate_alive=$$"\n')
    try:
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
        assert "rc=124" in out and "gate_alive=" in out                     # оболочка гейта дожила до конца
        time.sleep(0.3)
        assert _alive(foreign.pid), "посторонний процесс убит сторожем гейта"
        assert not _alive(int(gc.read_text().strip()))
    finally:
        foreign.kill()
        foreign.wait()


def test_kill_attempts_are_bounded_term_then_one_kill():
    """Повторы ограничены: процесс, игнорирующий TERM, снимается KILL ровно один раз; гейт не зацикливается."""
    script = (f'{_real_function()}\n'
              'start=$(date +%s)\n'
              'run_with_timeout 1 bash -c \'trap "" TERM; while :; do sleep 0.2; done\'\n'
              'rc=$?; echo "rc=$rc took=$(( $(date +%s) - start ))"\n')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
    rc = re.search(r"rc=(\d+) took=(\d+)", out)
    assert rc and rc.group(1) == "124", out
    assert int(rc.group(2)) <= 6, out                                       # 1 с срок + 2 с между TERM и KILL + запас
