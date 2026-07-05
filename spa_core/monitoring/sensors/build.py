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


def register_default_sensors() -> list:
    """Register the live-wired sensors with the sense-loop. Returns the registered source names."""
    from spa_core.monitoring.sense_loop import register_sensor, registered_sources
    register_sensor(build_peg_sensor())
    # TODO(S10.3 follow-up): register tvl/oracle/liquidity once their providers are wired.
    return registered_sources()
