"""
MP-1139  ProtocolDeFiRewardTokenLockupDiscountAnalyzer
------------------------------------------------------
Quantify the *illiquidity discount* on a yield position's reward emissions when
those rewards are locked, vested, or ve-escrowed rather than paid liquid, and
restate the position's headline APR as a realisable, lockup-adjusted APR.

Many DeFi farms pay their headline APR in a reward token that the farmer cannot
freely sell on receipt: it may vest over a cliff/linear schedule, be locked in a
ve-style escrow for months or years, or be subject to an early-exit penalty.
Locked rewards are worth less than their spot mark because of (a) the time value
of money over the lockup, (b) the price risk borne while locked (the token can
fall before it unlocks), and (c) any early-exit penalty if liquidity is needed
sooner. A 40% headline APR paid in a token locked for two years with a 50%
early-exit penalty is not a 40% APR.

For a single position the module computes:
- the share of total APR paid in the (illiquid) reward token vs paid liquid,
- a *lockup discount factor* (0..1) blending time-value, price-risk, and
  early-exit-penalty haircuts over the lockup horizon,
- the *realisable reward APR* (reward APR after the discount) and the total
  *lockup-adjusted APR* (liquid APR plus realisable reward APR),
- the headline-vs-realisable APR gap (the "paper yield" the headline overstates),
- a 0-100 *reward-realisability score* (higher = rewards are closer to liquid /
  the headline APR is closer to real).

Genuine gap: existing modules score emissions decay, reward sustainability, and
APY, but none discount *locked / vested / ve-escrowed* reward emissions for
time-value, price-risk, and early-exit penalty to restate the headline APR as a
realisable, lockup-adjusted APR.

The module returns:
- total_apr_pct / liquid_apr_pct / reward_apr_pct (input-derived)
- reward_share_of_apr_pct       - reward APR / total APR
- lockup_discount_factor        - 0..1 (1 = no discount, 0 = worthless)
- realisable_reward_apr_pct     - reward APR after the lockup discount
- lockup_adjusted_apr_pct       - liquid APR + realisable reward APR
- headline_vs_realisable_gap_pct- total APR minus lockup-adjusted APR
- paper_yield_share_pct         - share of headline APR that is "paper"
- reward_realisability_score    - 0-100, higher = closer to liquid
- classification                - FULLY_LIQUID .. DEEPLY_LOCKED
- grade                         - A-F letter grade
- flags / recommendations       - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "reward_token_lockup_discount_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Defaults.
_DEFAULT_DISCOUNT_RATE_PCT = 15.0   # annual time-value discount on locked value
_DAYS_PER_YEAR = 365.0

# Classification bands
CLASS_FULLY_LIQUID = "FULLY_LIQUID"
CLASS_LIGHTLY_LOCKED = "LIGHTLY_LOCKED"
CLASS_MODERATELY_LOCKED = "MODERATELY_LOCKED"
CLASS_HEAVILY_LOCKED = "HEAVILY_LOCKED"
CLASS_DEEPLY_LOCKED = "DEEPLY_LOCKED"

ALL_CLASSIFICATIONS = (
    CLASS_FULLY_LIQUID,
    CLASS_LIGHTLY_LOCKED,
    CLASS_MODERATELY_LOCKED,
    CLASS_HEAVILY_LOCKED,
    CLASS_DEEPLY_LOCKED,
)

# Flags
FLAG_LONG_LOCKUP = "LONG_LOCKUP"
FLAG_HIGH_EARLY_EXIT_PENALTY = "HIGH_EARLY_EXIT_PENALTY"
FLAG_REWARD_DOMINATED_APR = "REWARD_DOMINATED_APR"
FLAG_LARGE_PAPER_YIELD = "LARGE_PAPER_YIELD"
FLAG_HIGH_PRICE_RISK = "HIGH_PRICE_RISK"
FLAG_MOSTLY_LIQUID = "MOSTLY_LIQUID"
FLAG_DEEP_DISCOUNT = "DEEP_DISCOUNT"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_LONG_LOCKUP,
    FLAG_HIGH_EARLY_EXIT_PENALTY,
    FLAG_REWARD_DOMINATED_APR,
    FLAG_LARGE_PAPER_YIELD,
    FLAG_HIGH_PRICE_RISK,
    FLAG_MOSTLY_LIQUID,
    FLAG_DEEP_DISCOUNT,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_LONG_LOCKUP_DAYS = 365.0            # >= 1y lockup is long
_HIGH_EARLY_EXIT_PENALTY_PCT = 30.0  # >= 30% early-exit penalty is high
_REWARD_DOMINATED_SHARE_PCT = 60.0   # reward >= 60% of total APR is dominated
_LARGE_PAPER_YIELD_SHARE_PCT = 40.0  # >= 40% of headline is "paper"
_HIGH_PRICE_RISK_VOL_PCT = 80.0      # >= 80% annual vol is high price risk
_MOSTLY_LIQUID_DISCOUNT = 0.90       # discount factor >= 0.90 is mostly liquid
_DEEP_DISCOUNT_FACTOR = 0.40         # discount factor <= 0.40 is deep


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _reward_share_of_apr_pct(reward_apr_pct: float, total_apr_pct: float) -> float:
    """
    Share of total APR paid in the (illiquid) reward token, in pct.

        share = reward_apr / total_apr * 100

    Defensive: when total APR is ~0 the share is 0.0; the share is clamped to
    [0, 100].
    """
    total = total_apr_pct
    if total <= _EPS:
        return 0.0
    return _clamp(reward_apr_pct / total * 100.0, 0.0, 100.0)


def _time_value_factor(lockup_days: float, discount_rate_pct: float) -> float:
    """
    Time-value retention factor over the lockup, in (0, 1].

        factor = 1 / (1 + r) ** years     (continuous-ish discrete discount)

    where years = lockup_days / 365 and r = discount_rate/100. A zero lockup
    returns 1.0 (no time-value haircut). Defensive: years and rate floored at 0.
    """
    years = max(0.0, lockup_days) / _DAYS_PER_YEAR
    r = max(0.0, discount_rate_pct) / 100.0
    if years <= _EPS:
        return 1.0
    return 1.0 / ((1.0 + r) ** years)


def _price_risk_factor(lockup_days: float, annual_vol_pct: float) -> float:
    """
    Price-risk retention factor over the lockup, in (0, 1].

    Locked tokens bear price risk for the lockup horizon. We model the retained
    value as a haircut growing with the volatility scaled by sqrt(time)::

        sigma_horizon = (annual_vol/100) * sqrt(years)
        factor = 1 / (1 + sigma_horizon)

    A zero lockup or zero vol returns 1.0. Defensive: inputs floored at 0;
    sqrt is over a non-negative argument.
    """
    years = max(0.0, lockup_days) / _DAYS_PER_YEAR
    vol = max(0.0, annual_vol_pct) / 100.0
    if years <= _EPS or vol <= _EPS:
        return 1.0
    sigma_horizon = vol * math.sqrt(years)
    return 1.0 / (1.0 + sigma_horizon)


def _early_exit_factor(early_exit_penalty_pct: float) -> float:
    """
    Early-exit retention factor, in [0, 1].

    If the farmer may need liquidity before unlock, the relevant mark includes
    the early-exit penalty haircut::

        factor = 1 - (early_exit_penalty / 100)

    Defensive: penalty clamped to [0, 100] so the factor stays in [0, 1].
    """
    pen = _clamp(early_exit_penalty_pct, 0.0, 100.0) / 100.0
    return 1.0 - pen


def _lockup_discount_factor(
    lockup_days: float,
    discount_rate_pct: float,
    annual_vol_pct: float,
    early_exit_penalty_pct: float,
    liquid_unlock_fraction: float,
) -> float:
    """
    Blended lockup discount retention factor in [0, 1] (1 = no discount).

    Combines three multiplicative haircuts over the *locked* portion:
      - time-value (money locked is worth less now),
      - price-risk (token can fall before unlock),
      - early-exit penalty (cost to access liquidity sooner),
    then blends with any immediately-liquid unlock fraction::

        locked_factor = time_value * price_risk * early_exit
        factor = liquid_fraction * 1.0 + (1 - liquid_fraction) * locked_factor

    ``liquid_unlock_fraction`` (0..1) is the share of rewards already liquid on
    receipt (e.g. 30% liquid, 70% vested). Defensive: fraction clamped [0,1];
    all sub-factors are in [0,1].
    """
    lf = _clamp(liquid_unlock_fraction, 0.0, 1.0)
    tv = _time_value_factor(lockup_days, discount_rate_pct)
    pr = _price_risk_factor(lockup_days, annual_vol_pct)
    ee = _early_exit_factor(early_exit_penalty_pct)
    locked_factor = max(0.0, tv * pr * ee)
    factor = lf * 1.0 + (1.0 - lf) * locked_factor
    return _clamp(factor, 0.0, 1.0)


def _realisable_reward_apr_pct(
    reward_apr_pct: float,
    lockup_discount_factor: float,
) -> float:
    """Reward APR after applying the lockup discount factor (>= 0)."""
    return max(0.0, reward_apr_pct) * _clamp(lockup_discount_factor, 0.0, 1.0)


def _lockup_adjusted_apr_pct(
    liquid_apr_pct: float,
    realisable_reward_apr_pct: float,
) -> float:
    """Total realisable APR: liquid APR plus discounted reward APR."""
    return max(0.0, liquid_apr_pct) + max(0.0, realisable_reward_apr_pct)


def _headline_vs_realisable_gap_pct(
    total_apr_pct: float,
    lockup_adjusted_apr_pct: float,
) -> float:
    """Headline minus realisable APR — the 'paper yield' the headline overstates."""
    return max(0.0, total_apr_pct - lockup_adjusted_apr_pct)


def _paper_yield_share_pct(
    headline_vs_realisable_gap_pct: float,
    total_apr_pct: float,
) -> float:
    """
    Share of the headline APR that is 'paper' (lost to the lockup discount).

        share = gap / total_apr * 100

    Defensive: total ~0 => 0.0; clamped to [0, 100].
    """
    if total_apr_pct <= _EPS:
        return 0.0
    return _clamp(headline_vs_realisable_gap_pct / total_apr_pct * 100.0, 0.0, 100.0)


def _reward_realisability_score(
    lockup_discount_factor: float,
    reward_share_of_apr_pct: float,
    paper_yield_share_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = rewards are closer to liquid / headline APR is closer to real.

    Blends three drivers:
    - discount-factor (0-50): the retention factor itself scaled to 50; a fully
      liquid reward (factor 1.0) earns the full 50.
    - inverse paper-yield-share (0-30): one minus the share of headline lost to
      the discount; small paper yield earns the full 30.
    - reward-weight tempering (0-20): a position whose APR is mostly *liquid*
      (low reward share) is penalised less by any discount, earning up to 20 as
      the reward share falls.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    factor = _clamp(lockup_discount_factor, 0.0, 1.0)
    factor_component = factor * 50.0

    paper_share = _clamp(paper_yield_share_pct / 100.0, 0.0, 1.0)
    paper_component = (1.0 - paper_share) * 30.0

    reward_share = _clamp(reward_share_of_apr_pct / 100.0, 0.0, 1.0)
    weight_component = (1.0 - reward_share) * 20.0

    return _clamp(factor_component + paper_component + weight_component)


def _classify(lockup_discount_factor: float, has_data: bool) -> str:
    """
    Assign an advisory classification band on the lockup discount factor.

      >= 0.95 -> FULLY_LIQUID
      >= 0.80 -> LIGHTLY_LOCKED
      >= 0.60 -> MODERATELY_LOCKED
      >= 0.40 -> HEAVILY_LOCKED
      <  0.40 -> DEEPLY_LOCKED

    No data falls back to DEEPLY_LOCKED (cannot demonstrate liquidity).
    """
    if not has_data:
        return CLASS_DEEPLY_LOCKED

    f = lockup_discount_factor
    if f >= 0.95:
        return CLASS_FULLY_LIQUID
    if f >= 0.80:
        return CLASS_LIGHTLY_LOCKED
    if f >= 0.60:
        return CLASS_MODERATELY_LOCKED
    if f >= 0.40:
        return CLASS_HEAVILY_LOCKED
    return CLASS_DEEPLY_LOCKED


def _grade(reward_realisability_score: float) -> str:
    """Map reward_realisability_score (higher = better) to an A-F letter grade."""
    s = reward_realisability_score
    if s >= 90.0:
        return "A"
    if s >= 70.0:
        return "B"
    if s >= 50.0:
        return "C"
    if s >= 30.0:
        return "D"
    return "F"


def _flags(
    lockup_days: float,
    early_exit_penalty_pct: float,
    reward_share_of_apr_pct: float,
    paper_yield_share_pct: float,
    annual_vol_pct: float,
    lockup_discount_factor: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if lockup_days >= _LONG_LOCKUP_DAYS:
        flags.append(FLAG_LONG_LOCKUP)

    if early_exit_penalty_pct >= _HIGH_EARLY_EXIT_PENALTY_PCT:
        flags.append(FLAG_HIGH_EARLY_EXIT_PENALTY)

    if reward_share_of_apr_pct >= _REWARD_DOMINATED_SHARE_PCT:
        flags.append(FLAG_REWARD_DOMINATED_APR)

    if paper_yield_share_pct >= _LARGE_PAPER_YIELD_SHARE_PCT:
        flags.append(FLAG_LARGE_PAPER_YIELD)

    if annual_vol_pct >= _HIGH_PRICE_RISK_VOL_PCT:
        flags.append(FLAG_HIGH_PRICE_RISK)

    if lockup_discount_factor >= _MOSTLY_LIQUID_DISCOUNT:
        flags.append(FLAG_MOSTLY_LIQUID)

    if lockup_discount_factor <= _DEEP_DISCOUNT_FACTOR:
        flags.append(FLAG_DEEP_DISCOUNT)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    total_apr_pct: float,
    lockup_adjusted_apr_pct: float,
    headline_vs_realisable_gap_pct: float,
    lockup_days: float,
    early_exit_penalty_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no APR/lockup signal or data marked "
            "unreliable. Cannot assess reward-lockup discount for this position."
        )
        return recs

    if classification == CLASS_DEEPLY_LOCKED:
        recs.append(
            f"Deeply locked: the realisable APR is only ~"
            f"{lockup_adjusted_apr_pct:.2f}% versus a ~{total_apr_pct:.2f}% "
            "headline. Most of the advertised yield is paper; treat this as a "
            "long-horizon, high-conviction bet on the reward token."
        )
    elif classification == CLASS_HEAVILY_LOCKED:
        recs.append(
            f"Heavily locked: realisable APR ~{lockup_adjusted_apr_pct:.2f}% "
            f"vs ~{total_apr_pct:.2f}% headline. The lockup discount is large; "
            "size accordingly."
        )
    elif classification == CLASS_MODERATELY_LOCKED:
        recs.append(
            f"Moderately locked: realisable APR ~{lockup_adjusted_apr_pct:.2f}% "
            f"vs ~{total_apr_pct:.2f}% headline. A meaningful share of the "
            "yield is discounted for the lockup."
        )
    elif classification == CLASS_LIGHTLY_LOCKED:
        recs.append(
            f"Lightly locked: realisable APR ~{lockup_adjusted_apr_pct:.2f}% "
            f"is close to the ~{total_apr_pct:.2f}% headline; the lockup is a "
            "modest drag."
        )
    else:  # FULLY_LIQUID
        recs.append(
            f"Effectively liquid rewards: realisable APR ~"
            f"{lockup_adjusted_apr_pct:.2f}% tracks the ~{total_apr_pct:.2f}% "
            "headline closely."
        )

    if FLAG_LONG_LOCKUP in flags:
        recs.append(
            f"Long lockup: rewards are escrowed for ~{lockup_days:.0f} days. "
            "Time-value and price risk over that horizon materially discount "
            "the reward token."
        )

    if FLAG_HIGH_EARLY_EXIT_PENALTY in flags:
        recs.append(
            f"High early-exit penalty (~{early_exit_penalty_pct:.0f}%): if you "
            "may need liquidity before unlock, the effective value of locked "
            "rewards is well below their spot mark."
        )

    if FLAG_REWARD_DOMINATED_APR in flags:
        recs.append(
            "Reward-dominated APR: most of the headline yield is paid in the "
            "illiquid reward token, so the lockup discount drives the real "
            "return."
        )

    if FLAG_LARGE_PAPER_YIELD in flags:
        recs.append(
            f"Large paper yield: ~{headline_vs_realisable_gap_pct:.2f} points "
            "of the headline APR are lost to the lockup discount and may never "
            "be realised at the marked value."
        )

    if FLAG_HIGH_PRICE_RISK in flags:
        recs.append(
            "High reward-token volatility: the locked rewards carry large "
            "price risk before they unlock; hedge or discount further."
        )

    if FLAG_MOSTLY_LIQUID in flags and classification == CLASS_FULLY_LIQUID:
        recs.append(
            "Rewards are largely liquid on receipt: the headline APR is a fair "
            "approximation of the realisable return."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    total_apr_pct: float | None = None,
    liquid_apr_pct: float | None = None,
    reward_apr_pct: float | None = None,
    lockup_days: float | None = None,
    discount_rate_pct: float | None = None,
    annual_vol_pct: float | None = None,
    early_exit_penalty_pct: float | None = None,
    liquid_unlock_fraction: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the reward-token lockup discount of a single yield position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    APR decomposition: provide any two of ``total_apr_pct`` / ``liquid_apr_pct``
    / ``reward_apr_pct`` and the third is derived; if only ``total_apr_pct`` and
    ``reward_apr_pct`` are given, the liquid APR is total - reward (floored 0).
    If only ``liquid_apr_pct`` and ``reward_apr_pct`` are given, total is their
    sum. Defaults are 0.

    Recognised keys / keywords (all with safe defaults):
    - name                   : str
    - total_apr_pct          : float (headline APR)
    - liquid_apr_pct         : float (APR paid in liquid assets)
    - reward_apr_pct         : float (APR paid in the illiquid reward token)
    - lockup_days            : float (escrow / vesting horizon)
    - discount_rate_pct      : float (annual time-value rate, default 15)
    - annual_vol_pct         : float (reward-token annual volatility)
    - early_exit_penalty_pct : float (penalty to unlock early, 0-100)
    - liquid_unlock_fraction : float (0..1 share liquid on receipt)
    - data_quality           : truthy/"ok" => trusted; falsy/"poor" => not

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    t = token if isinstance(token, dict) else {}

    def _present(kw: Any, key: str) -> bool:
        return kw is not None or key in t

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(t.get(key, default), default)

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    has_total = _present(total_apr_pct, "total_apr_pct")
    has_liquid = _present(liquid_apr_pct, "liquid_apr_pct")
    has_reward = _present(reward_apr_pct, "reward_apr_pct")

    total_in = _pick(total_apr_pct, "total_apr_pct", 0.0)
    liquid_in = _pick(liquid_apr_pct, "liquid_apr_pct", 0.0)
    reward_in = _pick(reward_apr_pct, "reward_apr_pct", 0.0)

    # Reconcile the APR decomposition defensively.
    if has_total and has_reward and not has_liquid:
        total = max(0.0, total_in)
        reward = _clamp(reward_in, 0.0, total) if total > 0 else max(0.0, reward_in)
        liquid = max(0.0, total - reward)
    elif has_liquid and has_reward and not has_total:
        liquid = max(0.0, liquid_in)
        reward = max(0.0, reward_in)
        total = liquid + reward
    elif has_total and has_liquid and not has_reward:
        total = max(0.0, total_in)
        liquid = _clamp(liquid_in, 0.0, total) if total > 0 else max(0.0, liquid_in)
        reward = max(0.0, total - liquid)
    else:
        # All three (or fewer) given: trust liquid + reward, recompute total to
        # keep the identity total = liquid + reward.
        liquid = max(0.0, liquid_in)
        reward = max(0.0, reward_in)
        if has_total and not (has_liquid or has_reward):
            # Only total given: assume all reward (worst-case illiquidity).
            total = max(0.0, total_in)
            reward = total
            liquid = 0.0
        else:
            total = liquid + reward

    lockup_days_v = max(0.0, _pick(lockup_days, "lockup_days", 0.0))
    discount_rate = max(0.0, _pick(discount_rate_pct, "discount_rate_pct",
                                   _DEFAULT_DISCOUNT_RATE_PCT))
    annual_vol = max(0.0, _pick(annual_vol_pct, "annual_vol_pct", 0.0))
    early_exit = _clamp(_pick(early_exit_penalty_pct, "early_exit_penalty_pct", 0.0),
                        0.0, 100.0)
    liquid_unlock = _clamp(_pick(liquid_unlock_fraction, "liquid_unlock_fraction", 0.0),
                           0.0, 1.0)

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need some APR signal, and the data-quality flag must not
    # mark the inputs as unreliable.
    has_signal = total > _EPS or reward > _EPS or liquid > _EPS
    has_data = has_signal and data_quality_ok

    reward_share = _reward_share_of_apr_pct(reward, total)
    discount_factor = _lockup_discount_factor(
        lockup_days_v, discount_rate, annual_vol, early_exit, liquid_unlock
    )
    realisable_reward = _realisable_reward_apr_pct(reward, discount_factor)
    adjusted_apr = _lockup_adjusted_apr_pct(liquid, realisable_reward)
    gap = _headline_vs_realisable_gap_pct(total, adjusted_apr)
    paper_share = _paper_yield_share_pct(gap, total)
    classification = _classify(discount_factor, has_data)
    score = _reward_realisability_score(
        discount_factor, reward_share, paper_share, has_data
    )
    grade = _grade(score)
    flags = _flags(
        lockup_days_v,
        early_exit,
        reward_share,
        paper_share,
        annual_vol,
        discount_factor,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        total,
        adjusted_apr,
        gap,
        lockup_days_v,
        early_exit,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "total_apr_pct": total,
        "liquid_apr_pct": liquid,
        "reward_apr_pct": reward,
        "lockup_days": lockup_days_v,
        "discount_rate_pct": discount_rate,
        "annual_vol_pct": annual_vol,
        "early_exit_penalty_pct": early_exit,
        "liquid_unlock_fraction": liquid_unlock,
        "data_quality_ok": data_quality_ok,
        "reward_share_of_apr_pct": reward_share,
        "lockup_discount_factor": discount_factor,
        "realisable_reward_apr_pct": realisable_reward,
        "lockup_adjusted_apr_pct": adjusted_apr,
        "headline_vs_realisable_gap_pct": gap,
        "paper_yield_share_pct": paper_share,
        "reward_realisability_score": score,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(positions: list, config: dict | None = None) -> dict:
    """
    Analyse reward-lockup discount across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions               : int
        - results                       : list[dict]  (per-position analysis)
        - most_realisable_position      : str | None  (highest realisability)
        - least_realisable_position     : str | None  (lowest realisability)
        - avg_reward_realisability_score: float
        - deeply_locked_count           : int
        - timestamp                     : float
    """
    if not isinstance(positions, list):
        positions = []

    results = [
        analyze(p if isinstance(p, dict) else {}, config=config)
        for p in positions
    ]
    total = len(results)

    if total == 0:
        return {
            "total_positions": 0,
            "results": [],
            "most_realisable_position": None,
            "least_realisable_position": None,
            "avg_reward_realisability_score": 0.0,
            "deeply_locked_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["reward_realisability_score"])
    least = min(results, key=lambda r: r["reward_realisability_score"])
    avg = sum(r["reward_realisability_score"] for r in results) / total
    deep = sum(
        1 for r in results if r["classification"] == CLASS_DEEPLY_LOCKED
    )

    return {
        "total_positions": total,
        "results": results,
        "most_realisable_position": most["name"],
        "least_realisable_position": least["name"],
        "avg_reward_realisability_score": avg,
        "deeply_locked_count": deep,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiRewardTokenLockupDiscountAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = ProtocolDeFiRewardTokenLockupDiscountAnalyzer()
    >>> r = a.analyze({"name": "veCRV farm", "total_apr_pct": 40.0,
    ...                "reward_apr_pct": 32.0, "lockup_days": 730.0,
    ...                "early_exit_penalty_pct": 50.0})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, token: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(token, config=self._config, **kwargs)

    def analyze_portfolio(self, positions: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(positions, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_positions = [
        {
            "name": "veCRV farm (locked, penalised)",
            "total_apr_pct": 40.0,
            "reward_apr_pct": 32.0,
            "lockup_days": 730.0,
            "annual_vol_pct": 90.0,
            "early_exit_penalty_pct": 50.0,
            "liquid_unlock_fraction": 0.0,
        },
        {
            "name": "stable LP (mostly liquid)",
            "total_apr_pct": 8.0,
            "reward_apr_pct": 2.0,
            "lockup_days": 7.0,
            "annual_vol_pct": 20.0,
            "early_exit_penalty_pct": 0.0,
            "liquid_unlock_fraction": 0.5,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
