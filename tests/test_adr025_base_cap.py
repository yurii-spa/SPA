"""
tests/test_adr025_base_cap.py — ADR-025 Base Chain Expansion checks
MP-449 | Sprint v4.78

Validates:
  1. BASE_CHAIN_CAP == 0.20
  2. BASE_CHAIN_CAP < 0.50 (sanity)
  3. ADR-025 document exists and contains "ADR-025"
  4. ADR-025 document contains "Phase 1"
  5. ADR-025 document contains "Base Chain"
"""

import os
import sys

# Make sure spa_core is importable when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.risk.policy import RiskConfig

ADR_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "docs",
    "adr",
    "ADR-025-base-chain-expansion.md",
)


def _adr_text() -> str:
    with open(ADR_PATH, encoding="utf-8") as f:
        return f.read()


def test_base_chain_cap_value():
    """BASE_CHAIN_CAP must equal exactly 0.20 (ADR-025)."""
    cfg = RiskConfig()
    assert cfg.BASE_CHAIN_CAP == 0.20, (
        f"Expected BASE_CHAIN_CAP == 0.20, got {cfg.BASE_CHAIN_CAP}"
    )


def test_base_chain_cap_sanity():
    """BASE_CHAIN_CAP must be less than 0.50 (sanity: never exceeds T2 total cap)."""
    cfg = RiskConfig()
    assert cfg.BASE_CHAIN_CAP < 0.50, (
        f"BASE_CHAIN_CAP {cfg.BASE_CHAIN_CAP} is not < 0.50"
    )


def test_adr025_document_exists_and_contains_id():
    """ADR-025 document must exist and contain the string 'ADR-025'."""
    assert os.path.isfile(ADR_PATH), f"ADR document not found: {ADR_PATH}"
    text = _adr_text()
    assert "ADR-025" in text, "Document does not contain 'ADR-025'"


def test_adr025_document_contains_phase1():
    """ADR-025 document must contain 'Phase 1' (phased rollout commitment)."""
    text = _adr_text()
    assert "Phase 1" in text, "Document does not contain 'Phase 1'"


def test_adr025_document_contains_base_chain():
    """ADR-025 document must contain 'Base Chain' (subject of the ADR)."""
    text = _adr_text()
    assert "Base Chain" in text, "Document does not contain 'Base Chain'"
