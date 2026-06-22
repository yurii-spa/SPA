"""
MP-687: ProtocolUpgradeRiskAssessor
Assess the risk of a DeFi protocol undergoing a smart contract upgrade.
Pure stdlib, read-only analytics, atomic JSON writes.
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/upgrade_risk_log.json")
MAX_ENTRIES = 100


@dataclass
class UpgradeProposal:
    proposal_id: str
    protocol: str
    upgrade_type: str        # "PROXY_UPGRADE", "PARAMETER_CHANGE", "MIGRATION", "FULL_REWRITE"
    lines_changed: int
    audit_status: str        # "UNAUDITED", "IN_PROGRESS", "AUDITED", "MULTI_AUDITED"
    timelock_hours: int
    has_rollback: bool
    affected_tvl_usd: float
    community_vote_pct: float  # 0–100
    days_since_last_upgrade: int


@dataclass
class UpgradeRiskReport:
    proposal_id: str
    protocol: str
    upgrade_type: str
    code_change_risk: float
    audit_risk: float
    governance_risk: float
    operational_risk: float
    composite_risk: float
    risk_category: str        # ROUTINE / ELEVATED / HIGH / CRITICAL
    tvl_at_risk_usd: float
    recommendation: str       # MONITOR / PAUSE_NEW_DEPOSITS / REDUCE_EXPOSURE / EXIT
    action_items: List[str]


# ---------------------------------------------------------------------------
# Risk sub-component calculations
# ---------------------------------------------------------------------------

def _code_change_risk(proposal: UpgradeProposal) -> float:
    """
    FULL_REWRITE: 0.9
    MIGRATION:    0.7
    PROXY_UPGRADE: min(1.0, 0.2 + lines_changed/5000)
    PARAMETER_CHANGE: min(0.3, lines_changed/500)
    """
    t = proposal.upgrade_type
    if t == "FULL_REWRITE":
        return 0.9
    elif t == "MIGRATION":
        return 0.7
    elif t == "PROXY_UPGRADE":
        return min(1.0, 0.2 + proposal.lines_changed / 5000.0)
    elif t == "PARAMETER_CHANGE":
        return min(0.3, proposal.lines_changed / 500.0)
    else:
        # Unknown type — treat as elevated
        return 0.5


def _audit_risk(proposal: UpgradeProposal) -> float:
    """
    UNAUDITED:     0.9
    IN_PROGRESS:   0.6
    AUDITED:       0.2
    MULTI_AUDITED: 0.05
    """
    mapping = {
        "UNAUDITED":     0.9,
        "IN_PROGRESS":   0.6,
        "AUDITED":       0.2,
        "MULTI_AUDITED": 0.05,
    }
    return mapping.get(proposal.audit_status, 0.9)


def _governance_risk(proposal: UpgradeProposal) -> float:
    """
    Base: 0.3
    +0.3 if community_vote_pct < 10
    -0.15 if community_vote_pct > 66
    +0.2 if days_since_last_upgrade < 30
    Clamped [0.05, 0.95]
    """
    risk = 0.3
    if proposal.community_vote_pct < 10:
        risk += 0.3
    elif proposal.community_vote_pct > 66:
        risk -= 0.15
    if proposal.days_since_last_upgrade < 30:
        risk += 0.2
    return max(0.05, min(0.95, risk))


def _operational_risk(proposal: UpgradeProposal) -> float:
    """
    Base: 0.5
    -0.2 if timelock_hours >= 48
    -0.2 if has_rollback
    +0.3 if timelock_hours == 0
    Clamped [0.05, 0.95]
    """
    risk = 0.5
    if proposal.timelock_hours >= 48:
        risk -= 0.2
    if proposal.has_rollback:
        risk -= 0.2
    if proposal.timelock_hours == 0:
        risk += 0.3
    return max(0.05, min(0.95, risk))


def _composite_risk(code: float, audit: float, governance: float, operational: float) -> float:
    """code*0.30 + audit*0.35 + governance*0.15 + operational*0.20"""
    return code * 0.30 + audit * 0.35 + governance * 0.15 + operational * 0.20


def _risk_category(composite: float) -> str:
    """
    < 0.25 → ROUTINE
    < 0.45 → ELEVATED
    < 0.65 → HIGH
    else   → CRITICAL
    """
    if composite < 0.25:
        return "ROUTINE"
    elif composite < 0.45:
        return "ELEVATED"
    elif composite < 0.65:
        return "HIGH"
    else:
        return "CRITICAL"


def _recommendation(category: str) -> str:
    mapping = {
        "ROUTINE":   "MONITOR",
        "ELEVATED":  "PAUSE_NEW_DEPOSITS",
        "HIGH":      "REDUCE_EXPOSURE",
        "CRITICAL":  "EXIT",
    }
    return mapping.get(category, "MONITOR")


def _action_items(proposal: UpgradeProposal, category: str) -> List[str]:
    """Build action item list based on risk signals."""
    items: List[str] = []

    if proposal.audit_status in ("UNAUDITED", "IN_PROGRESS"):
        items.append("📋 Wait for audit completion before new deposits")

    if proposal.timelock_hours < 24:
        items.append("⚠️ Short timelock — monitor on-chain for sudden changes")

    if not proposal.has_rollback:
        items.append("⚠️ No rollback mechanism — upgrade is irreversible")

    if proposal.upgrade_type == "FULL_REWRITE":
        items.append("🚨 Full rewrite — treat as new protocol, re-evaluate from scratch")

    if category == "CRITICAL":
        items.append("🚨 Exit positions before upgrade executes")

    if category == "ROUTINE":
        items.append("✅ Routine upgrade — normal monitoring sufficient")

    return items


# ---------------------------------------------------------------------------
# Main assessment entry points
# ---------------------------------------------------------------------------

def assess(proposal: UpgradeProposal) -> UpgradeRiskReport:
    """Assess a single upgrade proposal and return UpgradeRiskReport."""
    code   = _code_change_risk(proposal)
    audit  = _audit_risk(proposal)
    gov    = _governance_risk(proposal)
    ops    = _operational_risk(proposal)
    comp   = _composite_risk(code, audit, gov, ops)
    cat    = _risk_category(comp)
    rec    = _recommendation(cat)
    items  = _action_items(proposal, cat)
    tvl_at_risk = proposal.affected_tvl_usd * comp

    return UpgradeRiskReport(
        proposal_id=proposal.proposal_id,
        protocol=proposal.protocol,
        upgrade_type=proposal.upgrade_type,
        code_change_risk=code,
        audit_risk=audit,
        governance_risk=gov,
        operational_risk=ops,
        composite_risk=comp,
        risk_category=cat,
        tvl_at_risk_usd=tvl_at_risk,
        recommendation=rec,
        action_items=items,
    )


def assess_batch(proposals: List[UpgradeProposal]) -> List[UpgradeRiskReport]:
    """Assess a list of proposals. Returns [] for empty input."""
    return [assess(p) for p in proposals]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _report_to_dict(report: UpgradeRiskReport) -> dict:
    return {
        "proposal_id":      report.proposal_id,
        "protocol":         report.protocol,
        "upgrade_type":     report.upgrade_type,
        "code_change_risk": report.code_change_risk,
        "audit_risk":       report.audit_risk,
        "governance_risk":  report.governance_risk,
        "operational_risk": report.operational_risk,
        "composite_risk":   report.composite_risk,
        "risk_category":    report.risk_category,
        "tvl_at_risk_usd":  report.tvl_at_risk_usd,
        "recommendation":   report.recommendation,
        "action_items":     report.action_items,
        "timestamp":        time.time(),
    }


def save_results(report: UpgradeRiskReport, data_file: Path = DATA_FILE) -> None:
    """Append report to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(data_file)
    history.append(_report_to_dict(report))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(str(tmp), str(data_file))


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load ring-buffer history. Returns [] if file missing or invalid."""
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo_run() -> None:
    """Quick smoke-test demo."""
    proposals = [
        UpgradeProposal(
            proposal_id="PROP-001",
            protocol="Aave V3",
            upgrade_type="PARAMETER_CHANGE",
            lines_changed=50,
            audit_status="AUDITED",
            timelock_hours=72,
            has_rollback=True,
            affected_tvl_usd=5_000_000_000,
            community_vote_pct=75.0,
            days_since_last_upgrade=180,
        ),
        UpgradeProposal(
            proposal_id="PROP-002",
            protocol="NewProtocol",
            upgrade_type="FULL_REWRITE",
            lines_changed=10000,
            audit_status="UNAUDITED",
            timelock_hours=0,
            has_rollback=False,
            affected_tvl_usd=50_000_000,
            community_vote_pct=5.0,
            days_since_last_upgrade=10,
        ),
    ]
    for p in proposals:
        r = assess(p)
        print(f"{r.proposal_id} [{r.protocol}]: {r.risk_category} / {r.recommendation}")
        print(f"  composite={r.composite_risk:.3f}  tvl_at_risk=${r.tvl_at_risk_usd:,.0f}")
        for item in r.action_items:
            print(f"  {item}")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv or len(sys.argv) == 1:
        _demo_run()
    elif "--run" in sys.argv:
        _demo_run()
        print("(no data written in demo mode)")
