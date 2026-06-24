"""
spa_core/strategy_lab/data/price_feed.py — ETH + LRT USD prices via DeFiLlama coins API.

Keyless public endpoints:
  current: https://coins.llama.fi/prices/current/ethereum:0x<addr>,ethereum:0x<addr2>,...
           → {"coins": {"ethereum:0x..": {"price": float, "symbol", "timestamp", ...}}}
  chart:   https://coins.llama.fi/chart/ethereum:0x<addr>?span=N&period=1d
           → {"coins": {"ethereum:0x..": {"prices": [{"timestamp": s, "price": float}, ...]}}}

Tokens (canonical mainnet contracts):
  WETH  (ETH ref) 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
  eETH            0x35fA164735182de50811E8e2E824cFb9B6118ac2
  weETH           0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee
  ezETH           0xbf5495Efe5DB9ce00f80364C8B423567e58d2110

Also computes lrt_eth_ratio = lrt_price / eth_price for depeg detection.

FAIL-CLOSED: missing/empty/unparseable price → InvalidDataError. No silent default.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

CHAIN = "ethereum"
# symbol key (lowercase, as used in MarketSnapshot) -> contract address
TOKENS: Dict[str, str] = {
    "eth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH = ETH reference
    "eeth": "0x35fA164735182de50811E8e2E824cFb9B6118ac2",
    "weeth": "0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee",
    "ezeth": "0xbf5495Efe5DB9ce00f80364C8B423567e58d2110",
}
LRT_SYMBOLS = ("eeth", "weeth", "ezeth")  # everything except the eth reference

CURRENT_URL = "https://coins.llama.fi/prices/current/{ids}"
CHART_URL = "https://coins.llama.fi/chart/{id}?span={span}&period=1d"

Fetcher = Callable[[str], object]


def _coin_id(addr: str) -> str:
    return f"{CHAIN}:{addr}"


def _validate_coins(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise InvalidDataError(f"coins price: expected object, got {type(payload).__name__}")
    coins = payload.get("coins")
    if not isinstance(coins, dict) or not coins:
        raise InvalidDataError("coins price: missing/empty 'coins'")
    return coins


def _extract_price(coins: dict, addr: str, symbol: str) -> float:
    entry = coins.get(_coin_id(addr))
    if not isinstance(entry, dict):
        raise InvalidDataError(f"coins price: no entry for {symbol} ({addr})")
    price = entry.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        raise InvalidDataError(f"coins price: missing/invalid price for {symbol}: {price!r}")
    return float(price)


def _ratios(prices: Dict[str, float]) -> Dict[str, float]:
    eth = prices.get("eth")
    if not eth:  # eth absent → cannot compute ratios (fail-closed at caller; here skip)
        raise InvalidDataError("coins price: eth reference price missing for ratio")
    return {
        sym: round(prices[sym] / eth, 8)
        for sym in LRT_SYMBOLS
        if sym in prices
    }


class PriceFeed:
    """ETH + LRT USD prices and lrt/eth ratios. Inject `fetcher` (url->json) in tests."""

    def __init__(self, fetcher: Optional[Fetcher] = None):
        self._fetch = fetcher or http_fetch

    # ── current (live) ──────────────────────────────────────────────────────────────────
    def current(self) -> Dict[str, object]:
        """Return {"prices": {sym: usd}, "ratios": {lrt_sym: lrt/eth}}. Schema-validates every
        token; raises InvalidDataError on any missing/invalid price."""
        ids = ",".join(_coin_id(a) for a in TOKENS.values())
        coins = _validate_coins(self._fetch(CURRENT_URL.format(ids=ids)))
        prices = {sym: _extract_price(coins, addr, sym) for sym, addr in TOKENS.items()}
        return {"prices": prices, "ratios": _ratios(prices)}

    # ── historical ──────────────────────────────────────────────────────────────────────
    def history(self, span: int = 90) -> Dict[str, Dict[str, float]]:
        """Return {sym: {date(ISO): usd_price}} for each token over the last `span` days.

        Fetches one /chart call per token. Schema-validates each: a chart with no usable
        price points raises InvalidDataError (fail-closed)."""
        out: Dict[str, Dict[str, float]] = {}
        for sym, addr in TOKENS.items():
            payload = self._fetch(CHART_URL.format(id=_coin_id(addr), span=span))
            out[sym] = _parse_chart(payload, addr, sym)
        return out

    def history_ratios(self, span: int = 90) -> Dict[str, Dict[str, float]]:
        """Return {lrt_sym: {date: lrt/eth ratio}} aligned on shared dates with eth."""
        hist = self.history(span=span)
        eth = hist.get("eth", {})
        ratios: Dict[str, Dict[str, float]] = {}
        for sym in LRT_SYMBOLS:
            series = hist.get(sym, {})
            ratios[sym] = {
                d: round(series[d] / eth[d], 8)
                for d in series
                if d in eth and eth[d]
            }
        return ratios


def _parse_chart(payload: object, addr: str, symbol: str) -> Dict[str, float]:
    """DeFiLlama /chart → {date(ISO): price}. One point per UTC day (last wins). Raises if no
    valid point is found."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"coins chart: expected object for {symbol}")
    coins = payload.get("coins")
    if not isinstance(coins, dict):
        raise InvalidDataError(f"coins chart: missing 'coins' for {symbol}")
    entry = coins.get(_coin_id(addr))
    if not isinstance(entry, dict):
        raise InvalidDataError(f"coins chart: no entry for {symbol} ({addr})")
    points = entry.get("prices")
    if not isinstance(points, list) or not points:
        raise InvalidDataError(f"coins chart: 'prices' missing/empty for {symbol}")
    series: Dict[str, float] = {}
    for pt in points:
        if not isinstance(pt, dict):
            continue
        ts = pt.get("timestamp")
        price = pt.get("price")
        if not isinstance(ts, (int, float)) or not isinstance(price, (int, float)) or price <= 0:
            continue
        d = datetime.datetime.fromtimestamp(
            ts, tz=datetime.timezone.utc
        ).date().isoformat()
        series[d] = float(price)  # last point on a day wins
    if not series:
        raise InvalidDataError(f"coins chart: no valid price points for {symbol}")
    return series


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(15)
    feed = PriceFeed()
    cur = feed.current()
    for sym, p in cur["prices"].items():
        print(f"{sym:>6} ${p:,.2f}")
    for sym, r in cur["ratios"].items():
        print(f"{sym:>6} /eth ratio = {r:.6f}")
