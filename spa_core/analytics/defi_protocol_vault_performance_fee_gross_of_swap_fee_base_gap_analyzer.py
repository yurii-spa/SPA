"""
MP-1228: DeFiProtocolVaultPerformanceFeeGrossOfSwapFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault's strategy must periodically SWAP its reward tokens (or perform an
in-kind conversion from yield token to the vault's base denomination currency)
through an AMM/DEX pool. Every such harvest swap incurs an explicit, protocol-
posted PERCENTAGE POOL SWAP FEE (e.g., 0.3% of the swap value on a Uniswap v3
or Curve pool). The strategy earns a GROSS yield, but the depositor's
economically realized yield is the yield NET OF the recurring swap fees paid
during reward-token conversion (gross_yield − swap_fee). The vault charges its
PERFORMANCE fee on the GROSS yield (BEFORE netting the per-harvest AMM swap
fee), not on the NET-OF-SWAP-FEE yield the depositor economically realized.
So the depositor pays a performance fee on the very slice of yield the AMM
swap fee already consumed — a "fee-on-swap-fee" / fee-base inflation. The fee
is levied on the gross yield; the FAIR fee would be levied only on the
net-of-swap-fee yield:

    fee_frac                      = clamp(performance_fee_pct / 100, 0, 1)
    swap_fee_consumed_yield_pct   = max(0, gross_yield - net_of_swap_fee_yield)
    fee_charged_pct               = fee_frac * max(0, gross_yield)
    fair_fee_pct                  = fee_frac * max(0, net_of_swap_fee_yield)
    fee_on_swap_fee_gap_pct       = max(0, fee_charged - fair_fee)
                                    (= performance fee charged on the
                                     swap-fee slice of the yield, which
                                     the depositor never received)
    net_return_after_fee_pct      = net_of_swap_fee_yield - fee_charged
    net_return_fair_pct           = net_of_swap_fee_yield - fair_fee
    overstatement_pct             = fee_on_swap_fee_gap_pct
    fee_on_swap_fee_fraction      = clamp(gap / fee_charged, 0, 1)
    realization_ratio             = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay a performance fee on what you earned", but with
the fee charged on the gross yield a chunk of the performance fee lands on the
AMM swap-fee slice the depositor never received. The scale-free
fee_on_swap_fee_fraction is the share of the charged performance fee that
landed on the swap-fee slice; it is the basis of the classification. When the
swap fee consumed nothing (net_of_swap_fee ≈ gross) the performance fee was
effectively fair (HIGHER score). When the swap fee consumed most of the yield,
the performance fee was charged almost entirely on the swap-fee slice (LOWER
score).

HIGHER score = the performance fee was charged on the net-of-swap-fee
base (gross ≈ net_of_swap_fee), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the swap-fee
slice, or the net return goes negative after the fee.

Override path (when fee_on_swap_fee_gap_pct is supplied directly, finite, AND
a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are present):
take the gap verbatim (negative → magnitude) and skip the net-of-swap-fee
geometry — fee_on_swap_fee_fraction and the metrics are computed the same way:

    fee_on_swap_fee_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-swap-fee / swap-fee-slice / fair geometry is
not known → those fields are reported as None, and the geometry-only flags
FEE_ON_SWAP_FEE / FULL_FEE_ON_SWAP_FEE / NET_NEGATIVE_AFTER_FEE are NOT
raised; realization_ratio is anchored to (1 - fee_on_swap_fee_fraction).)

Distinct from (this is the GROSS-OF-SWAP-FEE performance-fee BASE — the fee
being charged on the gross yield before the per-harvest AMM swap fee is
netted out, not the swap cost of portfolio rotation or an external/internal
fee layer):
  * defi_protocol_vault_performance_fee_gross_of_rebalancing_cost_base_gap_analyzer
    — that module prices the swap cost of PORTFOLIO ROTATION (changing the
    allocation weights among different protocols / assets, executing multiple
    DEX trades to restructure the whole portfolio). HERE the axis is the
    per-harvest AMM POOL FEE on converting the single reward-token stream to the
    vault denomination currency, independent of any portfolio rebalancing. The
    key distinction: rebalancing_cost is the turnover cost of RESTRUCTURING the
    allocation; HERE it is the percentage fee on CONVERTING yield tokens to base
    currency during each harvest, even when no rebalancing occurs at all.
  * defi_protocol_vault_performance_fee_gross_of_withdrawal_fee_base_gap_analyzer
    — that module prices an explicit, protocol-posted PERCENTAGE REDEMPTION /
    WITHDRAWAL / UNSTAKE FEE charged on EXITING the position itself (redeeming
    shares of the underlying vault or unstaking from the protocol). HERE the
    fee is an AMM/DEX POOL SWAP FEE charged by a DEX on the REWARD TOKEN
    CONVERSION swap, independent of any redemption or withdrawal from the
    underlying protocol. The key distinction: withdrawal_fee is charged by the
    UNDERLYING protocol on the principal redemption; HERE the fee is charged by
    a SEPARATE DEX pool on the swap of reward tokens to base currency, at harvest
    time, with no redemption of principal involved.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage_base_gap_analyzer
    — that module prices a MARKET-DRIVEN, ONE-OFF price impact on a SINGLE
    principal exit (slippage against AMM/orderbook depth when redeeming a large
    position). HERE it is the PROTOCOL-POSTED percentage pool swap fee on the
    recurring reward-token conversion swap, which is deterministic (not market-
    driven), scales with the yield (not the principal size), and recurs on every
    harvest (not a one-off principal exit).
  * defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer
    — that module prices a FIXED NETWORK GAS / KEEPER-TX COST (a flat
    denominated amount, independent of the yield size). HERE it is a PERCENTAGE
    AMM pool swap fee that scales linearly with the yield value; when the harvest
    yield is large the swap fee is large, when the harvest yield is small the
    swap fee is small — it is a yield-proportional cost, not a fixed network fee.
  * defi_protocol_vault_performance_fee_gross_of_funding_cost_base_gap_analyzer
    — that module prices the periodic PERP FUNDING payment on a notional perp /
    short position of a delta-neutral or basis hedge. HERE it is the AMM swap fee
    on the reward-token conversion, independent of any hedge or funding rate.
  * defi_protocol_vault_performance_fee_gross_of_borrow_cost_base_gap_analyzer
    — that module prices INTEREST on debt drawn from a lending market. HERE it is
    the AMM pool swap fee on converting reward tokens to base currency, with no
    debt involved.
  * defi_protocol_vault_performance_fee_gross_of_bridge_fee_base_gap_analyzer
    — that module prices a CROSS-CHAIN TRANSPORT FEE for moving value between
    chains. HERE the swap is a SAME-CHAIN DEX trade converting reward tokens,
    with no cross-chain transport involved.
  * defi_protocol_vault_performance_fee_gross_of_boost_fee_base_gap_analyzer
    — that module prices an external BOOST-PROVIDER PLATFORM FEE on amplified
    gauge emissions. HERE it is the AMM pool swap fee on the reward token
    conversion, independent of any boost mechanism.
  * defi_protocol_vault_performance_fee_gross_of_harvest_bounty_base_gap_analyzer
    — that module prices a PER-HARVEST CALLER REWARD paid to a keeper to trigger
    the harvest transaction (a reward for the keeper that initiates the harvest).
    HERE it is the AMM pool swap fee charged by the DEX pool itself on the swap
    occurring during that harvest, distinct from any keeper incentive.
  * the other gross_of_* perf-fee modules
    (gross_of_insurance_premium, gross_of_slashing_loss,
    gross_of_validator_commission, gross_of_referral_fee,
    gross_of_reserve_contribution, gross_of_impermanent_loss,
    gross_of_bad_debt_socialization, gross_of_protocol_revenue_share,
    gross_of_management_fee) — each prices a DIFFERENT erosion layer. None of
    those layers is the recurring per-harvest AMM/DEX pool swap fee on reward
    token conversion.
  * defi_protocol_vault_round_trip_cost_analyzer — that analyzer measures the
    TOTAL entry + exit round-trip cost for the whole position (deposit + eventual
    withdrawal). HERE the axis is the performance-fee BASE inflation from
    charging the fee on the gross yield BEFORE netting the per-harvest DEX swap
    fee, not the round-trip principal cost.
  * defi_protocol_vault_harvest_timing_analyzer and related harvest modules
    — those measure WHEN / HOW OFTEN to harvest. HERE the axis is the
    performance-fee BASE inflation from charging the fee on the gross
    (pre-swap-fee) yield, NOT the harvest timing or size.

The novel axis here: the performance-fee BASE being GROSS-OF-AMM-SWAP-FEE
rather than NET-OF-SWAP-FEE — a fee-on-swap-fee / fee-base inflation in which
the performance fee is charged on the slice of yield the per-harvest DEX pool
swap fee already consumed.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_gross_of_swap_fee_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_swap_fee_fraction
# in [0, 1] (= fee_on_swap_fee_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-swap-fee base
MILD_FRACTION = 0.20         # at/below → mild fee-on-swap-fee gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-swap-fee flag threshold on swap_fee_rate_pct.
# AMM pools above 1 % are unusually expensive for reward-token conversion.
HIGH_SWAP_FEE_PCT = 1.0

# Small epsilon to keep normalisers finite.
EPS = 1e-12


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


def _coerce_num(val) -> Optional[float]:
    """
    Coerce a single value to a finite float, or None if it is not interpretable.
    Accepts int/float/numeric-string; rejects bool, None, NaN, inf, and
    non-numeric values.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            fv = float(s)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    return None


def _coerce_signed(val) -> Optional[float]:
    """
    Coerce a value to a finite SIGNED float (may be negative), or None if it is
    not interpretable. Identical to _coerce_num; kept as a named alias for the
    net-of-swap-fee-yield field, which may legitimately be negative.
    """
    return _coerce_num(val)


def _coerce_count(val) -> Optional[int]:
    """
    Coerce a value to a non-negative integer count, or None if not interpretable.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    iv = int(cv)
    return iv if iv >= 0 else None


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultPerformanceFeeGrossOfSwapFeeBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the per-harvest AMM/DEX swap fee is netted out) and the FAIR
    fee it would charge on the NET-OF-SWAP-FEE yield the depositor economically
    realized, and the share of the charged performance fee that therefore landed
    on the SWAP-FEE slice of the yield (a fee-on-swap-fee / fee-base inflation).

        fee_frac                    = clamp(performance_fee_pct / 100, 0, 1)
        swap_fee_consumed_yield_pct = max(0, gross_yield - net_of_swap_fee_yield)
        fee_charged_pct             = fee_frac * max(0, gross_yield)
        fair_fee_pct                = fee_frac * max(0, net_of_swap_fee_yield)
        fee_on_swap_fee_gap_pct     = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct    = net_of_swap_fee_yield - fee_charged
        net_return_fair_pct         = net_of_swap_fee_yield - fair_fee
        overstatement_pct           = fee_on_swap_fee_gap_pct
        fee_on_swap_fee_fraction    = clamp(gap / fee_charged, 0, 1)
        realization_ratio           = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-swap-fee yield. When the net-of-swap-fee yield
    equals (or exceeds) the gross yield the AMM swap fee consumed nothing and
    the performance fee was charged on the right base
    (CLEAN_NET_OF_SWAP_FEE_BASE). When the swap fee consumed a large share of
    the yield, a large share of the performance fee was charged on the swap-fee
    slice (MODERATE / SEVERE fee-on-swap-fee gap), and if the fee exceeds the
    net-of-swap-fee yield the net return goes negative.

    HIGHER score = the performance fee was charged on the net-of-swap-fee base
    (gross ≈ net_of_swap_fee), the fee was effectively fair, nothing to fix.
    LOWER score = a large share of the performance fee landed on the swap-fee
    slice the depositor never realized, or the net return goes negative after
    the fee.

    Per-position input dict fields:
        vault / token               : str
        gross_yield_pct             : float — the GROSS yield (before the
                                      per-harvest AMM swap fee is netted)
                                      on which the performance fee is assessed.
                                      REQUIRED, must be a finite POSITIVE number
                                      (else INSUFFICIENT_DATA).
        net_of_swap_fee_yield_pct   : float — the yield NET OF the AMM swap fee
                                      (finite; may be < gross; may be negative;
                                      default 0.0 = the swap fee consumed the
                                      whole yield).
        performance_fee_pct         : float — performance-fee rate % (REQUIRED
                                      finite, clamped into 0..100; non-finite →
                                      INSUFFICIENT_DATA on the main path).
        swap_fee_rate_pct           : float — OPTIONAL informational DEX pool
                                      swap fee rate %; ≥ HIGH_SWAP_FEE_PCT
                                      raises HIGH_SWAP_FEE.
        fee_on_swap_fee_gap_pct     : float — OPTIONAL direct override of the
                                      fee-on-swap-fee gap (the performance fee
                                      charged on the swap-fee slice). When
                                      supplied (finite; negative → magnitude)
                                      AND a valid POSITIVE gross_yield_pct and
                                      POSITIVE fee_charged_pct are present,
                                      take this gap directly and skip the
                                      net-of-swap-fee geometry (override path;
                                      geometry → None).
        fee_charged_pct             : float — OPTIONAL, only used on the override
                                      path as the denominator for
                                      fee_on_swap_fee_fraction (finite > 0
                                      required to take the override path).
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))

        # The gross yield is required and must be finite & positive.
        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        swap_fee_rate = _coerce_num(p.get("swap_fee_rate_pct"))

        # Override path: a direct fee-on-swap-fee gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_swap_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, swap_fee_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, swap_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        swap_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-swap-fee yield may legitimately be negative (the swap fee
        # exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_swap_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        swap_fee_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_swap_fee_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_swap_fee_yield_pct=net_gain,
            swap_fee_consumed_yield_pct=swap_fee_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_swap_fee_gap_pct=fee_on_swap_fee_gap_pct,
            swap_fee_rate_pct=swap_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        swap_fee_rate: Optional[float],
    ) -> dict:
        # The gap cannot exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-swap-fee / swap-fee-slice / fair geometry is unknown on the
        # override path → report None.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_swap_fee_yield_pct=None,
            swap_fee_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_swap_fee_gap_pct=gap,
            swap_fee_rate_pct=swap_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_swap_fee_yield_pct: Optional[float],
        swap_fee_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_swap_fee_gap_pct: float,
        swap_fee_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the swap-fee slice.
        overstatement_pct = fee_on_swap_fee_gap_pct

        # Net return: only computable when net-of-swap-fee geometry is known.
        if net_of_swap_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_swap_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_swap_fee_yield_pct - fair_fee_pct)
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
        else:
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-swap-fee fraction — share of charged fee on the
        # swap-fee slice.
        if fee_charged_pct > EPS:
            fee_on_swap_fee_fraction = _clamp(
                fee_on_swap_fee_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_swap_fee_fraction = 0.0

        # Override path: anchor realisation on (1 - fee_on_swap_fee_fraction).
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_swap_fee_fraction, 0.0, 1.0)

        classification = self._classify(fee_on_swap_fee_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_swap_fee_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_swap_fee_yield_pct,
            swap_fee_consumed_yield_pct,
            gross_yield_pct,
            swap_fee_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_swap_fee_yield_pct": (
                round(net_of_swap_fee_yield_pct, 4)
                if net_of_swap_fee_yield_pct is not None else None),
            "swap_fee_consumed_yield_pct": (
                round(swap_fee_consumed_yield_pct, 4)
                if swap_fee_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_swap_fee_gap_pct": round(fee_on_swap_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_swap_fee_fraction": round(fee_on_swap_fee_fraction, 4),
            "net_is_negative": net_is_negative,
            "swap_fee_rate_pct": (
                round(swap_fee_rate_pct, 4)
                if swap_fee_rate_pct is not None else None),
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        fee_on_swap_fee_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the net-of-swap-fee
        yield the depositor actually realized: the depositor keeps the yield
        that survived the per-harvest AMM swap fee.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * fee-base penalty = clamp(1 − fee_on_swap_fee_fraction, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_swap_fee_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_swap_fee_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_SWAP_FEE_GAP"
        if fee_on_swap_fee_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_SWAP_FEE_BASE"
        if fee_on_swap_fee_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_SWAP_FEE_GAP"
        if fee_on_swap_fee_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_SWAP_FEE_GAP"
        return "SEVERE_FEE_ON_SWAP_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_SWAP_FEE"
        if classification == "CLEAN_NET_OF_SWAP_FEE_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_SWAP_FEE_GAP":
            return "MINOR_FEE_ON_SWAP_FEE"
        if classification == "MODERATE_FEE_ON_SWAP_FEE_GAP":
            return "DEMAND_NET_OF_SWAP_FEE_BASE"
        # SEVERE_FEE_ON_SWAP_FEE_GAP
        return "AVOID_FEE_ON_SWAP_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_swap_fee_yield_pct: Optional[float],
        swap_fee_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        swap_fee_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_SWAP_FEE_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (swap_fee_rate_pct is not None
                and swap_fee_rate_pct >= HIGH_SWAP_FEE_PCT):
            flags.append("HIGH_SWAP_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (swap_fee_consumed_yield_pct is not None
                    and swap_fee_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_SWAP_FEE")
            if (net_of_swap_fee_yield_pct is not None
                    and net_of_swap_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_SWAP_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_swap_fee_yield_pct": None,
            "swap_fee_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_swap_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_swap_fee_fraction": None,
            "net_is_negative": False,
            "swap_fee_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_SWAP_FEE",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_swap_fee_gap_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_swap_fee_gap_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "score": r["score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_SWAP_FEE_BASE: net_of_swap_fee ≈ gross → the AMM
            # swap fee consumed nothing (e.g., vault routes through a 0.01%
            # stablecoin pool), the performance fee was on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 15.0,
            "net_of_swap_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "swap_fee_rate_pct": 0.01,
        },
        {
            # MODERATE_FEE_ON_SWAP_FEE_GAP: gross 14, net 7 → ~half the fee
            # was charged on the swap-fee slice (fraction ~ 0.5).
            "vault": "CRV-Vault-ModerateSwapFee",
            "gross_yield_pct": 14.0,
            "net_of_swap_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "swap_fee_rate_pct": 1.5,
        },
        {
            # SEVERE_FEE_ON_SWAP_FEE_GAP (net negative): the AMM swap fees on
            # reward token conversion drove the net yield negative, yet the
            # performance fee is still charged on the gross yield.
            "vault": "BAL-Vault-SevereSwapFee",
            "gross_yield_pct": 10.0,
            "net_of_swap_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "swap_fee_rate_pct": 3.0,
        },
        {
            # Override path: fee-on-swap-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-Vault-OverrideGap",
            "gross_yield_pct": 20.0,
            "fee_on_swap_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_swap_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1228 Vault Performance-Fee Gross-Of-Swap-Fee-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeGrossOfSwapFeeBaseGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
