"""
MP-1024: DeFiProtocolLiquidityFragmentationAnalyzer
Analyzes liquidity fragmentation across chains and pools for a single asset.

Read-only analytics module. Writes ring-buffer log to
data/liquidity_fragmentation_log.json (cap 100, atomic write).

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_CAP = 100
_LOG_FILENAME = "liquidity_fragmentation_log.json"

# HHI thresholds
_HHI_UNIFIED = 6000       # pool_HHI > 6000 → concentrated / unified
_HHI_LOW_FRAG = 4000      # pool_HHI > 4000 → low fragmentation
_HHI_MODERATE = 2000      # pool_HHI > 2000 → moderate fragmentation
_HHI_HIGH = 1000          # pool_HHI > 1000 → high fragmentation
# < 1000 or deviation > 100bps → severely fragmented / HHI < 500 → severely

# Price deviation thresholds (bps)
_DEV_UNIFIED = 5          # < 5 bps → unified
_DEV_MODERATE = 20        # < 20 bps → low/moderate
_DEV_HIGH = 50            # > 50 bps → high fragmentation
_DEV_SEVERE = 100         # > 100 bps → severely fragmented

# Flag thresholds
_AGG_DEPENDENT_THRESHOLD = 70.0   # aggregator_routed_pct > 70
_CANONICAL_DOMINANCE_THRESHOLD = 70.0
_LARGEST_POOL_UNIFIED_THRESHOLD = 60.0

_ALL_LABELS = frozenset({
    "UNIFIED_LIQUIDITY",
    "LOW_FRAGMENTATION",
    "MODERATE_FRAGMENTATION",
    "HIGH_FRAGMENTATION",
    "SEVERELY_FRAGMENTED",
})

_ALL_FLAGS = frozenset({
    "AGGREGATOR_DEPENDENT",
    "CROSS_CHAIN_ARBITRAGE_OPPORTUNITY",
    "CANONICAL_DOMINANCE",
    "PRICE_DEVIATION_HIGH",
    "UNIFIED_DEEP_POOL",
})


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolLiquidityFragmentationAnalyzer:
    """
    Analyzes liquidity fragmentation for DeFi protocols.

    Each protocol entry describes a single asset's liquidity spread across
    chains and pools. The analyzer computes HHI-based fragmentation metrics,
    slippage multiplier, aggregator dependency, and price efficiency.
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_path = os.path.join(data_dir, _LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: list, config: dict) -> dict:
        """
        Analyze liquidity fragmentation for a list of protocols.

        Args:
            protocols: list[dict] — each dict describes one protocol/asset.
            config:    dict — optional overrides:
                         log_enabled (bool, default True)
                         data_dir    (str, overrides self.data_dir)

        Returns:
            dict with keys: timestamp, module, mp, protocol_count, protocols, aggregates
        """
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)

        results = [self._analyze_protocol(p) for p in protocols]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "DeFiProtocolLiquidityFragmentationAnalyzer",
            "mp": "MP-1024",
            "protocol_count": len(results),
            "protocols": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-protocol analysis
    # ------------------------------------------------------------------

    def _analyze_protocol(self, protocol: dict) -> dict:
        name = protocol.get("name", "unknown")
        asset_pair = protocol.get("asset_pair", "")
        total_liquidity_usd = float(protocol.get("total_liquidity_usd", 0.0))
        chain_distribution = dict(protocol.get("chain_distribution", {}))
        pool_distribution = dict(protocol.get("pool_distribution", {}))
        largest_single_pool_pct = float(protocol.get("largest_single_pool_pct", 0.0))
        cross_chain_bridge_volume_7d = float(protocol.get("cross_chain_bridge_volume_7d_usd", 0.0))
        canonical_chain = protocol.get("canonical_chain", "ethereum")
        aggregator_routed_pct = float(protocol.get("aggregator_routed_pct", 0.0))
        price_deviation_max_bps = float(protocol.get("price_deviation_max_bps", 0.0))

        # Core metrics
        chain_hhi = self._compute_hhi(chain_distribution)
        pool_hhi = self._compute_hhi(pool_distribution)
        fragmentation_score = self._compute_fragmentation_score(pool_hhi, price_deviation_max_bps)
        effective_slippage_multiplier = self._compute_slippage_multiplier(
            pool_hhi, price_deviation_max_bps, total_liquidity_usd
        )
        aggregator_dependency_score = self._compute_aggregator_dependency_score(aggregator_routed_pct)
        price_efficiency_score = self._compute_price_efficiency_score(price_deviation_max_bps)

        # Canonical chain dominance pct
        canonical_pct = self._canonical_chain_pct(chain_distribution, canonical_chain)

        label = self._determine_label(pool_hhi, price_deviation_max_bps)
        flags = self._compute_flags(
            aggregator_routed_pct,
            price_deviation_max_bps,
            canonical_pct,
            largest_single_pool_pct,
        )

        return {
            "name": name,
            "asset_pair": asset_pair,
            "total_liquidity_usd": total_liquidity_usd,
            "canonical_chain": canonical_chain,
            "chain_herfindahl": round(chain_hhi, 2),
            "pool_herfindahl": round(pool_hhi, 2),
            "fragmentation_score": round(fragmentation_score, 2),
            "effective_slippage_multiplier": round(effective_slippage_multiplier, 4),
            "aggregator_dependency_score": round(aggregator_dependency_score, 2),
            "price_efficiency_score": round(price_efficiency_score, 2),
            "canonical_chain_pct": round(canonical_pct, 2),
            "aggregator_routed_pct": aggregator_routed_pct,
            "price_deviation_max_bps": price_deviation_max_bps,
            "cross_chain_bridge_volume_7d_usd": cross_chain_bridge_volume_7d,
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # HHI computation
    # ------------------------------------------------------------------

    def _compute_hhi(self, distribution: dict) -> float:
        """
        Compute Herfindahl-Hirschman Index (0–10000) from a distribution dict.
        Returns 10000 if single entry, 0 if empty.
        """
        if not distribution:
            return 0.0
        total = sum(float(v) for v in distribution.values())
        if total <= 0:
            return 0.0
        return sum((float(v) / total * 100) ** 2 for v in distribution.values())

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

    def _compute_fragmentation_score(self, pool_hhi: float, deviation_bps: float) -> float:
        """
        Fragmentation score 0-100.
        Low HHI (spread liquidity) + high deviation = high fragmentation (score near 100).
        High HHI (concentrated)   + low deviation  = low fragmentation (score near 0).
        """
        # Convert HHI to concentration ratio (0=fully fragmented, 1=fully unified)
        hhi_concentration = pool_hhi / 10000.0
        # Convert deviation: 0bps=no fragmentation, 100+bps=severe
        deviation_factor = min(1.0, deviation_bps / 100.0)
        # Fragmentation = inverse of concentration blended with deviation
        fragmentation = (1.0 - hhi_concentration) * 0.6 + deviation_factor * 0.4
        return min(100.0, max(0.0, fragmentation * 100.0))

    def _compute_slippage_multiplier(
        self, pool_hhi: float, deviation_bps: float, total_liquidity_usd: float
    ) -> float:
        """
        Effective slippage multiplier.
        1.0 = unified liquidity (no penalty).
        >1.0 = fragmentation raises effective slippage.
        """
        # When fully unified (HHI=10000, deviation=0) → 1.0
        # When severely fragmented (HHI→0, deviation=100bps) → up to ~3.0
        hhi_factor = 1.0 - (pool_hhi / 10000.0)          # 0=unified, 1=fragmented
        deviation_factor = min(1.0, deviation_bps / 100.0)
        raw = 1.0 + hhi_factor * 1.5 + deviation_factor * 0.5
        return round(max(1.0, raw), 4)

    def _compute_aggregator_dependency_score(self, aggregator_routed_pct: float) -> float:
        """
        Aggregator dependency score 0-100.
        0% aggregator routed → 0 dependency.
        100% aggregator routed → 100 dependency.
        """
        return min(100.0, max(0.0, aggregator_routed_pct))

    def _compute_price_efficiency_score(self, deviation_bps: float) -> float:
        """
        Price efficiency score 0-100.
        0 deviation → 100 (perfectly efficient).
        100+ bps → 0 (very inefficient).
        """
        return min(100.0, max(0.0, (1.0 - deviation_bps / 100.0) * 100.0))

    def _canonical_chain_pct(self, chain_distribution: dict, canonical_chain: str) -> float:
        """Percentage of total liquidity on the canonical chain."""
        if not chain_distribution:
            return 0.0
        total = sum(float(v) for v in chain_distribution.values())
        if total <= 0:
            return 0.0
        canonical_tvl = float(chain_distribution.get(canonical_chain, 0.0))
        return (canonical_tvl / total) * 100.0

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _determine_label(self, pool_hhi: float, deviation_bps: float) -> str:
        """
        UNIFIED_LIQUIDITY      — pool_HHI > 6000 AND deviation < 5 bps
        LOW_FRAGMENTATION      — pool_HHI > 4000 AND deviation < 20 bps
        MODERATE_FRAGMENTATION — pool_HHI > 2000
        HIGH_FRAGMENTATION     — pool_HHI > 1000 OR deviation > 50 bps (but not severe)
        SEVERELY_FRAGMENTED    — pool_HHI < 500 OR deviation > 100 bps
        """
        if pool_hhi < 500 or deviation_bps > 100:
            return "SEVERELY_FRAGMENTED"
        if pool_hhi > _HHI_UNIFIED and deviation_bps < _DEV_UNIFIED:
            return "UNIFIED_LIQUIDITY"
        if pool_hhi > _HHI_LOW_FRAG and deviation_bps < _DEV_MODERATE:
            return "LOW_FRAGMENTATION"
        # High deviation or low HHI → HIGH before MODERATE
        if pool_hhi <= _HHI_HIGH or deviation_bps > _DEV_HIGH:
            return "HIGH_FRAGMENTATION"
        if pool_hhi > _HHI_MODERATE:
            return "MODERATE_FRAGMENTATION"
        return "MODERATE_FRAGMENTATION"

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        aggregator_routed_pct: float,
        deviation_bps: float,
        canonical_pct: float,
        largest_single_pool_pct: float,
    ) -> list:
        flags = []
        if aggregator_routed_pct > _AGG_DEPENDENT_THRESHOLD:
            flags.append("AGGREGATOR_DEPENDENT")
        if deviation_bps > _DEV_MODERATE:
            flags.append("CROSS_CHAIN_ARBITRAGE_OPPORTUNITY")
        if canonical_pct > _CANONICAL_DOMINANCE_THRESHOLD:
            flags.append("CANONICAL_DOMINANCE")
        if deviation_bps > _DEV_HIGH:
            flags.append("PRICE_DEVIATION_HIGH")
        if largest_single_pool_pct > _LARGEST_POOL_UNIFIED_THRESHOLD and deviation_bps < _DEV_UNIFIED:
            flags.append("UNIFIED_DEEP_POOL")
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_unified": None,
                "most_fragmented": None,
                "avg_fragmentation_score": 0.0,
                "severely_fragmented_count": 0,
                "unified_count": 0,
            }

        scores = [(r["name"], r["fragmentation_score"]) for r in results]
        most_unified = min(scores, key=lambda x: x[1])[0]
        most_fragmented = max(scores, key=lambda x: x[1])[0]
        avg_score = sum(r["fragmentation_score"] for r in results) / len(results)
        severely_count = sum(1 for r in results if r["label"] == "SEVERELY_FRAGMENTED")
        unified_count = sum(1 for r in results if r["label"] == "UNIFIED_LIQUIDITY")

        return {
            "most_unified": most_unified,
            "most_fragmented": most_fragmented,
            "avg_fragmentation_score": round(avg_score, 2),
            "severely_fragmented_count": severely_count,
            "unified_count": unified_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict, data_dir: str) -> None:
        log_path = os.path.join(data_dir, _LOG_FILENAME)
        os.makedirs(data_dir, exist_ok=True)

        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
