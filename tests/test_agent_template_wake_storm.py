"""Wake-storm resilience of scripts/agent_template.sh (incident 2026-08-04T07:00Z).

Real failure replayed here: after the Mac woke from sleep, access to the repo
root under ~/Documents transiently failed (EINTR): launchd .err logs showed
    shell-init: error retrieving current directory: getcwd: ... Interrupted system call
    /bin/bash: .../agent_<name>.sh: Interrupted system call
and ~40 agent logs showed
    python3: Error while finding module specification for '...'
    (ModuleNotFoundError: No module named 'spa_core')
with 39 agents stamping EXIT code=1 at 2026-08-04T07:00:14-15Z simultaneously.

The fix: agent_template.sh verifies the environment is actually usable
(cd by absolute path + getcwd + spa_core READABLE + python executable) and
retries ONLY that pre-python section; on give-up it exits 75 (EX_TEMPFAIL)
with an explicit WAKE_STORM_GIVEUP marker. Python is launched exactly once —
genuine module errors are never masked by a retry.

Positive controls: every test here replays a facet of the real incident.
Run against the PRE-FIX template (git show <old>:scripts/agent_template.sh)
these tests fail: old wrapper exits 78 immediately with no marker and no
recovery (verified during development — see the journal entry for this fix).
"""

import os
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "scripts" / "agent_template.sh"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_fake_root(root: Path, stub_marker: Path, stub_exit: int = 0) -> Path:
    """Build a minimal fake repo root + stub 'python3'.

    The stub appends its argv to *stub_marker* (one line per launch) and exits
    with *stub_exit* — so tests can count HOW MANY times python was launched.
    Returns the stub python path.
    """
    (root / "spa_core").mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("# fake spa_core\n")
    stub = root / "python3"
    stub.write_text(
        "#!/bin/bash\n"
        f'echo "PY_LAUNCH $@" >> "{stub_marker}"\n'
        f"exit {stub_exit}\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _clean_env(**overrides) -> dict:
    """Environment for the wrapper: inherit, but strip template header vars so
    mode B (CLI args) is exercised deterministically."""
    env = dict(os.environ)
    for k in ("AGENT_NAME", "MODULE", "RUN_SCRIPT", "MODULE_ARGS",
              "SPA_AGENT_REPO_ROOT", "SPA_AGENT_PYTHON",
              "WAKE_RETRY_MAX", "WAKE_RETRY_SLEEP"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in overrides.items()})
    return env


def _run_template(agent_name: str, env: dict, timeout: int = 60):
    return subprocess.run(
        ["/bin/bash", str(TEMPLATE), agent_name, "spa_core.fake.module"],
        env=env, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture
def agent_name():
    """Unique agent name per test; removes the /tmp/spa_<name>.log afterwards."""
    name = f"waketest_{uuid.uuid4().hex[:10]}"
    yield name
    log = Path(f"/tmp/spa_{name}.log")
    if log.exists():
        log.unlink()


def _log_text(agent_name: str) -> str:
    log = Path(f"/tmp/spa_{agent_name}.log")
    return log.read_text() if log.exists() else ""


# ---------------------------------------------------------------------------
# 1. Give-up path: repo root unreachable for the whole retry window
#    (replays: wake storm where ~/Documents never came back in time)
# ---------------------------------------------------------------------------


def test_giveup_exits_75_with_explicit_marker(tmp_path, agent_name):
    missing_root = tmp_path / "never_exists"
    env = _clean_env(
        SPA_AGENT_REPO_ROOT=missing_root,
        SPA_AGENT_PYTHON="/bin/true",  # irrelevant — probe fails before it
        WAKE_RETRY_SLEEP=0,
        WAKE_RETRY_MAX=3,
    )
    proc = _run_template(agent_name, env)

    # Old wrapper: exit 78 immediately, no marker. New: 75 + WAKE_STORM_GIVEUP.
    assert proc.returncode == 75, (proc.returncode, proc.stdout, proc.stderr)
    log = _log_text(agent_name)
    assert "WAKE_STORM_GIVEUP" in log
    assert f"agent={agent_name}" in log
    assert "last_fail=cd:" in log  # names the failing probe step
    # Python must NEVER have been launched on the give-up path.
    assert "PY_LAUNCH" not in log
    assert "START agent=" not in log


def test_giveup_names_unreadable_package_not_just_cd(tmp_path, agent_name):
    """Root exists but spa_core is not READABLE — the exact shape of the
    ModuleNotFoundError storm (tree present, reads fail). Probe must catch it
    BEFORE python, so no bogus code=1 'logic failure' is recorded."""
    root = tmp_path / "root"
    stub_marker = tmp_path / "launches.txt"
    _make_fake_root(root, stub_marker)
    os.chmod(root / "spa_core" / "__init__.py", 0o000)
    try:
        env = _clean_env(
            SPA_AGENT_REPO_ROOT=root,
            SPA_AGENT_PYTHON=root / "python3",
            WAKE_RETRY_SLEEP=0,
            WAKE_RETRY_MAX=3,
        )
        proc = _run_template(agent_name, env)
        assert proc.returncode == 75
        log = _log_text(agent_name)
        assert "WAKE_STORM_GIVEUP" in log
        assert "last_fail=read:spa_core/__init__.py" in log
        assert not stub_marker.exists()  # python never ran
    finally:
        os.chmod(root / "spa_core" / "__init__.py", 0o644)


# ---------------------------------------------------------------------------
# 2. Recovery path: environment becomes usable mid-retry
#    (replays: FS comes back a few seconds after wake — the common case)
# ---------------------------------------------------------------------------


def test_recovers_when_root_appears_mid_retry(tmp_path, agent_name):
    root = tmp_path / "late_root"
    stub_marker = tmp_path / "launches.txt"

    def create_late():
        time.sleep(1.5)
        _make_fake_root(root, stub_marker, stub_exit=0)

    t = threading.Thread(target=create_late)
    t.start()
    try:
        env = _clean_env(
            SPA_AGENT_REPO_ROOT=root,
            SPA_AGENT_PYTHON=root / "python3",
            WAKE_RETRY_SLEEP=1,
            WAKE_RETRY_MAX=10,
        )
        proc = _run_template(agent_name, env)
    finally:
        t.join()

    # Old wrapper: instant exit 78, python never runs. New: retries, then OK.
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    log = _log_text(agent_name)
    assert "wake-storm retry" in log          # it did wait, visibly
    assert "WAKE_STORM_GIVEUP" not in log
    assert "EXIT agent=" in log and "code=0" in log
    assert stub_marker.read_text().count("PY_LAUNCH") == 1


# ---------------------------------------------------------------------------
# 3. Honesty: python runs exactly ONCE; real failures are not masked
# ---------------------------------------------------------------------------


def test_real_python_failure_not_retried_or_masked(tmp_path, agent_name):
    root = tmp_path / "root"
    stub_marker = tmp_path / "launches.txt"
    _make_fake_root(root, stub_marker, stub_exit=1)
    env = _clean_env(
        SPA_AGENT_REPO_ROOT=root,
        SPA_AGENT_PYTHON=root / "python3",
        WAKE_RETRY_SLEEP=0,
    )
    proc = _run_template(agent_name, env)

    assert proc.returncode == 1  # propagated verbatim, NOT converted to 75
    assert stub_marker.read_text().count("PY_LAUNCH") == 1  # exactly one launch
    log = _log_text(agent_name)
    assert "WAKE_STORM_GIVEUP" not in log
    assert "code=1" in log


def test_healthy_start_has_zero_retry_noise(tmp_path, agent_name):
    root = tmp_path / "root"
    stub_marker = tmp_path / "launches.txt"
    _make_fake_root(root, stub_marker, stub_exit=0)
    env = _clean_env(
        SPA_AGENT_REPO_ROOT=root,
        SPA_AGENT_PYTHON=root / "python3",
    )
    proc = _run_template(agent_name, env)
    assert proc.returncode == 0
    log = _log_text(agent_name)
    assert "wake-storm retry" not in log
    assert "WAKE_STORM_GIVEUP" not in log
    assert "code=0" in log


# ---------------------------------------------------------------------------
# 4. getcwd class: wrapper launched with a DELETED cwd (shell-init failure)
# ---------------------------------------------------------------------------


def test_survives_deleted_inherited_cwd(tmp_path, agent_name):
    """Replays 'shell-init: error retrieving current directory: getcwd'.
    The wrapper is exec'd from a directory that no longer exists — it must
    still cd by absolute path and run python normally."""
    root = tmp_path / "root"
    stub_marker = tmp_path / "launches.txt"
    _make_fake_root(root, stub_marker, stub_exit=0)
    doomed = tmp_path / "doomed_cwd"
    doomed.mkdir()

    script = (
        f'cd "{doomed}" && rmdir "{doomed}" && '
        f'exec /bin/bash "{TEMPLATE}" {agent_name} spa_core.fake.module'
    )
    env = _clean_env(
        SPA_AGENT_REPO_ROOT=root,
        SPA_AGENT_PYTHON=root / "python3",
        WAKE_RETRY_SLEEP=0,
    )
    proc = subprocess.run(["/bin/bash", "-c", script], env=env,
                          capture_output=True, text=True, timeout=60)

    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert stub_marker.read_text().count("PY_LAUNCH") == 1
    assert "code=0" in _log_text(agent_name)


# ---------------------------------------------------------------------------
# 5. Budget: defaults must keep the wrapper well under launchd cadence
# ---------------------------------------------------------------------------


def test_default_retry_budget_at_most_30s():
    text = TEMPLATE.read_text()
    import re

    m_max = re.search(r'WAKE_RETRY_MAX="\$\{WAKE_RETRY_MAX:-(\d+)\}"', text)
    m_sleep = re.search(r'WAKE_RETRY_SLEEP="\$\{WAKE_RETRY_SLEEP:-(\d+)\}"', text)
    assert m_max and m_sleep, "retry knobs missing from agent_template.sh"
    total_sleep = (int(m_max.group(1)) - 1) * int(m_sleep.group(1))
    assert 0 < total_sleep <= 30, f"retry budget {total_sleep}s exceeds 30s"


def test_marker_token_present_exactly_in_template():
    """Monitoring greps for the literal WAKE_STORM_GIVEUP token — pin it."""
    assert "WAKE_STORM_GIVEUP" in TEMPLATE.read_text()
