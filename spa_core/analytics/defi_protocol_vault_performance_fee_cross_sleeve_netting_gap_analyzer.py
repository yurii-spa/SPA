"""
MP-1209: DeFiProtocolVaultPerformanceFeeCrossSleeveNettingGapAnalyzer
====================================================================
Advisory/read-only analytics module.

A multi-strategy ("multi-sleeve") vault charges a PERFORMANCE fee on the GROSS
gains of its WINNING sleeves WITHOUT netting the LOSSES of its losing sleeves in
the same fee period. The depositor therefore pays a performance fee on sleeve
winners even when the vault's NET return across all sleeves is far lower (or
negative). The fee is levied on un-netted gross winners; the FAIR fee would be
levied only on the vault's netted portfolio return:

    fee_frac            = clamp(performance_fee_pct / 100, 0, 1)
    offset_loss_pct     = max(0, gross_winner_gain_pct - net_portfolio_gain_pct)
    fee_charged_pct     = fee_frac * max(0, gross_winner_gain_pct)
    fair_fee_pct        = fee_frac * max(0, net_portfolio_gain_pct)
    netting_gap_pct     = max(0, fee_charged_pct - fair_fee_pct)
                        (= fee charged on winners that were offset by other
                         sleeves' losses, never netted out)
    net_return_after_fee_pct = net_portfolio_gain_pct - fee_charged_pct
    net_return_fair_pct      = net_portfolio_gain_pct - fair_fee_pct
    overstatement_pct        = netting_gap_pct
    fee_on_unnetted_fraction = clamp(netting_gap_pct / fee_charged_pct, 0, 1)
    realization_ratio        = clamp(net_return_after_fee / net_return_fair, 0, 1)

The headline says "the manager skims only the upside", but with no cross-sleeve
loss netting the fee is taken on the gross winners while the losing sleeves drag
the netted return down — so a chunk of the fee was charged on gains that the
portfolio as a whole never kept. The scale-free fee_on_unnetted_fraction is the
share of the charged fee that landed on un-netted (offset) gains; it is the basis
of the classification. When the netted portfolio return equals (or exceeds) the
gross winner gain there were no offsetting losses and the fee was fair (HIGHER
score). When the losing sleeves fully offset the winners (or the net return goes
negative after the fee), the fee was charged almost entirely on gains the vault
did not keep (LOWER score).

HIGHER score = sleeves were all net winners (net ≈ gross winners), the fee was
effectively fair, full cross-sleeve netting would change nothing. LOWER score = a
large share of the fee was charged on winners offset by other sleeves' losses, or
the net return goes negative after the fee.

Override path (when netting_gap_pct is supplied directly, finite, AND a valid
POSITIVE gross_winner_gain_pct and POSITIVE fee_charged_pct are present): take the
gap verbatim (negative → magnitude) and skip the net/offset geometry —
fee_on_unnetted_fraction and the metrics are computed the same way:

    fee_on_unnetted_fraction = clamp(netting_gap_pct / fee_charged_pct, 0, 1)

(On the override path the net / offset / fair geometry is not known → those fields
are reported as None, and the geometry-only flags FEE_ON_OFFSET_GAINS /
FULL_OFFSET / NET_NEGATIVE_AFTER_FEE are NOT raised; realization_ratio is anchored
to (1 - fee_on_unnetted_fraction).)

Distinct from:
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET over TIME for a SINGLE NAV series (does the fee wait
    for the prior peak to recover). HERE it is a CROSS-SECTIONAL netting gap across
    CONCURRENT sleeves in ONE fee period, independent of any temporal peak.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path of ONE series (fee on
    up-legs, no refund on down-legs over time). HERE there is no path / no time
    series: it is the simultaneous offset of winning sleeves by losing sleeves.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises. HERE it is what the fee is assessed ACROSS
    (gross winners un-netted vs the netted portfolio), regardless of frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices the
    fee charged on BETA (benchmark-level return over a too-low hurdle) vs ALPHA.
    HERE it is the fee charged on GROSS sleeve winners not netted against sleeve
    LOSSES, independent of any benchmark / hurdle.
  * defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer —
    that prices a fee on an UNREALIZED peak mark of ONE position that later
    REVERSED with no clawback (a TEMPORAL reversal). HERE the offset is
    CROSS-SECTIONAL and CONTEMPORANEOUS: losing sleeves in the SAME period, not a
    later reversal of one mark.
  * defi_protocol_vault_net_of_loss_yield_realization_analyzer — that nets a
    headline YIELD stream against a SEPARATE missed LOSS stream (IL / bad debt) at
    the NAV level. HERE the axis is the PERFORMANCE FEE's assessment base: gross
    sleeve winners un-netted against concurrent sleeve losses, NOT a yield-vs-loss
    NAV reconciliation.

The novel axis here: a performance fee charged on GROSS winning sleeves without
netting concurrent LOSING sleeves in the same fee period (no cross-sleeve loss
offset).

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
    "data", "vault_performance_fee_cross_sleeve_netting_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_unnetted_fraction in [0, 1]
# (= netting_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly netted (no offsetting losses)
MILD_FRACTION = 0.20         # at/below → mild netting gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe netting gap

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
    net-portfolio-gain field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeCrossSleeveNettingGapAnalyzer:
    """
    Measures the gap between the performance fee a multi-sleeve vault charges on
    the GROSS gains of its WINNING sleeves and the FAIR fee it would charge on the
    vault's NETTED portfolio return, and the share of the charged fee that
    therefore landed on winners OFFSET by other sleeves' losses (no cross-sleeve
    netting).

        fee_frac                 = clamp(performance_fee_pct / 100, 0, 1)
        offset_loss_pct          = max(0, gross_winner_gain - net_portfolio_gain)
        fee_charged_pct          = fee_frac * max(0, gross_winner_gain)
        fair_fee_pct             = fee_frac * max(0, net_portfolio_gain)
        netting_gap_pct          = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct = net_portfolio_gain - fee_charged
        net_return_fair_pct      = net_portfolio_gain - fair_fee
        overstatement_pct        = netting_gap_pct
        fee_on_unnetted_fraction = clamp(netting_gap / fee_charged, 0, 1)
        realization_ratio        = clamp(net_after_fee / net_fair, 0, 1)

    The fee is charged on the gross winning sleeves; the fair fee would be charged
    only on the netted portfolio return. When the netted return equals (or exceeds)
    the gross winners there were no offsetting losses (CLEAN_FULLY_NETTED). When the
    losing sleeves offset the winners and there is no cross-sleeve netting, a large
    share of the fee was charged on offset gains (MODERATE / SEVERE netting gap),
    and if the fee exceeds the netted return the net return goes negative.

    HIGHER score = sleeves were all net winners (net ≈ gross winners), the fee was
    effectively fair, full netting would change nothing. LOWER score = a large share
    of the fee was charged on winners offset by sleeve losses, or the net return
    goes negative after the fee.

    Per-position input dict fields:
        vault / token            : str
        gross_winner_gain_pct    : float — aggregate GROSS gain of the WINNING
                                   sleeves on which the fee is assessed. REQUIRED,
                                   must be a finite POSITIVE number (else
                                   INSUFFICIENT_DATA).
        net_portfolio_gain_pct   : float — the NETTED return across ALL sleeves
                                   (finite; may be < gross winners; may be negative;
                                   default 0.0 = winners fully offset).
        performance_fee_pct      : float — performance-fee rate % (REQUIRED finite,
                                   clamped into 0..100; non-finite →
                                   INSUFFICIENT_DATA on the main path).
        sleeve_count             : int — OPTIONAL informational count of sleeves.
        netting_gap_pct          : float — OPTIONAL direct override of the netting
                                   gap (the fee charged on offset gains). When
                                   supplied (finite; negative → magnitude) AND a
                                   valid POSITIVE gross_winner_gain_pct and POSITIVE
                                   fee_charged_pct are present, take this gap
                                   directly and skip the net / offset geometry
                                   (override path; geometry → None).
        fee_charged_pct          : float — OPTIONAL, only used on the override path
                                   as the denominator for fee_on_unnetted_fraction
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

        # The gross winner gain is required and must be finite & positive.
        winners = _coerce_num(p.get("gross_winner_gain_pct"))
        if winners is None or not math.isfinite(winners) or winners <= 0.0:
            return self._insufficient(token)

        sleeve_count = _coerce_count(p.get("sleeve_count"))

        # Override path: a direct netting gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("netting_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, winners, abs(gap_o), fee_charged_o, sleeve_count)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, winners, fee_pct, sleeve_count)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, winners: float, fee_pct: float,
        sleeve_count: Optional[int],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net portfolio gain may legitimately be negative (winners fully offset).
        net_gain = _coerce_signed(p.get("net_portfolio_gain_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        offset_loss_pct = max(0.0, winners - net_gain)
        fee_charged_pct = fee_frac * max(0.0, winners)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        netting_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_winner_gain_pct=winners,
            fee_frac=fee_frac,
            net_portfolio_gain_pct=net_gain,
            offset_loss_pct=offset_loss_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            netting_gap_pct=netting_gap_pct,
            sleeve_count=sleeve_count,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, winners: float, gap: float, fee_charged: float,
        sleeve_count: Optional[int],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net / offset / fair geometry is unknown on the override path → report
        # None; net return can not be derived without net_portfolio_gain, so
        # net-negative / full-offset flags / ratio fall back to the gap share.
        return self._finish(
            token=token,
            gross_winner_gain_pct=winners,
            fee_frac=None,
            net_portfolio_gain_pct=None,
            offset_loss_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            netting_gap_pct=gap,
            sleeve_count=sleeve_count,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_winner_gain_pct: float,
        fee_frac: Optional[float],
        net_portfolio_gain_pct: Optional[float],
        offset_loss_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        netting_gap_pct: float,
        sleeve_count: Optional[int],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the fee charged on offset gains (kept for family
        # consistency with the headline-honesty family).
        overstatement_pct = netting_gap_pct

        # Net return: only computable when net geometry is known.
        if net_portfolio_gain_pct is not None:
            net_return_after_fee_pct = net_portfolio_gain_pct - fee_charged_pct
            net_return_fair_pct = net_portfolio_gain_pct - fair_fee_pct
            net_is_negative = net_return_after_fee_pct < 0.0
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
            # Override path: net geometry unknown. Treat realisation via the
            # fee-on-unnetted share as the proxy below; flag as not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-unnetted fraction — the share of the charged fee that
        # landed on winners offset by other sleeves' losses.
        if fee_charged_pct > EPS:
            fee_on_unnetted_fraction = _clamp(
                netting_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_unnetted_fraction = 0.0

        # On the override path, with no net geometry, anchor the realisation on
        # (1 - fee_on_unnetted_fraction): the share of the fee that fell on the
        # net-kept gain is the share the depositor "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_unnetted_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_unnetted_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_unnetted_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_portfolio_gain_pct,
            offset_loss_pct,
            gross_winner_gain_pct,
            sleeve_count,
            used_override,
        )

        return {
            "token": token,
            "gross_winner_gain_pct": round(gross_winner_gain_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_portfolio_gain_pct": (
                round(net_portfolio_gain_pct, 4)
                if net_portfolio_gain_pct is not None else None),
            "offset_loss_pct": (
                round(offset_loss_pct, 4)
                if offset_loss_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "netting_gap_pct": round(netting_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_unnetted_fraction": round(fee_on_unnetted_fraction, 4),
            "net_is_negative": net_is_negative,
            "sleeve_count": sleeve_count,
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
        fee_on_unnetted_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the fee was charged on gains the portfolio actually kept:
        the depositor keeps the net return the netted sleeves produced. Two
        components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the fair
            net return that survives the un-netted fee,
          * fee-base penalty = clamp(1 − fee_on_unnetted_fraction, 0, 1) —
            penalises a large share of the fee being charged on offset gains.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_unnetted_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_unnetted_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole netted return (or more).
            return "SEVERE_NETTING_GAP"
        if fee_on_unnetted_fraction <= CLEAN_FRACTION:
            return "CLEAN_FULLY_NETTED"
        if fee_on_unnetted_fraction <= MILD_FRACTION:
            return "MILD_NETTING_GAP"
        if fee_on_unnetted_fraction <= MODERATE_FRACTION:
            return "MODERATE_NETTING_GAP"
        return "SEVERE_NETTING_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_NO_NETTING"
        if classification == "CLEAN_FULLY_NETTED":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_NETTING_GAP":
            return "MINOR_NETTING_GAP"
        if classification == "MODERATE_NETTING_GAP":
            return "DEMAND_CROSS_SLEEVE_NETTING"
        # SEVERE_NETTING_GAP
        return "AVOID_NO_NETTING"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_portfolio_gain_pct: Optional[float],
        offset_loss_pct: Optional[float],
        gross_winner_gain_pct: float,
        sleeve_count: Optional[int],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_FULLY_NETTED":
            flags.append("CLEAN_FULL_NETTING")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if sleeve_count is not None and sleeve_count >= 4:
            flags.append("MANY_SLEEVES")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if offset_loss_pct is not None and offset_loss_pct > 0.0:
                flags.append("FEE_ON_OFFSET_GAINS")
            if (net_portfolio_gain_pct is not None
                    and net_portfolio_gain_pct <= 0.0
                    and gross_winner_gain_pct > 0.0):
                flags.append("FULL_OFFSET")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_winner_gain_pct": None,
            "performance_fee_pct": None,
            "net_portfolio_gain_pct": None,
            "offset_loss_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "netting_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_unnetted_fraction": None,
            "net_is_negative": False,
            "sleeve_count": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_NO_NETTING",
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
                "worst_netting_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = sleeves netted clean → highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_netting_vault": by_score[0]["token"],
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
            # CLEAN_FULLY_NETTED: net ≈ gross winners → no offsetting losses, fee
            # was effectively fair.
            "vault": "USDC-MultiSleeve-CleanNetted",
            "gross_winner_gain_pct": 18.0,
            "net_portfolio_gain_pct": 18.0,
            "performance_fee_pct": 20.0,
            "sleeve_count": 3,
        },
        {
            # MODERATE_NETTING_GAP: winners 16, net 8 → ~half the fee was charged on
            # winners offset by losing sleeves (fee_on_unnetted ~ 0.5).
            "vault": "stETH-MultiSleeve-ModerateGap",
            "gross_winner_gain_pct": 16.0,
            "net_portfolio_gain_pct": 8.0,
            "performance_fee_pct": 20.0,
            "sleeve_count": 4,
        },
        {
            # SEVERE_NETTING_GAP (net negative): a big fee on gross winners while the
            # losing sleeves drive the net return negative → fee eats more than the
            # net return.
            "vault": "GOV-MultiSleeve-SevereGap",
            "gross_winner_gain_pct": 12.0,
            "net_portfolio_gain_pct": 1.0,
            "performance_fee_pct": 50.0,
            "sleeve_count": 5,
        },
        {
            # Override path: a netting gap supplied directly with the fee charged →
            # fee_on_unnetted = 5/12 ≈ 0.4167 → MODERATE_NETTING_GAP.
            "vault": "LST-MultiSleeve-OverrideGap",
            "gross_winner_gain_pct": 24.0,
            "netting_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross winner gain supplied.
            "vault": "MYSTERY-MultiSleeve-NoData",
            "performance_fee_pct": 20.0,
            "net_portfolio_gain_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1209 Vault Performance-Fee Cross-Sleeve "
            "Netting-Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeCrossSleeveNettingGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
