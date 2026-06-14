"""
MP-894 ProtocolCommunitySentimentScorer
Advisory/read-only. Pure stdlib. Atomic writes.

Scores protocol community health using governance participation, social
engagement, and developer activity signals.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ─── constants ────────────────────────────────────────────────────────────────

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "community_sentiment_log.json"
)
_LOG_CAP = 100

_NEVER_EXPLOITED = 9999  # sentinel value in input


# ─── sub-scores ───────────────────────────────────────────────────────────────

def _governance_health_score(proposals_90d: int, voter_pct: float) -> int:
    """0-100: min(100, proposals*15 + voter_pct*2)"""
    return min(100, int(proposals_90d * 15 + voter_pct * 2))


def _social_presence_score(twitter_followers: int, engagement_rate_pct: float) -> int:
    """0-100: twitter_score (0-50) + engagement_score (0-50)"""
    twitter_score = min(50, int(twitter_followers / 10_000))
    engagement_score = min(50, int(engagement_rate_pct * 10))
    return twitter_score + engagement_score


def _developer_activity_score(github_commits_30d: int) -> int:
    """0-100: min(100, commits*3)"""
    return min(100, github_commits_30d * 3)


def _community_investment_score(grants_usd: float) -> int:
    """0-100: min(100, int(grants_usd / 100_000 * 10))"""
    return min(100, int(grants_usd / 100_000 * 10))


def _security_trust_score(days_since_exploit: int) -> int:
    """100 if never; 50 if >365d; 20 if >90d; 0 if <=90d"""
    if days_since_exploit >= _NEVER_EXPLOITED:
        return 100
    if days_since_exploit > 365:
        return 50
    if days_since_exploit > 90:
        return 20
    return 0


def _composite_score(gov: int, social: int, dev: int, invest: int, sec: int) -> int:
    raw = gov * 0.25 + social * 0.20 + dev * 0.25 + invest * 0.15 + sec * 0.15
    return max(0, min(100, int(raw)))


def _sentiment_label(score: int) -> str:
    if score >= 80:
        return "THRIVING"
    if score >= 65:
        return "HEALTHY"
    if score >= 50:
        return "STABLE"
    if score >= 35:
        return "DECLINING"
    return "AT_RISK"


def _build_flags(
    proposals_90d: int,
    engagement_rate_pct: float,
    github_commits_30d: int,
    days_since_exploit: int,
    grants_usd: float,
) -> list:
    flags = []
    if proposals_90d < 2:
        flags.append("INACTIVE_GOVERNANCE")
    if engagement_rate_pct < 0.5:
        flags.append("LOW_ENGAGEMENT")
    if github_commits_30d == 0:
        flags.append("NO_DEVELOPMENT")
    if days_since_exploit < 365:
        flags.append("RECENT_EXPLOIT")
    if grants_usd > 0:
        flags.append("GRANT_FUNDED")
    return flags


def _recommendation(
    label: str,
    github_commits_30d: int,
    voter_pct: float,
    composite: int,
    proposals_90d: int,
    engagement_rate_pct: float,
    flags: list,
) -> str:
    if label == "THRIVING":
        return (
            f"Highly active community. "
            f"{github_commits_30d} commits/mo, "
            f"{voter_pct:.0f}% voter participation."
        )
    if label == "HEALTHY":
        return (
            f"Strong community. Score: {composite}. "
            f"{proposals_90d} governance proposals."
        )
    if label == "STABLE":
        return (
            f"Adequate community. Monitor engagement "
            f"({engagement_rate_pct:.1f}% rate)."
        )
    if label == "DECLINING":
        flag_str = (
            ", ".join(flags[:2]) if flags else "low engagement"
        )
        return f"Community showing weakness. Flags: {flag_str}."
    # AT_RISK
    return (
        f"Community at risk. {len(flags)} red flags. "
        "Deep due diligence required."
    )


# ─── log ──────────────────────────────────────────────────────────────────────

def _append_log(entry: dict, log_path: str = _LOG_PATH) -> None:
    """Append entry to ring-buffer JSON log (cap=100). Atomic write."""
    try:
        abs_path = os.path.abspath(log_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        try:
            with open(abs_path) as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        existing.append(entry)
        existing = existing[-_LOG_CAP:]
        dir_ = os.path.dirname(abs_path)
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, suffix=".tmp", delete=False
        ) as tf:
            json.dump(existing, tf, indent=2)
            tmp_name = tf.name
        os.replace(tmp_name, abs_path)
    except Exception:
        pass  # advisory — never raise


# ─── core ─────────────────────────────────────────────────────────────────────

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Score protocol community health using governance, social, dev, security
    signals.

    Parameters
    ----------
    protocols : list[dict]
        Each dict has: name, governance_proposals_90d, governance_voter_participation_pct,
        discord_active_members_30d, twitter_followers, twitter_engagement_rate_pct,
        github_commits_30d, bug_reports_open, community_grants_usd, days_since_exploit.
    config : dict, optional
        Reserved for future use.

    Returns
    -------
    dict with enriched protocols list and aggregate statistics.
    """
    ts = time.time()

    if not protocols:
        result = {
            "protocols": [],
            "most_vibrant": None,
            "average_composite_score": 0.0,
            "thriving_count": 0,
            "timestamp": ts,
        }
        _append_log(result)
        return result

    enriched = []
    for p in protocols:
        name = str(p.get("name", ""))
        proposals_90d = int(p.get("governance_proposals_90d", 0))
        voter_pct = float(p.get("governance_voter_participation_pct", 0.0))
        discord = int(p.get("discord_active_members_30d", 0))
        twitter_followers = int(p.get("twitter_followers", 0))
        engagement_rate = float(p.get("twitter_engagement_rate_pct", 0.0))
        commits = int(p.get("github_commits_30d", 0))
        bug_reports = int(p.get("bug_reports_open", 0))
        grants = float(p.get("community_grants_usd", 0.0))
        days_exploit = int(p.get("days_since_exploit", _NEVER_EXPLOITED))

        gov = _governance_health_score(proposals_90d, voter_pct)
        social = _social_presence_score(twitter_followers, engagement_rate)
        dev = _developer_activity_score(commits)
        invest = _community_investment_score(grants)
        sec = _security_trust_score(days_exploit)
        composite = _composite_score(gov, social, dev, invest, sec)
        label = _sentiment_label(composite)
        flags = _build_flags(proposals_90d, engagement_rate, commits, days_exploit, grants)
        rec = _recommendation(
            label, commits, voter_pct, composite,
            proposals_90d, engagement_rate, flags
        )

        enriched.append({
            "name": name,
            "governance_health_score": gov,
            "social_presence_score": social,
            "developer_activity_score": dev,
            "community_investment_score": invest,
            "security_trust_score": sec,
            "composite_score": composite,
            "sentiment_label": label,
            "flags": flags,
            "recommendation": rec,
        })

    # aggregates
    most_vibrant_entry = max(enriched, key=lambda x: x["composite_score"])
    most_vibrant: Optional[str] = most_vibrant_entry["name"]

    avg_composite = sum(e["composite_score"] for e in enriched) / len(enriched)
    thriving_count = sum(1 for e in enriched if e["sentiment_label"] == "THRIVING")

    result = {
        "protocols": enriched,
        "most_vibrant": most_vibrant,
        "average_composite_score": avg_composite,
        "thriving_count": thriving_count,
        "timestamp": ts,
    }
    _append_log(result)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="MP-894 ProtocolCommunitySentimentScorer")
    parser.add_argument("--run", action="store_true", help="Compute + write log")
    parser.add_argument("--check", action="store_true", help="Compute only (default)")
    args = parser.parse_args()

    _sample = [
        {
            "name": "Aave",
            "governance_proposals_90d": 5,
            "governance_voter_participation_pct": 12.0,
            "discord_active_members_30d": 3000,
            "twitter_followers": 250_000,
            "twitter_engagement_rate_pct": 1.5,
            "github_commits_30d": 80,
            "bug_reports_open": 3,
            "community_grants_usd": 500_000,
            "days_since_exploit": 9999,
        },
        {
            "name": "NewProtocol",
            "governance_proposals_90d": 1,
            "governance_voter_participation_pct": 2.0,
            "discord_active_members_30d": 200,
            "twitter_followers": 5_000,
            "twitter_engagement_rate_pct": 0.3,
            "github_commits_30d": 0,
            "bug_reports_open": 10,
            "community_grants_usd": 0.0,
            "days_since_exploit": 60,
        },
    ]

    result = analyze(_sample)
    print(json.dumps(result, indent=2))
