"""
MP-862 ProtocolTreasuryRunwayAnalyzer
======================================
Advisory-only analytics module. Estimates protocol financial runway based on
treasury assets vs. burn rate, and assesses sustainability of operations.

Pure Python stdlib. No external dependencies.
Atomic writes via tmp + os.replace.
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "treasury_runway_log.json"
)
_LOG_CAP = 100

_DEFAULT_PESSIMISTIC_HAIRCUT = 0.5


def _resolve_data_file(data_dir: str | None) -> str:
    if data_dir:
        return os.path.join(data_dir, "treasury_runway_log.json")
    return os.path.abspath(_DATA_FILE)


def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    log = _load_log(path)
    log.append(record)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ─────────────────────────────────────────────────────────────────────────────
# Label helpers
# ─────────────────────────────────────────────────────────────────────────────

def _runway_label(
    adjusted_runway_months: float,
    net_burn: float,
    treasury_usd: float,
) -> str:
    """
    SELF_SUSTAINING: net_burn <= 0 (profitable)
    HEALTHY:   adjusted_runway >= 36
    ADEQUATE:  >= 18
    TIGHT:     >= 6
    CRITICAL:  >= 1
    INSOLVENT: < 1 or (treasury=0 and net_burn > 0)
    """
    if net_burn <= 0:
        return "SELF_SUSTAINING"
    if treasury_usd == 0 and net_burn > 0:
        return "INSOLVENT"
    # adjusted_runway stored as 9999.0 for inf — treated as healthy
    if adjusted_runway_months >= 36:
        return "HEALTHY"
    if adjusted_runway_months >= 18:
        return "ADEQUATE"
    if adjusted_runway_months >= 6:
        return "TIGHT"
    if adjusted_runway_months >= 1:
        return "CRITICAL"
    return "INSOLVENT"


def _governance_safety_label(has_dao_vote: bool) -> str:
    if has_dao_vote:
        return "DAO-governed spending — treasury changes require governance"
    return "Centralized treasury — spending not subject to DAO approval"


def _recommendation(
    label: str,
    adjusted_runway_months: float,
    net_burn: float,
    vesting_pressure_pct: float,
) -> str:
    if label == "SELF_SUSTAINING":
        return (
            f"Protocol profitable at {abs(net_burn):.0f} USD/month net surplus. "
            f"Strong financial position."
        )
    if label == "HEALTHY":
        return (
            f"{adjusted_runway_months:.0f}+ months runway. Monitor vesting unlocks "
            f"({vesting_pressure_pct:.1f}% monthly pressure)."
        )
    if label == "ADEQUATE":
        return (
            f"{adjusted_runway_months:.0f} months runway. "
            f"Focus on revenue growth to reach sustainability."
        )
    if label == "TIGHT":
        return (
            f"Only {adjusted_runway_months:.1f} months runway. "
            f"Urgent: reduce burn or increase revenue."
        )
    if label == "CRITICAL":
        return (
            f"CRITICAL: Less than {adjusted_runway_months:.1f} months runway. "
            f"Immediate action required."
        )
    # INSOLVENT
    return "INSOLVENT: Treasury insufficient to cover operations. Protocol may collapse."


# ─────────────────────────────────────────────────────────────────────────────
# Core analyze function
# ─────────────────────────────────────────────────────────────────────────────

def analyze(
    protocols: list,
    config: dict | None = None,
    data_dir: str | None = None,
    persist: bool = False,
) -> dict:
    """
    Estimates protocol financial runway based on treasury assets vs. burn rate.

    Parameters
    ----------
    protocols : list[dict]
        Each entry must contain:
          name, treasury_usd, monthly_burn_usd, monthly_revenue_usd,
          token_price_usd, token_treasury_amount, vesting_unlock_usd_per_month,
          has_dao_vote_for_spending
    config : dict, optional
        pessimistic_token_haircut (default 0.5)
    data_dir : str, optional
        Override directory for log file.
    persist : bool
        If True, append result to ring-buffer log.

    Returns
    -------
    dict with enriched protocols list and summary fields.
    """
    cfg = config or {}
    haircut = float(cfg.get("pessimistic_token_haircut", _DEFAULT_PESSIMISTIC_HAIRCUT))

    ts = time.time()

    # ── Empty input ──────────────────────────────────────────────────────────
    if not protocols:
        result = {
            "protocols": [],
            "most_solvent": None,
            "most_at_risk": None,
            "profitable_protocols": [],
            "average_runway_months": None,
            "timestamp": ts,
        }
        if persist:
            _append_log(_resolve_data_file(data_dir), result)
        return result

    # ── Per-protocol calculations ─────────────────────────────────────────────
    enriched = []
    for proto in protocols:
        name = str(proto.get("name", ""))
        treasury_usd = float(proto.get("treasury_usd", 0.0))
        monthly_burn = float(proto.get("monthly_burn_usd", 0.0))
        monthly_revenue = float(proto.get("monthly_revenue_usd", 0.0))
        token_price = float(proto.get("token_price_usd", 0.0))
        token_amount = float(proto.get("token_treasury_amount", 0.0))
        vesting_unlock = float(proto.get("vesting_unlock_usd_per_month", 0.0))
        has_dao = bool(proto.get("has_dao_vote_for_spending", False))

        # net burn (positive = burning cash, negative = profitable)
        net_burn = monthly_burn - monthly_revenue

        # stablecoin runway
        if net_burn > 0:
            sc_runway = treasury_usd / net_burn
        else:
            sc_runway = 9999.0  # inf → 9999

        # token haircut value
        token_value_haircut = token_amount * token_price * (1.0 - haircut)

        # adjusted treasury
        adjusted_treasury = treasury_usd + token_value_haircut

        # adjusted runway
        if net_burn > 0:
            adj_runway = adjusted_treasury / net_burn
        else:
            adj_runway = 9999.0

        # coverage ratio
        if monthly_burn > 0:
            coverage_ratio = monthly_revenue / monthly_burn
        else:
            coverage_ratio = 9999.0

        # vesting pressure
        if treasury_usd > 0:
            vesting_pressure_pct = vesting_unlock / treasury_usd * 100.0
        else:
            vesting_pressure_pct = 0.0

        # boolean flags
        is_profitable = net_burn <= 0
        break_even_revenue = monthly_burn

        # Special case: treasury=0 and net_burn > 0 → INSOLVENT, runway=0
        if treasury_usd == 0 and net_burn > 0:
            sc_runway = 0.0
            adj_runway = 0.0

        # Label
        label = _runway_label(adj_runway, net_burn, treasury_usd)
        gov_label = _governance_safety_label(has_dao)
        rec = _recommendation(label, adj_runway, net_burn, vesting_pressure_pct)

        enriched.append({
            "name": name,
            "stablecoin_runway_months": sc_runway,
            "adjusted_runway_months": adj_runway,
            "net_burn_per_month": net_burn,
            "is_profitable": is_profitable,
            "break_even_revenue": break_even_revenue,
            "coverage_ratio": coverage_ratio,
            "vesting_pressure_pct": vesting_pressure_pct,
            "runway_label": label,
            "governance_safety_label": gov_label,
            "recommendation": rec,
        })

    # ── Summary ──────────────────────────────────────────────────────────────

    # most_solvent: highest adjusted_runway_months (9999 counts; highest wins)
    most_solvent_entry = max(enriched, key=lambda x: x["adjusted_runway_months"])
    most_solvent = most_solvent_entry["name"]

    # most_at_risk: lowest adjusted_runway_months excluding 9999 ones;
    # if all 9999 (all profitable), pick one with highest vesting_pressure_pct
    finite_entries = [e for e in enriched if e["adjusted_runway_months"] < 9999.0]
    if finite_entries:
        most_at_risk_entry = min(finite_entries, key=lambda x: x["adjusted_runway_months"])
        most_at_risk = most_at_risk_entry["name"]
    else:
        # all profitable — pick highest vesting pressure
        most_at_risk_entry = max(enriched, key=lambda x: x["vesting_pressure_pct"])
        most_at_risk = most_at_risk_entry["name"]

    # profitable protocols
    profitable_protocols = [e["name"] for e in enriched if e["is_profitable"]]

    # average runway: mean of finite (< 9999) adjusted_runway_months; None if all 9999
    finite_runways = [e["adjusted_runway_months"] for e in enriched
                      if e["adjusted_runway_months"] < 9999.0]
    if finite_runways:
        average_runway_months = sum(finite_runways) / len(finite_runways)
    else:
        average_runway_months = None

    result = {
        "protocols": enriched,
        "most_solvent": most_solvent,
        "most_at_risk": most_at_risk,
        "profitable_protocols": profitable_protocols,
        "average_runway_months": average_runway_months,
        "timestamp": ts,
    }

    if persist:
        _append_log(_resolve_data_file(data_dir), result)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _demo() -> None:
    import pprint
    demo_protocols = [
        {
            "name": "Aave",
            "treasury_usd": 100_000_000,
            "monthly_burn_usd": 2_000_000,
            "monthly_revenue_usd": 3_000_000,
            "token_price_usd": 85.0,
            "token_treasury_amount": 500_000,
            "vesting_unlock_usd_per_month": 500_000,
            "has_dao_vote_for_spending": True,
        },
        {
            "name": "SmallProtocol",
            "treasury_usd": 500_000,
            "monthly_burn_usd": 200_000,
            "monthly_revenue_usd": 50_000,
            "token_price_usd": 0.50,
            "token_treasury_amount": 1_000_000,
            "vesting_unlock_usd_per_month": 100_000,
            "has_dao_vote_for_spending": False,
        },
    ]
    res = analyze(demo_protocols)
    pprint.pprint(res)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-862 Protocol Treasury Runway Analyzer")
    parser.add_argument("--run", action="store_true", help="Run demo and persist log")
    parser.add_argument("--check", action="store_true", help="Run demo, print, no persist (default)")
    parser.add_argument("--data-dir", dest="data_dir", default=None)
    args = parser.parse_args()

    _demo()
