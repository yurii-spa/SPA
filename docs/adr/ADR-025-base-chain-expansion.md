# ADR-025: Base Chain Expansion

**Status:** Accepted  
**Date:** 2026-06-12  
**Author:** SPA Architect Agent  
**Sprint:** v4.78  
**Related:** ADR-019 (T2 cap), ADR-021 (Pendle YT T3-SPEC), ADR-002 (go-live rule)

---

## Context

SPA operates on Ethereum mainnet with 12 adapters. Base (Coinbase L2) offers:
- Lower gas costs (100x reduction vs mainnet)
- Growing DeFi ecosystem: Aave V3 (~$400M TVL), Aerodrome (Curve-fork, ~$800M TVL)
- Native USDC (Circle's official Base USDC, no bridge risk for USDC itself)
- Morpho Blue on Base (~$200M TVL)

Paper trading is running. Go-live target 2026-08-01. Base expansion adds yield diversification.

### Why Now

As of Sprint v4.78, T1 adapters on Ethereum mainnet dominate the portfolio with structural ~70–75% concentration. Base adapters provide yield diversification with lower gas overhead. Phase 1 (paper monitoring only) carries zero capital risk and generates 30 days of comparative APY data before any allocation decision.

---

## Decision

**Phase 1 (paper only, 2026-06-13 to 2026-07-12):**
- Add Aave V3 Base as T2 adapter (read-only APY feed)
- Add Morpho Blue Base as T2 adapter (read-only APY feed)
- No capital allocation — monitoring only

**Phase 2 (after go-live 2026-08-01, if evidence supports):**
- Maximum 20% of portfolio across all Base adapters combined (L2 concentration cap)
- Bridge via official Coinbase Base Bridge or LayerZero
- Kill-switch: if Base gas > 10 Gwei for 3+ days → reduce to 0%

**Not in scope:**
- Aerodrome LP positions (impermanent loss risk, requires IL modeling first)
- Pendle on Base (TVL < $50M as of research date)
- Leverage strategies on Base

---

## Risk Analysis

| Risk | Mitigation |
|------|-----------|
| L2 bridge risk | Max 20% Base exposure; read-only phase 1 |
| Smart contract risk | Aave/Morpho audited, same code as mainnet |
| Sequencer downtime | <30 min typical; daily cycle not affected |
| Gas spike | Kill-switch at 10 Gwei threshold |
| Liquidity risk | TVL floor $5M enforced by RiskPolicy (same as mainnet) |

---

## Consequences

- ADAPTER_REGISTRY expands from 12 → 14 adapters (aave-v3-base, morpho-blue-base)
- `risk_policy.py` adds `BASE_CHAIN_CAP = 0.20` constant (ADR-025)
- `cycle_runner.py`: read-only fetch only; no allocation until Phase 2 approval
- USER_APPROVAL required before any live Base allocation (Telegram button: APPROVE_BASE)
- Changelog in `RiskConfig` updated with ADR-025 reference

---

## Implementation Notes

- Both Base adapters inherit from existing `AaveV3Adapter` and `MorphoBlueAdapter` patterns
- Chain field: `chain = "base"` in Position dataclass
- `PortfolioState.chain_allocation_pct("base")` already works via existing multi-chain logic
- `BASE_CHAIN_CAP` enforced at allocator level (same pattern as `max_total_t2_allocation`)
- Phase 2 activation requires explicit Owner approval and 30-day paper evidence

---

## Review

- Owner approval required before Phase 2 activation
- Checkpoint: after 30 days paper evidence (2026-07-12)
- Next ADR if Base allocation approved: ADR-026 (Base allocator enforcement)

---

## Approval Criteria (для Phase 2)

- [ ] Phase 1 complete: 30 days read-only monitoring (by 2026-07-12)
- [ ] Base Aave V3 APY competitive vs mainnet (≥ 3.0%)
- [ ] Base Morpho Blue APY competitive vs mainnet (≥ 5.0%)
- [ ] Bridge infrastructure tested on testnet
- [ ] Owner explicit approval (Telegram: APPROVE_BASE)

---

## Rollback

Phase 1 rollback: remove adapters from ADAPTER_REGISTRY, delete `BASE_CHAIN_CAP` constant.  
Phase 2 rollback: set all Base adapter allocations to 0%, no bridge transactions needed.

---

## Related Decisions

- **ADR-019** — T2 total cap 50%; Base T2 adapters fall under this cap
- **ADR-002** — Go-live transfer rule; Phase 2 cannot start before go-live
- **ADR-021** — Pendle YT T3-SPEC; Pendle on Base explicitly out of scope
- **ADR_001** — Initial risk policy (T1/T2 caps origin)
