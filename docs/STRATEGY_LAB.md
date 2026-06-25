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
| `eth_lst_neutral` | neutral (β≈0) | **NEW — the SAFE ETH-yield sleeve.** PLAIN-staking LSTs (stETH/rETH, **NOT LRTs**) spot + short ETH-perp, β≈0. Income = staking yield ± funding. LSTs hug their ETH peg far tighter than LRTs → much smaller depeg residual than variant_n. The recommended ETH approach. | tighter LST depeg > Y%; funding < X for N hours |
| `rwa_sleeve` | stable (T1) | **NEW — the realized RWA cash floor (allocatable, not a benchmark).** Holds tokenized US-Treasury funds (BUIDL/USYC/USDY/OUSG…) and accrues at the LIVE tokenized-T-bill yield (rwa_feed, TVL-weighted ~3.4%). Zero price vol, ~no drawdown — the lowest-risk T1 home for idle cash. Banks the floor, doesn't try to beat it. | — (zero-vol) |
| `engine_a/b/c` | stable | Baselines wrapping the real Engine A ($100k base) / B (HY) / C (LP) sleeves. | risk-policy drawdown stop |
| `rwa_floor` | benchmark | Risk-free floor — **live tokenized-T-bill yield (~3.4%, rwa_feed), no longer hardcoded**, zero vol. The bar every strategy must beat risk-adjusted. Reference row, not held. | — |

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
  data/              — funding_feed (median across Binance/Bybit/OKX/KuCoin/Hyperliquid) · price (ETH/LST/LRT via DeFiLlama coins)
                       · restaking/staking (DeFiLlama yields) · rwa_feed (LIVE tokenized-T-bill floor, TVL-weighted ~3.4%)
                       schema-validated, fail-CLOSED (raise on bad/empty; no silent defaults), ff-with-limit + gap flags
  strategies/        — variant_n.py · variant_d.py · eth_lst_neutral.py · rwa_sleeve.py · baselines.py (A/B/C/RWA wrappers)
  backtest.py        — shared harness: same capital + window + data, deterministic, costs, window-stress validation
  report.py          — comparative markdown table vs RWA floor
  paper.py           — live service: restart-survival, idempotent per day, fail-closed, kills→Telegram
```

## Data layer (decisions)

- **Sourcing:** live public keyless APIs. Funding = **median across 5 venues — Binance, Bybit,
  OKX, KuCoin, Hyperliquid** ETH-perp (Hyperliquid pays hourly → normalized to the 8h cadence of
  the CEX venues before blending). Prices (ETH + eETH/ezETH/weETH + stETH/rETH) = DeFiLlama coins.
  Restaking/staking APY = DeFiLlama yields.
- **RWA floor = LIVE:** `data/rwa_feed.py` pulls the tokenized US-Treasury market (BUIDL/USYC/USDY/
  OUSG/USTB/TBILL…, ~$15B) from DeFiLlama yields and returns the **TVL-weighted mean APY (~3.4%)** —
  no longer a hardcoded literal. Fail-closed (raises `InvalidDataError` if no pool clears the $5M
  TVL floor); callers (`config.rwa_floor_apy_pct`) decide whether to fall back to a committed literal.
  Both `rwa_floor` (benchmark) and `rwa_sleeve` (allocatable) read this same live rate.
- **Fail-closed:** a malformed/empty API response raises `InvalidDataError`; strategies go to a
  safe state — never a silent default.
- **One source of truth:** backtest (historical) and paper (live) consume the SAME `MarketData`
  / cached series, so they can't disagree.

## Historical depth (free pagination)

The feeds paginate the free keyless endpoints to reach **~2 years** of real history at $0:
- **Binance/Bybit funding** — paged via `startTime`/`endTime` (Binance 1000/page ascending, Bybit
  200/page descending), de-duped, daily MEDIAN across venues. Reaches back to perp inception.
- **ETH + LRT prices** — DeFiLlama `coins.llama.fi/chart` paged in ≤365-day daily chunks.
- **Restaking APY** — DeFiLlama `yields.llama.fi/chart/{pool}` per-date APY series.

Real achievable depth: prices/eETH-restaking from **2024-06-05**; ezETH restaking from 2024-12-13
(earlier dates honestly gapped, not fabricated). Default window: **2024-06-05 → 2026-06-24**.

## Latest real comparative (deep window 2024-06-05 → 2026-06-24, 750 days)

Window validation ✅ — contains **4 ETH drawdowns >10% + 74 funding flips to negative** (real stress).

| Strategy | Net APY % | MaxDD % | Sharpe | β(ETH) | Beats floor |
|---|---|---|---|---|---|
| variant_n | −0.84 | 10.79 | −0.04 | −0.02 | ❌ (killed 2024-08-09, LRT depeg 2.89%) |
| variant_d | −15.42 | 30.05 | −1.03 | 0.05* | ❌ (killed 2024-08-05, drawdown 30%) |
| engine_a / b / c | 4.60 / 8.33 / 8.87 | 0 | — | ~0 | ✅ |
| rwa_floor | 4.60 | 0 | — | 0 | benchmark |

*Variant D's full-window β reads ~0 because its drawdown kill latched in the Aug-2024 ETH crash and
it held flat thereafter. **Honest finding:** over a deep window with real ETH crashes, both restaking
candidates hit their kill switches and do NOT beat the stable engines / RWA floor — exactly what the
lab exists to surface. (On a calm short window, Variant N's neutral carry did beat the floor; it is
the tail/crash behaviour that disqualifies it here.)
