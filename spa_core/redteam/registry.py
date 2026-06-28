"""
spa_core/redteam/registry.py — the seeded scenario REGISTRY.

The single place scenarios are registered. ``REGISTRY`` is the canonical one-per-surface set
(≥7 real adversarial scenarios). A scenario is looked up by surface for the rotation scheduler.

stdlib-only · LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict, List

from spa_core.redteam.base import RedTeamScenario, Surface
from spa_core.redteam.scenarios import ALL_SCENARIOS

# The canonical registry — every seeded scenario, in deterministic order.
REGISTRY: List[RedTeamScenario] = list(ALL_SCENARIOS)


def scenarios_for_surface(surface: str) -> List[RedTeamScenario]:
    """Every registered scenario targeting ``surface`` (deterministic order)."""
    return [s for s in REGISTRY if s.surface == surface]


def by_name() -> Dict[str, RedTeamScenario]:
    """Map scenario name → scenario (names are unique)."""
    return {s.name: s for s in REGISTRY}


def covered_surfaces() -> List[str]:
    """The Surface.ALL entries that have at least one registered scenario (deterministic order)."""
    have = {s.surface for s in REGISTRY}
    return [srf for srf in Surface.ALL if srf in have]
