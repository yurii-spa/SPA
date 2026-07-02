"""TEST-003 — lifecycle transition rules (docs/07 §3 + lifecycle_state schema).

Asserts the stdlib transition-checker in research/lifecycle.py accepts every
legal transition and REJECTS illegal ones (e.g. idea → approved_for_enhanced
directly is illegal).

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_SCHEMA = REPO_ROOT / "docs" / "schemas" / "lifecycle_state.schema.json"

_spec = importlib.util.spec_from_file_location(
    "spa_research_lifecycle", REPO_ROOT / "research" / "lifecycle.py"
)
lifecycle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lifecycle)


def _schema_status_enum() -> set[str]:
    with LIFECYCLE_SCHEMA.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return set(doc["properties"]["status"]["enum"])


def test_status_set_matches_schema_enum():
    """The checker's STATUSES must equal the schema's status enum exactly."""
    assert lifecycle.STATUSES == _schema_status_enum()


LEGAL = [
    ("idea", "research"),
    ("research", "paper_testing"),
    ("research", "rejected"),
    ("paper_testing", "paper_passed"),
    ("paper_testing", "rejected"),
    ("paper_testing", "frozen"),
    ("paper_passed", "small_capital_testing"),
    ("small_capital_testing", "small_capital_passed"),
    ("small_capital_testing", "frozen"),
    ("small_capital_passed", "approved_for_preserve"),
    ("small_capital_passed", "approved_for_core"),
    ("small_capital_passed", "approved_for_enhanced"),
    ("small_capital_passed", "approved_for_max_yield"),
    ("approved_for_core", "approved_for_enhanced"),  # re-tier
    ("approved_for_enhanced", "frozen"),
    ("frozen", "approved_for_enhanced"),  # un-freeze
    ("frozen", "retired"),
    ("approved_for_max_yield", "retired"),
    ("rejected", "research"),  # reopen with new evidence
]

ILLEGAL = [
    ("idea", "approved_for_enhanced"),  # the named example — skips the whole ladder
    ("idea", "paper_testing"),  # must go through research
    ("research", "approved_for_core"),
    ("research", "small_capital_testing"),
    ("paper_testing", "small_capital_testing"),  # must pass paper first
    ("paper_passed", "approved_for_core"),  # must small-cap test first
    ("small_capital_passed", "retired"),  # not a direct edge
    ("retired", "research"),  # terminal
    ("retired", "approved_for_core"),  # terminal
    ("approved_for_core", "idea"),  # no going back to idea
    ("paper_passed", "paper_testing"),  # no backslide edge defined
]


@pytest.mark.parametrize("src,dst", LEGAL, ids=lambda t: t if isinstance(t, str) else "")
def test_legal_transitions_accepted(src, dst):
    assert lifecycle.is_allowed(src, dst)
    lifecycle.check_transition(src, dst)  # must not raise


@pytest.mark.parametrize("src,dst", ILLEGAL, ids=lambda t: t if isinstance(t, str) else "")
def test_illegal_transitions_rejected(src, dst):
    assert not lifecycle.is_allowed(src, dst)
    with pytest.raises(lifecycle.IllegalTransition):
        lifecycle.check_transition(src, dst)


def test_idea_to_enhanced_is_illegal_named_case():
    """Explicit named case from the task spec."""
    with pytest.raises(lifecycle.IllegalTransition):
        lifecycle.check_transition("idea", "approved_for_enhanced")


def test_unknown_status_raises_valueerror():
    with pytest.raises(ValueError):
        lifecycle.is_allowed("idea", "not_a_status")
    with pytest.raises(ValueError):
        lifecycle.is_allowed("not_a_status", "idea")
