# ADR-525: Capital Architecture v1 and the Trading Research Engine v0

- **Status:** ACCEPTED · 2026-09-30 · owner: @yurii (owner directive «CAPITAL ARCHITECTURE v1 + TRADING
  RESEARCH ENGINE v0», autonomous execution authorised in it)
- **Scope:** new research/paper-only package `spa_core/trading_research/`, its agent
  `com.spa.trading_research`, docs `docs/CAPITAL_ARCHITECTURE.md` and `docs/TRADING_RESEARCH_ENGINE.md`,
  a read-only TRADING block in the Director report. No money path, no RiskPolicy / kill-switch change,
  no execution, no public-site numbers.

## Context (audit of 2026-09-30)

- SPA had **no directional price-trading engine**: every MA/momentum in `spa_core` runs on APY/TVL;
  backtests (`strategy_lab`, `tournament`, `professional_backtest`) are DeFi yield/carry; SPA's
  `btc_nav` (ADR-118) was never installed; `research/btc_cycle` is archived with its champion missing.
- The only BTC engine is **earn-defi** (separate repo, no remote): an MVRV-cycle allocator with a
  strong evidence design (hash-chained append-only ledger, hashed configs, replay, commit-reveal) but a
  single family, daily data only, no OOS/walk-forward, an M2 look-ahead in its backtest, and — found
  here — a still-open Coinbase daily candle stored as a close that tripped a false KC-1 on 09-18
  (INCIDENT open since 09-19). The candle bug is fixed in earn-defi `21c125e`; lifting the INCIDENT
  stays a manual reasoned owner action (earn-defi ADR-006).
- Public read-only market data is reachable: Binance spot klines (1h since 2017-08) and USDⓈ-M
  funding history.

## Decision

1. **Capital Architecture v1** as recorded in `docs/CAPITAL_ARCHITECTURE.md`: DeFi (Conservative /
   Balanced / Aggressive) · Trading (Crypto Spot / Crypto Futures / future equities) · Cash-Treasury ·
   Market Neutral-Basis · Future Engines; a Capital Allocator / Portfolio CIO later, **not built now**.
   Studio OS stays the control plane and never holds financial state; engines own theirs.
2. **Trading Research Engine v0** in the SPA repo (the only repository with a working canonical
   delivery), as a separate investment package with its own runtime state in `data/trading_research/`:
   candidate = family × params × asset × timeframe × direction × execution model; deterministic, stdlib,
   LLM-free; one shared `execution.step()` for backtest and forward paper; append-only hash-chained
   forward evidence recorded for ALL candidates from registration onward (never backfilled).
3. v0 universe: 138 candidates, BTC, 1h / 4h / 1D, spot long-only + 1× perpetual long/short paper.
4. Lifecycle up to FORWARD_PAPER / ROBUST is automatic; CHAMPION_CANDIDATE and SHADOW need a recorded
   owner decision; LIMITED_LIVE / PRODUCTION are refused in code.
5. earn-defi stays a separate product engine under Trading → Crypto Spot; SPA `btc_nav` is superseded
   (left in place, not installed).

## Consequences

- Forward-paper evidence starts accumulating immediately and cannot be rewritten; a strategy change is
  a new identity.
- The owner sees a concise TRADING status in the Director report (Bridge `/product`, `/report`).
- There is no code path to an exchange account; futures are simulation only.
