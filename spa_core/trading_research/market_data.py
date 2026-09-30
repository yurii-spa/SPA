"""Market data: CLOSED candles only, one base timeframe, deterministic aggregation.

Design (lessons from earn-defi 2026-09-18, where a still-open daily candle was stored as a «close»
and later tripped a false kill condition):
  * Only candles whose close time is in the PAST (plus a grace period) are stored. An open candle is
    never written, so there is nothing to «update» later.
  * Stored candles are never updated. A re-fetch that disagrees with a stored closed candle is
    recorded as a data conflict, not silently applied.
  * Base timeframe is 1h (Binance spot, public endpoint, history since 2017-08). Higher timeframes are
    AGGREGATED deterministically from 1h, UTC-aligned, and a bucket is produced only when every
    constituent hour exists — a gap is a missing bar, never an interpolated one.
  * Funding (for the perpetual paper model) comes from Binance USDⓈ-M public funding history.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

HOUR_MS = 3_600_000
TF_MS = {"1h": HOUR_MS, "2h": 2 * HOUR_MS, "4h": 4 * HOUR_MS, "8h": 8 * HOUR_MS, "12h": 12 * HOUR_MS,
         "1D": 24 * HOUR_MS, "1W": 7 * 24 * HOUR_MS}
#: Monday 1970-01-05 00:00 UTC — weekly buckets start on Mondays (as Binance does).
WEEK_ANCHOR_MS = 4 * 24 * HOUR_MS
CLOSE_GRACE_MS = 60_000           # a candle counts as closed 60 s after its close time
BINANCE_SPOT = "https://api.binance.com/api/v3/klines"
BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
SOURCE = "binance_spot"
FIRST_1H_MS = 1502942400000       # 2017-08-17 04:00 UTC, first BTCUSDT 1h candle on Binance


@dataclass(frozen=True)
class Bar:
    open_time: int      # ms, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


def bar_close_time(open_time: int, tf: str) -> int:
    return open_time + TF_MS[tf]


SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT NOT NULL, tf TEXT NOT NULL, open_time INTEGER NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
  source TEXT NOT NULL, fetched_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, tf, open_time)
);
CREATE TRIGGER IF NOT EXISTS candles_no_update BEFORE UPDATE ON candles
  BEGIN SELECT RAISE(ABORT, 'closed candles are immutable'); END;
CREATE TRIGGER IF NOT EXISTS candles_no_delete BEFORE DELETE ON candles
  BEGIN SELECT RAISE(ABORT, 'closed candles are immutable'); END;
CREATE TABLE IF NOT EXISTS funding (
  symbol TEXT NOT NULL, funding_time INTEGER NOT NULL, rate REAL NOT NULL, fetched_at INTEGER NOT NULL,
  PRIMARY KEY (symbol, funding_time)
);
CREATE TABLE IF NOT EXISTS data_conflicts (
  symbol TEXT, tf TEXT, open_time INTEGER, stored TEXT, refetched TEXT, seen_at INTEGER
);
"""


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.executescript(SCHEMA)
    return conn


def _http_json(url: str, params: dict, timeout: float = 20.0):
    q = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(q, headers={"User-Agent": "spa-trading-research/0 (read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # GET only — public market data
        return json.loads(r.read().decode("utf-8"))


def fetch_klines_binance(symbol: str, start_ms: int, *, limit: int = 1000,
                         http: Callable = _http_json) -> list:
    """Raw 1h klines from Binance spot starting at start_ms (public, no key)."""
    return http(BINANCE_SPOT, {"symbol": symbol, "interval": "1h", "startTime": start_ms, "limit": limit})


def store_closed_klines(conn: sqlite3.Connection, symbol: str, rows: list, *, now_ms: int) -> int:
    """Insert only CLOSED 1h candles. Returns how many new rows were stored."""
    new = 0
    for k in rows:
        open_time, close_time = int(k[0]), int(k[6])
        if close_time + CLOSE_GRACE_MS > now_ms:
            continue                                   # still open (or just closed) — never stored
        vals = (float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
        cur = conn.execute("SELECT open,high,low,close,volume FROM candles WHERE symbol=? AND tf='1h' "
                           "AND open_time=?", (symbol, open_time)).fetchone()
        if cur is None:
            conn.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (symbol, "1h", open_time, *vals, SOURCE, now_ms))
            new += 1
        elif tuple(round(x, 8) for x in cur) != tuple(round(x, 8) for x in vals):
            conn.execute("INSERT INTO data_conflicts VALUES (?,?,?,?,?,?)",
                         (symbol, "1h", open_time, json.dumps(cur), json.dumps(vals), now_ms))
    conn.commit()
    return new


def last_open_time(conn: sqlite3.Connection, symbol: str, tf: str = "1h") -> Optional[int]:
    r = conn.execute("SELECT MAX(open_time) FROM candles WHERE symbol=? AND tf=?", (symbol, tf)).fetchone()
    return r[0] if r and r[0] is not None else None


def sync_1h(conn: sqlite3.Connection, symbol: str, *, now_ms: Optional[int] = None,
            http: Callable = _http_json, max_requests: int = 200, sleep_s: float = 0.2) -> dict:
    """Catch up 1h candles from the last stored one (or Binance's first) to now. Idempotent."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    last = last_open_time(conn, symbol)
    start = FIRST_1H_MS if last is None else last + HOUR_MS
    stored, requests = 0, 0
    while start + HOUR_MS + CLOSE_GRACE_MS <= now_ms and requests < max_requests:
        rows = fetch_klines_binance(symbol, start, http=http)
        requests += 1
        if not rows:
            break
        stored += store_closed_klines(conn, symbol, rows, now_ms=now_ms)
        nxt = int(rows[-1][0]) + HOUR_MS
        if nxt <= start:
            break
        start = nxt
        if sleep_s and len(rows) >= 1000:
            time.sleep(sleep_s)
    return {"symbol": symbol, "stored": stored, "requests": requests,
            "last_open_time": last_open_time(conn, symbol)}


def sync_funding(conn: sqlite3.Connection, symbol: str, *, now_ms: Optional[int] = None,
                 http: Callable = _http_json, max_requests: int = 50) -> int:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    r = conn.execute("SELECT MAX(funding_time) FROM funding WHERE symbol=?", (symbol,)).fetchone()
    start = (r[0] + 1) if r and r[0] else 1567296000000   # 2019-09-01
    n = 0
    for _ in range(max_requests):
        rows = http(BINANCE_FUNDING, {"symbol": symbol, "startTime": start, "limit": 1000})
        if not rows:
            break
        for x in rows:
            ft = int(x["fundingTime"])
            if ft <= now_ms:
                n += conn.execute("INSERT OR IGNORE INTO funding VALUES (?,?,?,?)",
                                  (symbol, ft, float(x["fundingRate"]), now_ms)).rowcount
        start = int(rows[-1]["fundingTime"]) + 1
        if len(rows) < 1000:
            break
    conn.commit()
    return n


def load_1h(conn: sqlite3.Connection, symbol: str, *, since_ms: int = 0,
            until_ms: Optional[int] = None) -> List[Bar]:
    q = "SELECT open_time,open,high,low,close,volume FROM candles WHERE symbol=? AND tf='1h' AND open_time>=?"
    args: list = [symbol, since_ms]
    if until_ms is not None:
        q += " AND open_time<?"
        args.append(until_ms)
    return [Bar(*row) for row in conn.execute(q + " ORDER BY open_time", args)]


def bucket_start(open_time: int, tf: str) -> int:
    size = TF_MS[tf]
    if tf == "1W":
        return open_time - ((open_time - WEEK_ANCHOR_MS) % size)
    return open_time - (open_time % size)


def aggregate(bars_1h: Iterable[Bar], tf: str) -> List[Bar]:
    """UTC-aligned aggregation. A bucket is emitted only when ALL its hours are present."""
    if tf == "1h":
        return list(bars_1h)
    need = TF_MS[tf] // HOUR_MS
    out: List[Bar] = []
    cur_key, cur = None, []
    for b in bars_1h:
        k = bucket_start(b.open_time, tf)
        if k != cur_key:
            if cur_key is not None and len(cur) == need:
                out.append(_merge(cur_key, cur))
            cur_key, cur = k, []
        cur.append(b)
    if cur_key is not None and len(cur) == need:
        out.append(_merge(cur_key, cur))
    return out


def _merge(key: int, bs: List[Bar]) -> Bar:
    return Bar(key, bs[0].open, max(b.high for b in bs), min(b.low for b in bs), bs[-1].close,
               sum(b.volume for b in bs))


def gaps_1h(bars: List[Bar]) -> List[Dict[str, int]]:
    """Missing hours inside the stored range — reported, never filled."""
    out = []
    for a, b in zip(bars, bars[1:]):
        if b.open_time - a.open_time != HOUR_MS:
            out.append({"after": a.open_time, "missing_hours": (b.open_time - a.open_time) // HOUR_MS - 1})
    return out


def funding_series(conn: sqlite3.Connection, symbol: str) -> List[tuple]:
    return list(conn.execute("SELECT funding_time, rate FROM funding WHERE symbol=? ORDER BY funding_time",
                             (symbol,)))
