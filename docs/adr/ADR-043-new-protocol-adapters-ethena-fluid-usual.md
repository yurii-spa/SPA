# ADR-043: New Protocol Adapters — Ethena / Fluid / Usual

## Status

Accepted (2026-06-21)

## Context

The current allocation universe is dominated by low-APY T1 lending (Aave ~3.5%,
Compound ~4.8%). To improve the risk-adjusted yield ceiling without abandoning
the stablecoin mandate, we need additional **higher-APY sources** that are still
stablecoin-denominated and have credible TVL / audit profiles.

Three protocols were selected for read-only adapter integration (MP-1227):

- **Ethena sUSDe** — delta-neutral synthetic-dollar yield.
- **Fluid (Instadapp) USDC** — lending vault.
- **Usual USD0++** — RWA-backed stablecoin yield.

A recurring failure mode for new feeds is **single-source brittleness**: when a
protocol's own API rate-limits or goes down, the adapter returns stale or empty
data and the cycle silently degrades.

## Decision

Add three new **T2** adapters, each with a **layered fallback** APY/TVL feed:

```
direct protocol API  →  DeFiLlama yields  →  last cached value
```

The adapter tries the protocol's native API first (freshest, protocol-specific
fields), falls back to DeFiLlama on error/timeout, and finally serves the last
cached value rather than emitting a gap. Anomalous reads are flagged rather than
silently trusted.

| Adapter | File | Tier | Live APY (at integration) |
|---|---|---|---|
| Ethena sUSDe | `spa_core/adapters/ethena_susde_adapter.py` | T2 | **3.50%** |
| Fluid USDC | `spa_core/adapters/fluid_usdc_adapter.py` | T2 | **6.22%** |
| Usual USD0++ | `spa_core/adapters/usual_usd0pp_adapter.py` | T2 | **2.27%** |

All three are registered in `ADAPTER_REGISTRY`
(`spa_core/adapters/__init__.py`) as `T2`. With these additions the registry now
holds **22 active adapter tuples** (Aave/Compound/Morpho T1 core, plus the T2/T3
universe). All three start `research_only=True` per **[ADR-041](./ADR-041-adapter-tier-promotion.md)**
(New Adapter Default) and require a 30-day clean paper track before becoming
allocation-eligible.

### Tier rationale

Each meets the T2 bar (≥ $100M TVL, ≥ 1 audit) but none clears T1's 2-year /
$500M / instant-exit bar — Ethena's 7-day unstake cooldown alone disqualifies it
from T1. Ethena and Usual carry peg/RWA risk that is gated at the adapter level
(peg gate, anomaly flag) consistent with the read-only domain contract.

## Consequences

- **Positive:** Adds a 6.22% (Fluid) source materially above the T1 lending
  baseline, improving the achievable yield frontier.
- **Positive:** Layered fallback eliminates the single-source gap failure mode;
  a downed protocol API degrades to DeFiLlama/cache instead of a data hole.
- **Positive:** All three are pure-stdlib, read-only, and conform to the adapter
  interface — no execution-domain coupling.
- **Negative:** Usual USD0++ (2.27%) currently yields below several T1 options;
  it is integrated for optionality/RWA diversification, not immediate allocation.
- **Negative / Risk:** Ethena and Usual introduce peg-break tail risk; mitigated
  by `research_only=True`, T2 caps (ADR-019), and adapter peg gates.
- **Neutral:** Promotion to `research_only=False`, and any future T2→T1 move,
  follows the deterministic criteria in ADR-041.

## References

- MP-1227: Ethena / Fluid / Usual T2 adapters
- [ADR-041](./ADR-041-adapter-tier-promotion.md): Adapter tier promotion criteria
- [ADR-019](./ADR-019-t2-cap-increase.md): T2 total cap = 50%
- [ADR-028](./ADR-028-oracle-price-diversification.md): Oracle/price diversification
- `spa_core/adapters/__init__.py` (`ADAPTER_REGISTRY`)
