"""
MP-857: ProtocolUpgradeRiskMonitor
Advisory/read-only analytics module.

Assesses the risk of upcoming or recent protocol smart-contract upgrades based
on governance safety, audit coverage, and historical track record.

CLI:
    python3 -m spa_core.analytics.protocol_upgrade_risk_monitor --check
    python3 -m spa_core.analytics.protocol_upgrade_risk_monitor --run
    python3 -m spa_core.analytics.protocol_upgrade_risk_monitor --run --data-dir /path
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "protocol_upgrade_risk_log.json")
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _timelock_safety(timelock_hours: float) -> int:
    """0-25 safety contribution; longer timelock -> higher safety."""
    if timelock_hours >= 168:
        return 25
    if timelock_hours >= 72:
        return 20
    if timelock_hours >= 48:
        return 15
    if timelock_hours >= 24:
        return 10
    if timelock_hours >= 12:
        return 5
    return 0


def _governance_safety(approval_pct: float) -> int:
    """0-25 safety contribution; higher approval -> higher safety."""
    if approval_pct >= 80:
        return 25
    if approval_pct >= 60:
        return 20
    if approval_pct >= 40:
        return 15
    if approval_pct >= 20:
        return 8
    return 0


def _audit_safety(coverage_pct: float, auditor_count: int) -> int:
    """0-25 safety contribution; better audit -> higher safety."""
    if coverage_pct >= 95 and auditor_count >= 2:
        return 25
    if coverage_pct >= 80:
        return 20
    if coverage_pct >= 60:
        return 15
    if coverage_pct >= 40:
        return 10
    if coverage_pct >= 20:
        return 5
    return 0


def _track_record_safety(success_rate: float, days_since_incident: int) -> int:
    """0-25 safety contribution; better history -> higher safety (capped at 25)."""
    if success_rate >= 1.0:
        base = 15
    elif success_rate >= 0.9:
        base = 12
    elif success_rate >= 0.75:
        base = 8
    elif success_rate >= 0.5:
        base = 4
    else:
        base = 0

    if days_since_incident >= 365:
        bonus = 10
    elif days_since_incident >= 180:
        bonus = 7
    elif days_since_incident >= 90:
        bonus = 5
    elif days_since_incident >= 30:
        bonus = 3
    else:
        bonus = 0

    return min(25, base + bonus)


def _code_change_penalty(code_change_size: str) -> int:
    """Penalty added to raw risk score based on change scope."""
    return {"CRITICAL": 15, "MAJOR": 10, "MODERATE": 5, "MINOR": 0}.get(
        code_change_size, 0
    )


def _risk_level(risk_score: int) -> str:
    if risk_score >= 75:
        return "CRITICAL"
    if risk_score >= 50:
        return "HIGH"
    if risk_score >= 25:
        return "MODERATE"
    return "LOW"


def _recommendation(
    risk_level: str,
    risk_score: int,
    timelock_hours: float,
    audit_coverage_pct: float,
    auditor_count: int,
    governance_approval_pct: float,
) -> str:
    if risk_level == "CRITICAL":
        return (
            f"Avoid interaction during upgrade. Risk score {risk_score}/100. "
            f"Wait for {timelock_hours}h timelock + post-upgrade monitoring."
        )
    if risk_level == "HIGH":
        return (
            f"Reduce exposure before upgrade executes. "
            f"Audit coverage {audit_coverage_pct:.0f}% ({auditor_count} auditors)."
        )
    if risk_level == "MODERATE":
        return (
            f"Monitor upgrade closely. "
            f"Governance approval {governance_approval_pct:.0f}%."
        )
    return (
        f"Upgrade appears well-governed. "
        f"{timelock_hours}h timelock, {audit_coverage_pct:.0f}% audit coverage."
    )


def _key_risk_factors(
    timelock_hours: float,
    governance_approval_pct: float,
    audit_coverage_pct: float,
    auditor_count: int,
    code_change_size: str,
    days_since_last_incident: int,
    previous_upgrade_success_rate: float,
) -> list:
    factors = []
    if timelock_hours < 24:
        factors.append("Short or no timelock")
    if governance_approval_pct < 60:
        factors.append("Low governance approval")
    if audit_coverage_pct < 80:
        factors.append(f"Partial audit coverage ({audit_coverage_pct:.0f}%)")
    if auditor_count < 2:
        factors.append("Single auditor")
    if code_change_size in ("MAJOR", "CRITICAL"):
        factors.append(f"Large scope change ({code_change_size})")
    if days_since_last_incident < 90:
        factors.append("Recent incident history")
    if previous_upgrade_success_rate < 0.9:
        factors.append("Below-average upgrade track record")
    return factors if factors else ["No significant risk factors identified"]


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(upgrades: list, config: dict = None) -> dict:
    """
    Assess upgrade risk for each protocol upgrade entry.

    Parameters
    ----------
    upgrades : list[dict]
        Each entry: protocol, upgrade_status, timelock_hours,
        governance_approval_pct, audit_coverage_pct, auditor_count,
        days_since_last_incident, code_change_size,
        previous_upgrade_success_rate.
    config : dict | None
        Unused (reserved for future extension). Defaults to None.

    Returns
    -------
    dict with keys: upgrades, highest_risk_upgrade, lowest_risk_upgrade,
    pending_high_risk_count, average_risk_score, timestamp.
    """
    results = []

    for u in upgrades:
        protocol = u["protocol"]
        upgrade_status = u["upgrade_status"]
        timelock_hours = float(u["timelock_hours"])
        governance_approval_pct = float(u["governance_approval_pct"])
        audit_coverage_pct = float(u["audit_coverage_pct"])
        auditor_count = int(u["auditor_count"])
        days_since_last_incident = int(u["days_since_last_incident"])
        code_change_size = u["code_change_size"]
        previous_upgrade_success_rate = float(u["previous_upgrade_success_rate"])

        ts = _timelock_safety(timelock_hours)
        gs = _governance_safety(governance_approval_pct)
        au = _audit_safety(audit_coverage_pct, auditor_count)
        tr = _track_record_safety(
            previous_upgrade_success_rate, days_since_last_incident
        )

        safety_score = ts + gs + au + tr
        penalty = _code_change_penalty(code_change_size)
        raw_risk = 100 - safety_score + penalty
        risk_score = max(0, min(100, raw_risk))

        rl = _risk_level(risk_score)
        rec = _recommendation(
            rl,
            risk_score,
            timelock_hours,
            audit_coverage_pct,
            auditor_count,
            governance_approval_pct,
        )
        factors = _key_risk_factors(
            timelock_hours,
            governance_approval_pct,
            audit_coverage_pct,
            auditor_count,
            code_change_size,
            days_since_last_incident,
            previous_upgrade_success_rate,
        )

        results.append(
            {
                "protocol": protocol,
                "upgrade_status": upgrade_status,
                "risk_score": risk_score,
                "risk_level": rl,
                "timelock_score": ts,
                "governance_score": gs,
                "audit_score": au,
                "track_record_score": tr,
                "recommendation": rec,
                "key_risk_factors": factors,
            }
        )

    # Aggregates
    if results:
        highest = max(results, key=lambda r: r["risk_score"])["protocol"]
        lowest = min(results, key=lambda r: r["risk_score"])["protocol"]
        pending_high = sum(
            1
            for r in results
            if r["upgrade_status"] in ("PENDING", "TIMELOCKED")
            and r["risk_level"] in ("HIGH", "CRITICAL")
        )
        avg_risk = sum(r["risk_score"] for r in results) / len(results)
    else:
        highest = None
        lowest = None
        pending_high = 0
        avg_risk = 0.0

    return {
        "upgrades": results,
        "highest_risk_upgrade": highest,
        "lowest_risk_upgrade": lowest,
        "pending_high_risk_count": pending_high,
        "average_risk_score": avg_risk,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Atomic log writer
# ---------------------------------------------------------------------------

def _append_log(result: dict, data_file: str) -> None:
    """Append result to ring-buffer log (max _LOG_CAP entries), atomic write."""
    try:
        with open(data_file, "r") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    data_dir = os.path.dirname(data_file)
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, data_file)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEMO_UPGRADES = [
    {
        "protocol": "Aave V3",
        "upgrade_status": "TIMELOCKED",
        "timelock_hours": 72,
        "governance_approval_pct": 85.0,
        "audit_coverage_pct": 95.0,
        "auditor_count": 3,
        "days_since_last_incident": 400,
        "code_change_size": "MODERATE",
        "previous_upgrade_success_rate": 1.0,
    },
    {
        "protocol": "Compound V3",
        "upgrade_status": "PENDING",
        "timelock_hours": 6,
        "governance_approval_pct": 45.0,
        "audit_coverage_pct": 55.0,
        "auditor_count": 1,
        "days_since_last_incident": 20,
        "code_change_size": "MAJOR",
        "previous_upgrade_success_rate": 0.7,
    },
]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-857 ProtocolUpgradeRiskMonitor")
    parser.add_argument("--check", action="store_true", help="Compute and print without writing")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DEFAULT_DATA_FILE
    if args.data_dir:
        data_file = os.path.join(args.data_dir, "protocol_upgrade_risk_log.json")

    result = analyze(_DEMO_UPGRADES)
    print(json.dumps(result, indent=2))

    if args.run:
        _append_log(result, data_file)
        print(f"\n[MP-857] Log written -> {data_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
