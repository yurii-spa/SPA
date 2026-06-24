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
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

POOLS_URL = "https://yields.llama.fi/pools"

# snapshot symbol -> DeFiLlama selector (project/chain/symbol like fetch_historical_apy.py).
SELECTORS: Dict[str, dict] = {
    "eeth":  {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH"},
    "weeth": {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH"},
    "ezeth": {"project": "renzo",          "chain": "Ethereum", "symbol": "EZETH"},
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


def _match_apy(pools: List[dict], sel: dict) -> Optional[float]:
    """Highest-TVL pool matching project+chain+symbol; return its apy as DECIMAL, or None."""
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
    if best is None:
        return None
    apy = best.get("apy")
    if not isinstance(apy, (int, float)) or apy < 0:
        # matched a pool but its apy is missing/invalid — treat as no datapoint (fail-closed
        # for THIS symbol; caller decides if the overall result is empty).
        return None
    return float(apy) / 100.0  # DeFiLlama apy is percent → decimal


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


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(20)
    feed = RestakingFeed()
    for sym, apy in feed.apys().items():
        print(f"{sym:>6} restaking apy = {apy * 100:.3f}%")
