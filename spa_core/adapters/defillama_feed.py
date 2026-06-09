"""DeFiLlama yields API feed client.

Fetches live APY/TVL data from the DeFiLlama yields API and exposes a small,
cached lookup interface for SPA adapters. The API returns APY as a percentage
(e.g. 8.5 == 8.5%); SPA works in decimals (0.085), so values are converted on
read. All network errors are caught and logged, returning ``None`` so callers
can fall back to mock values.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from . import config

logger = logging.getLogger(__name__)


class DeFiLlamaFeed:
    """Cached client over the DeFiLlama ``/pools`` yields endpoint."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        timeout: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        self.api_url = api_url if api_url is not None else config.DEFILLAMA_API_URL
        self.cache_ttl = (
            cache_ttl if cache_ttl is not None else config.DEFILLAMA_CACHE_TTL
        )
        self.timeout = timeout if timeout is not None else config.DEFILLAMA_TIMEOUT
        self.enabled = enabled if enabled is not None else config.DEFILLAMA_ENABLED

        self._cache: Optional[list[dict]] = None
        self._cache_ts: float = 0.0

    # --- internal -----------------------------------------------------------

    def _fetch_pools(self) -> Optional[list[dict]]:
        """Return the raw pools list, served from cache within the TTL.

        Returns ``None`` on any network/parse error.
        """
        if not self.enabled:
            return None

        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self.cache_ttl:
            return self._cache

        try:
            resp = requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - log and fall back
            logger.warning("DeFiLlama fetch failed: %s", exc)
            return None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            logger.warning("DeFiLlama returned unexpected payload: %r", payload)
            return None

        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("DeFiLlama payload 'data' is not a list")
            return None

        self._cache = data
        self._cache_ts = now
        return data

    # --- public -------------------------------------------------------------

    def get_pool(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[dict]:
        """Return the matching pool with the highest ``tvlUsd``.

        Matching is case-insensitive on project, symbol and chain.
        Returns ``None`` if disabled, on error, or if no pool matches.
        """
        pools = self._fetch_pools()
        if not pools:
            return None

        project_l = project.lower()
        symbol_l = symbol.lower()
        chain_l = chain.lower()

        best: Optional[dict] = None
        best_tvl = float("-inf")
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("project", "")).lower() != project_l:
                continue
            if str(pool.get("symbol", "")).lower() != symbol_l:
                continue
            if str(pool.get("chain", "")).lower() != chain_l:
                continue
            tvl = pool.get("tvlUsd")
            tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
            if tvl > best_tvl:
                best_tvl = tvl
                best = pool

        return best

    def get_apy(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[float]:
        """Return live APY as a decimal (e.g. 0.085), or ``None`` on miss/error."""
        pool = self.get_pool(project, symbol, chain)
        if pool is None:
            return None
        apy = pool.get("apy")
        if not isinstance(apy, (int, float)):
            return None
        return float(apy) / 100.0

    def get_tvl(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[float]:
        """Return live TVL in USD, or ``None`` on miss/error."""
        pool = self.get_pool(project, symbol, chain)
        if pool is None:
            return None
        tvl = pool.get("tvlUsd")
        if not isinstance(tvl, (int, float)):
            return None
        return float(tvl)


# end of file
