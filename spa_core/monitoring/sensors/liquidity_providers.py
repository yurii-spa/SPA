"""spa_core/monitoring/sensors/liquidity_providers.py — RTMR (ADR-053) exit-liquidity providers.

Honest scope: real slippage-curve DEX depth is hard keyless, so exit depth is approximated by the
pool's on-protocol liquidity (DeFiLlama TVL as a CONSERVATIVE proxy — true withdrawable ≤ TVL). That
is enough to catch a pool DRAINING relative to our position (the liquidity risk that matters); it is
NOT a precise slippage model. Position sizes come from the paper book (`data/current_positions.json`).
``liq_ratio = pool_depth / position_usd``. stdlib-only, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

from spa_core.monitoring.sensors.tvl_providers import tvl_current_providers

_ROOT = Path(__file__).resolve().parents[3]
_POSITIONS = _ROOT / "data" / "current_positions.json"

# our-scope → DeFiLlama slug (the pool whose depth backs that position)
_SLUGS = {"aave_v3": "aave-v3", "compound_v3": "compound-v3", "morpho_blue": "morpho-blue",
          "morpho_steakhouse": "morpho-blue", "spark_susds": "spark", "fluid_fusdc": "fluid",
          "ethena": "ethena-usde"}


def depth_providers(scope_slugs: dict | None = None) -> dict:
    """{scope: {name: callable()->pool_depth_usd}} — DeFiLlama TVL as the conservative depth proxy."""
    scope_slugs = scope_slugs or _SLUGS
    return {scope: tvl_current_providers(slug) for scope, slug in scope_slugs.items()}


def position_sizes() -> dict:
    """{scope: usd} from the paper book's current allocation, or {} if unreadable."""
    try:
        d = json.load(open(_POSITIONS, encoding="utf-8"))
        # current_positions holds deployed capital; the last-rebalance allocation lives in trades.json,
        # but for a live liquidity check the deployed total split across held scopes is enough. Prefer an
        # explicit per-scope map if present; else fall back to the trades.json last allocation.
        for k in ("allocation", "positions", "holdings"):
            v = d.get(k)
            if isinstance(v, dict) and v:
                return {s: float(u) for s, u in v.items() if isinstance(u, (int, float))}
    except Exception:  # noqa: BLE001
        pass
    # fallback: last rebalance target from trades.json
    try:
        tr = json.load(open(_ROOT / "data" / "trades.json", encoding="utf-8"))
        alloc = tr[-1].get("to_allocation", {}) if isinstance(tr, list) and tr else {}
        return {s: float(u) for s, u in alloc.items() if isinstance(u, (int, float))}
    except Exception:  # noqa: BLE001
        return {}


def liquidity_inputs(scope_slugs: dict | None = None):
    """(depth_providers, position_usd) filtered to scopes we actually hold — the sensor's two args."""
    sizes = position_sizes()
    slugs = scope_slugs or _SLUGS
    held = {s: slugs[s] for s in slugs if s in sizes and sizes[s] > 0}
    return depth_providers(held), {s: sizes[s] for s in held}
