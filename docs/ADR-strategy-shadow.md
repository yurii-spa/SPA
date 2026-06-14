# ADR — Multi-Strategy Shadow Framework (Sprint A, v3.90)

**Status:** Accepted (advisory framework only)
**Date:** 2026-06-09
**Sprint:** A / v3.90

## Context

The portfolio currently runs a single allocation policy. To learn which
allocation logic performs best *before* committing any capital, we want to run
several candidate strategies side-by-side on identical live data and compare
their risk-adjusted returns over the paper-trading window.

## Decision

Introduce `spa_core/strategies/` — a **shadow framework** that fans one data
snapshot from the read-only adapter orchestrator
(`data/adapter_orchestrator_status.json`) out across **six** virtual $100K
portfolios (S0–S5), one per strategy:

| ID | Strategy | Risk | Logic |
|----|----------|------|-------|
| S0 | Baseline (Equal Weight) | low | 1/N across active pools |
| S1 | Concentration | high | top-1 50%, top-2 30%, rest split 20% |
| S2 | APY Momentum | high | weight ∝ positive APY momentum vs 5-run mean |
| S3 | Risk Parity+ | low | inverse-volatility (1/σ) weighting |
| S4 | Half-Kelly | medium | 0.5 × min(edge/(edge+1), 0.25), rf = 4% |
| S5 | Yield Spread | medium | weight ∝ positive spread vs median APY |

Each strategy returns raw target weights; a **single external risk guard**
(`apply_risk_policy`) then clips every strategy's output to the tier
concentration caps (T1 ≤ 40%, T2 ≤ 20%). `runner.py` advances each
`VirtualPortfolio` one step (APY → daily yield accrual, mark-to-market, rebalance)
and persists state to `data/strategies/{name}.json`. `comparator.py` ranks the
portfolios by **Sortino** (downside-deviation only — the primary metric) and
writes a leaderboard.

## Constraints honoured

- **Advisory / read-only.** Nothing imports or mutates `execution/`,
  `feed_health/`, or the deterministic risk agents. Caps are copied constants,
  not an import of capital-touching risk code.
- **Stdlib only**, atomic writes (`tempfile` + `os.replace`) throughout.
- **No shadow strategy may become an active allocation without an explicit,
  separately-approved ADR.** This framework only measures and ranks.

## Deviation: output filename

The sprint spec named `data/strategy_comparison.json` for the comparator output.
That file already exists as an **export-pipeline-owned artifact** (the legacy
`v1_passive` / `v2_aggressive` dashboard comparison, written by `export_data.py`,
with an incompatible dict schema). Overwriting it would break the existing
dashboard and be reverted on the next export run.

Following the project's **v3.79 precedent** (the orchestrator wrote
`adapter_orchestrator_status.json` rather than clobber the execution-owned
`adapter_status.json`), the shadow framework writes to a distinct file:
**`data/strategy_shadow_comparison.json`**. This keeps the new leaderboard fully
decoupled from the legacy export pipeline.

## Tests

`spa_core/tests/test_strategies.py` — 49 tests (unittest, stdlib, fully isolated
temp I/O, no network). Covers each strategy's weighting + fallbacks, the risk
guard caps/idempotence, `VirtualPortfolio` yield accrual + equity-curve ring
buffer + atomic persistence, the runner fan-out, and comparator ranking /
null-Sharpe handling.
