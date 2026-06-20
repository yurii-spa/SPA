# ADR-046: Multi-Chain Expansion Strategy

## Status

Accepted (2026-06-21)

## Context

Base chain support was added in v4.79 ([ADR-025](./ADR-025-base-chain-expansion.md),
[ADR-026](./ADR-026-base-chain-protocols-v2.md)), and S13 introduced multi-chain
yield arbitrage ([ADR-027](./ADR-027-s13-multi-chain-yield-arbitrage.md)). Two
further L2s — **Arbitrum** and **Optimism** — host mature lending and DEX
protocols that offer yield not reachable from Ethereum mainnet or Base alone.
Expanding the read-only adapter universe to these chains widens the opportunity
set the allocator and S13 can see.

Cross-chain expansion adds risk that mainnet-only operation does not: **bridge
risk** (moving capital between chains) and **per-chain gas variability**.

## Decision

Add **read-only adapters** for Arbitrum and Optimism protocols:

| Chain | Protocol | Adapter file |
|---|---|---|
| Arbitrum | Aave V3 | `spa_core/adapters/aave_arbitrum_adapter.py` |
| Arbitrum | Radiant | `spa_core/adapters/radiant_arbitrum_adapter.py` |
| Arbitrum | GMX (GLP) | `spa_core/adapters/gmx_glp_arbitrum_adapter.py` |
| Optimism | Aave V3 | `spa_core/adapters/aave_v3_optimism_adapter.py` |
| Optimism | Velodrome | `spa_core/adapters/velodrome_optimism_adapter.py` |

### Tiering

**All cross-chain adapters are T2 until proven**, regardless of how the same
protocol is tiered on mainnet. Rationale: a protocol's mainnet maturity does not
transfer to its L2 deployment — the L2 contracts, liquidity depth, and oracle
setup are distinct and must earn their own track record. Promotion to T1 follows
the standard ADR-041 criteria evaluated **on that chain's deployment**.

### Risk controls

1. **Bridge risk** — capital that must cross a bridge to reach a position is
   treated as carrying incremental risk; bridge exposure is monitored and
   bounded. (S13's cross-chain arbitrage already accounts for bridge cost/latency
   per ADR-027.)
2. **Gas monitoring** — per-chain gas is monitored (Base already has a gas
   monitor, `com.spa.base_gas_monitor`); Arbitrum/Optimism gas is tracked so the
   allocator does not chase yield that net gas erodes.
3. **Read-only domain** — these adapters live in `spa_core/adapters/`
   (read-only); they never write to the execution domain and remain pure-stdlib.

## Consequences

- **Positive:** Expands the yield surface to Arbitrum and Optimism; gives S13
  more cross-chain arbitrage legs.
- **Positive:** Uniform T2-until-proven rule prevents the false-comfort of
  importing mainnet tier into a fresh L2 deployment.
- **Negative / Risk:** Bridge risk is a new loss vector (bridge hacks have been
  among the largest DeFi exploits); bounded but not eliminated.
- **Negative:** More chains = more gas surfaces to monitor and more RPC/feed
  dependencies to keep fresh.
- **Neutral:** GMX GLP and Velodrome are not pure stablecoin-lending; their
  inclusion is for monitoring/optionality and is gated by RiskPolicy's APY and
  TVL bounds like any other pool.

## References

- [ADR-025](./ADR-025-base-chain-expansion.md): Base chain expansion (v4.79)
- [ADR-026](./ADR-026-base-chain-protocols-v2.md): Base protocols v2 / suspensions
- [ADR-027](./ADR-027-s13-multi-chain-yield-arbitrage.md): S13 multi-chain arbitrage
- [ADR-041](./ADR-041-adapter-tier-promotion.md): Tier promotion (applied per-chain)
- `com.spa.base_gas_monitor` launchd job (gas-monitoring precedent)
