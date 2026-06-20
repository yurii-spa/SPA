# ADR-042: Backtest Harness Design

## Status

Accepted (2026-06-21)

> **Numbering note:** This session's decisions were originally drafted as
> ADR-030…035, but those numbers are already taken (ADR-030 Emergency Circuit
> Breakers … ADR-041 Adapter Tier Promotion). The session's six ADRs were
> renumbered to **ADR-042 … ADR-047** to preserve a contiguous, collision-free
> sequence.

## Context

Over many sprints the project accumulated **35+ backtest files** across
`spa_core/strategies/`, `spa_core/shadow/`, and the backtest infra — but the
suite had **never been run end-to-end**. The blocker was *interface
fragmentation*: strategies expose **three mutually incompatible entry points**,
so no single driver could exercise them all:

1. **Native `backtest()`** — strategy owns its own historical loop and returns a
   results object.
2. **`run_day(state, market)`** — single-day step; caller owns the loop and
   threads state.
3. **`simulate_day(...)`** — variant single-day step with a different signature
   and return shape.

Because the interfaces never converged, dead-on-arrival backtest code shipped
repeatedly without validation. We needed one harness that normalizes all three
into a comparable artifact (a daily equity curve) so strategies can be ranked on
the same footing.

## Decision

Introduce an **adapter harness** in [`scripts/run_backtest.py`](../../scripts/run_backtest.py)
(MP-1547) that:

1. **Resolves each strategy through the registry** (`spa_core.`-prefixed) and
   detects which of the three interfaces it implements.
2. **Normalizes every interface to a daily equity curve.** Native `backtest()`
   curves are consumed directly; `run_day` / `simulate_day` strategies are
   wrapped in a harness-owned daily loop that threads state and records equity
   per day.
3. **Drives all strategies over the same synthetic market series** (90-day
   window) so returns, Sharpe, and max-drawdown are directly comparable.
4. **Exits 0 and is read-only** — the harness never touches allocator, risk, or
   execution domains; it only reads strategy code and writes a results artifact.

## Results (90-day synthetic series)

| Strategy | Total return | Notes |
|---|---|---|
| **S7** | **+11.08%** | Best performer (Pendle YT/PT family) |
| **S2** | **+8.98%** | |
| **S0** | **+5.72%** | Baseline stable-lending |

### Key finding — S7 bear-scenario fragility

In the bear scenario S7 returns **−14.28%**. Pendle YT is **market-sensitive**:
its yield-token economics decay sharply when rates/price move against the
position. This is a **risk signal for live trading** — S7's headline APY is the
best in the bull series but it carries the worst tail. This finding directly
motivates **[ADR-044](./ADR-044-bear-market-hedge-strategy.md)** (a dedicated
bear-market hedge), since the existing roster has no instrument that profits, or
even holds flat, when the market turns.

## Consequences

- **Positive:** 35+ backtest files are now runnable and comparable for the first
  time; strategy selection can be evidence-based rather than by-construction.
- **Positive:** Bear-scenario tails are now measurable per strategy — surfaced
  S7's −14.28% drawdown that was previously invisible.
- **Positive:** New strategies must conform to one of the three known interfaces
  to be picked up by the harness, creating soft pressure toward convergence.
- **Negative:** Current results are on **synthetic** data; they validate the
  *plumbing*, not real out-of-sample edge. Walk-forward and Monte-Carlo gates
  (ADR-037, ADR-038) remain mandatory before any paper→live promotion.
- **Neutral:** The three interfaces are normalized, not unified. A future ADR
  may deprecate two of them once strategies migrate.

## References

- MP-1547: Backtest e2e runner
- [ADR-037](./ADR-037-walk-forward-validation.md): Walk-forward validation gate
- [ADR-038](./ADR-038-monte-carlo-robustness.md): Monte Carlo robustness
- [ADR-044](./ADR-044-bear-market-hedge-strategy.md): Bear-market hedge (motivated by S7 −14.28%)
- [`scripts/run_backtest.py`](../../scripts/run_backtest.py)
