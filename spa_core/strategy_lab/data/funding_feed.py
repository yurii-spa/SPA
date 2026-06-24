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

DEEP HISTORY (pagination — FREE, no paid data):
  Both endpoints only return the most-recent page by default. To cover a 1–2 year window we
  paginate per-venue, de-dup by funding timestamp, then take the cross-venue MEDIAN per day:
    Binance: ?startTime=<ms>&limit=1000 — ascending; loop forward, advancing startTime past the
             last returned fundingTime, until we reach end_date or a page is short/empty.
    Bybit:   ?startTime=<ms>&endTime=<ms>&limit=200 — DESCENDING, capped 200 rows/call; loop a
             sliding [startTime,endTime] window backward (end := earliest_ts-1) until we pass
             start_date or a page is short/empty.
  A polite delay separates pages; a page cap bounds total calls. Every page is schema-validated
  (raises on malformed). `history(start_date, end_date)` returns the full paginated daily median
  series; the no-arg `history()` keeps the old single-page behaviour.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import statistics
import time
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

BINANCE_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&limit={limit}"
BYBIT_URL = (
    "https://api.bybit.com/v5/market/funding/history"
    "?category=linear&symbol=ETHUSDT&limit={limit}"
)
# Paginated variants (deep history).
BINANCE_PAGE_URL = (
    "https://fapi.binance.com/fapi/v1/fundingRate"
    "?symbol=ETHUSDT&startTime={start_ms}&limit={limit}"
)
BYBIT_PAGE_URL = (
    "https://api.bybit.com/v5/market/funding/history"
    "?category=linear&symbol=ETHUSDT&startTime={start_ms}&endTime={end_ms}&limit={limit}"
)

# Pagination knobs (FREE keyless endpoints — be polite, bound total work).
BINANCE_PAGE_LIMIT = 1000   # Binance fundingRate page cap (~111 days @ 3 settles/day)
BYBIT_PAGE_LIMIT = 200      # Bybit funding/history hard cap per call
PAGE_DELAY_S = 0.25         # polite delay between page fetches
MAX_PAGES = 60              # safety cap on total page fetches per venue (~years of depth)
_DAY_MS = 86_400_000

Fetcher = Callable[[str], object]


def _date_from_ms(ms: int) -> str:
    return datetime.datetime.fromtimestamp(
        ms / 1000.0, tz=datetime.timezone.utc
    ).date().isoformat()


def _to_ms(d: datetime.date) -> int:
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)


# ── per-venue ROW parsers (schema-validate, return (ts_ms, rate) rows for de-dup) ──────────
def _rows_binance(payload: object) -> List[Tuple[int, float]]:
    """Binance fundingRate → [(ts_ms, rate)]. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, list) or not payload:
        raise InvalidDataError(f"binance funding: expected non-empty list, got {type(payload).__name__}")
    rows: List[Tuple[int, float]] = []
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
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("binance funding: produced no datapoints")
    return rows


def _rows_bybit(payload: object) -> List[Tuple[int, float]]:
    """Bybit funding history → [(ts_ms, rate)]. Raises on bad schema / empty / missing field."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"bybit funding: expected object, got {type(payload).__name__}")
    if payload.get("retCode") != 0:
        raise InvalidDataError(f"bybit funding: retCode={payload.get('retCode')} ({payload.get('retMsg')})")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise InvalidDataError("bybit funding: missing 'result' object")
    raw = result.get("list")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("bybit funding: 'result.list' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
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
        rows.append((ts_ms, rate))
    if not rows:
        raise InvalidDataError("bybit funding: produced no datapoints")
    return rows


def _rows_to_by_date(rows: Dict[int, float]) -> Dict[str, List[float]]:
    """De-duped {ts_ms: rate} → {date(ISO): [rate, ...]}."""
    out: Dict[str, List[float]] = {}
    for ts_ms, rate in rows.items():
        out.setdefault(_date_from_ms(ts_ms), []).append(rate)
    return out


def _parse_binance(payload: object) -> Dict[str, List[float]]:
    """Binance fundingRate → {date: [rate, ...]}. Raises on bad schema / empty / missing field."""
    return _rows_to_by_date(dict(_rows_binance(payload)))


def _parse_bybit(payload: object) -> Dict[str, List[float]]:
    """Bybit funding history → {date: [rate, ...]}. Raises on bad schema / empty / missing field."""
    return _rows_to_by_date(dict(_rows_bybit(payload)))


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

    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        limit: int = 200,
        page_delay_s: float = PAGE_DELAY_S,
        max_pages: int = MAX_PAGES,
    ):
        self._fetch = fetcher or http_fetch
        self._limit = limit
        self._page_delay = page_delay_s
        self._max_pages = max_pages

    # ── history (single-page default + deep paginated window) ───────────────────────────────
    def history(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, float]:
        """date(ISO) -> median 8h funding (decimal).

        With no args: the original single-page behaviour (most-recent page only).
        With start_date/end_date (ISO): page BOTH venues across the window, de-dup each venue by
        funding timestamp, then take the cross-venue per-day median. Every page is schema-validated
        (raises on malformed). Days strictly inside [start_date, end_date] are kept."""
        if start_date is None and end_date is None:
            binance = _parse_binance(self._fetch(BINANCE_URL.format(limit=self._limit)))
            bybit = _parse_bybit(self._fetch(BYBIT_URL.format(limit=self._limit)))
            merged = _merge_median([binance, bybit])
            if not merged:
                raise InvalidDataError("funding: merged series empty")
            return merged

        if start_date is None or end_date is None:
            raise InvalidDataError("funding history: provide BOTH start_date and end_date")
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(f"funding history: bad date(s) {start_date!r}..{end_date!r}") from exc
        if d1 < d0:
            raise InvalidDataError(f"funding history: end {end_date} before start {start_date}")

        binance_rows = self._paginate_binance(d0, d1)
        bybit_rows = self._paginate_bybit(d0, d1)
        binance = _rows_to_by_date(binance_rows)
        bybit = _rows_to_by_date(bybit_rows)
        merged = _merge_median([binance, bybit])
        # keep only days within the requested window
        merged = {d: v for d, v in merged.items() if start_date <= d <= end_date}
        if not merged:
            raise InvalidDataError(
                f"funding history: empty after paginating {start_date}..{end_date}"
            )
        return merged

    def _paginate_binance(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """Binance: ascending pages from startTime forward. De-dup by ts_ms. Stop at end_date,
        an empty/short page, or no forward progress."""
        end_ms = _to_ms(d1) + _DAY_MS  # inclusive of d1's last settle
        cursor_ms = _to_ms(d0)
        rows: Dict[int, float] = {}
        for _ in range(self._max_pages):
            url = BINANCE_PAGE_URL.format(start_ms=cursor_ms, limit=BINANCE_PAGE_LIMIT)
            page = _rows_binance(self._fetch(url))  # schema-validates / raises
            new_max = cursor_ms
            for ts_ms, rate in page:
                if ts_ms > end_ms:
                    continue
                rows[ts_ms] = rate
                if ts_ms > new_max:
                    new_max = ts_ms
            last_ts = max(ts for ts, _ in page)
            if last_ts > end_ms or len(page) < BINANCE_PAGE_LIMIT:
                break  # reached the window end or the live edge
            if new_max <= cursor_ms:
                break  # no forward progress (guard against infinite loop)
            cursor_ms = last_ts + 1
            if self._page_delay:
                time.sleep(self._page_delay)
        return rows

    def _paginate_bybit(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """Bybit: DESCENDING pages over a sliding [startTime,endTime] window, walking backward.
        De-dup by ts_ms. Stop at start_date, an empty/short page, or no backward progress."""
        start_ms = _to_ms(d0)
        window_end_ms = _to_ms(d1) + _DAY_MS
        rows: Dict[int, float] = {}
        for _ in range(self._max_pages):
            url = BYBIT_PAGE_URL.format(
                start_ms=start_ms, end_ms=window_end_ms, limit=BYBIT_PAGE_LIMIT
            )
            page = _rows_bybit(self._fetch(url))  # schema-validates / raises
            earliest = min(ts for ts, _ in page)
            for ts_ms, rate in page:
                if ts_ms < start_ms:
                    continue
                rows[ts_ms] = rate
            if earliest <= start_ms or len(page) < BYBIT_PAGE_LIMIT:
                break  # reached the window start or the venue's history edge
            new_end = earliest - 1
            if new_end >= window_end_ms:
                break  # no backward progress (guard against infinite loop)
            window_end_ms = new_end
            if self._page_delay:
                time.sleep(self._page_delay)
        return rows

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
