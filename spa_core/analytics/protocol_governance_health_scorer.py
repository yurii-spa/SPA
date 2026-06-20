"""
MP-836 ProtocolGovernanceHealthScorer
Scores the governance health of DeFi protocols based on voter participation,
proposal frequency, token concentration, and governance structure.
Advisory/read-only. Pure stdlib. Atomic writes only.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Score sub-components
# ---------------------------------------------------------------------------

def _participation_score(voter_participation_pct: float) -> int:
    """0-25 points for voter participation."""
    if voter_participation_pct >= 20:
        return 25
    if voter_participation_pct >= 10:
        return 20
    if voter_participation_pct >= 5:
        return 15
    if voter_participation_pct >= 2:
        return 8
    return 2


def _activity_score(proposals_last_90d: int) -> int:
    """0-20 points for proposal activity."""
    if proposals_last_90d >= 10:
        return 20
    if proposals_last_90d >= 5:
        return 15
    if proposals_last_90d >= 2:
        return 10
    if proposals_last_90d >= 1:
        return 5
    return 0


def _decentralization_score(top10_holder_pct: float) -> int:
    """0-25 points for token distribution."""
    if top10_holder_pct <= 30:
        return 25
    if top10_holder_pct <= 50:
        return 18
    if top10_holder_pct <= 70:
        return 10
    if top10_holder_pct <= 85:
        return 5
    return 0


def _safety_score(timelock_hours: int, multisig_required: bool,
                  community_forum_active: bool) -> int:
    """0-20 points for safety structure."""
    score = 0
    if timelock_hours >= 48:
        score += 8
    elif timelock_hours >= 24:
        score += 5
    elif timelock_hours > 0:
        score += 2
    if multisig_required:
        score += 7
    if community_forum_active:
        score += 5
    return score


def _circulation_score(governance_token_circulating_pct: float) -> int:
    """0-10 points for token supply circulation."""
    if governance_token_circulating_pct >= 70:
        return 10
    if governance_token_circulating_pct >= 50:
        return 7
    if governance_token_circulating_pct >= 30:
        return 4
    return 1


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _grade(score: int) -> str:
    """Letter grade from 0-100 governance score."""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"


def _governance_label(score: int) -> str:
    """Human-readable label from score."""
    if score >= 80:
        return "EXCELLENT"
    if score >= 60:
        return "GOOD"
    if score >= 40:
        return "ADEQUATE"
    if score >= 20:
        return "WEAK"
    return "CRITICAL"


def _centralization_risk(top10_holder_pct: float) -> str:
    """Risk label from token concentration."""
    if top10_holder_pct <= 30:
        return "LOW"
    if top10_holder_pct <= 50:
        return "MEDIUM"
    if top10_holder_pct <= 70:
        return "HIGH"
    return "EXTREME"


# ---------------------------------------------------------------------------
# Flags and strengths
# ---------------------------------------------------------------------------

def _compute_flags(p: dict, min_participation: float) -> list:
    """Return list of governance concern flags."""
    flags = []
    if p["voter_participation_pct"] < min_participation:
        flags.append(f"Voter participation below {min_participation}%")
    if p["proposals_last_90d"] == 0:
        flags.append("No governance activity in 90 days")
    if p["top10_holder_pct"] > 50:
        flags.append("Top 10 wallets hold majority of governance tokens")
    if not p.get("has_timelock", False) or p.get("timelock_hours", 0) == 0:
        flags.append("No timelock on governance")
    if not p.get("multisig_required", False):
        flags.append("No multisig protection")
    if p["governance_token_circulating_pct"] < 30:
        flags.append("Token supply not widely distributed")
    return flags


def _compute_strengths(p: dict) -> list:
    """Return list of governance positive indicators."""
    strengths = []
    if p["voter_participation_pct"] >= 15:
        strengths.append("Strong voter participation")
    if p["proposals_last_90d"] >= 5:
        strengths.append("Active governance community")
    if p["top10_holder_pct"] <= 40:
        strengths.append("Decentralized token distribution")
    if p.get("timelock_hours", 0) >= 24:
        strengths.append("Timelock protection")
    if p.get("multisig_required", False):
        strengths.append("Multisig security")
    if p.get("community_forum_active", False):
        strengths.append("Active community forum")
    return strengths


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: Optional[dict] = None) -> dict:
    """
    Score governance health for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list[dict]
        Each item:
            name                              str
            voter_participation_pct           float
            proposals_last_90d                int
            top10_holder_pct                  float
            has_timelock                      bool
            timelock_hours                    int
            multisig_required                 bool
            community_forum_active            bool
            governance_token_circulating_pct  float

    config : dict, optional
        min_participation : float  default 5.0

    Returns
    -------
    dict — full result structure (see module docstring).
    """
    cfg = config or {}
    min_participation = float(cfg.get("min_participation", 5.0))

    scored = []
    for p in protocols:
        timelock_hours = int(p.get("timelock_hours", 0))
        has_timelock = bool(p.get("has_timelock", False))

        part = _participation_score(float(p["voter_participation_pct"]))
        act = _activity_score(int(p["proposals_last_90d"]))
        decent = _decentralization_score(float(p["top10_holder_pct"]))
        safety = _safety_score(
            timelock_hours,
            bool(p.get("multisig_required", False)),
            bool(p.get("community_forum_active", False)),
        )
        circ = _circulation_score(float(p["governance_token_circulating_pct"]))

        gov_score = min(100, part + act + decent + safety + circ)

        flags = _compute_flags(
            {**p, "has_timelock": has_timelock, "timelock_hours": timelock_hours},
            min_participation,
        )
        strengths = _compute_strengths(
            {**p, "timelock_hours": timelock_hours}
        )

        scored.append({
            "name": p["name"],
            "governance_score": gov_score,
            "grade": _grade(gov_score),
            "governance_label": _governance_label(gov_score),
            "centralization_risk": _centralization_risk(float(p["top10_holder_pct"])),
            "flags": flags,
            "strengths": strengths,
        })

    # ---- aggregate metrics --------------------------------------------------
    if scored:
        best = max(scored, key=lambda x: x["governance_score"])
        worst = min(scored, key=lambda x: x["governance_score"])
        best_governed = best["name"]
        worst_governed = worst["name"]
        average_score = sum(s["governance_score"] for s in scored) / len(scored)
    else:
        best_governed = None
        worst_governed = None
        average_score = 0.0

    critical_count = sum(1 for s in scored if s["governance_label"] == "CRITICAL")

    return {
        "protocols": scored,
        "best_governed": best_governed,
        "worst_governed": worst_governed,
        "average_score": round(average_score, 4),
        "critical_count": critical_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log (capped at 100 entries, atomic write)
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "governance_health_log.json"
)
LOG_PATH = os.path.normpath(LOG_PATH)
_LOG_CAP = 100


def _init_log(path: str) -> None:
    """Create log file as [] if it does not exist."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, [])


def _atomic_write(path: str, data) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def log_result(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result to ring-buffer log (max 100 entries)."""
    _init_log(log_path)
    try:
        with open(log_path) as f:
            entries = json.load(f)
    except (OSError, json.JSONDecodeError):
        entries = []
    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]
    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _init_log(LOG_PATH)

    _protocols = [
        {
            "name": "Aave",
            "voter_participation_pct": 12.0,
            "proposals_last_90d": 8,
            "top10_holder_pct": 35.0,
            "has_timelock": True,
            "timelock_hours": 48,
            "multisig_required": True,
            "community_forum_active": True,
            "governance_token_circulating_pct": 60.0,
        },
        {
            "name": "MinimalProto",
            "voter_participation_pct": 1.5,
            "proposals_last_90d": 0,
            "top10_holder_pct": 90.0,
            "has_timelock": False,
            "timelock_hours": 0,
            "multisig_required": False,
            "community_forum_active": False,
            "governance_token_circulating_pct": 10.0,
        },
    ]
    result = analyze(_protocols)
    print(json.dumps(result, indent=2))

    if "--run" in sys.argv:
        log_result(result)
        print(f"\n✅ Logged to {LOG_PATH}")
