"""
MP-997: ProtocolDeFiPointsSystemValuationAnalyzer
Analyzes DeFi protocol points systems and estimates probable point value.
Stdlib only. Atomic ring-buffer log (cap 100) → data/points_valuation_log.json.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save


_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "points_valuation_log.json"
)


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


class ProtocolDeFiPointsSystemValuationAnalyzer:
    """
    Analyzes DeFi protocol points programs and estimates point values.

    Program dict fields:
        name (str)
        protocol (str)
        total_points_issued (float)
        points_per_dollar_per_day (float)
        total_tvl_usd (float)
        fdv_hint_usd (float|None)
        expected_airdrop_pct_of_fdv (float)   # 0.0–1.0
        points_to_fdv_conversion_announced (bool)
        snapshot_date_days_until (int|None)
        has_transferable_points (bool)
        points_market_price_usd (float|None)
        competing_programs_count (int)
        user_count (int)
    """

    def __init__(self, log_path: str | None = None):
        self._log_path = log_path or _DEFAULT_LOG_PATH

    # ------------------------------------------------------------------
    # Core computation helpers
    # ------------------------------------------------------------------

    def _implied_point_value(self, prog: dict) -> float:
        """
        If market price exists → use it.
        Otherwise: fdv_hint × airdrop_pct / total_points_issued
        Returns 0.0 if insufficient data.
        """
        market_price = prog.get("points_market_price_usd")
        if market_price is not None:
            return float(market_price)

        fdv = prog.get("fdv_hint_usd")
        airdrop_pct = float(prog.get("expected_airdrop_pct_of_fdv", 0))
        total_pts = float(prog.get("total_points_issued", 0))
        if fdv is not None and total_pts > 0 and airdrop_pct > 0:
            return float(fdv) * airdrop_pct / total_pts
        return 0.0

    def _apy_from_points(self, prog: dict, implied_value: float) -> float:
        """
        apy_from_points_pct = implied_value × points_per_dollar_per_day × 365 × 100
        """
        ppd = float(prog.get("points_per_dollar_per_day", 0))
        return round(implied_value * ppd * 365 * 100, 4)

    def _dilution_risk_score(self, prog: dict) -> float:
        """
        dilution_risk_score (0-100):
        competing_programs_count contribution + total_points vs TVL ratio contribution.
        """
        competing = int(prog.get("competing_programs_count", 0))
        total_pts = float(prog.get("total_points_issued", 0))
        tvl = float(prog.get("total_tvl_usd", 1))
        if tvl <= 0:
            tvl = 1.0

        # More competing programs → higher dilution risk (capped at 10 → 100)
        competing_score = min(100.0, competing * 10.0)

        # Points density: pts per TVL dollar (log scale, high = diluted)
        if total_pts > 0 and tvl > 0:
            pts_per_tvl = total_pts / tvl
            # 1 pt/$ → 50, 100 pts/$ → ~100, 0.01 pts/$ → ~0
            density_score = min(100.0, max(0.0, (math.log10(max(pts_per_tvl, 1e-6)) + 2) / 4 * 100))
        else:
            density_score = 0.0

        return round(min(100.0, (competing_score * 0.55 + density_score * 0.45)), 2)

    def _uncertainty_discount(self, prog: dict) -> float:
        """
        0.0–1.0 discount factor:
        conversion_announced → 0.90
        fdv_hint exists (no conversion) → 0.50
        pure_speculation → 0.20
        market_price → 0.95 (most certain)
        """
        market_price = prog.get("points_market_price_usd")
        announced = bool(prog.get("points_to_fdv_conversion_announced", False))
        fdv_hint = prog.get("fdv_hint_usd")

        if market_price is not None:
            return 0.95
        if announced:
            return 0.90
        if fdv_hint is not None:
            return 0.50
        return 0.20

    # ------------------------------------------------------------------
    # Label & flags
    # ------------------------------------------------------------------

    def _label(self, prog: dict, apy: float, implied_value: float,
               dilution_score: float) -> str:
        market_price = prog.get("points_market_price_usd")
        announced = bool(prog.get("points_to_fdv_conversion_announced", False))
        fdv_hint = prog.get("fdv_hint_usd")
        competing = int(prog.get("competing_programs_count", 0))

        if market_price is not None and float(market_price) > 0.01 and announced:
            return "HIGH_VALUE_CONFIRMED"
        if dilution_score > 50 and competing > 5:
            return "DILUTION_RISK"
        if apy > 20.0 and fdv_hint is not None:
            return "LIKELY_VALUABLE"
        if apy > 5.0:
            return "SPECULATIVE_VALUE"
        return "LOW_VALUE"

    def _flags(self, prog: dict, dilution_score: float) -> list[str]:
        flags: list[str] = []
        if prog.get("points_market_price_usd") is not None:
            flags.append("POINTS_MARKET_EXISTS")
        days_until = prog.get("snapshot_date_days_until")
        if days_until is not None and int(days_until) < 30:
            flags.append("SNAPSHOT_IMMINENT")
        if prog.get("points_to_fdv_conversion_announced"):
            flags.append("CONVERSION_ANNOUNCED")
        if prog.get("has_transferable_points"):
            flags.append("TRANSFERABLE_POINTS")
        if int(prog.get("competing_programs_count", 0)) > 5:
            flags.append("HIGH_DILUTION_RISK")
        if prog.get("fdv_hint_usd") is None and prog.get("points_market_price_usd") is None:
            flags.append("NO_FDV_SIGNAL")
        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, points_programs: list[dict], config: dict) -> dict:
        """
        Main entry point.

        Returns:
            {
                "results": [...],
                "aggregates": {...},
                "timestamp": float,
            }
        """
        results = []
        for prog in points_programs:
            name = prog.get("name", "unknown")
            implied_value = self._implied_point_value(prog)
            apy = self._apy_from_points(prog, implied_value)
            dilution_score = self._dilution_risk_score(prog)
            discount = self._uncertainty_discount(prog)
            risk_adj_value = round(implied_value * discount, 8)
            label = self._label(prog, apy, implied_value, dilution_score)
            flags = self._flags(prog, dilution_score)

            results.append({
                "program": name,
                "protocol": prog.get("protocol", "unknown"),
                "implied_point_value_usd": round(implied_value, 8),
                "apy_from_points_pct": apy,
                "dilution_risk_score": dilution_score,
                "uncertainty_discount_factor": discount,
                "risk_adjusted_implied_value_usd": risk_adj_value,
                "label": label,
                "flags": flags,
            })

        # Aggregates
        if results:
            highest = max(results, key=lambda r: r["risk_adjusted_implied_value_usd"])
            lowest = min(results, key=lambda r: r["risk_adjusted_implied_value_usd"])
            avg_risk_adj = round(
                sum(r["risk_adjusted_implied_value_usd"] for r in results) / len(results), 8
            )
            confirmed_count = sum(
                1 for r in results if r["label"] == "HIGH_VALUE_CONFIRMED"
            )
            dilution_risk_count = sum(
                1 for r in results if r["label"] == "DILUTION_RISK"
            )
        else:
            highest = {"program": None}
            lowest = {"program": None}
            avg_risk_adj = 0.0
            confirmed_count = 0
            dilution_risk_count = 0

        output = {
            "results": results,
            "aggregates": {
                "highest_value_program": highest["program"],
                "lowest_value_program": lowest["program"],
                "avg_risk_adjusted_value": avg_risk_adj,
                "confirmed_count": confirmed_count,
                "dilution_risk_count": dilution_risk_count,
                "total_programs": len(results),
            },
            "timestamp": time.time(),
            "config": config,
        }

        write_log = config.get("write_log", True)
        if write_log:
            self._append_log(output)

        return output

    def _append_log(self, entry: dict) -> None:
        log_path = self._log_path
        log = _load_log(log_path)
        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(log_path, log)
