# 44 — Research: First 20 Strategies (§41)

**Status: STUB.** This document is a Priority-3 placeholder listing the first 20 strategies to
research, grouped by domain and product line. Each entry is a one-line rationale (why research
first / product line / capital tier). **No APY or TVL numbers are asserted here** — any such figure
requires verification and belongs in a Strategy Card at MVP 2-3, with an evidence level (L0–L6,
`docs/37`).

**Scope discipline.** Research roster only. Listing a strategy here does **not** approve it; every
candidate must pass the Yield Lab lifecycle (`docs/07`) — yield-source verification, protocol /
stablecoin review, liquidity review, Risk Scoring v2, red-team, paper-test, human approval — before
any live use. Capital preservation first (charter).

**Cross-references:** `docs/07_yield_lab_lifecycle.md`, `docs/33_yield_thesis_map.md`,
`docs/34_capital_tiers.md`, `docs/43_dangerous_strategies.md`, existing `spa_core/strategy_lab/`.

## First 20 strategies to research (one line each — no numbers)

### Stablecoin — Conservative (Preserve / Core)
1. **T1 lending (blue-chip money markets)** — deepest, most-audited base; anchor for lower tiers.
2. **Tokenized T-bill / RWA cash floor** — real risk-free-rate floor; benchmark to beat.
3. **Blue-chip savings vaults (audited, transparent)** — passive core yield with clear yield source.
4. **Short-duration stable LP (correlated stable pairs)** — low-IL liquidity provision at core tier.

### Stablecoin — Balanced (Core / Enhanced)
5. **Curated lending markets (isolated, whitelisted collateral)** — enhanced rate, bounded collateral.
6. **PT fixed-rate (principal token to maturity)** — deterministic fixed carry; maturity-scoped.
7. **Diversified stable LP with fee capture** — balanced yield from real trading fees.
8. **Staked-stable / savings-rate wrappers (transparent backing)** — yield from disclosed mechanism.

### Stablecoin — Enhanced (Enhanced)
9. **Basis / funding carry (delta-neutral, hedged)** — funding-rate harvest with explicit hedge.
10. **Curated credit vaults (disclosed underwriters)** — higher rate with named counterparties.
11. **Levered PT carry (bounded, liquidation-modeled)** — enhanced carry only with a liquidation model.
12. **Cross-venue stable arbitrage sleeves** — spread capture; capacity/liquidity constrained.

### Stablecoin — Aggressive (Max / Experimental)
13. **Structured yield sleeves (tail-aware)** — higher yield only with full tail analysis (isolated).
14. **Emerging-protocol lending (post-audit, size-capped)** — early access with strict caps.

### BTC — Cycle / Yield (decision-support)
15. **BTC capital-cycle rotation (accumulate / ladder)** — decision-support cycle framework.
16. **Conservative BTC lending (multi-custodian, low-utilization aware)** — honest low base yield.
17. **BTC basis / funding (hedged, exchange-diversified)** — carry with counterparty diversification.

### ETH — Staking / Yield (decision-support)
18. **Plain LST staking (stETH / rETH)** — base ETH yield, closest-to-peg exposure.
19. **Hedged ETH (LST + short perp, β≈0)** — market-neutral ETH yield sleeve.
20. **LRT / restaking (isolated, directional)** — higher yield with explicit depeg/slashing scrutiny.

TODO: expand at MVP 2-3 stage. (Each entry to be expanded into a full Strategy Card at MVP 2-3.)
