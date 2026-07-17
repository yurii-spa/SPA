"""spa_core/tests/test_investment_os_layer_integration.py — AI Investment OS layer consistency (AAA).

A structural integration guard for the whole product layer: every analyst agent module must exist, be a
ProductAgent with a unique agent_key, and be wired CONSISTENTLY into (a) the health monitor's ANALYSTS
list and (b) the API router's _ANALYSTS map. This catches the most common drift — adding an analyst but
forgetting to register it on the surface or the health monitor (or vice-versa). Not data-dependent.

PURE / no network / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib
import inspect

import pytest

from spa_core.investment_os.harness import ProductAgent
from spa_core.investment_os import health as HEALTH
from spa_core.api.routers import investment_os as ROUTER

# The analyst agent modules (module_name → expected agent_key).
AGENT_MODULES = {
    "stablecoin_yield": "stablecoin_yield",
    "market_regime": "market_regime",
    "reporting": "reporting",
    "red_team": "red_team",
    "liquidity": "liquidity",
    "protocol_risk": "protocol_risk",
    "yield_quality": "yield_quality",
    "onchain": "onchain",
    "quant": "quant",
    "market_structure": "market_structure",
    "chief_investment": "chief_investment",
}


def _agent_class(module_name):
    mod = importlib.import_module(f"spa_core.investment_os.agents.{module_name}")
    classes = [obj for _, obj in inspect.getmembers(mod, inspect.isclass)
               if issubclass(obj, ProductAgent) and obj is not ProductAgent
               and obj.__module__ == mod.__name__]
    assert len(classes) == 1, f"{module_name}: expected exactly 1 ProductAgent subclass, got {classes}"
    return classes[0]


def test_every_agent_module_is_a_product_agent_with_expected_key():
    for module_name, expected_key in AGENT_MODULES.items():
        cls = _agent_class(module_name)
        assert cls.agent_key == expected_key, f"{module_name}: agent_key={cls.agent_key!r} != {expected_key!r}"
        # contract: must have analyze() + run() (run inherited from ProductAgent)
        assert callable(getattr(cls, "analyze", None))
        assert callable(getattr(cls, "run", None))


def test_agent_keys_are_unique():
    keys = [_agent_class(m).agent_key for m in AGENT_MODULES]
    assert len(keys) == len(set(keys)), f"duplicate agent_key: {keys}"


def test_health_monitor_tracks_exactly_these_analysts():
    # health.ANALYSTS must equal the actual agent-key set (no missing, no stale).
    assert set(HEALTH.ANALYSTS) == set(AGENT_MODULES.values()), (
        f"health.ANALYSTS drift: {set(HEALTH.ANALYSTS) ^ set(AGENT_MODULES.values())}")


def test_router_surface_covers_every_analyst():
    # every analyst (except the health meta) must have a router entry pointing at its artifact.
    router_agents = {agent for (_, agent, _) in ROUTER._ANALYSTS.values()}
    missing = set(AGENT_MODULES.values()) - router_agents
    assert not missing, f"analysts missing from the API router: {missing}"


def test_router_artifact_paths_match_agent_keys():
    # each router entry's artifact filename must be <agent_key>.json under investment_os/.
    for slug, (rel_path, agent, _desc) in ROUTER._ANALYSTS.items():
        assert rel_path == f"investment_os/{agent}.json", f"{slug}: {rel_path} != investment_os/{agent}.json"


def test_router_has_index_and_health_and_all_endpoints():
    paths = {r.path for r in ROUTER.router.routes if hasattr(r, "path")}
    assert "/api/investment-os" in paths
    assert "/api/investment-os/health" in paths
    for slug in ROUTER._ANALYSTS:
        assert f"/api/investment-os/{slug}" in paths, f"missing endpoint for {slug}"
