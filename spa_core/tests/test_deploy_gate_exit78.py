# LLM_FORBIDDEN
"""spa_core/tests/test_deploy_gate_exit78.py — WS-8 deploy-gate red-team.

scripts/check_agent_before_deploy.sh must FAIL CLOSED (non-zero, agent NOT loaded) on the two
STATIC exit-78 antipatterns, BEFORE any launchctl load — so a new agent that would exit-78 is
caught at validation time, not only at load time:

  1. ProgramArguments[0] execs miniconda-python DIRECTLY (launchd cannot exec it → exit 78).
  2. StandardOutPath/StandardErrorPath under ~/Documents (TCC blocks the launchd write → exit 78).

These run in CHECK_ONLY mode (no launchctl), proving the gate refuses without touching the host.
"""
from __future__ import annotations

import os
import subprocess

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_GATE = os.path.join(_REPO, "scripts", "check_agent_before_deploy.sh")
_SCRIPTS = os.path.join(_REPO, "scripts")

_DIRECT_PY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.gatetest_directpy</string>
  <key>ProgramArguments</key><array>
    <string>/Users/yuriikulieshov/miniconda3/bin/python3</string>
    <string>-m</string><string>spa_core.redteam.rotation</string>
  </array>
  <key>StandardOutPath</key><string>/tmp/gatetest.out</string>
</dict></plist>
"""

_DOCS_LOG = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.gatetest_docslog</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>%s/agent_redteam_rotation.sh</string>
  </array>
  <key>StandardOutPath</key>
  <string>/Users/yuriikulieshov/Documents/SPA_Claude/logs/gatetest.out</string>
</dict></plist>
""" % _SCRIPTS


def _gate_repo_root() -> str:
    """The repo root the GATE itself resolves — it is a hardcoded constant in the shell script.

    The gate does not derive its root from ``cwd`` or from its own location: it pins
    ``REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"`` (so the canonical-track hash guard
    can never be pointed at a decoy tree). These two tests write their antipattern plist into
    ``<this checkout>/scripts/`` — which the gate only finds when this checkout IS that canonical
    root. From any other checkout (worktree, CI, a clone) the gate answers "plist not found" and
    the test fails on a path mismatch instead of on the property it means to prove.
    """
    try:
        with open(_GATE, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("REPO_ROOT="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


_GATE_ROOT = _gate_repo_root()
# Gate on the real precondition instead of on "am I in CI": the reason is then true wherever it
# fires, and inside the canonical checkout the tests genuinely EXECUTE. Writing the fixture plist
# into the canonical tree from a foreign checkout is NOT an option — a test must not mutate
# another working tree's scripts/.
_needs_canonical_checkout = pytest.mark.skipif(
    _REPO != _GATE_ROOT,
    reason=(f"the deploy gate hardcodes REPO_ROOT={_GATE_ROOT!r}; this checkout is {_REPO!r}, so the "
            "gate cannot see a fixture plist written here (it would report 'plist not found' rather "
            "than exercising the exit-78 refusal)"),
)


def _run_gate(name: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CHECK_ONLY="1")
    return subprocess.run(
        ["/bin/bash", _GATE, name],
        capture_output=True, text=True, env=env, timeout=60, cwd=_REPO,
    )


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
@_needs_canonical_checkout
def test_gate_fails_closed_on_direct_python():
    """Antipattern 1: direct miniconda-python in ProgramArguments → fail-closed before load."""
    plist = os.path.join(_SCRIPTS, "com.spa.gatetest_directpy.plist")
    with open(plist, "w") as f:
        f.write(_DIRECT_PY)
    try:
        res = _run_gate("gatetest_directpy")
    finally:
        os.remove(plist)
    assert res.returncode != 0, f"gate should FAIL CLOSED on direct python; stdout={res.stdout}"
    blob = res.stdout + res.stderr
    assert "exit 78" in blob and "python" in blob.lower()


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
@_needs_canonical_checkout
def test_gate_fails_closed_on_documents_log_path():
    """Antipattern 2: a log path under ~/Documents → TCC exit-78 → fail-closed before load."""
    plist = os.path.join(_SCRIPTS, "com.spa.gatetest_docslog.plist")
    with open(plist, "w") as f:
        f.write(_DOCS_LOG)
    try:
        res = _run_gate("gatetest_docslog")
    finally:
        os.remove(plist)
    assert res.returncode != 0, f"gate should FAIL CLOSED on ~/Documents log; stdout={res.stdout}"
    blob = res.stdout + res.stderr
    assert "Documents" in blob and "exit 78" in blob
