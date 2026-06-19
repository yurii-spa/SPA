"""
spa_core/utils/defillama.py

Centralized DeFiLlama API client.
Replaces copy-pasted urllib.request code across 10+ adapters.

MP-1379 (v9.95): Single source for all DeFiLlama yields API access.
Stdlib only — no third-party imports. All network errors are swallowed
and logged; callers receive empty lists / None — never raises.

Usage:
    from spa_core.utils.defillama import DeFiLlamaClient

    client = DeFiLlamaClient()
    pools = client.fetch_pools()          # all yield pools (cached)
    apy   = client.pool_apy("abc123")     # specific pool via /chart
    found = client.search(
        project="aave-v3",
        symbol_kw="USDC",
        chain="Ethereum",
    )
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://yields.llama.fi"
POOL_URL = f"{BASE_URL}/pools"
CHART_URL = f"{BASE_URL}/chart"


class DeFiLlamaClient:
    """Cached, stdlib-only client for the DeFiLlama yields API.

    Parameters
    ----------
    timeout:
        Socket timeout in seconds for every HTTP request.
    cache_ttl:
        Seconds before the pools cache is considered stale and refetched.
    """

    def __init__(self, timeout: int = 5, cache_ttl: int = 300) -> None:
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._pools_cache: Optional[list] = None
        self._pools_cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_pools(self, force: bool = False) -> list:
        """Fetch all yield pools from DeFiLlama ``/pools``.

        The result is cached for *cache_ttl* seconds.  Set *force=True* to
        bypass the cache and always hit the network.

        Returns an empty list on any network / parse error — never raises.
        """
        now = time.monotonic()
        if (
            not force
            and self._pools_cache is not None
            and (now - self._pools_cache_time) < self._cache_ttl
        ):
            return self._pools_cache

        raw = self._fetch_json(POOL_URL)
        if raw is None:
            return []

        # DeFiLlama wraps pools in {"status": "success", "data": [...]}
        if isinstance(raw, dict):
            pools = raw.get("data", [])
        elif isinstance(raw, list):
            pools = raw
        else:
            logger.warning("DeFiLlamaClient: unexpected payload type %s", type(raw))
            return []

        if not isinstance(pools, list):
            logger.warning("DeFiLlamaClient: 'data' field is not a list")
            return []

        self._pools_cache = pools
        self._pools_cache_time = now
        return pools

    def pool_apy(self, pool_id: str) -> Optional[float]:
        """Fetch the latest APY for a specific *pool_id* via ``/chart/{pool_id}``.

        Returns the most-recent ``apy`` value (float, percent) or *None* on
        any error (missing pool, network failure, etc.).
        """
        if not pool_id:
            return None
        url = f"{CHART_URL}/{pool_id}"
        raw = self._fetch_json(url)
        if raw is None:
            return None

        # DeFiLlama /chart returns {"status": "success", "data": [{...}, ...]}
        if isinstance(raw, dict):
            data = raw.get("data")
        else:
            data = None

        if not isinstance(data, list) or not data:
            return None

        last = data[-1]
        apy = last.get("apy") if isinstance(last, dict) else None
        if apy is None or not isinstance(apy, (int, float)):
            return None
        return float(apy)

    def search(
        self,
        project: Optional[str] = None,
        symbol_kw: Optional[str] = None,
        chain: Optional[str] = None,
        min_tvl: float = 1_000_000,
    ) -> list:
        """Search the cached pool list by flexible criteria.

        All parameters are optional and **case-insensitive**.

        Parameters
        ----------
        project:
            Pool ``project`` field — exact match (e.g. ``"aave-v3"``).
        symbol_kw:
            Substring match against pool ``symbol`` (e.g. ``"USDC"``).
        chain:
            Pool ``chain`` field — exact match (e.g. ``"Ethereum"``).
        min_tvl:
            Minimum ``tvlUsd``.  Defaults to 1 000 000.

        Returns
        -------
        list
            Matching pool dicts, empty if nothing matches or on error.
        """
        pools = self.fetch_pools()
        results: list = []

        project_l = project.lower() if project else None
        symbol_l = symbol_kw.lower() if symbol_kw else None
        chain_l = chain.lower() if chain else None

        for pool in pools:
            if not isinstance(pool, dict):
                continue

            if project_l is not None:
                if str(pool.get("project", "")).lower() != project_l:
                    continue

            if symbol_l is not None:
                if symbol_l not in str(pool.get("symbol", "")).lower():
                    continue

            if chain_l is not None:
                if str(pool.get("chain", "")).lower() != chain_l:
                    continue

            tvl = pool.get("tvlUsd")
            if isinstance(tvl, (int, float)) and float(tvl) < min_tvl:
                continue

            results.append(pool)

        return results

    def top_apy(self, project: str, n: int = 3) -> list:
        """Return the top *n* pools by APY for *project*.

        Pools with missing or non-numeric APY are excluded.
        Returns a list sorted by APY descending (highest first).
        """
        pools = self.search(project=project)
        scored: list = []
        for pool in pools:
            apy = pool.get("apy")
            if isinstance(apy, (int, float)):
                scored.append(pool)
        scored.sort(key=lambda p: float(p.get("apy", 0)), reverse=True)
        return scored[:n]

    def clear_cache(self) -> None:
        """Invalidate the in-memory pools cache."""
        self._pools_cache = None
        self._pools_cache_time = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str) -> Optional[object]:
        """GET *url* and parse response as JSON.

        Returns parsed object on success, *None* on any error.
        Never raises.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
            return json.loads(body)
        except urllib.error.URLError as exc:
            logger.warning("DeFiLlamaClient: network error fetching %s: %s", url, exc)
            return None
        except json.JSONDecodeError as exc:
            logger.warning("DeFiLlamaClient: JSON parse error for %s: %s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("DeFiLlamaClient: unexpected error fetching %s: %s", url, exc)
            return None
