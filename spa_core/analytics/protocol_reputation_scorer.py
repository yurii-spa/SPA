"""
MP-850 ProtocolReputationScorer
Scores DeFi protocol reputation by aggregating signals across age, incident
history, team transparency, code quality, institutional backing, and community trust.

Pure stdlib, read-only/advisory, atomic ring-buffer log (100 entries).
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "reputation_log.json"
)
RING_BUFFER_MAX = 100

DEFAULT_MIN_AGE_MONTHS = 6

# Grade / label thresholds
_GRADE_THRESHOLDS = [
    (80, "A", "ELITE"),
    (60, "B", "TRUSTED"),
    (40, "C", "ESTABLISHED"),
    (20, "D", "EMERGING"),
    (0,  "F", "RISKY"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_data_path(data_dir: str | None = None) -> str:
    if data_dir is not None:
        return os.path.join(data_dir, "reputation_log.json")
    return DATA_FILE


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(path: str, entries: list) -> None:
    """Atomically write ring-buffer log capped at RING_BUFFER_MAX."""
    capped = entries[-RING_BUFFER_MAX:]
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    atomic_save(capped, str(path))
def _compute_hack_ratio(total_hacks_usd: float, tvl_peak_usd: float) -> float:
    """Hack ratio = total_hacks / tvl_peak. Edge: peak=0 → 1.0 if hacked else 0.0."""
    if tvl_peak_usd > 0:
        return total_hacks_usd / tvl_peak_usd
    return 1.0 if total_hacks_usd > 0 else 0.0


def _age_score(age_months: int) -> int:
    """Age score 0–20."""
    if age_months >= 36:
        return 20
    if age_months >= 24:
        return 16
    if age_months >= 12:
        return 12
    if age_months >= 6:
        return 6
    return 0


def _hack_penalty(hack_ratio: float, total_hacks_usd: float) -> int:
    """Hack penalty (negative, subtracted from score)."""
    if hack_ratio >= 0.5:
        return -30
    if hack_ratio >= 0.2:
        return -20
    if hack_ratio >= 0.05:
        return -10
    if hack_ratio >= 0.01:
        return -5
    if total_hacks_usd > 0:
        return -2
    return 0


def _transparency_score(
    team_doxxed: bool,
    open_source: bool,
    has_code_of_conduct: bool,
) -> int:
    """Transparency score 0–20."""
    score = 0
    if team_doxxed:
        score += 8
    if open_source:
        score += 7
    if has_code_of_conduct:
        score += 5
    return score


def _quality_score(audit_count: int) -> int:
    """Quality / audit score 0–20."""
    if audit_count >= 4:
        return 20
    if audit_count >= 3:
        return 15
    if audit_count >= 2:
        return 10
    if audit_count >= 1:
        return 5
    return 0


def _backing_score(institutional_backers: int) -> int:
    """Institutional backing score 0–15."""
    if institutional_backers >= 5:
        return 15
    if institutional_backers >= 3:
        return 10
    if institutional_backers >= 1:
        return 5
    return 0


def _community_score(twitter_followers: int, github_stars: int) -> int:
    """Community score 0–10 (capped)."""
    twitter_pts = 0
    if twitter_followers >= 100_000:
        twitter_pts = 6
    elif twitter_followers >= 10_000:
        twitter_pts = 4
    elif twitter_followers >= 1_000:
        twitter_pts = 2

    github_pts = 0
    if github_stars >= 1_000:
        github_pts = 4
    elif github_stars >= 200:
        github_pts = 2

    return min(10, twitter_pts + github_pts)


def _bonus_score(has_bug_bounty: bool, regulatory_issues: int) -> int:
    """Bonus score 0–5."""
    score = 0
    if has_bug_bounty:
        score += 3
    if regulatory_issues == 0:
        score += 2
    return score


def _regulatory_penalty(regulatory_issues: int) -> int:
    """Regulatory penalty (negative, capped at -15)."""
    return max(-15, -5 * regulatory_issues)


def _grade_and_label(score: int) -> tuple[str, str, str]:
    """Return (grade, label, reputation_label) for a score 0–100."""
    for threshold, grade, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade, label
    return "F", "RISKY"


def _trust_factors(protocol: dict) -> list[str]:
    """Build list of positive trust signals."""
    factors = []
    age = protocol.get("age_months", 0)
    hacks = protocol.get("total_hacks_usd", 0.0)
    open_src = protocol.get("open_source", False)
    doxxed = protocol.get("team_doxxed", False)
    audits = protocol.get("audit_count", 0)
    backers = protocol.get("institutional_backers", 0)
    bug_bounty = protocol.get("has_bug_bounty", False)
    twitter = protocol.get("twitter_followers", 0)
    stars = protocol.get("github_stars", 0)

    if age >= 24:
        factors.append("Long track record")
    if hacks == 0:
        factors.append("No security incidents")
    if open_src:
        factors.append("Fully open source")
    if doxxed:
        factors.append("Doxxed team")
    if audits >= 2:
        factors.append(f"{audits} security audits")
    if backers >= 3:
        factors.append("Strong institutional backing")
    if bug_bounty:
        factors.append("Active bug bounty")
    if twitter >= 50_000 or stars >= 500:
        factors.append("Large community")

    return factors


def _risk_factors(protocol: dict, min_age_months: int) -> list[str]:
    """Build list of negative risk signals."""
    factors = []
    age = protocol.get("age_months", 0)
    hacks = protocol.get("total_hacks_usd", 0.0)
    open_src = protocol.get("open_source", False)
    doxxed = protocol.get("team_doxxed", False)
    audits = protocol.get("audit_count", 0)
    bug_bounty = protocol.get("has_bug_bounty", False)
    reg_issues = protocol.get("regulatory_issues", 0)

    if age < min_age_months:
        factors.append("Protocol is less than 6 months old")
    if hacks > 0:
        factors.append(f"${hacks / 1e6:.1f}M lost in security incidents")
    if not open_src:
        factors.append("Closed source code")
    if not doxxed:
        factors.append("Anonymous team")
    if audits == 0:
        factors.append("No security audits")
    if not bug_bounty:
        factors.append("No bug bounty program")
    if reg_issues > 0:
        factors.append(f"{reg_issues} regulatory action(s)")

    return factors


def _score_protocol(protocol: dict, min_age_months: int) -> dict:
    """Compute reputation score and all derived fields for one protocol."""
    name = protocol.get("name", "unknown")
    age = protocol.get("age_months", 0)
    hacks = protocol.get("total_hacks_usd", 0.0)
    tvl_peak = protocol.get("tvl_peak_usd", 0.0)
    doxxed = protocol.get("team_doxxed", False)
    coc = protocol.get("has_code_of_conduct", False)
    open_src = protocol.get("open_source", False)
    audits = protocol.get("audit_count", 0)
    backers = protocol.get("institutional_backers", 0)
    twitter = protocol.get("twitter_followers", 0)
    stars = protocol.get("github_stars", 0)
    bug_bounty = protocol.get("has_bug_bounty", False)
    reg_issues = protocol.get("regulatory_issues", 0)

    hack_ratio = _compute_hack_ratio(hacks, tvl_peak)

    age_s = _age_score(age)
    hack_p = _hack_penalty(hack_ratio, hacks)
    trans_s = _transparency_score(doxxed, open_src, coc)
    qual_s = _quality_score(audits)
    back_s = _backing_score(backers)
    comm_s = _community_score(twitter, stars)
    bonus_s = _bonus_score(bug_bounty, reg_issues)
    reg_p = _regulatory_penalty(reg_issues)

    raw = age_s + hack_p + trans_s + qual_s + back_s + comm_s + bonus_s + reg_p
    reputation_score = max(0, min(100, raw))

    grade, label = _grade_and_label(reputation_score)

    return {
        "name": name,
        "reputation_score": reputation_score,
        "reputation_grade": grade,
        "reputation_label": label,
        "trust_factors": _trust_factors(protocol),
        "risk_factors": _risk_factors(protocol, min_age_months),
        "hack_ratio": round(hack_ratio, 6),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    protocols: list[dict],
    config: dict | None = None,
    _data_dir: str | None = None,
) -> dict:
    """
    Score DeFi protocol reputation across multiple signals.

    Parameters
    ----------
    protocols : list[dict]
        Each item contains protocol metadata (see module docstring).
    config : dict | None
        Optional: {"min_age_months": int}  (default 6)

    Returns
    -------
    dict with keys: protocols, most_reputable, least_reputable,
                    elite_count, risky_count, average_score, timestamp
    """
    if config is None:
        config = {}

    min_age = int(config.get("min_age_months", DEFAULT_MIN_AGE_MONTHS))

    scored: list[dict] = [_score_protocol(p, min_age) for p in protocols]

    # Aggregate statistics
    if scored:
        scores = [s["reputation_score"] for s in scored]
        most_reputable = scored[scores.index(max(scores))]["name"]
        least_reputable = scored[scores.index(min(scores))]["name"]
        average_score = round(sum(scores) / len(scores), 4)
    else:
        most_reputable = None
        least_reputable = None
        average_score = 0.0

    elite_count = sum(1 for s in scored if s["reputation_label"] == "ELITE")
    risky_count = sum(1 for s in scored if s["reputation_label"] == "RISKY")

    ts = time.time()
    result = {
        "protocols": scored,
        "most_reputable": most_reputable,
        "least_reputable": least_reputable,
        "elite_count": elite_count,
        "risky_count": risky_count,
        "average_score": average_score,
        "timestamp": ts,
    }

    # Persist to ring-buffer log
    log_path = _get_data_path(_data_dir)
    try:
        entries = _load_log(log_path)
        entries.append(result)
        _save_log(log_path, entries)
    except Exception:
        pass  # advisory — never crash caller

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MP-850 ProtocolReputationScorer")
    parser.add_argument("--check", action="store_true", help="Run on sample protocols")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    sample = [
        {
            "name": "Aave V3",
            "age_months": 36,
            "total_hacks_usd": 0.0,
            "tvl_peak_usd": 10_000_000_000.0,
            "team_doxxed": True,
            "has_code_of_conduct": True,
            "open_source": True,
            "audit_count": 5,
            "institutional_backers": 8,
            "twitter_followers": 500_000,
            "github_stars": 4_000,
            "has_bug_bounty": True,
            "regulatory_issues": 0,
        },
        {
            "name": "NewProtocol",
            "age_months": 2,
            "total_hacks_usd": 5_000_000.0,
            "tvl_peak_usd": 10_000_000.0,
            "team_doxxed": False,
            "has_code_of_conduct": False,
            "open_source": False,
            "audit_count": 0,
            "institutional_backers": 0,
            "twitter_followers": 500,
            "github_stars": 50,
            "has_bug_bounty": False,
            "regulatory_issues": 2,
        },
    ]

    out = analyze(sample, _data_dir=args.data_dir)
    print(json.dumps(out, indent=2))
    sys.exit(0)
