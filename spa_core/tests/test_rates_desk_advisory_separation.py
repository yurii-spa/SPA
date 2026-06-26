"""
test_rates_desk_advisory_separation.py — HARD SEPARATION contract for the rates-desk sleeves.

Architect decision T5: the four rates-desk sleeves (FixedCarry / LeveredCarry / RateMatrix /
BasisHedge) are surfaced in the promotion REPORTING view, but they are IS_ADVISORY=True and MUST
NOT feed the live tournament/allocator before go-live. This suite asserts that contract in CODE
(not just on the reporting surface):

  • every rates-desk sleeve class is is_advisory=True (simulate only, never moves live capital);
  • the rates-desk sleeve ids appear in NO live-allocation path — neither the live strategy
    registry (REGISTRY) nor the multi_strategy_runner / allocator module sources.

Deterministic, stdlib-only.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from spa_core.strategy_lab.rates_desk.sleeves import (
    BasisHedgeSleeve,
    FixedCarrySleeve,
    LeveredCarrySleeve,
    RateMatrixSleeve,
)

_RATES_DESK_SLEEVE_CLASSES = (
    FixedCarrySleeve,
    LeveredCarrySleeve,
    RateMatrixSleeve,
    BasisHedgeSleeve,
)

_RATES_DESK_SLEEVE_IDS = (
    "rates_desk_fixed_carry",
    "rates_desk_levered_carry",
    "rates_desk_rate_matrix",
    "rates_desk_basis_hedge",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_all_rates_desk_sleeves_are_advisory():
    """Every rates-desk sleeve class is is_advisory=True — simulate only, never live capital."""
    for cls in _RATES_DESK_SLEEVE_CLASSES:
        assert getattr(cls, "is_advisory", False) is True, (
            f"{cls.__name__} must be is_advisory=True (rates-desk sleeves never move live capital)"
        )


def test_rates_desk_ids_absent_from_live_strategy_registry():
    """The rates-desk sleeve ids are NOT registered in the live strategy REGISTRY (the source the
    tournament/allocator iterate over) — reporting only, never a live allocation."""
    from spa_core.strategies.strategy_registry import REGISTRY

    registered = set(REGISTRY.get_all(enabled_only=False).keys())
    for sid in _RATES_DESK_SLEEVE_IDS:
        assert sid not in registered, (
            f"{sid} must NOT be in the live strategy registry (it is IS_ADVISORY, reporting only)"
        )


def test_rates_desk_ids_absent_from_live_allocation_sources():
    """The rates-desk sleeve ids appear nowhere in the live allocation source files
    (multi_strategy_runner + the allocator) — a grep-level guard against accidental wiring."""
    live_sources = [
        _PROJECT_ROOT / "spa_core" / "paper_trading" / "multi_strategy_runner.py",
    ]
    # the allocator module (name has drifted historically — include whatever exists)
    for cand in (
        _PROJECT_ROOT / "spa_core" / "strategies" / "strategy_allocator.py",
        _PROJECT_ROOT / "spa_core" / "paper_trading" / "strategy_allocator.py",
        _PROJECT_ROOT / "spa_core" / "paper_trading" / "allocator.py",
    ):
        if cand.exists():
            live_sources.append(cand)

    for src in live_sources:
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        for sid in _RATES_DESK_SLEEVE_IDS:
            assert sid not in text, (
                f"{sid} must NOT appear in live allocation source {src.name} "
                f"(rates-desk sleeves are reporting-only, IS_ADVISORY)"
            )


def test_rates_desk_sleeve_classes_have_distinct_ids():
    """Sanity: each sleeve class exposes a sleeve id matching the advisory-separation list (so the
    grep guards above key off the real ids, not stale literals)."""
    seen = set()
    for cls in _RATES_DESK_SLEEVE_CLASSES:
        # the id may be a class attr (sleeve_id / SLEEVE_ID / id) — accept any present form.
        sid = (
            getattr(cls, "sleeve_id", None)
            or getattr(cls, "SLEEVE_ID", None)
            or getattr(cls, "id", None)
        )
        if isinstance(sid, str):
            seen.add(sid)
    # at least one real id resolved AND every resolved id is in the curated list (no surprises).
    assert seen, "expected at least one rates-desk sleeve to expose its id"
    assert seen.issubset(set(_RATES_DESK_SLEEVE_IDS)), (
        f"sleeve ids {seen - set(_RATES_DESK_SLEEVE_IDS)} not in the curated advisory list — "
        f"update the separation guard"
    )
