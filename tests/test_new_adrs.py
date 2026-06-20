"""
tests/test_new_adrs.py

MP-1456 (v10.72) — ADR-032..036 existence and structure tests.
15 tests verifying ADR files exist, contain required sections, and meet quality standards.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"

NEW_ADRS = [
    "ADR-032-live-trading-gate.md",
    "ADR-034-atomic-write-centralization.md",
    "ADR-035-spaerror-hierarchy.md",
    "ADR-036-baseanalytics-migration.md",
]

REQUIRED_SECTIONS = ["Status", "Decision", "Context", "Consequences"]
MIN_BYTES = 500


# ── 1. File existence ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename", NEW_ADRS)
def test_adr_file_exists(filename):
    """Each new ADR file must exist in docs/adr/."""
    path = ADR_DIR / filename
    assert path.exists(), f"ADR file missing: {filename}"


@pytest.mark.parametrize("filename", NEW_ADRS)
def test_adr_file_non_empty(filename):
    """Each ADR must be at least 500 bytes."""
    path = ADR_DIR / filename
    if path.exists():
        assert path.stat().st_size >= MIN_BYTES, (
            f"{filename} too small: {path.stat().st_size} bytes (need ≥{MIN_BYTES})"
        )


# ── 2. Required sections ──────────────────────────────────────────────────────

@pytest.mark.parametrize("filename", NEW_ADRS)
@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_adr_contains_section(filename, section):
    """Each ADR must contain the required section heading."""
    path = ADR_DIR / filename
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert section in content, (
            f"{filename} missing section '## {section}' or '{section}' keyword"
        )


# ── 3. Content quality ────────────────────────────────────────────────────────

def test_adr032_mentions_gate():
    """ADR-032 must mention LiveTradingGate or gate concepts."""
    path = ADR_DIR / "ADR-032-live-trading-gate.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert any(kw in content for kw in ["gate", "Gate", "LOCKED", "activation"]), \
            "ADR-032 must discuss live trading gate concepts"


def test_adr034_mentions_atomic():
    """ADR-034 must mention atomic_save or atomic write pattern."""
    path = ADR_DIR / "ADR-034-atomic-write-centralization.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert any(kw in content for kw in ["atomic_save", "os.replace", "atomic"]), \
            "ADR-034 must discuss atomic write pattern"


def test_adr035_mentions_spaerror():
    """ADR-035 must mention SPAError hierarchy."""
    path = ADR_DIR / "ADR-035-spaerror-hierarchy.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "SPAError" in content, "ADR-035 must mention SPAError"


def test_adr036_mentions_baseanalytics():
    """ADR-036 must mention BaseAnalytics class."""
    path = ADR_DIR / "ADR-036-baseanalytics-migration.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        assert "BaseAnalytics" in content, "ADR-036 must mention BaseAnalytics"


# ── 4. ADR directory totals ───────────────────────────────────────────────────

def test_adr_directory_has_minimum_count():
    """docs/adr/ must have at least 20 ADR files."""
    adr_files = list(ADR_DIR.glob("*.md"))
    assert len(adr_files) >= 20, (
        f"Only {len(adr_files)} ADR files found (need ≥20)"
    )


def test_adr_directory_has_new_adrs():
    """All 4 new ADRs from MP-1456 must be present."""
    missing = [f for f in NEW_ADRS if not (ADR_DIR / f).exists()]
    assert not missing, f"Missing ADR files: {missing}"


def test_documentation_score_still_max():
    """documentation category must remain at 10/10 after ADR additions."""
    sys.path.insert(0, str(REPO_ROOT))
    from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
    r = GoLiveReadinessReport(base_dir=str(REPO_ROOT))
    d = r.assess_documentation_v2()
    assert d.score == d.max_score == 10.0, (
        f"Documentation score regressed: {d.score}/{d.max_score}"
    )
