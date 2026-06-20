"""
MP-1143  DeFiProtocolStablecoinPegArbitrageAnalyzer
---------------------------------------------------
Quantify the *convergence arbitrage* of an off-peg stablecoin: a stable trading
below (or above) its peg, where the strategy is to buy at the discount, earn the
holding yield while you wait, and capture the convergence gain when (if) the peg
is restored — weighed against the tail risk that the peg never recovers (a
permanent depeg, or the price falling further).

When a stablecoin trades at, say, $0.97 with an 8% holding APR, an arbitrageur
faces a probabilistic bet: with some probability the peg is restored within some
horizon (capturing the ~3.1% convergence gain plus the yield earned along the
way), and with the complementary probability the peg fails (a deeper, permanent
loss to some downside price). This module turns that bet into numbers: the
expected value of the trade, its annualised expected return, the breakeven
probability at which the trade is worth taking, the risk/reward ratio, and a
single peg-arbitrage attractiveness score.

Genuine gap, and an explicit distinction from the existing depeg monitors: the
analytics package already has ``defi_stablecoin_depeg_risk_monitor`` (and depeg
*contagion* modelers), but those quantify the *risk* of a depeg — i.e. they warn
a holder that a peg is in danger. This module is the *opposite* angle: it treats
an already-discounted stable as an *opportunity* and prices the expected return
of the convergence-arbitrage trade. A grep for "peg_arbitrage" and
"convergence_arb" across the package confirms no existing module covers the
arbitrage / discount-capture angle.

For a single opportunity the module computes:
- the discount (or premium) to peg,
- the convergence gain if the peg is restored,
- the holding yield earned over the expected horizon,
- the gross arbitrage return if the peg is restored (convergence + yield),
- the annualised version of that return,
- the probability-weighted expected value (repeg outcome vs fail outcome),
- the annualised expected value,
- the downside loss if the peg fails,
- the risk/reward ratio (upside vs downside),
- the breakeven repeg probability (the minimum p at which EV >= 0),
- a 0-100 *peg-arbitrage score* (higher = a more attractive, risk-adjusted arb).

The module returns:
- name / current_price_usd / target_peg_usd (input echoes)
- discount_to_peg_pct
- convergence_gain_pct
- holding_yield_over_horizon_pct
- gross_arb_return_if_repeg_pct
- annualized_arb_return_if_repeg_pct
- expected_value_pct
- expected_annualized_pct
- downside_loss_if_fails_pct
- risk_reward_ratio
- breakeven_repeg_probability_pct
- peg_arb_score                 - 0-100, higher = more attractive arb
- classification                - STRONG_ARB .. AVOID / NO_ARB_OPPORTUNITY
- grade                         - A-F letter grade
- flags / recommendations       - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "stablecoin_peg_arbitrage_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinels keep JSON finite (no inf/NaN).
# "Never breaks even on probability" / degenerate annualisation.
BREAKEVEN_SENTINEL = 999.0   # breakeven repeg probability cannot be met (>100%)
DAYS_SENTINEL = 1e9          # placeholder for degenerate horizon (unused output)
RATIO_SENTINEL_INF = 1e9     # risk/reward when downside is ~0 but upside > 0

_DAYS_PER_YEAR = 365.0

# Defaults.
_DEFAULT_TARGET_PEG_USD = 1.0
_DEFAULT_HOLDING_APR_PCT = 0.0
_DEFAULT_EXPECTED_DAYS_TO_REPEG = 30.0
_DEFAULT_REPEG_PROBABILITY_PCT = 50.0
_DEFAULT_DOWNSIDE_PRICE_IF_FAILS_USD = 0.0  # 0 => derive from current if unset

# A discount/premium smaller than this (in pct) is "near peg" -> no arb.
_NEAR_PEG_PCT = 0.5

# Classification bands (on peg_arb_score, with overrides).
CLASS_STRONG_ARB = "STRONG_ARB"
CLASS_ATTRACTIVE = "ATTRACTIVE"
CLASS_MARGINAL = "MARGINAL"
CLASS_UNATTRACTIVE = "UNATTRACTIVE"
CLASS_AVOID = "AVOID"
CLASS_NO_ARB_OPPORTUNITY = "NO_ARB_OPPORTUNITY"

ALL_CLASSIFICATIONS = (
    CLASS_STRONG_ARB,
    CLASS_ATTRACTIVE,
    CLASS_MARGINAL,
    CLASS_UNATTRACTIVE,
    CLASS_AVOID,
    CLASS_NO_ARB_OPPORTUNITY,
)

# Flags
FLAG_DEEP_DISCOUNT = "DEEP_DISCOUNT"
FLAG_HIGH_REPEG_PROBABILITY = "HIGH_REPEG_PROBABILITY"
FLAG_LOW_REPEG_PROBABILITY = "LOW_REPEG_PROBABILITY"
FLAG_NEGATIVE_EXPECTED_VALUE = "NEGATIVE_EXPECTED_VALUE"
FLAG_HIGH_TAIL_LOSS = "HIGH_TAIL_LOSS"
FLAG_FAVORABLE_RISK_REWARD = "FAVORABLE_RISK_REWARD"
FLAG_TRADING_ABOVE_PEG = "TRADING_ABOVE_PEG"
FLAG_NEAR_PEG_NO_ARB = "NEAR_PEG_NO_ARB"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_DEEP_DISCOUNT,
    FLAG_HIGH_REPEG_PROBABILITY,
    FLAG_LOW_REPEG_PROBABILITY,
    FLAG_NEGATIVE_EXPECTED_VALUE,
    FLAG_HIGH_TAIL_LOSS,
    FLAG_FAVORABLE_RISK_REWARD,
    FLAG_TRADING_ABOVE_PEG,
    FLAG_NEAR_PEG_NO_ARB,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_DEEP_DISCOUNT_PCT = 5.0          # discount >= 5% is a deep discount
_HIGH_REPEG_PROB_PCT = 75.0       # repeg probability >= 75% is high
_LOW_REPEG_PROB_PCT = 40.0        # repeg probability < 40% is low
_HIGH_TAIL_LOSS_PCT = 15.0        # downside loss >= 15% is a high tail loss
_FAVORABLE_RR_RATIO = 2.0         # risk/reward >= 2.0 is favourable

# Score classification bands (peg_arb_score).
_SCORE_STRONG = 80.0
_SCORE_ATTRACTIVE = 60.0
_SCORE_MARGINAL = 40.0
_SCORE_UNATTRACTIVE = 20.0


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

def _discount_to_peg_pct(current_price_usd: float, target_peg_usd: float) -> float:
    """
    Discount to peg, in pct of the target peg. Positive = below peg (a discount);
    negative = above peg (a premium).

        discount = (target_peg - current_price) / target_peg * 100

    Defensive: a non-positive peg returns 0.0 (no meaningful reference).
    """
    peg = target_peg_usd
    if peg <= _EPS:
        return 0.0
    return (peg - current_price_usd) / peg * 100.0


def _convergence_gain_pct(current_price_usd: float, target_peg_usd: float) -> float:
    """
    Convergence gain if the peg is restored, in pct of the *entry* price.

        gain = (target_peg - current_price) / current_price * 100

    This is the return on capital invested (you buy at current, sell at peg).
    Defensive: a non-positive current price returns 0.0.
    """
    cur = current_price_usd
    if cur <= _EPS:
        return 0.0
    return (target_peg_usd - cur) / cur * 100.0


def _holding_yield_over_horizon_pct(holding_apr_pct: float, days: float) -> float:
    """
    Holding yield earned over the horizon, in pct (simple, not compounded).

        yield = holding_apr * (days / 365)

    Defensive: days floored at 0.
    """
    d = max(0.0, days)
    return holding_apr_pct * (d / _DAYS_PER_YEAR)


def _gross_arb_return_if_repeg_pct(
    convergence_gain_pct: float,
    holding_yield_over_horizon_pct: float,
) -> float:
    """Gross return if the peg is restored: convergence gain plus holding yield."""
    return convergence_gain_pct + holding_yield_over_horizon_pct


def _annualized_arb_return_if_repeg_pct(
    gross_arb_return_if_repeg_pct: float,
    days: float,
) -> float:
    """
    Annualise the gross repeg return over the expected horizon.

        annualised = gross * (365 / days)

    Defensive: a non-positive horizon returns the un-annualised gross (cannot
    annualise over zero time without producing inf).
    """
    d = max(0.0, days)
    if d <= _EPS:
        return gross_arb_return_if_repeg_pct
    return gross_arb_return_if_repeg_pct * (_DAYS_PER_YEAR / d)


def _downside_loss_if_fails_pct(
    current_price_usd: float,
    downside_price_if_fails_usd: float,
) -> float:
    """
    Loss if the peg fails, in pct of the *entry* price (a positive number is a
    loss).

        loss = (current_price - downside_price) / current_price * 100

    Defensive: a non-positive current price returns 0.0. If the downside price
    is at/above the current price (no further loss) the loss is floored at 0.
    """
    cur = current_price_usd
    if cur <= _EPS:
        return 0.0
    return max(0.0, (cur - downside_price_if_fails_usd) / cur * 100.0)


def _expected_value_pct(
    repeg_probability_pct: float,
    gross_arb_return_if_repeg_pct: float,
    downside_loss_if_fails_pct: float,
    holding_yield_over_horizon_pct: float,
) -> float:
    """
    Probability-weighted expected value of the trade, in pct of capital.

        p = repeg_probability / 100  (clamped to [0,1])
        repeg_outcome = gross_arb_return_if_repeg          (positive)
        fail_outcome  = holding_yield - downside_loss      (yield earned before
                                                            the peg fails, less
                                                            the capital loss)
        EV = p * repeg_outcome + (1 - p) * fail_outcome
    """
    p = _clamp(repeg_probability_pct, 0.0, 100.0) / 100.0
    repeg_outcome = gross_arb_return_if_repeg_pct
    fail_outcome = holding_yield_over_horizon_pct - downside_loss_if_fails_pct
    return p * repeg_outcome + (1.0 - p) * fail_outcome


def _expected_annualized_pct(expected_value_pct: float, days: float) -> float:
    """
    Annualise the expected value over the expected horizon.

    Defensive: a non-positive horizon returns the un-annualised EV.
    """
    d = max(0.0, days)
    if d <= _EPS:
        return expected_value_pct
    return expected_value_pct * (_DAYS_PER_YEAR / d)


def _risk_reward_ratio(
    gross_arb_return_if_repeg_pct: float,
    downside_loss_if_fails_pct: float,
) -> float:
    """
    Risk/reward ratio: upside (gross repeg return) over downside (fail loss).

        ratio = upside / downside

    Defensive: when the downside is ~0 the ratio is undefined; return 0.0 when
    the upside is also ~0, and a large finite sentinel (RATIO_SENTINEL_INF) when
    the upside is positive (reward with no measurable risk). A non-positive
    upside with ~0 downside returns 0.0.
    """
    upside = gross_arb_return_if_repeg_pct
    downside = max(0.0, downside_loss_if_fails_pct)
    if downside <= _EPS:
        return RATIO_SENTINEL_INF if upside > _EPS else 0.0
    if upside <= 0.0:
        return 0.0
    return upside / downside


def _breakeven_repeg_probability_pct(
    gross_arb_return_if_repeg_pct: float,
    fail_outcome_pct: float,
) -> float:
    """
    Minimum repeg probability (pct) at which the expected value is >= 0.

    Solving EV = 0 for p::

        p * repeg_outcome + (1 - p) * fail_outcome = 0
        p = -fail_outcome / (repeg_outcome - fail_outcome)

    Edge cases (defensive, no inf/NaN):
    - If the fail outcome is already >= 0 (you do not lose money even on a fail),
      any probability works -> breakeven is 0.0%.
    - If even a certain repeg (p=1) cannot make EV >= 0 (repeg_outcome <= 0),
      the bet never breaks even -> BREAKEVEN_SENTINEL (999.0).
    - Otherwise return the breakeven p clamped to [0, 100]; if the computed
      breakeven exceeds 100% (cannot be met) return BREAKEVEN_SENTINEL.
    """
    repeg_outcome = gross_arb_return_if_repeg_pct
    fail = fail_outcome_pct

    if fail >= 0.0:
        return 0.0
    if repeg_outcome <= 0.0:
        # Both outcomes non-positive -> never EV>=0.
        return BREAKEVEN_SENTINEL

    denom = repeg_outcome - fail
    if abs(denom) <= _EPS:
        return BREAKEVEN_SENTINEL
    p = (-fail) / denom * 100.0
    if p > 100.0 + _EPS:
        return BREAKEVEN_SENTINEL
    return _clamp(p, 0.0, 100.0)


def _peg_arb_score(
    expected_value_pct: float,
    annualized_arb_return_if_repeg_pct: float,
    risk_reward_ratio: float,
    repeg_probability_pct: float,
    is_near_peg: bool,
    has_data: bool,
) -> float:
    """
    0-100: higher = a more attractive, risk-adjusted convergence arb.

    Blends four drivers:
    - expected-value component (0-40): a non-positive EV contributes 0; an EV at
      or above a strong mark (10%) contributes the full 40; linear in between.
    - risk/reward component (0-25): a ratio of 0 contributes 0, a ratio at or
      above the favourable mark (2.0) contributes the full 25; linear between.
    - repeg-probability component (0-20): scales linearly with the repeg
      probability (0% -> 0, 100% -> 20).
    - annualised-upside component (0-15): scales the annualised repeg return up
      to a 50% mark.

    Returns 0.0 when there is no usable data, and 0.0 when the position is
    effectively at peg (no arb to capture).
    """
    if not has_data or is_near_peg:
        return 0.0

    ev_capped = _clamp(expected_value_pct, 0.0, 10.0)
    ev_component = (ev_capped / 10.0) * 40.0

    rr_capped = _clamp(risk_reward_ratio, 0.0, _FAVORABLE_RR_RATIO)
    rr_component = (rr_capped / _FAVORABLE_RR_RATIO) * 25.0

    prob_capped = _clamp(repeg_probability_pct, 0.0, 100.0)
    prob_component = (prob_capped / 100.0) * 20.0

    ann_capped = _clamp(annualized_arb_return_if_repeg_pct, 0.0, 50.0)
    ann_component = (ann_capped / 50.0) * 15.0

    return _clamp(ev_component + rr_component + prob_component + ann_component)


def _classify(
    peg_arb_score: float,
    expected_value_pct: float,
    is_near_peg: bool,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band.

      no data / near peg          -> NO_ARB_OPPORTUNITY
      EV < 0                       -> AVOID
      score >= 80                  -> STRONG_ARB
      score >= 60                  -> ATTRACTIVE
      score >= 40                  -> MARGINAL
      score >= 20                  -> UNATTRACTIVE
      otherwise                    -> AVOID
    """
    if not has_data or is_near_peg:
        return CLASS_NO_ARB_OPPORTUNITY

    if expected_value_pct < 0.0:
        return CLASS_AVOID

    s = peg_arb_score
    if s >= _SCORE_STRONG:
        return CLASS_STRONG_ARB
    if s >= _SCORE_ATTRACTIVE:
        return CLASS_ATTRACTIVE
    if s >= _SCORE_MARGINAL:
        return CLASS_MARGINAL
    if s >= _SCORE_UNATTRACTIVE:
        return CLASS_UNATTRACTIVE
    return CLASS_AVOID


def _grade(peg_arb_score: float) -> str:
    """Map peg_arb_score (higher = better) to an A-F letter grade."""
    s = peg_arb_score
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
    discount_to_peg_pct: float,
    repeg_probability_pct: float,
    expected_value_pct: float,
    downside_loss_if_fails_pct: float,
    risk_reward_ratio: float,
    is_near_peg: bool,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if is_near_peg:
        flags.append(FLAG_NEAR_PEG_NO_ARB)
        return flags

    if discount_to_peg_pct < 0.0:
        flags.append(FLAG_TRADING_ABOVE_PEG)

    if discount_to_peg_pct >= _DEEP_DISCOUNT_PCT:
        flags.append(FLAG_DEEP_DISCOUNT)

    if repeg_probability_pct >= _HIGH_REPEG_PROB_PCT:
        flags.append(FLAG_HIGH_REPEG_PROBABILITY)
    elif repeg_probability_pct < _LOW_REPEG_PROB_PCT:
        flags.append(FLAG_LOW_REPEG_PROBABILITY)

    if expected_value_pct < 0.0:
        flags.append(FLAG_NEGATIVE_EXPECTED_VALUE)

    if downside_loss_if_fails_pct >= _HIGH_TAIL_LOSS_PCT:
        flags.append(FLAG_HIGH_TAIL_LOSS)

    if (risk_reward_ratio >= _FAVORABLE_RR_RATIO
            and risk_reward_ratio < RATIO_SENTINEL_INF):
        flags.append(FLAG_FAVORABLE_RISK_REWARD)
    elif risk_reward_ratio >= RATIO_SENTINEL_INF:
        flags.append(FLAG_FAVORABLE_RISK_REWARD)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    discount_to_peg_pct: float,
    convergence_gain_pct: float,
    expected_value_pct: float,
    expected_annualized_pct: float,
    repeg_probability_pct: float,
    breakeven_repeg_probability_pct: float,
    downside_loss_if_fails_pct: float,
    risk_reward_ratio: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no current-price / peg signal or data marked "
            "unreliable. Cannot assess the convergence-arbitrage opportunity for "
            "this stablecoin."
        )
        return recs

    if classification == CLASS_NO_ARB_OPPORTUNITY:
        recs.append(
            f"No arbitrage: the stable trades within ~{abs(discount_to_peg_pct):.2f}"
            "% of peg. There is no meaningful discount to capture; this is not a "
            "convergence-arb setup."
        )
        return recs

    if classification == CLASS_STRONG_ARB:
        recs.append(
            f"Strong arb: a ~{discount_to_peg_pct:.2f}% discount with a "
            f"~{repeg_probability_pct:.0f}% repeg probability gives a positive "
            f"expected value of ~{expected_value_pct:.2f}% "
            f"(~{expected_annualized_pct:.2f}% annualised). The risk-adjusted "
            "setup is compelling."
        )
    elif classification == CLASS_ATTRACTIVE:
        recs.append(
            f"Attractive arb: ~{discount_to_peg_pct:.2f}% discount, "
            f"~{convergence_gain_pct:.2f}% convergence gain if it repegs, and a "
            f"positive expected value (~{expected_value_pct:.2f}%). Worth sizing "
            "modestly."
        )
    elif classification == CLASS_MARGINAL:
        recs.append(
            f"Marginal arb: the expected value (~{expected_value_pct:.2f}%) is "
            "positive but slim relative to the tail risk. Only take it with a "
            "small allocation or a higher conviction on the repeg."
        )
    elif classification == CLASS_UNATTRACTIVE:
        recs.append(
            f"Unattractive arb: a thin expected value (~{expected_value_pct:.2f}%) "
            "does not adequately pay for the depeg tail risk. Prefer to pass."
        )
    else:  # AVOID
        recs.append(
            f"Avoid: the probability-weighted expected value is "
            f"~{expected_value_pct:.2f}%. The discount does not compensate for the "
            "risk that the peg fails; do not take this trade as configured."
        )

    if FLAG_TRADING_ABOVE_PEG in flags:
        recs.append(
            f"Trading above peg: the stable is ~{-discount_to_peg_pct:.2f}% over "
            "its peg. There is no discount to capture — convergence would be a "
            "loss, not a gain."
        )

    if FLAG_NEGATIVE_EXPECTED_VALUE in flags:
        if breakeven_repeg_probability_pct >= BREAKEVEN_SENTINEL:
            recs.append(
                "Negative expected value: even a certain repeg does not make this "
                "trade profitable at the current discount and yield. Skip it."
            )
        else:
            recs.append(
                f"Negative expected value: the repeg probability would need to be "
                f"at least ~{breakeven_repeg_probability_pct:.0f}% for the trade to "
                f"break even, versus the assumed ~{repeg_probability_pct:.0f}%."
            )

    if FLAG_HIGH_TAIL_LOSS in flags:
        recs.append(
            f"High tail loss: a failed repeg costs ~{downside_loss_if_fails_pct:.2f}"
            "% of capital. Size the position so this tail outcome is survivable."
        )

    if FLAG_FAVORABLE_RISK_REWARD in flags:
        rr = ("very high" if risk_reward_ratio >= RATIO_SENTINEL_INF
              else f"~{risk_reward_ratio:.2f}x")
        recs.append(
            f"Favourable risk/reward: the upside vs downside ratio is {rr}. The "
            "asymmetry favours taking the trade, subject to position sizing."
        )

    if FLAG_LOW_REPEG_PROBABILITY in flags:
        recs.append(
            f"Low repeg probability: at ~{repeg_probability_pct:.0f}% the bet leans "
            "on a discount that may not converge. Treat as speculative."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    current_price_usd: float | None = None,
    target_peg_usd: float | None = None,
    holding_apr_pct: float | None = None,
    expected_days_to_repeg: float | None = None,
    repeg_probability_pct: float | None = None,
    downside_price_if_fails_usd: float | None = None,
    position_size_usd: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the convergence-arbitrage opportunity of a single off-peg stablecoin.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                        : str
    - current_price_usd           : float (e.g. 0.97)
    - target_peg_usd              : float (default 1.0)
    - holding_apr_pct             : float (yield earned while waiting to repeg)
    - expected_days_to_repeg      : float (horizon to convergence, default 30)
    - repeg_probability_pct       : float (probability the peg is restored, 0..100)
    - downside_price_if_fails_usd : float (price if the peg fails, e.g. 0.80;
                                    when 0/unset it defaults to 90% of current)
    - position_size_usd           : float (optional; echoed and used for USD P&L)
    - data_quality                : truthy/"ok" => trusted; falsy/"poor" => not

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

    current = max(0.0, _pick(current_price_usd, "current_price_usd", 0.0))
    peg = max(0.0, _pick(target_peg_usd, "target_peg_usd", _DEFAULT_TARGET_PEG_USD))
    apr = _pick(holding_apr_pct, "holding_apr_pct", _DEFAULT_HOLDING_APR_PCT)
    days = max(0.0, _pick(expected_days_to_repeg, "expected_days_to_repeg",
                          _DEFAULT_EXPECTED_DAYS_TO_REPEG))
    repeg_prob = _clamp(_pick(repeg_probability_pct, "repeg_probability_pct",
                              _DEFAULT_REPEG_PROBABILITY_PCT), 0.0, 100.0)

    # Downside price: if unset/0, default to 90% of the current price (a modest
    # further decline) so the tail outcome is never a no-loss by default.
    downside_raw = downside_price_if_fails_usd
    if downside_raw is None:
        downside_raw = t.get("downside_price_if_fails_usd",
                             _DEFAULT_DOWNSIDE_PRICE_IF_FAILS_USD)
    downside = max(0.0, _safe_float(downside_raw, _DEFAULT_DOWNSIDE_PRICE_IF_FAILS_USD))
    if downside <= _EPS and current > _EPS:
        downside = current * 0.9

    position_size = max(0.0, _pick(position_size_usd, "position_size_usd", 0.0))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a positive current price and a positive peg.
    has_signal = current > _EPS and peg > _EPS
    has_data = has_signal and data_quality_ok

    discount = _discount_to_peg_pct(current, peg)
    is_near_peg = abs(discount) < _NEAR_PEG_PCT

    convergence = _convergence_gain_pct(current, peg)
    holding_yield = _holding_yield_over_horizon_pct(apr, days)
    gross_repeg = _gross_arb_return_if_repeg_pct(convergence, holding_yield)
    annual_repeg = _annualized_arb_return_if_repeg_pct(gross_repeg, days)
    downside_loss = _downside_loss_if_fails_pct(current, downside)
    fail_outcome = holding_yield - downside_loss
    ev = _expected_value_pct(repeg_prob, gross_repeg, downside_loss, holding_yield)
    ev_annual = _expected_annualized_pct(ev, days)
    rr = _risk_reward_ratio(gross_repeg, downside_loss)
    breakeven_prob = _breakeven_repeg_probability_pct(gross_repeg, fail_outcome)

    score = _peg_arb_score(
        ev, annual_repeg, rr, repeg_prob, is_near_peg, has_data
    )
    classification = _classify(score, ev, is_near_peg, has_data)
    grade = _grade(score)
    flags = _flags(
        discount,
        repeg_prob,
        ev,
        downside_loss,
        rr,
        is_near_peg,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        discount,
        convergence,
        ev,
        ev_annual,
        repeg_prob,
        breakeven_prob,
        downside_loss,
        rr,
        has_data,
    )

    # Optional USD P&L on the supplied position size.
    expected_pnl_usd = position_size * (ev / 100.0)

    result: dict[str, Any] = {
        "name": name_val,
        "current_price_usd": current,
        "target_peg_usd": peg,
        "holding_apr_pct": apr,
        "expected_days_to_repeg": days,
        "repeg_probability_pct": repeg_prob,
        "downside_price_if_fails_usd": downside,
        "position_size_usd": position_size,
        "data_quality_ok": data_quality_ok,
        "discount_to_peg_pct": discount,
        "is_near_peg": is_near_peg,
        "convergence_gain_pct": convergence,
        "holding_yield_over_horizon_pct": holding_yield,
        "gross_arb_return_if_repeg_pct": gross_repeg,
        "annualized_arb_return_if_repeg_pct": annual_repeg,
        "downside_loss_if_fails_pct": downside_loss,
        "expected_value_pct": ev,
        "expected_annualized_pct": ev_annual,
        "expected_pnl_usd": expected_pnl_usd,
        "risk_reward_ratio": rr,
        "breakeven_repeg_probability_pct": breakeven_prob,
        "peg_arb_score": score,
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

def analyze_portfolio(opportunities: list, config: dict | None = None) -> dict:
    """
    Analyse convergence-arb opportunities across a batch of stables and summarise.

    Returns
    -------
    dict
        - total_opportunities      : int
        - results                  : list[dict]  (per-opportunity analysis)
        - best_opportunity         : str | None  (highest peg-arb score)
        - worst_opportunity        : str | None  (lowest peg-arb score)
        - avg_peg_arb_score        : float
        - negative_ev_count        : int
        - timestamp                : float
    """
    if not isinstance(opportunities, list):
        opportunities = []

    results = [
        analyze(o if isinstance(o, dict) else {}, config=config)
        for o in opportunities
    ]
    total = len(results)

    if total == 0:
        return {
            "total_opportunities": 0,
            "results": [],
            "best_opportunity": None,
            "worst_opportunity": None,
            "avg_peg_arb_score": 0.0,
            "negative_ev_count": 0,
            "timestamp": time.time(),
        }

    best = max(results, key=lambda r: r["peg_arb_score"])
    worst = min(results, key=lambda r: r["peg_arb_score"])
    avg = sum(r["peg_arb_score"] for r in results) / total
    neg = sum(1 for r in results if r["expected_value_pct"] < 0.0)

    return {
        "total_opportunities": total,
        "results": results,
        "best_opportunity": best["name"],
        "worst_opportunity": worst["name"],
        "avg_peg_arb_score": avg,
        "negative_ev_count": neg,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolStablecoinPegArbitrageAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolStablecoinPegArbitrageAnalyzer()
    >>> r = a.analyze({"name": "USDx", "current_price_usd": 0.97,
    ...                "holding_apr_pct": 8.0, "expected_days_to_repeg": 30,
    ...                "repeg_probability_pct": 80.0,
    ...                "downside_price_if_fails_usd": 0.80})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, token: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(token, config=self._config, **kwargs)

    def analyze_portfolio(self, opportunities: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(opportunities, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_opportunities = [
        {
            "name": "USDx (mild discount, high repeg)",
            "current_price_usd": 0.97,
            "target_peg_usd": 1.0,
            "holding_apr_pct": 8.0,
            "expected_days_to_repeg": 30.0,
            "repeg_probability_pct": 85.0,
            "downside_price_if_fails_usd": 0.80,
        },
        {
            "name": "USDy (deep discount, low repeg)",
            "current_price_usd": 0.70,
            "target_peg_usd": 1.0,
            "holding_apr_pct": 0.0,
            "expected_days_to_repeg": 90.0,
            "repeg_probability_pct": 25.0,
            "downside_price_if_fails_usd": 0.30,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_opportunities[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_opportunities)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
