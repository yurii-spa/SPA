"""TEST-002 — every example card contains the required field NAMES from its
matching schema. Cards are markdown template-filled, so we check field-name
presence (not JSON-instance validation). Strategy cards must additionally
carry all 5 ADR-YL-008 spread fields.

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ADR_YL_008_SPREAD_FIELDS = [
    "floor_baseline_pct",
    "spread_over_floor_bps",
    "spread_risk_explanation",
    "unexplained_spread_bps",
    "spread_fully_explained",
]

# (card_glob, schema_path, extra_required_fields)
CARD_SETS = [
    (
        REPO_ROOT / "data" / "strategy_cards" / "examples",
        "*.strategy.md",
        REPO_ROOT / "data" / "strategy_cards" / "schema.strategy_card.json",
        ADR_YL_008_SPREAD_FIELDS,
    ),
    (
        REPO_ROOT / "data" / "protocol_cards" / "examples",
        "*.protocol.md",
        REPO_ROOT / "data" / "protocol_cards" / "schema.protocol_card.json",
        [],
    ),
    (
        REPO_ROOT / "data" / "stablecoin_cards" / "examples",
        "*.stablecoin.md",
        REPO_ROOT / "data" / "stablecoin_cards" / "schema.stablecoin_card.json",
        [],
    ),
]


def _required(schema_path: Path) -> list[str]:
    with schema_path.open("r", encoding="utf-8") as fh:
        return list(json.load(fh).get("required", []))


def _present(card_text: str, field: str) -> bool:
    return re.search(r"\b" + re.escape(field) + r"\b", card_text) is not None


def _collect_cases():
    cases = []
    for examples_dir, glob, schema_path, extra in CARD_SETS:
        req = _required(schema_path) + extra
        for card in sorted(examples_dir.glob(glob)):
            cases.append((card, tuple(req)))
    return cases


CASES = _collect_cases()


def test_cards_discovered():
    assert CASES, "no example cards discovered"
    # all three families represented
    names = {c.name for c, _ in CASES}
    assert any(n.endswith(".strategy.md") for n in names)
    assert any(n.endswith(".protocol.md") for n in names)
    assert any(n.endswith(".stablecoin.md") for n in names)


@pytest.mark.parametrize(
    "card_path,required_fields", CASES, ids=lambda x: x.name if isinstance(x, Path) else ""
)
def test_card_contains_required_field_names(card_path: Path, required_fields):
    text = card_path.read_text(encoding="utf-8")
    missing = [f for f in required_fields if not _present(text, f)]
    assert not missing, f"{card_path.name} missing field names: {missing}"


def test_every_strategy_card_has_all_five_spread_fields():
    strat_dir = REPO_ROOT / "data" / "strategy_cards" / "examples"
    cards = sorted(strat_dir.glob("*.strategy.md"))
    assert cards, "no strategy cards found"
    for card in cards:
        text = card.read_text(encoding="utf-8")
        missing = [f for f in ADR_YL_008_SPREAD_FIELDS if not _present(text, f)]
        assert not missing, f"{card.name} missing ADR-YL-008 spread fields: {missing}"
