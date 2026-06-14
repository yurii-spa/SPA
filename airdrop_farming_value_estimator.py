"""
MP-874 AirdropFarmingValueEstimator
-----------------------------------
Estimates the expected value of airdrop / points farming for a position and
compares it against a safe baseline yield (opportunity cost).  Produces an
attractiveness score and an advisory verdict.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
import tempfile
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DAYS_PER_YEAR: float = 365.0

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "airdrop_farming_log.json"
)
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _user_share(points_accrued: float, total_protocol_points: float) -> float:
    """Return user's fractional share of total points (0 if total is 0)."""
    if total_protocol_points <= 0:
        return 0.0
    return points_accrued / total_protocol_points


def _expected_airdrop_usd(
    user_share: float,
    airdrop_supply_pct: float,
    estimated_fdv_usd: float,
    probability: float,
) -> float:
    """Return expected USD value of the airdrop for this position."""
    prob = max(0.0, min(1.0, probability))
    supply_frac = max(0.0, airdrop_supply_pct) / 100.0
    return user_share * supply_frac * max(0.0, estimated_fdv_usd) * prob


def _annualized_airdrop_yield_pct(
    expected_airdrop_usd: float,
    position_usd: float,
    days_farming: float,
) -> float:
    """Return annualized airdrop yield % (0 if position or days are 0)."""
    if position_usd <= 0 or days_farming <= 0:
        return 0.0
    return expected_airdrop_usd / position_usd / days_farming * _DAYS_PER_YEAR * 100.0


def _opportunity_cost_usd(
    position_usd: float,
    base_apy_pct: float,
    days_farming: float,
) -> float:
    """Return USD forgone by farming instead of the safe baseline yield."""
    if position_usd <= 0 or days_farming <= 0:
        return 0.0
    return position_usd * base_apy_pct / 100.0 * days_farming / _DAYS_PER_YEAR


def _attractiveness_score(
    annualized_airdrop_yield_pct: float,
    base_apy_pct: float,
    net_expected_value_usd: float,
) -> float:
    """Return 0-100 attractiveness score (higher = more attractive)."""
    if net_expected_value_usd <= 0:
        return 0.0
    # Ratio of farming yield to baseline yield drives the score.
    if base_apy_pct <= 0:
        ratio = 10.0 if annualized_airdrop_yield_pct > 0 else 0.0
    else:
        ratio = annualized_airdrop_yield_pct / base_apy_pct

    # ratio 1x → 50, 2x → ~75, saturating toward 100.
    score = 100.0 * (1.0 - 1.0 / (1.0 + ratio))
    return max(0.0, min(100.0, score))


def _value_label(score: float, net_expected_value_usd: float) -> str:
    """Classify into AVOID / MARGINAL / ATTRACTIVE / HIGHLY_ATTRACTIVE."""
    if net_expected_value_usd <= 0 or score < 25.0:
        return "AVOID"
    if score < 50.0:
        return "MARGINAL"
    if score < 75.0:
        return "ATTRACTIVE"
    return "HIGHLY_ATTRACTIVE"


def _build_recommendations(
    label: str,
    annualized_airdrop_yield_pct: float,
    base_apy_pct: float,
    net_expected_value_usd: float,
    probability: float,
) -> list[str]:
    """Return advisory recommendations based on the verdict."""
    recs: list[str] = []

    if label == "AVOID":
        recs.append(
            f"Net expected value {net_expected_value_usd:,.0f} USD does not beat the "
            f"baseline {base_apy_pct:.1f}% APY. Prefer the safe yield."
        )
    elif label == "MARGINAL":
        recs.append(
            f"Marginal edge: farming yield {annualized_airdrop_yield_pct:.1f}% vs "
            f"baseline {base_apy_pct:.1f}%. Size cautiously."
        )
    elif label == "ATTRACTIVE":
        recs.append(
            f"Attractive: ~{annualized_airdrop_yield_pct:.1f}% annualized airdrop yield. "
            f"Continue farming and track points share."
        )
    else:  # HIGHLY_ATTRACTIVE
        recs.append(
            f"Highly attractive: ~{annualized_airdrop_yield_pct:.1f}% annualized airdrop "
            f"yield. Consider increasing allocation within risk limits."
        )

    if probability < 0.5:
        recs.append(
            f"Airdrop probability {probability:.0%} is low. Expected value is "
            f"highly uncertain."
        )

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(position: dict, config: dict | None = None) -> dict:
    """
    Estimate airdrop / points farming value for a position.

    Parameters
    ----------
    position : dict
        Expected keys:
        - protocol: str  (informational)
        - position_usd: float
        - points_accrued: float
        - total_protocol_points: float
        - estimated_fdv_usd: float  (fully diluted valuation of token)
        - airdrop_supply_pct: float  (% of supply going to airdrop)
        - probability: float  (0-1 likelihood airdrop happens)
        - days_farming: float
        - base_apy_pct: float  (safe alternative yield)
    config : dict, optional
        - log_path: str  (override default log path)

    Returns
    -------
    dict
        Full airdrop farming value analysis result.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    protocol = position.get("protocol", "UNKNOWN")
    position_usd = float(position.get("position_usd", 0.0))
    points_accrued = float(position.get("points_accrued", 0.0))
    total_protocol_points = float(position.get("total_protocol_points", 0.0))
    estimated_fdv_usd = float(position.get("estimated_fdv_usd", 0.0))
    airdrop_supply_pct = float(position.get("airdrop_supply_pct", 0.0))
    probability = float(position.get("probability", 0.0))
    days_farming = float(position.get("days_farming", 0.0))
    base_apy_pct = float(position.get("base_apy_pct", 0.0))

    user_share = _user_share(points_accrued, total_protocol_points)
    expected_airdrop_usd = _expected_airdrop_usd(
        user_share, airdrop_supply_pct, estimated_fdv_usd, probability
    )
    annualized_airdrop_yield_pct = _annualized_airdrop_yield_pct(
        expected_airdrop_usd, position_usd, days_farming
    )
    opportunity_cost_usd = _opportunity_cost_usd(
        position_usd, base_apy_pct, days_farming
    )
    net_expected_value_usd = expected_airdrop_usd - opportunity_cost_usd

    score = _attractiveness_score(
        annualized_airdrop_yield_pct, base_apy_pct, net_expected_value_usd
    )
    label = _value_label(score, net_expected_value_usd)
    recommendations = _build_recommendations(
        label,
        annualized_airdrop_yield_pct,
        base_apy_pct,
        net_expected_value_usd,
        probability,
    )

    ts = time.time()
    result: dict[str, Any] = {
        "protocol": protocol,
        "position_usd": position_usd,
        "user_share": user_share,
        "expected_airdrop_usd": expected_airdrop_usd,
        "annualized_airdrop_yield_pct": annualized_airdrop_yield_pct,
        "opportunity_cost_usd": opportunity_cost_usd,
        "net_expected_value_usd": net_expected_value_usd,
        "attractiveness_score": score,
        "label": label,
        "recommendations": recommendations,
        "timestamp": ts,
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


if __name__ == "__main__":
    import sys

    _demo = {
        "protocol": "Hyperliquid points",
        "position_usd": 50_000.0,
        "points_accrued": 12_000.0,
        "total_protocol_points": 4_000_000.0,
        "estimated_fdv_usd": 3_000_000_000.0,
        "airdrop_supply_pct": 30.0,
        "probability": 0.7,
        "days_farming": 90.0,
        "base_apy_pct": 5.0,
    }

    r = analyze(_demo)
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)
