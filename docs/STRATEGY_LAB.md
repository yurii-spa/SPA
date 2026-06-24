# Strategy Lab — backtest + paper-trading of pluggable yield strategies

A lab where several yield strategies run through **one shared backtest harness** and **one live
paper-trading service** (no real capital), for an honest risk-adjusted comparison vs the RWA
risk-free floor. Lives in `spa_core/strategy_lab/`. Parallel model — wraps the existing engines,
does not disturb them. stdlib-only, deterministic, LLM-forbidden in risk/kill logic.

## One-command usage

```bash
# Backtest — runs ALL strategies over the same window/capital, prints the comparative table:
python3 scripts/strategy_lab_backtest.py --refresh            # --refresh re-fetches live data
python3 scripts/strategy_lab_backtest.py --md report.md       # also write a markdown report

# Paper-trading (live, no capital) — one tick (launchd invokes this hourly):
python3 scripts/strategy_lab_paper.py                         # single tick (restart-survival)
python3 scripts/strategy_lab_paper.py --loop --interval 3600  # daemon mode
python3 scripts/strategy_lab_paper.py --status                # status table
python3 scripts/strategy_lab_paper.py --weekly               # weekly comparative report
```

Runs as `com.spa.strategy_lab_paper` (launchd, hourly) — survives restart, accumulates a
time-series for weeks/months.

## Strategies

| id | mandate | what it is | kill conditions |
|---|---|---|---|
| `variant_n` | neutral (β≈0) | LRT (eETH) spot + short ETH-perp hedge. Income = restaking yield + points ± funding. ETH price hedged out; residual = LRT/ETH depeg. | funding < X for N hours; LRT depeg > Y% |
| `variant_d` | directional (β≈1) | Pure LRT, no hedge. Income = restaking + points + ETH price move. ISOLATED sleeve, outside the stablecoin mandate. | drawdown > Z% from peak |
| `engine_a/b/c` | stable | Baselines wrapping the real Engine A ($100k base) / B (HY) / C (LP) sleeves. | risk-policy drawdown stop |
| `rwa_floor` | benchmark | Risk-free floor (4.5% APY, zero vol). The bar every strategy must beat risk-adjusted. | — |

All thresholds (X/Y/Z/N) live in the SSOT config — never hardcoded.

## Adding a strategy (DoD #4)

One new class implementing the `Strategy` ABC (`base.py`: `init/positions/step/metrics/kill_check`)
+ one config block in `strategy_lab_config.json`. The harness never changes.

## Architecture

```
spa_core/strategy_lab/
  base.py            — Strategy ABC + MarketSnapshot + Position + StrategyMetrics + KillResult + InvalidDataError
  config.py          — SSOT loader (strategy_lab_config.json); risk LIMITS imported from spa_core.risk.policy (not duplicated)
  metrics.py         — net APY, maxDD, Sharpe/Sortino, β-to-ETH, funding drag, corr-to-stable, tail(ETH-20+flip), beats-RWA-floor
  data/              — funding (median Binance+Bybit) · price (ETH/LRT via DeFiLlama coins) · restaking (DeFiLlama yields)
                       schema-validated, fail-CLOSED (raise on bad/empty; no silent defaults), ff-with-limit + gap flags
  strategies/        — variant_n.py · variant_d.py · baselines.py (A/B/C/RWA wrappers)
  backtest.py        — shared harness: same capital + window + data, deterministic, costs, window-stress validation
  report.py          — comparative markdown table vs RWA floor
  paper.py           — live service: restart-survival, idempotent per day, fail-closed, kills→Telegram
```

## Data layer (decisions)

- **Sourcing:** live public keyless APIs. Funding = **median of Binance + Bybit** ETH-perp.
  Prices (ETH + eETH/ezETH/weETH) = DeFiLlama coins. Restaking APY = DeFiLlama yields.
- **Fail-closed:** a malformed/empty API response raises `InvalidDataError`; strategies go to a
  safe state — never a silent default.
- **One source of truth:** backtest (historical) and paper (live) consume the SAME `MarketData`
  / cached series, so they can't disagree.

## Known limitation (honest)

The free keyless funding endpoints (Binance/Bybit) only reliably reach back a few weeks without
pagination, so the **real backtest window is bounded to recent history** (the current paper
track, 2026-06-10 →). A deeper historical backtest needs funding-history pagination or an
archived dataset — a follow-up. The harness itself is window-agnostic and validated on a
synthetic stress window (engineered ETH drawdown + funding flip).

## Latest real comparative (window 2026-06-10 → 2026-06-24)

| Strategy | Net APY % | MaxDD % | Sharpe | β(ETH) | Tail % | Beats floor |
|---|---|---|---|---|---|---|
| variant_n | 12.85 | 1.58 | 1.32 | −0.06 | +1.12 | ✅ |
| variant_d | −16.01 | 11.49 | −0.04 | 0.94 | −18.75 | ❌ |
| engine_a / b / c | 4.60 / 8.33 / 8.87 | 0 | — | ~0 | 0 | ✅ |
| rwa_floor | 4.60 | 0 | — | 0 | — | benchmark |

Variant N delivered a neutral (β≈0) return above the floor; Variant D underperformed in this
ETH-down window — exactly the behaviour the harness is meant to surface honestly.
