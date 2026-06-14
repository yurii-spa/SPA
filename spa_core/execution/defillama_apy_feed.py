"""
DeFiLlama live APY feed for T2 adapters (Sprint v3.27 / SPA-V327-001).

Lightweight, dependency-free (stdlib ``urllib`` only) helper that fetches live
APY values from DeFiLlama's public ``/pools`` endpoint and exposes a single
``get_live_apy(protocol, asset, chain)`` function used by the T2 adapters
(Yearn V3 / Euler V2 / Maple) to replace their hard-coded mock APYs.

Design principles (mirrors data_pipeline/defillama_fetcher.py):
  * stdlib only — ``urllib.request`` with manual retry/backoff.
  * NEVER raises — any network/parse/match failure returns ``None`` (adapters
    fall back to their mock APY).
  * In-process TTL cache (default 15 min) avoids hammering the endpoint when
    several adapters query in the same run.
  * Fuzzy protocol/asset/chain matching identical to the fetcher's
    ``match_whitelist_pools`` (substring project, substring symbol, substring
    chain; pick max ``tvlUsd`` candidate).

Env gates:
  * ``SPA_LIVE_APY``       — "1"/"true"/"yes" enables live reads (default off).
  * ``SPA_APY_CACHE_TTL``  — cache TTL in seconds (default 900 = 15 min).

The adapters call ``get_live_apy`` only when ``live_apy_enabled()`` is True and
they are NOT in dry-run mode.

Sprint v3.27 — initial implementation.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

log = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"

# Default cache TTL (seconds). Overridable via SPA_APY_CACHE_TTL.
_DEFAULT_CACHE_TTL = 900  # 15 minutes

# Maps a normalized SPA protocol name → DeFiLlama "project" substring (lowercase).
# Keys are normalized (lowercased, spaces→dashes). A few synonyms are supported
# so callers can pass either the SPA protocol id ("yearn-v3") or a bare name.
_PROTOCOL_PROJECT_MATCH: dict[str, str] = {
    "yearn-v3": "yearn",
    "euler-v2": "euler",
    "maple": "maple",
    "yearn": "yearn",
    "euler": "euler",
    "pendle-pt": "pendle",
    "pendle": "pendle",
    "sky-susds": "sky",
    "sky": "sky",
    "susds": "sky",
}


# ─── Module-level TTL cache ──────────────────────────────────────────────────

_CACHE: dict = {"pools": None, "ts": 0.0}


def _cache_ttl() -> float:
    """Return the configured cache TTL (seconds), env-overridable."""
    raw = os.getenv("SPA_APY_CACHE_TTL")
    if raw is None:
        return float(_DEFAULT_CACHE_TTL)
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning("SPA_APY_CACHE_TTL invalid (%r) — using default %ss", raw, _DEFAULT_CACHE_TTL)
        return float(_DEFAULT_CACHE_TTL)


def clear_cache() -> None:
    """Reset the in-process pool cache (used by tests)."""
    _CACHE["pools"] = None
    _CACHE["ts"] = 0.0


# ─── Network fetch ───────────────────────────────────────────────────────────

def _retry_request(url: str, timeout: int = 15, max_attempts: int = 3, backoff: float = 2.0):
    """Fetch URL with exponential backoff. Returns (bytes, None) or (None, err_str)."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read(), None
        except Exception as e:  # noqa: BLE001 — never propagate network errors
            last_err = str(e)
            if attempt < max_attempts - 1:
                time.sleep(backoff ** attempt)
    return None, last_err


def _fetch_pools() -> list[dict]:
    """Fetch all DeFiLlama pools. Returns [] on any error (never raises)."""
    data_bytes, err = _retry_request(DEFILLAMA_POOLS_URL, timeout=15, max_attempts=3, backoff=2.0)
    if err is not None:
        log.warning("defillama_apy_feed: fetch failed — %s", err)
        return []
    try:
        data = json.loads(data_bytes)
        pools = data.get("data", [])
        if not isinstance(pools, list):
            log.warning("defillama_apy_feed: unexpected /pools shape")
            return []
        return pools
    except Exception as e:  # noqa: BLE001
        log.warning("defillama_apy_feed: JSON parse error — %s", e)
        return []


def _get_pools_cached(force: bool = False) -> list[dict]:
    """Return pools from cache, refetching when stale or forced.

    A successful (non-empty) fetch is cached for the TTL window. An empty
    result (network failure) is NOT cached, so the next call retries.
    """
    now = time.time()
    cached = _CACHE.get("pools")
    age = now - _CACHE.get("ts", 0.0)
    if not force and cached is not None and age < _cache_ttl():
        return cached

    pools = _fetch_pools()
    if pools:
        _CACHE["pools"] = pools
        _CACHE["ts"] = now
    return pools


# ─── Fuzzy match (pure function, no network) ─────────────────────────────────

def get_live_apy_from_pools(
    pools: list[dict],
    protocol: str,
    asset: str,
    chain: str,
) -> float | None:
    """Deterministic fuzzy-match against a supplied pool list (no network).

    Mirrors defillama_fetcher.match_whitelist_pools logic:
      * project substring match (normalized protocol → DeFiLlama project)
      * asset substring match (uppercase symbol)
      * chain substring match (lowercase)
      * pick the candidate with the highest tvlUsd
    Returns ``round(apy, 4)`` or ``None`` (never raises).
    """
    try:
        protocol_key = (protocol or "").strip().lower().replace(" ", "-")
        project_match = _PROTOCOL_PROJECT_MATCH.get(protocol_key)
        if project_match is None:
            log.debug("defillama_apy_feed: unknown protocol %r", protocol)
            return None

        asset_u = (asset or "").strip().upper()
        chain_l = (chain or "").strip().lower()
        if not asset_u or not chain_l:
            return None

        candidates = []
        for p in pools or []:
            p_project = (p.get("project") or "").lower()
            p_symbol = (p.get("symbol") or "").upper()
            p_chain = (p.get("chain") or "").lower()
            if (project_match in p_project and
                    asset_u in p_symbol and
                    chain_l in p_chain):
                candidates.append(p)

        if not candidates:
            log.debug("defillama_apy_feed: no match for %s/%s/%s", protocol, asset, chain)
            return None

        best = max(candidates, key=lambda x: x.get("tvlUsd") or 0)
        apy = best.get("apy")
        if apy is None:
            log.debug("defillama_apy_feed: matched pool has apy=None (%s)", best.get("pool"))
            return None
        return round(float(apy), 4)
    except Exception as e:  # noqa: BLE001 — never propagate
        log.debug("defillama_apy_feed: get_live_apy_from_pools error — %s", e)
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def get_live_apy(protocol: str, asset: str, chain: str) -> float | None:
    """Return live APY (%) for a protocol/asset/chain, or ``None``.

    Fetches (cached) pools from DeFiLlama and runs the fuzzy matcher. Returns
    ``None`` on unknown protocol, no match, missing apy, or any error.
    """
    try:
        pools = _get_pools_cached()
        if not pools:
            return None
        return get_live_apy_from_pools(pools, protocol, asset, chain)
    except Exception as e:  # noqa: BLE001
        log.debug("defillama_apy_feed: get_live_apy error — %s", e)
        return None


def live_apy_enabled() -> bool:
    """True if the SPA_LIVE_APY env gate enables live APY reads."""
    return os.getenv("SPA_LIVE_APY", "false").lower() in ("1", "true", "yes")


# ─── Smoke test / demo ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Demo with deterministic mock pools (no network required).
    demo_pools = [
        {"project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
         "apy": 6.42, "tvlUsd": 120_000_000, "pool": "yearn-usdc"},
        {"project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
         "apy": 9.99, "tvlUsd": 1_000_000, "pool": "yearn-usdc-small"},
        {"project": "euler", "symbol": "USDC", "chain": "Ethereum",
         "apy": 7.40, "tvlUsd": 80_000_000, "pool": "euler-usdc"},
        {"project": "maple", "symbol": "USDC", "chain": "Ethereum",
         "apy": 5.60, "tvlUsd": 40_000_000, "pool": "maple-usdc"},
    ]
    print("yearn-v3 / USDC / ethereum ->",
          get_live_apy_from_pools(demo_pools, "yearn-v3", "USDC", "ethereum"))
    print("euler-v2 / USDC / ethereum ->",
          get_live_apy_from_pools(demo_pools, "euler-v2", "USDC", "ethereum"))
    print("maple / USDC / ethereum    ->",
          get_live_apy_from_pools(demo_pools, "maple", "USDC", "ethereum"))
    print("unknown / USDC / ethereum  ->",
          get_live_apy_from_pools(demo_pools, "aave-v3", "USDC", "ethereum"))
    print("live_apy_enabled():", live_apy_enabled())
