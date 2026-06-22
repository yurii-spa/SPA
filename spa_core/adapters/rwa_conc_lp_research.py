"""
spa_core/adapters/rwa_conc_lp_research.py — RWA Concentrated LP Research Adapter (RESEARCH_ONLY)

Tracks concentrated LP yield opportunities pairing RWA-backed stablecoins (OUSG, USDC)
in Uniswap V3 / Balancer-style tight ranges. The core position is OUSG-USDC, where
OUSG (Ondo Finance) provides T-bill yield (~4.8–5.2% APY) plus Uniswap V3 fee yield.

Status: RESEARCH_ONLY — no clean point-in-time historical data yet available.
Used by: RS-002 rwa_conc_liq slot.

Known venues (2026):
  - OUSG/USDC Uniswap V3 0.05% pool (Ethereum mainnet)
  - OUSG/USDC Uniswap V3 0.01% pool (tight peg range)
  - Ondo Finance OUSG direct (T-bill yield, ~4.8%)
  - Superstate USTB/USDC (similar RWA-backed stablecoin LP)

DeFiLlama: search "ondo" / "ousg" pools + "superstate" pools

Rules:
  - stdlib only (urllib.request, json, time, logging)
  - Timeout = 5s, graceful fallback on network error → FALLBACK_APY_PCT = 6.5
  - Not importable from execution / feed_health / risk
  - Atomic writes not required (adapter does not write state files)
  - LLM FORBIDDEN

Date: 2026-06-22 (Session IX, Sprint v12.81)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Module constants ──────────────────────────────────────────────────────────

RESEARCH_ONLY: bool = True
SOURCE_ID: str = "rwa_conc_lp"

DEFI_LLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

# Fallback APY (OUSG base T-bill yield + typical LP fee) when network unavailable
FALLBACK_APY_PCT: float = 6.5

# HTTP timeout
REQUEST_TIMEOUT_S: int = 5

# Cache TTL
_CACHE_TTL_S: int = 300

# DeFiLlama project/symbol keywords for RWA concentrated LP pools
_RWA_KEYWORDS = ("ousg", "ondo", "superstate", "ustb", "backed", "buidl")

# Minimum TVL to consider a pool valid (USD)
_MIN_TVL_USD: float = 500_000.0

# Sanity APY bounds
_APY_MIN: float = 0.0
_APY_MAX: float = 50.0  # RWA-backed yield won't spike like DeFi farm

# ── Venue registry ────────────────────────────────────────────────────────────

_KNOWN_VENUES: List[Dict[str, Any]] = [
    {
        "venue": "Uniswap V3 OUSG/USDC 0.05%",
        "protocol": "uniswap-v3",
        "asset_pair": "OUSG-USDC",
        "chain": "Ethereum",
        "estimated_apy_pct": 6.5,
        "note": "T-bill base (~4.8%) + LP fee yield (~1.7% at typical volume)",
        "tvl_usd": 2_000_000,
        "data_available": False,
        "pit_eligible": False,
    },
    {
        "venue": "Ondo Finance OUSG Direct",
        "protocol": "ondo-finance",
        "asset_pair": "OUSG",
        "chain": "Ethereum",
        "estimated_apy_pct": 4.8,
        "note": "Pure T-bill yield, no LP component — baseline for IL breakeven calc",
        "tvl_usd": 200_000_000,
        "data_available": False,
        "pit_eligible": False,
    },
    {
        "venue": "Superstate USTB/USDC",
        "protocol": "superstate",
        "asset_pair": "USTB-USDC",
        "chain": "Ethereum",
        "estimated_apy_pct": 5.1,
        "note": "Similar RWA LP structure; TVL smaller than OUSG",
        "tvl_usd": 50_000_000,
        "data_available": False,
        "pit_eligible": False,
    },
]


class RWAConcLPResearchAdapter:
    """Research-only adapter for RWA Concentrated LP yield (OUSG-USDC and peers).

    Queries DeFiLlama for OUSG/Ondo/Superstate pools. Falls back to curated
    venue estimates on any network error. Never raises from public methods.

    Public API:
        best_available_apy()              → float
        fetch_defillama_rwa_pools()       → list[dict]
        rwa_conc_lp_apy()                 → float
        venue_comparison()                → dict
        is_research_only()                → True
        source_metadata()                 → dict
        invalidate_cache()                → None
    """

    def __init__(self, http_timeout: int = REQUEST_TIMEOUT_S) -> None:
        # LLM FORBIDDEN — no language model calls in this adapter
        self._timeout = http_timeout
        self._pool_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_ts: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def is_research_only(self) -> bool:  # noqa: D401
        """Always True — this adapter is advisory/research only."""
        return True

    def best_available_apy(self) -> float:
        """Return best APY across all known RWA LP venues.

        Tries DeFiLlama first; falls back to curated estimates.
        Never raises.
        """
        # LLM FORBIDDEN
        try:
            pools = self.fetch_defillama_rwa_pools()
            if pools:
                apys = [p["apy"] for p in pools if p.get("apy") is not None]
                if apys:
                    return float(max(apys))
        except Exception:  # pylint: disable=broad-except
            logger.debug("rwa_conc_lp: DeFiLlama fetch failed, using curated APY")
        return FALLBACK_APY_PCT

    def rwa_conc_lp_apy(self) -> float:
        """APY to feed into RS-002 rwa_conc_liq slot. Capped at _APY_MAX."""
        # LLM FORBIDDEN
        raw = self.best_available_apy()
        return float(min(max(raw, _APY_MIN), _APY_MAX))

    def fetch_defillama_rwa_pools(self) -> List[Dict[str, Any]]:
        """Fetch DeFiLlama pools matching RWA keywords. Returns [] on error.

        Results are cached for _CACHE_TTL_S seconds.
        """
        # LLM FORBIDDEN
        now = time.monotonic()
        if self._pool_cache is not None and (now - self._cache_ts) < _CACHE_TTL_S:
            return self._pool_cache

        try:
            req = urllib.request.Request(
                DEFI_LLAMA_POOLS_URL,
                headers={"User-Agent": "SPA-adapter/1.0 (read-only)"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError, Exception):  # pylint: disable=broad-except
            logger.debug("rwa_conc_lp: failed to fetch DeFiLlama pools")
            return []

        pools_data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not isinstance(pools_data, list):
            return []

        matched: List[Dict[str, Any]] = []
        for pool in pools_data:
            if not isinstance(pool, dict):
                continue
            project = (pool.get("project") or "").lower()
            symbol = (pool.get("symbol") or "").lower()
            if not any(kw in project or kw in symbol for kw in _RWA_KEYWORDS):
                continue
            tvl = pool.get("tvlUsd", 0.0) or 0.0
            if float(tvl) < _MIN_TVL_USD:
                continue
            apy_raw = pool.get("apy") or pool.get("apyBase") or 0.0
            apy = float(apy_raw) if apy_raw is not None else 0.0
            if apy < _APY_MIN or apy > _APY_MAX:
                continue
            matched.append(
                {
                    "pool": pool.get("pool", ""),
                    "project": pool.get("project", ""),
                    "symbol": pool.get("symbol", ""),
                    "chain": pool.get("chain", ""),
                    "apy": apy,
                    "tvl": float(tvl),
                }
            )

        self._pool_cache = matched
        self._cache_ts = now
        return matched

    def venue_comparison(self) -> Dict[str, Any]:
        """Return dict with all known venues + live DeFiLlama data if available."""
        # LLM FORBIDDEN
        live_pools = []
        try:
            live_pools = self.fetch_defillama_rwa_pools()
        except Exception:  # pylint: disable=broad-except
            pass

        return {
            "source_id": SOURCE_ID,
            "research_only": True,
            "curated_venues": _KNOWN_VENUES,
            "live_defillama_pools": live_pools,
            "best_curated_apy_pct": max(v["estimated_apy_pct"] for v in _KNOWN_VENUES),
            "best_live_apy_pct": (
                max((p["apy"] for p in live_pools if p.get("apy") is not None), default=None)
                if live_pools
                else None
            ),
            "fallback_apy_pct": FALLBACK_APY_PCT,
            "notes": (
                "OUSG-USDC conc LP = T-bill base (~4.8%) + LP fee (~1.7%). "
                "IL risk low (tight peg range). KYC gating on OUSG limits TVL depth. "
                "Superstate USTB is a permissionless alternative with smaller TVL."
            ),
        }

    def source_metadata(self) -> Dict[str, Any]:
        """Return adapter metadata dict."""
        # LLM FORBIDDEN
        return {
            "source_id": SOURCE_ID,
            "adapter_class": "RWAConcLPResearchAdapter",
            "tier": "T2",
            "research_only": True,
            "asset": "OUSG-USDC",
            "chain": "Ethereum",
            "fallback_apy_pct": FALLBACK_APY_PCT,
            "data_available": False,
            "pit_eligible": False,
            "pit_note": "No PIT-clean historical series yet; requires exchange API agreement",
            "used_by": ["RS-002 rwa_conc_liq"],
            "risk_notes": (
                "IL low (tight stablecoin range), RWA credit risk (OUSG issuer), "
                "KYC required for direct OUSG. Regulatory: OUSG is a security token."
            ),
        }

    def invalidate_cache(self) -> None:
        """Force next fetch_defillama_rwa_pools() to bypass cache."""
        self._pool_cache = None
        self._cache_ts = 0.0


# ── Module-level convenience functions ───────────────────────────────────────

def get_rwa_conc_lp_apy() -> float:
    """Module-level convenience: return best APY for rwa_conc_lp source."""
    # LLM FORBIDDEN
    return RWAConcLPResearchAdapter().rwa_conc_lp_apy()
