"""
MP-860: ProtocolDeveloperActivityTracker

Tracks protocol developer health and ongoing maintenance signals:
commit frequency, active contributors, issue resolution, time since last update.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/developer_activity_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data/developer_activity_log.json")
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def _commit_momentum_score(commits_last_30d: int) -> int:
    """0-30: based on commits in last 30 days."""
    if commits_last_30d >= 50:
        return 30
    elif commits_last_30d >= 20:
        return 25
    elif commits_last_30d >= 10:
        return 20
    elif commits_last_30d >= 5:
        return 15
    elif commits_last_30d >= 1:
        return 8
    return 0


def _team_health_score(active_contributors_30d: int, total_contributors: int) -> int:
    """0-25: based on active contributors count and active ratio."""
    if active_contributors_30d >= 10:
        base = 15
    elif active_contributors_30d >= 5:
        base = 12
    elif active_contributors_30d >= 3:
        base = 8
    elif active_contributors_30d >= 2:
        base = 5
    elif active_contributors_30d == 1:
        base = 3
    else:
        base = 0

    # Concentration bonus
    if total_contributors > 0:
        concentration = active_contributors_30d / total_contributors
    else:
        concentration = 0.0

    if concentration >= 0.5:
        bonus = 5
    elif concentration >= 0.2:
        bonus = 3
    else:
        bonus = 0

    return min(25, base + bonus)


def _maintenance_score(days_since_last_commit: int, days_since_last_release: int) -> int:
    """0-25: based on recency of last commit and last release."""
    if days_since_last_commit <= 7:
        commit_score = 15
    elif days_since_last_commit <= 30:
        commit_score = 12
    elif days_since_last_commit <= 90:
        commit_score = 8
    elif days_since_last_commit <= 180:
        commit_score = 4
    else:
        commit_score = 0

    if days_since_last_release <= 30:
        release_score = 10
    elif days_since_last_release <= 90:
        release_score = 7
    elif days_since_last_release <= 180:
        release_score = 5
    elif days_since_last_release <= 365:
        release_score = 3
    else:
        release_score = 0

    return min(25, commit_score + release_score)


def _security_investment_score(has_bug_bounty: bool, bug_bounty_usd: float) -> int:
    """0-20: based on existence and size of bug bounty."""
    if not has_bug_bounty:
        return 0

    base = 10  # has_bug_bounty = True

    if bug_bounty_usd >= 1_000_000:
        bounty_score = 10
    elif bug_bounty_usd >= 500_000:
        bounty_score = 7
    elif bug_bounty_usd >= 100_000:
        bounty_score = 5
    elif bug_bounty_usd >= 10_000:
        bounty_score = 3
    elif bug_bounty_usd > 0:
        bounty_score = 1
    else:
        bounty_score = 0

    return min(20, base + bounty_score)


def _activity_level(activity_score: int) -> str:
    if activity_score >= 80:
        return "VERY_ACTIVE"
    elif activity_score >= 60:
        return "ACTIVE"
    elif activity_score >= 40:
        return "MODERATE"
    elif activity_score >= 20:
        return "LOW"
    return "INACTIVE"


def _velocity_trend(commits_last_30d: int, commits_last_90d: int) -> str:
    """Derive velocity trend from 30d vs 90d commit counts."""
    if commits_last_30d == 0:
        return "STAGNANT"
    # 30d pace vs 30d average over 90d window
    avg_30d_pace = commits_last_90d / 3.0 if commits_last_90d > 0 else 0.0
    if commits_last_30d > avg_30d_pace * 1.5:
        return "ACCELERATING"
    if commits_last_90d > 0 and commits_last_30d < avg_30d_pace * 0.5:
        return "DECELERATING"
    return "STABLE"


def _issue_resolution_rate(closed_issues_30d: int, open_issues: int) -> float:
    if open_issues > 0:
        return closed_issues_30d / open_issues
    return 1.0


def _summary(
    activity_level: str,
    active_contributors_30d: int,
    commits_last_30d: int,
    days_since_last_commit: int,
    days_since_last_release: int,
) -> str:
    if activity_level == "VERY_ACTIVE":
        return (
            f"Highly active team with {active_contributors_30d} contributors, "
            f"{commits_last_30d} commits in 30d."
        )
    elif activity_level == "ACTIVE":
        return (
            f"Active development. {commits_last_30d} commits, "
            f"{days_since_last_commit}d since last commit."
        )
    elif activity_level == "MODERATE":
        return f"Moderate activity. {days_since_last_release}d since last release."
    elif activity_level == "LOW":
        return f"Low development activity. Only {commits_last_30d} commits in 30 days."
    return f"Protocol appears inactive. {days_since_last_commit} days since last commit."


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze developer activity health for a list of protocols.

    Parameters
    ----------
    protocols : list of dict with keys:
        name, commits_last_30d, commits_last_90d, active_contributors_30d,
        total_contributors, open_issues, closed_issues_30d,
        days_since_last_commit, days_since_last_release,
        has_bug_bounty, bug_bounty_usd
    config : optional (unused for now, reserved for future)

    Returns
    -------
    dict with keys: protocols, most_active, least_active, inactive_protocols,
                    average_activity_score, timestamp
    """
    results = []

    for proto in protocols:
        name = proto.get("name", "UNKNOWN")
        commits_30d = int(proto.get("commits_last_30d", 0))
        commits_90d = int(proto.get("commits_last_90d", 0))
        active_contributors = int(proto.get("active_contributors_30d", 0))
        total_contributors = int(proto.get("total_contributors", 0))
        open_issues = int(proto.get("open_issues", 0))
        closed_30d = int(proto.get("closed_issues_30d", 0))
        days_last_commit = int(proto.get("days_since_last_commit", 0))
        days_last_release = int(proto.get("days_since_last_release", 0))
        has_bug_bounty = bool(proto.get("has_bug_bounty", False))
        bug_bounty_usd = float(proto.get("bug_bounty_usd", 0.0))

        cms = _commit_momentum_score(commits_30d)
        ths = _team_health_score(active_contributors, total_contributors)
        ms = _maintenance_score(days_last_commit, days_last_release)
        sis = _security_investment_score(has_bug_bounty, bug_bounty_usd)

        activity_score = min(100, cms + ths + ms + sis)
        al = _activity_level(activity_score)
        vt = _velocity_trend(commits_30d, commits_90d)
        irr = _issue_resolution_rate(closed_30d, open_issues)
        summ = _summary(al, active_contributors, commits_30d, days_last_commit, days_last_release)

        results.append({
            "name": name,
            "activity_score": activity_score,
            "activity_level": al,
            "commit_momentum_score": cms,
            "team_health_score": ths,
            "maintenance_score": ms,
            "security_investment_score": sis,
            "velocity_trend": vt,
            "issue_resolution_rate": irr,
            "summary": summ,
        })

    # Aggregate
    most_active: Optional[str] = None
    least_active: Optional[str] = None
    inactive_protocols: list = []
    average_activity_score = 0.0

    if results:
        most_active = max(results, key=lambda r: r["activity_score"])["name"]
        least_active = min(results, key=lambda r: r["activity_score"])["name"]
        inactive_protocols = [r["name"] for r in results if r["activity_level"] == "INACTIVE"]
        average_activity_score = sum(r["activity_score"] for r in results) / len(results)

    output = {
        "protocols": results,
        "most_active": most_active,
        "least_active": least_active,
        "inactive_protocols": inactive_protocols,
        "average_activity_score": average_activity_score,
        "timestamp": time.time(),
    }

    _append_log(output)
    return output


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Atomically append entry to DATA_FILE, capped at MAX_ENTRIES."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing: list = []
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    demo = [
        {
            "name": "Aave",
            "commits_last_30d": 45,
            "commits_last_90d": 120,
            "active_contributors_30d": 12,
            "total_contributors": 80,
            "open_issues": 30,
            "closed_issues_30d": 25,
            "days_since_last_commit": 2,
            "days_since_last_release": 15,
            "has_bug_bounty": True,
            "bug_bounty_usd": 2_000_000,
        },
        {
            "name": "OldProtocol",
            "commits_last_30d": 0,
            "commits_last_90d": 2,
            "active_contributors_30d": 0,
            "total_contributors": 5,
            "open_issues": 100,
            "closed_issues_30d": 1,
            "days_since_last_commit": 300,
            "days_since_last_release": 500,
            "has_bug_bounty": False,
            "bug_bounty_usd": 0.0,
        },
    ]
    result = analyze(demo)
    print(_json.dumps(result, indent=2))
