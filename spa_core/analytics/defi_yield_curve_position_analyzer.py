"""
MP-928 — DeFiYieldCurvePositionAnalyzer
Analyzes positions on the DeFi yield curve (fixed vs variable rate).
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_curve_position_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Label & flag constants
# --------------------------------------------------------------------------- #
LABEL_RATE_ADVANTAGE = "RATE_ADVANTAGE"
LABEL_NEUTRAL = "NEUTRAL"
LABEL_RATE_DISADVANTAGE = "RATE_DISADVANTAGE"
LABEL_EXPIRING_SOON = "EXPIRING_SOON"
LABEL_UNDERWATER = "UNDERWATER"

FLAG_HIGH_DURATION = "HIGH_DURATION"
FLAG_INVERTED_ADVANTAGE = "INVERTED_ADVANTAGE"
FLAG_NEAR_EXPIRY = "NEAR_EXPIRY"
FLAG_LARGE_DV01_EXPOSURE = "LARGE_DV01_EXPOSURE"
FLAG_BREAKEVEN_NEAR = "BREAKEVEN_NEAR"


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #
class DeFiYieldCurvePositionAnalyzer:
    """
    Analyzes DeFi yield-curve positions (fixed vs variable) for rate risk,
    duration risk, PnL sensitivity, and labels/flags each position.

    Usage::

        analyzer = DeFiYieldCurvePositionAnalyzer()
        result = analyzer.analyze(positions, config)
    """

    # Default config values used when key is absent from caller-supplied config
    _DEFAULTS: dict[str, Any] = {
        "large_dv01_usd_threshold": 500.0,   # flag LARGE_DV01_EXPOSURE above this
        "high_duration_days": 180,            # flag HIGH_DURATION above this
        "near_expiry_days": 14,               # flag NEAR_EXPIRY below this
        "breakeven_near_bps": 50,             # flag BREAKEVEN_NEAR within this
        "neutral_band_pct": 0.25,             # ±0.25% rate_advantage → NEUTRAL
    }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def analyze(
        self,
        positions: list[dict],
        config: dict | None = None,
    ) -> dict:
        """
        Analyze a list of DeFi yield-curve positions.

        Each position dict may contain:
            protocol                  (str)
            position_type             (str) fixed_lend|fixed_borrow|variable_lend|variable_borrow|lp
            notional_usd              (float)
            fixed_rate_pct            (float|None)
            current_variable_rate_pct (float)
            rate_duration_days        (int)
            breakeven_rate_pct        (float)
            rate_sensitivity          (float)  — DV01 per $1 notional per 1bps
            implied_vol_pct           (float)

        Returns a dict with per-position results and portfolio aggregates.
        """
        cfg = {**self._DEFAULTS, **(config or {})}

        analyzed: list[dict] = []
        for pos in positions:
            analyzed.append(self._analyze_one(pos, cfg))

        agg = self._aggregate(analyzed, cfg)

        result = {
            "positions": analyzed,
            "aggregates": agg,
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "position_count": len(analyzed),
        }
        self._append_log(result)
        return result

    # ------------------------------------------------------------------ #
    # Per-position analysis
    # ------------------------------------------------------------------ #
    def _analyze_one(self, pos: dict, cfg: dict) -> dict:
        protocol = str(pos.get("protocol", "unknown"))
        pos_type = str(pos.get("position_type", "variable_lend"))
        notional = float(pos.get("notional_usd", 0.0))
        fixed_rate = pos.get("fixed_rate_pct")
        variable_rate = float(pos.get("current_variable_rate_pct", 0.0))
        duration = int(pos.get("rate_duration_days", 0))
        breakeven = float(pos.get("breakeven_rate_pct", variable_rate))
        dv01_per_usd_per_bps = float(pos.get("rate_sensitivity", 0.0))
        implied_vol = float(pos.get("implied_vol_pct", 0.0))

        # Rate advantage: fixed vs current variable (lending perspective)
        rate_advantage_pct = self._compute_rate_advantage(
            pos_type, fixed_rate, variable_rate
        )

        # Duration risk score 0-100 (sigmoid on duration days)
        duration_risk_score = self._duration_risk_score(duration)

        # Rate risk score 0-100 based on DV01 * notional (absolute $-risk per bps)
        rate_risk_score = self._rate_risk_score(
            dv01_per_usd_per_bps, notional, cfg["large_dv01_usd_threshold"]
        )

        # Portfolio DV01 in USD ($ change per 1bps move in rates)
        position_dv01_usd = abs(dv01_per_usd_per_bps * notional)

        # PnL sensitivity — sign depends on position type
        pnl_sign = self._pnl_sign(pos_type)
        pnl_up_100bps = pnl_sign * position_dv01_usd * 100
        pnl_down_100bps = -pnl_sign * position_dv01_usd * 100

        # Label
        label = self._label(
            pos_type, rate_advantage_pct, duration, fixed_rate,
            variable_rate, breakeven, cfg
        )

        # Flags
        flags = self._flags(
            pos_type, fixed_rate, variable_rate, duration,
            position_dv01_usd, breakeven, rate_advantage_pct, cfg
        )

        return {
            "protocol": protocol,
            "position_type": pos_type,
            "notional_usd": notional,
            "fixed_rate_pct": fixed_rate,
            "current_variable_rate_pct": variable_rate,
            "rate_duration_days": duration,
            "breakeven_rate_pct": breakeven,
            "rate_sensitivity_dv01": dv01_per_usd_per_bps,
            "implied_vol_pct": implied_vol,
            "rate_advantage_pct": round(rate_advantage_pct, 4),
            "duration_risk_score": round(duration_risk_score, 2),
            "rate_risk_score": round(rate_risk_score, 2),
            "position_dv01_usd": round(position_dv01_usd, 4),
            "net_pnl_if_rates_up_100bps_usd": round(pnl_up_100bps, 2),
            "net_pnl_if_rates_down_100bps_usd": round(pnl_down_100bps, 2),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Aggregation
    # ------------------------------------------------------------------ #
    def _aggregate(self, positions: list[dict], cfg: dict) -> dict:
        if not positions:
            return {
                "total_notional_usd": 0.0,
                "portfolio_dv01_usd": 0.0,
                "rate_advantage_count": 0,
                "best_rate_position": None,
                "worst_rate_position": None,
                "average_duration_risk_score": 0.0,
                "average_rate_risk_score": 0.0,
                "label_counts": {},
                "flag_counts": {},
            }

        total_notional = sum(p["notional_usd"] for p in positions)
        portfolio_dv01 = sum(p["position_dv01_usd"] for p in positions)
        rate_adv_count = sum(
            1 for p in positions if p["label"] == LABEL_RATE_ADVANTAGE
        )

        # Best/worst by rate_advantage_pct
        sorted_by_adv = sorted(positions, key=lambda p: p["rate_advantage_pct"])
        worst = sorted_by_adv[0]["protocol"] if sorted_by_adv else None
        best = sorted_by_adv[-1]["protocol"] if sorted_by_adv else None

        avg_dur_risk = (
            sum(p["duration_risk_score"] for p in positions) / len(positions)
        )
        avg_rate_risk = (
            sum(p["rate_risk_score"] for p in positions) / len(positions)
        )

        label_counts: dict[str, int] = {}
        for p in positions:
            label_counts[p["label"]] = label_counts.get(p["label"], 0) + 1

        flag_counts: dict[str, int] = {}
        for p in positions:
            for f in p["flags"]:
                flag_counts[f] = flag_counts.get(f, 0) + 1

        return {
            "total_notional_usd": round(total_notional, 2),
            "portfolio_dv01_usd": round(portfolio_dv01, 4),
            "rate_advantage_count": rate_adv_count,
            "best_rate_position": best,
            "worst_rate_position": worst,
            "average_duration_risk_score": round(avg_dur_risk, 2),
            "average_rate_risk_score": round(avg_rate_risk, 2),
            "label_counts": label_counts,
            "flag_counts": flag_counts,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compute_rate_advantage(
        pos_type: str,
        fixed_rate: float | None,
        variable_rate: float,
    ) -> float:
        """
        Rate advantage from holder's perspective:
        - fixed_lend: positive when fixed > variable (locked in higher rate)
        - fixed_borrow: positive when fixed < variable (locked in cheaper funding)
        - variable_lend / variable_borrow / lp: 0 (no fixed rate to compare)
        """
        if fixed_rate is None:
            return 0.0
        if pos_type == "fixed_lend":
            return fixed_rate - variable_rate
        if pos_type == "fixed_borrow":
            return variable_rate - fixed_rate
        return 0.0

    @staticmethod
    def _duration_risk_score(duration_days: int) -> float:
        """Sigmoid: 0 days → ~0, 180 days → ~50, 365 days → ~85, 730+ → ~99."""
        if duration_days <= 0:
            return 0.0
        x = duration_days / 365.0
        score = 100.0 / (1.0 + math.exp(-4.0 * (x - 0.5)))
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _rate_risk_score(
        dv01_per_usd_per_bps: float,
        notional: float,
        large_dv01_threshold: float,
    ) -> float:
        """0-100 proportional to position DV01 in USD, capped at 2× threshold."""
        position_dv01 = abs(dv01_per_usd_per_bps * notional)
        if large_dv01_threshold <= 0:
            return 0.0
        ratio = position_dv01 / (2.0 * large_dv01_threshold)
        return min(ratio * 100.0, 100.0)

    @staticmethod
    def _pnl_sign(pos_type: str) -> float:
        """
        Sign of rate sensitivity from a P&L perspective:
        - Lenders profit when rates fall (duration/bond analogy) → negative
        - Borrowers profit when rates rise (cheaper relative funding) → positive
        - LP: typically mixed; treat as neutral
        """
        if pos_type in ("fixed_lend", "variable_lend"):
            return -1.0
        if pos_type in ("fixed_borrow", "variable_borrow"):
            return 1.0
        return 0.0

    def _label(
        self,
        pos_type: str,
        rate_advantage: float,
        duration: int,
        fixed_rate: float | None,
        variable_rate: float,
        breakeven: float,
        cfg: dict,
    ) -> str:
        # EXPIRING_SOON overrides everything when near expiry
        if 0 < duration <= cfg["near_expiry_days"]:
            return LABEL_EXPIRING_SOON

        # UNDERWATER: variable position with negative yield or fixed below breakeven
        if pos_type in ("fixed_lend", "fixed_borrow") and fixed_rate is not None:
            if pos_type == "fixed_lend" and fixed_rate < breakeven:
                return LABEL_UNDERWATER
            if pos_type == "fixed_borrow" and variable_rate < breakeven:
                return LABEL_UNDERWATER

        neutral_band = cfg["neutral_band_pct"]
        if abs(rate_advantage) <= neutral_band:
            return LABEL_NEUTRAL
        if rate_advantage > neutral_band:
            return LABEL_RATE_ADVANTAGE
        return LABEL_RATE_DISADVANTAGE

    def _flags(
        self,
        pos_type: str,
        fixed_rate: float | None,
        variable_rate: float,
        duration: int,
        position_dv01_usd: float,
        breakeven: float,
        rate_advantage: float,
        cfg: dict,
    ) -> list[str]:
        flags: list[str] = []
        if duration > cfg["high_duration_days"]:
            flags.append(FLAG_HIGH_DURATION)
        if (
            pos_type == "fixed_lend"
            and fixed_rate is not None
            and fixed_rate > variable_rate
        ):
            flags.append(FLAG_INVERTED_ADVANTAGE)
        if 0 < duration <= cfg["near_expiry_days"]:
            flags.append(FLAG_NEAR_EXPIRY)
        if position_dv01_usd >= cfg["large_dv01_usd_threshold"]:
            flags.append(FLAG_LARGE_DV01_EXPOSURE)
        # BREAKEVEN_NEAR: current variable within breakeven_near_bps of breakeven
        bps_to_breakeven = abs(variable_rate - breakeven) * 100
        if bps_to_breakeven <= cfg["breakeven_near_bps"]:
            flags.append(FLAG_BREAKEVEN_NEAR)
        return flags

    # ------------------------------------------------------------------ #
    # Ring-buffer log (cap 100, atomic write)
    # ------------------------------------------------------------------ #
    def _append_log(self, result: dict) -> None:
        log_path = os.path.abspath(_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                entries: list = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            entries = []

        entry = {
            "ts": result["analyzed_at"],
            "position_count": result["position_count"],
            "aggregates": result["aggregates"],
        }
        entries.append(entry)
        if len(entries) > _LOG_CAP:
            entries = entries[-_LOG_CAP:]

        atomic_save(entries, str(log_path))
