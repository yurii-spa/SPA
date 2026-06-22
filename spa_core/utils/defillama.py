"""
spa_core/utils/defillama.py

Centralized DeFiLlama API client — v2.

MP-1379 (v9.95): Single source for all DeFiLlama yields API access.
MP-1503 (v11.19): v2 — TTL cache, retry/backoff, rate-limit guard, cache logging.

Stdlib only — no third-party imports.  All network errors are swallowed
and logged; callers receive empty lists / None — never raises.

Usage:
    from spa_core.utils.defillama import DeFiLlamaClient

    client = DeFiLlamaClient()
    pools = client.fetch_pools()          # all yield pools (cached 5 min)
    pools = client.get_yields()           # alias for fetch_pools()
    apy   = client.pool_apy("abc123")    # specific pool via /chart
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
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://yields.llama.fi"
POOL_URL = f"{BASE_URL}/pools"
CHART_URL = f"{BASE_URL}/chart"

# v2 constants
CACHE_TTL_SECONDS: int = 300          # 5 minutes for APY data
_RETRY_ATTEMPTS: int = 3
_RETRY_BASE_DELAY: float = 1.0        # seconds — doubles on each retry
_MIN_REQUEST_INTERVAL: float = 1.0    # rate-limit guard: ≥ 1 req/sec


class DeFiLlamaClient:
    """Cached, stdlib-only client for the DeFiLlama yields API — v2.

    v2 additions (MP-1503):
    - General-purpose in-memory TTL cache keyed by URL (5-min TTL).
    - Retry with exponential backoff (3 attempts: delays 1s, 2s, 4s).
    - Rate-limit guard: enforces ≥ 1 s between outgoing requests.
    - INFO-level logging of cache hits/misses.

    Parameters
    ----------
    timeout:
        Socket timeout in seconds for every HTTP request.
    cache_ttl:
        Seconds before any cached response is considered stale.
    min_request_interval:
        Minimum seconds between outgoing HTTP requests (rate limit).
    max_retries:
        Number of retry attempts on transient network failures.
    retry_base_delay:
        Initial backoff delay in seconds (doubles on each retry).
    """

    def __init__(
        self,
        timeout: int = 5,
        cache_ttl: int = CACHE_TTL_SECONDS,
        min_request_interval: float = _MIN_REQUEST_INTERVAL,
        max_retries: int = _RETRY_ATTEMPTS,
        retry_base_delay: float = _RETRY_BASE_DELAY,
    ) -> None:
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._min_request_interval = min_request_interval
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

        # General-purpose URL → data cache (v2)
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, float] = {}

        # Pool-specific cache (backward-compat: tests access these directly)
        self._pools_cache: Optional[list] = None
        self._pools_cache_time: float = 0.0

        # Rate-limit state
        self._last_request_time: float = 0.0

        # Stats counters (informational)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_pools(self, force: bool = False) -> list:
        """Fetch all yield pools from DeFiLlama ``/pools``.

        The result is cached for *cache_ttl* seconds.  Set *force=True* to
        bypass the cache and always hit the network.

        Returns an empty list on any network / parse error — never raises.

        Note: also maintains ``_pools_cache`` / ``_pools_cache_time`` for
        backward-compatibility with callers that inspect these attributes directly.
        """
        # Use the generic _cached_fetch so that cache hits/misses are tracked
        # uniformly in cache_stats(). The pools-specific _pools_cache attributes
        # are kept for backward-compatibility with callers that inspect them directly.
        raw = self._cached_fetch(POOL_URL, force=force)
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

        # Update backward-compat attributes
        self._pools_cache = pools
        self._pools_cache_time = time.monotonic()
        return pools

    def get_yields(self, chain: Optional[str] = None) -> list:
        """Alias for :meth:`fetch_pools`, optionally filtered by chain.

        Added in v2 for compatibility with callers that prefer this name.

        Parameters
        ----------
        chain:
            Case-insensitive chain name filter (e.g. ``"Ethereum"``).
            If *None*, returns all pools.

        Returns
        -------
        list
            Matching pool dicts, empty on error.
        """
        pools = self.fetch_pools()
        if chain is None:
            return pools
        chain_l = chain.lower()
        return [p for p in pools if isinstance(p, dict)
                and str(p.get("chain", "")).lower() == chain_l]

    def pool_apy(self, pool_id: str) -> Optional[float]:
        """Fetch the latest APY for a specific *pool_id* via ``/chart/{pool_id}``.

        Returns the most-recent ``apy`` value (float, percent) or *None* on
        any error (missing pool, network failure, etc.).
        """
        if not pool_id:
            return None
        url = f"{CHART_URL}/{pool_id}"
        raw = self._cached_fetch(url)
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

    def cache_stats(self) -> dict:
        """Return current cache hit/miss counts and number of cached entries."""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "cached_entries": len(self._cache),
        }

    def clear_cache(self) -> None:
        """Invalidate the entire in-memory cache."""
        self._cache.clear()
        self._cache_timestamps.clear()
        # Reset pool-specific backward-compat attributes too
        self._pools_cache = None
        self._pools_cache_time = 0.0
        logger.debug("DeFiLlamaClient: cache cleared")

    # ------------------------------------------------------------------
    # v2 cache helpers
    # ------------------------------------------------------------------

    def _get_cached(self, key: str) -> tuple[bool, Any]:
        """Return *(hit, data)* for *key*.  hit=True means unexpired entry."""
        if key in self._cache:
            age = time.monotonic() - self._cache_timestamps[key]
            if age < self._cache_ttl:
                return True, self._cache[key]
        return False, None

    def _set_cache(self, key: str, value: Any) -> None:
        """Store *value* in cache under *key* with current timestamp."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.monotonic()

    def _cached_fetch(self, url: str, force: bool = False) -> Optional[Any]:
        """Return cached response for *url*, or fetch + cache if needed.

        Logs INFO on cache hit/miss.  On miss, calls :meth:`_fetch_json_with_retry`.
        """
        if not force:
            hit, data = self._get_cached(url)
            if hit:
                self._cache_hits += 1
                logger.info("DeFiLlamaClient: cache HIT  %s (hits=%d misses=%d)",
                            url, self._cache_hits, self._cache_misses)
                return data

        self._cache_misses += 1
        logger.info("DeFiLlamaClient: cache MISS %s (hits=%d misses=%d)",
                    url, self._cache_hits, self._cache_misses)

        data = self._fetch_json_with_retry(url)
        if data is not None:
            self._set_cache(url, data)
        return data

    # ------------------------------------------------------------------
    # v2 rate-limit guard
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Block until at least *min_request_interval* seconds have elapsed
        since the last outgoing HTTP request."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_request_interval:
            sleep_for = self._min_request_interval - elapsed
            logger.debug("DeFiLlamaClient: rate-limit sleep %.3fs", sleep_for)
            time.sleep(sleep_for)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # v2 retry with exponential backoff
    # ------------------------------------------------------------------

    def _fetch_json_with_retry(self, url: str) -> Optional[Any]:
        """Fetch *url* with up to *max_retries* attempts and exponential backoff.

        Delays: base, base*2, base*4, … between consecutive attempts.
        Returns parsed JSON on success, *None* if all attempts fail.
        """
        delay = self._retry_base_delay
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            self._rate_limit()
            result = self._fetch_json(url)
            if result is not None:
                if attempt > 1:
                    logger.info(
                        "DeFiLlamaClient: succeeded on attempt %d/%d for %s",
                        attempt, self._max_retries, url,
                    )
                return result

            logger.warning(
                "DeFiLlamaClient: attempt %d/%d failed for %s",
                attempt, self._max_retries, url,
            )
            if attempt < self._max_retries:
                logger.debug("DeFiLlamaClient: retrying in %.1fs", delay)
                time.sleep(delay)
                delay *= 2

        logger.warning(
            "DeFiLlamaClient: all %d attempts failed for %s",
            self._max_retries, url,
        )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str) -> Optional[Any]:
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
