"""
MP-1212: DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault advertises a HURDLE RATE: the depositor is told that the first `hurdle` %
of return is EXEMPT from the performance fee, and the fee is charged only on the
EXCESS of the gross return over the hurdle. Under a SOFT hurdle with a CATCH-UP
clause, that exemption is CLAWED BACK. The moment the gross return clears the
hurdle, the manager takes a CATCH-UP slice (often 100%) of the band of return
immediately above the hurdle, until the manager has collected the FULL fee_frac
of the WHOLE gross return — INCLUDING the hurdle band the depositor thought was
protected. The depositor ends up paying the performance fee as though the hurdle
had never existed: the hurdle "protection" is revoked (clawed back).

    fee_frac          = clamp(performance_fee_pct / 100, 0, 1)
    hurdle            = max(0, hurdle_rate_pct)        (default 0 → no hurdle)
    gross             = gross_return_pct  (REQUIRED, finite > 0 else INSUFFICIENT)
    excess            = max(0, gross - hurdle)
    catch_up_rate     = clamp(catch_up_rate_pct / 100, 0, 1)   (default 1.0 = 100%)

    # the depositor's BELIEF: a HARD hurdle, fee only on the excess
    fair_fee_pct      = fee_frac * excess

    # the SOFT catch-up reality
    if catch_up_rate > fee_frac:
        x_full = fee_frac * hurdle / (catch_up_rate - fee_frac)
    else:
        x_full = inf      # catch-up never overtakes the straight fee → never full
    if excess >= x_full:                       # full catch-up: hurdle fully clawed
        fee_charged_pct = fee_frac * gross
    else:                                       # partial catch-up
        fee_charged_pct = min(catch_up_rate * excess, fee_frac * gross)
    fee_charged_pct   = clamp(fee_charged_pct, 0, fee_frac * gross)

    catchup_gap_pct   = max(0, fee_charged - fair_fee)
                      (= the fee clawed back out of the hurdle exemption)
    hurdle_value_pct  = fee_frac * min(hurdle, gross)
                      (= the fee the hurdle was supposed to exempt = the
                       depositor's expected saving; this is the CEILING for the gap)
    catchup_recoup_fraction = clamp(catchup_gap / hurdle_value, 0, 1)
                      (scale-free, the BASIS of the classification)
    net_return_after_fee_pct = gross - fee_charged
    net_return_fair_pct      = gross - fair_fee
    net_is_negative          = net_return_fair_pct < 0
    overstatement_pct        = catchup_gap_pct
    realization_ratio        = clamp(net_after / net_fair, 0, 1)

The headline says "the first `hurdle` % is yours, fee only above it", but under a
soft hurdle with a catch-up clause the manager claws that exemption back: once the
gross clears the hurdle the catch-up band collects the fee on the hurdle slice too,
until the manager has the full fee_frac of the whole gross return. The scale-free
catchup_recoup_fraction is the share of the hurdle's promised exemption that the
catch-up clause clawed back; it is the basis of the classification. When there is
no hurdle (hurdle = 0) there is nothing to claw back and the fee is clean. When the
catch-up rate is high and the gross clears the catch-up band, the WHOLE hurdle
exemption is revoked (recoup ≈ 1).

HIGHER score = the hurdle exemption was honoured (a hard hurdle; recoup ≈ 0),
nothing to fix. LOWER score = a large share of the hurdle exemption was clawed back
by the catch-up clause, or the fair net return goes negative.

Override path (when catchup_gap_pct is supplied directly, finite, AND a valid
POSITIVE gross_return_pct and POSITIVE fee_charged_pct are present): take the gap
verbatim (negative → magnitude, capped at fee_charged) and skip the
hurdle / excess / fair / net / hurdle_value geometry. Because the hurdle_value
ceiling is NOT known on the override path, the catchup_recoup_fraction is computed
against the FEE CHARGED (a proxy denominator) rather than against hurdle_value:

    catchup_recoup_fraction = clamp(catchup_gap_pct / fee_charged_pct, 0, 1)
    realization_ratio       = clamp(1 - catchup_recoup_fraction, 0, 1)

(On the override path the hurdle / excess / fair / net / hurdle_value geometry is
not known → those fields are reported as None, and the geometry-only flags
FEE_ON_HURDLE_BAND / FULL_CATCHUP / HIGH_CATCHUP_RATE / NET_NEGATIVE_AFTER_FEE are
NOT raised.)

Distinct from:
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET over TIME for the WHOLE NAV series. HERE it is the
    static SOFT-HURDLE CATCH-UP claw-back of the hurdle exemption for a SINGLE fee
    period, not a high-water-mark reset over time.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path. HERE there is no path:
    it is the static catch-up claw-back of the advertised hurdle exemption.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises. HERE it is the SOFT-HURDLE CATCH-UP clause
    revoking the hurdle exemption, regardless of frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices the
    fee charged on BETA (a benchmark-level / too-low hurdle) vs ALPHA: whether the
    hurdle itself is a fair benchmark. HERE the hurdle level is taken as given and
    the axis is the SOFT-HURDLE CATCH-UP clause that claws BACK the hurdle's own
    exemption — the catch-up revoking the hurdle, NOT the benchmark level of it.
  * defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer —
    that prices a fee on an UNREALIZED peak mark of ONE position that later
    REVERSED with no clawback (a TEMPORAL reversal of a mark). HERE the claw-back
    is of the HURDLE EXEMPTION via the catch-up clause within a single period, not
    a later reversal of an unrealized mark.
  * defi_protocol_vault_performance_fee_cross_sleeve_netting_gap_analyzer — that
    nets winning sleeves against concurrent losing sleeves (a CROSS-SECTIONAL
    offset). HERE the axis is the SOFT-HURDLE CATCH-UP claw-back within a single
    sleeve, not a cross-sleeve netting.
  * defi_protocol_vault_performance_fee_subscription_timing_equalization_gap_analyzer
    — that prices a SUBSCRIBER-RELATIVE gap between the full-period base and the
    post-entry base (entry timing / equalization). HERE the gap is the CATCH-UP
    claw-back of the hurdle exemption, independent of any subscriber's entry timing.
  * defi_protocol_vault_performance_fee_management_fee_base_gap_analyzer — that
    prices the performance-fee BASE being GROSS-OF-MANAGEMENT rather than
    NET-OF-MANAGEMENT (a fee-on-fee stacking with the AUM fee). HERE the axis is
    the SOFT-HURDLE CATCH-UP clause revoking the hurdle's own exemption, independent
    of the management fee.

The novel axis here: the SOFT-HURDLE CATCH-UP CLAUSE that claws BACK the hurdle's
advertised performance-fee EXEMPTION — once the gross clears the hurdle the
catch-up band collects the fee on the hurdle slice too, until the manager has the
full fee on the whole gross return, as though the hurdle had never existed.

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
    "data", "vault_performance_fee_catch_up_clause_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free catchup_recoup_fraction in [0, 1]
# (= catchup_gap_pct / hurdle_value_pct).
CLEAN_FRACTION = 0.05        # at/below → the hurdle exemption was honoured
MILD_FRACTION = 0.20         # at/below → mild catch-up gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe catch-up gap

# High-catch-up-rate flag threshold on catch_up_rate_pct.
HIGH_CATCHUP_RATE_PCT = 100.0

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
    not interpretable. Identical to _coerce_num; kept as a named alias for fields
    that may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges under a SOFT
    hurdle with a CATCH-UP clause and the FAIR fee the depositor was told a HARD
    hurdle would charge (only on the excess over the hurdle), and the share of the
    hurdle's advertised exemption that the catch-up clause therefore CLAWS BACK.

        fee_frac          = clamp(performance_fee_pct / 100, 0, 1)
        hurdle            = max(0, hurdle_rate_pct)
        excess            = max(0, gross - hurdle)
        catch_up_rate     = clamp(catch_up_rate_pct / 100, 0, 1)   (default 1.0)
        fair_fee_pct      = fee_frac * excess              (depositor's belief)
        # soft catch-up:
        x_full = fee_frac*hurdle/(catch_up_rate-fee_frac) if catch_up_rate>fee_frac
                 else inf
        fee_charged_pct = fee_frac*gross           if excess >= x_full (full)
                          else min(catch_up_rate*excess, fee_frac*gross) (partial)
        catchup_gap_pct   = max(0, fee_charged - fair_fee)
        hurdle_value_pct  = fee_frac * min(hurdle, gross)   (ceiling for the gap)
        catchup_recoup_fraction = clamp(catchup_gap / hurdle_value, 0, 1)
        net_return_after_fee_pct = gross - fee_charged
        net_return_fair_pct      = gross - fair_fee
        realization_ratio        = clamp(net_after / net_fair, 0, 1)

    When there is no hurdle (hurdle = 0) there is nothing to exempt and nothing to
    claw back → CLEAN_HARD_HURDLE. When the catch-up rate is high and the gross
    clears the catch-up band, the whole hurdle exemption is revoked (recoup ≈ 1 →
    SEVERE), and if the fair net return goes negative the position is SEVERE.

    HIGHER score = the hurdle exemption was honoured (a hard hurdle; recoup ≈ 0),
    nothing to fix. LOWER score = a large share of the hurdle exemption was clawed
    back by the catch-up clause, or the fair net return goes negative.

    Per-position input dict fields:
        vault / token            : str
        gross_return_pct         : float — the GROSS return on which the fee is
                                   assessed. REQUIRED, must be a finite POSITIVE
                                   number (else INSUFFICIENT_DATA).
        performance_fee_pct      : float — performance-fee rate % (REQUIRED finite,
                                   clamped into 0..100; non-finite →
                                   INSUFFICIENT_DATA on the main path).
        hurdle_rate_pct          : float — OPTIONAL advertised hurdle rate %
                                   (clamped ≥ 0; default 0.0 = no hurdle → nothing
                                   to claw back → CLEAN).
        catch_up_rate_pct        : float — OPTIONAL catch-up rate % (clamped into
                                   0..100; default 100.0 = the manager takes the
                                   whole catch-up band); ≥ HIGH_CATCHUP_RATE_PCT
                                   raises HIGH_CATCHUP_RATE.
        catchup_gap_pct          : float — OPTIONAL direct override of the catch-up
                                   gap (the fee clawed back out of the hurdle
                                   exemption). When supplied (finite; negative →
                                   magnitude) AND a valid POSITIVE gross_return_pct
                                   and POSITIVE fee_charged_pct are present, take
                                   this gap directly and skip the hurdle / excess /
                                   fair / net / hurdle_value geometry (override
                                   path; geometry → None). On the override path the
                                   catchup_recoup_fraction denominator is the FEE
                                   CHARGED, not hurdle_value.
        fee_charged_pct          : float — OPTIONAL, only used on the override path
                                   as the denominator for catchup_recoup_fraction
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

        catch_up_rate_pct = _coerce_num(p.get("catch_up_rate_pct"))

        # Override path: a direct catch-up gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("catchup_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, catch_up_rate_pct)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, gross_gain, fee_pct, catch_up_rate_pct)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        catch_up_rate_pct: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        hurdle_in = _coerce_num(p.get("hurdle_rate_pct"))
        hurdle = max(0.0, hurdle_in) if hurdle_in is not None else 0.0

        excess = max(0.0, gross_gain - hurdle)

        # catch-up rate: default 100% if not supplied / non-finite.
        if catch_up_rate_pct is not None and math.isfinite(catch_up_rate_pct):
            catch_up_rate = _clamp(catch_up_rate_pct / 100.0, 0.0, 1.0)
        else:
            catch_up_rate = 1.0

        # depositor's belief: a HARD hurdle, fee only on the excess.
        fair_fee_pct = fee_frac * excess

        # soft catch-up: the catch-up band collects fee until the manager has the
        # full fee_frac of the whole gross return.
        full_fee = fee_frac * max(0.0, gross_gain)
        if catch_up_rate > fee_frac:
            x_full = fee_frac * hurdle / (catch_up_rate - fee_frac)
        else:
            x_full = float("inf")

        if excess >= x_full:
            # full catch-up: the hurdle exemption is fully clawed back.
            fee_charged_pct = full_fee
        else:
            # partial catch-up.
            fee_charged_pct = min(catch_up_rate * excess, full_fee)
        fee_charged_pct = _clamp(fee_charged_pct, 0.0, full_fee)

        catchup_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)
        hurdle_value_pct = fee_frac * min(hurdle, gross_gain)

        return self._finish(
            token=token,
            gross_return_pct=gross_gain,
            fee_frac=fee_frac,
            hurdle_rate_pct=hurdle,
            excess_return_pct=excess,
            catch_up_rate_pct=catch_up_rate_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            catchup_gap_pct=catchup_gap_pct,
            hurdle_value_pct=hurdle_value_pct,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        catch_up_rate_pct: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # hurdle / excess / fair / net / hurdle_value geometry is unknown on the
        # override path → report None; the recoup fraction falls back to the gap
        # share of the fee charged (a proxy denominator).
        return self._finish(
            token=token,
            gross_return_pct=gross_gain,
            fee_frac=None,
            hurdle_rate_pct=None,
            excess_return_pct=None,
            catch_up_rate_pct=catch_up_rate_pct,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            catchup_gap_pct=gap,
            hurdle_value_pct=None,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_return_pct: float,
        fee_frac: Optional[float],
        hurdle_rate_pct: Optional[float],
        excess_return_pct: Optional[float],
        catch_up_rate_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        catchup_gap_pct: float,
        hurdle_value_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the fee clawed back out of the hurdle exemption.
        overstatement_pct = catchup_gap_pct

        # Net return: only computable when the hurdle geometry is known.
        if hurdle_value_pct is not None:
            net_return_after_fee_pct = gross_return_pct - fee_charged_pct
            net_return_fair_pct = gross_return_pct - fair_fee_pct
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                # Mirror the template edge: when the fair net is non-positive, the
                # ratio is 1.0 only if the charged net still clears the fair net and
                # is itself non-negative, else 0.0.
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
            # Scale-free recoup fraction against the hurdle_value ceiling.
            if hurdle_value_pct > EPS:
                catchup_recoup_fraction = _clamp(
                    catchup_gap_pct / hurdle_value_pct, 0.0, 1.0)
            else:
                catchup_recoup_fraction = 0.0
        else:
            # Override path: hurdle geometry unknown → no net / ceiling. Anchor the
            # recoup on the fee-charged share (proxy denominator).
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            if fee_charged_pct > EPS:
                catchup_recoup_fraction = _clamp(
                    catchup_gap_pct / fee_charged_pct, 0.0, 1.0)
            else:
                catchup_recoup_fraction = 0.0
            realization_ratio = _clamp(
                1.0 - catchup_recoup_fraction, 0.0, 1.0)

        classification = self._classify(
            catchup_recoup_fraction, net_is_negative)
        score = self._score(
            realization_ratio, catchup_recoup_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            catchup_gap_pct,
            catchup_recoup_fraction,
            hurdle_rate_pct,
            hurdle_value_pct,
            gross_return_pct,
            catch_up_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_return_pct": round(gross_return_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "hurdle_rate_pct": (
                round(hurdle_rate_pct, 4)
                if hurdle_rate_pct is not None else None),
            "excess_return_pct": (
                round(excess_return_pct, 4)
                if excess_return_pct is not None else None),
            "catch_up_rate_pct": (
                round(catch_up_rate_pct, 4)
                if catch_up_rate_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "catchup_gap_pct": round(catchup_gap_pct, 4),
            "hurdle_value_pct": (
                round(hurdle_value_pct, 4)
                if hurdle_value_pct is not None else None),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "catchup_recoup_fraction": round(catchup_recoup_fraction, 4),
            "net_is_negative": net_is_negative,
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
        catchup_recoup_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the hurdle exemption was honoured (a hard hurdle): the
        depositor keeps the return the hurdle promised to exempt from the fee. Two
        components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the fair
            net return that survives the catch-up fee,
          * recoup penalty = clamp(1 − catchup_recoup_fraction, 0, 1) — penalises a
            large share of the hurdle exemption being clawed back.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        recoup_penalty = _clamp(1.0 - catchup_recoup_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * recoup_penalty, 0.0, 100.0)

    def _classify(
        self, catchup_recoup_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole gross return (or more) on the fair base.
            return "SEVERE_CATCHUP_GAP"
        if catchup_recoup_fraction <= CLEAN_FRACTION:
            return "CLEAN_HARD_HURDLE"
        if catchup_recoup_fraction <= MILD_FRACTION:
            return "MILD_CATCHUP_GAP"
        if catchup_recoup_fraction <= MODERATE_FRACTION:
            return "MODERATE_CATCHUP_GAP"
        return "SEVERE_CATCHUP_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_CATCHUP_CLAUSE"
        if classification == "CLEAN_HARD_HURDLE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_CATCHUP_GAP":
            return "MINOR_CATCHUP_GAP"
        if classification == "MODERATE_CATCHUP_GAP":
            return "DEMAND_HARD_HURDLE"
        # SEVERE_CATCHUP_GAP
        return "AVOID_CATCHUP_CLAUSE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        catchup_gap_pct: float,
        catchup_recoup_fraction: float,
        hurdle_rate_pct: Optional[float],
        hurdle_value_pct: Optional[float],
        gross_return_pct: float,
        catch_up_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_HARD_HURDLE":
            flags.append("HURDLE_HONOURED")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if catchup_gap_pct > 0.0:
                flags.append("FEE_ON_HURDLE_BAND")
            if (hurdle_value_pct is not None
                    and catchup_recoup_fraction >= 0.999
                    and hurdle_rate_pct is not None and hurdle_rate_pct > 0.0
                    and gross_return_pct > hurdle_rate_pct):
                flags.append("FULL_CATCHUP")
            if (catch_up_rate_pct is not None
                    and catch_up_rate_pct >= HIGH_CATCHUP_RATE_PCT):
                flags.append("HIGH_CATCHUP_RATE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_return_pct": None,
            "performance_fee_pct": None,
            "hurdle_rate_pct": None,
            "excess_return_pct": None,
            "catch_up_rate_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "catchup_gap_pct": None,
            "hurdle_value_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "catchup_recoup_fraction": None,
            "net_is_negative": False,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_CATCHUP_CLAUSE",
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
                "worst_catchup_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = the hurdle exemption was honoured → highest score is the
        # cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_catchup_vault": by_score[0]["token"],
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
            # CLEAN_HARD_HURDLE: a low catch-up rate barely above the straight fee,
            # gross only just clears the hurdle → almost nothing of the hurdle
            # exemption is clawed back (recoup ≈ 0).
            "vault": "USDC-Vault-CleanHardHurdle",
            "gross_return_pct": 10.5,
            "hurdle_rate_pct": 10.0,
            "performance_fee_pct": 20.0,
            "catch_up_rate_pct": 22.0,
        },
        {
            # MODERATE_CATCHUP_GAP: partial catch-up, ~a third to a half of the
            # hurdle exemption clawed back.
            "vault": "stETH-Vault-ModerateCatchup",
            "gross_return_pct": 14.0,
            "hurdle_rate_pct": 8.0,
            "performance_fee_pct": 20.0,
            "catch_up_rate_pct": 30.0,
        },
        {
            # SEVERE_CATCHUP_GAP: full catch-up (100% rate) revokes the WHOLE
            # hurdle exemption (recoup = 1.0) — the depositor pays the fee exactly
            # as though the advertised hurdle had never existed.
            "vault": "GOV-Vault-SevereCatchup",
            "gross_return_pct": 20.0,
            "hurdle_rate_pct": 10.0,
            "performance_fee_pct": 20.0,
            "catch_up_rate_pct": 100.0,
        },
        {
            # Override path: a catch-up gap supplied directly with the fee charged →
            # recoup = 4.8/12 = 0.4 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_return_pct": 24.0,
            "catchup_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross return supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "hurdle_rate_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1212 Vault Performance-Fee Soft-Hurdle Catch-Up Clause "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
