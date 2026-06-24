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
import time
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
# Deep history: anchor at a unix `start` and walk forward in ≤MAX_SPAN day chunks (the API 400s
# on very large span). period=1d → one point per UTC day. FREE keyless endpoint.
CHART_RANGE_URL = "https://coins.llama.fi/chart/{id}?start={start}&span={span}&period=1d"
MAX_SPAN = 365              # days per chart call (API rejects very large spans → ~400)
PAGE_DELAY_S = 0.25         # polite delay between page fetches
MAX_PAGES = 12              # safety cap (12 * 365 ≈ 12y) per token

Fetcher = Callable[[str], object]


def _to_unix(d: datetime.date) -> int:
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


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

    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        page_delay_s: float = PAGE_DELAY_S,
        max_pages: int = MAX_PAGES,
    ):
        self._fetch = fetcher or http_fetch
        self._page_delay = page_delay_s
        self._max_pages = max_pages

    # ── current (live) ──────────────────────────────────────────────────────────────────
    def current(self) -> Dict[str, object]:
        """Return {"prices": {sym: usd}, "ratios": {lrt_sym: lrt/eth}}. Schema-validates every
        token; raises InvalidDataError on any missing/invalid price."""
        ids = ",".join(_coin_id(a) for a in TOKENS.values())
        coins = _validate_coins(self._fetch(CURRENT_URL.format(ids=ids)))
        prices = {sym: _extract_price(coins, addr, sym) for sym, addr in TOKENS.items()}
        return {"prices": prices, "ratios": _ratios(prices)}

    # ── historical ──────────────────────────────────────────────────────────────────────
    def history(
        self,
        span: int = 90,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Return {sym: {date(ISO): usd_price}} for each token.

        Default (no start_date/end_date): one /chart call per token over the last `span` days.
        With start_date/end_date (ISO): page each token forward from `start` in ≤MAX_SPAN-day
        chunks (the API 400s on huge spans) until the window is covered, merging by date (last
        wins). Schema-validates each page; a token with no usable price points raises
        InvalidDataError (fail-closed)."""
        if start_date is None and end_date is None:
            out: Dict[str, Dict[str, float]] = {}
            for sym, addr in TOKENS.items():
                payload = self._fetch(CHART_URL.format(id=_coin_id(addr), span=span))
                out[sym] = _parse_chart(payload, addr, sym)
            return out

        if start_date is None or end_date is None:
            raise InvalidDataError("price history: provide BOTH start_date and end_date")
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(f"price history: bad date(s) {start_date!r}..{end_date!r}") from exc
        if d1 < d0:
            raise InvalidDataError(f"price history: end {end_date} before start {start_date}")

        out = {}
        for sym, addr in TOKENS.items():
            out[sym] = self._paginate_chart(addr, sym, d0, d1, start_date, end_date)
        return out

    def _paginate_chart(
        self, addr: str, sym: str, d0: datetime.date, d1: datetime.date,
        start_date: str, end_date: str,
    ) -> Dict[str, float]:
        """Walk forward from d0 in ≤MAX_SPAN-day chunks, merging schema-validated pages.
        Keeps only dates within [start_date, end_date]."""
        merged: Dict[str, float] = {}
        cursor = d0
        for _ in range(self._max_pages):
            if cursor > d1:
                break
            remaining = (d1 - cursor).days + 1
            span = min(MAX_SPAN, remaining)
            url = CHART_RANGE_URL.format(id=_coin_id(addr), start=_to_unix(cursor), span=span)
            page = _parse_chart(self._fetch(url), addr, sym)  # schema-validates / raises
            for d, p in page.items():
                if start_date <= d <= end_date:
                    merged[d] = p
            last_d = max(datetime.date.fromisoformat(x) for x in page)
            if last_d >= d1:
                break
            nxt = last_d + datetime.timedelta(days=1)
            if nxt <= cursor:
                break  # no forward progress (guard)
            cursor = nxt
            if self._page_delay:
                time.sleep(self._page_delay)
        if not merged:
            raise InvalidDataError(
                f"price history: no points for {sym} in {start_date}..{end_date}"
            )
        return merged

    def history_ratios(
        self,
        span: int = 90,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Return {lrt_sym: {date: lrt/eth ratio}} aligned on shared dates with eth."""
        hist = self.history(span=span, start_date=start_date, end_date=end_date)
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
