# ADR-031: Portfolio Rebalancing Policy

**Status:** Accepted
**Date:** 2026-06-12
**Related:** ADR-002 (go-live), ADR-024 (Gnosis Safe), MP-568 (rebalancer.py)

## Context

After go-live, the portfolio holds real USDC across multiple DeFi protocols.
Yield rates drift daily. Without active rebalancing, the portfolio drifts from
optimal allocation, reducing expected APY and increasing concentration risk.

We need a clear policy for:
- When to rebalance (trigger conditions)
- How much to rebalance (sizing)
- Cost constraints (gas + slippage)

## Decision

### Trigger Conditions (any of these → rebalance)

**RT-01: Drift Trigger (primary)**
Any single adapter drifts >5% from target weight.
Example: target aave_v3=30%, current=36% → drift=6% → TRIGGER

**RT-02: APY Opportunity**
A strategy regime change occurs (MarketRegimeDetector reports new regime) AND
potential APY gain from rebalancing > 50 bps.

**RT-03: Risk Gate**
DailyLimitsChecker DL-03 fires (concentration >40%) → immediate rebalance
to reduce concentration regardless of cost.

**RT-04: Calendar**
Every 7 days if any adapter has drifted >2% (maintenance rebalance).

### Sizing Rules

- Maximum single move: 10% of portfolio equity per adapter
- Maximum total moves in one rebalance: 30% of equity
- Minimum move size: $500 (avoid dust transactions)
- T3 adapters: max rebalance in = 5% per event

### Cost Constraints

- ETH mainnet: only rebalance if gas cost < 0.5% of move size
- Base chain: gas threshold from ADR-025 BaseGasMonitor (10 Gwei)
- Total estimated cost (gas + slippage): cap at 20 bps of move size
- If cost > cap: defer to next daily cycle

### Execution Phases

**Phase 0 (now → 2026-07-01):** Paper mode — record actions, no execution
**Phase 1 (2026-07-01 → 2026-08-01):** Gnosis Safe testnet dry-run
**Phase 2 (2026-08-01+):** Live execution via Gnosis Safe 2-of-3 multisig

### Forbidden Moves

- Never rebalance moonwell_base (SUSPENDED per ADR-026)
- Never increase T3-SPEC (susde, pendle) above 10% in a single event
- Never execute during Emergency Breakers HALT (ADR-030)

## Consequences

**Positive:**
- Systematic drift control reduces unintended risk concentration
- APY maintained closer to optimum between strategy updates
- Clear paper-mode baseline before live execution

**Negative:**
- Gas costs reduce net APY by estimated 5-15 bps/year
- Frequent rebalancing adds complexity to audit trail

## Implementation

See `spa_core/paper_trading/rebalancer.py` for implementation.
Triggers RT-01..RT-04 checked in `cycle_runner.py` Step 4 (post-allocation).
