"""
spa_core/strategy_lab/data/btc_lending_feed.py — wrapped-BTC lending supply APY via DeFiLlama.

The honest BTC-yield FLOOR for the BTC sleeves (btc_neutral's small lending floor +
btc_lending_sleeve's primary income). BTC is rarely *borrowed* on-chain (utilization ~2–6%),
so safe wrapped-BTC supply APY is structurally LOW — typically ~0–1.2%. A low number here is
CORRECT, not a bug (see spa_core/adapters/btc_lending.py + docs/RESEARCH_EXPANSION_2026-06-25.md).

We deliberately track only the two SAFE wrappers:
  tBTC  (Threshold, decentralized — lowest wrapper SPOF)
  cbBTC (Coinbase, single regulated entity)
and AVOID WBTC / LBTC as holdings (wrapper governance / restaking-leverage risk).

Keyless: https://yields.llama.fi/pools → match the highest-TVL lending pool per wrapper across a
small set of (project, chain) venues, return its apy as a DECIMAL (0.004 == 0.4%). For a
historical series we resolve the pool id then fetch yields.llama.fi/chart/{pool} (same mechanism
as restaking_feed.py).

Returns {symbol(lowercase): apy_decimal}. FAIL-CLOSED: malformed payload raises InvalidDataError;
an out-of-band APY (>5% on "safe" BTC lending) is rejected as anomalous (that symbol is dropped);
a totally empty result raises (no fabricated floor). 0% is a legitimate, expected reading.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

POOLS_URL = "https://yields.llama.fi/pools"
CHART_URL = "https://yields.llama.fi/chart/{pool}"

# Honest safe-BTC-lending band (decimals). 0% is legitimate; >5% on "safe" BTC lending is an
# anomaly (mirrors adapters/btc_lending.py MIN_APY/MAX_APY) → reject that read.
MIN_APY = 0.0
MAX_APY = 0.05

# snapshot symbol -> ordered (project, chain, defillama-symbol) lending venues to probe. The
# highest-TVL live match wins (mirrors adapters/btc_lending.py venue lists; WBTC/LBTC excluded).
SELECTORS: Dict[str, List[Tuple[str, str, str]]] = {
    "tbtc": [
        ("aave-v3", "Ethereum", "TBTC"),
        ("aave-v3", "Arbitrum", "TBTC"),
        ("compound-v3", "Ethereum", "TBTC"),
        ("morpho-blue", "Ethereum", "TBTC"),
    ],
    "cbbtc": [
        ("aave-v3", "Ethereum", "CBBTC"),
        ("aave-v3", "Base", "CBBTC"),
        ("compound-v3", "Ethereum", "CBBTC"),
        ("morpho-blue", "Ethereum", "CBBTC"),
        ("morpho-blue", "Base", "CBBTC"),
    ],
}

Fetcher = Callable[[str], object]


def _validate_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise InvalidDataError(f"btc yields pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"btc yields pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise InvalidDataError("btc yields pools: 'data' missing or empty")
    return data


def _best_pool(pools: List[dict], venues: List[Tuple[str, str, str]]) -> Optional[dict]:
    """Highest-TVL pool across the configured (project, chain, symbol) venues, or None."""
    best, best_tvl = None, float("-inf")
    for proj, chain, sym in venues:
        sym_u = sym.upper()
        for p in pools:
            if not isinstance(p, dict):
                continue
            if p.get("project") != proj or p.get("chain") != chain:
                continue
            if (p.get("symbol") or "").upper() != sym_u:
                continue
            tvl = p.get("tvlUsd")
            tvl = float(tvl) if isinstance(tvl, (int, float)) and not isinstance(tvl, bool) else 0.0
            if tvl > best_tvl:
                best_tvl, best = tvl, p
    return best


def _apy_decimal(pool: Optional[dict], sym: str) -> Optional[float]:
    """Pool apy (percent) → decimal, rejecting anomalous (>MAX_APY) reads. None on miss."""
    if pool is None:
        return None
    raw = pool.get("apy")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw < 0:
        return None
    apy = float(raw) / 100.0
    if apy < MIN_APY or apy > MAX_APY:
        return None  # anomalous for "safe" BTC lending → drop this symbol (fail-closed)
    return apy


def _parse_apy_chart(payload: object, sym: str) -> Dict[str, float]:
    """yields.llama.fi/chart/{pool} → {date(ISO): apy_decimal}. One point per UTC day (last
    wins). Raises on bad schema; anomalous-band points are skipped (not fabricated)."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"btc yields chart: expected object for {sym}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"btc yields chart: status={payload.get('status')!r} for {sym}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise InvalidDataError(f"btc yields chart: 'data' not a list for {sym}")
    out: Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            raise InvalidDataError(f"btc yields chart: row not an object for {sym}")
        ts = row.get("timestamp")
        apy = row.get("apy")
        if not isinstance(ts, str) or not ts:
            raise InvalidDataError(f"btc yields chart: missing/invalid timestamp for {sym}")
        if apy is None:
            continue
        if not isinstance(apy, (int, float)) or apy < 0:
            raise InvalidDataError(f"btc yields chart: invalid apy {apy!r} for {sym}")
        dec = float(apy) / 100.0
        if dec < MIN_APY or dec > MAX_APY:
            continue  # anomalous read — skip, don't fabricate
        try:
            d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                datetime.timezone.utc
            ).date().isoformat()
        except ValueError as exc:
            raise InvalidDataError(f"btc yields chart: unparseable timestamp {ts!r} for {sym}") from exc
        out[d] = round(dec, 6)
    return out


class BtcLendingFeed:
    """tBTC/cbBTC lending supply APY (decimal). Inject `fetcher` (url->json) in tests."""

    def __init__(self, fetcher: Optional[Fetcher] = None):
        self._fetch = fetcher or http_fetch

    def apys(self) -> Dict[str, float]:
        """{symbol: apy_decimal} for every wrapper that matched a live in-band pool. Raises only
        if NO wrapper resolved at all (a totally empty result is fail-closed)."""
        pools = _validate_pools(self._fetch(POOLS_URL))
        out: Dict[str, float] = {}
        for sym, venues in SELECTORS.items():
            apy = _apy_decimal(_best_pool(pools, venues), sym)
            if apy is not None:
                out[sym] = round(apy, 6)
        if not out:
            raise InvalidDataError("btc lending: no wrapped-BTC pool matched with a valid apy")
        return out

    def history(self, start_date: str, end_date: str) -> Dict[str, Dict[str, float]]:
        """{symbol: {date(ISO): apy_decimal}} over [start_date, end_date]. Resolves each wrapper
        to its highest-TVL pool id via /pools, fetches that pool's /chart. A wrapper with no
        points in the window is simply absent; raises only if NONE resolved."""
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(
                f"btc lending history: bad date(s) {start_date!r}..{end_date!r}"
            ) from exc
        if d1 < d0:
            raise InvalidDataError(
                f"btc lending history: end {end_date} before start {start_date}"
            )

        pools = _validate_pools(self._fetch(POOLS_URL))
        out: Dict[str, Dict[str, float]] = {}
        for sym, venues in SELECTORS.items():
            best = _best_pool(pools, venues)
            if best is None:
                continue
            pid = best.get("pool")
            if not isinstance(pid, str) or not pid:
                continue
            chart = _parse_apy_chart(self._fetch(CHART_URL.format(pool=pid)), sym)
            windowed = {d: a for d, a in chart.items() if start_date <= d <= end_date}
            if windowed:
                out[sym] = windowed
        if not out:
            raise InvalidDataError(
                f"btc lending history: no wrapped-BTC pool chart had points in "
                f"{start_date}..{end_date}"
            )
        return out


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(20)
    feed = BtcLendingFeed()
    for sym, apy in feed.apys().items():
        print(f"{sym:>6} btc-lending apy = {apy * 100:.4f}%")
