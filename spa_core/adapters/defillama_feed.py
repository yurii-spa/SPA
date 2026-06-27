"""DeFiLlama yields API feed client.

Fetches live APY/TVL data from the DeFiLlama yields API and exposes a small,
cached lookup interface for SPA adapters. All network errors are caught and
logged, returning ``None`` — the feed is the **single source of truth** for
live yields and never invents data.

Two read surfaces, kept deliberately distinct (and individually tested):

* ``get_pool`` / ``get_apy`` / ``get_tvl`` — legacy SPA convention. ``get_apy``
  returns APY as a **decimal** (e.g. 0.085 == 8.5%), matching ``YieldInfo`` and
  the orchestrator (which multiplies by 100). No anomaly filtering.
* ``fetch_pool`` / ``fetch_apy`` / ``fetch_tvl`` (SPA-V398) — return APY as a raw
  **percentage** (e.g. 8.5 == 8.5%) and apply liveness filters: a minimum TVL
  floor (dead/spam pools are not "live") and an APY sanity band (reject < 0 or
  > 200 — clearly anomalous for a stablecoin pool). All return ``None`` rather
  than ever falling back to a mock value.
"""
from __future__ import annotations

import gzip
import json as _json
import logging
import math
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

# Public DeFiLlama yields endpoint (mirrors ``config.DEFILLAMA_API_URL``; exposed
# here so callers/tests can reference it without importing ``config``).
DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
# Default request timeout (seconds) for the live fetch.
REQUEST_TIMEOUT = 8
# Liveness filters for the ``fetch_*`` surface.
MIN_TVL_USD_DEFAULT = 100_000.0  # below this a pool is treated as dead/spam.
APY_SANITY_MAX = 200.0  # APY above this (or below 0) is rejected as an anomaly.
# A TVL above this is not real on-chain data (the whole DeFi market is << $1T).
# Beyond it (incl. an overflow-prone huge-but-finite value) we reject rather
# than leak an unbounded figure into allocation (fail-closed).
TVL_SANITY_MAX = 1e15


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
            # Pin Accept-Encoding to gzip: DeFiLlama otherwise serves brotli,
            # which some local brotli decoders mishandle (SPA-V398).
            req = urllib.request.Request(
                self.api_url,
                headers={"Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            # We pin Accept-Encoding: gzip; urllib does NOT auto-decompress, so
            # decompress when the gzip magic bytes are present (SPA-V398 fix).
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            payload = _json.loads(raw.decode("utf-8"))
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
        # bool is an int subclass; never treat True/False as a numeric APY.
        if not isinstance(apy, (int, float)) or isinstance(apy, bool):
            return None
        apy = float(apy)
        # json.loads accepts NaN/Infinity tokens by default → reject non-finite
        # so we never hand a fabricated/unbounded value downstream (fail-closed).
        if not math.isfinite(apy):
            return None
        return apy / 100.0

    def get_tvl(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[float]:
        """Return live TVL in USD, or ``None`` on miss/error."""
        pool = self.get_pool(project, symbol, chain)
        if pool is None:
            return None
        tvl = pool.get("tvlUsd")
        if not isinstance(tvl, (int, float)) or isinstance(tvl, bool):
            return None
        tvl = float(tvl)
        # Reject NaN/Infinity (json.loads emits them), negative and absurd TVL.
        if not math.isfinite(tvl) or tvl < 0 or tvl > TVL_SANITY_MAX:
            return None
        return tvl

    # --- liveness-filtered surface (SPA-V398) -------------------------------

    def fetch_pool(
        self,
        project: str,
        symbol: str,
        chain: str = "Ethereum",
        min_tvl_usd: float = MIN_TVL_USD_DEFAULT,
    ) -> Optional[dict]:
        """Return ``{"apy", "tvl", "pool_id"}`` for the best matching live pool.

        ``apy`` is the raw DeFiLlama **percentage** (e.g. 8.5 == 8.5%); ``tvl`` is
        USD; ``pool_id`` is the DeFiLlama pool uuid (or ``None``).

        Returns ``None`` — never a mock — when any of these hold:

        * the feed is disabled or unreachable (no network / parse error),
        * no pool matches ``project`` (case-insensitive *contains*), ``symbol``
          (exact, upper-cased) and ``chain`` (exact, case-insensitive),
        * the matched pool's TVL is below ``min_tvl_usd`` (dead/spam pool),
        * the APY is missing or outside the sanity band ``0 <= apy <= 200``.

        Among several qualifying matches, the one with the largest TVL wins.
        This method never raises.
        """
        try:
            pools = self._fetch_pools()
            if not pools:
                return None

            project_l = project.lower()
            symbol_u = symbol.upper()
            chain_l = chain.lower()

            best: Optional[dict] = None
            best_tvl = float("-inf")
            for pool in pools:
                if not isinstance(pool, dict):
                    continue
                # project: case-insensitive substring match (handles
                # "morpho-blue" vs "morpho", "compound-v3" etc.).
                if project_l not in str(pool.get("project", "")).lower():
                    continue
                if str(pool.get("symbol", "")).upper() != symbol_u:
                    continue
                if str(pool.get("chain", "")).lower() != chain_l:
                    continue

                tvl = pool.get("tvlUsd")
                if isinstance(tvl, (int, float)) and not isinstance(tvl, bool):
                    tvl = float(tvl)
                else:
                    tvl = 0.0
                # Reject NaN/Infinity TVL (json.loads emits them): treat as 0
                # so the pool fails the floor below rather than leaking inf.
                if not math.isfinite(tvl):
                    tvl = 0.0
                if tvl < min_tvl_usd or tvl > TVL_SANITY_MAX:
                    # Dead/spam pool (too small) or absurd (not real) — skip.
                    continue

                apy = pool.get("apy")
                if not isinstance(apy, (int, float)) or isinstance(apy, bool):
                    continue
                apy = float(apy)
                # NaN slips past `apy < 0 or apy > MAX` (NaN comparisons are
                # always False) → reject non-finite explicitly first (fail-closed).
                if not math.isfinite(apy) or apy < 0 or apy > APY_SANITY_MAX:
                    logger.warning(
                        "DeFiLlama %s/%s on %s: anomalous APY %.4f%% rejected",
                        project,
                        symbol,
                        chain,
                        apy,
                    )
                    continue

                if tvl > best_tvl:
                    best_tvl = tvl
                    best = pool

            if best is None:
                return None

            return {
                "apy": float(best.get("apy")),
                "tvl": best_tvl,
                "pool_id": best.get("pool"),
            }
        except Exception as exc:  # noqa: BLE001 - graceful: never raise, never mock.
            logger.warning("DeFiLlama fetch_pool failed for %s/%s: %s", project, symbol, exc)
            return None

    def fetch_apy(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[float]:
        """Return live APY as a **percentage** (e.g. 8.5), or ``None``."""
        result = self.fetch_pool(project, symbol, chain)
        return result["apy"] if result else None

    def fetch_tvl(
        self, project: str, symbol: str, chain: str = "Ethereum"
    ) -> Optional[float]:
        """Return live TVL in USD, or ``None``."""
        result = self.fetch_pool(project, symbol, chain)
        return result["tvl"] if result else None


# end of file
