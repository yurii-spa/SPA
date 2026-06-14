"""ProtocolMaturityScorer — MP-804.

Scores protocol maturity based on age, audit history, incident record,
team transparency, and on-chain activity to inform risk-adjusted allocation
decisions.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/protocol_maturity_log.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Scoring components (0–100 total)
---------------------------------
  age_score        (0–25) : <90d=5, <180d=10, <365d=15, <730d=20, >=730d=25
  audit_score      (0–25) : count*5 − (last_audit_days_ago//180)*5, min 0, cap 25
  incident_score   (0–25) : 25 − count*8; −10 if loss > tvl*0.1; min 0
  team_score       (0–15) : doxxed+5, bug_bounty+5, governance_token+5
  activity_score   (0–10) : log10(tx_30d+1) / log10(100001) * 10, cap 10

Maturity tiers (total_score)
-----------------------------
  BATTLE_TESTED  : >= 80
  ESTABLISHED    : >= 55
  EMERGING       : >= 30
  EXPERIMENTAL   : <  30

Max recommended allocation per tier
--------------------------------------
  EXPERIMENTAL   : 5%
  EMERGING       : 15%
  ESTABLISHED    : 30%
  BATTLE_TESTED  : 50%

CLI (advisory, result printed always)
---------------------------------------
  python3 -m spa_core.analytics.protocol_maturity_scorer --check
  python3 -m spa_core.analytics.protocol_maturity_scorer --run
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/protocol_maturity_log.json")
MAX_ENTRIES: int = 100

# Tier thresholds
_TIER_BATTLE_TESTED = 80
_TIER_ESTABLISHED = 55
_TIER_EMERGING = 30

# Allocation caps per tier (%)
_ALLOC_CAPS: Dict[str, float] = {
    "BATTLE_TESTED": 50.0,
    "ESTABLISHED": 30.0,
    "EMERGING": 15.0,
    "EXPERIMENTAL": 5.0,
}


# ---------------------------------------------------------------------------
# Internal scoring helpers (pure functions — deterministic, no I/O)
# ---------------------------------------------------------------------------

def _age_score(age_days: int) -> int:
    """0–25: stepped thresholds by protocol age in days."""
    if age_days >= 730:
        return 25
    if age_days >= 365:
        return 20
    if age_days >= 180:
        return 15
    if age_days >= 90:
        return 10
    return 5


def _audit_score(audit_count: int, last_audit_days_ago: int) -> int:
    """0–25: count*5 minus penalty for staleness; min 0, capped 25."""
    raw = int(audit_count) * 5 - (int(last_audit_days_ago) // 180) * 5
    return max(min(raw, 25), 0)


def _incident_score(
    incident_count: int,
    total_loss_usd: float,
    tvl_usd: float,
) -> int:
    """0–25: 25 − count*8; −10 extra if material loss > 10% TVL; min 0."""
    raw = 25 - int(incident_count) * 8
    if total_loss_usd > tvl_usd * 0.1:
        raw -= 10
    return max(raw, 0)


def _team_score(
    team_doxxed: bool,
    has_bug_bounty: bool,
    governance_token: bool,
) -> int:
    """0–15: +5 per positive attribute."""
    score = 0
    if team_doxxed:
        score += 5
    if has_bug_bounty:
        score += 5
    if governance_token:
        score += 5
    return score


def _activity_score(on_chain_tx_30d: int) -> int:
    """0–10: log10(tx+1) / log10(100001) * 10, capped 10."""
    raw = math.log10(max(int(on_chain_tx_30d), 0) + 1) / math.log10(100001) * 10.0
    return min(int(raw), 10)


# ---------------------------------------------------------------------------
# Tier / allocation helpers
# ---------------------------------------------------------------------------

def _maturity_tier(total_score: int) -> str:
    if total_score >= _TIER_BATTLE_TESTED:
        return "BATTLE_TESTED"
    if total_score >= _TIER_ESTABLISHED:
        return "ESTABLISHED"
    if total_score >= _TIER_EMERGING:
        return "EMERGING"
    return "EXPERIMENTAL"


# ---------------------------------------------------------------------------
# Risk / strength narrative generators
# ---------------------------------------------------------------------------

def _build_key_risks(metrics: Dict[str, Any]) -> List[str]:
    risks: List[str] = []
    audit_count: int = int(metrics.get("audit_count", 0))
    last_audit_days_ago: int = int(metrics.get("last_audit_days_ago", 0))
    incident_count: int = int(metrics.get("incident_count", 0))
    total_loss_usd: float = float(metrics.get("total_loss_usd", 0.0))
    tvl_usd: float = float(metrics.get("tvl_usd", 0.0))
    age_days: int = int(metrics.get("age_days", 0))
    team_doxxed: bool = bool(metrics.get("team_doxxed", False))

    if audit_count == 0:
        risks.append("No security audit")
    if last_audit_days_ago > 365:
        risks.append("No audit in past year")
    if incident_count > 0:
        risks.append(f"{incident_count} security incident(s) on record")
    if total_loss_usd > tvl_usd * 0.1:
        risks.append("Material losses relative to TVL")
    if age_days < 90:
        risks.append("Protocol less than 90 days old")
    if not team_doxxed:
        risks.append("Anonymous team")

    return risks


def _build_key_strengths(metrics: Dict[str, Any]) -> List[str]:
    strengths: List[str] = []
    age_days: int = int(metrics.get("age_days", 0))
    audit_count: int = int(metrics.get("audit_count", 0))
    incident_count: int = int(metrics.get("incident_count", 0))
    has_bug_bounty: bool = bool(metrics.get("has_bug_bounty", False))
    team_doxxed: bool = bool(metrics.get("team_doxxed", False))

    if age_days >= 730:
        strengths.append("730+ days live")
    if audit_count >= 3:
        strengths.append(f"{audit_count} security audits completed")
    if incident_count == 0:
        strengths.append("No security incidents")
    if has_bug_bounty:
        strengths.append("Bug bounty program active")
    if team_doxxed:
        strengths.append("Team identity verified")

    return strengths


# ---------------------------------------------------------------------------
# Ring-buffer persistence (atomic write)
# ---------------------------------------------------------------------------

def _append_log(entry: Dict[str, Any]) -> None:
    """Atomically append *entry* to the ring-buffer log (max MAX_ENTRIES)."""
    try:
        data_file: Path = DATA_FILE
        data_file.parent.mkdir(parents=True, exist_ok=True)

        if data_file.exists():
            try:
                existing: List[Any] = json.loads(
                    data_file.read_text(encoding="utf-8")
                )
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []
        else:
            existing = []

        existing.append(entry)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]

        tmp = data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        os.replace(tmp, data_file)
    except Exception:  # noqa: BLE001 — advisory module; never raise on I/O errors
        pass


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def analyze(protocol: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Score protocol maturity and return structured assessment.

    Parameters
    ----------
    protocol:
        Protocol name / identifier.
    metrics:
        Dict with keys: age_days, audit_count, last_audit_days_ago,
        incident_count, total_loss_usd, tvl_usd, team_doxxed,
        has_bug_bounty, governance_token, on_chain_tx_30d.

    Returns
    -------
    dict with keys: protocol, components, total_score, maturity_tier,
                    max_recommended_allocation_pct, key_risks,
                    key_strengths, timestamp.
    """
    age_days: int = int(metrics.get("age_days", 0))
    audit_count: int = int(metrics.get("audit_count", 0))
    last_audit_days_ago: int = int(metrics.get("last_audit_days_ago", 0))
    incident_count: int = int(metrics.get("incident_count", 0))
    total_loss_usd: float = float(metrics.get("total_loss_usd", 0.0))
    tvl_usd: float = float(metrics.get("tvl_usd", 0.0))
    team_doxxed: bool = bool(metrics.get("team_doxxed", False))
    has_bug_bounty: bool = bool(metrics.get("has_bug_bounty", False))
    governance_token: bool = bool(metrics.get("governance_token", False))
    on_chain_tx_30d: int = int(metrics.get("on_chain_tx_30d", 0))

    # ---- Component scores ---------------------------------------------------
    age_s = _age_score(age_days)
    audit_s = _audit_score(audit_count, last_audit_days_ago)
    incident_s = _incident_score(incident_count, total_loss_usd, tvl_usd)
    team_s = _team_score(team_doxxed, has_bug_bounty, governance_token)
    activity_s = _activity_score(on_chain_tx_30d)

    total_score: int = age_s + audit_s + incident_s + team_s + activity_s

    # ---- Tier & allocation --------------------------------------------------
    tier = _maturity_tier(total_score)
    alloc_cap = _ALLOC_CAPS[tier]

    # ---- Narrative ----------------------------------------------------------
    risks = _build_key_risks(metrics)
    strengths = _build_key_strengths(metrics)

    result: Dict[str, Any] = {
        "protocol": protocol,
        "components": {
            "age_score": age_s,
            "audit_score": audit_s,
            "incident_score": incident_s,
            "team_score": team_s,
            "activity_score": activity_s,
        },
        "total_score": total_score,
        "maturity_tier": tier,
        "max_recommended_allocation_pct": alloc_cap,
        "key_risks": risks,
        "key_strengths": strengths,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point (advisory only — exits 0 always)
# ---------------------------------------------------------------------------

def _demo_metrics() -> Dict[str, Any]:
    return {
        "age_days": 800,
        "audit_count": 4,
        "last_audit_days_ago": 90,
        "incident_count": 0,
        "total_loss_usd": 0.0,
        "tvl_usd": 500_000_000,
        "team_doxxed": True,
        "has_bug_bounty": True,
        "governance_token": True,
        "on_chain_tx_30d": 50_000,
    }


if __name__ == "__main__":
    import sys

    result = analyze("DemoProtocol", _demo_metrics())
    print(json.dumps(result, indent=2))
    sys.exit(0)
