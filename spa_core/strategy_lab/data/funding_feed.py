"""
spa_core/strategy_lab/data/funding_feed.py — ETH-perp funding rate feed.

USER DECISION: funding_rate_8h = MEDIAN of Binance + Bybit ETH-perp funding per day. The
median (vs a mean) is robust to a single-venue outlier / glitch. Both venues are keyless
public endpoints.

  Binance: https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT
           → list[ {"symbol","fundingTime"(ms int),"fundingRate"(str), ...} ]
  Bybit:   https://api.bybit.com/v5/market/funding/history?category=linear&symbol=ETHUSDT
           → {"retCode":0,"result":{"list":[ {"symbol","fundingRate"(str),
              "fundingRateTimestamp"(ms str)} ]}}

Both venues settle ETH-USDT perp funding every 8h, so a raw funding entry IS already an "8h"
rate. We bucket by UTC date and take the median across BOTH venues' entries for that date —
i.e. the median 8h funding observed on that day. Returns date(ISO) -> funding_rate_8h(decimal).

FAIL-CLOSED: if a response is not the expected structure, or the funding field is
missing / empty / unparseable for a venue, raise InvalidDataError. No silent default.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import statistics
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

BINANCE_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&limit={limit}"
BYBIT_URL = (
    "https://api.bybit.com/v5/market/funding/history"
    "?category=linear&symbol=ETHUSDT&limit={limit}"
)

Fetcher = Callable[[str], object]


def _date_from_ms(ms: int) -> str:
    return datetime.datetime.fromtimestamp(
        ms / 1000.0, tz=datetime.timezone.utc
    ).date().isoformat()


# ── per-venue parsers (each SCHEMA-VALIDATES and raises InvalidDataError) ──────────────────
def _parse_binance(payload: object) -> Dict[str, List[float]]:
    """Binance fundingRate → {date: [rate, ...]}. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, list) or not payload:
        raise InvalidDataError(f"binance funding: expected non-empty list, got {type(payload).__name__}")
    out: Dict[str, List[float]] = {}
    for row in payload:
        if not isinstance(row, dict):
            raise InvalidDataError("binance funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("binance funding: missing/empty 'fundingRate'")
        ts = row.get("fundingTime")
        if not isinstance(ts, (int, float)):
            raise InvalidDataError("binance funding: missing/invalid 'fundingTime'")
        try:
            rate = float(row["fundingRate"])
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"binance funding: unparseable rate {row.get('fundingRate')!r}") from exc
        out.setdefault(_date_from_ms(int(ts)), []).append(rate)
    if not out:
        raise InvalidDataError("binance funding: produced no datapoints")
    return out


def _parse_bybit(payload: object) -> Dict[str, List[float]]:
    """Bybit funding history → {date: [rate, ...]}. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"bybit funding: expected object, got {type(payload).__name__}")
    if payload.get("retCode") != 0:
        raise InvalidDataError(f"bybit funding: retCode={payload.get('retCode')} ({payload.get('retMsg')})")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise InvalidDataError("bybit funding: missing 'result' object")
    rows = result.get("list")
    if not isinstance(rows, list) or not rows:
        raise InvalidDataError("bybit funding: 'result.list' missing or empty")
    out: Dict[str, List[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidDataError("bybit funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("bybit funding: missing/empty 'fundingRate'")
        ts = row.get("fundingRateTimestamp")
        try:
            ts_ms = int(ts)
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"bybit funding: invalid timestamp {ts!r}") from exc
        try:
            rate = float(row["fundingRate"])
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"bybit funding: unparseable rate {row.get('fundingRate')!r}") from exc
        out.setdefault(_date_from_ms(ts_ms), []).append(rate)
    if not out:
        raise InvalidDataError("bybit funding: produced no datapoints")
    return out


def _merge_median(by_venue: List[Dict[str, List[float]]]) -> Dict[str, float]:
    """For each date, median across ALL entries from ALL venues for that date.

    This combines both venues' 8h funding observations on a day into one robust 8h rate.
    A single-venue outlier is pulled toward the cross-venue middle."""
    union: Dict[str, List[float]] = {}
    for venue in by_venue:
        for date, rates in venue.items():
            union.setdefault(date, []).extend(rates)
    return {date: float(statistics.median(rates)) for date, rates in union.items() if rates}


# ── public API ────────────────────────────────────────────────────────────────────────────
class FundingFeed:
    """Median Binance+Bybit ETH-perp 8h funding. Inject `fetcher` (url->json) in tests."""

    def __init__(self, fetcher: Optional[Fetcher] = None, limit: int = 200):
        self._fetch = fetcher or http_fetch
        self._limit = limit

    def history(self) -> Dict[str, float]:
        """date(ISO) -> median 8h funding (decimal). Schema-validates both venues; raises
        InvalidDataError if either is malformed. Median is taken over whatever days each venue
        returned (the union), so partial overlap still yields a usable series."""
        binance = _parse_binance(self._fetch(BINANCE_URL.format(limit=self._limit)))
        bybit = _parse_bybit(self._fetch(BYBIT_URL.format(limit=self._limit)))
        merged = _merge_median([binance, bybit])
        if not merged:
            raise InvalidDataError("funding: merged series empty")
        return merged

    def latest(self) -> tuple[str, float]:
        """(date, median 8h funding) for the most recent shared/available day."""
        hist = self.history()
        last = max(hist)
        return last, hist[last]


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(15)
    feed = FundingFeed(limit=10)
    series = feed.history()
    for d in sorted(series)[-5:]:
        print(f"{d}  funding_8h={series[d]:+.8f}")
    d, v = feed.latest()
    print(f"LATEST {d}: {v:+.8f}")
