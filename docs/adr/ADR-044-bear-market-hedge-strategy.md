# ADR-044: Bear-Market Hedge Strategy (S31) + Market-Neutral (S32)

## Status

**Proposed** (2026-06-21) — design accepted; strategies not yet implemented.

> Implementation note: as of this ADR the strategy files `s31_*` / `s32_*` do
> **not** exist in `spa_core/strategies/` (only `delta_neutral_susde.py` is
> present). This ADR records the design decision and acceptance criteria;
> status moves to **Accepted** once S31/S32 land and pass the backtest harness.

## Context

The backtest harness (**[ADR-042](./ADR-042-backtest-harness-design.md)**)
revealed that **S7 loses −14.28% in the bear scenario**. S7 is a Pendle-YT
family strategy, and Pendle YT is structurally **market-sensitive** — its
yield-token value decays when rates/price move against the position. The current
roster is long-biased: every strategy assumes carry accrues in a stable or
rising market, and **none profits, or even holds flat, when the market turns
down**. A single regime shift could erase weeks of accrued paper yield.

We need an explicit hedge leg in the strategy universe so the portfolio has a
component whose payoff is *uncorrelated or inversely correlated* with the
long-carry book.

## Decision

Add two new strategies:

- **S31 — Bear-Market Hedge.** Activates when regime detection flags a bear
  market; rotates into capital-preserving / inversely-correlated positions
  (e.g. unwinding market-sensitive YT exposure, shifting to the most defensive
  stable-lending venue, raising the cash buffer toward the RiskPolicy max).
- **S32 — Market-Neutral.** Always-on delta-neutral construction targeting yield
  that is independent of market direction, complementing the existing
  `delta_neutral_susde` building block.

### Regime detection

Bear regime is detected from **two deterministic, on-chain-derived signals** (no
LLM — `monitoring` is an LLM-forbidden domain per CLAUDE.md):

1. **Aave utilization** — elevated/spiking borrow utilization as a stress proxy.
2. **T2 APY trend** — a sustained downward trend in T2 pool APYs (carry
   compression) as a leading indicator of risk-off conditions.

A bear flag is raised only when both signals agree, to avoid whipsaw on
single-signal noise.

### Target

- **Max drawdown < 0.5%** for S31/S32 in the backtest bear scenario — i.e. the
  hedge book should be effectively flat where S7 is −14.28%.
- S31/S32 must pass the ADR-042 harness, then the ADR-037 walk-forward and
  ADR-038 Monte-Carlo gates before any paper→live promotion.

## Consequences

- **Positive:** Gives the portfolio its first genuinely defensive leg; caps the
  bear-scenario tail that S7 exposes.
- **Positive:** Regime detection reuses existing read-only signals (Aave
  utilization, T2 APY series) — no new data dependency.
- **Negative:** A market-neutral book typically yields less in bull regimes;
  S32 is a drag on headline APY during good times (the cost of insurance).
- **Negative / Risk:** Regime-detection false negatives (failing to flag a bear)
  leave the long book unhedged; the two-signal-agreement rule trades
  responsiveness for fewer false positives.
- **Neutral:** S31/S32 remain paper-only and advisory until they clear the same
  promotion gates as every other strategy; `approved=False` from RiskPolicy
  still overrides them.

## References

- [ADR-042](./ADR-042-backtest-harness-design.md): Backtest harness (S7 −14.28% finding)
- [ADR-021](./ADR-021-pendle-yt-t3-classification.md): Pendle YT T3-SPEC advisory-only
- [ADR-039](./ADR-039-drawdown-circuit-breaker.md): Drawdown circuit breaker
- [ADR-040](./ADR-040-strategy-demotion-policy.md): Strategy demotion policy
- `spa_core/strategies/delta_neutral_susde.py` (S32 building block)
