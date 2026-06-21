# ADR-051: f(x) Protocol — T3 Watchlist

**Status:** PROPOSED  
**Date:** 2026-06-21  

## Context
DeFi deep research found f(x) Protocol Stability Pool:
- APY: 6.17% (organic: wstETH staking + trading fees, no emission inflation)
- TVL: $57.87M (above $5M SPA floor)
- Chain: Ethereum mainnet
- Mechanism: USDC deposited into stability pool, earns yield from wstETH collateral rebalancing

## Why interesting
- 6.17% vs current T1 blended ~4.1%
- Organic yield (not incentives) means it's sustainable
- No SPA exploit history found in rekt.news 301-entry database

## Blockers for T2 inclusion
1. f(x) v2 audit reports NOT publicly accessible — must obtain before any allocation
2. Novel mechanism (fractional reserve + rebase) requires deeper risk modeling
3. Stability pool withdrawal mechanics not fully understood

## Decision
**T3 Watchlist — 0% allocation until:**
- Obtain and review f(x) v2 audit reports
- Understand withdrawal queue mechanics
- Run 30-day paper observation
- Write dedicated risk model for fractional-reserve stablecoins

## Consequences
When the above blockers are cleared → propose ADR to upgrade to T2 (max 10% cap initially).
