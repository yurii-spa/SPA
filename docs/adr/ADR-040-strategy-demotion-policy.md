# ADR-040: Strategy Demotion Policy (extends ADR-023)

## Status
Accepted

## Context
ADR-023 (Strategy Promotion Policy) defines the conditions under which a strategy
may be promoted from "candidate" to "active" in the tournament. However, it does
not define what happens after promotion: a strategy may be promoted based on
strong early performance but later deteriorate due to regime change, data staleness,
or parameter decay.

Without a formal demotion policy, underperforming strategies remain in the active
pool indefinitely, dragging down portfolio performance and consuming allocation
budget that could be directed to superior strategies.

This ADR extends ADR-023 by defining the symmetric demotion path.

## Decision

### Demotion Triggers (any one sufficient)
| Trigger                                | Threshold                                |
|----------------------------------------|------------------------------------------|
| Rolling 30-day Sharpe (OOS)            | < 0.3 for 14 consecutive days            |
| Rolling 30-day drawdown                | > 8% (below RED circuit breaker level)  |
| Tournament ranking                     | Bottom 2 strategies for 30 consecutive days |
| Data source failure                    | Primary adapter unavailable > 72 hours  |
| WFV re-evaluation failure              | OOS Sharpe < 0.8 on quarterly re-run    |
| Manual override by fund manager        | Recorded in ADR log with reason         |

### Demotion States
```
ACTIVE → PROBATION → DEMOTED → ARCHIVED
```

- **PROBATION:** Strategy meets one demotion trigger. Allocation weight halved.
  State logged. Owner notified via Telegram. 14-day recovery window.
- **DEMOTED:** Strategy on probation fails to recover within 14 days. Allocation
  set to 0. Strategy remains in tournament for monitoring but receives no capital.
- **ARCHIVED:** Strategy demoted for > 60 days without recovery. Removed from
  active tournament. Can be re-submitted as a new candidate only after re-passing
  ADR-037 WFV and ADR-038 MC gates.

### Recovery from PROBATION
A strategy on PROBATION may return to ACTIVE if it meets ALL of the following
within the 14-day window:
1. Rolling 30-day Sharpe recovers to ≥ 0.6.
2. Tournament rank exits bottom 2.
3. No new demotion triggers fire.

### Re-entry after ARCHIVED
Archived strategies may be re-submitted after:
1. Parameter re-optimisation (documented in strategy file header).
2. Fresh WFV pass (ADR-037) with updated data.
3. Fresh MC pass (ADR-038).
4. Fund manager approval recorded in KANBAN.json.

### Quarterly Re-evaluation
All ACTIVE strategies undergo WFV re-evaluation every 90 days. Failure
automatically places the strategy in PROBATION regardless of current tournament
rank.

## Consequences

### Positive
- Keeps the active strategy pool performant through continuous culling.
- Provides a structured, auditable path for strategy lifecycle management.
- Prevents tournament from locking in early winners that no longer outperform.

### Negative / Trade-offs
- 14-day probation window may be too short in low-frequency, high-volatility
  markets where a single bad period recovers naturally.
- Archived strategies lose all context unless fund manager preserves parameter
  snapshots manually.
- Increases operational overhead: demotion events require Telegram alert,
  KANBAN update, and optional ADR annotation.

## Implementation

Primary module: `spa_core/strategies/demotion_engine.py`

```
class DemotionEngine:
    def evaluate(self, strategy_id: str, metrics: StrategyMetrics) -> DemotionState: ...
    def apply_demotion(self, strategy_id: str, state: DemotionState) -> None: ...
    def check_recovery(self, strategy_id: str, metrics: StrategyMetrics) -> bool: ...
```

State persisted in `data/strategy_demotion_log.json` (ring-buffer 200, atomic
write). Daily cycle calls `DemotionEngine.evaluate()` after
`tournament_evaluator.py`.

## References
- ADR-023 (Strategy Promotion Policy — extended by this ADR)
- ADR-037 (Walk-Forward Validation — prerequisite for re-entry)
- ADR-038 (Monte Carlo Robustness — prerequisite for re-entry)
- ADR-039 (Drawdown Circuit Breaker — complementary risk layer)
- `spa_core/strategies/demotion_engine.py`
- `spa_core/strategies/strategy_registry.py`
- `data/strategy_demotion_log.json`
