"""
spa_core/adapters/gold_proxy_research.py — Gold Proxy Research Adapter (RESEARCH_ONLY)

Tracks DeFi yield opportunities with gold price exposure.
Status: RESEARCH_ONLY — no clean point-in-time historical data.

Known venues (2026):
  - PAXG/USDC LP pools (Uniswap, Balancer)
  - Synthetix sXAU staking (limited)
  - Ondo OUSG (US Treasury proxy, not gold but similar stability)
  - Backed Finance xBTC/xGOLD tokens

DeFiLlama: can search for "paxg" pools and "gold" keyword

Rules:
  - stdlib only (urllib.request, json, time, logging)
  - Timeout = 5s, graceful fallback on network error → FALLBACK_APY_PCT = 8.0
  - Not importable from execution / feed_health / risk
  - Atomic writes not required (adapter does not write state files)
  - LLM FORBIDDEN

Date: 2026-06-19 (MP-1315, Sprint v9.31)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module constants ──────────────────────────────────────────────────────────

RESEARCH_ONLY: bool = True
SOURCE_ID: str = "gold_proxy_research"

DEFI_LLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

# Fallback APY when network is unavailable or no pools found
FALLBACK_APY_PCT: float = 8.0

# HTTP timeout
REQUEST_TIMEOUT_S: int = 5

# Cache TTL
_CACHE_TTL_S: int = 300

# Keywords searched in DeFiLlama pool symbols/projects
_GOLD_KEYWORDS = ("paxg", "gold", "xau", "sxau", "xgold")

# Minimum TVL to consider a pool valid (USD)
_MIN_TVL_USD: float = 100_000.0

# Sanity APY bounds
_APY_MIN: float = 0.0
_APY_MAX: float = 200.0


# ── Venue registry ────────────────────────────────────────────────────────────

class GoldProxyResearchAdapter:
    """Research-only adapter for DeFi yield opportunities with gold price exposure.

    Queries DeFiLlama for PAXG/gold-related pools. Falls back to curated
    PROXY_VENUES estimates on any network error. Never raises from public methods.

    Public API:
        best_available_apy()          → float (best APY across known venues)
        fetch_defillama_gold_pools()  → list[dict] (live or empty on error)
        gold_proxy_apy()              → float (APY for RS-001 gold_proxy slot)
        venue_comparison()            → dict (all venues with APY + metadata)
        is_research_only()            → True
        source_metadata()             → dict
        invalidate_cache()            → None
    """

    # Known venues with estimated APYs (2026 research figures)
    PROXY_VENUES: dict = {
        "paxg_usdc_univ3": {
            "description": "PAXG/USDC Uniswap V3",
            "est_apy": 8.0,
            "chain": "ethereum",
            "protocol": "uniswap-v3",
            "asset": "PAXG",
            "note": "LP fees on gold/stablecoin pair; IL risk from gold price moves",
        },
        "ondo_ousg": {
            "description": "Ondo OUSG (Treasury)",
            "est_apy": 5.2,
            "chain": "ethereum",
            "protocol": "ondo-finance",
            "asset": "OUSG",
            "note": "US Treasury proxy, not direct gold but similar safe-haven stability",
        },
        "synthetix_sxau": {
            "description": "Synthetix sXAU",
            "est_apy": 6.0,
            "chain": "ethereum",
            "protocol": "synthetix",
            "asset": "sXAU",
            "note": "Synthetic gold, staking rewards; liquidity may be limited",
        },
    }

    def __init__(self) -> None:
        # Cache: (pool_list, timestamp)
        self._cache: Optional[list] = None
        self._cache_ts: float = 0.0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fetch_pools_raw(self) -> Optional[list]:
        """Fetch raw pool list from DeFiLlama with TTL cache.

        Returns list of pool dicts or None on any network/parse error.
        Never raises.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < _CACHE_TTL_S:
            return self._cache

        try:
            req = urllib.request.Request(
                DEFI_LLAMA_POOLS_URL,
                headers={
                    "Accept-Encoding": "gzip",
                    "User-Agent": "SPA-GoldProxyResearch/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                raw = resp.read()
            payload = json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            logger.warning("GoldProxyResearchAdapter: network error: %s", exc)
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("GoldProxyResearchAdapter: JSON parse error: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("GoldProxyResearchAdapter: unexpected error: %s", exc)
            return None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            logger.warning("GoldProxyResearchAdapter: unexpected DeFiLlama payload shape")
            return None

        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("GoldProxyResearchAdapter: 'data' is not a list")
            return None

        self._cache = data
        self._cache_ts = now
        return data

    @staticmethod
    def _is_gold_pool(pool: dict) -> bool:
        """Return True if pool symbol, project, or underlying tokens reference gold."""
        if not isinstance(pool, dict):
            return False
        text_fields = " ".join(
            str(pool.get(k, "")).lower()
            for k in ("symbol", "project", "chain", "underlyingTokens")
        )
        return any(kw in text_fields for kw in _GOLD_KEYWORDS)

    @staticmethod
    def _pool_to_entry(pool: dict) -> dict:
        """Normalise a DeFiLlama pool dict into a standard entry."""
        apy_raw = pool.get("apy")
        apy = float(apy_raw) if isinstance(apy_raw, (int, float)) else 0.0
        tvl_raw = pool.get("tvlUsd")
        tvl = float(tvl_raw) if isinstance(tvl_raw, (int, float)) else 0.0
        return {
            "pool_id":  str(pool.get("pool", "")),
            "protocol": str(pool.get("project", "")),
            "symbol":   str(pool.get("symbol", "")),
            "chain":    str(pool.get("chain", "")),
            "apy":      apy,
            "tvl":      tvl,
            "source":   "defillama",
        }

    def _venue_best_live_apy(self, pools: list) -> Optional[float]:
        """Return the best APY from live gold pools (sanity + TVL filtered).

        Picks the pool with the highest APY that passes sanity bounds and
        has at least _MIN_TVL_USD TVL.
        """
        best: Optional[float] = None
        for pool in pools:
            if not self._is_gold_pool(pool):
                continue
            apy_raw = pool.get("apy")
            if not isinstance(apy_raw, (int, float)):
                continue
            apy = float(apy_raw)
            if not (_APY_MIN < apy <= _APY_MAX):
                continue
            tvl_raw = pool.get("tvlUsd", 0)
            tvl = float(tvl_raw) if isinstance(tvl_raw, (int, float)) else 0.0
            if tvl < _MIN_TVL_USD:
                continue
            if best is None or apy > best:
                best = apy
        return best

    # ── Public API ────────────────────────────────────────────────────────────

    def best_available_apy(self) -> float:
        """Return best estimated APY across known gold proxy venues.

        Tries live DeFiLlama data first; falls back to the maximum
        estimated APY from PROXY_VENUES on any network error.

        Returns:
            APY in percent (float > 0). Fallback: FALLBACK_APY_PCT (8.0).
        """
        pools = self._fetch_pools_raw()
        if pools is not None:
            live_best = self._venue_best_live_apy(pools)
            if live_best is not None and live_best > 0:
                return live_best

        # Fallback: best estimate from static PROXY_VENUES
        venue_apys = [v["est_apy"] for v in self.PROXY_VENUES.values()]
        return max(venue_apys) if venue_apys else FALLBACK_APY_PCT

    def fetch_defillama_gold_pools(self) -> list:
        """Search DeFiLlama for gold-related pools.

        Returns:
            List of dicts {pool_id, protocol, symbol, chain, apy, tvl, source}.
            Empty list on network error or if no matching pools found.
            Never raises.
        """
        pools = self._fetch_pools_raw()
        if pools is None:
            logger.info("GoldProxyResearchAdapter.fetch_defillama_gold_pools: using fallback (no network)")
            # Return venue-based fallback entries so callers always get a list
            return [
                {
                    "pool_id":  key,
                    "protocol": v["protocol"],
                    "symbol":   v["asset"],
                    "chain":    v["chain"],
                    "apy":      v["est_apy"],
                    "tvl":      0.0,
                    "source":   "fallback_estimate",
                }
                for key, v in self.PROXY_VENUES.items()
            ]

        results = []
        for pool in pools:
            if self._is_gold_pool(pool):
                entry = self._pool_to_entry(pool)
                results.append(entry)

        # If live search returned nothing, fall back to estimates
        if not results:
            logger.info("GoldProxyResearchAdapter: no gold pools found on DeFiLlama, using estimates")
            return [
                {
                    "pool_id":  key,
                    "protocol": v["protocol"],
                    "symbol":   v["asset"],
                    "chain":    v["chain"],
                    "apy":      v["est_apy"],
                    "tvl":      0.0,
                    "source":   "fallback_estimate",
                }
                for key, v in self.PROXY_VENUES.items()
            ]

        return results

    def gold_proxy_apy(self) -> float:
        """Return APY for the RS-001 gold_proxy slot (15% weight).

        Uses best_available_apy() as the primary signal. Clips result to
        [0.01, 20.0] for safety (RS-001 gold slot is not expected to exceed 20%).

        Returns:
            APY in percent. Always > 0 and <= 20.0.
        """
        raw = self.best_available_apy()
        # Ensure sensible bounds for the RS-001 slot
        return float(max(0.01, min(raw, 20.0)))

    def venue_comparison(self) -> dict:
        """Return comparison of all PROXY_VENUES with APY and metadata.

        Returns:
            dict keyed by venue key (paxg_usdc_univ3, ondo_ousg, synthetix_sxau)
            with: description, est_apy, chain, protocol, note, source_quality.
        """
        pools = self._fetch_pools_raw()

        result: dict = {}
        for key, venue in self.PROXY_VENUES.items():
            entry = {
                "description":    venue["description"],
                "est_apy":        venue["est_apy"],
                "chain":          venue["chain"],
                "protocol":       venue["protocol"],
                "asset":          venue["asset"],
                "note":           venue["note"],
                "source_quality": "RESEARCH",
                "live_apy":       None,
            }

            # Try to enrich with live data
            if pools is not None:
                kw = venue["asset"].lower()
                for pool in pools:
                    sym = str(pool.get("symbol", "")).lower()
                    proj = str(pool.get("project", "")).lower()
                    if kw in sym or kw in proj:
                        apy_raw = pool.get("apy")
                        if isinstance(apy_raw, (int, float)) and _APY_MIN < float(apy_raw) <= _APY_MAX:
                            tvl_raw = pool.get("tvlUsd", 0)
                            tvl = float(tvl_raw) if isinstance(tvl_raw, (int, float)) else 0.0
                            if tvl >= _MIN_TVL_USD:
                                entry["live_apy"] = float(apy_raw)
                                break

            result[key] = entry

        return result

    def is_research_only(self) -> bool:
        """Always True — adapter is strictly read-only / advisory."""
        return RESEARCH_ONLY

    def source_metadata(self) -> dict:
        """Return metadata for source pipeline / audit."""
        return {
            "source_id":       SOURCE_ID,
            "adapter":         "GoldProxyResearchAdapter",
            "research_only":   RESEARCH_ONLY,
            "data_source":     "DeFiLlama yields API + curated estimates",
            "endpoint":        DEFI_LLAMA_POOLS_URL,
            "fallback_apy_pct": FALLBACK_APY_PCT,
            "timeout_s":       REQUEST_TIMEOUT_S,
            "cache_ttl_s":     _CACHE_TTL_S,
            "gold_keywords":   list(_GOLD_KEYWORDS),
            "venue_count":     len(self.PROXY_VENUES),
            "venue_keys":      list(self.PROXY_VENUES.keys()),
            "min_tvl_usd":     _MIN_TVL_USD,
            "risk_note": (
                "Gold proxy strategies carry gold price volatility, liquidity risk, "
                "and (for LP positions) impermanent loss. RESEARCH_ONLY — "
                "no point-in-time historical APY series confirmed."
            ),
        }

    def invalidate_cache(self) -> None:
        """Reset internal pool cache (useful in tests)."""
        self._cache = None
        self._cache_ts = 0.0
