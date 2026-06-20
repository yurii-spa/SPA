"""
MP-1144  DeFiProtocolRewardClaimTimingOptimizer
-----------------------------------------------
Decide *when* to claim accrued, unclaimed yield-farming rewards. Claiming is not
free: each claim costs a fixed amount of gas, so claiming a tiny accrued balance
wastes most of it on gas. But waiting is not free either: while rewards sit
unclaimed they (a) are exposed to the reward-token's price volatility (you hold
an un-hedged, un-sold position that can drop before you ever realise it), and
(b) cannot be reinvested/compounded at the position's reinvestment APR. This
module weighs the fixed claim gas against those two costs of waiting and judges
whether a position is "mature" enough to claim now or should keep accumulating.

For a single position the module computes:
- the gas-to-accrued ratio (what share of the accrued balance the claim gas
  would eat right now),
- the *optimal claim threshold*: the accrued balance at which the claim gas
  drops to an acceptable gas-drag percentage,
- the *expected days to threshold* at the current accrual rate (accounting for
  what has already accrued),
- a recommended claim frequency (days between claims) consistent with the
  threshold,
- the *price-risk haircut*: the volatility cost of holding the unclaimed reward
  token until the threshold (vol * sqrt(time)),
- the *opportunity cost*: the reinvestment income foregone on the already-
  accrued balance while waiting,
- the *net benefit of claiming now*: reinvestment benefit + avoided price risk
  minus the claim gas,
- a 0-100 *claim-timing score* (higher = the position is mature / claiming now
  is sensible).

Genuine gap: existing modules cover round-trip entry/exit gas breakeven
(`defi_protocol_gas_cost_breakeven_analyzer`, which is about whether to *open* a
position at all) and reward-token lock-up discounting (the haircut for locking a
reward), but none isolates the *claim-timing* trade-off for already-accruing
rewards: fixed claim gas vs. the price-risk and reinvestment-opportunity cost of
leaving rewards unclaimed. A grep for "claim_timing" / "reward_claim" across the
analytics package confirms no existing module covers this angle.

The module returns:
- name (input echo) and the input echoes
- gas_to_accrued_ratio_pct       - claim gas as a share of accrued, now
- optimal_claim_threshold_usd    - accrued at which gas-drag hits the target
- expected_days_to_threshold     - days to reach the threshold at current accrual
- recommended_claim_frequency_days - claim cadence consistent with the threshold
- price_risk_haircut_pct         - vol cost of holding until threshold
- opportunity_cost_usd           - reinvest income foregone on the accrued
- net_benefit_of_claiming_now_usd - net dollar benefit of claiming right now
- claim_timing_score             - 0-100, higher = claim now / position mature
- classification                 - CLAIM_NOW .. TOO_SMALL_TO_CLAIM
- grade                          - A-F letter grade
- flags / recommendations        - advisory verdicts

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
    "reward_claim_timing_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "never reaches threshold / no accrual" (keeps JSON finite).
DAYS_SENTINEL_NEVER = 1e9

# Sentinel for "gas dwarfs accrued" gas-to-accrued ratio (no inf in JSON).
GAS_RATIO_SENTINEL = 999.0

_DAYS_PER_YEAR = 365.0

# Defaults.
_DEFAULT_REWARD_TOKEN_VOLATILITY_PCT = 60.0   # annualised vol of reward token
_DEFAULT_REINVESTMENT_APR_PCT = 5.0           # rate accrued could be reinvested
_DEFAULT_TARGET_GAS_DRAG_PCT = 2.0            # acceptable gas drag at claim time

# Classification bands
CLASS_CLAIM_NOW = "CLAIM_NOW"
CLASS_CLAIM_SOON = "CLAIM_SOON"
CLASS_ACCUMULATE = "ACCUMULATE"
CLASS_TOO_SMALL_TO_CLAIM = "TOO_SMALL_TO_CLAIM"
CLASS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_CLASSIFICATIONS = (
    CLASS_CLAIM_NOW,
    CLASS_CLAIM_SOON,
    CLASS_ACCUMULATE,
    CLASS_TOO_SMALL_TO_CLAIM,
    CLASS_INSUFFICIENT_DATA,
)

# Flags
FLAG_CLAIM_NOW = "CLAIM_NOW"
FLAG_GAS_EXCEEDS_REWARD = "GAS_EXCEEDS_REWARD"
FLAG_BELOW_THRESHOLD = "BELOW_THRESHOLD"
FLAG_HIGH_PRICE_RISK = "HIGH_PRICE_RISK"
FLAG_HIGH_OPPORTUNITY_COST = "HIGH_OPPORTUNITY_COST"
FLAG_FREQUENT_CLAIMING_WASTEFUL = "FREQUENT_CLAIMING_WASTEFUL"
FLAG_MATURE_FOR_CLAIM = "MATURE_FOR_CLAIM"
FLAG_ACCRUAL_STALLED = "ACCRUAL_STALLED"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_CLAIM_NOW,
    FLAG_GAS_EXCEEDS_REWARD,
    FLAG_BELOW_THRESHOLD,
    FLAG_HIGH_PRICE_RISK,
    FLAG_HIGH_OPPORTUNITY_COST,
    FLAG_FREQUENT_CLAIMING_WASTEFUL,
    FLAG_MATURE_FOR_CLAIM,
    FLAG_ACCRUAL_STALLED,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_GAS_EXCEEDS_REWARD_RATIO_PCT = 100.0   # gas >= 100% of accrued -> wasteful now
_MATURE_ACCRUED_RATIO = 1.0             # accrued >= threshold -> mature
_CLAIM_NOW_ACCRUED_RATIO = 1.0          # accrued >= threshold -> claim now
_CLAIM_SOON_ACCRUED_RATIO = 0.5         # accrued >= 50% of threshold -> soon
_HIGH_PRICE_RISK_PCT = 15.0             # haircut >= 15% -> high price risk
_HIGH_OPPORTUNITY_COST_USD = 1.0        # opp cost >= $1 -> high
_FREQUENT_CLAIM_FREQ_DAYS = 1.0         # recommended cadence < 1 day -> wasteful
_TOO_SMALL_ACCRUED_USD = 1e-6           # essentially no accrued
_PRICE_RISK_HAIRCUT_CAP_PCT = 200.0     # cap reported haircut (keep finite)


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

def _gas_to_accrued_ratio_pct(
    claim_gas_cost_usd: float,
    accrued_reward_usd: float,
) -> float:
    """
    Claim gas as a share of the currently accrued reward, in pct.

        ratio = claim_gas / accrued * 100

    Defensive: when the accrued balance is ~0 the ratio is effectively infinite
    — report the GAS_RATIO_SENTINEL (999.0) so JSON stays finite. When both are
    ~0 the ratio is 0.0.
    """
    gas = max(0.0, claim_gas_cost_usd)
    accrued = max(0.0, accrued_reward_usd)
    if accrued <= _EPS:
        return 0.0 if gas <= _EPS else GAS_RATIO_SENTINEL
    return gas / accrued * 100.0


def _optimal_claim_threshold_usd(
    claim_gas_cost_usd: float,
    target_gas_drag_pct: float,
) -> float:
    """
    Accrued balance at which the claim gas drops to the acceptable gas-drag.

        threshold = claim_gas / (target_gas_drag_pct / 100)

    i.e. if you want the gas to be only ``target_gas_drag_pct`` percent of the
    claimed amount, you must accrue at least this much before claiming.

    Defensive: a non-positive target drag yields the GAS_RATIO_SENTINEL-scaled
    sentinel (effectively "never acceptable") — return DAYS_SENTINEL_NEVER-style
    large value? No: keep it a USD figure, so return a large sentinel only when
    gas is positive; when gas is ~0 the threshold is 0.0 (any amount is fine).
    """
    gas = max(0.0, claim_gas_cost_usd)
    if gas <= _EPS:
        return 0.0
    drag = target_gas_drag_pct
    if drag <= _EPS:
        return DAYS_SENTINEL_NEVER
    return gas / (drag / 100.0)


def _expected_days_to_threshold(
    optimal_claim_threshold_usd: float,
    accrued_reward_usd: float,
    daily_accrual_usd: float,
) -> float:
    """
    Days to reach the optimal claim threshold at the current accrual rate,
    crediting what has already accrued.

        remaining = max(0, threshold - accrued)
        days = remaining / daily_accrual

    Defensive: when the daily accrual is <= 0 the threshold is never reached
    (return DAYS_SENTINEL_NEVER) unless the accrued already meets the threshold
    (return 0.0).
    """
    threshold = max(0.0, optimal_claim_threshold_usd)
    accrued = max(0.0, accrued_reward_usd)
    remaining = max(0.0, threshold - accrued)
    if remaining <= _EPS:
        return 0.0
    accrual = daily_accrual_usd
    if accrual <= _EPS:
        return DAYS_SENTINEL_NEVER
    return remaining / accrual


def _recommended_claim_frequency_days(
    optimal_claim_threshold_usd: float,
    daily_accrual_usd: float,
) -> float:
    """
    Recommended claim cadence (days between claims) consistent with always
    claiming at the threshold.

        frequency = threshold / daily_accrual

    Defensive: a non-positive accrual means no natural cadence — return
    DAYS_SENTINEL_NEVER. A ~0 threshold yields 0.0.
    """
    threshold = max(0.0, optimal_claim_threshold_usd)
    if threshold <= _EPS:
        return 0.0
    accrual = daily_accrual_usd
    if accrual <= _EPS:
        return DAYS_SENTINEL_NEVER
    return threshold / accrual


def _price_risk_haircut_pct(
    reward_token_volatility_pct: float,
    days_to_threshold: float,
) -> float:
    """
    Price-risk cost of holding the unclaimed reward token until the threshold,
    using a volatility-scales-with-sqrt-time model.

        haircut = annual_vol * sqrt(days / 365)

    Defensive: a non-positive horizon or non-positive vol yields 0.0; the
    sentinel "never reaches threshold" horizon is treated as a long but bounded
    exposure (cap the reported haircut at _PRICE_RISK_HAIRCUT_CAP_PCT so the
    figure stays finite and sensible).
    """
    vol = max(0.0, reward_token_volatility_pct)
    days = max(0.0, days_to_threshold)
    if vol <= _EPS or days <= _EPS:
        return 0.0
    if days >= DAYS_SENTINEL_NEVER:
        return _PRICE_RISK_HAIRCUT_CAP_PCT
    years = days / _DAYS_PER_YEAR
    haircut = vol * math.sqrt(max(0.0, years))
    return min(_PRICE_RISK_HAIRCUT_CAP_PCT, haircut)


def _opportunity_cost_usd(
    accrued_reward_usd: float,
    reinvestment_apr_pct: float,
    days_to_threshold: float,
) -> float:
    """
    Reinvestment income foregone on the *already accrued* balance while waiting
    to reach the threshold.

        opp_cost = accrued * (reinvest_apr/100) * (days / 365)

    Defensive: clamps accrued and days at 0; the "never" horizon is treated as a
    bounded one-year exposure so the figure stays finite.
    """
    accrued = max(0.0, accrued_reward_usd)
    days = max(0.0, days_to_threshold)
    if days >= DAYS_SENTINEL_NEVER:
        days = _DAYS_PER_YEAR  # bound the foregone window at one year
    return accrued * (reinvestment_apr_pct / 100.0) * (days / _DAYS_PER_YEAR)


def _net_benefit_of_claiming_now_usd(
    accrued_reward_usd: float,
    reinvestment_apr_pct: float,
    days_to_threshold: float,
    price_risk_haircut_pct: float,
    claim_gas_cost_usd: float,
) -> float:
    """
    Net dollar benefit of claiming the accrued balance *now* rather than waiting
    to the threshold.

        reinvest_benefit = opportunity cost recovered by claiming now
        risk_avoided     = haircut% * accrued (price exposure removed)
        net = reinvest_benefit + risk_avoided - claim_gas

    A large already-accrued balance makes claiming now worthwhile (positive
    net); a tiny balance makes the gas dominate (negative net).
    """
    accrued = max(0.0, accrued_reward_usd)
    reinvest_benefit = _opportunity_cost_usd(
        accrued, reinvestment_apr_pct, days_to_threshold
    )
    risk_avoided = accrued * (max(0.0, price_risk_haircut_pct) / 100.0)
    gas = max(0.0, claim_gas_cost_usd)
    return reinvest_benefit + risk_avoided - gas


def _claim_timing_score(
    accrued_reward_usd: float,
    optimal_claim_threshold_usd: float,
    gas_to_accrued_ratio_pct: float,
    price_risk_haircut_pct: float,
    opportunity_cost_usd: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = the position is mature / claiming now is sensible.

    Blends four drivers:
    - maturity component (0-55): how close the accrued balance is to the optimal
      claim threshold; full 55 at/above threshold, 0 at ~0 accrued.
    - low-gas-drag component (0-20): full 20 when the gas is a tiny share of the
      accrued balance now; 0 when gas >= accrued.
    - price-risk component (0-15): higher unclaimed price risk pushes toward
      claiming; full 15 at/above the high-price-risk mark.
    - opportunity component (0-10): higher foregone reinvest income pushes toward
      claiming; full 10 at/above the high-opportunity mark.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    threshold = max(0.0, optimal_claim_threshold_usd)
    accrued = max(0.0, accrued_reward_usd)

    # Maturity component (0..55).
    if threshold <= _EPS:
        maturity_ratio = 1.0
    elif threshold >= DAYS_SENTINEL_NEVER:
        maturity_ratio = 0.0
    else:
        maturity_ratio = _clamp(accrued / threshold, 0.0, 1.0)
    maturity_component = maturity_ratio * 55.0

    # Low-gas-drag component (0..20): invert gas/accrued ratio capped at 100%.
    drag_share = _clamp(gas_to_accrued_ratio_pct / 100.0, 0.0, 1.0)
    gas_component = (1.0 - drag_share) * 20.0

    # Price-risk component (0..15).
    risk_ratio = _clamp(price_risk_haircut_pct / _HIGH_PRICE_RISK_PCT, 0.0, 1.0)
    risk_component = risk_ratio * 15.0

    # Opportunity component (0..10).
    opp_ratio = _clamp(
        opportunity_cost_usd / _HIGH_OPPORTUNITY_COST_USD, 0.0, 1.0
    )
    opp_component = opp_ratio * 10.0

    return _clamp(
        maturity_component + gas_component + risk_component + opp_component
    )


def _classify(
    accrued_reward_usd: float,
    optimal_claim_threshold_usd: float,
    gas_to_accrued_ratio_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band.

      no data                                   -> INSUFFICIENT_DATA
      accrued ~0 / gas dwarfs accrued           -> TOO_SMALL_TO_CLAIM
      accrued >= threshold                      -> CLAIM_NOW
      accrued >= 50% of threshold               -> CLAIM_SOON
      otherwise                                 -> ACCUMULATE
    """
    if not has_data:
        return CLASS_INSUFFICIENT_DATA

    accrued = max(0.0, accrued_reward_usd)
    threshold = max(0.0, optimal_claim_threshold_usd)

    # Too small: essentially nothing accrued, or gas eats the whole balance and
    # the balance is well below the threshold.
    if accrued <= _TOO_SMALL_ACCRUED_USD:
        return CLASS_TOO_SMALL_TO_CLAIM

    if threshold <= _EPS:
        # No meaningful threshold (no gas) -> claiming is essentially free.
        return CLASS_CLAIM_NOW

    if threshold >= DAYS_SENTINEL_NEVER:
        # Threshold never acceptable (target drag ~0); treat as accumulate.
        return CLASS_ACCUMULATE

    ratio = accrued / threshold
    if ratio >= _CLAIM_NOW_ACCRUED_RATIO:
        return CLASS_CLAIM_NOW
    if (gas_to_accrued_ratio_pct >= _GAS_EXCEEDS_REWARD_RATIO_PCT
            and ratio < _CLAIM_SOON_ACCRUED_RATIO):
        return CLASS_TOO_SMALL_TO_CLAIM
    if ratio >= _CLAIM_SOON_ACCRUED_RATIO:
        return CLASS_CLAIM_SOON
    return CLASS_ACCUMULATE


def _grade(claim_timing_score: float) -> str:
    """Map claim_timing_score (higher = more mature) to an A-F letter grade."""
    s = claim_timing_score
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
    accrued_reward_usd: float,
    optimal_claim_threshold_usd: float,
    gas_to_accrued_ratio_pct: float,
    price_risk_haircut_pct: float,
    opportunity_cost_usd: float,
    recommended_claim_frequency_days: float,
    daily_accrual_usd: float,
    net_benefit_of_claiming_now_usd: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    accrued = max(0.0, accrued_reward_usd)
    threshold = max(0.0, optimal_claim_threshold_usd)

    if classification == CLASS_CLAIM_NOW:
        flags.append(FLAG_CLAIM_NOW)

    if gas_to_accrued_ratio_pct >= _GAS_EXCEEDS_REWARD_RATIO_PCT:
        flags.append(FLAG_GAS_EXCEEDS_REWARD)

    # Below threshold: accrued has not yet reached the optimal claim size.
    if (threshold > _EPS and threshold < DAYS_SENTINEL_NEVER
            and accrued < threshold):
        flags.append(FLAG_BELOW_THRESHOLD)

    if price_risk_haircut_pct >= _HIGH_PRICE_RISK_PCT:
        flags.append(FLAG_HIGH_PRICE_RISK)

    if opportunity_cost_usd >= _HIGH_OPPORTUNITY_COST_USD:
        flags.append(FLAG_HIGH_OPPORTUNITY_COST)

    # Frequent claiming wasteful: the natural cadence is sub-daily, i.e. the
    # threshold is reached very fast relative to gas (over-claiming).
    if (recommended_claim_frequency_days < _FREQUENT_CLAIM_FREQ_DAYS
            and recommended_claim_frequency_days > _EPS):
        flags.append(FLAG_FREQUENT_CLAIMING_WASTEFUL)

    # Mature for claim: the accrued balance is at/above the threshold.
    if (threshold > _EPS and threshold < DAYS_SENTINEL_NEVER
            and accrued >= threshold * _MATURE_ACCRUED_RATIO):
        flags.append(FLAG_MATURE_FOR_CLAIM)
    elif threshold <= _EPS and accrued > _TOO_SMALL_ACCRUED_USD:
        flags.append(FLAG_MATURE_FOR_CLAIM)

    # Accrual stalled: there is an accrued balance but no daily accrual.
    if daily_accrual_usd <= _EPS and accrued > _TOO_SMALL_ACCRUED_USD:
        flags.append(FLAG_ACCRUAL_STALLED)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    accrued_reward_usd: float,
    claim_gas_cost_usd: float,
    optimal_claim_threshold_usd: float,
    expected_days_to_threshold: float,
    price_risk_haircut_pct: float,
    opportunity_cost_usd: float,
    net_benefit_of_claiming_now_usd: float,
    recommended_claim_frequency_days: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no accrued-reward / gas signal or data marked "
            "unreliable. Cannot assess reward-claim timing for this position."
        )
        return recs

    if classification == CLASS_CLAIM_NOW:
        recs.append(
            f"Claim now: ~${accrued_reward_usd:,.2f} has accrued, at/above the "
            f"~${optimal_claim_threshold_usd:,.2f} threshold where the "
            f"~${claim_gas_cost_usd:,.2f} claim gas is a small drag. Realise it "
            "and reinvest."
        )
    elif classification == CLASS_CLAIM_SOON:
        recs.append(
            f"Claim soon: ~${accrued_reward_usd:,.2f} accrued is past halfway to "
            f"the ~${optimal_claim_threshold_usd:,.2f} threshold "
            f"(~{expected_days_to_threshold:.1f} more days at the current "
            "accrual). Claiming is close to optimal."
        )
    elif classification == CLASS_ACCUMULATE:
        recs.append(
            f"Accumulate: ~${accrued_reward_usd:,.2f} accrued is well below the "
            f"~${optimal_claim_threshold_usd:,.2f} threshold "
            f"(~{expected_days_to_threshold:.1f} days away). Let it grow so the "
            "claim gas is a smaller share."
        )
    else:  # TOO_SMALL_TO_CLAIM
        recs.append(
            f"Too small to claim: ~${accrued_reward_usd:,.2f} accrued does not "
            f"justify the ~${claim_gas_cost_usd:,.2f} claim gas. Wait for the "
            "balance to build up materially before claiming."
        )

    if FLAG_GAS_EXCEEDS_REWARD in flags:
        recs.append(
            "Gas exceeds reward: the claim gas is at least as large as the "
            "accrued balance. Claiming now would cost more than it realises."
        )

    if FLAG_HIGH_PRICE_RISK in flags:
        recs.append(
            f"High price risk: holding the unclaimed reward token until the "
            f"threshold carries ~{price_risk_haircut_pct:.1f}% volatility "
            "exposure. Consider claiming earlier to lock in value."
        )

    if FLAG_HIGH_OPPORTUNITY_COST in flags:
        recs.append(
            f"High opportunity cost: ~${opportunity_cost_usd:,.2f} of "
            "reinvestment income is foregone while the accrued balance sits "
            "unclaimed. Claiming and compounding sooner recovers it."
        )

    if FLAG_FREQUENT_CLAIMING_WASTEFUL in flags:
        recs.append(
            f"Frequent claiming wasteful: a cadence of "
            f"~{recommended_claim_frequency_days:.2f} days implies over-claiming "
            "tiny amounts. Batch claims to a sensible interval to save gas."
        )

    if FLAG_ACCRUAL_STALLED in flags:
        recs.append(
            "Accrual stalled: there is an accrued balance but no measured daily "
            "accrual. Verify the position is still earning before deciding."
        )

    if net_benefit_of_claiming_now_usd > 0.0 and classification != CLASS_CLAIM_NOW:
        recs.append(
            f"Net benefit of claiming now is positive (~"
            f"${net_benefit_of_claiming_now_usd:,.2f}): the avoided price risk "
            "plus recovered reinvestment income outweigh the claim gas."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    accrued_reward_usd: float | None = None,
    daily_accrual_usd: float | None = None,
    claim_gas_cost_usd: float | None = None,
    reward_token_volatility_pct: float | None = None,
    reinvestment_apr_pct: float | None = None,
    days_since_last_claim: float | None = None,
    target_gas_drag_pct: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the reward-claim timing of a single yield position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                          : str
    - accrued_reward_usd            : float (currently unclaimed reward, USD)
    - daily_accrual_usd             : float (reward accruing per day, USD)
    - claim_gas_cost_usd            : float (fixed gas cost of a claim, USD)
    - reward_token_volatility_pct   : float (annual vol, default 60)
    - reinvestment_apr_pct          : float (rate accrued could compound, def 5)
    - days_since_last_claim         : float (optional, informational)
    - target_gas_drag_pct           : float (acceptable gas drag, default 2)
    - data_quality                  : truthy/"ok" => trusted; falsy/"poor"

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

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(t.get(key, default), default)

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    accrued = max(0.0, _pick(accrued_reward_usd, "accrued_reward_usd", 0.0))
    daily_accrual = max(0.0, _pick(daily_accrual_usd, "daily_accrual_usd", 0.0))
    claim_gas = max(0.0, _pick(claim_gas_cost_usd, "claim_gas_cost_usd", 0.0))
    vol = max(0.0, _pick(
        reward_token_volatility_pct, "reward_token_volatility_pct",
        _DEFAULT_REWARD_TOKEN_VOLATILITY_PCT))
    reinvest_apr = _pick(
        reinvestment_apr_pct, "reinvestment_apr_pct",
        _DEFAULT_REINVESTMENT_APR_PCT)
    days_since = max(0.0, _pick(
        days_since_last_claim, "days_since_last_claim", 0.0))
    target_drag = max(0.0, _pick(
        target_gas_drag_pct, "target_gas_drag_pct",
        _DEFAULT_TARGET_GAS_DRAG_PCT))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need an accrued or accrual signal plus some gas signal,
    # and the data-quality flag must not mark the inputs as unreliable.
    has_signal = (
        (accrued > _EPS or daily_accrual > _EPS)
        and claim_gas > _EPS
    )
    has_data = has_signal and data_quality_ok

    gas_ratio = _gas_to_accrued_ratio_pct(claim_gas, accrued)
    threshold = _optimal_claim_threshold_usd(claim_gas, target_drag)
    days_to_threshold = _expected_days_to_threshold(
        threshold, accrued, daily_accrual)
    claim_freq = _recommended_claim_frequency_days(threshold, daily_accrual)
    price_risk = _price_risk_haircut_pct(vol, days_to_threshold)
    opp_cost = _opportunity_cost_usd(accrued, reinvest_apr, days_to_threshold)
    net_benefit = _net_benefit_of_claiming_now_usd(
        accrued, reinvest_apr, days_to_threshold, price_risk, claim_gas)
    classification = _classify(accrued, threshold, gas_ratio, has_data)
    score = _claim_timing_score(
        accrued, threshold, gas_ratio, price_risk, opp_cost, has_data)
    grade = _grade(score)
    flags = _flags(
        accrued,
        threshold,
        gas_ratio,
        price_risk,
        opp_cost,
        claim_freq,
        daily_accrual,
        net_benefit,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        accrued,
        claim_gas,
        threshold,
        days_to_threshold,
        price_risk,
        opp_cost,
        net_benefit,
        claim_freq,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "accrued_reward_usd": accrued,
        "daily_accrual_usd": daily_accrual,
        "claim_gas_cost_usd": claim_gas,
        "reward_token_volatility_pct": vol,
        "reinvestment_apr_pct": reinvest_apr,
        "days_since_last_claim": days_since,
        "target_gas_drag_pct": target_drag,
        "data_quality_ok": data_quality_ok,
        "gas_to_accrued_ratio_pct": gas_ratio,
        "optimal_claim_threshold_usd": threshold,
        "expected_days_to_threshold": days_to_threshold,
        "recommended_claim_frequency_days": claim_freq,
        "price_risk_haircut_pct": price_risk,
        "opportunity_cost_usd": opp_cost,
        "net_benefit_of_claiming_now_usd": net_benefit,
        "claim_timing_score": score,
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
    Analyse reward-claim timing across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions               : int
        - results                       : list[dict]  (per-position analysis)
        - most_ready_to_claim_position  : str | None  (highest claim-timing score)
        - least_ready_to_claim_position : str | None  (lowest claim-timing score)
        - avg_claim_timing_score        : float
        - claim_now_count               : int
        - negative_net_benefit_count    : int
        - wasteful_claiming_count       : int
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
            "most_ready_to_claim_position": None,
            "least_ready_to_claim_position": None,
            "avg_claim_timing_score": 0.0,
            "claim_now_count": 0,
            "negative_net_benefit_count": 0,
            "wasteful_claiming_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["claim_timing_score"])
    least = min(results, key=lambda r: r["claim_timing_score"])
    avg = sum(r["claim_timing_score"] for r in results) / total
    claim_now = sum(1 for r in results if r["classification"] == CLASS_CLAIM_NOW)
    neg = sum(
        1 for r in results if r["net_benefit_of_claiming_now_usd"] < 0.0
    )
    wasteful = sum(
        1 for r in results if FLAG_FREQUENT_CLAIMING_WASTEFUL in r["flags"]
    )

    return {
        "total_positions": total,
        "results": results,
        "most_ready_to_claim_position": most["name"],
        "least_ready_to_claim_position": least["name"],
        "avg_claim_timing_score": avg,
        "claim_now_count": claim_now,
        "negative_net_benefit_count": neg,
        "wasteful_claiming_count": wasteful,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolRewardClaimTimingOptimizer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolRewardClaimTimingOptimizer()
    >>> r = a.analyze({"name": "CRV-rewards", "accrued_reward_usd": 120.0,
    ...                "daily_accrual_usd": 8.0, "claim_gas_cost_usd": 3.0})
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
            "name": "CRV-rewards (mature)",
            "accrued_reward_usd": 220.0,
            "daily_accrual_usd": 8.0,
            "claim_gas_cost_usd": 3.0,
            "reward_token_volatility_pct": 70.0,
            "reinvestment_apr_pct": 6.0,
            "target_gas_drag_pct": 2.0,
        },
        {
            "name": "tiny-rewards (too small)",
            "accrued_reward_usd": 1.5,
            "daily_accrual_usd": 0.05,
            "claim_gas_cost_usd": 4.0,
            "reward_token_volatility_pct": 90.0,
            "reinvestment_apr_pct": 5.0,
            "target_gas_drag_pct": 2.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
