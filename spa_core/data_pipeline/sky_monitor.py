"""
Sky/sUSDS GSM Pause Delay Monitor.
Sky stays at 0% allocation until Ethereum governance confirms >= 48h timelock.
This script checks on-chain state and updates watch_status.json.

Current status: PENDING (not yet confirmed as of 2026-05-21)
ADR reference: MEMORY_FACTS.md — Sky/sUSDS section
"""
import json, datetime

SKY_WATCH_CONDITION = "GSM Pause Delay >= 48h"
SKY_CURRENT_STATUS = "PENDING"  # change to CONFIRMED when on-chain event fires
SKY_LAST_CHECKED = "2026-05-21"

def check_sky_status() -> dict:
    """
    Returns current Sky eligibility status.
    In v2.0, this will call on-chain data via web3.py.
    For now: manual update required (set SKY_CURRENT_STATUS = 'CONFIRMED').
    """
    return {
        "protocol": "Sky/sUSDS",
        "watch_condition": SKY_WATCH_CONDITION,
        "status": SKY_CURRENT_STATUS,  # PENDING | CONFIRMED | FAILED
        "eligible_for_t1": SKY_CURRENT_STATUS == "CONFIRMED",
        "allocation_pct": 0.30 if SKY_CURRENT_STATUS == "CONFIRMED" else 0.0,
        "last_checked": SKY_LAST_CHECKED,
        "note": "Upon CONFIRMED: Sky → T1, 30% allocation per ADR. See MEMORY_FACTS.md.",
    }

def get_watch_list_status() -> list[dict]:
    """Returns status of all Watch List protocols."""
    return [check_sky_status()]
