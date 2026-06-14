"""
MP-998: DeFi Protocol Volume-to-TVL Efficiency Analyzer
Analyzes capital efficiency (velocity) across DeFi protocols by category.
Read-only analytics. stdlib only. Atomic ring-buffer write.
"""

import json
import os
import time
import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Category benchmark velocities (volume/TVL per day)
# ---------------------------------------------------------------------------
CATEGORY_BENCHMARKS = {
    "dex": 0.5,
    "lending": 0.1,
    "perps": 2.0,
    "options": 0.3,
    "stablecoin": 0.05,  # conservative default for unlisted
}
DEFAULT_BENCHMARK = 0.2

LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "volume_tvl_efficiency_log.json"
)
LOG_CAP = 100


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    if denom == 0:
        return default
    return num / denom


class DeFiProtocolVolumeToTVLEfficiencyAnalyzer:
    """
    Analyzes TVL capital efficiency (velocity = Volume/TVL) per protocol.
    All computation is deterministic and LLM-free.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: list, config: dict) -> dict:
        """
        Analyze a list of protocol dicts and return efficiency report.

        Parameters
        ----------
        protocols : list[dict]  — protocol snapshots (see module docstring)
        config    : dict        — options:
            data_dir  (str)  — override log directory
            log_cap   (int)  — override ring-buffer cap (default 100)
            skip_log  (bool) — skip writing the ring-buffer log

        Returns
        -------
        dict with keys:
            protocols  : list[dict]  — per-protocol analysis
            aggregates : dict        — summary stats
            timestamp  : str         — ISO-8601
            version    : str         — module version
        """
        results = [self._analyze_protocol(p, config) for p in protocols]

        aggregates = self._compute_aggregates(results)

        report = {
            "protocols": results,
            "aggregates": aggregates,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "version": "1.0.0",
            "module": "MP-998",
        }

        if not config.get("skip_log", False):
            self._append_log(report, config)

        return report

    # ------------------------------------------------------------------
    # Per-protocol analysis
    # ------------------------------------------------------------------

    def _analyze_protocol(self, p: dict, config: dict) -> dict:
        name = p.get("name", "unknown")
        category = str(p.get("category", "dex")).lower()
        tvl = float(p.get("total_tvl_usd", 0))
        vol7 = float(p.get("daily_volume_7d_avg_usd", 0))
        vol30 = float(p.get("daily_volume_30d_avg_usd", 0))
        fees7 = float(p.get("daily_fees_7d_avg_usd", 0))
        fees30 = float(p.get("daily_fees_30d_avg_usd", 0))
        active_markets = int(p.get("active_pairs_or_markets", 10))
        protocol_rev_share = float(p.get("protocol_revenue_share_pct", 50.0))
        lp_rev_share = float(p.get("lp_revenue_share_pct", 50.0))
        il_estimate = float(p.get("impermanent_loss_estimate_pct", 0.0))

        # Core metrics
        volume_to_tvl_ratio = _safe_div(vol7, tvl)
        fee_to_tvl_ratio_daily = _safe_div(fees7, tvl)
        fee_to_tvl_annualized = fee_to_tvl_ratio_daily * 365 * 100  # %
        lp_net_apy_pct = fee_to_tvl_annualized - il_estimate

        # Benchmark for category
        benchmark = CATEGORY_BENCHMARKS.get(category, DEFAULT_BENCHMARK)
        velocity_ratio = _safe_div(volume_to_tvl_ratio, benchmark)

        # Capital efficiency score (0-100): velocity ratio normalized
        # Score = 50 × velocity_ratio, capped at 100, then adjusted for markets
        capital_efficiency_score = _clamp(50.0 * velocity_ratio)
        # Bonus for active_markets depth (up to +10)
        depth_bonus = _clamp((active_markets - 1) / 49.0 * 10, 0, 10)
        capital_efficiency_score = _clamp(capital_efficiency_score + depth_bonus)

        # Revenue quality score (0-100)
        # Components: fee/volume ratio consistency + protocol_revenue_share
        fee_to_volume = _safe_div(fees7, vol7) * 100  # %
        fee_consistency = 0.0
        if vol7 > 0 and vol30 > 0 and fees7 > 0 and fees30 > 0:
            expected_fees30 = fees7  # ideal: same ratio
            actual_fees30 = fees30
            ratio = _safe_div(min(actual_fees30, expected_fees30),
                              max(actual_fees30, expected_fees30), 1.0)
            fee_consistency = ratio * 50.0
        else:
            fee_consistency = 25.0  # neutral when data incomplete

        rev_quality = fee_consistency + _clamp(protocol_rev_share / 100.0 * 50.0)
        revenue_quality_score = _clamp(rev_quality)

        # Efficiency label
        label = self._efficiency_label(velocity_ratio, capital_efficiency_score)

        # Flags
        flags = self._compute_flags(
            velocity_ratio=velocity_ratio,
            fee_to_tvl_annualized=fee_to_tvl_annualized,
            lp_net_apy_pct=lp_net_apy_pct,
            vol7=vol7,
            vol30=vol30,
            active_markets=active_markets,
        )

        return {
            "name": name,
            "category": category,
            "total_tvl_usd": tvl,
            "volume_to_tvl_ratio": round(volume_to_tvl_ratio, 6),
            "fee_to_tvl_ratio_daily": round(fee_to_tvl_ratio_daily, 6),
            "fee_to_tvl_annualized_pct": round(fee_to_tvl_annualized, 4),
            "lp_net_apy_pct": round(lp_net_apy_pct, 4),
            "capital_efficiency_score": round(capital_efficiency_score, 2),
            "revenue_quality_score": round(revenue_quality_score, 2),
            "benchmark_velocity": benchmark,
            "velocity_ratio_vs_benchmark": round(velocity_ratio, 4),
            "efficiency_label": label,
            "flags": flags,
            "active_pairs_or_markets": active_markets,
            "protocol_revenue_share_pct": protocol_rev_share,
            "lp_revenue_share_pct": lp_rev_share,
            "impermanent_loss_estimate_pct": il_estimate,
        }

    # ------------------------------------------------------------------
    # Labels & Flags
    # ------------------------------------------------------------------

    def _efficiency_label(self, velocity_ratio: float, score: float) -> str:
        """Determine efficiency label based on velocity_ratio vs benchmark."""
        if velocity_ratio > 2.0 and score > 80:
            return "CAPITAL_POWERHOUSE"
        if velocity_ratio > 1.5:
            return "HIGH_EFFICIENCY"
        if velocity_ratio >= 0.8:
            return "AVERAGE"
        if velocity_ratio >= 0.5:
            return "UNDERPERFORMING"
        return "CAPITAL_IDLE"

    def _compute_flags(
        self,
        velocity_ratio: float,
        fee_to_tvl_annualized: float,
        lp_net_apy_pct: float,
        vol7: float,
        vol30: float,
        active_markets: int,
    ) -> list:
        flags = []
        if velocity_ratio > 1.0:
            flags.append("ABOVE_BENCHMARK")
        if velocity_ratio < 0.5:
            flags.append("BELOW_BENCHMARK")
        if fee_to_tvl_annualized > 30.0:
            flags.append("HIGH_FEE_GENERATION")
        if lp_net_apy_pct < 0:
            flags.append("LP_NEGATIVE_YIELD")
        if vol30 > 0 and vol7 > 0 and vol30 < vol7 * 0.7:
            flags.append("VOLUME_DECLINING")
        if active_markets < 5 and vol7 > 0:
            flags.append("CONCENTRATED_VOLUME")
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_efficient": None,
                "least_efficient": None,
                "avg_capital_efficiency": 0.0,
                "powerhouse_count": 0,
                "idle_count": 0,
                "total_protocols": 0,
            }

        scores = [(r["capital_efficiency_score"], r["name"]) for r in results]
        most_efficient = max(scores, key=lambda x: x[0])[1]
        least_efficient = min(scores, key=lambda x: x[0])[1]
        avg = sum(s for s, _ in scores) / len(scores)
        powerhouse_count = sum(
            1 for r in results if r["efficiency_label"] == "CAPITAL_POWERHOUSE"
        )
        idle_count = sum(
            1 for r in results if r["efficiency_label"] == "CAPITAL_IDLE"
        )

        return {
            "most_efficient": most_efficient,
            "least_efficient": least_efficient,
            "avg_capital_efficiency": round(avg, 2),
            "powerhouse_count": powerhouse_count,
            "idle_count": idle_count,
            "total_protocols": len(results),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _resolve_log_path(self, config: dict) -> str:
        data_dir = config.get("data_dir")
        if data_dir:
            return os.path.join(data_dir, "volume_tvl_efficiency_log.json")
        return LOG_FILE

    def _append_log(self, report: dict, config: dict) -> None:
        log_path = self._resolve_log_path(config)
        cap = int(config.get("log_cap", LOG_CAP))

        # Load existing
        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                    entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                entries = []

        # Append summary entry
        entry = {
            "timestamp": report["timestamp"],
            "total_protocols": report["aggregates"]["total_protocols"],
            "avg_capital_efficiency": report["aggregates"]["avg_capital_efficiency"],
            "powerhouse_count": report["aggregates"]["powerhouse_count"],
            "idle_count": report["aggregates"]["idle_count"],
            "most_efficient": report["aggregates"]["most_efficient"],
            "least_efficient": report["aggregates"]["least_efficient"],
        }
        entries.append(entry)

        # Ring-buffer cap
        if len(entries) > cap:
            entries = entries[-cap:]

        # Atomic write
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        tmp = log_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, log_path)
