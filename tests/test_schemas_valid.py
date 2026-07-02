"""TEST-001 — every research-layer JSON schema parses as valid JSON and has
the draft-2020-12 shape ($schema + properties).

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_FILES = sorted(
    list((REPO_ROOT / "docs" / "schemas").glob("*.json"))
    + list((REPO_ROOT / "data").glob("*_cards/schema.*.json"))
)


def test_schema_files_discovered():
    assert SCHEMA_FILES, "no schema files discovered"
    # sanity: both the docs/schemas set and the data/*_cards set are present
    dirs = {p.parent.name for p in SCHEMA_FILES}
    assert "schemas" in dirs
    assert any(d.endswith("_cards") for d in dirs)


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_parses_and_has_draft_shape(schema_path: Path):
    with schema_path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)  # raises on invalid JSON

    assert isinstance(doc, dict), f"{schema_path.name}: top-level is not an object"

    # draft 2020-12 declaration
    declared = doc.get("$schema", "")
    assert "json-schema.org" in declared and "2020-12" in declared, (
        f"{schema_path.name}: $schema is not draft 2020-12 ({declared!r})"
    )

    # a schema object describing a record must expose properties
    assert "properties" in doc and isinstance(doc["properties"], dict), (
        f"{schema_path.name}: missing 'properties' object"
    )
    assert doc["properties"], f"{schema_path.name}: 'properties' is empty"
