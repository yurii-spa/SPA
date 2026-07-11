"""
spa_core/strategy_lab/data/restaking_feed.py — LRT restaking yield (APY) via DeFiLlama yields.

Keyless: https://yields.llama.fi/pools → {"status":"success","data":[ {project,chain,symbol,
apy,tvlUsd,...} ]}. We match the canonical LRT staking pools (highest-TVL among matches),
reusing the project/chain/symbol matching style from scripts/fetch_historical_apy.py.

Verified against live /pools (2026-06-24):
  eeth/weeth → project "ether.fi-stake", symbol "WEETH", chain Ethereum (TVL ~$2.8B)
  ezeth      → project "renzo",          symbol "EZETH",  chain Ethereum

Returns {symbol(lowercase): apy_decimal}. eeth and weeth map to the same ether.fi staking
pool (weETH is the wrapped form of eETH; one restaking yield).

FAIL-CLOSED: malformed payload, or NONE of the requested pools matched / had a valid apy →
InvalidDataError. (A single missing optional pool is tolerated only if at least one matched;
see `apys()`.)

DEEP HISTORY (free): /pools is point-in-time. For a historical APY series we (1) match the pool
via /pools to get its pool id, then (2) fetch yields.llama.fi/chart/{pool} which returns the
APY time-series. `history(start_date, end_date)` returns {symbol: {date(ISO): apy_decimal}} over
the window. ezETH's pool history starts later than eETH's — symbols with no points in the window
are simply absent (per-symbol fail-closed), not a hard error, as long as at least one resolves.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

POOLS_URL = "https://yields.llama.fi/pools"
CHART_URL = "https://yields.llama.fi/chart/{pool}"

# snapshot symbol -> DeFiLlama selector (project/chain/symbol like fetch_historical_apy.py).
SELECTORS: Dict[str, dict] = {
    "eeth":  {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH"},
    "weeth": {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH"},
    "ezeth": {"project": "renzo",          "chain": "Ethereum", "symbol": "EZETH"},
    # plain LST staking yield (Lido stETH) — the wstETH holder's real base yield, needed by the
    # leverage-loop + levered-restaking books. A best-TVL selector, fail-closed if no pool matches.
    "steth": {"project": "lido",           "chain": "Ethereum", "symbol": "STETH"},
}

Fetcher = Callable[[str], object]


def _validate_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise InvalidDataError(f"yields pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"yields pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise InvalidDataError("yields pools: 'data' missing or empty")
    return data


def _match_pool(pools: List[dict], sel: dict) -> Optional[dict]:
    """Highest-TVL pool matching project+chain+symbol, or None."""
    proj, chain, sym = sel["project"], sel["chain"], sel["symbol"].upper()
    best, best_tvl = None, float("-inf")
    for p in pools:
        if not isinstance(p, dict):
            continue
        if p.get("project") != proj or p.get("chain") != chain:
            continue
        if (p.get("symbol") or "").upper() != sym:
            continue
        tvl = p.get("tvlUsd")
        tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
        if tvl > best_tvl:
            best_tvl, best = tvl, p
    return best


def _match_apy(pools: List[dict], sel: dict) -> Optional[float]:
    """Highest-TVL pool matching project+chain+symbol; return its apy as DECIMAL, or None."""
    best = _match_pool(pools, sel)
    if best is None:
        return None
    apy = best.get("apy")
    if not isinstance(apy, (int, float)) or apy < 0:
        # matched a pool but its apy is missing/invalid — treat as no datapoint (fail-closed
        # for THIS symbol; caller decides if the overall result is empty).
        return None
    return float(apy) / 100.0  # DeFiLlama apy is percent → decimal


def _parse_apy_chart(payload: object, sym: str) -> Dict[str, float]:
    """yields.llama.fi/chart/{pool} → {date(ISO): apy_decimal}. One point per UTC day (last
    wins). Raises on bad schema; an empty/point-less chart is NOT fatal here (returns {}), so a
    symbol whose pool simply has no points in the window is dropped rather than aborting."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"yields chart: expected object for {sym}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"yields chart: status={payload.get('status')!r} for {sym}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise InvalidDataError(f"yields chart: 'data' not a list for {sym}")
    out: Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            raise InvalidDataError(f"yields chart: row not an object for {sym}")
        ts = row.get("timestamp")
        apy = row.get("apy")
        if not isinstance(ts, str) or not ts:
            raise InvalidDataError(f"yields chart: missing/invalid timestamp for {sym}")
        if apy is None:
            continue  # a gap day in the pool's own history — skip, don't fabricate
        if not isinstance(apy, (int, float)) or apy < 0:
            raise InvalidDataError(f"yields chart: invalid apy {apy!r} for {sym}")
        # timestamp is ISO8601 like "2024-06-05T23:01:34.685Z"
        try:
            d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                datetime.timezone.utc
            ).date().isoformat()
        except ValueError as exc:
            raise InvalidDataError(f"yields chart: unparseable timestamp {ts!r} for {sym}") from exc
        out[d] = round(float(apy) / 100.0, 6)  # percent → decimal; last point on a day wins
    return out


class RestakingFeed:
    """eETH/ezETH restaking APY (decimal). Inject `fetcher` (url->json) in tests."""

    def __init__(self, fetcher: Optional[Fetcher] = None):
        self._fetch = fetcher or http_fetch

    def apys(self) -> Dict[str, float]:
        """Return {symbol: apy_decimal} for every selector that matched a pool with a valid
        apy. Schema-validates the payload (raises on malformed). Raises InvalidDataError only
        if NO selector matched at all (a totally empty result is a fail-closed condition)."""
        pools = _validate_pools(self._fetch(POOLS_URL))
        out: Dict[str, float] = {}
        for sym, sel in SELECTORS.items():
            apy = _match_apy(pools, sel)
            if apy is not None:
                out[sym] = round(apy, 6)
        if not out:
            raise InvalidDataError("restaking: no LRT pool matched with a valid apy")
        return out

    def history(self, start_date: str, end_date: str) -> Dict[str, Dict[str, float]]:
        """Return {symbol: {date(ISO): apy_decimal}} over [start_date, end_date].

        Resolves each selector to a pool id via /pools, then fetches that pool's /chart for the
        APY time-series. Schema-validates /pools and every chart (raises on malformed). A symbol
        whose pool has NO points in the window is simply absent; raises only if NONE resolved."""
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(f"restaking history: bad date(s) {start_date!r}..{end_date!r}") from exc
        if d1 < d0:
            raise InvalidDataError(f"restaking history: end {end_date} before start {start_date}")

        pools = _validate_pools(self._fetch(POOLS_URL))
        # resolve unique pool ids (eeth/weeth share one pool → fetch its chart once)
        sym_to_pool: Dict[str, str] = {}
        pool_charts: Dict[str, Dict[str, float]] = {}
        for sym, sel in SELECTORS.items():
            match = _match_pool(pools, sel)
            if match is None:
                continue
            pid = match.get("pool")
            if not isinstance(pid, str) or not pid:
                continue
            sym_to_pool[sym] = pid

        out: Dict[str, Dict[str, float]] = {}
        for sym, pid in sym_to_pool.items():
            if pid not in pool_charts:
                pool_charts[pid] = _parse_apy_chart(self._fetch(CHART_URL.format(pool=pid)), sym)
            windowed = {
                d: a for d, a in pool_charts[pid].items() if start_date <= d <= end_date
            }
            if windowed:
                out[sym] = windowed
        if not out:
            raise InvalidDataError(
                f"restaking history: no LRT pool chart had points in {start_date}..{end_date}"
            )
        return out


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(20)
    feed = RestakingFeed()
    for sym, apy in feed.apys().items():
        print(f"{sym:>6} restaking apy = {apy * 100:.3f}%")
