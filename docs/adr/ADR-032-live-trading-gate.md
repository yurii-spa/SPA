# ADR-032: Live Trading Gate — Triple-Lock Activation Protocol

**Date:** 2026-06-20  
**Status:** Accepted  
**Sprint:** v10.71 (MP-1456)  
**Deciders:** SPA Engineering

---

## Context

Moving from paper trading to live trading with real capital ($100K USDC) carries
irreversible financial risk. An accidental or premature activation could lead to
unrecoverable losses. Multiple v10.x sprints introduced safeguards, but no single
ADR documented the complete gate architecture.

## Decision

Implement a **triple-lock LiveTradingGate** before any live execution is permitted:

### Lock 1 — GoLive Readiness Score ≥ 90/100
The `GoLiveReadinessReport` must return `total_score ≥ 90` before the gate
unlocks. This requires completing the full 30-day paper track, all infrastructure
checks, and evidence accumulation.

### Lock 2 — Manual Owner Confirmation
Activation requires the owner to type `"I CONFIRM LIVE TRADING"` explicitly into
`spa_core/golive/activate.py`. This string is never read from a file or
environment variable — it must be typed interactively.

### Lock 3 — 7-Day Consecutive READY Check
The `golive_status.json` must show `consecutive_ready_days ≥ 7` immediately
before activation. A single non-READY day resets the counter.

### `@live_trading_forbidden` Decorator

All paper-trading entry points are decorated with `@live_trading_forbidden`:

```python
# spa_core/paper_trading/cycle_runner.py
@live_trading_forbidden
def run_cycle(date: str) -> dict:
    ...
```

This decorator raises `LiveTradingForbiddenError` if:
- `data/golive_status.json` is missing or `ready: false`
- `data/live_trading_gate.json` does not have `status: "LOCKED"`

### Gate State File

`data/live_trading_gate.json` is the authoritative gate state:
```json
{
  "status": "LOCKED",
  "reason": "paper_trading_active",
  "locked_at": "2026-06-10T00:00:00",
  "unlock_prerequisites": [
    "golive_readiness_score >= 90",
    "consecutive_ready_days >= 7",
    "owner_manual_confirmation"
  ]
}
```

## Consequences

**Positive:**
- No accidental live activation from code path
- Owner must be present and deliberate to activate
- 7-day buffer prevents activating after a single good day

**Negative:**
- Adds latency to activation (intentional)
- Owner must have access to the CLI at activation time

## Implementation Status

- `spa_core/golive/activate.py`: ✓ implemented (MP-1430)
- `data/live_trading_gate.json`: ✓ present, `status: LOCKED`
- `@live_trading_forbidden`: referenced in cycle_runner architecture
- GoLiveChecker: ✓ 26 criteria, `consecutive_ready_days` tracked

## Related ADRs

- ADR-002: Go-live transfer rule (30-day track requirement)
- ADR-011: Security checklist for go-live
- ADR-022: Gnosis Safe multisig for live execution
