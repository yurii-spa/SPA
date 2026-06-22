"""
MP-902 ProtocolVersionRiskAnalyzer
-------------------------------------
Advisory / read-only analytics module.
Assesses risk from protocol upgrades, version migrations, and smart
contract changes.

CLI:
    python3 -m spa_core.analytics.protocol_version_risk_analyzer --check
    python3 -m spa_core.analytics.protocol_version_risk_analyzer --run
    python3 -m spa_core.analytics.protocol_version_risk_analyzer --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_URGENT_MIGRATION_DAYS = 14
_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "version_risk_log.json",
)

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _mechanism_risk(upgrade_mechanism: str) -> int:
    return {
        "IMMUTABLE": 0,
        "GOVERNANCE": 10,
        "TIMELOCK_ONLY": 15,
        "MULTISIG": 30,
        "ADMIN_KEY": 50,
    }.get(upgrade_mechanism, 30)  # unknown → treat as MULTISIG


def _pending_upgrade_bonus(pending_upgrade: bool) -> int:
    return 20 if pending_upgrade else 0


def _migration_risk_score(
    migration_required: bool,
    migration_deadline_days: int,
    urgent_days: int,
) -> int:
    if not migration_required:
        return 0
    if migration_deadline_days <= urgent_days:
        return 25
    if migration_deadline_days < 30:
        return 15
    return 10


def _audit_risk(audit_count: int) -> int:
    if audit_count == 0:
        return 10
    if audit_count == 1:
        return 5
    return 0


def _upgrade_risk_score(
    upgrade_mechanism: str,
    pending_upgrade: bool,
    migration_required: bool,
    migration_deadline_days: int,
    audit_count: int,
    urgent_days: int,
) -> int:
    total = (
        _mechanism_risk(upgrade_mechanism)
        + _pending_upgrade_bonus(pending_upgrade)
        + _migration_risk_score(migration_required, migration_deadline_days, urgent_days)
        + _audit_risk(audit_count)
    )
    return max(0, min(100, total))


def _migration_urgency(
    migration_required: bool,
    migration_deadline_days: int,
    urgent_days: int,
) -> str:
    if not migration_required or migration_deadline_days == 0:
        return "NONE"
    if migration_deadline_days < urgent_days:
        return "URGENT"
    if migration_deadline_days < 30:
        return "SOON"
    if migration_deadline_days < 90:
        return "PLANNED"
    return "NONE"


def _version_maturity_label(days_since_last_upgrade: int) -> str:
    if days_since_last_upgrade > 365:
        return "BATTLE_TESTED"
    if days_since_last_upgrade > 180:
        return "STABLE"
    if days_since_last_upgrade > 90:
        return "MATURING"
    return "FRESH"


def _governance_safety(upgrade_mechanism: str) -> str:
    if upgrade_mechanism == "IMMUTABLE":
        return "IMMUTABLE"
    if upgrade_mechanism in ("GOVERNANCE", "TIMELOCK_ONLY"):
        return "DECENTRALIZED"
    if upgrade_mechanism == "MULTISIG":
        return "SEMI_DECENTRALIZED"
    if upgrade_mechanism == "ADMIN_KEY":
        return "CENTRALIZED"
    return "SEMI_DECENTRALIZED"  # unknown default


def _audit_coverage_label(audit_count: int) -> str:
    if audit_count >= 3:
        return "WELL_AUDITED"
    if audit_count >= 1:
        return "AUDITED"
    return "UNAUDITED"


def _tvl_migration_risk_label(tvl_at_risk_usd: float) -> str:
    if tvl_at_risk_usd > 100_000_000:
        return "CRITICAL"
    if tvl_at_risk_usd > 10_000_000:
        return "HIGH"
    if tvl_at_risk_usd > 1_000_000:
        return "MODERATE"
    return "LOW"


def _composite_risk(upgrade_risk: int, tvl_at_risk_usd: float) -> int:
    tvl_weight = 25 if tvl_at_risk_usd > 10_000_000 else (10 if tvl_at_risk_usd > 1_000_000 else 0)
    raw = upgrade_risk * 0.7 + tvl_weight * 0.3
    return max(0, min(100, int(raw)))


def _risk_label(composite: int) -> str:
    if composite <= 20:
        return "MINIMAL"
    if composite <= 35:
        return "LOW"
    if composite <= 55:
        return "MODERATE"
    if composite <= 75:
        return "HIGH"
    return "CRITICAL"


def _build_flags(
    migration_urgency_val: str,
    pending_upgrade: bool,
    upgrade_mechanism: str,
    audit_count: int,
    tvl_at_risk_usd: float,
) -> list[str]:
    flags: list[str] = []
    if migration_urgency_val == "URGENT":
        flags.append("URGENT_MIGRATION")
    if pending_upgrade:
        flags.append("PENDING_UPGRADE")
    if upgrade_mechanism == "ADMIN_KEY":
        flags.append("CENTRALIZED_ADMIN")
    if audit_count == 0:
        flags.append("UNAUDITED_VERSION")
    if tvl_at_risk_usd > 10_000_000:
        flags.append("HIGH_TVL_AT_RISK")
    return flags


def _recommendation(
    risk_lbl: str,
    governance_safety_val: str,
    audit_coverage_lbl: str,
    flags: list[str],
    migration_urgency_val: str,
    migration_deadline_days: int,
) -> str:
    if risk_lbl in ("MINIMAL", "LOW"):
        return (
            f"Low upgrade risk. {governance_safety_val} governance, {audit_coverage_lbl}."
        )
    if risk_lbl == "MODERATE":
        flag_str = (
            ", ".join(flags[:2]) if flags else "pending changes"
        )
        return f"Moderate risk. {len(flags)} flag(s). Review: {flag_str}."
    if risk_lbl == "HIGH":
        concern_str = ", ".join(flags[:2]) if flags else "multiple concerns"
        return f"High upgrade risk. {concern_str}. Reduce exposure."
    # CRITICAL
    if migration_urgency_val == "URGENT":
        return (
            f"Critical. URGENT migration by day {migration_deadline_days}. Act immediately."
        )
    return "Critical. Multiple critical risks. Act immediately."


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(protocols: list[dict], config: dict | None = None) -> dict:
    """
    Assess upgrade/version risk for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each dict per spec.
    config : dict, optional
        ``urgent_migration_days`` (default 14).

    Returns
    -------
    dict with keys: protocols, highest_risk_protocol, urgent_migrations,
                    average_risk_score, timestamp.
    """
    if config is None:
        config = {}
    urgent_days: int = int(config.get("urgent_migration_days", _DEFAULT_URGENT_MIGRATION_DAYS))

    result_protocols: list[dict] = []

    for p in protocols:
        name: str = p.get("name", "")
        current_version: str = p.get("current_version", "")
        days_since: int = int(p.get("days_since_last_upgrade", 0))
        pending: bool = bool(p.get("pending_upgrade", False))
        mechanism: str = p.get("upgrade_mechanism", "MULTISIG")
        mig_required: bool = bool(p.get("migration_required", False))
        mig_deadline: int = int(p.get("migration_deadline_days", 0))
        audit_cnt: int = int(p.get("audit_count_for_current_version", 0))
        tvl_risk: float = float(p.get("tvl_at_risk_usd", 0.0))

        urs = _upgrade_risk_score(
            mechanism, pending, mig_required, mig_deadline, audit_cnt, urgent_days
        )
        mig_urg = _migration_urgency(mig_required, mig_deadline, urgent_days)
        maturity = _version_maturity_label(days_since)
        gov_safety = _governance_safety(mechanism)
        audit_lbl = _audit_coverage_label(audit_cnt)
        tvl_risk_lbl = _tvl_migration_risk_label(tvl_risk)
        comp = _composite_risk(urs, tvl_risk)
        risk_lbl = _risk_label(comp)
        flags = _build_flags(mig_urg, pending, mechanism, audit_cnt, tvl_risk)
        rec = _recommendation(risk_lbl, gov_safety, audit_lbl, flags, mig_urg, mig_deadline)

        result_protocols.append(
            {
                "name": name,
                "current_version": current_version,
                "upgrade_mechanism": mechanism,
                "upgrade_risk_score": urs,
                "migration_urgency": mig_urg,
                "version_maturity_label": maturity,
                "governance_safety": gov_safety,
                "audit_coverage_label": audit_lbl,
                "tvl_migration_risk_label": tvl_risk_lbl,
                "composite_risk": comp,
                "risk_label": risk_lbl,
                "flags": flags,
                "recommendation": rec,
            }
        )

    # Summary
    highest_risk_protocol: str | None = None
    if result_protocols:
        highest_risk_protocol = max(
            result_protocols, key=lambda x: x["composite_risk"]
        )["name"]

    urgent_migrations = [
        rp["name"] for rp in result_protocols if rp["migration_urgency"] == "URGENT"
    ]

    avg_risk = (
        sum(rp["composite_risk"] for rp in result_protocols) / len(result_protocols)
        if result_protocols
        else 0.0
    )

    return {
        "protocols": result_protocols,
        "highest_risk_protocol": highest_risk_protocol,
        "urgent_migrations": urgent_migrations,
        "average_risk_score": avg_risk,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(data, str(path))
def _read_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, entry: dict) -> None:
    log = _read_log(path)
    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_protocols() -> list[dict]:
    return [
        {
            "name": "Aave V3",
            "current_version": "v3.1",
            "days_since_last_upgrade": 200,
            "pending_upgrade": False,
            "upgrade_mechanism": "GOVERNANCE",
            "migration_required": False,
            "migration_deadline_days": 0,
            "audit_count_for_current_version": 4,
            "tvl_at_risk_usd": 8_000_000,
            "backward_compatible": True,
        },
        {
            "name": "Compound V3",
            "current_version": "v3",
            "days_since_last_upgrade": 60,
            "pending_upgrade": True,
            "upgrade_mechanism": "MULTISIG",
            "migration_required": True,
            "migration_deadline_days": 10,
            "audit_count_for_current_version": 1,
            "tvl_at_risk_usd": 50_000_000,
            "backward_compatible": False,
        },
        {
            "name": "Yearn V3",
            "current_version": "v3",
            "days_since_last_upgrade": 400,
            "pending_upgrade": False,
            "upgrade_mechanism": "IMMUTABLE",
            "migration_required": False,
            "migration_deadline_days": 0,
            "audit_count_for_current_version": 5,
            "tvl_at_risk_usd": 500_000,
            "backward_compatible": True,
        },
    ]


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-902 ProtocolVersionRiskAnalyzer — advisory analytics"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run on sample data, print results, do NOT write to disk (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run on sample data and append result to data/version_risk_log.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override directory for log file.",
    )
    args = parser.parse_args(argv)

    protos = _sample_protocols()
    result = analyze(protos)

    print(json.dumps(result, indent=2))
    print(f"\n[MP-902] highest_risk_protocol = {result['highest_risk_protocol']}")
    print(f"[MP-902] urgent_migrations      = {result['urgent_migrations']}")
    print(f"[MP-902] average_risk_score     = {result['average_risk_score']:.1f}")

    if args.run:
        if args.data_dir:
            log_path = os.path.join(args.data_dir, "version_risk_log.json")
        else:
            log_path = _DEFAULT_LOG_PATH
        _append_log(log_path, result)
        print(f"[MP-902] Appended to {log_path}")


if __name__ == "__main__":
    main()
