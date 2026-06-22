"""
MP-781: TokenUnlockMonitor
Tracks scheduled token unlock events and their sell pressure risk.
Computes: unlock_value_usd, dilution_pct, days_until_unlock, sell_pressure_score (0-100),
risk_level: LOW / MEDIUM / HIGH / CRITICAL.
Ring buffer log, capped 100 entries, atomic write. stdlib only. LLM_FORBIDDEN.
"""

import json
import os
import time
from typing import List, Dict, Optional, Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = os.path.join(DATA_DIR, "token_unlock_log.json")
LOG_CAP = 100
SECONDS_PER_DAY = 86_400.0

# Sell-pressure scoring weights (tuned so TEAM/INVESTOR score highest)
_CATEGORY_WEIGHT = {
    "TEAM": 1.00,
    "INVESTOR": 0.90,
    "ECOSYSTEM": 0.50,
    "PUBLIC": 0.25,
}
_DEFAULT_CATEGORY_WEIGHT = 0.40  # fallback for unknown categories

# Risk thresholds: (dilution_pct threshold, days_until_unlock threshold) → risk_level
# Evaluated top-down; first match wins.
_RISK_RULES = [
    # dilution %, days_until_unlock
    (20.0, 30,  "CRITICAL"),
    (10.0, 30,  "HIGH"),
    (20.0, 90,  "HIGH"),
    ( 5.0, 90,  "MEDIUM"),
    (10.0, 180, "MEDIUM"),
    ( 0.0, 0,   "LOW"),      # catch-all
]


# ---------------------------------------------------------------------------
# Atomic write helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, entry: Any, cap: int = LOG_CAP) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# Computation helpers
# ---------------------------------------------------------------------------

def _validate_event(event: Dict[str, Any]) -> None:
    required = [
        "protocol", "unlock_date_ts", "unlock_amount_tokens",
        "current_price_usd", "circulating_supply", "category",
    ]
    for field in required:
        if field not in event:
            raise ValueError(f"Missing field '{field}' in unlock event: {event}")
    if event["unlock_amount_tokens"] < 0:
        raise ValueError("unlock_amount_tokens must be non-negative")
    if event["current_price_usd"] < 0:
        raise ValueError("current_price_usd must be non-negative")
    if event["circulating_supply"] <= 0:
        raise ValueError("circulating_supply must be positive")
    valid_cats = {"TEAM", "INVESTOR", "ECOSYSTEM", "PUBLIC"}
    if event["category"] not in valid_cats:
        raise ValueError(
            f"category must be one of {valid_cats}, got '{event['category']}'"
        )


def _days_until_unlock(unlock_date_ts: float, now_ts: Optional[float] = None) -> float:
    """Positive = future, negative = past (already unlocked)."""
    now = now_ts if now_ts is not None else time.time()
    return (unlock_date_ts - now) / SECONDS_PER_DAY


def _sell_pressure_score(
    dilution_pct: float,
    days_until: float,
    category: str,
) -> float:
    """
    Sell pressure score 0-100.

    Formula:
      base = category_weight * 100
      dilution_factor = min(1.0, dilution_pct / 20.0)    (saturates at 20%)
      urgency_factor:
        if days_until <= 0 : 1.0  (already unlocked / happening now)
        elif days_until <= 7: 0.9
        elif days_until <= 30: 0.75
        elif days_until <= 90: 0.55
        elif days_until <= 180: 0.35
        else: 0.15
      score = base * 0.4 + base * dilution_factor * 0.35 + base * urgency_factor * 0.25
    """
    cat_w = _CATEGORY_WEIGHT.get(category, _DEFAULT_CATEGORY_WEIGHT)
    base = cat_w * 100.0

    dilution_factor = min(1.0, dilution_pct / 20.0)

    if days_until <= 0:
        urgency_factor = 1.0
    elif days_until <= 7:
        urgency_factor = 0.90
    elif days_until <= 30:
        urgency_factor = 0.75
    elif days_until <= 90:
        urgency_factor = 0.55
    elif days_until <= 180:
        urgency_factor = 0.35
    else:
        urgency_factor = 0.15

    score = (
        base * 0.40
        + base * dilution_factor * 0.35
        + base * urgency_factor * 0.25
    )
    return min(100.0, round(score, 2))


def _risk_level(dilution_pct: float, days_until: float) -> str:
    """
    risk_level: LOW / MEDIUM / HIGH / CRITICAL

    Thresholds (spec):
      CRITICAL: dilution > 20% AND days_until < 30
      HIGH:     dilution > 10% AND days_until < 30, OR dilution > 20% AND days_until < 90
      MEDIUM:   dilution > 5%  AND days_until < 90, OR dilution > 10% AND days_until < 180
      LOW:      everything else
    """
    for dil_thresh, day_thresh, level in _RISK_RULES:
        if dilution_pct > dil_thresh and days_until < day_thresh:
            return level
    return "LOW"


def _enrich_event(event: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Compute derived fields and return enriched copy."""
    _validate_event(event)
    amount = event["unlock_amount_tokens"]
    price = event["current_price_usd"]
    supply = event["circulating_supply"]

    unlock_value_usd = amount * price
    dilution_pct = (amount / supply) * 100.0
    days_until = _days_until_unlock(event["unlock_date_ts"], now_ts)
    sp_score = _sell_pressure_score(dilution_pct, days_until, event["category"])
    r_level = _risk_level(dilution_pct, days_until)

    enriched = dict(event)
    enriched["unlock_value_usd"] = round(unlock_value_usd, 4)
    enriched["dilution_pct"] = round(dilution_pct, 6)
    enriched["days_until_unlock"] = round(days_until, 4)
    enriched["sell_pressure_score"] = sp_score
    enriched["risk_level"] = r_level
    return enriched


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TokenUnlockMonitor:
    """
    MP-781: Monitor scheduled token unlock events and assess sell pressure risk.

    Usage:
        mon = TokenUnlockMonitor()
        result = mon.monitor(events)
        upcoming = mon.get_upcoming_unlocks(days=30)
        high_risk = mon.get_high_risk_protocols()
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        log_cap: int = LOG_CAP,
    ):
        self._data_dir = data_dir or DATA_DIR
        self._log_file = os.path.join(self._data_dir, "token_unlock_log.json")
        self._log_cap = log_cap
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def monitor(
        self,
        unlock_events: List[Dict[str, Any]],
        now_ts: Optional[float] = None,
        write_log: bool = False,
    ) -> Dict[str, Any]:
        """
        Process unlock events and compute risk metrics.

        Parameters
        ----------
        unlock_events : list of dicts with keys:
            protocol, unlock_date_ts, unlock_amount_tokens, current_price_usd,
            circulating_supply, category (TEAM/INVESTOR/ECOSYSTEM/PUBLIC)
        now_ts : optional float — override current UTC timestamp (for testing)
        write_log : bool — persist summary to ring-buffer log

        Returns
        -------
        dict with:
            events (enriched), summary, timestamp_utc
        """
        now = now_ts if now_ts is not None else time.time()

        enriched_events: List[Dict[str, Any]] = []
        for ev in unlock_events:
            enriched_events.append(_enrich_event(ev, now_ts=now))

        # Sort by days_until_unlock ascending (most imminent first)
        enriched_events.sort(key=lambda e: e["days_until_unlock"])

        summary = self._build_summary(enriched_events)
        result = {
            "events": enriched_events,
            "summary": summary,
            "timestamp_utc": now,
            "event_count": len(enriched_events),
        }
        self._last_result = result
        if write_log:
            self._persist(result)
        return result

    def get_upcoming_unlocks(
        self,
        days: float = 30,
        now_ts: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return enriched events within the next ``days`` days from the last
        monitor() call. If monitor() has not been called, returns [].
        """
        if self._last_result is None:
            return []
        cutoff = float(days)
        return [
            ev for ev in self._last_result["events"]
            if 0 <= ev["days_until_unlock"] <= cutoff
        ]

    def get_high_risk_protocols(self) -> List[Dict[str, Any]]:
        """
        Return events with risk_level HIGH or CRITICAL from the last monitor() call,
        sorted by sell_pressure_score descending.
        """
        if self._last_result is None:
            return []
        high_risk = [
            ev for ev in self._last_result["events"]
            if ev["risk_level"] in ("HIGH", "CRITICAL")
        ]
        high_risk.sort(key=lambda e: e["sell_pressure_score"], reverse=True)
        return high_risk

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_summary(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not events:
            return {
                "total_events": 0,
                "total_unlock_value_usd": 0.0,
                "risk_breakdown": {
                    "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0
                },
                "avg_sell_pressure_score": 0.0,
                "max_sell_pressure_score": 0.0,
                "highest_risk_protocol": None,
            }

        risk_breakdown: Dict[str, int] = {
            "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0
        }
        total_value = 0.0
        scores = []
        for ev in events:
            risk_breakdown[ev["risk_level"]] = (
                risk_breakdown.get(ev["risk_level"], 0) + 1
            )
            total_value += ev["unlock_value_usd"]
            scores.append(ev["sell_pressure_score"])

        avg_score = round(sum(scores) / len(scores), 2)
        max_score = max(scores)
        highest = max(events, key=lambda e: e["sell_pressure_score"])

        return {
            "total_events": len(events),
            "total_unlock_value_usd": round(total_value, 4),
            "risk_breakdown": risk_breakdown,
            "avg_sell_pressure_score": avg_score,
            "max_sell_pressure_score": round(max_score, 2),
            "highest_risk_protocol": highest["protocol"],
        }

    def _persist(self, result: Dict[str, Any]) -> None:
        """Append compact summary to ring-buffer log."""
        entry = {
            "timestamp_utc": result["timestamp_utc"],
            "event_count": result["event_count"],
            "summary": result["summary"],
        }
        _append_log(self._log_file, entry, self._log_cap)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def monitor(
    unlock_events: List[Dict[str, Any]],
    now_ts: Optional[float] = None,
    write_log: bool = False,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Module-level convenience wrapper for TokenUnlockMonitor.monitor()."""
    return TokenUnlockMonitor(data_dir=data_dir).monitor(
        unlock_events, now_ts=now_ts, write_log=write_log
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo() -> None:
    now = time.time()
    events = [
        {
            "protocol": "ProjectAlpha",
            "unlock_date_ts": now + 20 * SECONDS_PER_DAY,
            "unlock_amount_tokens": 5_000_000,
            "current_price_usd": 2.50,
            "circulating_supply": 20_000_000,
            "category": "TEAM",
        },
        {
            "protocol": "ProjectBeta",
            "unlock_date_ts": now + 60 * SECONDS_PER_DAY,
            "unlock_amount_tokens": 2_000_000,
            "current_price_usd": 1.00,
            "circulating_supply": 100_000_000,
            "category": "INVESTOR",
        },
        {
            "protocol": "ProjectGamma",
            "unlock_date_ts": now + 10 * SECONDS_PER_DAY,
            "unlock_amount_tokens": 500_000,
            "current_price_usd": 0.50,
            "circulating_supply": 200_000_000,
            "category": "PUBLIC",
        },
    ]
    mon = TokenUnlockMonitor()
    result = mon.monitor(events)
    print(json.dumps(result, indent=2))
    print("\nUpcoming (30d):", json.dumps(mon.get_upcoming_unlocks(30), indent=2))
    print("\nHigh-risk:", json.dumps(mon.get_high_risk_protocols(), indent=2))


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        _demo()
    else:
        print("Usage: python3 -m spa_core.analytics.token_unlock_monitor --demo")
