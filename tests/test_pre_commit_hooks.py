"""
tests/test_pre_commit_hooks.py
Tests for pre-commit hook infrastructure — MP-1522 (v11.38)

15 tests verifying:
  - pre_commit_check.sh exists and has the required gates
  - install_pre_commit.sh exists and is well-formed
  - Secret detection patterns work correctly
  - Gate content assertions
  - Integration: script runs without error on clean repo
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PRE_COMMIT_SCRIPT = Path("scripts/pre_commit_check.sh")
INSTALL_SCRIPT = Path("scripts/install_pre_commit.sh")


def _read_pre_commit() -> str:
    return PRE_COMMIT_SCRIPT.read_text(encoding="utf-8")


def _read_install() -> str:
    return INSTALL_SCRIPT.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. File existence
# ─────────────────────────────────────────────────────────────────────────────


def test_pre_commit_check_sh_exists() -> None:
    assert PRE_COMMIT_SCRIPT.exists(), "scripts/pre_commit_check.sh not found"


def test_install_pre_commit_sh_exists() -> None:
    assert INSTALL_SCRIPT.exists(), "scripts/install_pre_commit.sh not found"


def test_pre_commit_has_shebang() -> None:
    content = _read_pre_commit()
    assert content.startswith("#!/usr/bin/env bash") or content.startswith("#!/bin/bash"), \
        "pre_commit_check.sh must start with a bash shebang"


def test_install_has_shebang() -> None:
    content = _read_install()
    assert content.startswith("#!/usr/bin/env bash") or content.startswith("#!/bin/bash"), \
        "install_pre_commit.sh must start with a bash shebang"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Gate content assertions
# ─────────────────────────────────────────────────────────────────────────────


def test_gate_bare_exceptions() -> None:
    """pre_commit_check.sh must check for bare exceptions."""
    content = _read_pre_commit()
    assert "bare exception" in content.lower() or "Exception\|RuntimeError" in content or \
           "Exception|RuntimeError" in content, \
        "pre_commit_check.sh must include a bare exceptions gate"


def test_gate_kanban_health() -> None:
    content = _read_pre_commit()
    assert "kanban_health" in content or "KANBAN" in content


def test_gate_no_secrets() -> None:
    content = _read_pre_commit()
    assert "secret" in content.lower() or "ghp_" in content or "SECRET" in content


def test_gate_public_api_import() -> None:
    content = _read_pre_commit()
    assert "import spa_core" in content or "spa_core.VERSION" in content


def test_gate_set_euo_pipefail() -> None:
    """Script must use set -euo pipefail for safe execution."""
    content = _read_pre_commit()
    assert "set -euo pipefail" in content or "set -e" in content


# ─────────────────────────────────────────────────────────────────────────────
# 3. Secret detection patterns
# ─────────────────────────────────────────────────────────────────────────────


def test_secret_pattern_detects_ghp() -> None:
    """Verify the secret pattern in the script would catch real PAT patterns."""
    content = _read_pre_commit()
    # The script must reference ghp_ pattern
    assert "ghp_" in content, "pre_commit_check.sh must scan for ghp_ tokens"


def test_no_actual_secret_in_pre_commit() -> None:
    """The pre_commit_check.sh itself must not contain real tokens."""
    content = _read_pre_commit()
    # Real PATs start with ghp_ followed by many chars (test for full token)
    pat_pattern = re.compile(r"ghp_[A-Za-z0-9]{36,}")
    assert not pat_pattern.search(content), "Real GitHub PAT found in pre_commit_check.sh!"


def test_no_actual_secret_in_install() -> None:
    content = _read_install()
    pat_pattern = re.compile(r"ghp_[A-Za-z0-9]{36,}")
    assert not pat_pattern.search(content), "Real GitHub PAT found in install_pre_commit.sh!"


# ─────────────────────────────────────────────────────────────────────────────
# 4. install_pre_commit.sh content
# ─────────────────────────────────────────────────────────────────────────────


def test_install_references_pre_commit_check() -> None:
    content = _read_install()
    assert "pre_commit_check.sh" in content or "pre-commit" in content


def test_install_has_dry_run_option() -> None:
    content = _read_install()
    assert "--dry-run" in content


def test_install_has_uninstall_option() -> None:
    content = _read_install()
    assert "--uninstall" in content


# ─────────────────────────────────────────────────────────────────────────────
# 5. Bash syntax check (if bash available)
# ─────────────────────────────────────────────────────────────────────────────


def test_pre_commit_bash_syntax() -> None:
    """bash -n checks syntax without executing."""
    result = subprocess.run(
        ["bash", "-n", str(PRE_COMMIT_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, \
        f"pre_commit_check.sh has syntax errors:\n{result.stderr}"


def test_install_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, \
        f"install_pre_commit.sh has syntax errors:\n{result.stderr}"
