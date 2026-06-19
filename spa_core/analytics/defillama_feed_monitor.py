"""
spa_core/analytics/defillama_feed_monitor.py

Monitors DeFiLlama API for protocol data availability.
Used for source promotion pipeline — checks which SOURCE_NEEDED protocols
now have data available on DeFiLlama.

Check patterns:
  GMX: search yields.llama.fi/pools for project="gmx" or "gmx-v2"
  BTC concentrated LP: search for btc+usd pools on Uniswap V3 Arbitrum
  RWA: search for "rwa" or "ondo" in pool names
  Gold proxy: search for "paxg" or "gold" in pool names

For each protocol, returns:
  {
    "protocol_id": str,
    "defillama_found": bool,
    "pool_count": int,
    "best_pool": {
      "pool_id": str,
      "project": str,
      "apy": float,
      "tvl_usd": float,
      "chain": str
    } | None,
    "data_period_available": str | None,  # "2+ years" | "6-12 months" | "< 6 months"
    "can_promote_to_pending": bool,
    "notes": str
  }

Rules:
  - stdlib only — no external dependencies
  - Atomic writes: tmp file + os.replace
  - Read-only / advisory — does NOT modify allocator / risk / execution
  - Graceful network fallback — never raises on timeout or connection error
  - LLM FORBIDDEN
  - Exit 0 always

Date: 2026-06-19 (MP-1336, Sprint v9.52)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from spa_core.base import BaseAnalytics
from typing import Dict, List, Optional

__all__ = ["DeFiLlamaFeedMonitor", "MONITORED_PROTOCOLS"]

logger = logging.getLogger(__name__)

# ── Protocol list ─────────────────────────────────────────────────────────────

MONITORED_PROTOCOLS: List[str] = [
    "gmx_btc_exposure",
    "gmx_eth_exposure",
    "btc_usd_conc_liq",
    "rwa_conc_liq",
    "trader_losses_vault",
    "gold_proxy",
]

# ── Per-protocol search parameters ───────────────────────────────────────────

_PROTOCOL_PARAMS: Dict[str, Dict] = {
    "gmx_btc_exposure": {
        "projects":   ["gmx", "gmx-v2"],
        "symbol_kw":  ["btc", "wbtc"],
        "chain":      None,
        "min_tvl":    1_000_000,
        "note":       "GMX GLP/GM BTC exposure — DeFiLlama project search",
    },
    "gmx_eth_exposure": {
        "projects":   ["gmx", "gmx-v2"],
        "symbol_kw":  ["eth", "weth"],
        "chain":      None,
        "min_tvl":    1_000_000,
        "note":       "GMX GLP/GM ETH exposure — DeFiLlama project search",
    },
    "btc_usd_conc_liq": {
        "projects":   ["uniswap-v3", "uniswap-v4", "aerodrome"],
        "symbol_kw":  ["btc", "wbtc"],
        "chain":      "Arbitrum",
        "min_tvl":    500_000,
        "note":       "BTC/USD concentrated LP — Uniswap V3 Arbitrum search",
    },
    "rwa_conc_liq": {
        "projects":   ["ondo-finance", "maple", "centrifuge"],
        "symbol_kw":  ["rwa", "ondo", "usdc"],
        "chain":      None,
        "min_tvl":    500_000,
        "note":       "RWA concentrated LP — RWA protocol search",
    },
    "trader_losses_vault": {
        "projects":   ["gmx", "gmx-v2", "hyperliquid"],
        "symbol_kw":  ["glp", "hb", "hlp"],
        "chain":      None,
        "min_tvl":    1_000_000,
        "note":       "Trader losses vault — GMX/Hyperliquid LP vault search",
    },
    "gold_proxy": {
        "projects":   [],  # search by symbol
        "symbol_kw":  ["paxg", "xaut", "gold"],
        "chain":      None,
        "min_tvl":    100_000,
        "note":       "Gold proxy — search for PAXG/XAUT pools on DeFiLlama",
    },
}

# Minimum TVL (USD) required to mark can_promote_to_pending = True
_PROMOTE_MIN_TVL: float = 100_000

# Minimum APY (%) required for promotion
_PROMOTE_MIN_APY: float = 0.1

# Timeout for HTTP requests (seconds)
_HTTP_TIMEOUT: int = 10


class DeFiLlamaFeedMonitor(BaseAnalytics):
    """Monitors DeFiLlama API for protocol data availability.

    Used for source promotion pipeline — promotes protocols from
    SOURCE_NEEDED → PENDING when data becomes available.

    Network calls are isolated to _fetch_pools(); all other logic is
    pure / deterministic.  Graceful fallback if network is unavailable.
    """

    OUTPUT_PATH = "data/research/defillama_monitor.json"

    API_BASE: str = "https://yields.llama.fi"

    def __init__(self) -> None:
        super().__init__()
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl: int = 3600  # seconds
        self._cache_ts: Dict[str, float] = {}

    def to_dict(self) -> dict:
        """Returns current cached monitoring results as JSON-serializable dict."""
        return dict(self._cache)

    # ── Public API ────────────────────────────────────────────────────────────

    def check_protocol(self, protocol_id: str) -> dict:
        """Check DeFiLlama for a given protocol.

        Graceful fallback if network is unavailable — never raises.

        Args:
            protocol_id: one of MONITORED_PROTOCOLS (or any string for fallback)

        Returns:
            dict with keys: protocol_id, defillama_found, pool_count,
                            best_pool, data_period_available,
                            can_promote_to_pending, notes
        """
        # Return cached result if fresh
        cached = self._get_cache(protocol_id)
        if cached is not None:
            return cached

        params = _PROTOCOL_PARAMS.get(protocol_id, {})
        note = params.get("note", f"Unknown protocol: {protocol_id}")

        pools_raw = self._fetch_pools()
        if pools_raw is None:
            # Network unavailable
            result = self._build_result(
                protocol_id=protocol_id,
                matched_pools=[],
                notes=f"{note} [network unavailable — graceful fallback]",
            )
            self._set_cache(protocol_id, result)
            return result

        matched = self._match_pools(protocol_id, params, pools_raw)
        result = self._build_result(
            protocol_id=protocol_id,
            matched_pools=matched,
            notes=note,
        )
        self._set_cache(protocol_id, result)
        return result

    def check_all(self) -> Dict[str, dict]:
        """Return check results for all MONITORED_PROTOCOLS.

        Returns:
            dict mapping protocol_id → check result dict
        """
        return {pid: self.check_protocol(pid) for pid in MONITORED_PROTOCOLS}

    def promotable_protocols(self) -> List[str]:
        """Return list of protocol IDs where can_promote_to_pending is True.

        Returns:
            List of protocol_id strings (subset of MONITORED_PROTOCOLS)
        """
        results = self.check_all()
        return [
            pid
            for pid, r in results.items()
            if r.get("can_promote_to_pending", False)
        ]

    def monitoring_report(self) -> Dict:
        """Generate summary report across all monitored protocols.

        Returns:
            dict with keys: checked_at, total_monitored, found_on_defillama,
                            promotable, protocols, recommendation
        """
        results = self.check_all()
        found_count = sum(1 for r in results.values() if r.get("defillama_found", False))
        promotable_list = [
            pid for pid, r in results.items() if r.get("can_promote_to_pending", False)
        ]

        if promotable_list:
            recommendation = (
                f"{len(promotable_list)} protocol(s) ready to promote from "
                f"SOURCE_NEEDED → PENDING: {', '.join(promotable_list)}"
            )
        else:
            recommendation = (
                "No protocols currently meet promotion criteria. "
                "Retry when DeFiLlama adds historical pool data for monitored protocols."
            )

        return {
            "checked_at":        datetime.now(tz=timezone.utc).isoformat(),
            "total_monitored":   len(MONITORED_PROTOCOLS),
            "found_on_defillama": found_count,
            "promotable":        len(promotable_list),
            "protocols":         results,
            "recommendation":    recommendation,
        }

    def save(self, path: str = "data/research/defillama_monitor.json") -> None:
        """Atomically save monitoring report to JSON.

        Args:
            path: output file path
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        report = self.monitoring_report()

        fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=".dlm_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, out_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ── Private: network ──────────────────────────────────────────────────────

    def _fetch_pools(self) -> Optional[List[Dict]]:
        """Fetch pool data from DeFiLlama yields API.

        Returns:
            List of pool dicts, or None if network unavailable.
        """
        url = f"{self.API_BASE}/pools"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SPA-Monitor/1.0"})
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            # DeFiLlama response is {"status": "ok", "data": [...]}
            if isinstance(raw, dict):
                return raw.get("data", [])
            if isinstance(raw, list):
                return raw
            return []
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
            logger.warning("DeFiLlama API unavailable — graceful fallback")
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("DeFiLlama API parse error: %s", exc)
            return None

    # ── Private: matching / scoring ───────────────────────────────────────────

    def _match_pools(
        self,
        protocol_id: str,
        params: Dict,
        pools: List[Dict],
    ) -> List[Dict]:
        """Filter pools matching this protocol's search parameters.

        Args:
            protocol_id: used for GMX-specific chain fallback
            params: search params from _PROTOCOL_PARAMS
            pools: raw pool list from DeFiLlama

        Returns:
            List of matching pool dicts (may be empty).
        """
        if not params:
            return []

        projects  = {p.lower() for p in params.get("projects", [])}
        sym_kw    = [k.lower() for k in params.get("symbol_kw", [])]
        chain_req = (params.get("chain") or "").lower()
        min_tvl   = params.get("min_tvl", 0)

        matched: List[Dict] = []
        for pool in pools:
            project   = str(pool.get("project", "")).lower()
            symbol    = str(pool.get("symbol", "")).lower()
            chain     = str(pool.get("chain", "")).lower()
            tvl       = float(pool.get("tvlUsd", 0) or 0)
            apy       = float(pool.get("apy", 0) or 0)

            # Project filter (if specified)
            if projects and project not in projects:
                continue

            # Symbol keyword filter
            if sym_kw and not any(k in symbol for k in sym_kw):
                continue

            # Chain filter (optional)
            if chain_req and chain_req not in chain:
                continue

            # TVL floor
            if tvl < min_tvl:
                continue

            matched.append({
                "pool_id": pool.get("pool", ""),
                "project": pool.get("project", ""),
                "symbol":  pool.get("symbol", ""),
                "apy":     apy,
                "tvl_usd": tvl,
                "chain":   pool.get("chain", ""),
            })

        return matched

    def _build_result(
        self,
        protocol_id: str,
        matched_pools: List[Dict],
        notes: str,
    ) -> Dict:
        """Build standardised result dict for a protocol check.

        Args:
            protocol_id: protocol identifier
            matched_pools: pools that passed match filters (may be empty)
            notes: human-readable notes string

        Returns:
            dict conforming to the module-level schema.
        """
        found = len(matched_pools) > 0
        best  = self._best_pool(matched_pools) if found else None

        # Promotion criteria: pool found + meets TVL and APY thresholds
        can_promote = (
            found
            and best is not None
            and best["tvl_usd"] >= _PROMOTE_MIN_TVL
            and best["apy"] >= _PROMOTE_MIN_APY
        )

        return {
            "protocol_id":           protocol_id,
            "defillama_found":       found,
            "pool_count":            len(matched_pools),
            "best_pool":             best,
            "data_period_available": self._infer_data_period(matched_pools),
            "can_promote_to_pending": can_promote,
            "notes":                 notes,
        }

    @staticmethod
    def _best_pool(pools: List[Dict]) -> Optional[Dict]:
        """Select the best pool by TVL (highest)."""
        if not pools:
            return None
        best = max(pools, key=lambda p: p.get("tvl_usd", 0))
        return {
            "pool_id": best["pool_id"],
            "project": best["project"],
            "apy":     best["apy"],
            "tvl_usd": best["tvl_usd"],
            "chain":   best["chain"],
        }

    @staticmethod
    def _infer_data_period(pools: List[Dict]) -> Optional[str]:
        """Infer approximate data period from pool metadata.

        DeFiLlama does not expose inception date in the /pools endpoint;
        we use pool TVL as a maturity proxy.
        """
        if not pools:
            return None
        max_tvl = max(p.get("tvl_usd", 0) for p in pools)
        if max_tvl >= 100_000_000:
            return "2+ years"
        if max_tvl >= 10_000_000:
            return "6-12 months"
        return "< 6 months"

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _get_cache(self, key: str) -> Optional[Dict]:
        if key not in self._cache:
            return None
        age = time.monotonic() - self._cache_ts.get(key, 0)
        if age > self._cache_ttl:
            del self._cache[key]
            return None
        return self._cache[key]

    def _set_cache(self, key: str, value: Dict) -> None:
        self._cache[key] = value
        self._cache_ts[key] = time.monotonic()
