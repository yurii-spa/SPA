"""
MP-910: Protocol Fee Structure Analyzer
Analyzes DeFi protocol fee structures: effective rates, competitiveness, revenue.
Pure stdlib, read-only advisory, atomic ring-buffer log (cap 100).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

# ── constants ────────────────────────────────────────────────────────────────
LOG_CAP = 100

LABEL_VERY_COMPETITIVE = "VERY_COMPETITIVE"
LABEL_COMPETITIVE = "COMPETITIVE"
LABEL_MARKET_RATE = "MARKET_RATE"
LABEL_EXPENSIVE = "EXPENSIVE"
LABEL_VERY_EXPENSIVE = "VERY_EXPENSIVE"

FLAG_FEE_SWITCH = "FEE_SWITCH_ON"
FLAG_HIGH_PROTOCOL_CUT = "HIGH_PROTOCOL_CUT"
FLAG_EXPENSIVE_VS_MARKET = "EXPENSIVE_VS_MARKET"
FLAG_NO_TIERS = "NO_TIERS"
FLAG_DECLINING_VOLUME = "DECLINING_VOLUME"

VALID_CATEGORIES = {"dex", "lending", "yield", "bridge", "perps"}

DEFAULT_CONFIG: dict[str, Any] = {
    # fee label thresholds relative to competitor_avg_fee_pct
    "very_competitive_ratio": 0.7,   # eff_rate <= 70% of competitor
    "competitive_ratio": 0.9,        # eff_rate <= 90%
    "market_rate_ratio": 1.1,        # eff_rate <= 110%
    "expensive_ratio": 2.0,          # eff_rate <= 200% → EXPENSIVE; else VERY_EXPENSIVE
    # flag thresholds
    "high_protocol_cut_pct": 20.0,   # protocol_fee_pct > 20%
    "expensive_vs_market_multiplier": 2.0,  # eff_rate > 2x competitor
    "declining_volume_pct": 10.0,    # placeholder for volume decline detection
    "log_enabled": True,
}


# ── main class ────────────────────────────────────────────────────────────────
class ProtocolFeeStructureAnalyzer:
    """Analyze fee structure competitiveness for DeFi protocols."""

    # ------------------------------------------------------------------
    def analyze(self, protocols: list[dict], config: dict | None = None) -> dict:
        """
        Parameters
        ----------
        protocols : list of dict, each containing:
            - name                   str
            - category               str  (dex/lending/yield/bridge/perps)
            - fee_tiers              list of {tier_name, fee_pct, volume_24h_usd}
            - protocol_fee_pct       float  (% of swap fee to protocol treasury)
            - fee_switch_active      bool
            - total_volume_30d_usd   float
            - competitor_avg_fee_pct float
        config : optional overrides for DEFAULT_CONFIG

        Returns
        -------
        dict with:
            protocols_detail, cheapest_protocol, most_expensive,
            total_ecosystem_revenue_30d_usd, average_effective_rate,
            fee_switch_count, timestamp_utc, config_used
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}

        if not protocols:
            result = self._empty_result(cfg)
            self._append_log(result, cfg)
            return result

        details: list[dict] = []
        for proto in protocols:
            details.append(self._analyze_protocol(proto, cfg))

        agg = self._aggregate(details, cfg)
        agg["protocols_detail"] = details
        agg["timestamp_utc"] = int(time.time())
        agg["config_used"] = cfg

        if cfg.get("log_enabled", True):
            self._append_log(agg, cfg)

        return agg

    # ------------------------------------------------------------------
    # protocol-level
    # ------------------------------------------------------------------

    def _analyze_protocol(self, proto: dict, cfg: dict) -> dict:
        name = proto.get("name", "unknown")
        category = proto.get("category", "unknown").lower()
        if category not in VALID_CATEGORIES:
            category = "unknown"

        fee_tiers: list[dict] = proto.get("fee_tiers", [])
        protocol_fee_pct = float(proto.get("protocol_fee_pct", 0.0))
        fee_switch_active = bool(proto.get("fee_switch_active", False))
        total_volume_30d = float(proto.get("total_volume_30d_usd", 0.0))
        competitor_avg = float(proto.get("competitor_avg_fee_pct", 0.3))

        # clamp
        protocol_fee_pct = max(0.0, min(100.0, protocol_fee_pct))
        competitor_avg = max(0.0001, competitor_avg)

        # effective fee rate (volume-weighted across tiers)
        effective_rate, tier_analysis = self._effective_rate(fee_tiers)

        # protocol revenue 30d
        protocol_revenue_30d = (
            total_volume_30d
            * (effective_rate / 100.0)
            * (protocol_fee_pct / 100.0)
        )

        # user cost score 0-100 (lower rate → lower score = better for user)
        user_cost_score = self._user_cost_score(effective_rate, competitor_avg)

        # competitive position
        competitive_position = self._competitive_position(effective_rate, competitor_avg)

        # label
        label = self._fee_label(effective_rate, competitor_avg, cfg)

        # flags
        flags = self._flags(
            fee_switch_active, protocol_fee_pct, effective_rate,
            competitor_avg, fee_tiers, cfg
        )

        return {
            "name": name,
            "category": category,
            "fee_tiers_count": len(fee_tiers),
            "effective_fee_rate_pct": round(effective_rate, 4),
            "protocol_fee_pct": protocol_fee_pct,
            "fee_switch_active": fee_switch_active,
            "total_volume_30d_usd": total_volume_30d,
            "competitor_avg_fee_pct": competitor_avg,
            "protocol_revenue_30d_usd": round(protocol_revenue_30d, 2),
            "user_cost_score": round(user_cost_score, 2),
            "competitive_position": competitive_position,
            "fee_label": label,
            "flags": flags,
            "tier_analysis": tier_analysis,
        }

    def _effective_rate(self, fee_tiers: list[dict]) -> tuple[float, list[dict]]:
        """Volume-weighted average fee rate across tiers."""
        if not fee_tiers:
            return 0.0, []

        total_vol = sum(
            float(t.get("volume_24h_usd", 0.0)) for t in fee_tiers
        )
        tier_analysis: list[dict] = []

        if total_vol <= 0:
            # equal weight
            rates = [float(t.get("fee_pct", 0.0)) for t in fee_tiers]
            avg = sum(rates) / len(rates) if rates else 0.0
            for t in fee_tiers:
                tier_analysis.append({
                    "tier_name": t.get("tier_name", ""),
                    "fee_pct": float(t.get("fee_pct", 0.0)),
                    "volume_24h_usd": float(t.get("volume_24h_usd", 0.0)),
                    "volume_share_pct": round(100.0 / len(fee_tiers), 2),
                })
            return avg, tier_analysis

        weighted_sum = 0.0
        for t in fee_tiers:
            vol = float(t.get("volume_24h_usd", 0.0))
            fee = float(t.get("fee_pct", 0.0))
            share = (vol / total_vol) * 100.0
            weighted_sum += fee * (vol / total_vol)
            tier_analysis.append({
                "tier_name": t.get("tier_name", ""),
                "fee_pct": fee,
                "volume_24h_usd": vol,
                "volume_share_pct": round(share, 2),
            })

        return weighted_sum, tier_analysis

    def _user_cost_score(self, eff_rate: float, competitor_avg: float) -> float:
        """
        0 = free, 100 = very expensive.
        Normalized so that competitor avg maps to 50.
        """
        if competitor_avg <= 0:
            return 50.0
        ratio = eff_rate / competitor_avg
        # ratio 0 → 0; ratio 1 → 50; ratio 2 → 100; clamp 0-100
        score = ratio * 50.0
        return min(100.0, max(0.0, score))

    def _competitive_position(self, eff_rate: float, competitor_avg: float) -> str:
        """Human-readable competitive position description."""
        if competitor_avg <= 0:
            return "no_benchmark"
        ratio = eff_rate / competitor_avg
        if ratio <= 0.7:
            return "significantly_cheaper"
        if ratio <= 0.9:
            return "cheaper"
        if ratio <= 1.1:
            return "at_market"
        if ratio <= 2.0:
            return "more_expensive"
        return "significantly_more_expensive"

    def _fee_label(self, eff_rate: float, competitor_avg: float, cfg: dict) -> str:
        if competitor_avg <= 0:
            return LABEL_MARKET_RATE
        ratio = eff_rate / competitor_avg
        if ratio <= cfg["very_competitive_ratio"]:
            return LABEL_VERY_COMPETITIVE
        if ratio <= cfg["competitive_ratio"]:
            return LABEL_COMPETITIVE
        if ratio <= cfg["market_rate_ratio"]:
            return LABEL_MARKET_RATE
        if ratio <= cfg["expensive_ratio"]:
            return LABEL_EXPENSIVE
        return LABEL_VERY_EXPENSIVE

    def _flags(
        self,
        fee_switch_active: bool,
        protocol_fee_pct: float,
        eff_rate: float,
        competitor_avg: float,
        fee_tiers: list[dict],
        cfg: dict,
    ) -> list[str]:
        flags: list[str] = []
        if fee_switch_active:
            flags.append(FLAG_FEE_SWITCH)
        if protocol_fee_pct > cfg["high_protocol_cut_pct"]:
            flags.append(FLAG_HIGH_PROTOCOL_CUT)
        if competitor_avg > 0 and eff_rate > cfg["expensive_vs_market_multiplier"] * competitor_avg:
            flags.append(FLAG_EXPENSIVE_VS_MARKET)
        if len(fee_tiers) <= 1:
            flags.append(FLAG_NO_TIERS)
        # DECLINING_VOLUME: placeholder — not enough data in single snapshot
        return flags

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, details: list[dict], cfg: dict) -> dict:
        if not details:
            return {
                "cheapest_protocol": None,
                "most_expensive": None,
                "total_ecosystem_revenue_30d_usd": 0.0,
                "average_effective_rate": None,
                "fee_switch_count": 0,
            }

        sorted_by_rate = sorted(
            details, key=lambda d: d["effective_fee_rate_pct"]
        )
        cheapest = sorted_by_rate[0]["name"] if sorted_by_rate else None
        most_expensive = sorted_by_rate[-1]["name"] if sorted_by_rate else None

        total_revenue = sum(d["protocol_revenue_30d_usd"] for d in details)

        rates = [d["effective_fee_rate_pct"] for d in details]
        avg_rate = sum(rates) / len(rates) if rates else None

        fee_switch_count = sum(1 for d in details if d["fee_switch_active"])

        return {
            "cheapest_protocol": cheapest,
            "most_expensive": most_expensive,
            "total_ecosystem_revenue_30d_usd": round(total_revenue, 2),
            "average_effective_rate": round(avg_rate, 4) if avg_rate is not None else None,
            "fee_switch_count": fee_switch_count,
        }

    # ------------------------------------------------------------------
    # ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, result: dict, cfg: dict) -> None:
        log_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data",
                         "fee_structure_log.json")
        )
        try:
            if os.path.exists(log_path):
                with open(log_path) as f:
                    buf: list = json.load(f)
            else:
                buf = []
            summary = {
                "ts": result.get("timestamp_utc"),
                "cheapest": result.get("cheapest_protocol"),
                "most_expensive": result.get("most_expensive"),
                "total_revenue_30d": result.get("total_ecosystem_revenue_30d_usd", 0),
                "avg_effective_rate": result.get("average_effective_rate"),
                "fee_switch_count": result.get("fee_switch_count", 0),
            }
            buf.append(summary)
            if len(buf) > LOG_CAP:
                buf = buf[-LOG_CAP:]
            tmp = log_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(buf, f, indent=2)
            os.replace(tmp, log_path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _empty_result(self, cfg: dict) -> dict:
        return {
            "protocols_detail": [],
            "cheapest_protocol": None,
            "most_expensive": None,
            "total_ecosystem_revenue_30d_usd": 0.0,
            "average_effective_rate": None,
            "fee_switch_count": 0,
            "timestamp_utc": int(time.time()),
            "config_used": cfg,
        }
