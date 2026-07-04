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


def _run_gate(name: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CHECK_ONLY="1")
    return subprocess.run(
        ["/bin/bash", _GATE, name],
        capture_output=True, text=True, env=env, timeout=60, cwd=_REPO,
    )


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/env-dependent (needs committed data/ or the Mac host); runs locally, skipped in the data-less GitHub CI")
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
@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/env-dependent (needs committed data/ or the Mac host); runs locally, skipped in the data-less GitHub CI")
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
