"""
MP-1046 DeFiProtocolTokenVestingOverhangAnalyzer
-------------------------------------------------
Analyzes sell pressure from upcoming token vesting cliffs and scheduled
unlocks.  Produces an overhang ratio, days-of-volume pressure, a worst-cliff
score (0–100), dilution percentage, and an advisory label.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "token_vesting_overhang_log.json"
)
_LOG_CAP = 100

# Recipient type → expected sell-pressure weight (1.0 = highest pressure).
_RECIPIENT_WEIGHTS: dict[str, float] = {
    "team": 1.0,
    "investor": 0.9,
    "ecosystem": 0.5,
    "community": 0.3,
}
_DEFAULT_RECIPIENT_WEIGHT = 0.5

# Urgency thresholds (days from now → urgency multiplier).
_URGENCY_TIERS = [
    (30, 1.0),
    (60, 0.8),
    (90, 0.6),
    (180, 0.4),
    (365, 0.2),
]
_URGENCY_BEYOND = 0.05  # for unlocks > 365 days out

# size_score: 20 % of circulating supply → 100 (cliff_size_divisor = 0.20)
_CLIFF_SIZE_DIVISOR = 0.20

# pressure_score: 60 days of avg daily volume to absorb → 100
_CLIFF_PRESSURE_DAYS = 60.0

# Label thresholds on worst_cliff_score
_LABEL_THRESHOLDS = [
    (20.0, "MINIMAL_OVERHANG"),
    (40.0, "MANAGEABLE"),
    (60.0, "SIGNIFICANT_CLIFF"),
    (80.0, "HEAVY_OVERHANG"),
]
_LABEL_TOP = "SUPPLY_SHOCK"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
def _urgency_factor(unlock_date_days: float) -> float:
    """Return urgency multiplier (1.0 = imminent, lower = further away)."""
    days = max(0.0, unlock_date_days)
    for threshold, factor in _URGENCY_TIERS:
        if days <= threshold:
            return factor
    return _URGENCY_BEYOND


def _recipient_weight(recipient_type: str) -> float:
    """Return sell-pressure weight for the given recipient type."""
    return _RECIPIENT_WEIGHTS.get(str(recipient_type).lower().strip(), _DEFAULT_RECIPIENT_WEIGHT)


def _cliff_score_for_unlock(
    amount: float,
    circulating_supply: float,
    current_price_usd: float,
    avg_daily_volume_usd: float,
    unlock_date_days: float,
    recipient_type: str,
) -> float:
    """
    Return cliff score (0–100) for a single unlock event.

    Two sub-components weighted 50/50:
    - size_score: how large the unlock is relative to circulating supply
    - pressure_score: how many days of avg volume it represents

    Both are multiplied by recipient sell-pressure weight and urgency factor.
    """
    if circulating_supply <= 0 or current_price_usd < 0 or avg_daily_volume_usd <= 0:
        return 0.0

    amt = max(0.0, amount)

    # size_score: fraction of circulating supply, normalised so that
    # _CLIFF_SIZE_DIVISOR (20 %) → 100.
    size_ratio = amt / circulating_supply
    size_score = min(100.0, size_ratio / _CLIFF_SIZE_DIVISOR * 100.0)

    # pressure_score: days of avg daily volume required to absorb the unlock.
    unlock_usd = amt * current_price_usd
    days_of_volume = unlock_usd / avg_daily_volume_usd if avg_daily_volume_usd > 0 else 0.0
    pressure_score = min(100.0, days_of_volume / _CLIFF_PRESSURE_DAYS * 100.0)

    combined = (size_score + pressure_score) / 2.0
    rw = _recipient_weight(recipient_type)
    urgency = _urgency_factor(unlock_date_days)

    return min(100.0, combined * rw * urgency)


def _overhang_ratio(upcoming_unlocks: list[dict], circulating_supply: float) -> float:
    """Total upcoming unlock amount / circulating supply."""
    if circulating_supply <= 0:
        return 0.0
    total = sum(max(0.0, float(u.get("amount", 0.0))) for u in upcoming_unlocks)
    return total / circulating_supply


def _days_supply_pressure(
    upcoming_unlocks: list[dict],
    current_price_usd: float,
    avg_daily_volume_usd: float,
) -> float:
    """
    How many days of avg daily trading volume would be needed to absorb
    the total upcoming unlock sell-pressure.
    """
    if avg_daily_volume_usd <= 0 or current_price_usd < 0:
        return 0.0
    total_usd = sum(
        max(0.0, float(u.get("amount", 0.0))) * current_price_usd
        for u in upcoming_unlocks
    )
    return total_usd / avg_daily_volume_usd


def _dilution_pct(upcoming_unlocks: list[dict], total_supply: float) -> float:
    """Upcoming unlock amount as % of total supply."""
    if total_supply <= 0:
        return 0.0
    total = sum(max(0.0, float(u.get("amount", 0.0))) for u in upcoming_unlocks)
    return total / total_supply * 100.0


def _worst_cliff_score(
    upcoming_unlocks: list[dict],
    circulating_supply: float,
    current_price_usd: float,
    avg_daily_volume_usd: float,
) -> float:
    """Return the worst (highest) cliff score across all unlock events."""
    if not upcoming_unlocks:
        return 0.0
    best = 0.0
    for u in upcoming_unlocks:
        score = _cliff_score_for_unlock(
            amount=float(u.get("amount", 0.0)),
            circulating_supply=circulating_supply,
            current_price_usd=current_price_usd,
            avg_daily_volume_usd=avg_daily_volume_usd,
            unlock_date_days=float(u.get("unlock_date_days", 365.0)),
            recipient_type=str(u.get("recipient_type", "ecosystem")),
        )
        if score > best:
            best = score
    return best


def _label(worst_score: float) -> str:
    """Map worst_cliff_score → advisory label."""
    for threshold, lbl in _LABEL_THRESHOLDS:
        if worst_score < threshold:
            return lbl
    return _LABEL_TOP


def _build_recommendations(
    label: str,
    overhang_ratio: float,
    days_pressure: float,
    dilution_pct_val: float,
    upcoming_unlocks: list[dict],
) -> list[str]:
    """Return advisory recommendations based on the analysis result."""
    recs: list[str] = []

    if label == "MINIMAL_OVERHANG":
        recs.append(
            f"Token unlock schedule presents minimal sell pressure "
            f"({overhang_ratio * 100:.1f}% of circulating supply). "
            f"No immediate concern."
        )
    elif label == "MANAGEABLE":
        recs.append(
            f"Upcoming unlocks ({overhang_ratio * 100:.1f}% of circ. supply) are "
            f"manageable.  Monitor price action around cliff dates."
        )
    elif label == "SIGNIFICANT_CLIFF":
        recs.append(
            f"Significant vesting cliff detected.  Unlocks represent "
            f"~{days_pressure:.0f} days of avg. trading volume.  "
            f"Consider reducing exposure near unlock dates."
        )
    elif label == "HEAVY_OVERHANG":
        recs.append(
            f"Heavy token overhang: {overhang_ratio * 100:.1f}% of circ. supply "
            f"unlocking.  High probability of sell pressure; risk of price "
            f"drawdown around cliff dates."
        )
    else:  # SUPPLY_SHOCK
        recs.append(
            f"SUPPLY SHOCK risk: unlocks represent ~{days_pressure:.0f} days of "
            f"volume ({dilution_pct_val:.1f}% dilution).  "
            f"Strong advisory to exit or hedge before unlock."
        )

    # Team/investor unlocks warrant extra caution
    high_pressure_types = {"team", "investor"}
    risky_types = [
        u for u in upcoming_unlocks
        if str(u.get("recipient_type", "")).lower() in high_pressure_types
    ]
    if risky_types and label not in {"MINIMAL_OVERHANG", "MANAGEABLE"}:
        recs.append(
            f"{len(risky_types)} team/investor unlock(s) detected — "
            f"these carry the highest sell-pressure risk."
        )

    if dilution_pct_val > 10.0:
        recs.append(
            f"Dilution of {dilution_pct_val:.1f}% relative to total supply "
            f"is material — factor into long-term valuation."
        )

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DeFiProtocolTokenVestingOverhangAnalyzer:
    """
    Analyzes sell pressure from upcoming token vesting cliffs.

    Usage
    -----
    analyzer = DeFiProtocolTokenVestingOverhangAnalyzer()
    result = analyzer.analyze(token_data)
    """

    def __init__(self, log_path: str = _LOG_PATH, log_cap: int = _LOG_CAP) -> None:
        self._log_path = log_path
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(self, token_data: dict, config: dict | None = None) -> dict[str, Any]:
        """
        Analyze token vesting overhang for sell-pressure risk.

        Parameters
        ----------
        token_data : dict
            - token_symbol: str
            - total_supply: float            (total token supply)
            - circulating_supply: float      (currently circulating supply)
            - upcoming_unlocks: list[dict]   each with:
                  unlock_date_days: float    (days from now until unlock)
                  amount: float              (tokens to be unlocked)
                  recipient_type: str        (team/investor/ecosystem/community)
            - current_price_usd: float
            - avg_daily_volume_usd: float    (avg daily trading volume in USD)
        config : dict, optional
            - log_path: str  (override default log path)
            - skip_log: bool (default False)

        Returns
        -------
        dict
            Full vesting overhang analysis with metrics and advisory label.
        """
        cfg = config or {}
        log_path = cfg.get("log_path", self._log_path)
        skip_log = bool(cfg.get("skip_log", False))

        token_symbol = str(token_data.get("token_symbol", "UNKNOWN"))
        total_supply = max(0.0, float(token_data.get("total_supply", 0.0)))
        circulating_supply = max(0.0, float(token_data.get("circulating_supply", 0.0)))
        upcoming_unlocks = list(token_data.get("upcoming_unlocks", []))
        current_price_usd = max(0.0, float(token_data.get("current_price_usd", 0.0)))
        avg_daily_volume_usd = max(0.0, float(token_data.get("avg_daily_volume_usd", 0.0)))

        # Core metrics
        oh_ratio = _overhang_ratio(upcoming_unlocks, circulating_supply)
        days_pressure = _days_supply_pressure(
            upcoming_unlocks, current_price_usd, avg_daily_volume_usd
        )
        dil_pct = _dilution_pct(upcoming_unlocks, total_supply)
        worst_score = _worst_cliff_score(
            upcoming_unlocks, circulating_supply, current_price_usd, avg_daily_volume_usd
        )
        lbl = _label(worst_score)
        recommendations = _build_recommendations(
            lbl, oh_ratio, days_pressure, dil_pct, upcoming_unlocks
        )

        result: dict[str, Any] = {
            "token_symbol": token_symbol,
            "total_supply": total_supply,
            "circulating_supply": circulating_supply,
            "current_price_usd": current_price_usd,
            "avg_daily_volume_usd": avg_daily_volume_usd,
            "upcoming_unlock_count": len(upcoming_unlocks),
            "overhang_ratio": oh_ratio,
            "days_supply_pressure": days_pressure,
            "worst_cliff_score": worst_score,
            "dilution_pct": dil_pct,
            "label": lbl,
            "recommendations": recommendations,
            "timestamp": time.time(),
        }

        if not skip_log:
            try:
                _atomic_log(log_path, result)
            except Exception:
                pass  # advisory: never crash caller

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(token_data: dict, config: dict | None = None) -> dict[str, Any]:
    """Module-level shortcut — delegates to DeFiProtocolTokenVestingOverhangAnalyzer."""
    return DeFiProtocolTokenVestingOverhangAnalyzer().analyze(token_data, config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "token_symbol": "DEMO",
        "total_supply": 1_000_000_000.0,
        "circulating_supply": 200_000_000.0,
        "upcoming_unlocks": [
            {"unlock_date_days": 20, "amount": 50_000_000.0, "recipient_type": "investor"},
            {"unlock_date_days": 90, "amount": 100_000_000.0, "recipient_type": "team"},
            {"unlock_date_days": 180, "amount": 20_000_000.0, "recipient_type": "ecosystem"},
        ],
        "current_price_usd": 2.50,
        "avg_daily_volume_usd": 5_000_000.0,
    }

    r = analyze(_demo, config={"skip_log": True})
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)
