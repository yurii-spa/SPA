"""spa_core/monitoring/asset_map.py — RTMR (ADR-053) protocol → underlying stablecoin.

The peg / oracle sensors emit ASSET-scoped signals ("USDC", "USDT", "DAI"), but the cycle
allocates to PROTOCOLS (aave_v3, compound_v3, …). This map routes an asset de-risk (e.g. a USDC
depeg) to every protocol whose principal is that asset, so the posture gate can clamp them.
Deterministic, stdlib-only, LLM-forbidden. Best-effort — a protocol not listed is left unmapped
(its own protocol-scoped posture, from tvl/liquidity, still applies).
"""
# LLM_FORBIDDEN
from __future__ import annotations

# protocol (allocation key) → principal stablecoin the position is denominated in
_PROTOCOL_ASSET: dict[str, str] = {
    # USDC lending markets
    "aave_v3": "USDC", "aave_arbitrum": "USDC", "aave_v3_optimism": "USDC",
    "aave_v3_polygon": "USDC", "aave_v3_base": "USDC", "compound_v3": "USDC",
    "morpho_blue": "USDC", "morpho_steakhouse": "USDC", "morpho_blue_base": "USDC",
    "fluid_fusdc": "USDC", "moonwell_base": "USDC", "extra_finance_base": "USDC",
    # DAI / USDS
    "sdai": "DAI", "spark_susds": "DAI", "spark": "DAI",
    # USDe / Ethena
    "susde": "USDE", "ethena": "USDE", "pendle_pt_susde": "USDE",
    # others (own peg, monitored separately or unmapped)
    "frax": "FRAX", "sfrax": "FRAX", "scrvusd": "CRVUSD", "stusd": "USD",
    "ondo_usdy": "USDY", "wusdm": "USDM", "maple": "USDC",
}


def asset_of(protocol: str) -> str | None:
    """Principal stablecoin for a protocol scope, or None if unmapped."""
    return _PROTOCOL_ASSET.get(str(protocol))
