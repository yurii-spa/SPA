"""
MP-1210: DeFiProtocolVaultPerformanceFeeSubscriptionTimingEqualizationGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault crystallises a PERFORMANCE fee on the FULL-PERIOD NAV gain, but a
depositor who SUBSCRIBED MID-PERIOD only earned the gain that accrued AFTER his
entry. Without equalization (series accounting / equalization credits) the
mid-period subscriber pays a performance fee on the profit that arose BEFORE his
entry — profit he never received. The fee is levied on the full-period gain; the
FAIR fee would be levied only on the post-entry (since-subscription) gain:

    fee_frac                = clamp(performance_fee_pct / 100, 0, 1)
    pre_entry_gain_pct      = max(0, full_period_gain_pct - post_entry_gain_pct)
    fee_charged_pct         = fee_frac * max(0, full_period_gain_pct)
    fair_fee_pct            = fee_frac * max(0, post_entry_gain_pct)
    equalization_gap_pct    = max(0, fee_charged_pct - fair_fee_pct)
                            (= fee charged on the pre-entry gain the subscriber
                             never earned, never credited back via equalization)
    net_return_after_fee_pct = post_entry_gain_pct - fee_charged_pct
    net_return_fair_pct      = post_entry_gain_pct - fair_fee_pct
    overstatement_pct        = equalization_gap_pct
    fee_on_pre_entry_fraction = clamp(equalization_gap / fee_charged, 0, 1)
    realization_ratio         = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay on the gains you made", but with no equalization
the fee is taken on the whole period's gain while the subscriber only ever
participated in the post-entry slice — so a chunk of the fee was charged on
profit that arose before he ever entered. The scale-free fee_on_pre_entry_fraction
is the share of the charged fee that landed on the pre-entry (un-earned) gain; it
is the basis of the classification. When the subscriber entered at the start of
the period (post_entry ≈ full) there was no pre-entry gain and the fee was fair
(HIGHER score). When the subscriber entered at a peak (post_entry ≈ 0 or the net
return goes negative after the fee), the fee was charged almost entirely on gains
the subscriber never earned (LOWER score).

HIGHER score = the subscriber entered at the start of the period (post_entry ≈
full), the fee was effectively fair, equalization would change nothing. LOWER
score = a large share of the fee was charged on pre-entry gains the subscriber
never earned, or the net return goes negative after the fee.

Override path (when equalization_gap_pct is supplied directly, finite, AND a valid
POSITIVE full_period_gain_pct and POSITIVE fee_charged_pct are present): take the
gap verbatim (negative → magnitude) and skip the post-entry / pre-entry geometry —
fee_on_pre_entry_fraction and the metrics are computed the same way:

    fee_on_pre_entry_fraction = clamp(equalization_gap_pct / fee_charged_pct, 0, 1)

(On the override path the post-entry / pre-entry / fair geometry is not known →
those fields are reported as None, and the geometry-only flags FEE_ON_PRE_ENTRY_
GAINS / FULL_PRE_ENTRY / NET_NEGATIVE_AFTER_FEE are NOT raised; realization_ratio
is anchored to (1 - fee_on_pre_entry_fraction).)

Distinct from:
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET over TIME for the WHOLE NAV series (does the fee
    wait for the prior peak to recover). HERE it is the SUBSCRIBER-RELATIVE gap
    between the full-period base and the post-entry base for a SINGLE fee period.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path (fee on up-legs, no
    refund on down-legs). HERE there is no path: it is the static gap between the
    full-period gain and the gain accrued after a single entry timestamp.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises. HERE it is what the fee is assessed ACROSS
    (full-period gain vs the post-entry slice), regardless of frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices the
    fee charged on BETA (benchmark-level return over a too-low hurdle) vs ALPHA.
    HERE it is the fee charged on the PRE-ENTRY gain a late subscriber never
    earned, independent of any benchmark / hurdle.
  * defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer —
    that prices a fee on an UNREALIZED peak mark of ONE position that later
    REVERSED with no clawback (a TEMPORAL reversal). HERE the gap is the SUBSCRIBER
    ENTRY TIMING: gains that arose before the subscriber entered, not a later
    reversal of a mark he held.
  * defi_protocol_vault_performance_fee_cross_sleeve_netting_gap_analyzer — that
    nets gross winning sleeves against concurrent losing sleeves in one period
    (a CROSS-SECTIONAL offset). HERE the axis is the SUBSCRIPTION TIMING within a
    single sleeve: full-period gain vs the post-entry gain for a mid-period
    subscriber, NOT a cross-sleeve netting.

The novel axis here: a performance fee charged on the FULL-PERIOD gain for a
MID-PERIOD subscriber without equalization (series accounting / equalization
credits), so the subscriber pays a fee on pre-entry gains he never earned.

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
    "data", "vault_performance_fee_subscription_timing_equalization_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_pre_entry_fraction in [0, 1]
# (= equalization_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly equalized (entered at start)
MILD_FRACTION = 0.20         # at/below → mild equalization gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe equalization gap

# Late-subscription flag threshold on entry_fraction_of_period in [0, 1].
LATE_SUBSCRIPTION_FRACTION = 0.5

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
    post-entry-gain field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeSubscriptionTimingEqualizationGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the FULL-PERIOD
    NAV gain and the FAIR fee it would charge on the POST-ENTRY (since-subscription)
    gain a mid-period subscriber actually earned, and the share of the charged fee
    that therefore landed on PRE-ENTRY gains the subscriber never earned (no
    equalization / series accounting).

        fee_frac                  = clamp(performance_fee_pct / 100, 0, 1)
        pre_entry_gain_pct        = max(0, full_period_gain - post_entry_gain)
        fee_charged_pct           = fee_frac * max(0, full_period_gain)
        fair_fee_pct              = fee_frac * max(0, post_entry_gain)
        equalization_gap_pct      = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct  = post_entry_gain - fee_charged
        net_return_fair_pct       = post_entry_gain - fair_fee
        overstatement_pct         = equalization_gap_pct
        fee_on_pre_entry_fraction = clamp(equalization_gap / fee_charged, 0, 1)
        realization_ratio         = clamp(net_after_fee / net_fair, 0, 1)

    The fee is charged on the full-period gain; the fair fee would be charged only
    on the post-entry gain. When the post-entry gain equals (or exceeds) the
    full-period gain the subscriber entered at the start and there was no pre-entry
    gain (CLEAN_FULLY_EQUALIZED). When the subscriber entered late and a large
    share of the gain accrued before entry, a large share of the fee was charged on
    pre-entry gains (MODERATE / SEVERE equalization gap), and if the fee exceeds the
    post-entry return the net return goes negative.

    HIGHER score = the subscriber entered at the start of the period (post_entry ≈
    full), the fee was effectively fair, equalization would change nothing. LOWER
    score = a large share of the fee was charged on pre-entry gains the subscriber
    never earned, or the net return goes negative after the fee.

    Per-position input dict fields:
        vault / token            : str
        full_period_gain_pct     : float — the FULL-PERIOD NAV gain on which the fee
                                   is assessed. REQUIRED, must be a finite POSITIVE
                                   number (else INSUFFICIENT_DATA).
        post_entry_gain_pct      : float — the gain accrued AFTER the subscriber's
                                   entry (finite; may be < full; may be negative;
                                   default 0.0 = entered at the peak, earned
                                   nothing).
        performance_fee_pct      : float — performance-fee rate % (REQUIRED finite,
                                   clamped into 0..100; non-finite →
                                   INSUFFICIENT_DATA on the main path).
        entry_fraction_of_period : float — OPTIONAL informational fraction of the
                                   period (0..1) that elapsed before entry; ≥0.5
                                   raises LATE_SUBSCRIPTION.
        equalization_gap_pct     : float — OPTIONAL direct override of the
                                   equalization gap (the fee charged on pre-entry
                                   gains). When supplied (finite; negative →
                                   magnitude) AND a valid POSITIVE
                                   full_period_gain_pct and POSITIVE fee_charged_pct
                                   are present, take this gap directly and skip the
                                   post-entry / pre-entry geometry (override path;
                                   geometry → None).
        fee_charged_pct          : float — OPTIONAL, only used on the override path
                                   as the denominator for fee_on_pre_entry_fraction
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

        # The full-period gain is required and must be finite & positive.
        full_gain = _coerce_num(p.get("full_period_gain_pct"))
        if full_gain is None or not math.isfinite(full_gain) or full_gain <= 0.0:
            return self._insufficient(token)

        entry_fraction = _coerce_num(p.get("entry_fraction_of_period"))

        # Override path: a direct equalization gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("equalization_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, full_gain, abs(gap_o), fee_charged_o, entry_fraction)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, full_gain, fee_pct, entry_fraction)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, full_gain: float, fee_pct: float,
        entry_fraction: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # post-entry gain may legitimately be negative (entered above the peak).
        post_gain = _coerce_signed(p.get("post_entry_gain_pct"))
        if post_gain is None or not math.isfinite(post_gain):
            post_gain = 0.0

        pre_entry_gain_pct = max(0.0, full_gain - post_gain)
        fee_charged_pct = fee_frac * max(0.0, full_gain)
        fair_fee_pct = fee_frac * max(0.0, post_gain)
        equalization_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            full_period_gain_pct=full_gain,
            fee_frac=fee_frac,
            post_entry_gain_pct=post_gain,
            pre_entry_gain_pct=pre_entry_gain_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            equalization_gap_pct=equalization_gap_pct,
            entry_fraction=entry_fraction,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, full_gain: float, gap: float, fee_charged: float,
        entry_fraction: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # post-entry / pre-entry / fair geometry is unknown on the override path →
        # report None; net return can not be derived without post_entry_gain, so
        # net-negative / full-pre-entry flags / ratio fall back to the gap share.
        return self._finish(
            token=token,
            full_period_gain_pct=full_gain,
            fee_frac=None,
            post_entry_gain_pct=None,
            pre_entry_gain_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            equalization_gap_pct=gap,
            entry_fraction=entry_fraction,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        full_period_gain_pct: float,
        fee_frac: Optional[float],
        post_entry_gain_pct: Optional[float],
        pre_entry_gain_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        equalization_gap_pct: float,
        entry_fraction: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the fee charged on pre-entry gains (kept for family
        # consistency with the headline-honesty family).
        overstatement_pct = equalization_gap_pct

        # Net return: only computable when post-entry geometry is known.
        if post_entry_gain_pct is not None:
            net_return_after_fee_pct = post_entry_gain_pct - fee_charged_pct
            net_return_fair_pct = post_entry_gain_pct - fair_fee_pct
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
            # Override path: post-entry geometry unknown. Treat realisation via the
            # fee-on-pre-entry share as the proxy below; flag as not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-pre-entry fraction — the share of the charged fee that
        # landed on gains that accrued before the subscriber entered.
        if fee_charged_pct > EPS:
            fee_on_pre_entry_fraction = _clamp(
                equalization_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_pre_entry_fraction = 0.0

        # On the override path, with no post-entry geometry, anchor the realisation
        # on (1 - fee_on_pre_entry_fraction): the share of the fee that fell on the
        # post-entry gain is the share the subscriber "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_pre_entry_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_pre_entry_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_pre_entry_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            post_entry_gain_pct,
            pre_entry_gain_pct,
            full_period_gain_pct,
            entry_fraction,
            used_override,
        )

        return {
            "token": token,
            "full_period_gain_pct": round(full_period_gain_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "post_entry_gain_pct": (
                round(post_entry_gain_pct, 4)
                if post_entry_gain_pct is not None else None),
            "pre_entry_gain_pct": (
                round(pre_entry_gain_pct, 4)
                if pre_entry_gain_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "equalization_gap_pct": round(equalization_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_pre_entry_fraction": round(fee_on_pre_entry_fraction, 4),
            "net_is_negative": net_is_negative,
            "entry_fraction_of_period": (
                round(entry_fraction, 4) if entry_fraction is not None else None),
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
        fee_on_pre_entry_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the fee was charged on gains the subscriber actually
        earned: the depositor keeps the post-entry return he participated in. Two
        components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the fair
            net return that survives the full-period fee,
          * fee-base penalty = clamp(1 − fee_on_pre_entry_fraction, 0, 1) —
            penalises a large share of the fee being charged on pre-entry gains.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        subscriber keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_pre_entry_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_pre_entry_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole post-entry return (or more).
            return "SEVERE_EQUALIZATION_GAP"
        if fee_on_pre_entry_fraction <= CLEAN_FRACTION:
            return "CLEAN_FULLY_EQUALIZED"
        if fee_on_pre_entry_fraction <= MILD_FRACTION:
            return "MILD_EQUALIZATION_GAP"
        if fee_on_pre_entry_fraction <= MODERATE_FRACTION:
            return "MODERATE_EQUALIZATION_GAP"
        return "SEVERE_EQUALIZATION_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_NO_EQUALIZATION"
        if classification == "CLEAN_FULLY_EQUALIZED":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_EQUALIZATION_GAP":
            return "MINOR_EQUALIZATION_GAP"
        if classification == "MODERATE_EQUALIZATION_GAP":
            return "DEMAND_EQUALIZATION_ACCOUNTING"
        # SEVERE_EQUALIZATION_GAP
        return "AVOID_NO_EQUALIZATION"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        post_entry_gain_pct: Optional[float],
        pre_entry_gain_pct: Optional[float],
        full_period_gain_pct: float,
        entry_fraction: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_FULLY_EQUALIZED":
            flags.append("CLEAN_FULL_EQUALIZATION")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (entry_fraction is not None
                and entry_fraction >= LATE_SUBSCRIPTION_FRACTION):
            flags.append("LATE_SUBSCRIPTION")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if pre_entry_gain_pct is not None and pre_entry_gain_pct > 0.0:
                flags.append("FEE_ON_PRE_ENTRY_GAINS")
            if (post_entry_gain_pct is not None
                    and post_entry_gain_pct <= 0.0
                    and full_period_gain_pct > 0.0):
                flags.append("FULL_PRE_ENTRY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "full_period_gain_pct": None,
            "performance_fee_pct": None,
            "post_entry_gain_pct": None,
            "pre_entry_gain_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "equalization_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_pre_entry_fraction": None,
            "net_is_negative": False,
            "entry_fraction_of_period": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_NO_EQUALIZATION",
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
                "worst_equalization_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = entered clean / fee fair → highest score is the cleanest
        # vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_equalization_vault": by_score[0]["token"],
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
            # CLEAN_FULLY_EQUALIZED: post-entry ≈ full → entered at the start, no
            # pre-entry gain, fee was effectively fair.
            "vault": "USDC-Vault-CleanEqualized",
            "full_period_gain_pct": 18.0,
            "post_entry_gain_pct": 18.0,
            "performance_fee_pct": 20.0,
            "entry_fraction_of_period": 0.0,
        },
        {
            # MODERATE_EQUALIZATION_GAP: full 16, post-entry 8 → ~half the fee was
            # charged on pre-entry gains (fee_on_pre_entry ~ 0.5).
            "vault": "stETH-Vault-ModerateGap",
            "full_period_gain_pct": 16.0,
            "post_entry_gain_pct": 8.0,
            "performance_fee_pct": 20.0,
            "entry_fraction_of_period": 0.5,
        },
        {
            # SEVERE_EQUALIZATION_GAP (net negative): the subscriber entered above
            # the period high and his post-entry return is negative, yet the fee is
            # still charged on the full-period gain → fair net return is negative.
            "vault": "GOV-Vault-SevereGap",
            "full_period_gain_pct": 12.0,
            "post_entry_gain_pct": -3.0,
            "performance_fee_pct": 50.0,
            "entry_fraction_of_period": 0.9,
        },
        {
            # Override path: an equalization gap supplied directly with the fee
            # charged → fee_on_pre_entry = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "full_period_gain_pct": 24.0,
            "equalization_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no full-period gain supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "post_entry_gain_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1210 Vault Performance-Fee Subscription-Timing "
            "Equalization-Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeSubscriptionTimingEqualizationGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
