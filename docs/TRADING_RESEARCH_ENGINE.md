# Trading Research Engine v0

> Decision: [ADR-525](decisions/ADR-525-capital-architecture-v1-and-trading-research-engine.md) ·
> code: `spa_core/trading_research/` · state: `data/trading_research/` (runtime, not in git) ·
> agent: `com.spa.trading_research` (every 15 min) · research/paper ONLY.

## Model

A candidate is data, not code:

    family(+version) × params × asset × timeframe × direction × execution model

`strategies.registry()` expands grids into candidates; adding one is a grid line, adding a family is
one pure function. Identity = `family@vN:asset:tf:exec:def_hash10`; the def hash covers the family
version and the execution-model version, so a changed strategy is a NEW candidate with a new history.
A golden fingerprint test fails if a family's output changes without a version bump.

v0 universe: **138 candidates** — 10 public-domain families (MA cross SMA/EMA, price vs MA, time-series
momentum, Donchian breakout, SuperTrend, RSI mean reversion, MACD, Bollinger mean reversion, trend with
ATR volatility filter, SuperTrend ∧ SMA-200) × grid × **BTC** × **1h / 4h / 1D** × spot long-only
(all) and 1× perpetual long/short paper (trend families).

## Data

Binance spot BTCUSDT 1h klines (public, since 2017-08-17) + Binance USDⓈ-M funding history. Only
CLOSED candles are stored; stored candles are immutable (triggers); a refetch that disagrees is logged
as a conflict, never applied. 4h / 1D / 1W are aggregated from 1h, UTC-aligned, complete buckets only;
gaps are reported, never filled. Other timeframes (2h, 8h, 12h, 1W) are one entry in `TF_MS`.

## Backtest (`backtest.py`)

Same signal functions and the same `execution.step()` as the forward paper. Target decided on bar t's
close, filled at bar t+1's open. Costs per side: spot 10 bps fee + 5 bps slippage; perp 5 + 5 bps,
funding at every funding timestamp, isolated-margin liquidation. Validation: in-sample < 2023-01-01 ≤
out-of-sample, calendar-year slices, regime slices, costs at 0×/1×/2×/3×, family-neighbour
robustness, buy-and-hold benchmark. Every run carries a manifest (data range, data hash, gaps, code
version, split, cost model).

Qualification (`ranking.py`) needs ALL of: OOS Sharpe ≥ 0.8, IS Sharpe ≥ 0.4, OOS Sharpe ≥ 0.5 at 3×
costs, ≥ 15 trades, max drawdown ≥ −55 %, beats buy-and-hold on Calmar or drawdown, neighbours' median
OOS Sharpe ≥ 0.3. Score = min(IS, OOS, OOS@3×). The shortlist drops candidates whose OOS daily returns
correlate > 0.85 with one already picked.

## Forward paper (`forward.py`, `evidence.py`)

Every tick: sync closed candles → register new candidates → for every candidate, one observation per
newly closed bar that OPENED after its registration (never backfilled; missed ticks are caught up and
flagged `late`) → daily backtest refresh and lifecycle re-derivation → `status.json`. Observations are
append-only (UPDATE/DELETE abort), one per (candidate, bar), hash-chained per candidate, and carry:
candidate id + def hash, asset, timeframe, bar open/close time, signal time, fill of the previous
decision at this bar's open with its cost, funding, position, equity, the new target and action, the
closed trade if any, the book state, the assumptions (fees/slippage/timing), a market-data reference
(`n` bars + hash of the last 300) and the code version + release. `python -m spa_core.trading_research
verify` recomputes every chain. Forward paper records ALL candidates — the rejected ones are the control
group against selection bias; the FORWARD_PAPER stage marks the qualified ones.

## Lifecycle (`lifecycle.py`)

DISCOVERED → BACKTESTING → BACKTEST_QUALIFIED | REJECTED → FORWARD_PAPER → ROBUST (automatic,
research-only) → CHAMPION_CANDIDATE → SHADOW (need a recorded owner decision) → LIMITED_LIVE →
PRODUCTION (refused in code). Every transition is an append-only, hash-chained event with its reason.
ROBUST needs ≥ 30 forward days, ≥ 5 forward trades, forward Sharpe ≥ 0.5 and ≤ 50 % degradation vs OOS.

## Regimes (`regime.py`)

Rule-based on daily bars, causal (a day's label applies from the next day): bull / bear / sideways by
SMA-200 and its 20-day slope; high / normal / low volatility by the 30-day realized-vol percentile in the
trailing year; stress on |daily move| > 8 % or vol percentile > 95 %.

## Operations

`python -m spa_core.trading_research tick | backtest | verify | status`. Health: `status.json` (read by
the Director report — a tick older than 2 h is an alert), the `ticks` table, agent_health (launchd).
Owner surface: Director report → «📈 Продукт» → TRADING block; Bridge `/product`.
