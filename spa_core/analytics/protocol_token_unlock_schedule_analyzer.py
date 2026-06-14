"""
MP-906: ProtocolTokenUnlockScheduleAnalyzer

Analyses token vesting/unlock schedules and models their sell pressure impact
on circulating supply, price dilution, and volume coverage.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/token_unlock_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/token_unlock_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

PRESSURE_LABELS = ("MINIMAL", "LOW", "MODERATE", "HIGH", "SEVERE", "EXTREME")

# Sell-pressure % of circulating supply unlocked in 30 days → base score
_SELL_PRESSURE_BRACKETS = [
    (0.50, 10),
    (2.00, 20),
    (5.00, 35),
    (10.0, 50),
    (20.0, 65),
    (35.0, 78),
    (float("inf"), 90),
]

# Recipient type risk multipliers (used for bonus)
RECIPIENT_RISK = {
    "team":       0.9,   # most likely to sell
    "investor":   0.75,
    "ecosystem":  0.4,
    "community":  0.2,
}


# ─────────────────────────────────────────────────────────────────
# Internal computation helpers (exposed for unit tests)
# ─────────────────────────────────────────────────────────────────

def _unlocks_in_window(upcoming_unlocks: list, days: int = 30) -> list:
    """Filter unlocks whose date_days_from_now is within *days*."""
    return [u for u in upcoming_unlocks if float(u.get("date_days_from_now", 999)) <= days]


def _compute_sell_pressure_30d_pct(
    upcoming_unlocks: list,
    circulating_supply: float,
) -> float:
    """
    Return (total_unlocked_in_30d / circulating_supply) * 100.
    Zero if circulating_supply <= 0.
    """
    if circulating_supply <= 0:
        return 0.0
    w = _unlocks_in_window(upcoming_unlocks, 30)
    total = sum(float(u.get("amount", 0)) for u in w)
    return (total / circulating_supply) * 100.0


def _compute_dilution_impact(
    upcoming_unlocks: list,
    total_supply: float,
) -> float:
    """
    Return (30d_unlocked / total_supply) * 100.
    Represents dilution of total supply expressed as %.
    """
    if total_supply <= 0:
        return 0.0
    w = _unlocks_in_window(upcoming_unlocks, 30)
    total = sum(float(u.get("amount", 0)) for u in w)
    return (total / total_supply) * 100.0


def _base_score_from_sell_pressure(sell_pct: float) -> int:
    """Map sell_pressure_30d_pct to a base pressure score."""
    for threshold, score in _SELL_PRESSURE_BRACKETS:
        if sell_pct <= threshold:
            return score
    return 90


def _compute_unlock_pressure_score(
    upcoming_unlocks: list,
    circulating_supply: float,
    total_supply: float,
    daily_volume_usd: float,
    current_price_usd: float,
    vesting_cliff_days: float,
    sell_pressure_30d_pct: float,
) -> int:
    """
    Return unlock_pressure_score in [0, 100].

    Components:
    1. Base from sell_pressure_30d_pct
    2. Bonus for team/investor unlocks in 30d window
    3. Bonus for large single unlock (>5 % total_supply)
    4. Bonus for imminent cliff
    5. Bonus for low volume vs 30d unlock value
    """
    score = _base_score_from_sell_pressure(sell_pressure_30d_pct)

    window = _unlocks_in_window(upcoming_unlocks, 30)

    # ── Bonus: team / investor recipient types ───────────────────
    recipient_bonus = 0
    for u in window:
        rt = str(u.get("recipient_type", "")).lower()
        risk = RECIPIENT_RISK.get(rt, 0.3)
        recipient_bonus += int(risk * 12)
    score += min(recipient_bonus, 18)

    # ── Bonus: any single unlock > 5 % of total_supply ──────────
    if total_supply > 0:
        for u in upcoming_unlocks:
            amt = float(u.get("amount", 0))
            if (amt / total_supply) > 0.05:
                score += 10
                break

    # ── Bonus: cliff imminence ───────────────────────────────────
    cliff = float(vesting_cliff_days)
    if 0 < cliff < 7:
        score += 15
    elif 0 < cliff < 14:
        score += 8
    elif 0 < cliff < 30:
        score += 3

    # ── Bonus: unlock USD vs daily volume ───────────────────────
    unlock_30d_usd = (
        sum(float(u.get("amount", 0)) for u in window) * current_price_usd
    )
    if daily_volume_usd > 0 and unlock_30d_usd >= 10 * daily_volume_usd:
        score += 15

    return max(0, min(100, score))


def _pressure_label(score: int) -> str:
    """Map pressure score to label string."""
    if score >= 85:
        return "EXTREME"
    if score >= 70:
        return "SEVERE"
    if score >= 55:
        return "HIGH"
    if score >= 40:
        return "MODERATE"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


def _compute_flags(
    upcoming_unlocks: list,
    total_supply: float,
    daily_volume_usd: float,
    current_price_usd: float,
    vesting_cliff_days: float,
) -> list:
    """Return list of active flag strings."""
    flags = []

    window_30 = _unlocks_in_window(upcoming_unlocks, 30)

    # TEAM_UNLOCK_SOON: any team unlock within 30 days
    for u in window_30:
        if str(u.get("recipient_type", "")).lower() == "team":
            flags.append("TEAM_UNLOCK_SOON")
            break

    # LARGE_SINGLE_UNLOCK: any single unlock > 5% of total_supply
    if total_supply > 0:
        for u in upcoming_unlocks:
            amt = float(u.get("amount", 0))
            if (amt / total_supply) > 0.05:
                flags.append("LARGE_SINGLE_UNLOCK")
                break

    # CLIFF_IMMINENT: vesting cliff < 7 days away
    if 0 < float(vesting_cliff_days) < 7:
        flags.append("CLIFF_IMMINENT")

    # LOW_VOLUME_VS_UNLOCK: 30d unlock USD > 10x daily volume
    unlock_30d_usd = (
        sum(float(u.get("amount", 0)) for u in window_30) * current_price_usd
    )
    if daily_volume_usd > 0 and unlock_30d_usd >= 10 * daily_volume_usd:
        flags.append("LOW_VOLUME_VS_UNLOCK")

    return flags


def _total_30d_unlock_usd(
    upcoming_unlocks: list,
    current_price_usd: float,
) -> float:
    """Sum USD value of all unlocks in the 30-day window."""
    window = _unlocks_in_window(upcoming_unlocks, 30)
    return sum(float(u.get("amount", 0)) for u in window) * current_price_usd


# ─────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────

class ProtocolTokenUnlockScheduleAnalyzer:
    """
    Advisory analyzer for token vesting / unlock schedules.

    Pure stdlib, read-only/advisory. Ring-buffer log to
    data/token_unlock_log.json (cap 100, atomic writes).
    """

    def analyze(self, tokens: list, config: dict = None) -> dict:
        """
        Analyse unlock pressure for each token.

        Parameters
        ----------
        tokens : list[dict]
            Each entry must have:
              name, total_supply, circulating_supply,
              upcoming_unlocks (list of {date_days_from_now, amount,
              recipient_type: team/investor/community/ecosystem}),
              current_price_usd, market_cap_usd, daily_volume_usd,
              vesting_cliff_days
        config : dict, optional
            Reserved for future tuneable thresholds.

        Returns
        -------
        dict
            {
              "tokens": [...per-token result dicts...],
              "highest_pressure_token": str | None,
              "lowest_pressure_token": str | None,
              "total_30d_unlock_usd": float,
              "average_pressure_score": float,
              "extreme_count": int,
              "timestamp": float,
            }
        """
        cfg = config or {}
        _ = cfg  # reserved

        results = []

        for token in tokens:
            name = str(token.get("name", "UNKNOWN"))
            total_supply = float(token.get("total_supply", 0))
            circulating_supply = float(token.get("circulating_supply", 0))
            upcoming_unlocks = list(token.get("upcoming_unlocks", []))
            current_price_usd = float(token.get("current_price_usd", 0.0))
            market_cap_usd = float(token.get("market_cap_usd", 0.0))
            daily_volume_usd = float(token.get("daily_volume_usd", 0.0))
            vesting_cliff_days = float(token.get("vesting_cliff_days", 0.0))

            sell_pct = _compute_sell_pressure_30d_pct(
                upcoming_unlocks, circulating_supply
            )
            dilution = _compute_dilution_impact(upcoming_unlocks, total_supply)
            pressure_score = _compute_unlock_pressure_score(
                upcoming_unlocks, circulating_supply, total_supply,
                daily_volume_usd, current_price_usd, vesting_cliff_days,
                sell_pct,
            )
            label = _pressure_label(pressure_score)
            flags = _compute_flags(
                upcoming_unlocks, total_supply,
                daily_volume_usd, current_price_usd, vesting_cliff_days,
            )
            unlock_usd_30d = _total_30d_unlock_usd(upcoming_unlocks, current_price_usd)

            results.append({
                "name": name,
                "total_supply": total_supply,
                "circulating_supply": circulating_supply,
                "current_price_usd": current_price_usd,
                "market_cap_usd": market_cap_usd,
                "vesting_cliff_days": vesting_cliff_days,
                "sell_pressure_30d_pct": round(sell_pct, 4),
                "dilution_impact": round(dilution, 4),
                "unlock_pressure_score": pressure_score,
                "pressure_label": label,
                "unlock_usd_30d": round(unlock_usd_30d, 2),
                "flags": flags,
            })

        # ── Aggregates ─────────────────────────────────────────
        highest_pressure_token: str | None = None
        lowest_pressure_token: str | None = None
        total_30d_usd = 0.0
        average_pressure_score = 0.0
        extreme_count = 0

        if results:
            by_score = sorted(results, key=lambda r: r["unlock_pressure_score"])
            lowest_pressure_token = by_score[0]["name"]
            highest_pressure_token = by_score[-1]["name"]

            total_30d_usd = sum(r["unlock_usd_30d"] for r in results)
            average_pressure_score = (
                sum(r["unlock_pressure_score"] for r in results) / len(results)
            )
            extreme_count = sum(1 for r in results if r["pressure_label"] == "EXTREME")

        output = {
            "tokens": results,
            "highest_pressure_token": highest_pressure_token,
            "lowest_pressure_token": lowest_pressure_token,
            "total_30d_unlock_usd": round(total_30d_usd, 2),
            "average_pressure_score": round(average_pressure_score, 2),
            "extreme_count": extreme_count,
            "timestamp": time.time(),
        }

        _append_log(output)
        return output


# ─────────────────────────────────────────────────────────────────
# Ring-buffer log
# ─────────────────────────────────────────────────────────────────

def _append_log(entry: dict) -> None:
    """Atomically append *entry* to DATA_FILE, capped at MAX_ENTRIES."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing: list = []
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, DATA_FILE)


# ─────────────────────────────────────────────────────────────────
# CLI demo
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo = [
        {
            "name": "ARB",
            "total_supply": 10_000_000_000,
            "circulating_supply": 3_000_000_000,
            "upcoming_unlocks": [
                {"date_days_from_now": 10, "amount": 1_000_000_000, "recipient_type": "team"},
                {"date_days_from_now": 90, "amount": 500_000_000, "recipient_type": "investor"},
            ],
            "current_price_usd": 1.20,
            "market_cap_usd": 3_600_000_000,
            "daily_volume_usd": 200_000_000,
            "vesting_cliff_days": 5,
        },
        {
            "name": "USDC",
            "total_supply": 43_000_000_000,
            "circulating_supply": 43_000_000_000,
            "upcoming_unlocks": [],
            "current_price_usd": 1.0,
            "market_cap_usd": 43_000_000_000,
            "daily_volume_usd": 8_000_000_000,
            "vesting_cliff_days": 0,
        },
    ]
    analyzer = ProtocolTokenUnlockScheduleAnalyzer()
    result = analyzer.analyze(demo)
    print(json.dumps(result, indent=2))
