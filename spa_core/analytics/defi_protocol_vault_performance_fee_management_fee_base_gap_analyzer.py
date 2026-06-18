"""
MP-1211: DeFiProtocolVaultPerformanceFeeManagementFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault charges its PERFORMANCE fee on the GROSS return — the return BEFORE the
management (AUM) fee is deducted. The FAIR base would be the return NET OF the
management fee: the management fee is the manager's first claim on the return,
and the performance fee should only reward the slice of return that remains after
it. When the performance fee is levied on the gross return instead, the depositor
pays a performance fee on the very slice of return the management fee already
consumed — a "fee-on-fee" / fee-stacking. The fee is levied on the gross return;
the FAIR fee would be levied only on the net-of-management return:

    fee_frac                = clamp(performance_fee_pct / 100, 0, 1)
    mgmt_consumed_return_pct = max(0, gross_return_pct - net_of_mgmt_return_pct)
    fee_charged_pct         = fee_frac * max(0, gross_return_pct)
    fair_fee_pct            = fee_frac * max(0, net_of_mgmt_return_pct)
    fee_on_fee_gap_pct      = max(0, fee_charged_pct - fair_fee_pct)
                            (= performance fee charged on the management-fee layer
                             of the return, which the depositor never kept)
    net_return_after_fee_pct = net_of_mgmt_return_pct - fee_charged_pct
    net_return_fair_pct      = net_of_mgmt_return_pct - fair_fee_pct
    overstatement_pct        = fee_on_fee_gap_pct
    fee_on_mgmt_fraction      = clamp(fee_on_fee_gap / fee_charged, 0, 1)
    realization_ratio         = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay a performance fee on what you earned", but with the
performance fee charged on the gross return the fee is taken on the whole pre-AUM-fee
return while the depositor only ever kept the net-of-management slice — so a chunk of
the performance fee landed on the management-fee layer of the return the depositor
never kept. The scale-free fee_on_mgmt_fraction is the share of the charged
performance fee that landed on the management-fee layer; it is the basis of the
classification. When the management fee consumed nothing (net_of_mgmt ≈ gross) there
was no management-fee layer and the performance fee was fair (HIGHER score). When the
management fee consumed most of the return (net_of_mgmt ≈ 0 or the net return goes
negative after the fee), the performance fee was charged almost entirely on the
management-fee layer (LOWER score).

HIGHER score = the performance fee was charged on the net-of-management base
(gross ≈ net_of_mgmt), the fee was effectively fair, nothing to fix. LOWER score =
a large share of the performance fee landed on the management-fee layer, or the net
return goes negative after the fee.

Override path (when fee_on_fee_gap_pct is supplied directly, finite, AND a valid
POSITIVE gross_return_pct and POSITIVE fee_charged_pct are present): take the
gap verbatim (negative → magnitude) and skip the net-of-management / management-fee
geometry — fee_on_mgmt_fraction and the metrics are computed the same way:

    fee_on_mgmt_fraction = clamp(fee_on_fee_gap_pct / fee_charged_pct, 0, 1)

(On the override path the net-of-management / management-fee-layer / fair geometry is
not known → those fields are reported as None, and the geometry-only flags
FEE_ON_MGMT_LAYER / FULL_FEE_ON_FEE / NET_NEGATIVE_AFTER_FEE are NOT raised;
realization_ratio is anchored to (1 - fee_on_mgmt_fraction).)

Distinct from:
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET over TIME for the WHOLE NAV series (does the fee
    wait for the prior peak to recover). HERE it is the static gap between the
    GROSS base and the NET-OF-MANAGEMENT base for a SINGLE fee period.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path (fee on up-legs, no
    refund on down-legs). HERE there is no path: it is the static gap between the
    gross return and the return net of the management fee.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises. HERE it is what the fee is assessed ACROSS
    (gross return vs the net-of-management slice), regardless of frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices the
    fee charged on BETA (benchmark-level return over a too-low hurdle) vs ALPHA.
    HERE it is the fee charged on the MANAGEMENT-FEE layer of the return, the AUM
    fee's own claim, independent of any benchmark / hurdle.
  * defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer —
    that prices a fee on an UNREALIZED peak mark of ONE position that later
    REVERSED with no clawback (a TEMPORAL reversal). HERE the gap is the FEE BASE:
    gross vs net-of-management for a single period, not a later reversal of a mark.
  * defi_protocol_vault_performance_fee_cross_sleeve_netting_gap_analyzer — that
    nets gross winning sleeves against concurrent losing sleeves in one period
    (a CROSS-SECTIONAL offset). HERE the axis is the FEE-LAYER STACKING within a
    single sleeve: gross return vs the net-of-management return, NOT a cross-sleeve
    netting.
  * defi_protocol_vault_performance_fee_subscription_timing_equalization_gap_analyzer
    — that prices a SUBSCRIBER-RELATIVE gap between the full-period base and the
    post-entry base (entry timing / equalization). HERE the gap is the FEE BASE
    relative to the MANAGEMENT FEE, independent of any subscriber's entry timing.
  * defi_protocol_vault_management_fee_accrual_analyzer — that prices the
    continuous AUM-fee DRAG itself (the management fee in isolation). HERE the axis
    is the INTERACTION: the performance-fee base being gross-of-management-fee
    rather than net, not the management-fee drag on its own.
  * defi_protocol_vault_management_fee_on_idle_capital_analyzer — that prices a
    management fee charged on UNINVESTED cash (idle capital). HERE the axis is the
    performance-fee base being gross-of-management, not where the management fee is
    charged.

The novel axis here: the performance-fee BASE being GROSS-OF-MANAGEMENT-FEE rather
than NET-OF-MANAGEMENT-FEE — a fee-on-fee / fee-stacking interaction in which the
performance fee is charged on the slice of return the management (AUM) fee already
consumed.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_management_fee_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_mgmt_fraction in [0, 1]
# (= fee_on_fee_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-mgmt base
MILD_FRACTION = 0.20         # at/below → mild fee-on-fee gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe fee-on-fee gap

# High-management-fee flag threshold on management_fee_pct.
HIGH_MGMT_FEE_PCT = 2.0

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
    net-of-management-return field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeManagementFeeBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    return (before the management/AUM fee is deducted) and the FAIR fee it would
    charge on the NET-OF-MANAGEMENT return the depositor actually kept, and the
    share of the charged performance fee that therefore landed on the
    MANAGEMENT-FEE layer of the return (a fee-on-fee / fee-stacking interaction).

        fee_frac                  = clamp(performance_fee_pct / 100, 0, 1)
        mgmt_consumed_return_pct  = max(0, gross_return - net_of_mgmt_return)
        fee_charged_pct           = fee_frac * max(0, gross_return)
        fair_fee_pct              = fee_frac * max(0, net_of_mgmt_return)
        fee_on_fee_gap_pct        = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct  = net_of_mgmt_return - fee_charged
        net_return_fair_pct       = net_of_mgmt_return - fair_fee
        overstatement_pct         = fee_on_fee_gap_pct
        fee_on_mgmt_fraction      = clamp(fee_on_fee_gap / fee_charged, 0, 1)
        realization_ratio         = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross return; the fair fee would be
    charged only on the net-of-management return. When the net-of-management return
    equals (or exceeds) the gross return the management fee consumed nothing and the
    performance fee was charged on the right base (CLEAN_NET_OF_MGMT_BASE). When the
    management fee consumed a large share of the return, a large share of the
    performance fee was charged on the management-fee layer (MODERATE / SEVERE
    fee-on-fee gap), and if the fee exceeds the net-of-management return the net
    return goes negative.

    HIGHER score = the performance fee was charged on the net-of-management base
    (gross ≈ net_of_mgmt), the fee was effectively fair, nothing to fix. LOWER
    score = a large share of the performance fee landed on the management-fee layer
    the depositor never kept, or the net return goes negative after the fee.

    Per-position input dict fields:
        vault / token            : str
        gross_return_pct         : float — the GROSS return (before the AUM fee) on
                                   which the performance fee is assessed. REQUIRED,
                                   must be a finite POSITIVE number (else
                                   INSUFFICIENT_DATA).
        net_of_mgmt_return_pct   : float — the return NET OF the management fee
                                   (finite; may be < gross; may be negative;
                                   default 0.0 = the management fee consumed the
                                   whole return).
        performance_fee_pct      : float — performance-fee rate % (REQUIRED finite,
                                   clamped into 0..100; non-finite →
                                   INSUFFICIENT_DATA on the main path).
        management_fee_pct       : float — OPTIONAL informational management (AUM)
                                   fee rate %; ≥ HIGH_MGMT_FEE_PCT raises
                                   HIGH_MGMT_FEE.
        fee_on_fee_gap_pct       : float — OPTIONAL direct override of the
                                   fee-on-fee gap (the performance fee charged on the
                                   management-fee layer). When supplied (finite;
                                   negative → magnitude) AND a valid POSITIVE
                                   gross_return_pct and POSITIVE fee_charged_pct are
                                   present, take this gap directly and skip the
                                   net-of-management / management-fee geometry
                                   (override path; geometry → None).
        fee_charged_pct          : float — OPTIONAL, only used on the override path
                                   as the denominator for fee_on_mgmt_fraction
                                   (finite > 0 required to take the override path).
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

        # The gross return is required and must be finite & positive.
        gross_gain = _coerce_num(p.get("gross_return_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        mgmt_fee = _coerce_num(p.get("management_fee_pct"))

        # Override path: a direct fee-on-fee gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, mgmt_fee)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, gross_gain, fee_pct, mgmt_fee)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        mgmt_fee: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-management return may legitimately be negative (mgmt fee exceeds
        # the gross return).
        net_gain = _coerce_signed(p.get("net_of_mgmt_return_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        mgmt_consumed_return_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_fee_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_return_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_mgmt_return_pct=net_gain,
            mgmt_consumed_return_pct=mgmt_consumed_return_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_fee_gap_pct=fee_on_fee_gap_pct,
            management_fee_pct=mgmt_fee,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        mgmt_fee: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-management / management-fee / fair geometry is unknown on the
        # override path → report None; net return can not be derived without
        # net_of_mgmt_return, so net-negative / full-fee-on-fee flags / ratio fall
        # back to the gap share.
        return self._finish(
            token=token,
            gross_return_pct=gross_gain,
            fee_frac=None,
            net_of_mgmt_return_pct=None,
            mgmt_consumed_return_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_fee_gap_pct=gap,
            management_fee_pct=mgmt_fee,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_return_pct: float,
        fee_frac: Optional[float],
        net_of_mgmt_return_pct: Optional[float],
        mgmt_consumed_return_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_fee_gap_pct: float,
        management_fee_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the management-fee layer
        # (kept for family consistency with the headline-honesty family).
        overstatement_pct = fee_on_fee_gap_pct

        # Net return: only computable when net-of-management geometry is known.
        if net_of_mgmt_return_pct is not None:
            net_return_after_fee_pct = net_of_mgmt_return_pct - fee_charged_pct
            net_return_fair_pct = net_of_mgmt_return_pct - fair_fee_pct
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
            # Override path: net-of-management geometry unknown. Treat realisation
            # via the fee-on-mgmt share as the proxy below; flag as not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-mgmt fraction — the share of the charged performance
        # fee that landed on the management-fee layer of the return.
        if fee_charged_pct > EPS:
            fee_on_mgmt_fraction = _clamp(
                fee_on_fee_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_mgmt_fraction = 0.0

        # On the override path, with no net-of-management geometry, anchor the
        # realisation on (1 - fee_on_mgmt_fraction): the share of the fee that fell
        # on the net-of-management return is the share the depositor "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_mgmt_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_mgmt_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_mgmt_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_mgmt_return_pct,
            mgmt_consumed_return_pct,
            gross_return_pct,
            management_fee_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_return_pct": round(gross_return_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_mgmt_return_pct": (
                round(net_of_mgmt_return_pct, 4)
                if net_of_mgmt_return_pct is not None else None),
            "mgmt_consumed_return_pct": (
                round(mgmt_consumed_return_pct, 4)
                if mgmt_consumed_return_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_fee_gap_pct": round(fee_on_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_mgmt_fraction": round(fee_on_mgmt_fraction, 4),
            "net_is_negative": net_is_negative,
            "management_fee_pct": (
                round(management_fee_pct, 4)
                if management_fee_pct is not None else None),
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
        fee_on_mgmt_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the net-of-management
        return the depositor actually kept: the depositor keeps the return that
        survived the AUM fee. Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the fair
            net return that survives the gross-based fee,
          * fee-base penalty = clamp(1 − fee_on_mgmt_fraction, 0, 1) — penalises a
            large share of the fee being charged on the management-fee layer.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_mgmt_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_mgmt_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole net-of-management return (or more).
            return "SEVERE_FEE_ON_FEE_GAP"
        if fee_on_mgmt_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_MGMT_BASE"
        if fee_on_mgmt_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_FEE_GAP"
        if fee_on_mgmt_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_FEE_GAP"
        return "SEVERE_FEE_ON_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_FEE"
        if classification == "CLEAN_NET_OF_MGMT_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_FEE_GAP":
            return "MINOR_FEE_ON_FEE"
        if classification == "MODERATE_FEE_ON_FEE_GAP":
            return "DEMAND_NET_OF_MGMT_BASE"
        # SEVERE_FEE_ON_FEE_GAP
        return "AVOID_FEE_ON_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_mgmt_return_pct: Optional[float],
        mgmt_consumed_return_pct: Optional[float],
        gross_return_pct: float,
        management_fee_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_NET_OF_MGMT_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (management_fee_pct is not None
                and management_fee_pct >= HIGH_MGMT_FEE_PCT):
            flags.append("HIGH_MGMT_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (mgmt_consumed_return_pct is not None
                    and mgmt_consumed_return_pct > 0.0):
                flags.append("FEE_ON_MGMT_LAYER")
            if (net_of_mgmt_return_pct is not None
                    and net_of_mgmt_return_pct <= 0.0
                    and gross_return_pct > 0.0):
                flags.append("FULL_FEE_ON_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_return_pct": None,
            "performance_fee_pct": None,
            "net_of_mgmt_return_pct": None,
            "mgmt_consumed_return_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_mgmt_fraction": None,
            "net_is_negative": False,
            "management_fee_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_FEE",
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
                "worst_fee_on_fee_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = charged on the net-of-mgmt base / fee fair → highest score
        # is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_fee_on_fee_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_MGMT_BASE: net_of_mgmt ≈ gross → the management fee
            # consumed nothing, the performance fee was charged on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_return_pct": 18.0,
            "net_of_mgmt_return_pct": 18.0,
            "performance_fee_pct": 20.0,
            "management_fee_pct": 0.0,
        },
        {
            # MODERATE_FEE_ON_FEE_GAP: gross 16, net_of_mgmt 8 → ~half the fee was
            # charged on the management-fee layer (fee_on_mgmt ~ 0.5).
            "vault": "stETH-Vault-ModerateFeeOnFee",
            "gross_return_pct": 16.0,
            "net_of_mgmt_return_pct": 8.0,
            "performance_fee_pct": 20.0,
            "management_fee_pct": 2.0,
        },
        {
            # SEVERE_FEE_ON_FEE_GAP (net negative): the management fee drove the
            # net-of-mgmt return negative, yet the performance fee is still charged
            # on the gross return → fair net return is negative.
            "vault": "GOV-Vault-SevereFeeOnFee",
            "gross_return_pct": 12.0,
            "net_of_mgmt_return_pct": -3.0,
            "performance_fee_pct": 50.0,
            "management_fee_pct": 3.0,
        },
        {
            # Override path: a fee-on-fee gap supplied directly with the fee
            # charged → fee_on_mgmt = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_return_pct": 24.0,
            "fee_on_fee_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross return supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_mgmt_return_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1211 Vault Performance-Fee Management-Fee-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeManagementFeeBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
