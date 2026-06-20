"""
MP-1026: DeFiProtocolGovernanceProposalImpactScorer
Evaluates potential impact of governance proposals on DeFi protocols.
Read-only/advisory — no modifications to allocator/risk/execution.
Atomic writes to data/governance_proposal_impact_log.json (ring-buffer 100).
"""

import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "governance_proposal_impact_log.json"
)
LOG_CAP = 100

RISK_CATEGORY_SCORES: dict[str, float] = {
    "upgrade": 80.0,
    "risk_parameter": 70.0,
    "new_market": 60.0,
    "token_emission": 50.0,
    "parameter_change": 40.0,
    "treasury_spend": 40.0,
    "fee_change": 30.0,
}

IMPACT_THRESHOLDS = {
    "CRITICAL_PROPOSAL": 70.0,
    "HIGH_IMPACT": 50.0,
    "MODERATE_IMPACT": 25.0,
    "LOW_IMPACT": 10.0,
}

TVL_LARGE_THRESHOLD_USD = 100_000_000  # $100M
TVL_CRITICAL_RATIO = 0.50              # 50% of protocol TVL
PASSAGE_PROB_LIKELY = 0.70


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _logistic(x: float, k: float = 5.0) -> float:
    """Logistic sigmoid mapping real line → (0, 1)."""
    try:
        return 1.0 / (1.0 + math.exp(-k * x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _compute_passage_probability(proposal: dict) -> float:
    """
    Logistic blend of:
      - votes_for_pct  (direct signal)
      - historical_pass_rate_proposer  (proposer track record)
      - quorum_proximity  (how close to quorum)
    Result in [0, 1].
    """
    votes_for = float(proposal.get("current_votes_for_pct", 0.0))
    hist_rate = float(proposal.get("historical_pass_rate_proposer", 0.5))
    quorum_req = float(proposal.get("quorum_required_pct", 50.0))
    votes_total = votes_for + float(proposal.get("current_votes_against_pct", 0.0))

    # quorum proximity: fraction of quorum already met (capped at 1)
    quorum_prox = min(1.0, votes_total / quorum_req) if quorum_req > 0 else 0.5

    # Weighted blend of the three signals → center around 0 before logistic
    blend = (0.50 * (votes_for / 100.0) +
             0.30 * hist_rate +
             0.20 * quorum_prox)
    # Shift so 0.5 blend → p ≈ 0.5
    return round(_logistic(blend - 0.5), 4)


def _compute_tvl_impact_ratio(proposal: dict) -> float:
    """tvl_affected / protocol_tvl, capped at 1."""
    affected = float(proposal.get("tvl_affected_usd", 0.0))
    total = float(proposal.get("protocol_tvl_usd", 1.0))
    if total <= 0:
        return 0.0
    return round(min(1.0, affected / total), 4)


def _compute_urgency_score(proposal: dict) -> float:
    """
    0-100 composite urgency:
      emergency = True   → +50
      days_to_vote_end < 3 → +30
      timelock_days == 0  → +20
    """
    score = 0.0
    if proposal.get("emergency_proposal", False):
        score += 50.0
    if float(proposal.get("days_to_vote_end", 999)) < 3:
        score += 30.0
    if float(proposal.get("timelock_days", 1)) == 0:
        score += 20.0
    return _clamp(score)


def _risk_category_score(proposal: dict) -> float:
    """0-100 score per proposal_type."""
    p_type = str(proposal.get("proposal_type", "")).lower()
    return RISK_CATEGORY_SCORES.get(p_type, 40.0)


def _overall_impact_score(
    passage_prob: float,
    tvl_ratio: float,
    risk_cat: float,
) -> float:
    """
    overall_impact = passage_prob × tvl_impact_ratio × risk_category_score × 0.01
    Capped at 100.
    """
    raw = passage_prob * tvl_ratio * risk_cat
    return round(_clamp(raw), 4)


def _impact_label(impact_score: float, tvl_ratio: float,
                  proposal_type: str) -> str:
    if impact_score > IMPACT_THRESHOLDS["CRITICAL_PROPOSAL"] and tvl_ratio > TVL_CRITICAL_RATIO:
        return "CRITICAL_PROPOSAL"
    if impact_score > IMPACT_THRESHOLDS["HIGH_IMPACT"]:
        return "HIGH_IMPACT"
    if impact_score > IMPACT_THRESHOLDS["MODERATE_IMPACT"]:
        return "MODERATE_IMPACT"
    if impact_score > IMPACT_THRESHOLDS["LOW_IMPACT"]:
        return "LOW_IMPACT"
    if proposal_type == "parameter_change":
        return "ROUTINE"
    if impact_score <= IMPACT_THRESHOLDS["LOW_IMPACT"]:
        return "ROUTINE"
    return "LOW_IMPACT"


def _compute_flags(proposal: dict, passage_prob: float,
                   tvl_ratio: float, tvl_affected: float) -> list[str]:
    flags: list[str] = []
    if proposal.get("emergency_proposal", False):
        flags.append("EMERGENCY_GOVERNANCE")
    proposer = str(proposal.get("proposer_type", "")).lower()
    if proposer == "team":
        flags.append("TEAM_PROPOSAL")
    if proposer == "community":
        flags.append("COMMUNITY_DRIVEN")
    if passage_prob > PASSAGE_PROB_LIKELY:
        flags.append("LIKELY_TO_PASS")
    if tvl_affected > TVL_LARGE_THRESHOLD_USD:
        flags.append("AFFECTS_LARGE_TVL")
    p_type = str(proposal.get("proposal_type", "")).lower()
    if float(proposal.get("timelock_days", 1)) == 0 and p_type == "upgrade":
        flags.append("NO_TIMELOCK_RISK")
    return flags


def _score_single(proposal: dict) -> dict:
    """Score a single governance proposal; return enriched dict."""
    passage_prob = _compute_passage_probability(proposal)
    tvl_ratio = _compute_tvl_impact_ratio(proposal)
    urgency = _compute_urgency_score(proposal)
    risk_cat = _risk_category_score(proposal)
    impact = _overall_impact_score(passage_prob, tvl_ratio, risk_cat)
    tvl_affected = float(proposal.get("tvl_affected_usd", 0.0))
    p_type = str(proposal.get("proposal_type", "")).lower()
    label = _impact_label(impact, tvl_ratio, p_type)
    flags = _compute_flags(proposal, passage_prob, tvl_ratio, tvl_affected)
    apy_impact = proposal.get("estimated_apy_impact_bps")

    return {
        "name": proposal.get("name", ""),
        "protocol": proposal.get("protocol", ""),
        "proposal_type": p_type,
        "passage_probability": passage_prob,
        "tvl_impact_ratio": tvl_ratio,
        "urgency_score": urgency,
        "risk_category_score": risk_cat,
        "overall_impact_score": impact,
        "impact_label": label,
        "flags": flags,
        "estimated_apy_impact_bps": apy_impact,
    }


def _compute_aggregates(scored: list[dict]) -> dict:
    if not scored:
        return {
            "highest_impact": None,
            "lowest_impact": None,
            "avg_impact_score": 0.0,
            "critical_count": 0,
            "routine_count": 0,
        }
    impacts = [s["overall_impact_score"] for s in scored]
    avg = round(statistics.mean(impacts), 4)
    hi_idx = impacts.index(max(impacts))
    lo_idx = impacts.index(min(impacts))
    critical_count = sum(1 for s in scored if s["impact_label"] == "CRITICAL_PROPOSAL")
    routine_count = sum(1 for s in scored if s["impact_label"] == "ROUTINE")
    return {
        "highest_impact": {
            "name": scored[hi_idx]["name"],
            "protocol": scored[hi_idx]["protocol"],
            "overall_impact_score": scored[hi_idx]["overall_impact_score"],
            "impact_label": scored[hi_idx]["impact_label"],
        },
        "lowest_impact": {
            "name": scored[lo_idx]["name"],
            "protocol": scored[lo_idx]["protocol"],
            "overall_impact_score": scored[lo_idx]["overall_impact_score"],
            "impact_label": scored[lo_idx]["impact_label"],
        },
        "avg_impact_score": avg,
        "critical_count": critical_count,
        "routine_count": routine_count,
    }


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    atomic_save(data, str(path))
def _append_log(result: dict, log_path: str) -> None:
    """Append a log entry (ring-buffer, cap LOG_CAP)."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "proposal_count": result.get("proposal_count", 0),
        "avg_impact_score": result.get("aggregates", {}).get("avg_impact_score", 0.0),
        "critical_count": result.get("aggregates", {}).get("critical_count", 0),
        "routine_count": result.get("aggregates", {}).get("routine_count", 0),
    }
    existing.append(entry)
    # ring-buffer
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolGovernanceProposalImpactScorer:
    """
    Scores governance proposals for their potential impact on DeFi protocols.

    Input:
        proposals: list of proposal dicts (see module docstring)
        config: optional overrides {"log_path": str, "log_cap": int}

    Output:
        dict with keys:
            scored_proposals, aggregates, proposal_count, ts
    """

    def score(self, proposals: list[dict], config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(proposals, list):
            raise TypeError("proposals must be a list")

        scored = [_score_single(p) for p in proposals]
        aggregates = _compute_aggregates(scored)

        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "proposal_count": len(scored),
            "scored_proposals": scored,
            "aggregates": aggregates,
        }

        if write_log and scored:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
