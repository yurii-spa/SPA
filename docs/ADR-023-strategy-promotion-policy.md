# ADR-023: Strategy Promotion Policy — Paper → Live

**Date**: 2026-06-12  
**Status**: Accepted  
**Author**: SPA Architect Agent

---

## Context

SPA runs multiple paper trading strategies (S0–S10) in parallel VPortfolios. 
As of v4.73, S7 (Pendle YT+PT Aggressive) is the first strategy to cross 10% APY baseline.
This ADR defines when a strategy is promoted from paper to live allocation.

---

## Decision

### Promotion Gate (all criteria must pass)

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| MIN_DAYS_PAPER | ≥ 14 calendar days | Min observation window |
| SHARPE_RATIO | ≥ 0.80 (30d rolling) | Risk-adjusted return |
| MAX_DRAWDOWN | ≥ -5% (not exceeded) | Kill-switch alignment |
| APY_TARGET | ≥ 7.0% net | Minimum viable yield |
| CALMAR_RATIO | ≥ 1.0 | Return/max-dd quality |
| ADAPTER_HEALTH | All adapters PASS | No failed data feeds |
| CHAIN_CONCENTRATION | Ethereum ≤ 70% | ADR-019 compliance |

### Promotion Process

1. `PromotionEngine.evaluate(strategy_id)` → returns `PROMOTE|HOLD|DEMOTE|KILL`
2. If `PROMOTE`:
   a. Create ADR-{N} entry in DECISIONS.md
   b. Send Telegram alert: "Strategy {id} promoted to live"
   c. Allocator shifts capital from S0 baseline to promoted strategy (5% increments)
   d. Monitor 7-day post-promotion period with tighter kill switch (-3%)

### Demotion Gate

| Criterion | Threshold | Action |
|-----------|-----------|--------|
| SHARPE_RATIO | < 0.0 (rolling 14d) | DEMOTE → back to paper |
| DRAWDOWN | < -10% | KILL → back to S0 baseline |
| ADAPTER_FAILURE | >24h data gap | PAUSE until restored |

### T3 / T3-SPEC Strategies (S7, S8, S10)

Additional constraints for high-risk strategies:
- MAX_ALLOCATION: 30% of total portfolio (T3 cap per ADR-020)
- MIN_DAYS_PAPER: ≥ 30 days (doubled vs T1/T2)
- SHARPE_RATIO: ≥ 1.0 (higher bar)
- Requires explicit USER_APPROVAL in Telegram before first live allocation

### Current Status (2026-06-12)

| Strategy | APY | Days Paper | Status | Est. Promotion |
|----------|-----|------------|--------|----------------|
| S5 Pendle PT Enhanced | 8.5% | 0 | paper | 2026-06-26 (if metrics hold) |
| S7 Pendle YT+PT | 10.1% | 0 | paper (T3, needs 30d) | 2026-07-12 |
| S2 Pendle+Morpho | 7.0% | 0 | paper | 2026-06-26 |

---

## Consequences

- Positive: Clear, deterministic promotion criteria reduces human bias
- Positive: T3 30-day requirement provides safety buffer
- Risk: 30-day wait may miss optimal entry windows for Pendle YT
- Mitigation: Shadow portfolio tracks opportunity cost during wait period

---

## Implementation

`spa_core/strategies/promotion_engine.py` evaluates this policy daily via `cycle_runner.py`.
Criteria stored in `spa_core/config/promotion_config.py` for easy tuning.
