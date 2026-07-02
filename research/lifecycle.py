#!/usr/bin/env python3
"""SPA Yield Lab lifecycle transition checker (stdlib-only, research-layer).

Encodes the allowed status transitions from docs/07 §3
(``07_yield_lab_architecture.md``) and the status enum in
``docs/schemas/lifecycle_state.schema.json``.

Graph (docs/07 §3):

    idea → research
    research → paper_testing | rejected
    paper_testing → paper_passed | rejected | frozen
    paper_passed → small_capital_testing | rejected
    small_capital_testing → small_capital_passed | frozen
    small_capital_passed → approved_for_{preserve,core,enhanced,max_yield}
    approved_for_* → (re-tier to another approved_* ) | frozen | retired
    frozen → (un-freeze back to prior-style approved_*) | retired
    rejected → terminal (may reopen to research with NEW evidence)
    retired → terminal

Imports NOTHING from spa_core. Never touches RiskPolicy / execution. No I/O.
"""

from __future__ import annotations

from typing import Dict, Set

# The canonical status enum (mirrors lifecycle_state.schema.json / strategy card).
STATUSES: Set[str] = {
    "idea",
    "research",
    "rejected",
    "paper_testing",
    "paper_passed",
    "small_capital_testing",
    "small_capital_passed",
    "approved_for_preserve",
    "approved_for_core",
    "approved_for_enhanced",
    "approved_for_max_yield",
    "frozen",
    "retired",
}

_APPROVED = {
    "approved_for_preserve",
    "approved_for_core",
    "approved_for_enhanced",
    "approved_for_max_yield",
}

# Allowed forward transitions per docs/07 §3.
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "idea": {"research"},
    "research": {"paper_testing", "rejected"},
    "paper_testing": {"paper_passed", "rejected", "frozen"},
    "paper_passed": {"small_capital_testing", "rejected"},
    "small_capital_testing": {"small_capital_passed", "frozen"},
    "small_capital_passed": set(_APPROVED),
    # Approved cards may be re-tiered, frozen, or retired.
    "approved_for_preserve": (set(_APPROVED) | {"frozen", "retired"}) - {"approved_for_preserve"},
    "approved_for_core": (set(_APPROVED) | {"frozen", "retired"}) - {"approved_for_core"},
    "approved_for_enhanced": (set(_APPROVED) | {"frozen", "retired"}) - {"approved_for_enhanced"},
    "approved_for_max_yield": (set(_APPROVED) | {"frozen", "retired"}) - {"approved_for_max_yield"},
    # frozen: un-freeze back to an approved line (review) or retire.
    "frozen": set(_APPROVED) | {"retired"},
    # Terminal states.
    "rejected": {"research"},  # may reopen ONLY with new evidence
    "retired": set(),
}


class IllegalTransition(ValueError):
    """Raised when a status transition is not permitted by docs/07 §3."""


def is_allowed(src: str, dst: str) -> bool:
    """True iff ``src → dst`` is a permitted lifecycle transition."""
    if src not in STATUSES:
        raise ValueError(f"unknown source status: {src!r}")
    if dst not in STATUSES:
        raise ValueError(f"unknown target status: {dst!r}")
    return dst in ALLOWED_TRANSITIONS.get(src, set())


def check_transition(src: str, dst: str) -> None:
    """Raise IllegalTransition if ``src → dst`` is not permitted."""
    if not is_allowed(src, dst):
        raise IllegalTransition(f"illegal lifecycle transition: {src} -> {dst}")
