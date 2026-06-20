# ADR-039: Drawdown Circuit Breaker

## Status
Accepted

## Context
RiskPolicy v1.0 (ADR-001) already mandates a kill switch when portfolio drawdown
reaches 5%. However, the existing kill switch fires only at the hard limit and
does not provide graduated responses — the system either continues trading
normally or halts entirely.

In practice, drawdown risk accumulates progressively. By the time the 5%
hard-stop is reached, the optimal moment to reduce exposure may already have
passed. A circuit breaker framework with graduated "trip levels" reduces expected
loss before the hard-stop is reached while avoiding unnecessary halts during
normal volatility.

## Decision

### Circuit Breaker Levels
| Level   | Trigger Condition              | Action                                         |
|---------|-------------------------------|------------------------------------------------|
| YELLOW  | Portfolio drawdown ≥ 2%        | Log alert; no position changes; daily Telegram warning |
| ORANGE  | Portfolio drawdown ≥ 3%        | Freeze new positions; existing positions held; Telegram alert |
| RED     | Portfolio drawdown ≥ 4%        | Reduce all T2/T3 positions to zero; hold T1 only |
| BLACK   | Portfolio drawdown ≥ 5%        | Full kill switch (existing RiskPolicy behaviour) |

"Portfolio drawdown" is measured from the rolling peak of `equity_curve_daily.json`
over the trailing 30 days (consistent with `drawdown_analytics.py` MP-115).

### Cooldown and Reset
- A circuit breaker **does not reset automatically**. Recovery requires equity to
  return to within 0.5% of the pre-trigger peak (the "reset level").
- Concurrent trips at multiple levels: the most severe level governs.
- ORANGE and above trigger an immediate entry in `data/risk_policy_blocks.json`
  (ring-buffer 100, existing infrastructure).

### Scope
- Circuit breaker logic resides in `spa_core/risk/circuit_breaker.py`.
- It is invoked by `cycle_runner.py` **before** `StrategyAllocator`, so
  allocator never sees prohibited states.
- `approved=False` from the circuit breaker cannot be overridden by any strategy
  or agent (same restriction as RiskPolicy).

### Paper-Trading Behaviour
During the paper-trading period (prior to go-live), circuit breaker levels YELLOW
and ORANGE trigger alerts only. RED and BLACK behave exactly as in production
(positions adjusted in the virtual portfolio). This ensures the mechanism is
exercised before real capital is involved.

## Consequences

### Positive
- Provides graduated risk response instead of binary halt.
- Reduces expected drawdown magnitude in tail scenarios.
- Gives the fund manager an audited warning trail before hard stop.

### Negative / Trade-offs
- ORANGE freeze could persist during a temporary dip, causing opportunity cost.
- Adds complexity to the daily cycle; requires careful sequencing with existing
  RiskPolicy gate to avoid double-blocking.
- Reset logic must be conservative enough to avoid premature re-entry.

## Implementation

Primary module: `spa_core/risk/circuit_breaker.py`

```
class DrawdownCircuitBreaker:
    LEVELS = {
        "YELLOW": 0.02,
        "ORANGE": 0.03,
        "RED":    0.04,
        "BLACK":  0.05,
    }
    def check(self, equity_curve: list[dict]) -> CircuitBreakerState: ...
    def is_approved(self, state: CircuitBreakerState) -> bool: ...
    def get_level(self, state: CircuitBreakerState) -> str: ...
```

`CircuitBreakerState` includes: `level` (NONE/YELLOW/ORANGE/RED/BLACK),
`current_drawdown_pct`, `peak_equity`, `approved`, `action_required`.

State written to `data/circuit_breaker_state.json` (atomic write) after each
daily cycle.

## References
- ADR-001 / RiskPolicy v1.0 (original kill switch definition)
- ADR-030 (Emergency Circuit Breakers — high-level policy)
- `spa_core/risk/circuit_breaker.py`
- `spa_core/paper_trading/drawdown_analytics.py` (MP-115)
- `data/risk_policy_blocks.json`
