"""
MP-829: ProtocolAdoptionVelocityTracker
Measures how rapidly a protocol is gaining adoption (users, TVL) relative to
peers and whether momentum is accelerating or decelerating.

Pure stdlib, read-only analytics, atomic write, ring-buffer log (cap 100).
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

RING_BUFFER_CAP = 100

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "adoption_velocity_log.json"
)

# ── velocity label thresholds ──────────────────────────────────────────────
_LABEL_THRESHOLDS = [
    (70, "VIRAL"),
    (50, "FAST"),
    (30, "GROWING"),
    (10, "STABLE"),
    (0,  "DECLINING"),
]


def _velocity_label(score: int) -> str:
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "DECLINING"


def _compute_protocol(p: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all velocity metrics for a single protocol dict."""
    name: str = str(p["name"])
    tvl_now: float = float(p["tvl_now"])
    tvl_30d: float = float(p["tvl_30d_ago"])
    tvl_90d: float = float(p["tvl_90d_ago"])
    user_now: int = int(p["user_count_now"])
    user_30d: int = int(p["user_count_30d_ago"])
    dau: int = int(p["daily_active_users"])

    # ── TVL growth rates ───────────────────────────────────────────────────
    # If tvl_30d_ago = 0 → skip all TVL components (set to 0 per spec edge case)
    if tvl_30d > 0:
        tvl_growth_30d_pct = (tvl_now - tvl_30d) / tvl_30d * 100.0
        if tvl_90d > 0:
            tvl_growth_90d_pct = (tvl_now - tvl_90d) / tvl_90d * 100.0
        else:
            tvl_growth_90d_pct = 0.0
        # ── acceleration: 30d rate vs historical 30d average from 90d period
        tvl_acceleration = tvl_growth_30d_pct - (tvl_growth_90d_pct / 3.0)
    else:
        tvl_growth_30d_pct = 0.0
        tvl_growth_90d_pct = 0.0 if tvl_90d == 0 else (tvl_now - tvl_90d) / tvl_90d * 100.0
        tvl_acceleration = 0.0

    # ── user growth ────────────────────────────────────────────────────────
    if user_30d > 0:
        user_growth_30d_pct: Optional[float] = (user_now - user_30d) / user_30d * 100.0
    else:
        user_growth_30d_pct = None

    # ── engagement & TVL per user ──────────────────────────────────────────
    if user_now > 0:
        dau_ratio = dau / user_now
        tvl_per_user = tvl_now / user_now
    else:
        dau_ratio = 0.0
        tvl_per_user = 0.0

    # ── velocity score (0-100) ─────────────────────────────────────────────
    # TVL component: capped at 40 pts (40% monthly = max); only if tvl_30d > 0
    if tvl_30d > 0:
        tvl_component = min(40.0, max(0.0, tvl_growth_30d_pct))
        accel_component = min(20.0, max(0.0, tvl_acceleration))
    else:
        tvl_component = 0.0
        accel_component = 0.0

    # User component: capped at 20 pts
    user_val = user_growth_30d_pct if user_growth_30d_pct is not None else 0.0
    user_component = min(20.0, max(0.0, user_val))

    # Engagement component: DAU/users * 100, capped at 20
    engagement_component = min(20.0, dau_ratio * 100.0)

    raw_score = tvl_component + user_component + engagement_component + accel_component
    velocity_score = int(max(0, min(100, raw_score)))

    return {
        "name": name,
        "tvl_growth_30d_pct": round(tvl_growth_30d_pct, 4),
        "tvl_growth_90d_pct": round(tvl_growth_90d_pct, 4),
        "tvl_acceleration": round(tvl_acceleration, 4),
        "user_growth_30d_pct": round(user_growth_30d_pct, 4) if user_growth_30d_pct is not None else None,
        "dau_ratio": round(dau_ratio, 6),
        "tvl_per_user": round(tvl_per_user, 4),
        "velocity_score": velocity_score,
        "velocity_label": _velocity_label(velocity_score),
    }


def analyze(protocols: List[Dict[str, Any]], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyze protocol adoption velocity across a list of protocols.

    protocols: list of {
        "name": str,
        "tvl_now": float,
        "tvl_30d_ago": float,
        "tvl_90d_ago": float,
        "user_count_now": int,
        "user_count_30d_ago": int,
        "daily_active_users": int,
        "age_days": int
    }
    config: {
        "min_age_days": int  # default 30
    }

    Returns dict with per-protocol metrics + summary fields.
    Appends result to ring-buffer log at data/adoption_velocity_log.json.
    """
    cfg = config or {}
    min_age_days: int = int(cfg.get("min_age_days", 30))
    log_path: str = cfg.get("log_path", _DEFAULT_LOG)

    eligible: List[Dict[str, Any]] = []
    filtered_out: List[str] = []

    for p in protocols:
        age = int(p.get("age_days", 0))
        if age < min_age_days:
            filtered_out.append(str(p["name"]))
        else:
            eligible.append(p)

    computed: List[Dict[str, Any]] = [_compute_protocol(p) for p in eligible]

    # ── summary fields ─────────────────────────────────────────────────────
    if computed:
        market_leader = max(computed, key=lambda x: x["velocity_score"])["name"]
        fastest_growing = max(computed, key=lambda x: x["tvl_growth_30d_pct"])["name"]
        most_engaged = max(computed, key=lambda x: x["dau_ratio"])["name"]
    else:
        market_leader = None
        fastest_growing = None
        most_engaged = None

    result: Dict[str, Any] = {
        "protocols": computed,
        "market_leader": market_leader,
        "fastest_growing": fastest_growing,
        "most_engaged": most_engaged,
        "filtered_out": filtered_out,
        "timestamp": time.time(),
    }

    _append_log(result, log_path)
    return result


# ── ring-buffer log (atomic write) ────────────────────────────────────────

def _append_log(result: Dict[str, Any], log_path: str) -> None:
    """Append result entry to ring-buffer JSON log (cap 100). Atomic write."""
    log_path = os.path.normpath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(result)
    if len(entries) > RING_BUFFER_CAP:
        entries = entries[-RING_BUFFER_CAP:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp_path, log_path)


# ── CLI convenience ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _DEMO = [
        {
            "name": "Aave V3",
            "tvl_now": 12_000_000,
            "tvl_30d_ago": 10_000_000,
            "tvl_90d_ago": 8_000_000,
            "user_count_now": 5000,
            "user_count_30d_ago": 4000,
            "daily_active_users": 500,
            "age_days": 365,
        },
        {
            "name": "NewProtocol",
            "tvl_now": 500_000,
            "tvl_30d_ago": 100_000,
            "tvl_90d_ago": 50_000,
            "user_count_now": 1000,
            "user_count_30d_ago": 200,
            "daily_active_users": 300,
            "age_days": 20,  # too young → filtered
        },
    ]
    res = analyze(_DEMO)
    print(json.dumps(res, indent=2))
    sys.exit(0)
