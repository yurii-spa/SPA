"""spa_core/defi_engine — DeFi Engine vNext, Phase 1 foundation (ADR-532).

A DERIVED layer over the three package books. It owns no position, no tier and no number of its
own: every value it publishes is computed from an existing canonical source and names that
source. It never gates execution and never moves capital (invariant #1: RiskPolicy v1.0 stays
the only hard gate); its verdicts are advisory and are published for the owner, the CIO and the
site pipeline.

Modules
-------
``books``          the three books (Conservative / Balanced / Aggressive) read into one shape
``tiers``          the single tier authority (``adapters.tier_map``) + a census of every copy
``mechanics``      the second risk axis: what a position DOES (supply, RWA credit, synthetic…)
``apy_contract``   one named definition per APY quantity, gross and net
``exit_model``     exit latency / exit liquidity per position and per book
``loss_budget``    each package's published drawdown budget vs measured drawdown and its gate
``coverage``       which monitoring sensor covers which held position
``passport``       the Position Passport — a derived per-position view, never a store
``engine``         assembles everything into ``data/defi_engine/{status,passports}.json``

LLM_FORBIDDEN, stdlib only, deterministic for fixed inputs (``now`` is injected).
"""
# LLM_FORBIDDEN

SCHEMA_VERSION = "defi-engine-status/1"
PASSPORT_SCHEMA_VERSION = "position-passport/1"
