# ADR-038: Monte Carlo Robustness Testing for Strategy Validation

## Status
Accepted

## Context
Walk-forward validation (ADR-037) tests a strategy on historical OOS windows
but cannot quantify the uncertainty of those estimates. A strategy may pass
WFV with a marginally acceptable OOS Sharpe of 0.82 while having a 30%
probability of delivering negative returns under plausible market variation.

Monte Carlo (MC) robustness testing addresses this by generating thousands of
synthetic APY trajectories derived from historical statistics (mean, volatility,
autocorrelation) and measuring how often a strategy achieves acceptable outcomes
across the full simulated distribution.

This ADR establishes MC robustness testing as a complementary validation layer
to WFV, required before any strategy is promoted from "candidate" to "active"
in the tournament.

## Decision

### Minimum MC Requirements
- **Simulations:** ≥ 1,000 random APY trajectories per strategy
- **Trajectory generation:** Bootstrap resampling of historical APY returns
  (block bootstrap, block size = 5 days, preserves short-term autocorrelation)
- **Scenario horizon:** matches WFV test window (≥ 1 month per fold)

### Acceptance Thresholds
| Metric                        | Threshold          |
|-------------------------------|--------------------|
| P(Sharpe ≥ 0.5) across sims  | ≥ 60%              |
| Median OOS Sharpe (MC)        | ≥ 0.6              |
| 5th-percentile OOS Sharpe     | ≥ 0.0 (no loss)    |
| Max drawdown (95th percentile)| ≤ 15%              |

A strategy that fails any single threshold is flagged **MC_FAIL** and cannot
advance. It may be re-submitted after parameter adjustment or after 30 additional
days of OOS data become available.

### Determinism
All MC runs use a fixed random seed (`seed=42`) for reproducibility. Seed may
be overridden via CLI flag `--mc-seed` for sensitivity analysis only.

## Consequences

### Positive
- Provides distributional risk estimates, not just point estimates.
- Catches strategies that are marginally WFV-passing but fragile.
- Results are stored in `data/mc_robustness.json` for audit trail.

### Negative / Trade-offs
- 1,000+ simulations add ~5–30 seconds per strategy; acceptable in batch
  pre-launch validation but not in daily cycle_runner.
- Bootstrap does not model tail events (black swans) — separate stress tests
  (ADR-039) cover those.
- Requires clean historical APY series ≥ 90 days; protocols with shorter
  history are exempt and receive a "DATA_INSUFFICIENT" waiver recorded in the
  audit log.

## Implementation

Primary module: `spa_core/backtesting/monte_carlo_robustness.py`

```
class MonteCarloRobustness:
    def __init__(self, n_simulations=1000, block_size=5, seed=42): ...
    def run(self, strategy, apy_series: list[float]) -> MCResult: ...
    def is_approved(self, result: MCResult) -> bool: ...
```

`MCResult` includes: `n_simulations`, `p_sharpe_above_0_5`, `median_sharpe`,
`p5_sharpe`, `p95_max_drawdown`, `approved`, `waiver_reason`.

Results logged to `data/mc_robustness.json` (ring-buffer 50, atomic write).

## References
- ADR-037 (Walk-Forward Validation — prerequisite gate)
- ADR-039 (Drawdown Circuit Breaker — complementary stress layer)
- `spa_core/backtesting/monte_carlo_robustness.py`
- MASTER_PLAN_v1.md §3 (Backtesting Standards)
