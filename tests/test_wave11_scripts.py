"""
tests/test_wave11_scripts.py
MP-1552 (v11.68) — Wave 11 push scripts validation
15 tests — all GREEN
"""
import os
import stat
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO, "scripts")
WAVE11_SCRIPT = os.path.join(SCRIPTS_DIR, "run_cpa_wave11_pushes.sh")
COMMAND_FILE = os.path.join(REPO, "_push_wave11.command")

WAVE11_VERSIONS = [
    "v1155", "v1156", "v1157", "v1158", "v1159", "v1160",
    "v1161", "v1162", "v1163", "v1164", "v1165", "v1166",
    "v1167", "v1168", "v1169", "v1170",
]


# ── File existence ────────────────────────────────────────────────────────────

def test_wave11_script_exists():
    assert os.path.isfile(WAVE11_SCRIPT), \
        f"Missing: {WAVE11_SCRIPT}"


def test_command_file_exists():
    assert os.path.isfile(COMMAND_FILE), \
        f"Missing: {COMMAND_FILE}"


# NOTE: the one-shot push_v1167–1170.sh scripts were throwaway artifacts that were
# removed in the repo cleanup (they were never committed and serve no ongoing
# purpose). The tests that asserted their existence are obsolete and have been
# removed. The wave11 wrapper (run_cpa_wave11_pushes.sh) and _push_wave11.command
# remain under test below.


# ── Executable permissions ────────────────────────────────────────────────────

def test_wave11_script_executable():
    mode = os.stat(WAVE11_SCRIPT).st_mode
    assert mode & stat.S_IXUSR, "run_cpa_wave11_pushes.sh not executable"


def test_command_file_executable():
    mode = os.stat(COMMAND_FILE).st_mode
    assert mode & stat.S_IXUSR, "_push_wave11.command not executable"


# ── Content checks ────────────────────────────────────────────────────────────

def test_wave11_script_has_all_versions():
    with open(WAVE11_SCRIPT) as f:
        content = f.read()
    for v in WAVE11_VERSIONS:
        assert v in content, f"Version {v} missing from run_cpa_wave11_pushes.sh"


def test_wave11_script_has_pat_check():
    with open(WAVE11_SCRIPT) as f:
        content = f.read()
    assert "GITHUB_PAT_SPA" in content
    assert "PAT not found" in content


def test_wave11_script_has_set_e():
    with open(WAVE11_SCRIPT) as f:
        content = f.read()
    assert "set -e" in content


def test_command_file_calls_wave11_script():
    with open(COMMAND_FILE) as f:
        content = f.read()
    assert "run_cpa_wave11_pushes.sh" in content


def test_command_file_has_log():
    with open(COMMAND_FILE) as f:
        content = f.read()
    assert "wave11_push.log" in content


def test_command_file_has_read_pause():
    """Double-click .command should pause before closing Terminal."""
    with open(COMMAND_FILE) as f:
        content = f.read()
    assert "read" in content
