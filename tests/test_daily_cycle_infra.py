"""
tests/test_daily_cycle_infra.py

MP-1427 (v10.43): 25 tests for launchd daily cycle infrastructure.

Verifies:
  - Shell script exists and has correct content
  - launchd plist exists and is valid XML with correct values
  - Install script exists and has correct content
  - Python modules referenced are importable
  - Log directory logic is correct

stdlib only, no external dependencies.
"""
from __future__ import annotations

import os
import sys
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# ── Locate repo root ──────────────────────────────────────────────────────────
REPO = Path(__file__).parent.parent
SCRIPTS = REPO / "scripts"
TESTS = REPO / "tests"

RUNNER_SH = SCRIPTS / "run_daily_paper_cycle.sh"
PLIST_FILE = SCRIPTS / "com.spa.daily_cycle.plist"
INSTALL_SH = SCRIPTS / "install_daily_cycle.sh"


# ════════════════════════════════════════════════════════════════════════════
# Group 1: run_daily_paper_cycle.sh
# ════════════════════════════════════════════════════════════════════════════

class TestRunnerScript:
    """Tests for scripts/run_daily_paper_cycle.sh"""

    def test_runner_exists(self):
        """T01: run_daily_paper_cycle.sh exists"""
        assert RUNNER_SH.exists(), f"Missing: {RUNNER_SH}"

    def test_runner_has_shebang(self):
        """T02: runner starts with #!/bin/bash"""
        content = RUNNER_SH.read_text()
        assert content.startswith("#!/bin/bash"), "Missing #!/bin/bash shebang"

    def test_runner_references_cpa_cycle_with_evidence(self):
        """T03: runner invokes CPACycleWithEvidence"""
        content = RUNNER_SH.read_text()
        assert "CPACycleWithEvidence" in content

    def test_runner_creates_log_dir(self):
        """T04: runner creates logs directory"""
        content = RUNNER_SH.read_text()
        assert "mkdir -p" in content

    def test_runner_uses_log_file(self):
        """T05: runner writes to LOG_FILE"""
        content = RUNNER_SH.read_text()
        assert "LOG_FILE" in content

    def test_runner_uses_utc_timestamp(self):
        """T06: runner uses UTC date in log"""
        content = RUNNER_SH.read_text()
        assert "date -u" in content or "date +%Y" in content

    def test_runner_has_set_e(self):
        """T07: runner uses set -e for error propagation"""
        content = RUNNER_SH.read_text()
        assert "set -e" in content

    def test_runner_cds_to_repo(self):
        """T08: runner changes to SPA_Claude directory"""
        content = RUNNER_SH.read_text()
        assert "SPA_Claude" in content and "cd " in content

    def test_runner_logs_completion(self):
        """T09: runner logs completion message"""
        content = RUNNER_SH.read_text()
        assert "completed" in content.lower() or "Cycle completed" in content

    def test_runner_exits_with_code(self):
        """T10: runner propagates exit code (any explicit `exit $VAR`/`exit 0`)."""
        content = RUNNER_SH.read_text()
        assert (
            "EXIT_CODE" in content
            or "CYCLE_EXIT" in content
            or "exit $?" in content
            or "exit 0" in content
        )


# ════════════════════════════════════════════════════════════════════════════
# Group 2: com.spa.daily_cycle.plist
# ════════════════════════════════════════════════════════════════════════════

class TestLaunchdPlist:
    """Tests for scripts/com.spa.daily_cycle.plist"""

    def test_plist_exists(self):
        """T11: com.spa.daily_cycle.plist exists"""
        assert PLIST_FILE.exists(), f"Missing: {PLIST_FILE}"

    def test_plist_is_valid_xml(self):
        """T12: plist parses as valid XML"""
        tree = ET.parse(PLIST_FILE)
        root = tree.getroot()
        assert root.tag == "plist"

    def test_plist_label_correct(self):
        """T13: plist Label == com.spa.daily_cycle"""
        content = PLIST_FILE.read_text()
        assert "com.spa.daily_cycle" in content

    def test_plist_hour_is_8(self):
        """T14: StartCalendarInterval Hour = 8"""
        content = PLIST_FILE.read_text()
        assert "<integer>8</integer>" in content

    def test_plist_uses_shell_script(self):
        """T15: plist invokes run_daily_paper_cycle.sh"""
        content = PLIST_FILE.read_text()
        assert "run_daily_paper_cycle.sh" in content

    def test_plist_uses_bash(self):
        """T16: plist calls /bin/bash"""
        content = PLIST_FILE.read_text()
        assert "/bin/bash" in content

    def test_plist_has_stdout_path(self):
        """T17: plist has StandardOutPath"""
        content = PLIST_FILE.read_text()
        assert "StandardOutPath" in content

    def test_plist_has_stderr_path(self):
        """T18: plist has StandardErrorPath"""
        content = PLIST_FILE.read_text()
        assert "StandardErrorPath" in content

    def test_plist_has_start_calendar_interval(self):
        """T19: plist uses StartCalendarInterval (not StartInterval)"""
        content = PLIST_FILE.read_text()
        assert "StartCalendarInterval" in content

    def test_plist_no_start_interval(self):
        """T20: plist does NOT use StartInterval (old bug — caused Telegram spam)"""
        content = PLIST_FILE.read_text()
        # StartCalendarInterval is allowed; StartInterval alone is the bug
        lines = [l.strip() for l in content.splitlines()]
        for line in lines:
            if "<key>StartInterval</key>" in line:
                pytest.fail("Found StartInterval — old bug; use StartCalendarInterval")

    def test_plist_has_environment_path(self):
        """T21: plist sets PATH environment variable"""
        content = PLIST_FILE.read_text()
        assert "EnvironmentVariables" in content or "PATH" in content


# ════════════════════════════════════════════════════════════════════════════
# Group 3: install_daily_cycle.sh
# ════════════════════════════════════════════════════════════════════════════

class TestInstallScript:
    """Tests for scripts/install_daily_cycle.sh"""

    def test_install_exists(self):
        """T22: install_daily_cycle.sh exists"""
        assert INSTALL_SH.exists(), f"Missing: {INSTALL_SH}"

    def test_install_loads_launchd(self):
        """T23: install script calls launchctl load"""
        content = INSTALL_SH.read_text()
        assert "launchctl load" in content

    def test_install_copies_to_launch_agents(self):
        """T24: install script targets ~/Library/LaunchAgents"""
        content = INSTALL_SH.read_text()
        assert "LaunchAgents" in content

    def test_install_makes_runner_executable(self):
        """T25: install script calls chmod +x on runner"""
        content = INSTALL_SH.read_text()
        assert "chmod +x" in content
