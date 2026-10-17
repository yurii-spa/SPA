"""Дверь принадлежности процесса на Linux: `/proc` вместо BSD-флага `ps -E` (G03).

Замер CI run #6 (17.10): на `ubuntu-latest` procps отвечает на `ps -A -Ewww …`
«unsupported SysV option», и прибор владения ВСЕГДА отдавал третий исход — 125,
`OWNERSHIP_UNKNOWN`, запись без `identity`. Девятнадцать красных тестов в
`test_claude_run_timeout_ownership.py` / `test_safe_terminate_ownership.py`, а клин срока на
Linux был бы инертен (карточка `inbox-na-linux-prinadlezhnost-protsessa-vsegda`).

Linux-машины под рукой нет, поэтому поведение доказывается ПОДДЕЛЬНЫМ деревом `/proc`
во временном каталоге: корень procfs и такт часов ядра — входы модуля (`PROC_ROOT`,
`CLK_TCK`), а платформа — `sys.platform`. Каждая сцена — положительный контроль: на коде
до правки (`ps -E` без переключателя) Linux-сцены краснеют, потому что `_ps` спрашивает
настоящий `ps` хоста, а не поддельное дерево (и `PROC_ROOT` у модуля нет вовсе).

Четыре исхода, и они различимы: свой · чужой · процесса нет · НЕ ИЗМЕРЕНО (инв. #17).
Нечитаемое никогда не становится «свой» или «чужой» по умолчанию (инв. #2).
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "shadow"))

import claude_run_with_timeout as CRT       # noqa: E402
import safe_terminate as ST                # noqa: E402

TCK = 100
UPTIME = 10_000.0
RUN = "canary-linux-1-abc"
CHILD = 400          # «наш ребёнок» сцены; в поддельном дереве он вожак
MINE = 500           # отделившийся потомок с нашей меткой в ОКРУЖЕНИИ (ppid=1)
FOREIGN = 501        # посторонний с ЧУЖОЙ меткой
NOLABEL = 502        # посторонний без метки


def _stat_line(pid, comm, state, ppid, age_s):
    start_ticks = int((UPTIME - age_s) * TCK)
    # поля 3..22: state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt
    # utime stime cutime cstime priority nice num_threads itrealvalue starttime
    mid = [state, str(ppid)] + ["0"] * 17 + [str(start_ticks)]
    return f"{pid} ({comm}) " + " ".join(mid) + " 0 0 0\n"


def _proc(root: Path, pid, *, comm="python3", state="S", ppid=1, age_s=5.0,
          argv=("python3", "-m", "pytest"), env=None, cwd=None):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "stat").write_text(_stat_line(pid, comm, state, ppid, age_s))
    (d / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
    env = {"PATH": "/usr/bin", "HOME": "/home/runner"} if env is None else env
    (d / "environ").write_bytes(b"".join(f"{k}={v}".encode() + b"\0" for k, v in env.items()))
    if cwd is not None:
        os.symlink(cwd, d / "cwd")
    return d


@pytest.fixture
def linux(tmp_path, monkeypatch):
    """Поддельный Linux: корень procfs в tmp, такт ядра закреплён, настоящий `ps` запрещён."""
    root = tmp_path / "proc"
    root.mkdir()
    (root / "uptime").write_text(f"{UPTIME} 12345.00\n")
    (root / "self").mkdir()                       # нечисловые записи procfs пропускаются
    monkeypatch.setattr(sys, "platform", "linux")
    # raising=False: на коде до правки атрибутов нет, и контроль обязан краснеть ПОВЕДЕНИЕМ
    # (дверь ушла в `ps` и получила отказ procps), а не опечаткой в фикстуре.
    monkeypatch.setattr(CRT, "PROC_ROOT", str(root), raising=False)
    monkeypatch.setattr(CRT, "CLK_TCK", TCK, raising=False)

    class Procps:
        """Дословный ответ procps на раннере CI run #6 на любой вызов `ps`."""
        returncode, stdout, stderr = 1, "", "error: unsupported SysV option"

    def procps(cmd, **k):
        CALLS.append(cmd)
        return Procps()
    CALLS.clear()
    monkeypatch.setattr(CRT.subprocess, "run", procps)
    yield root
    assert CALLS == [], f"на Linux дверь обязана идти в /proc, а позван `ps`: {CALLS}"


CALLS: list = []


@pytest.fixture
def scene(linux):
    _proc(linux, 1, comm="systemd", argv=("/sbin/init",), age_s=9000)
    _proc(linux, CHILD, ppid=1, age_s=6, argv=("python3", "parent.py"),
          env={"PATH": "/usr/bin", CRT.RUN_ID_VAR: RUN})
    _proc(linux, MINE, ppid=1, age_s=5, env={"PATH": "/usr/bin", CRT.RUN_ID_VAR: RUN})
    _proc(linux, FOREIGN, ppid=1, age_s=5,
          env={"PATH": "/usr/bin", CRT.RUN_ID_VAR: "orchestrator-77777-cafe"})
    _proc(linux, NOLABEL, ppid=1, age_s=5)
    return linux


def _census(**kw):
    return CRT.census(CHILD, RUN, 60.0, self_pid=os.getpid(), self_sid=None,
                      instruments={"run_id": CRT._inst_run_id, "tree": CRT._inst_tree}, **kw)


# ── переключатель платформы ──────────────────────────────────────────────────

def test_linux_switch_reads_proc_not_ps(scene):
    out = CRT._ps(list(CRT.FORM_SNAPSHOT))
    pids = {int(line.split()[0]) for line in out.splitlines()}
    assert pids == {1, CHILD, MINE, FOREIGN, NOLABEL}


def test_darwin_switch_keeps_bsd_ps_E(monkeypatch, tmp_path):
    seen = []

    class R:
        returncode, stdout, stderr = 0, "  1 0 S 01:00 /sbin/launchd PATH=/usr/bin\n", ""

    def fake_run(cmd, **k):
        seen.append(cmd)
        return R()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(CRT, "PROC_ROOT", str(tmp_path / "нет-такого"), raising=False)
    monkeypatch.setattr(CRT.subprocess, "run", fake_run)
    snap = CRT.Snapshot.take()
    assert seen == [["ps", "-A", "-Ewww", "-o", "pid=,ppid=,state=,etime=,command="]]
    assert list(snap.rows) == [1]


# ── четыре исхода ────────────────────────────────────────────────────────────

def test_owned_detached_child_found_by_env_label(scene):
    pids = {o.pid for o in _census()}
    assert MINE in pids, "отделившийся потомок с нашей меткой в /proc/<pid>/environ не найден"
    snap = CRT.Snapshot.take()
    assert snap.env_readable == 5 and snap.env_blind == 0
    assert snap.rows[MINE][2] == pytest.approx(5.0, abs=1.0)        # возраст из stat+uptime


def test_not_owned_foreign_label_and_no_label(scene):
    pids = {o.pid for o in _census()}
    assert FOREIGN not in pids and NOLABEL not in pids and 1 not in pids


def test_process_gone_is_skipped_not_an_error(scene):
    # Процесс в листинге есть, а stat уже исчез (ушёл между листингом и чтением).
    (scene / str(NOLABEL) / "stat").unlink()
    snap = CRT.Snapshot.take()
    assert NOLABEL not in snap.rows and MINE in snap.rows
    # Вопрос «жив ли номер» — измеренное «нет», а не отказ.
    assert CRT._ps(["-o", "stat=", "-p", str(NOLABEL)]) == ""
    assert CRT._ps(["-o", "stat=", "-p", "99"]) == ""
    assert CRT._ps(["-o", "stat=", "-p", str(MINE)]) == "S\n"


def test_zombie_state_comes_from_proc_stat(linux):
    _proc(linux, 77, state="Z", argv=(), comm="python3")
    assert CRT._ps(["-o", "stat=", "-p", "77"]) == "Z\n"
    assert CRT.Snapshot.take().rows[77][1] == "Z"


def test_unreadable_stat_is_unmeasured_never_owned_or_not_owned(scene):
    # stat нечитаем (не «нет файла») ⇒ таблица НЕ ИЗМЕРЕНА целиком: строка, которую не
    # видно, могла быть нашим выжившим, и «своих не осталось» было бы ложным 124.
    target = scene / str(FOREIGN) / "stat"
    target.unlink()
    target.mkdir()                                 # чтение даст IsADirectoryError
    with pytest.raises(CRT.PsUnavailable):
        CRT.Snapshot.take()
    ev = ST.classify(MINE, child_pid=CHILD, run_id=RUN, run_age_s=60.0, self_pid=os.getpid(),
                     self_sid=-1, instruments={"run_id": CRT._inst_run_id})
    assert ev["state"] == ST.OWNERSHIP_UNKNOWN
    assert "identity" not in ev


def test_permission_denied_stat_is_unmeasured(scene):
    target = scene / str(FOREIGN) / "stat"
    target.chmod(0)
    if os.access(target, os.R_OK):
        pytest.fail("предпосылка НЕ ОБЕСПЕЧЕНА: chmod 000 не закрыл чтение (root?) — "
                    "сцена «нет права» не построена, мерить нечем")
    try:
        with pytest.raises(CRT.PsUnavailable):
            CRT.Snapshot.take()
    finally:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_unreadable_environ_is_a_blind_row_not_a_failed_table(scene):
    env = scene / str(NOLABEL) / "environ"
    env.chmod(0)
    if os.access(env, os.R_OK):
        pytest.fail("предпосылка НЕ ОБЕСПЕЧЕНА: chmod 000 не закрыл чтение (root?)")
    try:
        snap = CRT.Snapshot.take()
    finally:
        env.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert snap.env_blind == 1 and snap.env_readable == 4
    assert "=" not in snap.rows[NOLABEL][3]


def test_no_proc_root_is_unmeasured(linux, monkeypatch):
    monkeypatch.setattr(CRT, "PROC_ROOT", str(linux / "нет-такого"))
    with pytest.raises(CRT.PsUnavailable):
        CRT.Snapshot.take()
    with pytest.raises(CRT.PsUnavailable):
        CRT.argv_rows()


def test_no_uptime_is_unmeasured(scene):
    (scene / "uptime").unlink()
    with pytest.raises(CRT.PsUnavailable):
        CRT.Snapshot.take()


def test_empty_proc_is_unmeasured_not_clean(linux):
    with pytest.raises(CRT.PsUnavailable):
        CRT.Snapshot.take()


# ── форма строки: разбор общий с macOS ───────────────────────────────────────

def test_argv_is_a_prefix_of_the_env_row_so_origin_is_measurable(scene):
    _proc(scene, 600, ppid=1, age_s=5, argv=("bash", "wrap.sh", "--run-id",
                                              f"{CRT.RUN_ID_VAR}={RUN}"))
    snap = CRT.Snapshot.take()
    org = CRT.match_origin(snap, RUN)
    assert org[MINE][0] == CRT.MATCH_ENV
    assert org[600][0] == CRT.MATCH_CMDLINE


def test_newline_in_argument_does_not_split_the_table(linux):
    _proc(linux, 42, argv=("python3", "-c", "print(1)\n  4242 1 S 00:01 fake"))
    snap = CRT.Snapshot.take()
    assert list(snap.rows) == [42]


def test_kernel_thread_has_bracketed_comm(linux):
    _proc(linux, 2, comm="kthreadd", argv=(), env={}, age_s=9000)
    assert CRT.argv_rows()[2] == "[kthreadd]"


def test_etime_render_round_trips_through_the_shared_parser():
    for s in (0, 59, 61, 3599, 3600, 86399, 86400 * 3 + 3723):
        assert CRT._parse_etime(CRT._fmt_etime(s)) == s


def test_process_cwd_on_linux_reads_proc_link(scene, tmp_path):
    _proc(scene, 700, cwd=str(tmp_path))
    assert ST.process_cwd(700) == str(tmp_path)
    assert ST.process_cwd(701) is None             # процесса нет ⇒ не прочитан, не ""


def test_classify_owned_on_linux_carries_identity(scene):
    ev = ST.classify(MINE, child_pid=CHILD, run_id=RUN, run_age_s=60.0, self_pid=os.getpid(),
                     self_sid=-1, instruments={"run_id": CRT._inst_run_id})
    assert ev["state"] == ST.OWNED
    assert ev["identity"][0] == MINE and ev["identity"][1] == 1


def test_unknown_ps_form_on_linux_still_goes_to_real_ps(monkeypatch):
    """Форма, которой /proc не отвечает, уходит в procps с проверкой кода — не в тишину."""
    seen = []

    class R:
        returncode, stdout, stderr = 1, "", "error: unsupported SysV option"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(CRT.subprocess, "run", lambda cmd, **k: seen.append(cmd) or R())
    with pytest.raises(CRT.PsUnavailable):
        CRT._ps(["-A", "-o", "pid="])
    assert seen == [["ps", "-A", "-o", "pid="]]
