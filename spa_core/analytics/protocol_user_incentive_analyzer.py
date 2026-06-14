"""
MP-921 ProtocolUserIncentiveAnalyzer
=====================================
Advisory-only, read-only analytics module.
Analyzes the effectiveness of user incentive programs in DeFi protocols.

Input per incentive program:
  protocol, program_type (liquidity_mining/referral/points/airdrop/staking_rewards),
  monthly_cost_usd, monthly_new_users, monthly_tvl_added_usd,
  retention_after_program_pct (% users staying after incentives end),
  duration_months, token_price_change_during_pct

Computes per program:
  - cost_per_user_usd          : monthly_cost / monthly_new_users
  - cost_per_tvl_usd           : monthly_cost / monthly_tvl_added
  - roi_score          (0-100) : TVL added vs cost; at 10x cost -> 100
  - efficiency_score   (0-100) : ROI weighted by retention
  - mercenary_capital_risk (0-100): inverse of retention
  - efficiency_label: EXCELLENT / GOOD / FAIR / POOR / WASTEFUL
  - flags: MERCENARY_CAPITAL, HIGH_COST_PER_USER, TVL_FARMING,
           TOKEN_DUMP, EFFECTIVE_RETENTION

Aggregates:
  most_efficient, least_efficient, total_monthly_cost_usd,
  average_retention, excellent_count, total_count

Output file: data/user_incentive_log.json (ring-buffer, cap 100)
Pure Python stdlib only. Atomic writes (tmp + os.replace).
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_CAP = 100
DEFAULT_LOG_PATH = "data/user_incentive_log.json"

VALID_PROGRAM_TYPES = frozenset({
    "liquidity_mining", "referral", "points", "airdrop", "staking_rewards",
})

EFFICIENCY_THRESHOLDS = [
    (80.0, "EXCELLENT"),
    (60.0, "GOOD"),
    (40.0, "FAIR"),
    (20.0, "POOR"),
]

# Flag thresholds
MERCENARY_CAPITAL_RETENTION_THRESHOLD = 20.0    # %
HIGH_COST_PER_USER_THRESHOLD          = 1000.0  # USD
TVL_FARMING_TVL_PER_USER_THRESHOLD    = 10_000.0  # USD TVL per user
TVL_FARMING_MAX_USERS                 = 100     # max users to still flag
TOKEN_DUMP_THRESHOLD                  = -30.0   # %
EFFECTIVE_RETENTION_THRESHOLD         = 60.0    # %

# ROI score is 100 when tvl_added = ROI_FULL_MULTIPLE * cost
ROI_FULL_MULTIPLE = 10.0


# ---------------------------------------------------------------------------
# Core helper functions
# ---------------------------------------------------------------------------

def _cost_per_user_usd(monthly_cost_usd: float, monthly_new_users: int) -> float:
    """Cost per new user. Returns inf when users=0 and cost>0."""
    if monthly_new_users <= 0:
        return float("inf") if monthly_cost_usd > 0 else 0.0
    return monthly_cost_usd / monthly_new_users


def _cost_per_tvl_usd(monthly_cost_usd: float, monthly_tvl_added_usd: float) -> float:
    """Cost per USD of TVL added. Returns inf when tvl=0 and cost>0."""
    if monthly_tvl_added_usd <= 0:
        return float("inf") if monthly_cost_usd > 0 else 0.0
    return monthly_cost_usd / monthly_tvl_added_usd


def _roi_score(monthly_tvl_added_usd: float, monthly_cost_usd: float) -> float:
    """
    ROI score 0-100.
    ratio = tvl_added / cost
    score = min(100, ratio / ROI_FULL_MULTIPLE * 100)
    At ratio = 10 -> score = 100.
    """
    if monthly_cost_usd <= 0:
        return 100.0 if monthly_tvl_added_usd > 0 else 0.0
    ratio = monthly_tvl_added_usd / monthly_cost_usd
    return max(0.0, min(100.0, ratio / ROI_FULL_MULTIPLE * 100.0))


def _efficiency_score(roi: float, retention_pct: float) -> float:
    """
    Efficiency score 0-100.
    efficiency = roi * 0.60 + retention_pct * 0.40
    """
    return max(0.0, min(100.0, roi * 0.60 + retention_pct * 0.40))


def _mercenary_capital_risk(retention_pct: float) -> float:
    """
    Mercenary capital risk 0-100.
    risk = 100 - retention_pct
    High risk when retention is low.
    """
    return max(0.0, min(100.0, 100.0 - retention_pct))


def _efficiency_label(efficiency: float) -> str:
    """Map efficiency score to label."""
    for threshold, label in EFFICIENCY_THRESHOLDS:
        if efficiency >= threshold:
            return label
    return "WASTEFUL"


def _compute_flags(
    retention_after_program_pct: float,
    cost_per_user: float,
    monthly_tvl_added_usd: float,
    monthly_new_users: int,
    token_price_change_during_pct: float,
) -> list:
    """Return list of applicable flag strings."""
    flags = []

    if retention_after_program_pct < MERCENARY_CAPITAL_RETENTION_THRESHOLD:
        flags.append("MERCENARY_CAPITAL")

    if cost_per_user != float("inf") and cost_per_user > HIGH_COST_PER_USER_THRESHOLD:
        flags.append("HIGH_COST_PER_USER")
    elif cost_per_user == float("inf"):
        # infinite cost per user -> also flag
        flags.append("HIGH_COST_PER_USER")

    tvl_per_user = monthly_tvl_added_usd / max(monthly_new_users, 1)
    if (
        tvl_per_user > TVL_FARMING_TVL_PER_USER_THRESHOLD
        and monthly_new_users < TVL_FARMING_MAX_USERS
    ):
        flags.append("TVL_FARMING")

    if token_price_change_during_pct < TOKEN_DUMP_THRESHOLD:
        flags.append("TOKEN_DUMP")

    if retention_after_program_pct > EFFECTIVE_RETENTION_THRESHOLD:
        flags.append("EFFECTIVE_RETENTION")

    return flags


# ---------------------------------------------------------------------------
# Per-program analysis
# ---------------------------------------------------------------------------

def _analyze_single(program: dict, config: dict) -> dict:
    """Analyze a single incentive program dict. Returns enriched result dict."""
    protocol                     = str(program.get("protocol",                    "UNKNOWN"))
    program_type                 = str(program.get("program_type",                "unknown"))
    monthly_cost_usd             = float(program.get("monthly_cost_usd",          0.0))
    monthly_new_users            = int(program.get("monthly_new_users",           0))
    monthly_tvl_added_usd        = float(program.get("monthly_tvl_added_usd",     0.0))
    retention_after_program_pct  = float(program.get("retention_after_program_pct", 0.0))
    duration_months              = int(program.get("duration_months",             1))
    token_price_change_during_pct = float(program.get("token_price_change_during_pct", 0.0))

    cpu     = _cost_per_user_usd(monthly_cost_usd, monthly_new_users)
    cpt     = _cost_per_tvl_usd(monthly_cost_usd, monthly_tvl_added_usd)
    roi     = _roi_score(monthly_tvl_added_usd, monthly_cost_usd)
    eff     = _efficiency_score(roi, retention_after_program_pct)
    mc_risk = _mercenary_capital_risk(retention_after_program_pct)
    label   = _efficiency_label(eff)
    flags   = _compute_flags(
        retention_after_program_pct,
        cpu,
        monthly_tvl_added_usd,
        monthly_new_users,
        token_price_change_during_pct,
    )

    # Serialise inf as None for JSON compatibility
    def _safe(v: float):
        return None if v == float("inf") or v == float("-inf") else round(v, 4)

    return {
        "protocol":                      protocol,
        "program_type":                  program_type,
        "monthly_cost_usd":              monthly_cost_usd,
        "monthly_new_users":             monthly_new_users,
        "monthly_tvl_added_usd":         monthly_tvl_added_usd,
        "retention_after_program_pct":   retention_after_program_pct,
        "duration_months":               duration_months,
        "token_price_change_during_pct": token_price_change_during_pct,
        "cost_per_user_usd":             _safe(cpu),
        "cost_per_tvl_usd":              round(cpt, 6) if cpt not in (float("inf"), float("-inf")) else None,
        "roi_score":                     round(roi, 4),
        "efficiency_score":              round(eff, 4),
        "mercenary_capital_risk":        round(mc_risk, 4),
        "efficiency_label":              label,
        "flags":                         flags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(incentive_programs: list, config: dict) -> dict:
    """
    Analyze a list of incentive program dicts.

    Returns:
        dict with keys:
            analyses   – list of per-program result dicts
            aggregate  – summary stats
            timestamp  – Unix time of analysis
    """
    if not incentive_programs:
        return {
            "analyses": [],
            "aggregate": {
                "most_efficient":       None,
                "least_efficient":      None,
                "total_monthly_cost_usd": 0.0,
                "average_retention":    0.0,
                "excellent_count":      0,
                "total_count":          0,
            },
            "timestamp": time.time(),
        }

    analyses = [_analyze_single(p, config) for p in incentive_programs]
    scores = [a["efficiency_score"] for a in analyses]

    best_idx  = scores.index(max(scores))
    worst_idx = scores.index(min(scores))

    total_cost    = sum(a["monthly_cost_usd"] for a in analyses)
    avg_retention = sum(a["retention_after_program_pct"] for a in analyses) / len(analyses)
    excellent_count = sum(1 for a in analyses if a["efficiency_label"] == "EXCELLENT")

    return {
        "analyses": analyses,
        "aggregate": {
            "most_efficient":         analyses[best_idx]["protocol"],
            "least_efficient":        analyses[worst_idx]["protocol"],
            "total_monthly_cost_usd": round(total_cost, 2),
            "average_retention":      round(avg_retention, 4),
            "excellent_count":        excellent_count,
            "total_count":            len(analyses),
        },
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log persistence
# ---------------------------------------------------------------------------

def append_log(result: dict, log_path: str = DEFAULT_LOG_PATH) -> None:
    """Append *result* to ring-buffer JSON log (cap LOG_CAP). Atomic write."""
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    existing: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(result)
    existing = existing[-LOG_CAP:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(existing, fh, indent=2)
    os.replace(tmp, log_path)


def run(incentive_programs: list, config: dict, log_path: str = DEFAULT_LOG_PATH) -> dict:
    """Analyze incentive programs and persist result to log. Returns analysis result."""
    result = analyze(incentive_programs, config)
    append_log(result, log_path)
    return result
