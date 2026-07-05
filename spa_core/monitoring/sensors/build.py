"""spa_core/monitoring/sensors/build.py — RTMR (ADR-053) wire live keyless providers into sensors.

Assembles the deterministic sensor set with real feeds and registers it with the sense-loop. Peg
is wired now (live keyless price quorum, §13.1); tvl/oracle/liquidity are registered once their
providers exist (TVL via DeFiLlama, oracle via Chainlink RPC, liquidity via DEX depth) — follow-up.
LLM-forbidden, deterministic wiring only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring.sensors.peg import PegSensor
from spa_core.monitoring.sensors.providers import price_providers_for, supported_assets

# stablecoins with ENOUGH keyless price sources for a real quorum (>= min_quorum).
# USDE/SUSDE have too few CEX listings for a price quorum → monitor them ON-CHAIN via the
# oracle/DEX sensor (follow-up), not this CEX price quorum (else they fail-closed forever).
_DEFAULT_ASSETS = ["USDC", "USDT", "DAI"]
_MIN_SOURCES = 3


def build_peg_sensor(assets: list | None = None) -> PegSensor:
    assets = assets or _DEFAULT_ASSETS
    providers = {}
    targets = {}
    for a in assets:
        provs = price_providers_for(a)
        if len(provs) >= _MIN_SOURCES:   # only wire assets with a real multi-source quorum
            providers[a] = provs         # scope = asset symbol (e.g. "USDC")
            targets[a] = 1.0             # USD-pegged
    return PegSensor(providers, targets)




# protocols to watch for TVL collapse → DeFiLlama slugs
_TVL_SLUGS = {"aave-v3": "aave_v3", "compound-v3": "compound_v3", "morpho-blue": "morpho_blue",
              "ethena-usde": "ethena", "sky-lending": "sky", "spark": "spark", "fluid": "fluid"}


def build_tvl_sensor(slugs: dict | None = None):
    from spa_core.monitoring.sensors.tvl import TvlSensor
    from spa_core.monitoring.sensors.tvl_providers import tvl_current_providers, tvl_24h_ago
    slugs = slugs or _TVL_SLUGS
    current, history = {}, {}
    for slug, scope in slugs.items():
        current[scope] = tvl_current_providers(slug)
        history[scope] = (lambda sl=slug: tvl_24h_ago(sl))   # lazy — fetched at poll, not build
    return TvlSensor(current, history)




def build_oracle_sensor(assets: list | None = None):
    from spa_core.monitoring.sensors.oracle import OracleSensor
    from spa_core.monitoring.sensors.oracle_providers import oracle_feeds
    return OracleSensor(oracle_feeds(assets))




def build_liquidity_sensor():
    from spa_core.monitoring.sensors.liquidity import LiquiditySensor
    from spa_core.monitoring.sensors.liquidity_providers import liquidity_inputs
    depth, sizes = liquidity_inputs()
    return LiquiditySensor(depth, sizes)


def register_default_sensors() -> list:
    """Register the live-wired sensors with the sense-loop. Returns the registered source names."""
    from spa_core.monitoring.sense_loop import register_sensor, registered_sources
    register_sensor(build_peg_sensor())
    import sys as _sys
    for _name, _fn in (("tvl", build_tvl_sensor), ("oracle", build_oracle_sensor),
                       ("liquidity", build_liquidity_sensor)):
        try:
            register_sensor(_fn())
        except Exception as _e:  # noqa: BLE001 — optional sensor; log WHY it was skipped, don't hide it
            print(f"rtmr build: {_name} sensor skipped: {type(_e).__name__}: {_e}", flush=True)
    # TODO(S10.3 follow-up): register tvl/oracle/liquidity once their providers are wired.
    return registered_sources()
