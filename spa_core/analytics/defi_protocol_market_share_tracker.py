"""
MP-982: DeFi Protocol Market Share Tracker
Tracks market share dynamics across DeFi protocol categories.
Read-only analytics module — never modifies allocator/risk/execution.
Stdlib only, atomic writes, ring-buffer log cap 100.
"""

import json
import os
from datetime import datetime, timezone
from spa_core.utils.atomic import atomic_save

# Default log file
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "market_share_log.json"
)

LOG_CAP = 100

VALID_CATEGORIES = {
    "dex", "lending", "perp", "bridge", "liquid_staking", "yield"
}


class DeFiProtocolMarketShareTracker:
    """
    Tracks market share dynamics across DeFi protocol categories.

    Each protocol dict must contain:
        name                    (str)
        category                (str: dex/lending/perp/bridge/liquid_staking/yield)
        tvl_current_usd         (float)
        tvl_30d_ago_usd         (float)
        volume_30d_usd          (float)
        volume_90d_ago_usd      (float)
        fees_30d_usd            (float)
        unique_users_30d        (int)
        integrations_count      (int)

    config keys (all optional):
        log_path                (str)   path for ring-buffer JSON log
        write_log               (bool)  default True
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def track(self, protocols: list[dict], config: dict | None = None) -> dict:
        """
        Compute market-share analytics for a list of protocols.

        Returns dict with:
            protocols           list of per-protocol result dicts
            category_summary    dict keyed by category
            tracked_at          ISO timestamp
        """
        if config is None:
            config = {}

        log_path = config.get("log_path", DEFAULT_LOG_PATH)
        write_log = config.get("write_log", True)

        if not protocols:
            result = {
                "protocols": [],
                "category_summary": {},
                "tracked_at": self._now_iso(),
                "error": "no_protocols",
            }
            return result

        # Validate & normalise inputs
        normalised = [self._normalise(p) for p in protocols]

        # Group by category
        by_cat: dict[str, list[dict]] = {}
        for p in normalised:
            by_cat.setdefault(p["category"], []).append(p)

        # Compute category-level totals needed for share calculations
        cat_totals = self._compute_category_totals(by_cat)

        # Compute per-protocol metrics
        results = []
        for p in normalised:
            metrics = self._compute_protocol_metrics(p, by_cat[p["category"]], cat_totals)
            results.append(metrics)

        # Category summaries
        cat_summary = self._compute_category_summaries(results, by_cat)

        output = {
            "protocols": results,
            "category_summary": cat_summary,
            "tracked_at": self._now_iso(),
        }

        if write_log:
            self._append_log(output, log_path)

        return output

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalise(p: dict) -> dict:
        """Return a copy with numeric fields coerced and defaults applied."""
        return {
            "name":                 str(p.get("name", "unknown")),
            "category":             str(p.get("category", "dex")).lower(),
            "tvl_current_usd":      float(p.get("tvl_current_usd", 0.0)),
            "tvl_30d_ago_usd":      float(p.get("tvl_30d_ago_usd", 0.0)),
            "volume_30d_usd":       float(p.get("volume_30d_usd", 0.0)),
            "volume_90d_ago_usd":   float(p.get("volume_90d_ago_usd", 0.0)),
            "fees_30d_usd":         float(p.get("fees_30d_usd", 0.0)),
            "unique_users_30d":     int(p.get("unique_users_30d", 0)),
            "integrations_count":   int(p.get("integrations_count", 0)),
        }

    @staticmethod
    def _compute_category_totals(by_cat: dict) -> dict:
        """
        Returns:
            {category: {total_tvl_current, total_tvl_30d, total_volume_30d}}
        """
        totals: dict[str, dict] = {}
        for cat, protos in by_cat.items():
            total_tvl_cur  = sum(p["tvl_current_usd"]  for p in protos)
            total_tvl_30d  = sum(p["tvl_30d_ago_usd"]  for p in protos)
            total_vol_30d  = sum(p["volume_30d_usd"]   for p in protos)
            totals[cat] = {
                "total_tvl_current":  total_tvl_cur,
                "total_tvl_30d":      total_tvl_30d,
                "total_volume_30d":   total_vol_30d,
            }
        return totals

    def _compute_protocol_metrics(
        self,
        p: dict,
        category_peers: list[dict],
        cat_totals: dict,
    ) -> dict:
        cat = p["category"]
        totals = cat_totals[cat]

        # --- TVL market share ---
        total_tvl_cur = totals["total_tvl_current"]
        total_tvl_30d = totals["total_tvl_30d"]

        tvl_share_pct = (
            p["tvl_current_usd"] / total_tvl_cur * 100.0
            if total_tvl_cur > 0 else 0.0
        )
        tvl_share_30d_ago_pct = (
            p["tvl_30d_ago_usd"] / total_tvl_30d * 100.0
            if total_tvl_30d > 0 else 0.0
        )
        tvl_share_change_30d = tvl_share_pct - tvl_share_30d_ago_pct

        # --- Volume market share ---
        total_vol_30d = totals["total_volume_30d"]
        vol_share_pct = (
            p["volume_30d_usd"] / total_vol_30d * 100.0
            if total_vol_30d > 0 else 0.0
        )

        # --- Volume growth ---
        vol_growth_pct = (
            (p["volume_30d_usd"] - p["volume_90d_ago_usd"]) / p["volume_90d_ago_usd"] * 100.0
            if p["volume_90d_ago_usd"] > 0 else 0.0
        )

        # --- Capital efficiency: volume / TVL ---
        capital_efficiency = (
            p["volume_30d_usd"] / p["tvl_current_usd"]
            if p["tvl_current_usd"] > 0 else 0.0
        )

        # --- Stickiness score (0-100) ---
        # users_component: normalise unique_users_30d against category max
        max_users  = max((q["unique_users_30d"]    for q in category_peers), default=1) or 1
        max_integr = max((q["integrations_count"]  for q in category_peers), default=1) or 1
        max_eff    = max(
            (q["volume_30d_usd"] / q["tvl_current_usd"] if q["tvl_current_usd"] > 0 else 0.0
             for q in category_peers),
            default=1
        ) or 1

        user_norm  = min(p["unique_users_30d"]   / max_users  * 100.0, 100.0)
        integr_norm= min(p["integrations_count"] / max_integr * 100.0, 100.0)
        eff_norm   = min(capital_efficiency      / max_eff    * 100.0, 100.0)

        stickiness = user_norm * 0.4 + integr_norm * 0.3 + eff_norm * 0.3

        # --- Market position label ---
        if tvl_share_change_30d < -5.0:
            position = "DECLINING"
        elif tvl_share_pct > 40.0:
            position = "DOMINANT"
        elif tvl_share_pct > 20.0:
            position = "LEADING"
        elif tvl_share_pct > 10.0:
            position = "CHALLENGER"
        else:
            position = "NICHE"

        # --- Flags ---
        flags: list[str] = []
        if tvl_share_change_30d > 2.0:
            flags.append("GAINING_SHARE")
        if tvl_share_change_30d < -2.0:
            flags.append("LOSING_SHARE")
        if capital_efficiency > 0.5:
            flags.append("HIGH_EFFICIENCY")
        if stickiness > 70.0:
            flags.append("STICKY_PROTOCOL")
        # CATEGORY_LEADER check: highest TVL in category
        if p["tvl_current_usd"] == max(q["tvl_current_usd"] for q in category_peers):
            flags.append("CATEGORY_LEADER")

        return {
            "name":                      p["name"],
            "category":                  cat,
            "tvl_current_usd":           p["tvl_current_usd"],
            "tvl_market_share_pct":      round(tvl_share_pct, 4),
            "volume_market_share_pct":   round(vol_share_pct, 4),
            "tvl_share_change_30d_pct":  round(tvl_share_change_30d, 4),
            "volume_growth_pct":         round(vol_growth_pct, 4),
            "capital_efficiency":        round(capital_efficiency, 6),
            "protocol_stickiness_score": round(stickiness, 2),
            "market_position":           position,
            "flags":                     flags,
        }

    @staticmethod
    def _hhi(shares: list[float]) -> float:
        """Herfindahl-Hirschman Index from market share percentages (0-100 scale → 0-10000)."""
        return sum(s ** 2 for s in shares)

    def _compute_category_summaries(
        self,
        results: list[dict],
        by_cat: dict,
    ) -> dict:
        summary: dict[str, dict] = {}
        # Group results by category
        by_cat_results: dict[str, list[dict]] = {}
        for r in results:
            by_cat_results.setdefault(r["category"], []).append(r)

        for cat, protos in by_cat_results.items():
            total_tvl = sum(p["tvl_current_usd"] for p in protos)
            shares = [p["tvl_market_share_pct"] for p in protos]
            hhi = self._hhi(shares)

            # Category leader: highest TVL
            leader = max(protos, key=lambda x: x["tvl_current_usd"])
            # Fastest growing (by tvl_share_change_30d)
            fastest_growing = max(protos, key=lambda x: x["tvl_share_change_30d_pct"])
            # Fastest declining
            fastest_declining = min(protos, key=lambda x: x["tvl_share_change_30d_pct"])

            summary[cat] = {
                "category_leader":       leader["name"],
                "total_category_tvl":    round(total_tvl, 2),
                "hhi_concentration":     round(hhi, 2),
                "fastest_growing":       fastest_growing["name"],
                "fastest_declining":     fastest_declining["name"],
                "protocol_count":        len(protos),
            }

        return summary

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _append_log(entry: dict, log_path: str) -> None:
        """Atomic ring-buffer append (cap LOG_CAP)."""
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        dir_name = os.path.dirname(log_path)
        atomic_save(log, str(log_path))
# ------------------------------------------------------------------ #
# CLI                                                                  #
# ------------------------------------------------------------------ #

if __name__ == "__main__":

    sample_protocols = [
        {
            "name": "Uniswap V3",
            "category": "dex",
            "tvl_current_usd": 4_500_000_000,
            "tvl_30d_ago_usd": 4_000_000_000,
            "volume_30d_usd": 15_000_000_000,
            "volume_90d_ago_usd": 12_000_000_000,
            "fees_30d_usd": 45_000_000,
            "unique_users_30d": 250_000,
            "integrations_count": 120,
        },
        {
            "name": "Curve Finance",
            "category": "dex",
            "tvl_current_usd": 3_200_000_000,
            "tvl_30d_ago_usd": 3_500_000_000,
            "volume_30d_usd": 5_000_000_000,
            "volume_90d_ago_usd": 5_500_000_000,
            "fees_30d_usd": 12_000_000,
            "unique_users_30d": 80_000,
            "integrations_count": 95,
        },
    ]

    tracker = DeFiProtocolMarketShareTracker()
    result = tracker.track(sample_protocols, {"write_log": False})
    print(json.dumps(result, indent=2))
