"""
spa_core/strategy_lab/data — the Strategy Lab DATA LAYER.

Produces `MarketSnapshot` objects (defined in strategy_lab/base.py) — the SAME shape for
backtest historical snapshots AND live paper-trading. ONE source of truth.

Sourcing (LIVE PUBLIC keyless APIs):
  - funding_feed.py   — ETH-perp funding = MEDIAN of Binance + Bybit (robust to a single venue).
  - price_feed.py     — ETH + LRT (eETH, weETH, ezETH) USD prices via DeFiLlama coins API,
                        plus lrt_eth_ratio for depeg detection.
  - restaking_feed.py — eETH/ezETH restaking APY via DeFiLlama yields.
  - market_data.py    — MarketData unifier: snapshot(date), latest(), historical_range(s,e).

Design rules (inherited from the repo):
  - stdlib-only runtime (urllib + gzip + json), deterministic.
  - LLM FORBIDDEN.
  - Fail-CLOSED: a malformed / empty API response raises InvalidDataError — NEVER a silent
    default / fabricated value.
  - Forward-fill only within an explicit limit; beyond it the field is None + flagged in
    snapshot.gaps. Forward-filled fields are flagged in snapshot.ff_filled.
  - Atomic cache writes to data/market_data/*.json so backtest + paper share one cache.
"""
# LLM_FORBIDDEN
