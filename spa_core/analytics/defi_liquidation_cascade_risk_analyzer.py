"""
MP-909: DeFi Liquidation Cascade Risk Analyzer
Analyzes cascade liquidation risk across DeFi positions.
Pure stdlib, read-only advisory, atomic ring-buffer log (cap 100).
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any

# ── constants ────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                        "liquidation_cascade_log.json")
LOG_CAP = 100

LABEL_SAFE = "SAFE"
LABEL_WATCH = "WATCH"
LABEL_AT_RISK = "AT_RISK"
LABEL_DANGER = "DANGER"
LABEL_CRITICAL = "CRITICAL"

FLAG_BELOW_130 = "BELOW_130"
FLAG_CORRELATED = "CORRELATED_COLLATERAL"
FLAG_HIGH_VOL = "HIGH_VOLATILITY"
FLAG_LARGE_POS = "LARGE_POSITION"

DEFAULT_CONFIG: dict[str, Any] = {
    "health_watch": 1.5,
    "health_at_risk": 1.3,
    "health_danger": 1.1,
    "health_critical": 1.0,
    "correlation_threshold": 0.8,
    "volatility_threshold": 50.0,
    "large_position_debt_usd": 100_000.0,
    "cascade_vol_weight": 0.4,
    "cascade_corr_weight": 0.3,
    "cascade_proximity_weight": 0.3,
    "log_enabled": True,
}


# ── main class ────────────────────────────────────────────────────────────────
class DeFiLiquidationCascadeRiskAnalyzer:
    """Analyze cascade liquidation risk for a list of DeFi positions."""

    # ------------------------------------------------------------------
    def analyze(self, positions: list[dict], config: dict | None = None) -> dict:
        """
        Parameters
        ----------
        positions : list of dict, each containing:
            - protocol                  str
            - collateral_token          str
            - debt_token                str
            - collateral_usd            float  (current collateral value)
            - debt_usd                  float  (current debt value)
            - liquidation_threshold_pct float  (e.g. 80 means 80%)
            - current_price_usd         float  (collateral token price)
            - price_30d_volatility_pct  float  (30-day price volatility %)
            - collateral_correlation_to_debt float (0-1)
        config : optional overrides for DEFAULT_CONFIG keys

        Returns
        -------
        dict with keys:
            positions_detail, most_at_risk, safest_position,
            total_debt_at_risk_usd, average_health_factor,
            critical_count, timestamp_utc, config_used
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}

        if not positions:
            result = self._empty_result(cfg)
            self._append_log(result, cfg)
            return result

        details: list[dict] = []
        for pos in positions:
            details.append(self._analyze_position(pos, cfg))

        agg = self._aggregate(details, cfg)
        agg["positions_detail"] = details
        agg["timestamp_utc"] = int(time.time())
        agg["config_used"] = cfg

        if cfg.get("log_enabled", True):
            self._append_log(agg, cfg)

        return agg

    # ------------------------------------------------------------------
    # position-level helpers
    # ------------------------------------------------------------------

    def _analyze_position(self, pos: dict, cfg: dict) -> dict:
        protocol = pos.get("protocol", "unknown")
        coll_token = pos.get("collateral_token", "unknown")
        debt_token = pos.get("debt_token", "unknown")
        collateral_usd = float(pos.get("collateral_usd", 0.0))
        debt_usd = float(pos.get("debt_usd", 0.0))
        liq_threshold_pct = float(pos.get("liquidation_threshold_pct", 80.0))
        current_price_usd = float(pos.get("current_price_usd", 0.0))
        volatility = float(pos.get("price_30d_volatility_pct", 0.0))
        correlation = float(pos.get("collateral_correlation_to_debt", 0.0))

        # clamp inputs
        liq_threshold_pct = max(0.0, min(100.0, liq_threshold_pct))
        correlation = max(0.0, min(1.0, correlation))

        # health factor: (collateral * threshold%) / debt
        liq_threshold = liq_threshold_pct / 100.0
        if debt_usd <= 0:
            health_factor = float("inf")
            distance_pct = 100.0
            liq_price_usd = 0.0
        else:
            health_factor = (collateral_usd * liq_threshold) / debt_usd
            # distance_to_liquidation: how much the collateral price can drop before LT
            # liq_price = debt / (collateral_amount * liq_threshold)
            # collateral_amount = collateral_usd / current_price_usd
            if current_price_usd > 0:
                collateral_amount = collateral_usd / current_price_usd
                if collateral_amount > 0:
                    liq_price_usd = debt_usd / (collateral_amount * liq_threshold)
                    if liq_price_usd >= current_price_usd:
                        distance_pct = 0.0
                    else:
                        distance_pct = (
                            (current_price_usd - liq_price_usd)
                            / current_price_usd
                        ) * 100.0
                else:
                    liq_price_usd = 0.0
                    distance_pct = 0.0
            else:
                liq_price_usd = 0.0
                distance_pct = 0.0

        # cascade risk score (0-100)
        cascade_score = self._cascade_score(
            health_factor, volatility, correlation, distance_pct, cfg
        )

        # label
        label = self._label(health_factor, cfg)

        # flags
        flags = self._flags(
            health_factor, correlation, volatility, debt_usd, cfg
        )

        return {
            "protocol": protocol,
            "collateral_token": coll_token,
            "debt_token": debt_token,
            "collateral_usd": collateral_usd,
            "debt_usd": debt_usd,
            "liquidation_threshold_pct": liq_threshold_pct,
            "health_factor": round(health_factor, 4)
            if not math.isinf(health_factor)
            else None,
            "distance_to_liquidation_pct": round(distance_pct, 2),
            "liquidation_price_usd": round(liq_price_usd, 4),
            "cascade_risk_score": round(cascade_score, 2),
            "risk_label": label,
            "flags": flags,
            "price_30d_volatility_pct": volatility,
            "collateral_correlation_to_debt": correlation,
        }

    def _cascade_score(
        self,
        health_factor: float,
        volatility: float,
        correlation: float,
        distance_pct: float,
        cfg: dict,
    ) -> float:
        """Compute cascade risk score 0-100."""
        if math.isinf(health_factor):
            return 0.0

        vol_weight = cfg["cascade_vol_weight"]
        corr_weight = cfg["cascade_corr_weight"]
        prox_weight = cfg["cascade_proximity_weight"]

        # volatility component: 50% vol → 50 points; scaled 0-100
        vol_score = min(100.0, (volatility / 100.0) * 100.0)

        # correlation component: direct 0-100
        corr_score = correlation * 100.0

        # proximity component: closer to liq → higher score
        # distance_pct 0 → score 100; distance_pct 100 → score 0
        prox_score = max(0.0, 100.0 - distance_pct)

        score = (
            vol_score * vol_weight
            + corr_score * corr_weight
            + prox_score * prox_weight
        )
        return min(100.0, max(0.0, score))

    def _label(self, health_factor: float, cfg: dict) -> str:
        if math.isinf(health_factor):
            return LABEL_SAFE
        if health_factor >= cfg["health_watch"]:
            return LABEL_SAFE
        if health_factor >= cfg["health_at_risk"]:
            return LABEL_WATCH
        if health_factor > cfg["health_danger"]:
            return LABEL_AT_RISK
        if health_factor > cfg["health_critical"]:
            return LABEL_DANGER
        return LABEL_CRITICAL

    def _flags(
        self,
        health_factor: float,
        correlation: float,
        volatility: float,
        debt_usd: float,
        cfg: dict,
    ) -> list[str]:
        flags: list[str] = []
        if not math.isinf(health_factor) and health_factor < 1.3:
            flags.append(FLAG_BELOW_130)
        if correlation > cfg["correlation_threshold"]:
            flags.append(FLAG_CORRELATED)
        if volatility > cfg["volatility_threshold"]:
            flags.append(FLAG_HIGH_VOL)
        if debt_usd > cfg["large_position_debt_usd"]:
            flags.append(FLAG_LARGE_POS)
        return flags

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, details: list[dict], cfg: dict) -> dict:
        if not details:
            return {
                "most_at_risk": None,
                "safest_position": None,
                "total_debt_at_risk_usd": 0.0,
                "average_health_factor": None,
                "critical_count": 0,
            }

        # sort by cascade score desc
        sorted_by_risk = sorted(
            details, key=lambda d: d["cascade_risk_score"], reverse=True
        )
        most_at_risk = sorted_by_risk[0]["protocol"] if sorted_by_risk else None

        # safest = lowest cascade score
        safest = sorted(details, key=lambda d: d["cascade_risk_score"])[0]
        safest_position = safest["protocol"]

        # total_debt_at_risk: positions with DANGER or CRITICAL label
        at_risk_labels = {LABEL_DANGER, LABEL_CRITICAL}
        total_debt_at_risk = sum(
            (d["debt_usd"] for d in details if d["risk_label"] in at_risk_labels),
            0.0,
        )

        # average health factor (exclude None / inf)
        valid_hf = [
            d["health_factor"]
            for d in details
            if d["health_factor"] is not None
        ]
        avg_hf = sum(valid_hf) / len(valid_hf) if valid_hf else None

        critical_count = sum(
            1 for d in details if d["risk_label"] == LABEL_CRITICAL
        )

        return {
            "most_at_risk": most_at_risk,
            "safest_position": safest_position,
            "total_debt_at_risk_usd": round(total_debt_at_risk, 2),
            "average_health_factor": round(avg_hf, 4) if avg_hf is not None else None,
            "critical_count": critical_count,
        }

    # ------------------------------------------------------------------
    # ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, result: dict, cfg: dict) -> None:
        log_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data",
                         "liquidation_cascade_log.json")
        )
        try:
            if os.path.exists(log_path):
                with open(log_path) as f:
                    buf: list = json.load(f)
            else:
                buf = []
            summary = {
                "ts": result.get("timestamp_utc"),
                "critical_count": result.get("critical_count", 0),
                "total_debt_at_risk_usd": result.get("total_debt_at_risk_usd", 0),
                "avg_health_factor": result.get("average_health_factor"),
                "most_at_risk": result.get("most_at_risk"),
            }
            buf.append(summary)
            if len(buf) > LOG_CAP:
                buf = buf[-LOG_CAP:]
            tmp = log_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(buf, f, indent=2)
            os.replace(tmp, log_path)
        except Exception:
            pass  # advisory only — never raise

    # ------------------------------------------------------------------
    def _empty_result(self, cfg: dict) -> dict:
        return {
            "positions_detail": [],
            "most_at_risk": None,
            "safest_position": None,
            "total_debt_at_risk_usd": 0.0,
            "average_health_factor": None,
            "critical_count": 0,
            "timestamp_utc": int(time.time()),
            "config_used": cfg,
        }
