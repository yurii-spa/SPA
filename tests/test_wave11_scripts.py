"""
tests/test_wave11_scripts.py
MP-1552 (v11.68) — Wave 11 push scripts validation
15 tests — all GREEN
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO, "scripts")
WAVE11_SCRIPT = os.path.join(SCRIPTS_DIR, "run_cpa_wave11_pushes.sh")

# NOTE: _push_wave11.command (the double-click Finder launcher) was intentionally
# purged from the repo in commit c3b765dae ("purge tracked junk from remote —
# *.command ...") and *.command is now gitignored (.gitignore:83), because a
# rotated Cloudflare token had leaked via a sibling *.command file. The launcher
# is a throwaway convenience artifact, not an ongoing product surface, so the
# tests that asserted its existence/contents/permissions have been removed as
# dead tests. The wave11 wrapper (run_cpa_wave11_pushes.sh) — the real artifact —
# remains under test below.

WAVE11_VERSIONS = [
    "v1155", "v1156", "v1157", "v1158", "v1159", "v1160",
    "v1161", "v1162", "v1163", "v1164", "v1165", "v1166",
    "v1167", "v1168", "v1169", "v1170",
]


# ── File existence ────────────────────────────────────────────────────────────

def test_wave11_script_exists():
    assert os.path.isfile(WAVE11_SCRIPT), \
        f"Missing: {WAVE11_SCRIPT}"


# NOTE: the one-shot push_v1167–1170.sh scripts were throwaway artifacts that were
# removed in the repo cleanup (they were never committed and serve no ongoing
# purpose). The tests that asserted their existence are obsolete and have been
# removed. The wave11 wrapper (run_cpa_wave11_pushes.sh) remains under test below.


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
