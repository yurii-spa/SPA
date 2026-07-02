"""TEST-004 — APY evidence standard (docs/37).

* No strategy card presents an APY field without an `apy_evidence_level`.
* The evidence enum is exactly L0..L6 in every schema that declares it.

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STRAT_DIR = REPO_ROOT / "data" / "strategy_cards" / "examples"
STRAT_SCHEMA = REPO_ROOT / "data" / "strategy_cards" / "schema.strategy_card.json"
LIFECYCLE_SCHEMA = REPO_ROOT / "docs" / "schemas" / "lifecycle_state.schema.json"

EXPECTED_ENUM = ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]

APY_CLAIM_FIELDS = [
    "expected_apy_range",
    "observed_apy_range",
    "base_apy",
    "incentive_apy",
    "sustainable_apy_estimate",
]


def _present(text: str, field: str) -> bool:
    return re.search(r"\b" + re.escape(field) + r"\b", text) is not None


STRAT_CARDS = sorted(STRAT_DIR.glob("*.strategy.md"))


def test_cards_present():
    assert STRAT_CARDS, "no strategy cards found"


@pytest.mark.parametrize("card", STRAT_CARDS, ids=lambda p: p.name)
def test_no_apy_range_without_evidence_level(card: Path):
    text = card.read_text(encoding="utf-8")
    has_apy = any(_present(text, f) for f in APY_CLAIM_FIELDS)
    if has_apy:
        assert _present(text, "apy_evidence_level"), (
            f"{card.name}: presents an APY field but no apy_evidence_level"
        )


@pytest.mark.parametrize("card", STRAT_CARDS, ids=lambda p: p.name)
def test_stated_evidence_level_is_in_enum(card: Path):
    text = card.read_text(encoding="utf-8")
    # Find the value after apy_evidence_level, e.g. "- **apy_evidence_level:** `L3`"
    m = re.search(r"apy_evidence_level[:*`\s]*`?\s*(L[0-9])", text)
    assert m, f"{card.name}: apy_evidence_level value not found"
    assert m.group(1) in EXPECTED_ENUM, f"{card.name}: {m.group(1)} not in {EXPECTED_ENUM}"


def test_strategy_schema_evidence_enum_is_l0_l6():
    with STRAT_SCHEMA.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    enum = schema["properties"]["apy_evidence_level"]["enum"]
    assert enum == EXPECTED_ENUM


def test_lifecycle_schema_evidence_enum_is_l0_l6():
    with LIFECYCLE_SCHEMA.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    enum = schema["properties"]["required_evidence_level"]["enum"]
    assert enum == EXPECTED_ENUM
