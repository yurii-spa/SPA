#!/usr/bin/env python3
"""STRAT-004 — Strategy Card validator (stdlib-only, research-layer).

A pure-function + CLI validator for SPA Yield Lab Strategy Cards. Given a
strategy-card markdown body and the strategy-card JSON schema, it asserts:

  1. Every REQUIRED field name from the schema appears in the card
     (cards are markdown template-filled, so we check field-NAME presence,
     not JSON-instance validation).
  2. Every ADR-YL-008 spread field name is present.
  3. No APY-ish field is presented without an `apy_evidence_level`
     (docs/37 evidence standard).

This module imports NOTHING from spa_core. It never touches the runtime
RiskPolicy or execution path, and it mutates no data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

# ADR-YL-008 — the five spread-over-floor fields every strategy card must carry.
ADR_YL_008_SPREAD_FIELDS: List[str] = [
    "floor_baseline_pct",
    "spread_over_floor_bps",
    "spread_risk_explanation",
    "unexplained_spread_bps",
    "spread_fully_explained",
]

# docs/37 — APY evidence enum L0..L6.
EVIDENCE_LEVELS: List[str] = ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]

# Field names that assert an APY claim (any of these present ⇒ evidence required).
APY_CLAIM_FIELDS: List[str] = [
    "expected_apy_range",
    "observed_apy_range",
    "base_apy",
    "incentive_apy",
    "sustainable_apy_estimate",
]

_EVIDENCE_FIELD = "apy_evidence_level"


def required_field_names(schema: Dict) -> List[str]:
    """Return the schema's top-level `required` field names."""
    req = schema.get("required", [])
    return [str(x) for x in req]


def _field_present(card_text: str, field: str) -> bool:
    """True if the field NAME appears in the card markdown.

    Cards are template-filled markdown (e.g. ``- **strategy_id:** `SC-...` ``),
    so a field is "present" if its bare name is a whole-word substring.
    """
    return re.search(r"\b" + re.escape(field) + r"\b", card_text) is not None


def validate_card(card_text: str, schema: Dict) -> List[str]:
    """Validate a strategy card body against the schema. Pure function.

    Returns a list of human-readable violation strings. Empty list == valid.
    """
    problems: List[str] = []

    # 1. Every required schema field name present.
    for field in required_field_names(schema):
        if not _field_present(card_text, field):
            problems.append(f"missing required field: {field}")

    # 2. Every ADR-YL-008 spread field present.
    for field in ADR_YL_008_SPREAD_FIELDS:
        if not _field_present(card_text, field):
            problems.append(f"missing ADR-YL-008 spread field: {field}")

    # 3. No APY-ish field without an apy_evidence_level.
    apy_fields_present = [f for f in APY_CLAIM_FIELDS if _field_present(card_text, f)]
    if apy_fields_present and not _field_present(card_text, _EVIDENCE_FIELD):
        problems.append(
            "APY field(s) present without an apy_evidence_level: "
            + ", ".join(apy_fields_present)
        )

    # If an evidence level is stated, it must be one of L0..L6.
    if _field_present(card_text, _EVIDENCE_FIELD):
        m = re.search(_EVIDENCE_FIELD + r"[:*`\s]*[`]?\s*(L[0-9])", card_text)
        if m and m.group(1) not in EVIDENCE_LEVELS:
            problems.append(f"invalid apy_evidence_level: {m.group(1)}")

    return problems


def _load_schema(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a SPA strategy card (STRAT-004).")
    parser.add_argument("card", type=Path, help="Path to a strategy-card .md file.")
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data"
        / "strategy_cards"
        / "schema.strategy_card.json",
        help="Path to schema.strategy_card.json.",
    )
    args = parser.parse_args(argv)

    card_text = args.card.read_text(encoding="utf-8")
    schema = _load_schema(args.schema)
    problems = validate_card(card_text, schema)

    if problems:
        print(f"INVALID: {args.card}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
