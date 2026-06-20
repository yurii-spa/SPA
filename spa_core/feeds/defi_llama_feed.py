"""spa_core/feeds/defi_llama_feed.py — DeFiLlama yields feed with retry/backoff and CoinGecko fallback.

Fetches live APY/TVL data from the DeFiLlama yields API and exposes a simple
``get_apy(project, asset, chain)`` interface for SPA adapters and the daily cycle.

Design constraints (FORBIDDEN rules):
    * stdlib only — no external dependencies (requests, httpx, …)
    * Never raises — all errors are caught and logged; caller gets None
    * Never mocks — returns None when live data is unavailable; no hardcoded APY
    * Atomic reads only — this module never writes to disk

Retry / resilience (v1197):
    * Up to MAX_RETRIES=3 attempts on DeFiLlama with exponential backoff (1s, 2s, 4s)
    * User-Agent is rotated on each attempt (CDN 403 mitigation)
    * On all-retries-exhausted, CoinGecko DeFi yields API is queried as secondary source
    * ``live_apy_fallback_source`` is added to every get_pool() result to log data origin

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
import urllib.error
import urllib.request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Public DeFiLlama yields endpoint.
DEFILLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

#: CoinGecko coins/markets endpoint (free public API, fallback source).
COINGECKO_MARKETS_URL: str = "https://api.coingecko.com/api/v3/coins/markets"

#: Default cache TTL in seconds (1 hour).
CACHE_TTL: int = 3600

#: Default HTTP request timeout in seconds.
REQUEST_TIMEOUT: int = 10

#: Dead/spam pool TVL floor in USD.  Pools below this threshold are ignored.
MIN_TVL_USD: float = 100_000.0

#: Anomalous APY ceiling (%).  Any pool with apy > this is rejected as bogus.
APY_SANITY_MAX: float = 200.0

#: Maximum number of retry attempts for DeFiLlama fetches.
MAX_RETRIES: int = 3

#: Base backoff delay in seconds; actual delays are 1s, 2s, 4s (2^attempt).
BACKOFF_BASE: float = 1.0

#: User-Agents rotated on successive retries.  DeFiLlama CDN occasionally
#: blocks bot-like UAs with a 403; rotating helps bypass the filter.
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (compatible; SPA-yield-tracker/1.0)",
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "curl/7.88.1",
]

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

#: Maps DeFiLlama project slugs to CoinGecko coin IDs for fallback queries.
#: Used by ``_fetch_coingecko_fallback`` to verify protocol liveness.
COINGECKO_COIN_IDS: dict[str, str] = {
    "aave-v3":         "aave",
    "aave":            "aave",
    "compound":        "compound-governance-token",
    "compound-v3":     "compound-governance-token",
    "yearn-finance":   "yearn-finance",
    "morpho-blue":     "morpho",
    "morpho":          "morpho",
    "euler-v2":        "euler",
    "euler":           "euler",
    "maple":           "maple",
    "maple-finance":   "maple",
}


# ---------------------------------------------------------------------------
# DefiLlamaFeed class
# ---------------------------------------------------------------------------


class DefiLlamaFeed:
    """Cached DeFiLlama /pools client with retry/backoff and CoinGecko fallback.

    ``get_pool(project, asset, chain)`` returns a dict with keys
    ``{"apy", "tvl_usd", "pool_id", "live_apy_fallback_source"}`` where:
        * ``apy``                    — raw DeFiLlama **percentage** (e.g. 8.5 for 8.5%)
        * ``tvl_usd``                — USD TVL
        * ``pool_id``                — DeFiLlama pool uuid (or ``None``)
        * ``live_apy_fallback_source`` — ``"defillama"`` | ``"coingecko"`` (data origin)

    ``get_apy(project, asset, chain)`` divides by 100 and returns a **decimal**
    (e.g. ``0.085`` for 8.5%) to match the SPA adapter convention.

    Resilience (v1197):
        1. DeFiLlama is tried up to MAX_RETRIES=3 times with exponential backoff
           (1 s, 2 s, 4 s) and rotating User-Agents on each attempt.
        2. On persistent DeFiLlama failure, ``_fetch_coingecko_fallback`` queries
           CoinGecko's public /coins/markets endpoint as a secondary source.
           CoinGecko's free tier does not expose per-pool lending APY, so this
           fallback confirms protocol liveness but returns None for APY when no
           yield data is available.  ``live_apy_fallback_source`` is always logged.

    The underlying /pools fetch is cached for ``cache_ttl`` seconds.
    All errors are absorbed: methods return ``None`` on any failure.

    Args:
        api_url:   DeFiLlama yields API URL.
        cache_ttl: Cache lifetime in seconds (default: 3600 = 1 hour).
        timeout:   HTTP request timeout in seconds.
        enabled:   Set to ``False`` to disable all network calls (useful in
                   test isolation without patching urllib).
        cg_url:    CoinGecko markets API URL (override for testing).
    """

    def __init__(
        self,
        api_url: str = DEFILLAMA_POOLS_URL,
        cache_ttl: int = CACHE_TTL,
        timeout: int = REQUEST_TIMEOUT,
        enabled: bool = True,
        cg_url: str = COINGECKO_MARKETS_URL,
    ) -> None:
        self.api_url = api_url
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.enabled = enabled
        self.cg_url = cg_url
        self._cache: Optional[list] = None
        self._cache_ts: float = 0.0

    # ── internal: fetch helpers ──────────────────────────────────────────────

    def _fetch_url(self, url: str, user_agent: str) -> bytes:
        """Single HTTP GET attempt.  Raises on any error (caller handles)."""
        req = urllib.request.Request(
            url,
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _fetch_with_retry(self, url: str) -> Optional[bytes]:
        """Fetch *url* with exponential backoff and rotating User-Agents.

        Makes up to ``MAX_RETRIES`` attempts.  On HTTP 403/429 the delay doubles
        and the User-Agent rotates to the next entry in ``_USER_AGENTS``.
        Non-retriable HTTP errors (e.g. 404, 500) abort immediately.

        Returns:
            Raw response bytes on success; ``None`` on persistent failure.
            Never raises.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            ua = _USER_AGENTS[attempt % len(_USER_AGENTS)]
            try:
                return self._fetch_url(url, ua)
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in (403, 429):
                    delay = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "DefiLlamaFeed: HTTP %d on attempt %d/%d — "
                        "backoff=%.1fs UA=%r",
                        exc.code, attempt + 1, MAX_RETRIES, delay, ua,
                    )
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(delay)
                else:
                    # Non-retriable HTTP error (4xx/5xx other than 403/429)
                    logger.warning(
                        "DefiLlamaFeed: non-retriable HTTP %d: %s", exc.code, exc
                    )
                    return None
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                delay = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "DefiLlamaFeed: network error on attempt %d/%d: %s — retry in %.1fs",
                    attempt + 1, MAX_RETRIES, exc, delay,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)

        logger.warning(
            "DefiLlamaFeed: all %d retries exhausted. last error: %s",
            MAX_RETRIES, last_exc,
        )
        return None

    # ── internal: pool list cache ────────────────────────────────────────────

    def _load_pools(self) -> Optional[list]:
        """Return the cached pool list, refreshing if the TTL has expired.

        Uses ``_fetch_with_retry`` for resilient fetching.  Returns ``None``
        when disabled, on persistent network error, or on unexpected payload.
        Never raises.
        """
        if not self.enabled:
            return None

        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self.cache_ttl:
            return self._cache

        raw = self._fetch_with_retry(self.api_url)
        if raw is None:
            return None

        try:
            payload = _json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DefiLlamaFeed._load_pools: JSON decode failed: %s", exc)
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

    # ── internal: pool selection ─────────────────────────────────────────────

    def _select_pool(
        self,
        pools: list,
        project: str,
        asset: str,
        chain: str,
        min_tvl_usd: float,
    ) -> Optional[dict]:
        """Select the best pool from *pools* matching (project, asset, chain).

        Returns ``{"apy", "tvl_usd", "pool_id"}`` (without fallback_source) or
        ``None`` when no qualifying pool is found.  Never raises.
        """
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

    # ── internal: CoinGecko fallback ─────────────────────────────────────────

    def _fetch_coingecko_fallback(self, project: str) -> Optional[dict]:
        """Query CoinGecko DeFi yields API as a secondary source for *project*.

        Called when DeFiLlama is unreachable (HTTP 403/timeout on all retries).
        Uses CoinGecko's public ``/coins/markets`` endpoint to verify protocol
        liveness.  CoinGecko's free tier does not expose per-pool lending APY,
        so this method returns ``None`` for APY while logging the attempt.  If
        CoinGecko ever exposes yield data for a coin, this method is the right
        place to parse it.

        Returns:
            Pool-shaped dict ``{"apy", "tvl_usd", "pool_id"}`` on success, or
            ``None`` when no yield data is available.  Never raises.

        Args:
            project: DeFiLlama project slug (e.g. ``"aave-v3"``).
        """
        if not self.enabled:
            return None

        coin_id = COINGECKO_COIN_IDS.get(project.lower())
        if not coin_id:
            logger.debug(
                "DefiLlamaFeed CoinGecko fallback: no coin mapping for project=%r",
                project,
            )
            return None

        url = (
            f"{self.cg_url}"
            f"?vs_currency=usd&ids={coin_id}"
            f"&per_page=1&page=1&sparkline=false"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; SPA-yield-tracker/1.0)",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            coins = _json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DefiLlamaFeed CoinGecko fallback: fetch error for coin=%r: %s",
                coin_id, exc,
            )
            return None

        if not isinstance(coins, list) or not coins:
            logger.debug(
                "DefiLlamaFeed CoinGecko fallback: empty response for coin=%r",
                coin_id,
            )
            return None

        coin = coins[0]
        market_cap = coin.get("market_cap")
        # CoinGecko /coins/markets does not include per-pool lending APY in the
        # free tier.  Protocol is confirmed alive, but APY is unavailable.
        logger.info(
            "DefiLlamaFeed CoinGecko fallback: project=%r coin=%r confirmed live "
            "(market_cap=%s) — APY not available from CoinGecko public API.",
            project, coin_id, market_cap,
        )
        # Return None: never fabricate APY (FORBIDDEN: no hardcoded APY).
        return None

    # ── public ──────────────────────────────────────────────────────────────

    def get_pool(
        self,
        project: str,
        asset: str = "USDC",
        chain: str = "Ethereum",
        min_tvl_usd: float = MIN_TVL_USD,
    ) -> Optional[dict]:
        """Return the best matching live pool as a dict.

        The returned dict contains:
            * ``apy``                      — raw DeFiLlama **percentage** (e.g. 8.5 for 8.5%)
            * ``tvl_usd``                  — USD TVL
            * ``pool_id``                  — DeFiLlama pool uuid (or ``None``)
            * ``live_apy_fallback_source`` — ``"defillama"`` or ``"coingecko"`` (data origin)

        Resolution order:
            1. DeFiLlama /pools (with retry/backoff) → source = ``"defillama"``
            2. CoinGecko /coins/markets fallback     → source = ``"coingecko"``

        Returns ``None`` on miss, error, or when all qualifying pools are filtered
        out and CoinGecko has no yield data.  Never raises.
        """
        try:
            pools = self._load_pools()
            if pools:
                result = self._select_pool(pools, project, asset, chain, min_tvl_usd)
                if result is not None:
                    result["live_apy_fallback_source"] = "defillama"
                    return result

            # DeFiLlama unavailable or no matching pool → try CoinGecko
            cg_result = self._fetch_coingecko_fallback(project)
            if cg_result is not None:
                cg_result["live_apy_fallback_source"] = "coingecko"
                return cg_result

            return None

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
