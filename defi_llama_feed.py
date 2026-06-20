"""spa_core/feeds/defi_llama_feed.py — DeFiLlama yields feed with 1-hour cache.

Fetches live APY/TVL data from the DeFiLlama yields API and exposes a simple
``get_apy(protocol_slug)`` interface for SPA adapters and the daily cycle.

Design constraints (FORBIDDEN rules):
    * stdlib only — no external dependencies (requests, httpx, …)
    * Never raises — all errors are caught and logged; caller gets None
    * Never mocks — returns None when live data is unavailable; no hardcoded APY
    * Atomic reads only — this module never writes to disk

Pool selection strategy:
    * project: case-insensitive **substring** match (robust against DeFiLlama
      slug variants, e.g. "morpho" matches "morpho-blue")
    * symbol: exact upper-case match (e.g. "USDC")
    * chain: case-insensitive exact match (e.g. "ethereum")
    * Among qualifying pools the one with the highest ``tvlUsd`` wins

Liveness filters (dead/spam/anomaly rejection):
    * TVL floor: pool.tvlUsd >= MIN_TVL_USD (default $100k)
    * APY sanity: 0 <= pool.apy <= APY_SANITY_MAX (default 200%)

Return convention (SPA adapter standard):
    * ``DefiLlamaFeed.get_apy(project, asset, chain)``  → decimal  (0.085 = 8.5%)
    * ``get_apy(protocol_slug)``                        → decimal  (0.085 = 8.5%)

Both return None — never a fallback value — when data is unavailable.
"""
from __future__ import annotations

import json as _json
import logging
import time
import urllib.request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Public DeFiLlama yields endpoint.
DEFILLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

#: Default cache TTL in seconds (1 hour).
CACHE_TTL: int = 3600

#: Default HTTP request timeout in seconds.
REQUEST_TIMEOUT: int = 10

#: Dead/spam pool TVL floor in USD.  Pools below this threshold are ignored.
MIN_TVL_USD: float = 100_000.0

#: Anomalous APY ceiling (%).  Any pool with apy > this is rejected as bogus.
APY_SANITY_MAX: float = 200.0

# ---------------------------------------------------------------------------
# Protocol slug → (defillama_project, asset, chain)
# ---------------------------------------------------------------------------

#: Maps SPA internal names and DeFiLlama slugs to (project, asset, chain).
#: Used by the module-level ``get_apy(slug)`` convenience function.
PROTOCOL_MAP: dict[str, Tuple[str, str, str]] = {
    # ── Yearn V3 ──────────────────────────────────────────────────────────
    "yearn_v3":       ("yearn-finance", "USDC", "Ethereum"),
    "yearn-v3":       ("yearn-finance", "USDC", "Ethereum"),
    "yearn-finance":  ("yearn-finance", "USDC", "Ethereum"),
    # ── Morpho Blue ──────────────────────────────────────────────────────
    "morpho_blue":    ("morpho-blue", "USDC", "Ethereum"),
    "morpho-blue":    ("morpho-blue", "USDC", "Ethereum"),
    "morpho":         ("morpho-blue", "USDC", "Ethereum"),
    # ── Euler V2 ─────────────────────────────────────────────────────────
    "euler_v2":       ("euler-v2", "USDC", "Ethereum"),
    "euler-v2":       ("euler-v2", "USDC", "Ethereum"),
    # ── Maple Finance ─────────────────────────────────────────────────────
    "maple":          ("maple", "USDC", "Ethereum"),
    "maple-finance":  ("maple", "USDC", "Ethereum"),
}


# ---------------------------------------------------------------------------
# DefiLlamaFeed class
# ---------------------------------------------------------------------------


class DefiLlamaFeed:
    """Cached DeFiLlama /pools client.

    ``get_apy(project, asset, chain)`` returns APY as a **decimal**
    (e.g. ``0.085`` for 8.5%) to match the SPA adapter convention.

    The underlying /pools fetch is cached for ``cache_ttl`` seconds.
    All errors are absorbed: the method returns ``None`` on any failure.

    Args:
        api_url:   DeFiLlama yields API URL.
        cache_ttl: Cache lifetime in seconds (default: 3600 = 1 hour).
        timeout:   HTTP request timeout in seconds.
        enabled:   Set to ``False`` to disable all network calls (useful in
                   test isolation without patching urllib).
    """

    def __init__(
        self,
        api_url: str = DEFILLAMA_POOLS_URL,
        cache_ttl: int = CACHE_TTL,
        timeout: int = REQUEST_TIMEOUT,
        enabled: bool = True,
    ) -> None:
        self.api_url = api_url
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.enabled = enabled
        self._cache: Optional[list] = None
        self._cache_ts: float = 0.0

    # ── internal ────────────────────────────────────────────────────────────

    def _load_pools(self) -> Optional[list]:
        """Return the cached pool list, refreshing if the TTL has expired.

        Returns ``None`` when disabled, on any network error, or if the API
        returns an unexpected payload shape.  Never raises.
        """
        if not self.enabled:
            return None

        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self.cache_ttl:
            return self._cache

        try:
            req = urllib.request.Request(
                self.api_url,
                headers={"Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            payload = _json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DefiLlamaFeed._load_pools: fetch failed: %s", exc)
            return None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            logger.warning(
                "DefiLlamaFeed._load_pools: unexpected API response shape"
            )
            return None

        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("DefiLlamaFeed._load_pools: 'data' is not a list")
            return None

        self._cache = data
        self._cache_ts = now
        return data

    # ── public ──────────────────────────────────────────────────────────────

    def get_pool(
        self,
        project: str,
        asset: str = "USDC",
        chain: str = "Ethereum",
        min_tvl_usd: float = MIN_TVL_USD,
    ) -> Optional[dict]:
        """Return the best matching live pool as ``{"apy", "tvl_usd", "pool_id"}``.

        ``apy`` is the raw DeFiLlama **percentage** (e.g. ``8.5`` for 8.5%);
        ``tvl_usd`` is in USD; ``pool_id`` is the DeFiLlama uuid (or ``None``).

        Matching rules:
            * ``project`` — case-insensitive substring (handles slug variants)
            * ``asset``   — exact upper-case symbol match
            * ``chain``   — case-insensitive exact match

        Liveness filters: pools with TVL < ``min_tvl_usd`` or APY outside
        ``[0, APY_SANITY_MAX]`` are silently rejected.

        Returns ``None`` on miss, error, or when all qualifying pools are
        filtered out.  Never raises.
        """
        try:
            pools = self._load_pools()
            if not pools:
                return None

            proj_l = project.lower()
            asset_u = asset.upper()
            chain_l = chain.lower()

            best_apy: Optional[float] = None
            best_tvl: float = float("-inf")
            best_id: Optional[str] = None

            for pool in pools:
                if not isinstance(pool, dict):
                    continue

                # --- project: substring match ---
                if proj_l not in str(pool.get("project", "")).lower():
                    continue

                # --- symbol: exact upper-case ---
                if str(pool.get("symbol", "")).upper() != asset_u:
                    continue

                # --- chain: case-insensitive exact ---
                if str(pool.get("chain", "")).lower() != chain_l:
                    continue

                # --- TVL floor ---
                raw_tvl = pool.get("tvlUsd")
                tvl = float(raw_tvl) if isinstance(raw_tvl, (int, float)) else 0.0
                if tvl < min_tvl_usd:
                    continue

                # --- APY sanity ---
                raw_apy = pool.get("apy")
                if not isinstance(raw_apy, (int, float)):
                    continue
                apy = float(raw_apy)
                if apy < 0.0 or apy > APY_SANITY_MAX:
                    logger.warning(
                        "DefiLlamaFeed: %s/%s on %s — anomalous apy=%.4f%% rejected",
                        project, asset, chain, apy,
                    )
                    continue

                # --- take highest TVL ---
                if tvl > best_tvl:
                    best_tvl = tvl
                    best_apy = apy
                    best_id = pool.get("pool")

            if best_apy is None:
                return None

            return {"apy": best_apy, "tvl_usd": best_tvl, "pool_id": best_id}

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DefiLlamaFeed.get_pool(%s/%s): unexpected error: %s",
                project, asset, exc,
            )
            return None

    def get_apy(
        self,
        project: str,
        asset: str = "USDC",
        chain: str = "Ethereum",
    ) -> Optional[float]:
        """Return live APY as a **decimal** (e.g. ``0.085`` for 8.5%), or ``None``.

        This is the SPA adapter convention: the orchestrator multiplies by 100
        to display a percentage.  Returns ``None`` — never a fallback value —
        when the live feed is unavailable.
        """
        result = self.get_pool(project, asset, chain)
        if result is None:
            return None
        return result["apy"] / 100.0

    def get_tvl(
        self,
        project: str,
        asset: str = "USDC",
        chain: str = "Ethereum",
    ) -> Optional[float]:
        """Return live TVL in USD, or ``None``."""
        result = self.get_pool(project, asset, chain)
        return result["tvl_usd"] if result is not None else None

    def invalidate_cache(self) -> None:
        """Force the next call to re-fetch from the API (useful in tests)."""
        self._cache = None
        self._cache_ts = 0.0


# ---------------------------------------------------------------------------
# Module-level singleton + convenience function
# ---------------------------------------------------------------------------

_SINGLETON: Optional[DefiLlamaFeed] = None


def _get_singleton() -> DefiLlamaFeed:
    """Return the shared process-wide feed instance (lazy init)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = DefiLlamaFeed()
    return _SINGLETON


def get_apy(
    protocol_slug: str,
    asset: str = "USDC",
    chain: str = "Ethereum",
) -> Optional[float]:
    """Return live APY as a **decimal** for the given protocol slug.

    Uses the module-level singleton (1-hour cache, shared across all callers
    in the same Python process).

    ``protocol_slug`` can be a SPA internal name (e.g. ``"yearn_v3"``,
    ``"morpho_blue"``, ``"euler_v2"``, ``"maple"``) or a DeFiLlama project slug
    (e.g. ``"yearn-finance"``, ``"morpho-blue"``, ``"euler-v2"``).
    Unknown slugs are forwarded verbatim to the DeFiLlama substring matcher.

    Returns:
        APY as a decimal (e.g. ``0.085`` for 8.5%), or ``None`` if the feed is
        unavailable or no qualifying pool was found.  Never raises.
    """
    if protocol_slug in PROTOCOL_MAP:
        project, asset, chain = PROTOCOL_MAP[protocol_slug]
    else:
        project = protocol_slug

    return _get_singleton().get_apy(project, asset, chain)
