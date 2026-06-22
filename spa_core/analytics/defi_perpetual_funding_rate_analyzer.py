"""
MP-932: DeFiPerpetualFundingRateAnalyzer
==========================================
Advisory-only analytics module.
Analyzes funding rates on DeFi perpetual markets.

Input (per market):
  protocol, pair, current_funding_rate_8h_pct, avg_funding_rate_30d_pct,
  open_interest_usd, long_short_ratio, funding_rate_volatility_pct,
  predicted_next_rate_pct, insurance_fund_usd, liquidations_24h_usd

Computed per market:
  annualized_funding_pct  (8h_rate × 3 × 365)
  funding_cost_score      (0-100; higher = more expensive for longs)
  market_skew_score       (0-100; 100 = extremely long-heavy)
  carry_trade_opportunity_pct (annualized_funding − spot_staking_apy)
  funding_label           HEAVILY_LONG / LONG_BIASED / NEUTRAL /
                          SHORT_BIASED / HEAVILY_SHORT
  flags                   EXTREME_FUNDING | CARRY_OPPORTUNITY |
                          HIGH_LIQUIDATION_RISK | LOW_INSURANCE | VOLATILE_FUNDING

Aggregates:
  highest_funding_market, lowest_funding_market,
  total_open_interest_usd, average_annualized_funding, carry_opportunity_count

Ring-buffer log → data/perp_funding_rate_log.json (cap 100).
Atomic writes: tmp + os.replace.

Pure stdlib. No external dependencies.
"""

import json
import math
import os
import time
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

LOG_PATH = os.path.join(_REPO_ROOT, "data", "perp_funding_rate_log.json")
LOG_MAX_ENTRIES = 100

# Periods per day for an 8-hour funding rate
_PERIODS_PER_DAY = 3
_DAYS_PER_YEAR = 365

# Flag thresholds
EXTREME_FUNDING_THRESHOLD_8H_PCT: float = 0.1    # |rate| > 0.1% per 8h
CARRY_PREMIUM_THRESHOLD_PCT: float = 5.0          # annualized premium over staking
HIGH_LIQ_RATIO: float = 0.05                      # liquidations / OI > 5%
LOW_INSURANCE_RATIO: float = 0.01                 # insurance < 1% of OI
VOLATILE_FUNDING_THRESHOLD: float = 0.05          # volatility_pct > 0.05%

# Default spot-staking APY used in carry-trade calculation
DEFAULT_SPOT_STAKING_APY_PCT: float = 4.0

# Skew label thresholds (long_short_ratio)
HEAVILY_LONG_RATIO: float = 2.0
LONG_BIASED_RATIO: float = 1.25
SHORT_BIASED_RATIO: float = 0.8
HEAVILY_SHORT_RATIO: float = 0.5


# ---------------------------------------------------------------------------
# Pure helpers (importable for testing)
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _annualize_funding_rate(funding_rate_8h_pct: float) -> float:
    """Convert 8-hour funding rate % → annualized %: rate × 3 × 365."""
    return funding_rate_8h_pct * _PERIODS_PER_DAY * _DAYS_PER_YEAR


def _funding_cost_score(annualized_pct: float) -> float:
    """
    Score 0-100 representing how expensive funding is for longs.
    0%  annualized → 50 (neutral).
    +100% annualized → 100 (maximum cost).
    −100% annualized → 0 (shorts paying longs).
    Linear mapping: score = 50 + 0.5 × annualized_pct.
    """
    return _clamp(50.0 + 0.5 * annualized_pct)


def _market_skew_score(long_short_ratio: float) -> float:
    """
    Score 0-100 for how long-heavy the market is.
    ratio = 1 → 50 (balanced).
    ratio → ∞ → 100 (extremely long-heavy).
    ratio → 0  → 0  (extremely short-heavy).
    Uses log2 mapping: score = 50 + 25 × log2(ratio).
    """
    if long_short_ratio <= 0:
        return 0.0
    return _clamp(50.0 + 25.0 * math.log2(long_short_ratio))


def _funding_label(long_short_ratio: float) -> str:
    """Classify market skew into a descriptive label."""
    if long_short_ratio >= HEAVILY_LONG_RATIO:
        return "HEAVILY_LONG"
    if long_short_ratio >= LONG_BIASED_RATIO:
        return "LONG_BIASED"
    if long_short_ratio <= HEAVILY_SHORT_RATIO:
        return "HEAVILY_SHORT"
    if long_short_ratio <= SHORT_BIASED_RATIO:
        return "SHORT_BIASED"
    return "NEUTRAL"


def _carry_trade_opportunity(
    annualized_funding_pct: float,
    spot_staking_apy_pct: float,
) -> float:
    """Annualized premium of perp funding over spot staking APY."""
    return annualized_funding_pct - spot_staking_apy_pct


def _compute_flags(
    market: dict,
    annualized_pct: float,
    carry_premium: float,
) -> List[str]:
    """Return list of applicable flag strings for a single market."""
    flags: List[str] = []
    current_rate = market.get("current_funding_rate_8h_pct", 0.0)
    oi = market.get("open_interest_usd", 0.0)
    liq = market.get("liquidations_24h_usd", 0.0)
    insurance = market.get("insurance_fund_usd", 0.0)
    vol = market.get("funding_rate_volatility_pct", 0.0)

    if abs(current_rate) > EXTREME_FUNDING_THRESHOLD_8H_PCT:
        flags.append("EXTREME_FUNDING")
    if carry_premium > CARRY_PREMIUM_THRESHOLD_PCT:
        flags.append("CARRY_OPPORTUNITY")
    if oi > 0 and liq / oi > HIGH_LIQ_RATIO:
        flags.append("HIGH_LIQUIDATION_RISK")
    if oi > 0 and insurance < oi * LOW_INSURANCE_RATIO:
        flags.append("LOW_INSURANCE")
    if vol > VOLATILE_FUNDING_THRESHOLD:
        flags.append("VOLATILE_FUNDING")

    return flags


def _analyze_market(market: dict, config: dict) -> dict:
    """Compute all derived fields for a single perpetual market entry."""
    spot_staking_apy = config.get(
        "spot_staking_apy_pct", DEFAULT_SPOT_STAKING_APY_PCT
    )

    current_rate_8h = market.get("current_funding_rate_8h_pct", 0.0)
    annualized = _annualize_funding_rate(current_rate_8h)
    cost_score = _funding_cost_score(annualized)
    ls_ratio = market.get("long_short_ratio", 1.0)
    skew_score = _market_skew_score(ls_ratio)
    label = _funding_label(ls_ratio)
    carry_premium = _carry_trade_opportunity(annualized, spot_staking_apy)
    flags = _compute_flags(market, annualized, carry_premium)

    return {
        "protocol": market.get("protocol", ""),
        "pair": market.get("pair", ""),
        "current_funding_rate_8h_pct": current_rate_8h,
        "avg_funding_rate_30d_pct": market.get("avg_funding_rate_30d_pct", 0.0),
        "open_interest_usd": market.get("open_interest_usd", 0.0),
        "long_short_ratio": ls_ratio,
        "funding_rate_volatility_pct": market.get(
            "funding_rate_volatility_pct", 0.0
        ),
        "predicted_next_rate_pct": market.get("predicted_next_rate_pct", 0.0),
        "insurance_fund_usd": market.get("insurance_fund_usd", 0.0),
        "liquidations_24h_usd": market.get("liquidations_24h_usd", 0.0),
        "annualized_funding_pct": round(annualized, 6),
        "funding_cost_score": round(cost_score, 2),
        "market_skew_score": round(skew_score, 2),
        "carry_trade_opportunity_pct": round(carry_premium, 6),
        "funding_label": label,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Atomic ring-buffer log
# ---------------------------------------------------------------------------

def _atomic_log(
    entry: dict,
    log_path: str,
    max_entries: int = LOG_MAX_ENTRIES,
) -> None:
    """Append *entry* to ring-buffer JSON log. Atomic: tmp + os.replace."""
    try:
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        existing: List[dict] = []
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        existing.append(entry)
        if len(existing) > max_entries:
            existing = existing[-max_entries:]
        atomic_save(existing, str(log_path))
    except Exception:
        pass  # advisory module — log failures are non-fatal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DeFiPerpetualFundingRateAnalyzer:
    """
    MP-932 — Advisory analytics for DeFi perpetual-market funding rates.

    Usage::

        analyzer = DeFiPerpetualFundingRateAnalyzer()
        result   = analyzer.analyze(markets, config)

    Returns a dict with keys:
        status, markets_analyzed, markets (list of per-market dicts),
        aggregates (dict), config_used (dict), timestamp (ISO-8601 UTC).
    """

    def analyze(self, markets: List[dict], config: Optional[dict] = None) -> dict:
        """
        Analyze a list of perpetual-market snapshots.

        Parameters
        ----------
        markets : list[dict]
            Each entry must contain the fields documented in the module header.
        config : dict, optional
            spot_staking_apy_pct  – comparison baseline (default 4.0)
            write_log             – bool, default True
            log_path              – override default log path

        Returns
        -------
        dict
        """
        if config is None:
            config = {}

        write_log = config.get("write_log", True)
        log_path = config.get("log_path", LOG_PATH)
        spot_staking_apy = config.get(
            "spot_staking_apy_pct", DEFAULT_SPOT_STAKING_APY_PCT
        )

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not markets:
            result: dict = {
                "status": "ok",
                "markets_analyzed": 0,
                "markets": [],
                "aggregates": {
                    "highest_funding_market": None,
                    "lowest_funding_market": None,
                    "total_open_interest_usd": 0.0,
                    "average_annualized_funding": 0.0,
                    "carry_opportunity_count": 0,
                },
                "config_used": {"spot_staking_apy_pct": spot_staking_apy},
                "timestamp": timestamp,
            }
            if write_log:
                _atomic_log(result, log_path)
            return result

        analyzed = [_analyze_market(m, config) for m in markets]

        total_oi = sum(m["open_interest_usd"] for m in analyzed)
        avg_annual = sum(m["annualized_funding_pct"] for m in analyzed) / len(analyzed)
        carry_count = sum(
            1 for m in analyzed if "CARRY_OPPORTUNITY" in m["flags"]
        )

        highest = max(analyzed, key=lambda m: m["annualized_funding_pct"])
        lowest = min(analyzed, key=lambda m: m["annualized_funding_pct"])

        result = {
            "status": "ok",
            "markets_analyzed": len(analyzed),
            "markets": analyzed,
            "aggregates": {
                "highest_funding_market": (
                    highest["protocol"] + ":" + highest["pair"]
                ),
                "lowest_funding_market": (
                    lowest["protocol"] + ":" + lowest["pair"]
                ),
                "total_open_interest_usd": round(total_oi, 2),
                "average_annualized_funding": round(avg_annual, 6),
                "carry_opportunity_count": carry_count,
            },
            "config_used": {"spot_staking_apy_pct": spot_staking_apy},
            "timestamp": timestamp,
        }

        if write_log:
            _atomic_log(result, log_path)

        return result
