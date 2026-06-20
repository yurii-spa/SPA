"""
MP-757: RewardTokenTracker
Advisory / read-only analytics module.
Tracks DeFi reward/incentive tokens earned across protocols,
estimates USD value accounting for vesting schedules and price volatility,
and computes true risk-adjusted yield contribution.

Pure stdlib. No external dependencies. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import List
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = os.path.join(DATA_DIR, "reward_token_log.json")
RING_BUFFER_CAP = 100

VESTING_DISCOUNT_PER_MONTH = 2.0   # % per month
VESTING_DISCOUNT_MAX = 50.0        # %
VOLATILITY_DISCOUNT_FACTOR = 0.3   # fraction of annualized vol used as haircut
VOLATILITY_DISCOUNT_MAX = 50.0     # %

HIGH_VALUE_THRESHOLD = 2.0         # % risk-adjusted APY contribution
MODERATE_VALUE_THRESHOLD = 0.5

QUALITY_HIGH_RATIO = 70.0          # % of gross
QUALITY_MEDIUM_RATIO = 40.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RewardToken:
    token_symbol: str
    protocol: str

    # Earned
    tokens_earned_per_year: float
    token_price_usd: float
    annual_reward_usd: float

    # Vesting
    vesting_months: int
    vesting_discount_pct: float
    net_reward_usd: float

    # Price risk
    token_volatility_pct: float
    volatility_discount_pct: float
    risk_adjusted_reward_usd: float

    # Position context
    position_size_usd: float
    risk_adjusted_apy_contribution_pct: float

    # Assessment
    is_high_value: bool
    token_label: str
    recommendation: str


@dataclass
class RewardTrackingResult:
    tokens: List[RewardToken]

    total_annual_reward_usd: float
    total_risk_adjusted_usd: float

    top_reward_token: str

    high_value_tokens: List[str]

    total_risk_adjusted_apy_pct: float

    reward_quality_label: str

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_vesting_discount(vesting_months: int) -> float:
    """% illiquidity discount: vesting_months * 2%, capped at 50%."""
    return min(vesting_months * VESTING_DISCOUNT_PER_MONTH, VESTING_DISCOUNT_MAX)


def compute_volatility_discount(volatility_pct: float) -> float:
    """% haircut: volatility_pct * 0.3, capped at 50%."""
    return min(volatility_pct * VOLATILITY_DISCOUNT_FACTOR, VOLATILITY_DISCOUNT_MAX)


def token_label(risk_adjusted_apy_pct: float) -> str:
    """HIGH_VALUE (>=2%) | MODERATE_VALUE (0.5-2%) | LOW_VALUE (<0.5%)"""
    if risk_adjusted_apy_pct >= HIGH_VALUE_THRESHOLD:
        return "HIGH_VALUE"
    elif risk_adjusted_apy_pct >= MODERATE_VALUE_THRESHOLD:
        return "MODERATE_VALUE"
    else:
        return "LOW_VALUE"


def reward_quality_label(risk_adj_total: float, gross_total: float) -> str:
    """
    HIGH_QUALITY (ratio>=70%) | MEDIUM_QUALITY (40-70%) | LOW_QUALITY (<40%)
    where ratio = risk_adj_total / gross_total * 100 if gross_total > 0 else 100
    """
    if gross_total > 0:
        ratio = risk_adj_total / gross_total * 100.0
    else:
        ratio = 100.0
    if ratio >= QUALITY_HIGH_RATIO:
        return "HIGH_QUALITY"
    elif ratio >= QUALITY_MEDIUM_RATIO:
        return "MEDIUM_QUALITY"
    else:
        return "LOW_QUALITY"


def _token_recommendation(label: str) -> str:
    if label == "HIGH_VALUE":
        return "High-value reward. Consider claiming and reinvesting regularly."
    elif label == "MODERATE_VALUE":
        return "Moderate reward value. Monitor token price."
    else:
        return "Low reward value after risk discounts. Verify emission rate."


# ---------------------------------------------------------------------------
# High-level tracking
# ---------------------------------------------------------------------------

def track_token(
    token_symbol: str,
    protocol: str,
    tokens_earned_per_year: float,
    token_price_usd: float,
    vesting_months: int,
    token_volatility_pct: float,
    position_size_usd: float,
) -> RewardToken:
    """Compute all fields for a single reward token position."""
    annual_reward = tokens_earned_per_year * token_price_usd

    vest_disc = compute_vesting_discount(vesting_months)
    net_reward = annual_reward * (1.0 - vest_disc / 100.0)

    vol_disc = compute_volatility_discount(token_volatility_pct)
    risk_adj_reward = net_reward * (1.0 - vol_disc / 100.0)

    if position_size_usd > 0:
        risk_adj_apy = risk_adj_reward / position_size_usd * 100.0
    else:
        risk_adj_apy = 0.0

    label = token_label(risk_adj_apy)
    high_value = risk_adj_apy >= HIGH_VALUE_THRESHOLD
    rec = _token_recommendation(label)

    return RewardToken(
        token_symbol=token_symbol,
        protocol=protocol,
        tokens_earned_per_year=tokens_earned_per_year,
        token_price_usd=token_price_usd,
        annual_reward_usd=annual_reward,
        vesting_months=vesting_months,
        vesting_discount_pct=vest_disc,
        net_reward_usd=net_reward,
        token_volatility_pct=token_volatility_pct,
        volatility_discount_pct=vol_disc,
        risk_adjusted_reward_usd=risk_adj_reward,
        position_size_usd=position_size_usd,
        risk_adjusted_apy_contribution_pct=risk_adj_apy,
        is_high_value=high_value,
        token_label=label,
        recommendation=rec,
    )


def track_portfolio(tokens_data: List[dict]) -> RewardTrackingResult:
    """
    tokens_data: list of dicts with keys matching track_token signature.
    Returns a RewardTrackingResult (not saved to disk).
    """
    tokens: List[RewardToken] = []
    for td in tokens_data:
        t = track_token(
            token_symbol=td["token_symbol"],
            protocol=td["protocol"],
            tokens_earned_per_year=td["tokens_earned_per_year"],
            token_price_usd=td["token_price_usd"],
            vesting_months=td.get("vesting_months", 0),
            token_volatility_pct=td.get("token_volatility_pct", 0.0),
            position_size_usd=td["position_size_usd"],
        )
        tokens.append(t)

    total_annual = sum(t.annual_reward_usd for t in tokens)
    total_risk_adj = sum(t.risk_adjusted_reward_usd for t in tokens)

    if tokens:
        top_t = max(tokens, key=lambda t: t.risk_adjusted_reward_usd)
        top_label = top_t.token_symbol
    else:
        top_label = ""

    high_value = [t.token_symbol for t in tokens if t.token_label == "HIGH_VALUE"]
    total_risk_adj_apy = sum(t.risk_adjusted_apy_contribution_pct for t in tokens)

    quality = reward_quality_label(total_risk_adj, total_annual)

    if not tokens:
        summary = "No reward tokens tracked."
    elif quality == "HIGH_QUALITY":
        summary = "Reward portfolio is high quality — most gross rewards survive risk discounts."
    elif quality == "MEDIUM_QUALITY":
        summary = "Reward portfolio is medium quality. Some value lost to vesting/volatility."
    else:
        summary = "Reward portfolio is low quality. Significant value lost to vesting or volatility discounts."

    return RewardTrackingResult(
        tokens=tokens,
        total_annual_reward_usd=total_annual,
        total_risk_adjusted_usd=total_risk_adj,
        top_reward_token=top_label,
        high_value_tokens=high_value,
        total_risk_adjusted_apy_pct=total_risk_adj_apy,
        reward_quality_label=quality,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer)
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _result_to_dict(result: RewardTrackingResult) -> dict:
    return {
        "tokens": [asdict(t) for t in result.tokens],
        "total_annual_reward_usd": result.total_annual_reward_usd,
        "total_risk_adjusted_usd": result.total_risk_adjusted_usd,
        "top_reward_token": result.top_reward_token,
        "high_value_tokens": result.high_value_tokens,
        "total_risk_adjusted_apy_pct": result.total_risk_adjusted_apy_pct,
        "reward_quality_label": result.reward_quality_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def load_history(filepath: str = LOG_FILE) -> List[dict]:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def save_results(result: RewardTrackingResult, filepath: str = LOG_FILE) -> RewardTrackingResult:
    """Append result to ring-buffer log (cap=100). Updates result.saved_to."""
    _ensure_data_dir()
    history = load_history(filepath)
    entry = _result_to_dict(result)
    history.append(entry)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    dir_name = os.path.dirname(os.path.abspath(filepath))
    atomic_save(history, str(filepath))
    result.saved_to = filepath
    return result
