"""
MP-884: ProtocolAuditCoverageScorer
Scores DeFi protocols on their security audit quality, coverage, and recency.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer write (100 entries) → data/audit_coverage_log.json
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
DEFAULT_STALE_AUDIT_DAYS = 365
LOG_FILE = "data/audit_coverage_log.json"
LOG_MAX = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_config(config: dict | None) -> dict:
    cfg = config or {}
    return {
        "stale_audit_days": int(cfg.get("stale_audit_days", DEFAULT_STALE_AUDIT_DAYS)),
    }


def _audit_recency_score(days_since_last_audit: int) -> int:
    """Map days since last audit to a 0–100 recency score."""
    if days_since_last_audit <= 30:
        return 100
    if days_since_last_audit <= 90:
        return 80
    if days_since_last_audit <= 180:
        return 60
    if days_since_last_audit <= 365:
        return 40
    if days_since_last_audit <= 730:
        return 20
    return 0


def _auditor_quality_score(auditor_tier: str) -> int:
    """Map auditor tier string to a quality score."""
    mapping = {
        "TOP_TIER": 100,
        "MID_TIER": 70,
        "COMMUNITY": 40,
        "UNAUDITED": 0,
    }
    return mapping.get(auditor_tier, 0)


def _coverage_score(audit_coverage_pct: float) -> int:
    return min(100, int(audit_coverage_pct))


def _finding_penalty(critical_findings_unresolved: int, high_findings_unresolved: int) -> int:
    raw = critical_findings_unresolved * 20 + high_findings_unresolved * 10
    return min(60, raw)


def _bounty_score(bug_bounty_usd: float) -> int:
    if bug_bounty_usd <= 0:
        return 0
    return min(40, int(bug_bounty_usd / 250_000 * 10))


def _formal_verification_bonus(formal_verification: bool) -> int:
    return 10 if formal_verification else 0


def _overall_score(
    recency: int,
    quality: int,
    coverage: int,
    penalty: int,
    bounty: int,
    fv_bonus: int,
) -> int:
    raw = (
        recency * 0.20
        + quality * 0.30
        + coverage * 0.20
        - penalty
        + bounty * 0.15
        + fv_bonus * 0.15
    )
    return max(0, min(100, int(raw)))


def _security_grade(score: int) -> str:
    if score >= 95:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 75:
        return "B+"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _audit_status(
    auditor_tier: str,
    days_since_last_audit: int,
    audit_coverage_pct: float,
    overall: int,
    stale_audit_days: int,
) -> str:
    """Determine audit status with priority order: UNAUDITED > STALE > INSUFFICIENT > EXCELLENT > ADEQUATE."""
    if auditor_tier == "UNAUDITED":
        return "UNAUDITED"
    if days_since_last_audit > stale_audit_days:
        return "STALE"
    if audit_coverage_pct < 50:
        return "INSUFFICIENT"
    if overall >= 80:
        return "EXCELLENT"
    return "ADEQUATE"


def _build_flags(
    days_since_last_audit: int,
    critical_findings_unresolved: int,
    bug_bounty_usd: float,
    audit_coverage_pct: float,
    stale_audit_days: int,
) -> list[str]:
    flags: list[str] = []
    if days_since_last_audit > stale_audit_days:
        flags.append("STALE_AUDIT")
    if critical_findings_unresolved > 0:
        flags.append("CRITICAL_FINDINGS")
    if bug_bounty_usd <= 0:
        flags.append("NO_BOUNTY")
    if audit_coverage_pct < 50:
        flags.append("LOW_COVERAGE")
    return flags


def _recommendation(
    security_grade: str,
    audit_count: int,
    audit_coverage_pct: float,
    flags: list[str],
) -> str:
    if security_grade in ("A+", "A"):
        return (
            f"Well-secured. {audit_count} audit(s), {audit_coverage_pct:.0f}% coverage."
        )
    if security_grade in ("B+", "B"):
        if flags:
            return f"Adequate security. {len(flags)} minor concerns."
        return "Good security posture."
    if security_grade == "C":
        concern = ", ".join(flags[:2]) if flags else "low coverage"
        return f"Security gaps present. Address: {concern}."
    # D or F
    return "High security risk. Avoid until critical findings resolved."


def _score_protocol(proto: dict, stale_audit_days: int) -> dict:
    """Compute per-protocol audit coverage score."""
    name = str(proto.get("name", "unknown"))
    audit_count = int(proto.get("audit_count", 0))
    auditor_tier = str(proto.get("auditor_tier", "UNAUDITED"))
    days_since = int(proto.get("days_since_last_audit", 0))
    lines_of_code = int(proto.get("lines_of_code", 0))
    audit_coverage_pct = float(proto.get("audit_coverage_pct", 0.0))
    critical_unresolved = int(proto.get("critical_findings_unresolved", 0))
    high_unresolved = int(proto.get("high_findings_unresolved", 0))
    bug_bounty_usd = float(proto.get("bug_bounty_usd", 0.0))
    formal_verification = bool(proto.get("formal_verification", False))

    recency = _audit_recency_score(days_since)
    quality = _auditor_quality_score(auditor_tier)
    coverage = _coverage_score(audit_coverage_pct)
    penalty = _finding_penalty(critical_unresolved, high_unresolved)
    bounty = _bounty_score(bug_bounty_usd)
    fv_bonus = _formal_verification_bonus(formal_verification)
    overall = _overall_score(recency, quality, coverage, penalty, bounty, fv_bonus)
    grade = _security_grade(overall)
    status = _audit_status(auditor_tier, days_since, audit_coverage_pct, overall, stale_audit_days)
    flags = _build_flags(days_since, critical_unresolved, bug_bounty_usd, audit_coverage_pct, stale_audit_days)
    rec = _recommendation(grade, audit_count, audit_coverage_pct, flags)

    return {
        "name": name,
        "auditor_tier": auditor_tier,
        "audit_recency_score": recency,
        "auditor_quality_score": quality,
        "coverage_score": coverage,
        "finding_penalty": penalty,
        "bounty_score": bounty,
        "formal_verification_bonus": fv_bonus,
        "overall_score": overall,
        "security_grade": grade,
        "audit_status": status,
        "flags": flags,
        "recommendation": rec,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list[dict], config: dict | None = None) -> dict:
    """
    Score DeFi protocols on audit quality, coverage, and recency.

    Parameters
    ----------
    protocols : list of protocol dicts (see module docstring)
    config    : optional override dict; keys: stale_audit_days

    Returns
    -------
    dict with per-protocol scores and aggregates
    """
    cfg = _resolve_config(config)
    stale_audit_days = cfg["stale_audit_days"]

    scored: list[dict] = []
    for proto in protocols:
        scored.append(_score_protocol(proto, stale_audit_days))

    if scored:
        safest = max(scored, key=lambda p: p["overall_score"])["name"]
        average_score = round(
            sum(p["overall_score"] for p in scored) / len(scored), 4
        )
    else:
        safest = None
        average_score = 0.0

    unaudited_count = sum(
        1 for p in protocols if str(p.get("auditor_tier", "UNAUDITED")) == "UNAUDITED"
    )

    return {
        "protocols": scored,
        "safest_protocol": safest,
        "unaudited_count": unaudited_count,
        "average_score": average_score,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

def log_result(result: dict, data_dir: str = ".") -> None:
    """Append result snapshot to the ring-buffer JSON log (max 100 entries)."""
    log_path = os.path.join(data_dir, LOG_FILE)
    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)

    try:
        with open(log_path) as f:
            entries: list[dict] = json.load(f)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(result)
    entries = entries[-LOG_MAX:]

    atomic_save(entries, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Quick demo with sample protocols."""
    sample = [
        {
            "name": "Aave-V3",
            "audit_count": 5,
            "auditor_tier": "TOP_TIER",
            "days_since_last_audit": 45,
            "lines_of_code": 15000,
            "audit_coverage_pct": 92.0,
            "critical_findings_unresolved": 0,
            "high_findings_unresolved": 1,
            "bug_bounty_usd": 1_000_000.0,
            "formal_verification": True,
        },
        {
            "name": "NewProtocol",
            "audit_count": 0,
            "auditor_tier": "UNAUDITED",
            "days_since_last_audit": 9999,
            "lines_of_code": 5000,
            "audit_coverage_pct": 0.0,
            "critical_findings_unresolved": 0,
            "high_findings_unresolved": 0,
            "bug_bounty_usd": 0.0,
            "formal_verification": False,
        },
    ]
    result = analyze(sample)
    import json as _json
    print(_json.dumps(result, indent=2))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--run" in args:
        data_dir = "."
        if "--data-dir" in args:
            idx = args.index("--data-dir")
            data_dir = args[idx + 1]
        result = analyze([])
        log_result(result, data_dir)
        import json as _json
        print(_json.dumps(result, indent=2))
    else:
        _demo()
