"""
MP-1216: DeFiProtocolVaultPerformanceFeeGrossOfBorrowCostBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault runs a LEVERAGED strategy (leveraged staking / looping / perp-carry) and
pays a BORROW / FUNDING cost (interest on the debt / perp-funding) on the
borrowed leverage. The vault charges its PERFORMANCE fee on the GROSS yield of
the leveraged position (the yield BEFORE the borrow / funding cost of servicing
the debt is netted out), not on the NET-OF-BORROW-COST yield the depositor
actually keeps after servicing the debt. So the depositor pays a performance fee
on the very slice of yield that went to servicing the borrow / funding cost of
the leverage — a "fee-on-borrow" / fee-base inflation. The fee is levied on the
gross yield; the FAIR fee would be levied only on the net-of-borrow-cost yield:

    fee_frac                          = clamp(performance_fee_pct / 100, 0, 1)
    borrow_consumed_yield_pct         = max(0, gross_yield - net_of_borrow_cost_yield)
    fee_charged_pct                   = fee_frac * max(0, gross_yield)
    fair_fee_pct                      = fee_frac * max(0, net_of_borrow_cost_yield)
    fee_on_borrow_cost_gap_pct        = max(0, fee_charged - fair_fee)
                                      (= performance fee charged on the
                                       borrow / funding cost slice of the yield,
                                       which the depositor never received)
    net_return_after_fee_pct          = net_of_borrow_cost_yield - fee_charged
    net_return_fair_pct               = net_of_borrow_cost_yield - fair_fee
    overstatement_pct                 = fee_on_borrow_cost_gap_pct
    fee_on_borrow_cost_fraction       = clamp(gap / fee_charged, 0, 1)
    realization_ratio                 = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay a performance fee on what you earned", but with
the performance fee charged on the gross yield the fee is taken on the whole
pre-borrow-cost yield while the depositor only ever kept the net-of-borrow-cost
slice — so a chunk of the performance fee landed on the borrow / funding cost
slice the leverage consumed. The scale-free fee_on_borrow_cost_fraction is the
share of the charged performance fee that landed on the borrow-cost slice; it is
the basis of the classification. When the borrow cost consumed nothing
(net_of_borrow_cost ≈ gross) there was no borrow slice and the performance fee
was fair (HIGHER score). When the borrow / funding cost consumed most of the
yield (net_of_borrow_cost ≈ 0 or the net return goes negative after the fee), the
performance fee was charged almost entirely on the borrow-cost slice (LOWER
score).

HIGHER score = the performance fee was charged on the net-of-borrow-cost base
(gross ≈ net_of_borrow_cost), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the borrow / funding
cost slice, or the net return goes negative after the fee.

Override path (when fee_on_borrow_cost_gap_pct is supplied directly, finite, AND
a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are present): take
the gap verbatim (negative → magnitude) and skip the net-of-borrow-cost /
borrow-cost geometry — fee_on_borrow_cost_fraction and the metrics are computed
the same way:

    fee_on_borrow_cost_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-borrow-cost / borrow-slice / fair geometry is
not known → those fields are reported as None, and the geometry-only flags
FEE_ON_BORROW_COST / FULL_FEE_ON_BORROW / NET_NEGATIVE_AFTER_FEE are NOT raised;
realization_ratio is anchored to (1 - fee_on_borrow_cost_fraction).)

Distinct from (this is the COST OF LEVERAGE — interest on the debt / perp
funding — paid OUT to service the borrowed plug, an economic layer distinct from
an internal retained buffer or a network/keeper cost):
  * defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer — that
    prices the performance fee charged on the GROSS-OF-COST base: the gas /
    keeper / HARVEST costs the VAULT PAYS to a keeper/network to realize the
    yield. HERE it is the BORROW / FUNDING cost of the leverage (interest on the
    debt / perp funding) — the price of the borrowed plug, NOT the
    keeper/network cost of harvesting. Distinct axis.
  * defi_protocol_vault_performance_fee_protocol_revenue_share_base_gap_analyzer
    — that prices the performance fee charged on the gross-of-revenue-share base:
    the EXTERNAL underlying protocol's revenue-share / take-rate cut, value the
    external protocol extracts before it reaches the depositor. HERE the layer is
    the borrow / funding cost of leverage, NOT an external protocol's cut.
    Distinct axis.
  * defi_protocol_vault_performance_fee_gross_of_reserve_contribution_base_gap_analyzer
    — that prices the performance fee charged on the gross-of-reserve base: an
    INTERNAL insurance / safety / reserve buffer the vault RETAINS out of the
    yield. HERE it is the borrow / funding cost of leverage paid OUT to service
    the debt, NOT an internal retained buffer. Distinct axis.
  * defi_protocol_vault_performance_fee_management_fee_base_gap_analyzer — that
    prices the performance fee charged on the vault's OWN MANAGEMENT / AUM-fee
    layer of the return (the gross-of-management base; a fee-on-fee). HERE it is
    the borrow / funding cost of leverage, not a fee layer. Distinct axis.
  * borrow_rate_optimizer / borrowing_cost_optimizer / leverage / APY modules —
    those measure the borrow RATE itself, leverage RISK, or net leveraged APY.
    HERE the axis is the performance-fee BASE being gross-of-borrow-cost: the fee
    being charged on the gross (pre-borrow-cost) yield rather than the
    net-of-borrow-cost yield, NOT the borrow rate / leverage risk / APY itself.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices
    the mechanics of the HWM RESET over TIME for the WHOLE NAV series. HERE it is
    the static gap between the GROSS base and the NET-OF-BORROW-COST base for a
    SINGLE fee period.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path. HERE there is no path:
    it is the static gap between the gross yield and the yield net of the borrow
    / funding cost.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that
    prices how OFTEN the fee crystallises. HERE it is what the fee is assessed
    ACROSS (gross yield vs the net-of-borrow-cost slice), regardless of frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices
    the fee charged on BETA (benchmark-level return over a too-low hurdle) vs
    ALPHA. HERE it is the fee charged on the borrow-cost slice of the yield, the
    slice the leverage consumed, independent of any benchmark.
  * defi_protocol_vault_performance_fee_catch_up_clause_gap_analyzer — that
    prices the catch-up clause clawing back the hurdle exemption. HERE it is the
    static gross-of-borrow-cost base, independent of any hurdle/catch-up.

The novel axis here: the performance-fee BASE being GROSS-OF-BORROW-COST rather
than NET-OF-BORROW-COST — a fee-on-borrow / fee-base inflation in which the
performance fee is charged on the slice of yield that went to servicing the
borrow / funding cost (interest on the debt / perp funding) of the vault's
leveraged strategy.

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
    "data", "vault_performance_fee_gross_of_borrow_cost_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_borrow_cost_fraction in
# [0, 1] (= fee_on_borrow_cost_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-borrow-cost base
MILD_FRACTION = 0.20         # at/below → mild fee-on-borrow gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-borrow-cost flag threshold on borrow_cost_rate_pct.
HIGH_BORROW_COST_PCT = 10.0

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
    net-of-borrow-cost-yield field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfBorrowCostBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the borrow / funding cost of the leverage is netted out) and
    the FAIR fee it would charge on the NET-OF-BORROW-COST yield the depositor
    actually keeps after servicing the debt, and the share of the charged
    performance fee that therefore landed on the BORROW-COST slice of the yield
    (a fee-on-borrow / fee-base inflation).

        fee_frac                     = clamp(performance_fee_pct / 100, 0, 1)
        borrow_consumed_yield_pct    = max(0, gross_yield - net_of_borrow_cost_yield)
        fee_charged_pct              = fee_frac * max(0, gross_yield)
        fair_fee_pct                 = fee_frac * max(0, net_of_borrow_cost_yield)
        fee_on_borrow_cost_gap_pct   = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct     = net_of_borrow_cost_yield - fee_charged
        net_return_fair_pct          = net_of_borrow_cost_yield - fair_fee
        overstatement_pct            = fee_on_borrow_cost_gap_pct
        fee_on_borrow_cost_fraction  = clamp(gap / fee_charged, 0, 1)
        realization_ratio            = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-borrow-cost yield. When the net-of-borrow-cost
    yield equals (or exceeds) the gross yield the borrow cost consumed nothing
    and the performance fee was charged on the right base
    (CLEAN_NET_OF_BORROW_BASE). When the borrow / funding cost consumed a large
    share of the yield, a large share of the performance fee was charged on the
    borrow slice (MODERATE / SEVERE fee-on-borrow gap), and if the fee exceeds
    the net-of-borrow-cost yield the net return goes negative.

    HIGHER score = the performance fee was charged on the net-of-borrow-cost base
    (gross ≈ net_of_borrow_cost), the fee was effectively fair, nothing to fix.
    LOWER score = a large share of the performance fee landed on the borrow /
    funding cost slice the depositor never received, or the net return goes
    negative after the fee.

    Per-position input dict fields:
        vault / token                  : str
        gross_yield_pct                : float — the GROSS yield (before the
                                         borrow / funding cost of the leverage is
                                         netted out) on which the performance fee
                                         is assessed. REQUIRED, must be a finite
                                         POSITIVE number (else INSUFFICIENT_DATA).
        net_of_borrow_cost_yield_pct   : float — the yield NET OF the borrow /
                                         funding cost (finite; may be < gross; may
                                         be negative; default 0.0 = the borrow
                                         cost consumed the whole yield).
        performance_fee_pct            : float — performance-fee rate % (REQUIRED
                                         finite, clamped into 0..100; non-finite →
                                         INSUFFICIENT_DATA on the main path).
        borrow_cost_rate_pct           : float — OPTIONAL informational borrow /
                                         funding cost rate %; ≥ HIGH_BORROW_COST_PCT
                                         raises HIGH_BORROW_COST.
        fee_on_borrow_cost_gap_pct     : float — OPTIONAL direct override of the
                                         fee-on-borrow gap (the performance fee
                                         charged on the borrow-cost slice). When
                                         supplied (finite; negative → magnitude)
                                         AND a valid POSITIVE gross_yield_pct and
                                         POSITIVE fee_charged_pct are present, take
                                         this gap directly and skip the
                                         net-of-borrow-cost / borrow-cost geometry
                                         (override path; geometry → None).
        fee_charged_pct                : float — OPTIONAL, only used on the override
                                         path as the denominator for
                                         fee_on_borrow_cost_fraction (finite > 0
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

        borrow_rate = _coerce_num(p.get("borrow_cost_rate_pct"))

        # Override path: a direct fee-on-borrow gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_borrow_cost_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, borrow_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, gross_gain, fee_pct, borrow_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        borrow_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-borrow-cost yield may legitimately be negative (the borrow
        # cost exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_borrow_cost_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        borrow_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_borrow_cost_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_borrow_cost_yield_pct=net_gain,
            borrow_consumed_yield_pct=borrow_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_borrow_cost_gap_pct=fee_on_borrow_cost_gap_pct,
            borrow_cost_rate_pct=borrow_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        borrow_rate: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-borrow-cost / borrow-slice / fair geometry is unknown on the
        # override path → report None; net return can not be derived without
        # net_of_borrow_cost_yield, so net-negative / full-fee-on-borrow flags /
        # ratio fall back to the gap share.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_borrow_cost_yield_pct=None,
            borrow_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_borrow_cost_gap_pct=gap,
            borrow_cost_rate_pct=borrow_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_borrow_cost_yield_pct: Optional[float],
        borrow_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_borrow_cost_gap_pct: float,
        borrow_cost_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the borrow-cost slice
        # (kept for family consistency with the headline-honesty family).
        overstatement_pct = fee_on_borrow_cost_gap_pct

        # Net return: only computable when net-of-borrow-cost geometry is known.
        if net_of_borrow_cost_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_borrow_cost_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_borrow_cost_yield_pct - fair_fee_pct)
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                # Mirror the hurdle/clawback template edge: when the fair net is
                # non-positive, the ratio is 1.0 only if the charged net still
                # clears the fair net and is itself non-negative, else 0.0.
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
        else:
            # Override path: net-of-borrow-cost geometry unknown. Treat
            # realisation via the fee-on-borrow share as the proxy below; flag as
            # not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-borrow fraction — the share of the charged
        # performance fee that landed on the borrow-cost slice.
        if fee_charged_pct > EPS:
            fee_on_borrow_cost_fraction = _clamp(
                fee_on_borrow_cost_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_borrow_cost_fraction = 0.0

        # On the override path, with no net-of-borrow-cost geometry, anchor the
        # realisation on (1 - fee_on_borrow_cost_fraction): the share of the fee
        # that fell on the net-of-borrow-cost yield is the share the depositor
        # "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_borrow_cost_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_borrow_cost_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_borrow_cost_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_borrow_cost_yield_pct,
            borrow_consumed_yield_pct,
            gross_yield_pct,
            borrow_cost_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_borrow_cost_yield_pct": (
                round(net_of_borrow_cost_yield_pct, 4)
                if net_of_borrow_cost_yield_pct is not None else None),
            "borrow_consumed_yield_pct": (
                round(borrow_consumed_yield_pct, 4)
                if borrow_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_borrow_cost_gap_pct": round(
                fee_on_borrow_cost_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_borrow_cost_fraction": round(
                fee_on_borrow_cost_fraction, 4),
            "net_is_negative": net_is_negative,
            "borrow_cost_rate_pct": (
                round(borrow_cost_rate_pct, 4)
                if borrow_cost_rate_pct is not None else None),
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
        fee_on_borrow_cost_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the net-of-borrow-cost
        yield the depositor actually kept: the depositor keeps the yield that
        survived the borrow / funding cost of the leverage. Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            fair net return that survives the gross-based fee,
          * fee-base penalty = clamp(1 − fee_on_borrow_cost_fraction, 0, 1) —
            penalises a large share of the fee being charged on the borrow-cost
            slice.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_borrow_cost_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_borrow_cost_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole net-of-borrow-cost yield (or more).
            return "SEVERE_FEE_ON_BORROW_GAP"
        if fee_on_borrow_cost_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_BORROW_BASE"
        if fee_on_borrow_cost_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_BORROW_GAP"
        if fee_on_borrow_cost_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_BORROW_GAP"
        return "SEVERE_FEE_ON_BORROW_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_BORROW"
        if classification == "CLEAN_NET_OF_BORROW_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_BORROW_GAP":
            return "MINOR_FEE_ON_BORROW"
        if classification == "MODERATE_FEE_ON_BORROW_GAP":
            return "DEMAND_NET_OF_BORROW_BASE"
        # SEVERE_FEE_ON_BORROW_GAP
        return "AVOID_FEE_ON_BORROW"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_borrow_cost_yield_pct: Optional[float],
        borrow_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        borrow_cost_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_NET_OF_BORROW_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (borrow_cost_rate_pct is not None
                and borrow_cost_rate_pct >= HIGH_BORROW_COST_PCT):
            flags.append("HIGH_BORROW_COST")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (borrow_consumed_yield_pct is not None
                    and borrow_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_BORROW_COST")
            if (net_of_borrow_cost_yield_pct is not None
                    and net_of_borrow_cost_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_BORROW")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_borrow_cost_yield_pct": None,
            "borrow_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_borrow_cost_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_borrow_cost_fraction": None,
            "net_is_negative": False,
            "borrow_cost_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_BORROW",
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
                "worst_borrow_gap_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = charged on the net-of-borrow-cost base / fee fair →
        # highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_borrow_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_BORROW_BASE: net_of_borrow ≈ gross → the borrow cost
            # consumed nothing, the performance fee was charged on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 18.0,
            "net_of_borrow_cost_yield_pct": 18.0,
            "performance_fee_pct": 20.0,
            "borrow_cost_rate_pct": 0.0,
        },
        {
            # MODERATE_FEE_ON_BORROW_GAP: gross 16, net 8 → ~half the fee was
            # charged on the borrow slice (fraction ~ 0.5).
            "vault": "stETH-Vault-ModerateBorrow",
            "gross_yield_pct": 16.0,
            "net_of_borrow_cost_yield_pct": 8.0,
            "performance_fee_pct": 20.0,
            "borrow_cost_rate_pct": 12.0,
        },
        {
            # SEVERE_FEE_ON_BORROW_GAP (net negative): the borrow / funding cost
            # drove the net-of-borrow-cost yield negative, yet the performance fee
            # is still charged on the gross yield → fair net return is negative.
            "vault": "GOV-Vault-SevereBorrow",
            "gross_yield_pct": 12.0,
            "net_of_borrow_cost_yield_pct": -3.0,
            "performance_fee_pct": 50.0,
            "borrow_cost_rate_pct": 15.0,
        },
        {
            # Override path: a fee-on-borrow gap supplied directly with the fee
            # charged → fraction = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_yield_pct": 24.0,
            "fee_on_borrow_cost_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_borrow_cost_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1216 Vault Performance-Fee Gross-Of-Borrow-Cost-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfBorrowCostBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
