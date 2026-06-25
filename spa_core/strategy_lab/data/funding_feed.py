"""
spa_core/strategy_lab/data/funding_feed.py — ETH-perp funding rate feed.

USER DECISION: funding_rate_8h = MEDIAN of ALL available keyless public ETH-perp venues per
day. The median (vs a mean) is robust to a single-venue outlier / glitch / downtime. All venues
below are keyless public endpoints. If a venue is down/empty for a day, the median is taken over
the venues that DID return — a day is only dropped if NO venue had data.

VENUES (all public, keyless, ETH-USD(T) perp funding-rate history):
  Binance: https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT
           → list[ {"symbol","fundingTime"(ms int),"fundingRate"(str), ...} ]            (8h)
  Bybit:   https://api.bybit.com/v5/market/funding/history?category=linear&symbol=ETHUSDT
           → {"retCode":0,"result":{"list":[ {"symbol","fundingRate"(str),
              "fundingRateTimestamp"(ms str)} ]}}                                          (8h)
  OKX:     https://www.okx.com/api/v5/public/funding-rate-history?instId=ETH-USDT-SWAP
           → {"code":"0","data":[ {"fundingRate"(str),"fundingTime"(ms str), ...} ]}       (8h)
  KuCoin:  https://api-futures.kucoin.com/api/v1/contract/funding-rates?symbol=ETHUSDTM
           → {"code":"200000","data":[ {"symbol","fundingRate"(float),"timepoint"(ms int)} ]} (8h)
  Hyperliquid (on-chain perp DEX): https://api.hyperliquid.xyz/info  POST
           {"type":"fundingHistory","coin":"ETH","startTime":<ms>}
           → list[ {"coin","fundingRate"(str),"premium"(str),"time"(ms int)} ]            (HOURLY)

Binance/Bybit/OKX/KuCoin settle ETH perp funding every 8h, so a raw entry IS already an "8h"
rate. We bucket each venue's entries by UTC date and take the median across ALL venues' entries
for that date — i.e. the median 8h funding observed on that day.

HYPERLIQUID HOURLY → DAILY-8h NORMALIZATION:
  Hyperliquid pays funding EVERY HOUR, so a single HL entry is a 1h rate and is ~8× smaller than
  an 8h rate from the other venues. Putting raw HL hourly rates into the same median would bias
  the median downward. We make HL comparable by AGGREGATING each UTC day's hourly fundings into a
  daily total, then dividing by 3 to express it as a per-8h-period rate (a day has three 8h
  settlement periods on the other venues). I.e.:
       hl_8h_equiv(day) = (sum of that day's hourly fundingRates) / 3
  This converts HL's hourly accrual into the SAME "rate per 8h settlement" unit the other four
  venues report, so all five sit in one comparable per-day median. (Summing the day's hourly
  rates recovers the realized daily funding; /3 re-expresses it per 8h period.) The normalization
  is intentionally simple/linear and deterministic — no compounding assumption.

FAIL-CLOSED: if a venue response is not the expected structure, or a funding field is missing /
empty / unparseable, that venue's parser raises InvalidDataError. The per-day median is only
computed over venues that returned cleanly; the whole call only raises if NO venue produced any
datapoint for the window. No silent default, no fabricated value.

DEEP HISTORY (pagination — FREE, no paid data):
  Each venue paginates its own way; every page is schema-validated (raises on malformed):
    Binance: ?startTime=<ms>&limit=1000 — ascending; loop forward.
    Bybit:   ?startTime=<ms>&endTime=<ms>&limit=200 — DESCENDING window walked backward.
    OKX:     ?after=<ms>&limit=100 — DESCENDING; `after` returns records OLDER than the cursor;
             walk backward until before start or a short page.
    KuCoin:  ?from=<ms>&to=<ms> — returns the whole window in one shot (no pagination needed).
    Hyperliquid: POST startTime=<ms> — ascending HOURLY; loop forward advancing startTime.
  A polite delay separates pages; a page cap bounds total calls. `history(start_date, end_date)`
  returns the full paginated daily median series; the no-arg `history()` keeps the old
  single-page behaviour (most-recent page of each venue).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import statistics
import time
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

# ── per-symbol venue tickers ───────────────────────────────────────────────────────────────
# The five venues each name the ETH/BTC perp differently. A FundingFeed is built for ONE asset
# (default "ETH" → ETHUSDT etc.); pass symbol="BTC" for the BTCUSDT perp. Hyperliquid uses the
# bare coin ("ETH"/"BTC") in its POST body. Adding a new asset = one row here.
VENUE_TICKERS: Dict[str, Dict[str, str]] = {
    "ETH": {
        "binance": "ETHUSDT",
        "bybit": "ETHUSDT",
        "okx": "ETH-USDT-SWAP",
        "kucoin": "ETHUSDTM",
        "hyperliquid": "ETH",
    },
    "BTC": {
        "binance": "BTCUSDT",
        "bybit": "BTCUSDT",
        "okx": "BTC-USDT-SWAP",
        "kucoin": "XBTUSDTM",   # KuCoin futures uses XBT for Bitcoin
        "hyperliquid": "BTC",
    },
}

# ── single-page (most-recent) URL templates (the venue ticker is filled per-asset) ──────────
BINANCE_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit={limit}"
BYBIT_URL = (
    "https://api.bybit.com/v5/market/funding/history"
    "?category=linear&symbol={sym}&limit={limit}"
)
OKX_URL = (
    "https://www.okx.com/api/v5/public/funding-rate-history"
    "?instId={sym}&limit={limit}"
)
KUCOIN_URL = (
    "https://api-futures.kucoin.com/api/v1/contract/funding-rates"
    "?symbol={sym}&from={start_ms}&to={end_ms}"
)
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"  # POST body carries the query

# ── paginated (deep history) URL templates ─────────────────────────────────────────────────
BINANCE_PAGE_URL = (
    "https://fapi.binance.com/fapi/v1/fundingRate"
    "?symbol={sym}&startTime={start_ms}&limit={limit}"
)
BYBIT_PAGE_URL = (
    "https://api.bybit.com/v5/market/funding/history"
    "?category=linear&symbol={sym}&startTime={start_ms}&endTime={end_ms}&limit={limit}"
)
OKX_PAGE_URL = (
    "https://www.okx.com/api/v5/public/funding-rate-history"
    "?instId={sym}&after={after_ms}&limit={limit}"
)
# KuCoin takes the whole window directly (shares KUCOIN_URL).

# Pagination knobs (FREE keyless endpoints — be polite, bound total work).
BINANCE_PAGE_LIMIT = 1000   # Binance fundingRate page cap (~111 days @ 3 settles/day)
BYBIT_PAGE_LIMIT = 200      # Bybit funding/history hard cap per call
OKX_PAGE_LIMIT = 100        # OKX funding-rate-history hard cap per call
HL_HOURS_PER_8H = 3.0       # three 8h settlement periods per UTC day on the 8h venues
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


def _rows_okx(payload: object) -> List[Tuple[int, float]]:
    """OKX funding-rate-history → [(ts_ms, rate)]. Raises on bad schema / empty / missing field.

    Schema: {"code":"0","msg":"","data":[ {"fundingRate":str,"fundingTime":str(ms), ...} ]}.
    OKX `code` is a STRING ("0" = ok). 8h settlement."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"okx funding: expected object, got {type(payload).__name__}")
    if str(payload.get("code")) != "0":
        raise InvalidDataError(f"okx funding: code={payload.get('code')!r} ({payload.get('msg')!r})")
    raw = payload.get("data")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("okx funding: 'data' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise InvalidDataError("okx funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("okx funding: missing/empty 'fundingRate'")
        ts = row.get("fundingTime")
        try:
            ts_ms = int(ts)
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"okx funding: invalid 'fundingTime' {ts!r}") from exc
        try:
            rate = float(row["fundingRate"])
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"okx funding: unparseable rate {row.get('fundingRate')!r}") from exc
        rows.append((ts_ms, rate))
    if not rows:
        raise InvalidDataError("okx funding: produced no datapoints")
    return rows


def _rows_kucoin(payload: object) -> List[Tuple[int, float]]:
    """KuCoin futures funding-rates → [(ts_ms, rate)]. Raises on bad schema / empty / missing.

    Schema: {"code":"200000","data":[ {"symbol","fundingRate":float,"timepoint":int(ms)} ]}.
    KuCoin `code` is a STRING ("200000" = ok). 8h settlement."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"kucoin funding: expected object, got {type(payload).__name__}")
    if str(payload.get("code")) != "200000":
        raise InvalidDataError(f"kucoin funding: code={payload.get('code')!r} ({payload.get('msg')!r})")
    raw = payload.get("data")
    if not isinstance(raw, list) or not raw:
        raise InvalidDataError("kucoin funding: 'data' missing or empty")
    rows: List[Tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise InvalidDataError("kucoin funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("kucoin funding: missing/empty 'fundingRate'")
        ts = row.get("timepoint")
        if not isinstance(ts, (int, float)):
            raise InvalidDataError(f"kucoin funding: missing/invalid 'timepoint' {ts!r}")
        try:
            rate = float(row["fundingRate"])
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"kucoin funding: unparseable rate {row.get('fundingRate')!r}") from exc
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("kucoin funding: produced no datapoints")
    return rows


def _rows_hyperliquid(payload: object) -> List[Tuple[int, float]]:
    """Hyperliquid fundingHistory → [(ts_ms, HOURLY rate)]. Raises on bad schema / empty / missing.

    Schema: list[ {"coin","fundingRate":str,"premium":str,"time":int(ms)} ]. These are HOURLY
    rates — callers must normalize via _hl_8h_by_date before mixing with the 8h venues."""
    if not isinstance(payload, list) or not payload:
        raise InvalidDataError(f"hyperliquid funding: expected non-empty list, got {type(payload).__name__}")
    rows: List[Tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise InvalidDataError("hyperliquid funding: row is not an object")
        if "fundingRate" not in row or row.get("fundingRate") in (None, ""):
            raise InvalidDataError("hyperliquid funding: missing/empty 'fundingRate'")
        ts = row.get("time")
        if not isinstance(ts, (int, float)):
            raise InvalidDataError(f"hyperliquid funding: missing/invalid 'time' {ts!r}")
        try:
            rate = float(row["fundingRate"])
        except (TypeError, ValueError) as exc:
            raise InvalidDataError(f"hyperliquid funding: unparseable rate {row.get('fundingRate')!r}") from exc
        rows.append((int(ts), rate))
    if not rows:
        raise InvalidDataError("hyperliquid funding: produced no datapoints")
    return rows


def _rows_to_by_date(rows: Dict[int, float]) -> Dict[str, List[float]]:
    """De-duped {ts_ms: rate} → {date(ISO): [rate, ...]} (8h-rate venues)."""
    out: Dict[str, List[float]] = {}
    for ts_ms, rate in rows.items():
        out.setdefault(_date_from_ms(ts_ms), []).append(rate)
    return out


def _hl_8h_by_date(rows: Dict[int, float]) -> Dict[str, List[float]]:
    """De-duped Hyperliquid HOURLY {ts_ms: rate} → {date: [hl_8h_equiv]} (a single value/day).

    Per the module docstring: sum the day's hourly fundings, divide by 3 → a per-8h-period rate
    comparable to the 8h venues. Returned as a one-element list so it slots into the same union
    median as the other venues (one 8h-equivalent observation per HL day)."""
    daily_sum: Dict[str, float] = {}
    for ts_ms, rate in rows.items():
        daily_sum.setdefault(_date_from_ms(ts_ms), 0.0)
        daily_sum[_date_from_ms(ts_ms)] += rate
    return {date: [total / HL_HOURS_PER_8H] for date, total in daily_sum.items()}


def _parse_binance(payload: object) -> Dict[str, List[float]]:
    return _rows_to_by_date(dict(_rows_binance(payload)))


def _parse_bybit(payload: object) -> Dict[str, List[float]]:
    return _rows_to_by_date(dict(_rows_bybit(payload)))


def _parse_okx(payload: object) -> Dict[str, List[float]]:
    return _rows_to_by_date(dict(_rows_okx(payload)))


def _parse_kucoin(payload: object) -> Dict[str, List[float]]:
    return _rows_to_by_date(dict(_rows_kucoin(payload)))


def _parse_hyperliquid(payload: object) -> Dict[str, List[float]]:
    return _hl_8h_by_date(dict(_rows_hyperliquid(payload)))


def _merge_median(by_venue: List[Dict[str, List[float]]]) -> Dict[str, float]:
    """For each date, median across ALL entries from ALL venues for that date.

    Combines every venue's 8h(-equivalent) funding observations on a day into one robust 8h rate.
    A single-venue outlier is pulled toward the cross-venue middle. Venues that contributed
    nothing for a day simply don't appear — the median is over whoever did."""
    union: Dict[str, List[float]] = {}
    for venue in by_venue:
        for date, rates in venue.items():
            union.setdefault(date, []).extend(rates)
    return {date: float(statistics.median(rates)) for date, rates in union.items() if rates}


def _try_venue(fn: Callable[[], Dict[str, List[float]]]) -> Dict[str, List[float]]:
    """Run a venue parse; on InvalidDataError/FetchError return {} so the median uses the rest.

    Fail-OPEN per-venue (a single venue down must not drop the whole day); the CALL still
    fails-closed overall because `history()` raises if the merged series ends up empty."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — any venue-level failure → contribute nothing, never fabricate
        return {}


# ── public API ────────────────────────────────────────────────────────────────────────────
class FundingFeed:
    """Median perp 8h funding across Binance + Bybit + OKX + KuCoin + Hyperliquid, for ONE asset.

    `symbol` selects the perp asset: "ETH" (default — back-compat, the ETHUSDT perp) or "BTC"
    (the BTCUSDT perp). The 5-venue median + Hyperliquid hourly→8h normalization are identical
    for both; only the per-venue ticker differs (see VENUE_TICKERS).

    Inject `fetcher` (url->json) in tests. Per-venue failures are tolerated (median of the rest);
    the call only raises if NO venue produced data."""

    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        limit: int = 200,
        page_delay_s: float = PAGE_DELAY_S,
        max_pages: int = MAX_PAGES,
        symbol: str = "ETH",
    ):
        self._fetch = fetcher or http_fetch
        self._limit = limit
        self._page_delay = page_delay_s
        self._max_pages = max_pages
        sym = (symbol or "ETH").upper()
        if sym not in VENUE_TICKERS:
            raise InvalidDataError(
                f"funding: unsupported symbol {symbol!r} (known: {sorted(VENUE_TICKERS)})"
            )
        self._symbol = sym
        self._tickers = VENUE_TICKERS[sym]

    # ── Hyperliquid POST helper (its query is a JSON body, not a query string) ──────────────
    def _fetch_hyperliquid(self, start_ms: int) -> object:
        """POST {"type":"fundingHistory","coin":<ETH|BTC>,"startTime":<ms>} to the HL info
        endpoint.

        The injected test fetcher only takes a url string, so encode the query into the url as a
        fragment the FakeFetcher can route on ('hyperliquid'); the REAL http_fetch path issues a
        proper POST. We detect the real fetcher by capability, not type."""
        coin = self._tickers["hyperliquid"]
        body = {"type": "fundingHistory", "coin": coin, "startTime": int(start_ms)}
        if self._fetch is http_fetch:
            return http_fetch(HYPERLIQUID_URL, post_json=body)
        # injected (test) fetcher: pass a routable url carrying the coin + startTime
        return self._fetch(
            f"{HYPERLIQUID_URL}#fundingHistory&coin={coin}&startTime={int(start_ms)}"
        )

    # ── history (single-page default + deep paginated window) ───────────────────────────────
    def history(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, float]:
        """date(ISO) -> median 8h funding (decimal) across all available venues.

        With no args: original single-page behaviour (most-recent page of each venue).
        With start_date/end_date (ISO): page every venue across the window, de-dup each by funding
        timestamp, normalize Hyperliquid hourly→8h, then take the cross-venue per-day median.
        Every page is schema-validated. A venue that fails for the whole call contributes nothing;
        only an EMPTY merged series raises."""
        if start_date is None and end_date is None:
            now_ms = int(time.time() * 1000)
            day_ago = now_ms - _DAY_MS
            binance = _try_venue(lambda: _parse_binance(
                self._fetch(BINANCE_URL.format(sym=self._tickers["binance"], limit=self._limit))))
            bybit = _try_venue(lambda: _parse_bybit(
                self._fetch(BYBIT_URL.format(sym=self._tickers["bybit"], limit=self._limit))))
            okx = _try_venue(lambda: _parse_okx(
                self._fetch(OKX_URL.format(sym=self._tickers["okx"], limit=self._limit))))
            kucoin = _try_venue(lambda: _parse_kucoin(self._fetch(KUCOIN_URL.format(
                sym=self._tickers["kucoin"], start_ms=day_ago - 7 * _DAY_MS, end_ms=now_ms))))
            hyperliquid = _try_venue(lambda: _parse_hyperliquid(
                self._fetch_hyperliquid(now_ms - 7 * _DAY_MS)))
            merged = _merge_median([binance, bybit, okx, kucoin, hyperliquid])
            if not merged:
                raise InvalidDataError("funding: merged series empty (no venue returned data)")
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

        binance = _try_venue(lambda: _rows_to_by_date(self._paginate_binance(d0, d1)))
        bybit = _try_venue(lambda: _rows_to_by_date(self._paginate_bybit(d0, d1)))
        okx = _try_venue(lambda: _rows_to_by_date(self._paginate_okx(d0, d1)))
        kucoin = _try_venue(lambda: _rows_to_by_date(self._fetch_kucoin_window(d0, d1)))
        hyperliquid = _try_venue(lambda: _hl_8h_by_date(self._paginate_hyperliquid(d0, d1)))
        merged = _merge_median([binance, bybit, okx, kucoin, hyperliquid])
        # keep only days within the requested window
        merged = {d: v for d, v in merged.items() if start_date <= d <= end_date}
        if not merged:
            raise InvalidDataError(
                f"funding history: empty after paginating {start_date}..{end_date} (no venue had data)"
            )
        return merged

    def _paginate_binance(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """Binance: ascending pages from startTime forward. De-dup by ts_ms. Stop at end_date,
        an empty/short page, or no forward progress."""
        end_ms = _to_ms(d1) + _DAY_MS  # inclusive of d1's last settle
        cursor_ms = _to_ms(d0)
        rows: Dict[int, float] = {}
        for _ in range(self._max_pages):
            url = BINANCE_PAGE_URL.format(
                sym=self._tickers["binance"], start_ms=cursor_ms, limit=BINANCE_PAGE_LIMIT
            )
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
                sym=self._tickers["bybit"], start_ms=start_ms, end_ms=window_end_ms,
                limit=BYBIT_PAGE_LIMIT,
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

    def _paginate_okx(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """OKX: DESCENDING pages via `after=<cursor>` (returns records OLDER than cursor). Walk
        backward from d1's end until before start_date, a short/empty page, or no progress."""
        start_ms = _to_ms(d0)
        cursor_ms = _to_ms(d1) + _DAY_MS  # ask for records older than the day after d1
        rows: Dict[int, float] = {}
        for _ in range(self._max_pages):
            url = OKX_PAGE_URL.format(
                sym=self._tickers["okx"], after_ms=cursor_ms, limit=OKX_PAGE_LIMIT
            )
            page = _rows_okx(self._fetch(url))  # schema-validates / raises
            earliest = min(ts for ts, _ in page)
            for ts_ms, rate in page:
                if ts_ms < start_ms:
                    continue
                rows[ts_ms] = rate
            if earliest <= start_ms or len(page) < OKX_PAGE_LIMIT:
                break  # reached the window start or the history edge
            if earliest >= cursor_ms:
                break  # no backward progress (guard)
            cursor_ms = earliest  # `after` is exclusive → next page is strictly older
            if self._page_delay:
                time.sleep(self._page_delay)
        return rows

    def _fetch_kucoin_window(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """KuCoin: the from/to endpoint returns the WHOLE window in one call (no pagination).
        Schema-validated; de-dup by ts_ms."""
        start_ms = _to_ms(d0)
        end_ms = _to_ms(d1) + _DAY_MS
        url = KUCOIN_URL.format(sym=self._tickers["kucoin"], start_ms=start_ms, end_ms=end_ms)
        page = _rows_kucoin(self._fetch(url))  # schema-validates / raises
        rows: Dict[int, float] = {}
        for ts_ms, rate in page:
            if start_ms <= ts_ms <= end_ms:
                rows[ts_ms] = rate
        return rows

    def _paginate_hyperliquid(self, d0: datetime.date, d1: datetime.date) -> Dict[int, float]:
        """Hyperliquid: ascending HOURLY pages from startTime forward (POST). De-dup by ts_ms.
        Stop at end_date, an empty/short-progress page, or no forward progress. Rates stay HOURLY
        here — normalization to 8h happens in _hl_8h_by_date downstream."""
        end_ms = _to_ms(d1) + _DAY_MS
        cursor_ms = _to_ms(d0)
        rows: Dict[int, float] = {}
        for _ in range(self._max_pages):
            page = _rows_hyperliquid(self._fetch_hyperliquid(cursor_ms))  # validates / raises
            new_max = cursor_ms
            for ts_ms, rate in page:
                if ts_ms > end_ms:
                    continue
                rows[ts_ms] = rate
                if ts_ms > new_max:
                    new_max = ts_ms
            last_ts = max(ts for ts, _ in page)
            if last_ts > end_ms:
                break  # walked past the window end
            if new_max <= cursor_ms:
                break  # no forward progress (guard / live edge)
            cursor_ms = last_ts + 1
            if self._page_delay:
                time.sleep(self._page_delay)
        return rows

    def latest(self) -> tuple[str, float]:
        """(date, median 8h funding) for the most recent available day."""
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
