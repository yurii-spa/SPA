"""`com.spa.system_briefing` wrapper must REACH its final exec (ADR-610 review P0, 2026-10-07).

An edit that added the continuity step glued the last line into `exec/bin/bash …` — still valid shell
syntax (`bash -n` passes), but `exec/bin/bash` is a command name that does not exist: rc 127 on every
30-minute tick, so SYSTEM_BRIEFING, the mirror-backed memory `ensure-fresh` and the continuity rebuild
would all go dark silently. Two checks: the exact exec line, and a real run of the real script with its
absolute paths redirected to stubs (positive control: the glued variant must exit 127 in the same scene).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "scripts" / "agent_system_briefing.sh"
PROD = "/Users/yuriikulieshov/Documents/SPA_Claude"
PY = "/Users/yuriikulieshov/miniconda3/bin/python3"
MIRROR = "/Users/yuriikulieshov/Documents/SPA_mirror"


def test_exec_line_is_exec_space_bin_bash():
    last = [l for l in WRAPPER.read_text(encoding="utf-8").splitlines() if l.strip()][-1]
    assert re.match(r"^exec /bin/bash \S+/scripts/agent_template\.sh system_briefing ", last), last


def _run(tmp: Path, text: str) -> subprocess.CompletedProcess:
    root = tmp / "prod"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "agent_template.sh").write_text('echo "REACHED $*"\n')
    stub_py = tmp / "python3"
    stub_py.write_text("#!/bin/sh\nexit 0\n")
    stub_py.chmod(0o755)
    logs = tmp / "logs"
    logs.mkdir()
    text = (text.replace(PY, str(stub_py)).replace(MIRROR, str(tmp / "no_mirror")).replace(PROD, str(root))
            .replace("/tmp/spa_", f"{logs}/spa_"))
    script = tmp / "wrapper.sh"
    script.write_text(text)
    return subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp)})


def test_real_wrapper_runs_to_the_exec(tmp_path):
    src = WRAPPER.read_text(encoding="utf-8")
    assert PY in src and PROD in src          # the stubbing below must actually bite
    r = _run(tmp_path, src)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert "REACHED system_briefing" in r.stdout


def test_positive_control_glued_exec_dies_127(tmp_path):
    src = WRAPPER.read_text(encoding="utf-8").replace("\nexec /bin/bash ", "\nexec/bin/bash ")
    r = _run(tmp_path, src)
    assert r.returncode == 127 and "REACHED" not in r.stdout
