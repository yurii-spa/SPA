"""STRAT-004 — tests for the stdlib strategy-card validator.

Research-layer only: imports NOTHING from spa_core, mutates no data/, and
never runs the cycle. Reads the repo's real strategy cards + schema.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "data" / "strategy_cards" / "schema.strategy_card.json"
CARDS_DIR = REPO_ROOT / "data" / "strategy_cards" / "examples"

# Load validate.py by file path (no package import machinery, no spa_core).
_spec = importlib.util.spec_from_file_location(
    "spa_research_card_validate", Path(__file__).with_name("validate.py")
)
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)


def _schema() -> dict:
    with SCHEMA.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_no_execution_or_risk_import():
    """The validator must not IMPORT runtime execution / risk / cycle."""
    src = (Path(__file__).with_name("validate.py")).read_text(encoding="utf-8")
    for line in src.splitlines():
        s = line.strip()
        assert not s.startswith("import spa_core")
        assert not s.startswith("from spa_core")


def test_required_field_names_reads_schema():
    req = validate.required_field_names(_schema())
    # Sanity: the schema's known required core fields are surfaced.
    for expected in ("strategy_id", "apy_evidence_level", "status", "owner"):
        assert expected in req


def test_every_real_strategy_card_is_valid():
    schema = _schema()
    cards = sorted(CARDS_DIR.glob("*.strategy.md"))
    assert cards, "no strategy cards found"
    for card in cards:
        problems = validate.validate_card(card.read_text(encoding="utf-8"), schema)
        assert problems == [], f"{card.name}: {problems}"


def test_missing_required_field_is_caught():
    schema = _schema()
    bad = "- **name:** `X`\n"  # missing almost everything
    problems = validate.validate_card(bad, schema)
    assert any("strategy_id" in p for p in problems)


def test_missing_spread_field_is_caught():
    schema = _schema()
    # Take a real valid card, strip one ADR-YL-008 spread field name.
    sample = (CARDS_DIR / "susde_dn.strategy.md").read_text(encoding="utf-8")
    mutilated = sample.replace("spread_fully_explained", "SPREAD_REMOVED")
    problems = validate.validate_card(mutilated, schema)
    assert any("spread_fully_explained" in p for p in problems)


def test_apy_without_evidence_is_caught():
    schema = _schema()
    card = (
        "- **strategy_id:** `SC-9999`\n"
        "- **expected_apy_range:** `{ low: 4, high: 6 }`\n"
        "- **base_apy:** `5`\n"
    )
    problems = validate.validate_card(card, schema)
    assert any("apy_evidence_level" in p for p in problems)


def test_evidence_enum_is_l0_l6():
    assert validate.EVIDENCE_LEVELS == ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
