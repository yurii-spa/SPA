"""
spa_core/strategy_lab/aggressive_lab/run.py — the Aggressive Lab CLI / standing-tick entrypoint.

Two real-data operations, both isolation-verified, both writing only data/aggressive_lab/:
    python3 -m spa_core.strategy_lab.aggressive_lab.run backtest   # REAL 2024-26 replay
    python3 -m spa_core.strategy_lab.aggressive_lab.run paper       # ONE live forward tick
    python3 -m spa_core.strategy_lab.aggressive_lab.run both        # backtest then a live tick

The backtest sources the sUSDe PT/YT implied-yield series from the REAL deep Pendle dataset
(rates_desk pendle history); the live tick builds a live snapshot from the live feeds. NO mock data.
Advisory: never moves capital, never touches the go-live track (proven each run by the md5 witness).

stdlib only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import socket
import sys

from spa_core.strategy_lab.aggressive_lab import feeds as af
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.harness import PaperService, run_backtest


def _real_history_feeds() -> AggressiveFeeds:
    """Build an AggressiveFeeds backed by the REAL deep history feeds (2024–2026):
      • Pendle PT/YT-sUSDe implied yields + sUSDe staking APY ← the deep Pendle dataset (always),
      • ETH-perp funding ← the 5-venue median funding feed (best-effort over the Pendle window),
      • LRT/LST restaking APY ← the DeFiLlama restaking-yield history (best-effort).
    A best-effort feed that raises is simply omitted — the books that need it then FAIL CLOSED on
    each tick (honest gap), never a fabricated number. The sUSDe books always get real data."""
    pt_series, susde_series = af.load_real_susde_history()  # fail-closed if dataset missing
    start, end = min(pt_series), max(pt_series)

    funding_series = None
    try:
        from spa_core.strategy_lab.data.funding_feed import FundingFeed
        funding_series = FundingFeed(symbol="ETH").history(start, end) or None
    except Exception:  # noqa: BLE001 — a funding-feed failure leaves those books to fail-close
        funding_series = None

    restaking_series = None
    try:
        from spa_core.strategy_lab.data.restaking_feed import RestakingFeed
        rs = RestakingFeed().history(start, end)  # {symbol: {date: apy}}
        restaking_series = rs or None
    except Exception:  # noqa: BLE001
        restaking_series = None

    return AggressiveFeeds(
        pt_susde_series=pt_series, susde_apy_series=susde_series,
        funding_series=funding_series, restaking_series=restaking_series,
    )


def run_real_backtest() -> dict:
    feeds = _real_history_feeds()
    dates = sorted(set(feeds.available_dates()))
    start, end = dates[0], dates[-1]
    return run_backtest(feeds, start, end)


def main(argv=None) -> int:
    socket.setdefaulttimeout(30)
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "both"
    out = {}
    if mode in ("backtest", "both"):
        out["backtest"] = run_real_backtest()
    if mode in ("paper", "both"):
        out["paper"] = PaperService().tick()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
