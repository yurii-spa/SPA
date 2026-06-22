"""
MP-838 ProtocolSecurityAuditTracker
=====================================
Advisory-only analytics module. Pure stdlib. No external dependencies.
Tracks and scores protocol security based on audit history, audit quality,
recency, coverage, and open findings — helping identify under-audited or
high-risk protocols.

Data log: data/security_audit_log.json (ring-buffer 100 entries, atomic write)
"""

import json
import math
import time
from datetime import date, datetime
from pathlib import Path
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_STALE_AUDIT_DAYS = 365
LOG_MAX_ENTRIES = 100

# Freshness labels
FRESHNESS_FRESH = "FRESH"
FRESHNESS_RECENT = "RECENT"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNAUDITED = "UNAUDITED"

# Grade thresholds (score → grade)
GRADE_A_MIN = 80
GRADE_B_MIN = 60
GRADE_C_MIN = 40
GRADE_D_MIN = 20

# Risk labels
RISK_SAFE = "SAFE"
RISK_CAUTION = "CAUTION"
RISK_RISKY = "RISKY"
RISK_AVOID = "AVOID"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date:
    """Parse ISO date string to datetime.date."""
    return datetime.strptime(date_str[:10], "%Y-%m-%d").date()


def _days_between(d1: date, d2: date) -> int:
    """Return abs number of days between two dates."""
    return abs((d2 - d1).days)


def _get_today(config: dict) -> date:
    """Return today's date, honoring config override for testing."""
    today_str = config.get("today") if config else None
    if today_str:
        return _parse_date(today_str)
    return date.today()


def _compute_audit_volume_score(audit_count: int) -> int:
    """Return 0-20 score based on number of audits."""
    if audit_count >= 4:
        return 20
    if audit_count >= 3:
        return 15
    if audit_count >= 2:
        return 10
    if audit_count == 1:
        return 5
    return 0


def _compute_freshness(
    audits: list,
    stale_audit_days: int,
    today: date,
) -> tuple:
    """
    Return (freshness_label, freshness_score, days_since_latest).
    freshness_label: FRESH | RECENT | STALE | UNAUDITED
    freshness_score: 0-25
    days_since_latest: int or None
    """
    if not audits:
        return FRESHNESS_UNAUDITED, 0, None

    # Find the most recent audit date
    audit_dates = [_parse_date(a["date"]) for a in audits]
    latest_date = max(audit_dates)
    days_since = _days_between(latest_date, today)

    half_stale = stale_audit_days // 2
    if days_since <= half_stale:
        return FRESHNESS_FRESH, 25, days_since
    if days_since <= stale_audit_days:
        return FRESHNESS_RECENT, 15, days_since
    return FRESHNESS_STALE, 5, days_since


def _compute_coverage_score(audits: list) -> float:
    """Return 0-20 score based on mean scope_pct across all audits."""
    if not audits:
        return 0.0
    scopes = [float(a.get("scope_pct", 0.0)) for a in audits]
    mean_scope = sum(scopes) / len(scopes)
    return mean_scope * 0.20  # 100% scope → 20 pts


def _compute_open_findings(audits: list) -> tuple:
    """
    Return (open_critical_count, open_high_count) summed across all audits.
    For each audit:
      open_critical = ceil(critical_findings * (1 - resolved_pct/100))
      open_high     = ceil(high_findings * (1 - resolved_pct/100))
    """
    total_critical = 0
    total_high = 0
    for a in audits:
        critical = int(a.get("critical_findings", 0))
        high = int(a.get("high_findings", 0))
        resolved_pct = float(a.get("resolved_pct", 0.0))
        unresolved_factor = 1.0 - resolved_pct / 100.0
        total_critical += math.ceil(critical * unresolved_factor)
        total_high += math.ceil(high * unresolved_factor)
    return total_critical, total_high


def _compute_findings_penalty(open_critical: int, open_high: int) -> int:
    """Return penalty points (positive int to be subtracted from score)."""
    critical_penalty = min(open_critical * 8, 40)
    high_penalty = min(open_high * 4, 20)
    return critical_penalty + high_penalty


def _compute_bonus_score(formal_verification: bool, bug_bounty_usd: float) -> int:
    """Return 0-15 bonus points."""
    score = 0
    if formal_verification:
        score += 10
    if bug_bounty_usd >= 1_000_000:
        score += 5
    elif bug_bounty_usd >= 100_000:
        score += 3
    elif bug_bounty_usd > 0:
        score += 1
    return score


def _compute_change_penalty(days_since_major_change: int, stale_audit_days: int) -> int:
    """Return penalty points for code drift (positive int to be subtracted)."""
    if days_since_major_change > stale_audit_days * 2:
        return 10
    if days_since_major_change > stale_audit_days:
        return 5
    return 0


def _score_to_grade(score: int) -> str:
    """Convert security score 0-100 to letter grade."""
    if score >= GRADE_A_MIN:
        return "A"
    if score >= GRADE_B_MIN:
        return "B"
    if score >= GRADE_C_MIN:
        return "C"
    if score >= GRADE_D_MIN:
        return "D"
    return "F"


def _grade_to_risk(grade: str) -> str:
    """Map grade to risk label."""
    if grade in ("A", "B"):
        return RISK_SAFE
    if grade == "C":
        return RISK_CAUTION
    if grade == "D":
        return RISK_RISKY
    return RISK_AVOID  # F


def _compute_flags(
    audit_count: int,
    freshness: str,
    open_critical: int,
    open_high: int,
    bug_bounty_usd: float,
    days_since_major_change: int,
    stale_audit_days: int,
) -> list:
    """Return list of flag strings for a protocol."""
    flags = []
    if audit_count == 0:
        flags.append("No security audits")
    if freshness == FRESHNESS_STALE:
        flags.append("Audit is stale — code may have changed significantly")
    if open_critical > 0:
        flags.append(f"{open_critical} unresolved critical finding(s)")
    if open_high > 0:
        flags.append(f"{open_high} unresolved high-severity finding(s)")
    if bug_bounty_usd == 0:
        flags.append("No bug bounty program")
    if days_since_major_change > stale_audit_days:
        flags.append("Major code changes since last audit")
    return flags


# ---------------------------------------------------------------------------
# Per-protocol analysis
# ---------------------------------------------------------------------------

def _analyze_protocol(protocol: dict, stale_audit_days: int, today: date) -> dict:
    """Analyze a single protocol and return its security assessment dict."""
    name = protocol.get("name", "")
    audits = protocol.get("audits", [])
    days_since_major_change = int(protocol.get("days_since_major_change", 0))
    bug_bounty_usd = float(protocol.get("bug_bounty_usd", 0.0))
    formal_verification = bool(protocol.get("formal_verification", False))

    audit_count = len(audits)

    # Component scores
    volume_score = _compute_audit_volume_score(audit_count)
    freshness_label, freshness_score, days_since_latest = _compute_freshness(
        audits, stale_audit_days, today
    )
    coverage_score = _compute_coverage_score(audits)
    open_critical, open_high = _compute_open_findings(audits)
    findings_penalty = _compute_findings_penalty(open_critical, open_high)
    bonus_score = _compute_bonus_score(formal_verification, bug_bounty_usd)
    change_penalty = _compute_change_penalty(days_since_major_change, stale_audit_days)

    raw_score = (
        volume_score
        + freshness_score
        + coverage_score
        + bonus_score
        - findings_penalty
        - change_penalty
    )
    security_score = max(0, min(100, int(raw_score)))

    grade = _score_to_grade(security_score)
    risk_label = _grade_to_risk(grade)

    flags = _compute_flags(
        audit_count,
        freshness_label,
        open_critical,
        open_high,
        bug_bounty_usd,
        days_since_major_change,
        stale_audit_days,
    )

    return {
        "name": name,
        "audit_count": audit_count,
        "security_score": security_score,
        "security_grade": grade,
        "audit_freshness": freshness_label,
        "open_critical_count": open_critical,
        "open_high_count": open_high,
        "risk_label": risk_label,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze a list of protocols and return security audit assessment.

    Parameters
    ----------
    protocols : list[dict]
        Each item contains: name, audits, days_since_major_change,
        bug_bounty_usd, formal_verification
    config : dict, optional
        stale_audit_days (default 365)
        today (ISO date string, for testing)

    Returns
    -------
    dict with keys: protocols, best_security, riskiest_protocol,
                    unaudited_count, avoid_count, average_security_score,
                    timestamp
    """
    if config is None:
        config = {}

    stale_audit_days = int(config.get("stale_audit_days", DEFAULT_STALE_AUDIT_DAYS))
    today = _get_today(config)

    if not protocols:
        return {
            "protocols": [],
            "best_security": None,
            "riskiest_protocol": None,
            "unaudited_count": 0,
            "avoid_count": 0,
            "average_security_score": 0.0,
            "timestamp": time.time(),
        }

    assessed = [
        _analyze_protocol(p, stale_audit_days, today)
        for p in protocols
    ]

    scores = [p["security_score"] for p in assessed]
    average_security_score = sum(scores) / len(scores) if scores else 0.0

    best = max(assessed, key=lambda p: p["security_score"])
    best_security = best["name"]

    worst = min(assessed, key=lambda p: p["security_score"])
    riskiest_protocol = worst["name"]

    unaudited_count = sum(1 for p in assessed if p["audit_freshness"] == FRESHNESS_UNAUDITED)
    avoid_count = sum(1 for p in assessed if p["risk_label"] == RISK_AVOID)

    return {
        "protocols": assessed,
        "best_security": best_security,
        "riskiest_protocol": riskiest_protocol,
        "unaudited_count": unaudited_count,
        "avoid_count": avoid_count,
        "average_security_score": average_security_score,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100, atomic write)
# ---------------------------------------------------------------------------

def _get_log_path() -> Path:
    """Resolve path to security_audit_log.json relative to repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "security_audit_log.json"
        if candidate.parent.exists():
            return candidate
    return Path("data") / "security_audit_log.json"


def append_log(result: dict, log_path: Path = None) -> None:
    """
    Append an analysis result to the ring-buffer log (max 100 entries).
    Uses atomic write: tmp file + os.replace.
    """
    if log_path is None:
        log_path = _get_log_path()

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(result)
    if len(existing) > LOG_MAX_ENTRIES:
        existing = existing[-LOG_MAX_ENTRIES:]

    atomic_save(existing, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _sample_protocols() -> list:
    return [
        {
            "name": "Aave V3",
            "audits": [
                {"auditor": "Trail of Bits", "date": "2024-03-01",
                 "scope_pct": 95.0, "critical_findings": 0, "high_findings": 2,
                 "resolved_pct": 100.0},
                {"auditor": "ConsenSys Diligence", "date": "2024-06-15",
                 "scope_pct": 90.0, "critical_findings": 0, "high_findings": 1,
                 "resolved_pct": 100.0},
                {"auditor": "Certik", "date": "2025-01-10",
                 "scope_pct": 85.0, "critical_findings": 0, "high_findings": 0,
                 "resolved_pct": 100.0},
            ],
            "days_since_major_change": 90,
            "bug_bounty_usd": 2_000_000.0,
            "formal_verification": True,
        },
        {
            "name": "NewProtocol",
            "audits": [],
            "days_since_major_change": 30,
            "bug_bounty_usd": 0.0,
            "formal_verification": False,
        },
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-838 ProtocolSecurityAuditTracker")
    parser.add_argument("--check", action="store_true", help="Run analysis (no write)")
    parser.add_argument("--run", action="store_true", help="Run analysis + write log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    protos = _sample_protocols()
    result = analyze(protos)

    print(json.dumps(result, indent=2))

    if args.run:
        log_path = None
        if args.data_dir:
            log_path = Path(args.data_dir) / "security_audit_log.json"
        append_log(result, log_path)
        print("\n✅ Log written.")
