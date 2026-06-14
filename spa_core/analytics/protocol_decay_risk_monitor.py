# spa_core/analytics/protocol_decay_risk_monitor.py
# MP-846 — ProtocolDecayRiskMonitor (pure stdlib, advisory/read-only)
#
# Monitors protocols for "decay signals": TVL decline, developer activity drop,
# community disengagement, and token price erosion that precede protocol failure.
#
# Scoring (0-100):
#   tvl_decay_score   : 0-35
#   dev_decay_score   : 0-25
#   user_decay_score  : 0-20
#   sentiment_score   : 0-10
#   stale_score       : 0-10
#   token_score       : 0-10   (price-trend component)
#   total             : min(100, sum)
#
# Labels: HEALTHY(<20) | EARLY_DECAY(20-39) | MODERATE_DECAY(40-59)
#         | SEVERE_DECAY(60-79) | FAILING(>=80)
#
# This module is ADVISORY ONLY — never modifies allocator/risk/execution.
# Atomic writes: tmp-file + os.replace.

import json
import math
import os
import time
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data/protocol_decay_log.json")
MAX_ENTRIES = 100

DEFAULT_DECAY_THRESHOLD = 60
DEFAULT_MIN_TREND_POINTS = 3


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tvl_decay_score(tvl_trend: list, min_pts: int) -> tuple:
    """
    Returns (score: int, tvl_change_pct: float | None).
    """
    if len(tvl_trend) < min_pts:
        return 0, None

    first = tvl_trend[0]
    last = tvl_trend[-1]

    if first == 0:
        return 0, None

    tvl_change_pct = (last - first) / first * 100.0

    if tvl_change_pct < -50:
        score = 35
    elif tvl_change_pct < -30:
        score = 25
    elif tvl_change_pct < -15:
        score = 15
    elif tvl_change_pct < -5:
        score = 8
    else:
        score = 0

    return score, tvl_change_pct


def _dev_decay_score(commits_30d: int, commits_90d_ago: int) -> tuple:
    """
    Returns (score: int, dev_change_pct: float | None).
    """
    if commits_90d_ago == 0:
        return 0, None

    dev_change = (commits_30d - commits_90d_ago) / commits_90d_ago * 100.0

    if dev_change < -70:
        score = 25
    elif dev_change < -40:
        score = 18
    elif dev_change < -20:
        score = 10
    elif dev_change < 0:
        score = 5
    else:
        score = 0

    return score, dev_change


def _user_decay_score(users_30d: int, users_90d_ago: int) -> tuple:
    """
    Returns (score: int, user_change_pct: float | None).
    """
    if users_90d_ago == 0:
        return 0, None

    user_change = (users_30d - users_90d_ago) / users_90d_ago * 100.0

    if user_change < -50:
        score = 20
    elif user_change < -25:
        score = 14
    elif user_change < -10:
        score = 7
    else:
        score = 0

    return score, user_change


def _sentiment_score(social_sentiment: float) -> int:
    if social_sentiment < -0.5:
        return 10
    elif social_sentiment < -0.2:
        return 6
    elif social_sentiment < 0:
        return 3
    else:
        return 0


def _stale_score(days_since_update: int) -> int:
    if days_since_update > 365:
        return 10
    elif days_since_update > 180:
        return 7
    elif days_since_update > 90:
        return 4
    elif days_since_update > 30:
        return 1
    else:
        return 0


def _token_trend_and_score(token_price_trend: list, min_pts: int) -> tuple:
    """
    Returns (token_trend_label: str, token_score: int, price_change_pct: float | None).
    """
    if len(token_price_trend) < min_pts:
        return "STABLE", 0, None

    first = token_price_trend[0]
    last = token_price_trend[-1]

    if first == 0:
        return "STABLE", 0, None

    price_change = (last - first) / first * 100.0

    # Label
    if price_change < -60:
        label = "CRASHING"
        score = 10
    elif price_change < -20:
        label = "FALLING"
        score = 7
    elif price_change < 10:
        label = "STABLE"
        score = 3
    else:
        label = "RISING"
        score = 0

    return label, score, price_change


def _decay_label(score: int) -> str:
    if score >= 80:
        return "FAILING"
    elif score >= 60:
        return "SEVERE_DECAY"
    elif score >= 40:
        return "MODERATE_DECAY"
    elif score >= 20:
        return "EARLY_DECAY"
    else:
        return "HEALTHY"


def _warning_signals(
    tvl_change_pct: Optional[float],
    dev_change: Optional[float],
    user_change: Optional[float],
    social_sentiment: float,
    days_since_update: int,
    price_change: Optional[float],
) -> list:
    signals = []
    if tvl_change_pct is not None and tvl_change_pct < -30:
        signals.append("TVL declining >30%")
    if dev_change is not None and dev_change < -40:
        signals.append("Developer activity dropped significantly")
    if user_change is not None and user_change < -25:
        signals.append("User base shrinking")
    if social_sentiment < -0.2:
        signals.append("Negative community sentiment")
    if days_since_update > 90:
        signals.append("No protocol updates in 90+ days")
    if price_change is not None and price_change < -30:
        signals.append("Token price in freefall")
    return signals


def _estimated_months_to_critical(
    tvl_change_pct: Optional[float],
    tvl_trend_len: int,
    decay_score: int,
) -> Optional[float]:
    """
    Extrapolation of how many months until the protocol reaches 'critical' state.
    Only computed when decay_score >= 20 and TVL is declining.
    """
    if tvl_change_pct is None:
        return None
    if tvl_change_pct >= 0:
        return None
    if decay_score < 20:
        return None

    # Monthly decay rate: approximate weekly data → divide by 4
    monthly_decay_rate = abs(tvl_change_pct) / tvl_trend_len / 4.0

    if monthly_decay_rate <= 0:
        return None

    months = (100 - decay_score) / (decay_score * monthly_decay_rate / 100.0)
    return round(min(months, 120.0), 2)


# ---------------------------------------------------------------------------
# Main analyse function
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyse each protocol for decay signals and aggregate results.

    Parameters
    ----------
    protocols : list[dict]  — each dict per module docstring schema.
    config    : dict        — optional keys:
                             "decay_threshold" (default 60)
                             "min_trend_points" (default 3)

    Returns
    -------
    dict  — full analysis result (see module docstring for schema).
    """
    if config is None:
        config = {}

    decay_threshold = int(config.get("decay_threshold", DEFAULT_DECAY_THRESHOLD))
    min_pts = int(config.get("min_trend_points", DEFAULT_MIN_TREND_POINTS))

    analysed = []

    for proto in protocols:
        name = proto.get("name", "unknown")

        tvl_trend          = proto.get("tvl_trend", [])
        commits_30d        = int(proto.get("github_commits_30d", 0))
        commits_90d_ago    = int(proto.get("github_commits_90d_ago", 0))
        token_price_trend  = proto.get("token_price_trend", [])
        users_30d          = int(proto.get("unique_users_30d", 0))
        users_90d_ago      = int(proto.get("unique_users_90d_ago", 0))
        social_sentiment   = float(proto.get("social_sentiment_score", 0.0))
        days_since_update  = int(proto.get("days_since_last_update", 0))

        # Score components
        tvl_score, tvl_change_pct = _tvl_decay_score(tvl_trend, min_pts)
        dev_score, dev_change     = _dev_decay_score(commits_30d, commits_90d_ago)
        user_score, user_change   = _user_decay_score(users_30d, users_90d_ago)
        sent_score                = _sentiment_score(social_sentiment)
        st_score                  = _stale_score(days_since_update)
        token_trend, tok_score, price_change = _token_trend_and_score(token_price_trend, min_pts)

        total_score = min(100, tvl_score + dev_score + user_score + sent_score + st_score + tok_score)

        label  = _decay_label(total_score)
        warns  = _warning_signals(tvl_change_pct, dev_change, user_change,
                                   social_sentiment, days_since_update, price_change)
        months = _estimated_months_to_critical(tvl_change_pct, len(tvl_trend), total_score)

        analysed.append({
            "name":                          name,
            "decay_score":                   total_score,
            "decay_label":                   label,
            "tvl_change_pct":                round(tvl_change_pct, 4) if tvl_change_pct is not None else None,
            "dev_activity_change_pct":       round(dev_change, 4) if dev_change is not None else None,
            "user_change_pct":               round(user_change, 4) if user_change is not None else None,
            "token_trend":                   token_trend,
            "warning_signals":               warns,
            "estimated_months_to_critical":  months,
        })

    # Aggregate
    decaying = [p["name"] for p in analysed if p["decay_score"] > decay_threshold]

    healthiest = None
    if analysed:
        healthiest = min(analysed, key=lambda p: p["decay_score"])["name"]

    most_at_risk = None
    if analysed:
        most_at_risk = max(analysed, key=lambda p: p["decay_score"])["name"]

    avg_score = (
        sum(p["decay_score"] for p in analysed) / len(analysed)
        if analysed else 0.0
    )

    ts = time.time()
    result = {
        "protocols":          analysed,
        "decaying_protocols": decaying,
        "healthiest_protocol": healthiest,
        "most_at_risk":       most_at_risk,
        "average_decay_score": round(avg_score, 4),
        "timestamp":          ts,
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic write)
# ---------------------------------------------------------------------------

def _append_log(result: dict) -> None:
    """Append summary to ring-buffer log; cap at MAX_ENTRIES."""
    log_path = DATA_FILE

    existing: list = []
    try:
        with open(log_path, "r") as fh:
            existing = json.load(fh)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "timestamp":            result["timestamp"],
        "protocol_count":       len(result["protocols"]),
        "decaying_count":       len(result["decaying_protocols"]),
        "average_decay_score":  result["average_decay_score"],
        "most_at_risk":         result["most_at_risk"],
        "healthiest_protocol":  result["healthiest_protocol"],
    }

    existing.append(entry)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = log_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(existing, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def _demo() -> None:
    protocols = [
        {
            "name": "Aave V3",
            "tvl_trend": [5e9, 4.8e9, 4.7e9, 4.9e9, 5.1e9],
            "github_commits_30d": 45,
            "github_commits_90d_ago": 40,
            "token_price_trend": [80.0, 82.0, 85.0, 87.0, 90.0],
            "unique_users_30d": 12000,
            "unique_users_90d_ago": 11500,
            "social_sentiment_score": 0.3,
            "days_since_last_update": 5,
        },
        {
            "name": "FailingProto",
            "tvl_trend": [1e9, 600e6, 300e6, 100e6, 50e6],
            "github_commits_30d": 1,
            "github_commits_90d_ago": 50,
            "token_price_trend": [10.0, 5.0, 2.0, 0.5, 0.1],
            "unique_users_30d": 50,
            "unique_users_90d_ago": 5000,
            "social_sentiment_score": -0.9,
            "days_since_last_update": 400,
        },
    ]
    result = analyze(protocols)
    import json as _json
    print(_json.dumps(result, indent=2))


if __name__ == "__main__":
    _demo()
