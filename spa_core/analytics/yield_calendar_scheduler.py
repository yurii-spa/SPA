"""
MP-833 YieldCalendarScheduler
Advisory-only analytics module.
Tracks upcoming DeFi yield events, classifies urgency and impact,
and emits prioritized action recommendations.

Data log: data/yield_calendar_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
from datetime import date, datetime, timedelta
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = {
    "EPOCH_END",
    "TOKEN_UNLOCK",
    "VESTING_CLIFF",
    "EMISSION_CHANGE",
    "REWARD_DISTRIBUTION",
}

_DEFAULT_HORIZON_DAYS = 90
_DEFAULT_CRITICAL_DAYS = 14
_LOG_RING_SIZE = 100

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> date:
    """Parse ISO date string to date object."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _days_until(event_date: date, today: date) -> int:
    """Return signed days until event (negative = past)."""
    return (event_date - today).days


def _urgency(days: int, critical_days: int, horizon_days: int) -> str:
    if days < 0:
        return "PAST"
    if days <= critical_days:
        return "URGENT"
    if days <= horizon_days:
        return "UPCOMING"
    return "DISTANT"


def _impact_label(pct: float) -> str:
    if pct >= 5.0:
        return "MAJOR_POSITIVE"
    if pct > 0:
        return "MINOR_POSITIVE"
    if pct == 0:
        return "NEUTRAL"
    if pct > -5.0:
        return "MINOR_NEGATIVE"
    return "MAJOR_NEGATIVE"


def _action_recommended(event_type: str, urgency: str, impact: str, event_date: str) -> str:
    if impact == "MAJOR_POSITIVE" and urgency == "URGENT":
        return f"Prepare to capture yield boost — act before {event_date}"
    if impact == "MAJOR_POSITIVE" and urgency == "UPCOMING":
        return f"Monitor and plan position increase ahead of {event_date}"
    if impact == "MAJOR_NEGATIVE" and urgency == "URGENT":
        return f"Consider exit or hedge before {event_date}"
    if impact == "MAJOR_NEGATIVE" and urgency == "UPCOMING":
        return f"Review position — significant yield drop expected {event_date}"
    if event_type == "TOKEN_UNLOCK" and urgency in ("URGENT", "UPCOMING"):
        return f"Monitor token price impact from unlock at {event_date}"
    if event_type == "VESTING_CLIFF" and urgency in ("URGENT", "UPCOMING"):
        return f"Watch for selling pressure at cliff {event_date}"
    if urgency == "PAST":
        return "Event already occurred — assess realized impact"
    return f"Monitor event scheduled for {event_date}"


# ---------------------------------------------------------------------------
# Core analyse function
# ---------------------------------------------------------------------------


def analyze(events: list, config: dict = None) -> dict:
    """
    Analyse a list of DeFi yield calendar events.

    Parameters
    ----------
    events : list[dict]
        Each dict: protocol, event_type, event_date, expected_impact_pct,
                   usd_value_affected, description.
    config : dict | None
        today (ISO str override), horizon_days (int), critical_days (int).

    Returns
    -------
    dict with enriched event list and summary statistics.
    """
    cfg = config or {}
    today_str = cfg.get("today")
    today: date = _parse_date(today_str) if today_str else date.today()
    horizon_days: int = int(cfg.get("horizon_days", _DEFAULT_HORIZON_DAYS))
    critical_days: int = int(cfg.get("critical_days", _DEFAULT_CRITICAL_DAYS))

    enriched = []
    for ev in events:
        protocol = str(ev.get("protocol", ""))
        event_type = str(ev.get("event_type", ""))
        event_date_str = str(ev.get("event_date", ""))
        impact_pct = float(ev.get("expected_impact_pct", 0.0))
        usd_affected = float(ev.get("usd_value_affected", 0.0))
        description = str(ev.get("description", ""))

        try:
            event_date = _parse_date(event_date_str)
        except (ValueError, TypeError):
            # Skip malformed dates
            continue

        days = _days_until(event_date, today)
        is_past = days < 0
        urgency = _urgency(days, critical_days, horizon_days)
        impact = _impact_label(impact_pct)
        action = _action_recommended(event_type, urgency, impact, event_date_str)

        enriched.append({
            "protocol": protocol,
            "event_type": event_type,
            "event_date": event_date_str,
            "days_until": days,
            "is_past": is_past,
            "urgency": urgency,
            "expected_impact_pct": impact_pct,
            "usd_value_affected": usd_affected,
            "impact_label": impact,
            "description": description,
            "action_recommended": action,
        })

    # Sort by days_until ascending (past → soonest future → distant)
    enriched.sort(key=lambda e: e["days_until"])

    # Summary counts
    urgent_count = sum(1 for e in enriched if e["urgency"] == "URGENT")
    upcoming_count = sum(1 for e in enriched if e["urgency"] == "UPCOMING")

    # next_event: soonest non-past
    future = [e for e in enriched if not e["is_past"]]
    next_event = future[0] if future else None

    # highest_impact_event: largest abs(expected_impact_pct)
    highest_impact_event = None
    if enriched:
        highest_impact_event = max(enriched, key=lambda e: abs(e["expected_impact_pct"]))

    total_usd_at_risk = sum(
        e["usd_value_affected"] for e in enriched if e["expected_impact_pct"] < 0
    )
    total_usd_opportunity = sum(
        e["usd_value_affected"] for e in enriched if e["expected_impact_pct"] > 0
    )

    result = {
        "events": enriched,
        "urgent_count": urgent_count,
        "upcoming_count": upcoming_count,
        "next_event": next_event,
        "highest_impact_event": highest_impact_event,
        "total_usd_at_risk": total_usd_at_risk,
        "total_usd_opportunity": total_usd_opportunity,
        "timestamp": time.time(),
    }
    return result


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append result snapshot to ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "yield_calendar_log.json")

    # Load existing log
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    # Append summary snapshot (not full event list to keep log compact)
    snapshot = {
        "timestamp": result["timestamp"],
        "urgent_count": result["urgent_count"],
        "upcoming_count": result["upcoming_count"],
        "total_usd_at_risk": result["total_usd_at_risk"],
        "total_usd_opportunity": result["total_usd_opportunity"],
        "event_count": len(result["events"]),
    }
    log.append(snapshot)

    # Ring-buffer cap
    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    # Atomic write
    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_events():
    today = date.today()
    return [
        {
            "protocol": "Aave V3",
            "event_type": "EPOCH_END",
            "event_date": (today + timedelta(days=7)).isoformat(),
            "expected_impact_pct": 6.0,
            "usd_value_affected": 50000.0,
            "description": "Aave epoch ending — expect yield spike",
        },
        {
            "protocol": "Compound V3",
            "event_type": "TOKEN_UNLOCK",
            "event_date": (today + timedelta(days=30)).isoformat(),
            "expected_impact_pct": -3.0,
            "usd_value_affected": 20000.0,
            "description": "COMP token unlock — potential sell pressure",
        },
        {
            "protocol": "Morpho",
            "event_type": "EMISSION_CHANGE",
            "event_date": (today + timedelta(days=120)).isoformat(),
            "expected_impact_pct": -8.0,
            "usd_value_affected": 30000.0,
            "description": "Morpho emission halving",
        },
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-833 YieldCalendarScheduler")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    sample = _sample_events()
    result = analyze(sample)

    print(f"Events analysed : {len(result['events'])}")
    print(f"Urgent          : {result['urgent_count']}")
    print(f"Upcoming        : {result['upcoming_count']}")
    print(f"USD at risk     : ${result['total_usd_at_risk']:,.0f}")
    print(f"USD opportunity : ${result['total_usd_opportunity']:,.0f}")
    if result["next_event"]:
        ne = result["next_event"]
        print(f"Next event      : {ne['protocol']} {ne['event_type']} in {ne['days_until']}d")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to  : {args.data_dir}/yield_calendar_log.json")
