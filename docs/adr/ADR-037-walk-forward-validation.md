# ADR-037: Walk-Forward Validation as Mandatory Pre-Paper Gate

## Status
Accepted

## Context
Simple backtesting can overfit historical data, producing strategies that look
exceptional on in-sample (IS) data but fail on live markets. Walk-forward
validation (WFV) addresses this by repeatedly training a strategy on a window of
historical data and then evaluating it on the immediately following out-of-sample
(OOS) window, sliding both windows forward in time.

Without a mandatory WFV gate, the tournament (S0–S10) risks promoting strategies
whose apparent performance is an artifact of curve-fitting rather than genuine
predictive edge.

## Decision
All strategies MUST pass WFV before being considered for paper trading:

- **Training window:** 6 months minimum per fold
- **Test window:** 1 month minimum per fold
- **Minimum folds:** 3 (covering at least 9 months of history in total)
- **OOS Sharpe threshold:** ≥ 0.8 (annualised, on OOS windows only)
- **Degradation ratio:** OOS_Sharpe / IS_Sharpe ≥ 0.7

A strategy that passes IS backtesting but fails WFV (i.e. OOS Sharpe < 0.8 OR
degradation ratio < 0.7) is classified as **overfit** and blocked from paper
trading until re-parameterised or the data window extends sufficiently.

## Consequences

### Positive
- Reduces strategy overfitting before real capital is at risk.
- Provides a reproducible, auditable gate with numeric thresholds.
- Encourages strategies with robust, low-complexity parameterisation.

### Negative / Trade-offs
- Requires ≥ 9 months of historical APY/TVL data per protocol, which is not
  yet available for newer protocols (Aave V3 Arbitrum, Pendle PT).
- T3-SPEC strategies (S10) may be temporarily blocked even if conceptually sound.
- WFV run time increases O(n_folds × strategy_complexity); acceptable for daily
  batch but not suitable for real-time signal generation.

## Implementation

Primary module: `spa_core/backtesting/walk_forward_validator.py`

```
class WalkForwardValidator:
    def __init__(self, train_months=6, test_months=1, min_folds=3,
                 oos_sharpe_min=0.8, degradation_ratio_min=0.7): ...
    def validate(self, strategy, apy_series: list[dict]) -> WFVResult: ...
    def is_approved(self, result: WFVResult) -> bool: ...
```

`WFVResult` includes: `n_folds`, `is_sharpe_mean`, `oos_sharpe_mean`,
`degradation_ratio`, `approved`, `rejection_reason`.

The gate is invoked in `spa_core/paper_trading/pre_launch_validation.py`
under the `wfv_gate` check. Result is logged to `data/wfv_results.json`
(ring-buffer 50 entries, atomic write).

## References
- `spa_core/backtesting/walk_forward_validator.py`
- `spa_core/paper_trading/pre_launch_validation.py`
- ADR-023 (Strategy Promotion Policy)
- MASTER_PLAN_v1.md §3 (Backtesting Standards)
