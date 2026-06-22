"""
MP-1000: DeFiProtocolFeeTierOptimizer
Recommends optimal fee tier for DEX pools (Uniswap V3-style).

Read-only analytics module. Writes ring-buffer log to
data/fee_tier_optimization_log.json (cap 100, atomic write).

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_FEE_TIERS = (5, 30, 100, 500)          # bps
LOG_CAP = 100
_LOG_FILENAME = "fee_tier_optimization_log.json"

_ALL_LABELS = frozenset({
    "OPTIMAL_TIER",
    "SLIGHTLY_OVERPRICED",
    "SLIGHTLY_UNDERPRICED",
    "SIGNIFICANTLY_MISALIGNED",
    "EXTREME_MISMATCH",
})

_ALL_FLAGS = frozenset({
    "FEE_TOO_HIGH_FOR_STABLE",
    "FEE_TOO_LOW_FOR_VOLATILE",
    "ARBITRAGE_DOMINATED",
    "CONCENTRATED_LIQUIDITY_EFFICIENT",
    "SWITCH_RECOMMENDED",
})


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolFeeTierOptimizer:
    """
    Analyzes Uniswap V3-style liquidity pools and recommends the optimal
    fee tier based on volatility, correlation, arbitrage share, and
    tick concentration.

    Stable pairs (low vol / high corr) → 5 bps
    Medium volatility                  → 30 bps
    High volatility                    → 100 bps
    Exotic / very high volatility      → 500 bps
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_path = os.path.join(data_dir, _LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, pools: list, config: dict) -> dict:
        """
        Optimize fee tiers for a list of pools.

        Args:
            pools:  list[dict] — each dict describes one liquidity pool.
            config: dict — optional overrides:
                      log_enabled (bool, default True)
                      data_dir    (str, overrides self.data_dir)

        Returns:
            dict with keys: timestamp, module, mp, pool_count, pools, aggregates
        """
        if not isinstance(pools, list):
            raise TypeError("pools must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        # Allow config to override data_dir
        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)

        results = [self._analyze_pool(p) for p in pools]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "DeFiProtocolFeeTierOptimizer",
            "mp": "MP-1000",
            "pool_count": len(results),
            "pools": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-pool analysis
    # ------------------------------------------------------------------

    def _analyze_pool(self, pool: dict) -> dict:
        name = pool.get("name", "unknown")
        token_pair = pool.get("token_pair", "")
        current_fee_bps = int(pool.get("current_fee_tier_bps", 30))
        volume_24h = float(pool.get("volume_24h_usd", 0.0))
        tvl = float(pool.get("tvl_usd", 1.0))
        volatility = float(pool.get("price_volatility_30d_pct", 0.0))
        correlation = float(pool.get("correlation_with_eth", 0.0))
        arb_pct = float(pool.get("arbitrage_volume_pct", 0.0))
        tick_tightness = float(pool.get("tick_range_tightness_pct", 0.0))
        competing_pools = int(pool.get("competing_pools_same_pair", 0))
        swap_count = int(pool.get("swap_count_24h", 0))
        avg_swap_size = float(pool.get("avg_swap_size_usd", 0.0))

        # Guard against non-positive TVL
        if tvl <= 0.0:
            tvl = 1.0

        # ── Core metrics ──────────────────────────────────────────────
        fee_revenue_daily_usd = volume_24h * current_fee_bps / 10_000.0
        fee_apy_pct = fee_revenue_daily_usd * 365.0 / tvl * 100.0

        # Arbitrage drag: fraction of fee revenue captured by arbs, annualised
        arbitrage_drag_pct = (
            (arb_pct / 100.0) * volume_24h * current_fee_bps / 10_000.0
            / tvl * 365.0 * 100.0
        )

        # ── Optimal fee ───────────────────────────────────────────────
        optimal_fee_bps = self._determine_optimal_fee(volatility, correlation)

        # ── Mismatch score ────────────────────────────────────────────
        mismatch_score = (
            abs(current_fee_bps - optimal_fee_bps) / optimal_fee_bps * 100.0
            if optimal_fee_bps > 0 else 0.0
        )

        # ── Label & flags ─────────────────────────────────────────────
        label = self._determine_label(current_fee_bps, optimal_fee_bps, mismatch_score)
        flags = self._compute_flags(
            correlation, current_fee_bps, volatility,
            arb_pct, tick_tightness, label, mismatch_score,
        )

        # ── Optimal-tier revenue (counterfactual) ─────────────────────
        optimal_revenue_daily_usd = volume_24h * optimal_fee_bps / 10_000.0
        optimal_fee_apy_pct = optimal_revenue_daily_usd * 365.0 / tvl * 100.0

        return {
            # Input fields
            "name": name,
            "token_pair": token_pair,
            "current_fee_tier_bps": current_fee_bps,
            "volume_24h_usd": volume_24h,
            "tvl_usd": tvl,
            "price_volatility_30d_pct": volatility,
            "correlation_with_eth": correlation,
            "arbitrage_volume_pct": arb_pct,
            "tick_range_tightness_pct": tick_tightness,
            "competing_pools_same_pair": competing_pools,
            "swap_count_24h": swap_count,
            "avg_swap_size_usd": avg_swap_size,
            # Derived
            "fee_revenue_daily_usd": round(fee_revenue_daily_usd, 4),
            "fee_apy_pct": round(fee_apy_pct, 4),
            "arbitrage_drag_pct": round(arbitrage_drag_pct, 4),
            "optimal_fee_bps": optimal_fee_bps,
            "fee_tier_mismatch_score": round(mismatch_score, 2),
            "optimal_fee_revenue_daily_usd": round(optimal_revenue_daily_usd, 4),
            "optimal_fee_apy_pct": round(optimal_fee_apy_pct, 4),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Optimal fee determination
    # ------------------------------------------------------------------

    def _determine_optimal_fee(self, volatility: float, correlation: float) -> int:
        """
        stable_pairs  (corr>0.95 OR vol<5)  → 5 bps
        medium_vol    (5 ≤ vol < 30)         → 30 bps
        high_vol      (30 ≤ vol < 80)        → 100 bps
        exotic        (vol ≥ 80)             → 500 bps
        """
        if correlation > 0.95 or volatility < 5.0:
            return 5
        if volatility < 30.0:
            return 30
        if volatility < 80.0:
            return 100
        return 500

    # ------------------------------------------------------------------
    # Label determination
    # ------------------------------------------------------------------

    def _determine_label(
        self, current: int, optimal: int, mismatch: float
    ) -> str:
        """
        OPTIMAL_TIER          — current == optimal
        EXTREME_MISMATCH      — mismatch > 100 %
        SIGNIFICANTLY_MISALIGNED — mismatch > 50 %
        SLIGHTLY_OVERPRICED   — current > optimal, mismatch ≤ 50 %
        SLIGHTLY_UNDERPRICED  — current < optimal, mismatch ≤ 50 %
        """
        if current == optimal:
            return "OPTIMAL_TIER"
        if mismatch > 100.0:
            return "EXTREME_MISMATCH"
        if mismatch > 50.0:
            return "SIGNIFICANTLY_MISALIGNED"
        if current > optimal:
            return "SLIGHTLY_OVERPRICED"
        return "SLIGHTLY_UNDERPRICED"

    # ------------------------------------------------------------------
    # Flag computation
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        correlation: float,
        current_fee: int,
        volatility: float,
        arb_pct: float,
        tick_tightness: float,
        label: str,
        mismatch_score: float,
    ) -> list:
        flags: list[str] = []

        if correlation > 0.95 and current_fee > 30:
            flags.append("FEE_TOO_HIGH_FOR_STABLE")

        if volatility > 50.0 and current_fee < 100:
            flags.append("FEE_TOO_LOW_FOR_VOLATILE")

        if arb_pct > 60.0:
            flags.append("ARBITRAGE_DOMINATED")

        if tick_tightness > 50.0 and label == "OPTIMAL_TIER":
            flags.append("CONCENTRATED_LIQUIDITY_EFFICIENT")

        if mismatch_score > 40.0:
            flags.append("SWITCH_RECOMMENDED")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_optimized": None,
                "worst_mismatch": None,
                "avg_fee_apy": 0.0,
                "optimal_count": 0,
                "extreme_mismatch_count": 0,
            }

        most_optimized = min(results, key=lambda r: r["fee_tier_mismatch_score"])
        worst_mismatch = max(results, key=lambda r: r["fee_tier_mismatch_score"])
        avg_fee_apy = sum(r["fee_apy_pct"] for r in results) / len(results)
        optimal_count = sum(1 for r in results if r["label"] == "OPTIMAL_TIER")
        extreme_mismatch_count = sum(
            1 for r in results if r["label"] == "EXTREME_MISMATCH"
        )

        return {
            "most_optimized": most_optimized["name"],
            "worst_mismatch": worst_mismatch["name"],
            "avg_fee_apy": round(avg_fee_apy, 4),
            "optimal_count": optimal_count,
            "extreme_mismatch_count": extreme_mismatch_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, record: dict, data_dir: str) -> None:
        """Append compact entry to ring-buffer log (cap=LOG_CAP). Atomic."""
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, _LOG_FILENAME)

        try:
            with open(log_path, "r") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        entry = {
            "timestamp": record["timestamp"],
            "pool_count": record["pool_count"],
            "aggregates": record["aggregates"],
        }
        log.append(entry)
        log = log[-LOG_CAP:]  # ring-buffer

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
